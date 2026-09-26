"""Registration, sign-in, sessions, and user management inside an organization.

Everything that could tell an anonymous caller whether an account exists is deliberately
uninformative: registration, login and the failure paths all answer the same way whether or
not the address is known.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import Actor, set_actor
from app.config import get_settings
from app.db import get_session
from app.deps import current_user, db, require_admin, require_owner
from app.enums import ActorType, Role
from app.models import Organization, User, UserSession
from app.schemas import (LoginRequest, MeOut, OrgOut, PasswordChange, RegisterRequest,
                         SessionOut, TokenOut, UserCreate, UserOut, UserUpdate)
from app.services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])
org_router = APIRouter(prefix="/api/org", tags=["organization"])


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, org_id=user.org_id, email=user.email, name=user.name,
                   role=Role(user.role), is_active=user.is_active, created_at=user.created_at,
                   last_login_at=user.last_login_at)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _issue(session: Session, user: User, request: Request) -> TokenOut:
    settings = get_settings()
    record, token = auth.start_session(
        session, user, settings, client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"))
    session.commit()
    return TokenOut(access_token=token, expires_at=record.expires_at, user=user_out(user))


# ---------------------------------------------------------------- registration and sign-in

@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterRequest, request: Request, session: Session = Depends(get_session)):
    """Create an organization and its first user, who is necessarily its owner."""
    settings = get_settings()
    if not settings.allow_open_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This instance does not accept self-serve registration. "
                            "Ask an owner to invite you.")
    set_actor(session, Actor(ActorType.user, "self-registration", "Created an organization"))
    try:
        org, owner = auth.create_organization(
            session, name=body.organization_name, owner_email=body.email,
            owner_name=body.name, owner_password=body.password, settings=settings)
    except auth.AuthError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.info["org_id"] = org.id
    session.commit()
    return _issue(session, owner, request)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)):
    try:
        user = auth.authenticate(session, body.email, body.password)
    except auth.AuthError as exc:
        # One message for a wrong password, an unknown address and a disabled account.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return _issue(session, user, request)


@router.post("/logout", status_code=204)
def logout(request: Request, session: Session = Depends(get_session),
           _user: User = Depends(current_user)):
    token = (request.headers.get("authorization") or "").partition(" ")[2].strip()
    auth.revoke_session(session, token)
    session.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), session: Session = Depends(db)):
    org = session.get(Organization, user.org_id)
    return MeOut(user=user_out(user), organization=OrgOut.model_validate(org))


@router.get("/sessions", response_model=list[SessionOut])
def my_sessions(user: User = Depends(current_user), session: Session = Depends(db)):
    """Somewhere to notice a session you do not recognise, and end it."""
    rows = session.scalars(select(UserSession).where(UserSession.user_id == user.id)
                           .order_by(UserSession.created_at.desc()).limit(50)).all()
    return [SessionOut(
        id=r.id, token_hint=r.token_hint, created_at=r.created_at, expires_at=r.expires_at,
        revoked_at=r.revoked_at, last_seen_at=r.last_seen_at, client_ip=r.client_ip,
        user_agent=r.user_agent,
        status=("revoked" if r.revoked_at else "expired" if auth.session_expired(r) else "active"),
    ) for r in rows]


@router.post("/sessions/{session_id}/revoke", status_code=204)
def revoke_one(session_id: str, user: User = Depends(current_user), session: Session = Depends(db)):
    record = session.get(UserSession, session_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if record.revoked_at is None:
        from app.models import utcnow

        record.revoked_at = utcnow()
        session.commit()


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: User = Depends(current_user),
                    session: Session = Depends(db)):
    """Changing a password ends every other session — that is usually the whole point."""
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That is not your current password.")
    settings = get_settings()
    try:
        user.password_hash = auth.hash_password(body.new_password, settings)
    except auth.AuthError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    auth.revoke_all_for(session, user.id)
    session.commit()


# ---------------------------------------------------------------- organization and users

@org_router.get("", response_model=OrgOut)
def get_org(user: User = Depends(current_user), session: Session = Depends(db)):
    return OrgOut.model_validate(session.get(Organization, user.org_id))


@org_router.patch("", response_model=OrgOut)
def update_org(body: dict, user: User = Depends(require_owner), session: Session = Depends(db)):
    org = session.get(Organization, user.org_id)
    name = (body.get("name") or "").strip()
    if name:
        org.name = name[:200]
    session.commit()
    return OrgOut.model_validate(org)


@users_router.get("", response_model=list[UserOut])
def list_users(user: User = Depends(current_user), session: Session = Depends(db)):
    rows = session.scalars(select(User).where(User.org_id == user.org_id)
                           .order_by(User.created_at)).all()
    return [user_out(u) for u in rows]


@users_router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, actor: User = Depends(require_admin),
                session: Session = Depends(db)):
    """Add someone to this organization. Admins cannot mint owners."""
    if body.role is Role.owner and Role(actor.role) is not Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can create another owner.")
    org = session.get(Organization, actor.org_id)
    set_actor(session, Actor(ActorType.user, actor.id, f"Added {body.email} as {body.role.value}"))
    try:
        user = auth.add_user(session, org, email=body.email, name=body.name,
                             password=body.password, role=body.role, settings=get_settings())
    except auth.AuthError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    return user_out(user)


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, actor: User = Depends(require_admin),
                session: Session = Depends(db)):
    """Change a role or disable an account. Either one ends that user's sessions at once."""
    target = session.get(User, user_id)
    if target is None or target.org_id != actor.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    is_owner_actor = Role(actor.role) is Role.owner
    if Role(target.role) is Role.owner and not is_owner_actor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can change another owner.")
    if body.role is Role.owner and not is_owner_actor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can promote someone to owner.")

    # An organization with no active owner cannot be administered back out of that state.
    losing_owner = (Role(target.role) is Role.owner
                    and ((body.role is not None and body.role is not Role.owner)
                         or body.is_active is False))
    if losing_owner and auth.count_owners(session, actor.org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This is the last active owner. Promote someone else first.")

    set_actor(session, Actor(ActorType.user, actor.id, "Changed a user's access"))
    changed = False
    if body.role is not None and body.role.value != target.role:
        target.role, changed = body.role.value, True
    if body.is_active is not None and body.is_active != target.is_active:
        target.is_active, changed = body.is_active, True
    if body.name is not None:
        target.name = body.name.strip()[:200]

    # A reduced role or a disabled account must take effect now, not when a token expires.
    if changed:
        auth.revoke_all_for(session, target.id)
    session.commit()
    return user_out(target)
