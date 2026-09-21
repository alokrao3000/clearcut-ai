from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DISCLAIMER_TEXT, DISCLAIMER_VERSION
from app.deps import current_user_id, db
from app.models import DisclaimerAcceptance
from app.schemas import DisclaimerOut

router = APIRouter(prefix="/api/disclaimer", tags=["disclaimer"])


def _status(session: Session, user_id: str) -> DisclaimerOut:
    row = session.scalar(select(DisclaimerAcceptance).where(
        DisclaimerAcceptance.user_id == user_id, DisclaimerAcceptance.version == DISCLAIMER_VERSION))
    return DisclaimerOut(version=DISCLAIMER_VERSION, text=DISCLAIMER_TEXT, accepted=row is not None,
                         accepted_at=row.accepted_at if row else None)


@router.get("", response_model=DisclaimerOut)
def get_disclaimer(session: Session = Depends(db), user_id: str = Depends(current_user_id)):
    return _status(session, user_id)


@router.post("/accept", response_model=DisclaimerOut)
def accept_disclaimer(request: Request, session: Session = Depends(db), user_id: str = Depends(current_user_id)):
    if not _status(session, user_id).accepted:
        session.add(DisclaimerAcceptance(user_id=user_id, version=DISCLAIMER_VERSION,
                                         client_ip=request.client.host if request.client else None))
        session.commit()
    return _status(session, user_id)
