"""arq worker entrypoint.

    .venv/Scripts/python -m arq app.worker.WorkerSettings

The handlers are synchronous SQLAlchemy code, so each job runs in a thread and the event
loop stays free for arq's own bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

import app.audit  # noqa: F401  registers the audit flush hook
from app.config import get_settings
from app.db import Base, engine
from app.services import handlers  # noqa: F401  registers the job handlers
from app.services.queue import run_job

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clearcut.worker")


async def run_job_task(ctx: dict, job_id: str) -> None:
    await asyncio.to_thread(run_job, job_id)


async def startup(ctx: dict) -> None:
    Base.metadata.create_all(engine)
    log.info("ClearCut worker ready (redis=%s)", get_settings().redis_url)


class WorkerSettings:
    functions = [run_job_task]
    on_startup = startup
    max_jobs = 4
    job_timeout = get_settings().job_timeout_seconds
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
