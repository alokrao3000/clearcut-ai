from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import (NOT_FOUND, db, require_admin, require_disclaimer, scoped_project,
                      session_org, visible_directory)
from app.enums import LAYER_KINDS, Layer, RightsholderKind
from app.models import AuditLog, Rightsholder, RightsholderAlias
from app.presenters import rightsholder_out
from app.schemas import AuditOut, RightsholderCreate, RightsholderOut, RightsholderUpdate
from app.services.mapping import normalize, score

router = APIRouter(tags=["directory"])
# Directory writes are an admin concern: a corrected licensing address changes who
# everyone in the organization will email.
WRITE = [Depends(require_admin), Depends(require_disclaimer)]


def load_rightsholder(session: Session, rid: str) -> Rightsholder:
    """The shared catalogue, or one of this tenant's own entries. Nobody else's."""
    rh = session.get(Rightsholder, rid)
    if rh is None or (rh.org_id is not None and rh.org_id != session_org(session)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return rh


def load_own_rightsholder(session: Session, rid: str) -> Rightsholder:
    """As above, but refuses the shared catalogue: it is reference data, not tenant data."""
    rh = load_rightsholder(session, rid)
    if rh.org_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is a shared directory entry and cannot be edited from here. Create your own "
            "entry for it instead, which only your organization will see.")
    return rh


def _namespaced(base: str, org_id: str) -> str:
    """A collision-free id for a tenant whose preferred one is taken by someone else."""
    suffix = f"_{org_id[:8]}"
    return f"{base[:80 - len(suffix)]}{suffix}"


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
    stmt = (select(Rightsholder).where(visible_directory(session))
            .options(selectinload(Rightsholder.aliases), selectinload(Rightsholder.children)))
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
    org_id = session_org(session)
    return [rightsholder_out(rh, org_id) for rh in rows[:limit]]


@router.get("/api/rightsholders/{rid}", response_model=RightsholderOut)
def get_rightsholder(rid: str, session: Session = Depends(db)):
    return rightsholder_out(load_rightsholder(session, rid), session_org(session))


@router.post("/api/rightsholders", response_model=RightsholderOut, status_code=201, dependencies=WRITE)
def create_rightsholder(body: RightsholderCreate, session: Session = Depends(db)):
    """Create an entry this organization owns. It is invisible to every other tenant."""
    # The primary key is global, so two tenants cannot both hold `ent_acme`. Telling the
    # second one "that id exists" would also confirm the existence of a row they can neither
    # see nor read, so the id they asked for is namespaced to them instead.
    existing = session.get(Rightsholder, body.id)
    if existing is not None and existing.org_id == session_org(session):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You already have a directory entry with that id.")
    if existing is not None:
        body = body.model_copy(update={"id": _namespaced(body.id, session_org(session))})
    _check_parent(session, body.id, body.parent_id)
    rh = Rightsholder(**body.model_dump(exclude={"aliases", "kind"}), kind=body.kind.value,
                      org_id=session_org(session), is_placeholder=False)
    rh.aliases = [RightsholderAlias(alias=a) for a in dict.fromkeys(body.aliases)]
    session.add(rh)
    session.commit()
    return rightsholder_out(rh, session_org(session))


@router.patch("/api/rightsholders/{rid}", response_model=RightsholderOut, dependencies=WRITE)
def update_rightsholder(rid: str, body: RightsholderUpdate, session: Session = Depends(db)):
    rh = load_own_rightsholder(session, rid)
    data = body.model_dump(exclude_unset=True)
    if "parent_id" in data:
        _check_parent(session, rid, data["parent_id"])
    for field, value in data.items():
        setattr(rh, field, getattr(value, "value", value))
    session.commit()
    return rightsholder_out(rh, session_org(session))


@router.get("/api/audit", response_model=list[AuditOut])
def audit_log(table: str | None = None, row_id: str | None = None, actor_type: str | None = None,
              limit: int = Query(200, le=1000), session: Session = Depends(db)):
    """E&O trace: every change with the actor that made it, scoped to this organization."""
    stmt = (select(AuditLog).where(AuditLog.org_id == session_org(session))
            .order_by(AuditLog.id.desc()).limit(limit))
    if table:
        stmt = stmt.where(AuditLog.table_name == table)
    if row_id:
        stmt = stmt.where(AuditLog.row_id == row_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    return session.scalars(stmt).all()
