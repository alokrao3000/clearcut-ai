from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import db, require_disclaimer
from app.enums import LAYER_KINDS, Layer, RightsholderKind
from app.models import AuditLog, Rightsholder, RightsholderAlias
from app.presenters import rightsholder_out
from app.schemas import AuditOut, RightsholderCreate, RightsholderOut, RightsholderUpdate
from app.services.mapping import normalize, score

router = APIRouter(tags=["directory"])
WRITE = [Depends(require_disclaimer)]


def load_rightsholder(session: Session, rid: str) -> Rightsholder:
    rh = session.get(Rightsholder, rid)
    if rh is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rightsholder not found")
    return rh


def _check_parent(session: Session, rid: str, parent_id: str | None) -> None:
    node = load_rightsholder(session, parent_id) if parent_id else None
    while node is not None:
        if node.id == rid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Parent would create a cycle")
        node = node.parent


@router.get("/api/rightsholders", response_model=list[RightsholderOut])
def search_rightsholders(q: str | None = None, kind: RightsholderKind | None = None, layer: Layer | None = None,
                         limit: int = Query(25, le=100), session: Session = Depends(db)):
    """Directory search for the manual rightsholder picker. Fuzzy on name and aliases."""
    stmt = select(Rightsholder).options(selectinload(Rightsholder.aliases), selectinload(Rightsholder.children))
    if kind:
        stmt = stmt.where(Rightsholder.kind == kind.value)
    if layer:
        stmt = stmt.where(Rightsholder.kind.in_([k.value for k in LAYER_KINDS[layer]]))
    rows = session.scalars(stmt).all()
    if q:
        nq = normalize(q)
        scored = []
        for rh in rows:
            names = [rh.name] + [a.alias for a in rh.aliases]
            best = max(max(score(nq, normalize(n)), score(normalize(n), nq)) for n in names)
            if best >= 55:
                scored.append((best, rh))
        rows = [rh for _, rh in sorted(scored, key=lambda x: (-x[0], x[1].name))]
    else:
        rows = sorted(rows, key=lambda r: r.name)
    return [rightsholder_out(rh) for rh in rows[:limit]]


@router.get("/api/rightsholders/{rid}", response_model=RightsholderOut)
def get_rightsholder(rid: str, session: Session = Depends(db)):
    return rightsholder_out(load_rightsholder(session, rid))


@router.post("/api/rightsholders", response_model=RightsholderOut, status_code=201, dependencies=WRITE)
def create_rightsholder(body: RightsholderCreate, session: Session = Depends(db)):
    if session.get(Rightsholder, body.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Rightsholder id already exists")
    _check_parent(session, body.id, body.parent_id)
    rh = Rightsholder(**body.model_dump(exclude={"aliases", "kind"}), kind=body.kind.value, is_placeholder=False)
    rh.aliases = [RightsholderAlias(alias=a) for a in dict.fromkeys(body.aliases)]
    session.add(rh)
    session.commit()
    return rightsholder_out(rh)


@router.patch("/api/rightsholders/{rid}", response_model=RightsholderOut, dependencies=WRITE)
def update_rightsholder(rid: str, body: RightsholderUpdate, session: Session = Depends(db)):
    rh = load_rightsholder(session, rid)
    data = body.model_dump(exclude_unset=True)
    if "parent_id" in data:
        _check_parent(session, rid, data["parent_id"])
    for field, value in data.items():
        setattr(rh, field, getattr(value, "value", value))
    session.commit()
    return rightsholder_out(rh)


@router.get("/api/audit", response_model=list[AuditOut])
def audit_log(table: str | None = None, row_id: str | None = None, actor_type: str | None = None,
              limit: int = Query(200, le=1000), session: Session = Depends(db)):
    """E&O trace: every change with the actor that made it."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if table:
        stmt = stmt.where(AuditLog.table_name == table)
    if row_id:
        stmt = stmt.where(AuditLog.row_id == row_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    return session.scalars(stmt).all()
