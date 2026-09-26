"""Request correlation, structured logs, and a readiness check that names what is broken.

Three small things that matter once this runs somewhere other than a laptop:

* **A request id on every log line and every response.** When a producer says "the export
  failed at about four", the id in their error message is the only thing that finds it.
* **JSON logs on demand.** A terminal wants text; a log collector wants fields. One flag.
* **Readiness that is specific.** `{"status": "degraded"}` with a named component beats a
  health check that is green until everything is on fire. The database is required; Redis,
  object storage, the PDF stack and the LLM are reported but do not fail the check, because
  the product is deliberately usable without them.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Never logged, whatever else happens.
REDACTED_HEADERS = {"authorization", "cookie", "x-clearcut-signature", "x-webhook-signature"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in ("method", "path", "status", "duration_ms", "user_id", "org_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if as_json
        else logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn duplicates access lines that this middleware already produces, with more detail.
    logging.getLogger("uvicorn.access").disabled = True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, times the request, and logs one line per request."""

    def __init__(self, app, logger_name: str = "clearcut.request"):
        super().__init__(app)
        self.log = logging.getLogger(logger_name)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        # An id from outside is useful for tracing across services but must not be trusted
        # into a log line unbounded.
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - started) * 1000
            self.log.exception("%s %s failed after %.1fms", request.method, request.url.path,
                               duration, extra={"method": request.method,
                                                "path": request.url.path,
                                                "duration_ms": round(duration, 1)})
            request_id_var.reset(token)
            raise

        duration = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        self.log.info(
            "%s %s -> %s in %.1fms", request.method, request.url.path, response.status_code,
            duration,
            extra={"method": request.method, "path": request.url.path,
                   "status": response.status_code, "duration_ms": round(duration, 1),
                   "user_id": getattr(request.state, "user_id", None),
                   "org_id": getattr(request.state, "org_id", None)})
        request_id_var.reset(token)
        return response


# ---------------------------------------------------------------- readiness


def check_components(engine, settings) -> tuple[str, dict[str, dict]]:
    """Probe each dependency. Only the database can make the service unready."""
    from sqlalchemy import text

    components: dict[str, dict] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        components["database"] = {"status": "ok", "required": True}
    except Exception as exc:  # noqa: BLE001 - any failure here is the same failure
        components["database"] = {"status": "error", "required": True, "detail": str(exc)[:200]}

    if settings.use_worker:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
            components["redis"] = {"status": "ok", "required": False}
        except Exception as exc:  # noqa: BLE001
            components["redis"] = {"status": "error", "required": False, "detail": str(exc)[:200]}
    else:
        components["redis"] = {"status": "disabled", "required": False,
                               "detail": "Jobs run inline; set CLEARCUT_USE_WORKER=true to use arq."}

    from app.services import pdf

    probe = pdf.probe()
    components["pdf"] = ({"status": "ok", "required": False, "detail": probe.version}
                         if probe.available else
                         {"status": "unavailable", "required": False, "detail": probe.error})

    components["llm"] = ({"status": "configured", "required": False} if settings.anthropic_api_key
                         else {"status": "unconfigured", "required": False,
                               "detail": "Script extraction and reply reading are disabled."})

    components["thumbnail_cache"] = {
        "status": "enabled" if settings.thumbnail_cache_enabled else "disabled",
        "required": False}

    unhealthy = any(c.get("required") and c["status"] != "ok" for c in components.values())
    return ("degraded" if unhealthy else "ok"), components
