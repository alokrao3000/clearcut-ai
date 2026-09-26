import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.audit  # noqa: F401  registers the audit flush hook
from app.config import get_settings
from app.db import SessionLocal, engine
from app.observability import RequestContextMiddleware, check_components, configure_logging
from app.routers import (assets, auth, directory, disclaimer, export, mail, outreach,
                         projects, scripts, tasks)
from app.schemas import HealthOut
from app.seed import seed
from app.services import handlers  # noqa: F401  registers the background job handlers
from app.services import auth as auth_service
from app.services import schema
from app.services.workflow import WorkflowError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    revision = schema.ensure_ready(engine, settings.database_url,
                                   auto_migrate=settings.auto_migrate)
    log.info("Schema at revision %s", revision)
    if settings.seed_on_startup:
        with SessionLocal() as session:
            # The seeded directory belongs to no tenant: org_id stays NULL and every
            # organization reads it.
            seed(session)
    yield


_settings = get_settings()
configure_logging(_settings.log_level, _settings.log_json)

app = FastAPI(title="ClearCut AI", version="0.1.0", lifespan=lifespan,
              description="Pre-production asset sourcing and clearance workflow. Advisory drafts only.")
app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origins,
                   allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Request-Id"])
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(auth_service.PermissionDenied)
def permission_denied(_request: Request, exc: auth_service.PermissionDenied):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(WorkflowError)
def workflow_error(_request: Request, exc: WorkflowError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


for r in (auth, disclaimer, projects, assets, tasks, directory, scripts, outreach, mail,
          export):
    app.include_router(r.router)
app.include_router(scripts.jobs_router)
app.include_router(auth.users_router)
app.include_router(auth.org_router)
# Unauthenticated token surface. Mounted at the app root, not under /api, because the
# URL is pasted into an email and read by a human.
app.include_router(outreach.public_router)
# The mail provider's webhook. Authenticated by signature, not by the disclaimer gate.
app.include_router(mail.public_router)


@app.get("/api/health")
def health():
    """Liveness. Deliberately trivial: it answers whether the process is up, nothing more."""
    return {"status": "ok"}


@app.get("/api/health/ready", response_model=HealthOut)
def ready(response: Response):
    """Readiness, component by component.

    Only the database can make this unready. Redis, object storage, the PDF stack and the LLM
    are reported but never fail the check, because the product is deliberately usable without
    any of them — saying otherwise would make the signal useless.
    """
    status_text, components = check_components(engine, get_settings())
    if status_text != "ok":
        response.status_code = 503
    return HealthOut(status=status_text, version=app.version, components=components)
