from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.audit  # noqa: F401  registers the audit flush hook
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.routers import assets, directory, disclaimer, mail, outreach, projects, scripts, tasks
from app.seed import seed
from app.services import handlers  # noqa: F401  registers the background job handlers
from app.services.workflow import WorkflowError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)  # Alembic migrations arrive in M6
    if get_settings().seed_on_startup:
        with SessionLocal() as session:
            seed(session)
    yield


app = FastAPI(title="ClearCut AI", version="0.1.0", lifespan=lifespan,
              description="Pre-production asset sourcing and clearance workflow. Advisory drafts only.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"],
                   allow_headers=["*"])


@app.exception_handler(WorkflowError)
def workflow_error(_request: Request, exc: WorkflowError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


for r in (disclaimer, projects, assets, tasks, directory, scripts, outreach, mail):
    app.include_router(r.router)
app.include_router(scripts.jobs_router)
# Unauthenticated token surface. Mounted at the app root, not under /api, because the
# URL is pasted into an email and read by a human.
app.include_router(outreach.public_router)
# The mail provider's webhook. Authenticated by signature, not by the disclaimer gate.
app.include_router(mail.public_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
