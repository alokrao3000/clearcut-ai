from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.deps import current_user_id, db, require_disclaimer
from app.enums import ActorType
from app.models import AuditLog, ClearanceTask
from app.presenters import task_out
from app.schemas import AuditOut, TaskOut, TaskUpdate, TransitionRequest
from app.services import pipeline, workflow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
WRITE = [Depends(require_disclaimer)]


def load_task(session: Session, task_id: str) -> ClearanceTask:
    task = session.get(ClearanceTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
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
