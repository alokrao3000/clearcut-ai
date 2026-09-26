"""Job queue with an inline fallback.

Every unit of deferrable work is a `Job` row plus a handler registered here. With
`CLEARCUT_USE_WORKER=false` (the default) a job runs inline the moment it is enqueued,
so a dev box, the test suite and the current frontend all behave exactly as they did
before M3. With the worker enabled the same handler runs in arq instead.

Handlers take a Session and the job's payload, and return whatever should land in
`Job.result`. They must be safe to run twice: arq retries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app import db  # module, not the factory: tests swap SessionLocal for their own engine
from app.config import get_settings
from app.models import Job, utcnow

log = logging.getLogger(__name__)

Handler = Callable[[Session, dict], dict | None]
_HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return register


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)


def enqueue(session: Session, kind: str, payload: dict, *, project_id: str | None = None,
            subject_id: str | None = None) -> Job:
    """Record the job, then either run it now or hand it to the worker."""
    if kind not in _HANDLERS:
        raise KeyError(f"No handler registered for job kind '{kind}'.")

    job = Job(kind=kind, payload=payload, project_id=project_id, subject_id=subject_id, status="queued")
    session.add(job)
    session.commit()

    settings = get_settings()
    if settings.use_worker:
        try:
            _push(job.id)
            return job
        except Exception as exc:  # noqa: BLE001 - a queue outage must not lose the work
            log.warning("Could not reach Redis (%s); running job %s inline", exc, job.id)

    run_job(job.id)
    session.refresh(job)
    return job


def _push(job_id: str) -> None:
    """Hand the job id to arq. Sync callers only — FastAPI runs them in a worker thread."""
    import asyncio

    from arq.connections import RedisSettings, create_pool

    async def send() -> None:
        redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await redis.enqueue_job("run_job_task", job_id)
        finally:
            await redis.aclose()

    asyncio.run(send())


def run_job(job_id: str) -> None:
    """Execute a job in its own session and record the outcome on the Job row."""
    with db.SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            log.error("Job %s vanished before it ran", job_id)
            return
        if job.status in ("running", "complete"):
            return  # arq retried a job that is already in flight or done

        # A job has no request behind it, so nothing has stamped the tenant on this
        # session. Without this, everything the job audits lands with a null org and
        # disappears from the owning organization's E&O trail.
        if job.project_id:
            from app.models import Project

            project = session.get(Project, job.project_id)
            if project is not None:
                session.info["org_id"] = project.org_id

        job.status, job.started_at = "running", utcnow()
        session.commit()

        try:
            result = _HANDLERS[job.kind](session, dict(job.payload or {}))
        except Exception as exc:  # noqa: BLE001 - the failure belongs on the job row
            session.rollback()
            job = session.get(Job, job_id)
            if job is not None:
                job.status, job.error, job.finished_at = "failed", f"{type(exc).__name__}: {exc}", utcnow()
                session.commit()
            log.exception("Job %s (%s) failed", job_id, job.kind if job else "?")
            return

        job = session.get(Job, job_id)
        if job is not None:
            job.status, job.result, job.finished_at = "complete", result or {}, utcnow()
            session.commit()
