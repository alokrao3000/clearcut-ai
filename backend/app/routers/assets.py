from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.deps import current_user_id, db, require_disclaimer
from app.enums import ActorType
from app.models import Asset
from app.presenters import asset_out, task_out
from app.schemas import AddLayerRequest, AssetOut, AssetUpdate, TaskOut
from app.services import pipeline

router = APIRouter(prefix="/api/assets", tags=["assets"])
WRITE = [Depends(require_disclaimer)]


def load_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return asset


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, session: Session = Depends(db)):
    return asset_out(load_asset(session, asset_id))


@router.patch("/{asset_id}", response_model=AssetOut, dependencies=WRITE)
def update_asset(asset_id: str, body: AssetUpdate, session: Session = Depends(db)):
    """Manual correction of scraped metadata. The frozen ingest_payload is never touched."""
    asset = load_asset(session, asset_id)
    changes = body.model_dump(exclude_unset=True, exclude={"remap"})
    for field, value in changes.items():
        setattr(asset, field, value)
    session.flush()
    if body.remap and changes:
        pipeline.map_and_estimate(session, asset.project, asset.tasks)
    session.commit()
    return asset_out(asset)


@router.delete("/{asset_id}", status_code=204, dependencies=WRITE)
def delete_asset(asset_id: str, session: Session = Depends(db)):
    session.delete(load_asset(session, asset_id))
    session.commit()


@router.post("/{asset_id}/layers", response_model=TaskOut, status_code=201, dependencies=WRITE)
def add_layer(asset_id: str, body: AddLayerRequest, session: Session = Depends(db)):
    """Split out another right, e.g. a performer's likeness visible in a clip."""
    task = pipeline.add_layer(session, load_asset(session, asset_id), body.layer)
    session.commit()
    return task_out(task)


@router.post("/{asset_id}/remap", response_model=AssetOut, dependencies=WRITE)
def remap(asset_id: str, session: Session = Depends(db), user_id: str = Depends(current_user_id)):
    asset = load_asset(session, asset_id)
    set_actor(session, Actor(ActorType.user, user_id, "Requested re-run of rights matching"))
    pipeline.map_and_estimate(session, asset.project, asset.tasks)
    session.commit()
    return asset_out(asset)
