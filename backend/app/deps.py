from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.config import DISCLAIMER_VERSION
from app.db import get_session
from app.enums import ActorType
from app.models import DisclaimerAcceptance


def current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    # Placeholder identity until auth lands in M6.
    return (x_user_id or "dev-user").strip()[:200]


def db(session: Session = Depends(get_session), user_id: str = Depends(current_user_id)) -> Session:
    set_actor(session, Actor(ActorType.user, user_id))
    return session


def require_disclaimer(session: Session = Depends(db), user_id: str = Depends(current_user_id)) -> None:
    """Mutating endpoints are blocked until the user accepts the current disclaimer version."""
    accepted = session.scalar(select(DisclaimerAcceptance.id).where(
        DisclaimerAcceptance.user_id == user_id, DisclaimerAcceptance.version == DISCLAIMER_VERSION))
    if accepted is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "disclaimer_required", "version": DISCLAIMER_VERSION,
                    "message": "Accept the current disclaimer via POST /api/disclaimer/accept."},
        )
