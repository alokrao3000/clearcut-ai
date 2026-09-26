"""Request dependencies: who is calling, what they may do, and what they may see.

Three layers, applied in this order:

1. `current_user` — resolves the bearer token, or 401. There is no development bypass; an
   unauthenticated request is unauthenticated on every machine.
2. `require_member` / `require_admin` / `require_owner` — role floors, asked as "at least
   this", so adding a role later cannot silently widen an existing permission.
3. `scoped` — the tenancy boundary. Every loader in every router resolves its object to an
   organization and compares it against the caller's, and a mismatch is a **404, not a 403**:
   telling a stranger that an id exists but belongs to someone else is itself a disclosure.

The disclaimer gate from M1 still sits on top of all of it.
"""

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.config import DISCLAIMER_VERSION
from app.db import get_session
from app.enums import ActorType, Role
from app.models import DisclaimerAcceptance, User
from app.services import auth

NOT_FOUND = "Not found"


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user(request: Request, session: Session = Depends(get_session),
                 token: str | None = Depends(bearer_token)) -> User:
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.",
                            headers={"WWW-Authenticate": "Bearer"})
    user = auth.resolve_session(session, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That session is no longer valid.",
                            headers={"WWW-Authenticate": "Bearer"})
    session.commit()  # persist last_seen_at
    # Stashed so middleware and error handlers can attribute a request without re-resolving.
    request.state.user_id = user.id
    request.state.org_id = user.org_id
    return user


def db(session: Session = Depends(get_session), user: User = Depends(current_user)) -> Session:
    """The session every authenticated route uses, with the audit actor already attributed."""
    set_actor(session, Actor(ActorType.user, user.id))
    session.info["org_id"] = user.org_id
    return session


def _role_floor(minimum: Role):
    def dependency(user: User = Depends(current_user)) -> User:
        try:
            auth.require_role(user, minimum)
        except auth.PermissionDenied as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
        return user

    return dependency


require_member = _role_floor(Role.member)
require_admin = _role_floor(Role.admin)
require_owner = _role_floor(Role.owner)


def require_disclaimer(session: Session = Depends(db), user: User = Depends(current_user)) -> None:
    """Mutating endpoints stay blocked until this user accepts the current disclaimer version."""
    accepted = session.scalar(select(DisclaimerAcceptance.id).where(
        DisclaimerAcceptance.user_id == user.id, DisclaimerAcceptance.version == DISCLAIMER_VERSION))
    if accepted is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "disclaimer_required", "version": DISCLAIMER_VERSION,
                    "message": "Accept the current disclaimer via POST /api/disclaimer/accept."},
        )


def session_org(session: Session) -> str:
    """The organization this request belongs to.

    Carried on the session rather than passed down through every loader, the same way the
    audit actor already is. That is the point: a router cannot forget to pass something it
    never had to pass, so a scoped read cannot silently become an unscoped one.
    """
    org_id = session.info.get("org_id")
    if org_id is None:
        # Only reachable if a route takes a raw session and then does a tenant-scoped read.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "This route read tenant data from an unscoped session.")
    return org_id


def scoped(obj, session: Session, org_id_of=lambda o: o.org_id):
    """Return `obj` if it belongs to the caller's organization, else raise 404.

    404 rather than 403 on purpose: a 403 confirms the id is real and simply not yours, which
    turns an id-guessing loop into a census of other tenants' projects.
    """
    if obj is None or org_id_of(obj) != session_org(session):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return obj


def scoped_project(session: Session, project_id: str):
    """Load a project and prove it belongs to the caller, or 404.

    Every route that takes a `project_id` in its path calls this *before* filtering anything
    else by that id. Without it, a query like `where(Asset.project_id == project_id)` is
    perfectly correct SQL against somebody else's project.
    """
    from app.models import Project

    return scoped(session.get(Project, project_id), session)


def visible_directory(session: Session):
    """Filter for directory reads: the shared catalogue plus this tenant's own entries."""
    from app.models import Rightsholder

    return (Rightsholder.org_id.is_(None)) | (Rightsholder.org_id == session_org(session))


# Kept as a narrow shim so the M1–M5 routers that only needed an id keep working; it now
# returns a real, authenticated user id rather than a placeholder.
def current_user_id(user: User = Depends(current_user)) -> str:
    return user.id


# Write endpoints need at least `member` *and* an accepted disclaimer. Bundling them means a
# router cannot accidentally take one without the other.
WRITE = [Depends(require_member), Depends(require_disclaimer)]
