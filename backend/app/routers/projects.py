from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import WRITE, db, scoped, session_org
from app.enums import Stage
from app.models import Asset, ClearanceTask, Project
from app.presenters import asset_out, board_card, task_out
from app.schemas import (AssetOut, BoardCard, BudgetTotals, IngestRequest, IngestResultOut, JobOut,
                         ProjectCreate, ProjectOut, ProjectUpdate, TaskOut)
from app.services import budget, pipeline
from app.services.ingest import MetadataFetcher, get_fetcher
from app.services.queue import enqueue

router = APIRouter(prefix="/api/projects", tags=["projects"])


def load_project(session: Session, project_id: str) -> Project:
    """A project belonging to another organization is reported missing, never forbidden."""
    return scoped(session.get(Project, project_id), session)


def project_tasks(session: Session, project_id: str) -> list[ClearanceTask]:
    return list(session.scalars(
        select(ClearanceTask).join(Asset).where(Asset.project_id == project_id)
        .options(selectinload(ClearanceTask.asset), selectinload(ClearanceTask.rightsholder))
        .order_by(Asset.created_at, ClearanceTask.layer)))


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(db)):
    return session.scalars(
        select(Project).where(Project.org_id == session_org(session))
        .order_by(Project.created_at.desc())).all()


@router.post("", response_model=ProjectOut, status_code=201, dependencies=WRITE)
def create_project(body: ProjectCreate, session: Session = Depends(db)):
    project = Project(org_id=session_org(session), name=body.name,
                      distribution_scope=body.distribution_scope.value,
                      production_tier=body.production_tier.value)
    session.add(project)
    session.commit()
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(db)):
    return load_project(session, project_id)


@router.patch("/{project_id}", response_model=ProjectOut, dependencies=WRITE)
def update_project(project_id: str, body: ProjectUpdate, session: Session = Depends(db)):
    project = load_project(session, project_id)
    scope_changed = False
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        value = getattr(value, "value", value)
        if field in ("distribution_scope", "production_tier") and getattr(project, field) != value:
            scope_changed = True
        setattr(project, field, value)
    session.flush()
    if scope_changed:
        pipeline.estimate(session, project, project_tasks(session, project_id))
    session.commit()
    return project


@router.delete("/{project_id}", status_code=204, dependencies=WRITE)
def delete_project(project_id: str, session: Session = Depends(db)):
    session.delete(load_project(session, project_id))
    session.commit()


@router.post("/{project_id}/ingest", response_model=list[IngestResultOut] | JobOut, dependencies=WRITE)
def ingest(project_id: str, body: IngestRequest, session: Session = Depends(db),
           fetcher: MetadataFetcher = Depends(get_fetcher)):
    project = load_project(session, project_id)

    if body.defer:
        # Large pastes hold the request open for a while; hand them to the worker instead.
        return enqueue(
            session, "ingest_urls",
            {"project_id": project.id,
             "items": [{"url": str(i.url), "notes": i.notes, "usage_seconds": i.usage_seconds}
                       for i in body.items]},
            project_id=project.id,
        )

    items = [(str(i.url), i.notes, i.usage_seconds) for i in body.items]
    outcomes = pipeline.ingest_into_project(session, project, items, fetcher)
    session.commit()
    return [IngestResultOut(url=o.url, asset_id=o.asset.id, status=o.asset.ingest_status, duplicate=o.duplicate,
                            error=o.asset.ingest_error) for o in outcomes]


@router.get("/{project_id}/assets", response_model=list[AssetOut])
def list_assets(project_id: str, session: Session = Depends(db)):
    load_project(session, project_id)
    assets = session.scalars(
        select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at)
        .options(selectinload(Asset.tasks).selectinload(ClearanceTask.rightsholder))).all()
    return [asset_out(a) for a in assets]


@router.get("/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(project_id: str, session: Session = Depends(db)):
    load_project(session, project_id)
    return [task_out(t) for t in project_tasks(session, project_id)]


@router.get("/{project_id}/board", response_model=dict[Stage, list[BoardCard]])
def board(project_id: str, session: Session = Depends(db)):
    load_project(session, project_id)
    columns: dict[Stage, list[BoardCard]] = {s: [] for s in Stage}
    for task in project_tasks(session, project_id):
        columns[Stage(task.stage)].append(board_card(task))
    return columns


@router.post("/{project_id}/estimate", response_model=BudgetTotals, dependencies=WRITE)
def estimate(project_id: str, session: Session = Depends(db)):
    """Re-run the budget matrix on every task whose budget is not yet approved."""
    project = load_project(session, project_id)
    tasks = project_tasks(session, project_id)
    pipeline.estimate(session, project, tasks)
    session.commit()
    return budget.project_totals(tasks)


@router.get("/{project_id}/budget", response_model=BudgetTotals)
def budget_totals(project_id: str, session: Session = Depends(db)):
    load_project(session, project_id)
    return budget.project_totals(project_tasks(session, project_id))
