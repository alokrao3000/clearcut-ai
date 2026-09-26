from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.config import get_settings
from app.deps import NOT_FOUND, WRITE, current_user_id, db, scoped
from app.enums import ActorType
from app.models import AuditLog, ClearanceTask
from app.presenters import task_out
from app.schemas import AuditOut, ContactResolutionOut, TaskOut, TaskUpdate, TransitionRequest
from app.services import contacts, pipeline, workflow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def load_task(session: Session, task_id: str) -> ClearanceTask:
    """Scoped through the asset's project; a task carries no org_id of its own."""
    task = session.get(ClearanceTask, task_id)
    if task is None or task.asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped(task.asset.project, session)
    return task


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, session: Session = Depends(db)):
    return task_out(load_task(session, task_id))


@router.patch("/{task_id}", response_model=TaskOut, dependencies=WRITE)
def update_task(task_id: str, body: TaskUpdate, session: Session = Depends(db),
                user_id: str = Depends(current_user_id)):
    task = load_task(session, task_id)
    set_actor(session, Actor(ActorType.user, user_id, body.reason))
    fields = body.model_fields_set - {"reason"}
    if "rightsholder_id" in fields:
        try:
            pipeline.assign_rightsholder(session, task, body.rightsholder_id)
        except LookupError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    for field in fields & {"quoted_amount", "agreed_amount", "notes"}:
        setattr(task, field, getattr(body, field))
    session.commit()
    return task_out(task)


@router.post("/{task_id}/transition", response_model=TaskOut, dependencies=WRITE)
def transition(task_id: str, body: TransitionRequest, session: Session = Depends(db),
               user_id: str = Depends(current_user_id)):
    task = load_task(session, task_id)
    set_actor(session, Actor(ActorType.user, user_id, body.reason))
    workflow.transition(task, body.to)
    session.commit()
    return task_out(task)


@router.post("/{task_id}/estimate", response_model=TaskOut, dependencies=WRITE)
def estimate(task_id: str, session: Session = Depends(db)):
    task = load_task(session, task_id)
    pipeline.estimate(session, task.asset.project, [task])
    session.commit()
    return task_out(task)


@router.get("/{task_id}/history", response_model=list[AuditOut])
def history(task_id: str, session: Session = Depends(db)):
    load_task(session, task_id)
    return session.scalars(select(AuditLog).where(AuditLog.table_name == "clearance_tasks",
                                                  AuditLog.row_id == task_id).order_by(AuditLog.id)).all()


@router.get("/{task_id}/contacts", response_model=ContactResolutionOut)
def contacts_for_task(task_id: str, session: Session = Depends(db)):
    """Everyone who could grant this right, ranked, with the reasoning behind the pick.

    Computed fresh rather than read from the task's cached copy: the directory and the
    asset's credits both change, and this is a read-only view either way.
    """
    task = load_task(session, task_id)
    resolution = contacts.resolve(session, task, get_settings())
    fields = resolution.to_task_fields()
    return ContactResolutionOut(
        task_id=task.id, layer=task.layer, recommended=fields["recommended_contact"],
        options=fields["contact_options"], research_leads=fields["research_leads"],
    )


@router.post("/{task_id}/resolve-contacts", response_model=ContactResolutionOut, dependencies=WRITE)
def resolve_contacts(task_id: str, session: Session = Depends(db)):
    """Re-run contact resolution after the directory or the asset's credits changed."""
    task = load_task(session, task_id)
    pipeline.resolve_contacts(session, [task])
    session.commit()
    return ContactResolutionOut(
        task_id=task.id, layer=task.layer, recommended=task.recommended_contact,
        options=task.contact_options or [], research_leads=task.research_leads or [],
    )
