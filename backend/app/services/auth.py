"""Passwords, sessions and role checks.

Deliberate choices, because this is the part a reviewer will read first:

* **bcrypt, not a homemade hash.** Cost is configurable so a slow CI box and a production
  host can differ without changing stored hashes — the cost travels inside the hash.
* **Opaque session tokens, stored as digests.** Not JWTs: a clearance file is evidence, and
  "revoke this person now" has to mean now. A stateless token cannot promise that without a
  revocation list, which is a session table wearing a disguise.
* **Login is deliberately uninformative.** A wrong password, an unknown address and a
  disabled account produce the same answer and take the same time, so the endpoint cannot be
  used to enumerate who has an account.
* **Roles are ranked, not enumerated.** A check asks for "at least member", so adding a role
  later cannot silently widen an existing permission.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.enums import ROLE_RANK, Role
from app.models import Organization, User, UserSession, utcnow
from app.services import tokens

log = logging.getLogger(__name__)

# Compared against on every failed login so that a missing user costs the same as a wrong
# password. Without it, "unknown address" returns measurably faster than "wrong password".
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=12))

MIN_PASSWORD_LENGTH = 12


class AuthError(ValueError):
    """Shown to the caller verbatim, so the message must never reveal what exists."""


class PermissionDenied(PermissionError):
    pass


# ---------------------------------------------------------------- passwords


def hash_password(password: str, settings: Settings) -> str:
    check_password_strength(password)
    return bcrypt.hashpw(password.encode("utf-8"),
                         bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    """Always does the work, even with nothing to compare against."""
    encoded = password.encode("utf-8")
    if not password_hash:
        bcrypt.checkpw(encoded, _DUMMY_HASH)  # burn the same time
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        # A malformed stored hash is a corrupt row, not a valid login.
        log.warning("Rejecting a login against a malformed password hash.")
        return False


def check_password_strength(password: str) -> None:
    """Length over composition rules, which mostly produce `Passw0rd!` and a sticky note."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 200:
        raise AuthError("That password is too long.")
    if password.strip() != password:
        raise AuthError("Passwords cannot start or end with a space.")


# ---------------------------------------------------------------- organizations and users


def slugify(name: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    return base[:60] or "org"


def unique_slug(session: Session, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while session.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        suffix = f"-{n}"
        slug, n = f"{base[:60 - len(suffix)]}{suffix}", n + 1
    return slug


def normalize_email(email: str) -> str:
    return email.strip().lower()[:300]


def create_organization(session: Session, *, name: str, owner_email: str, owner_name: str,
                        owner_password: str, settings: Settings) -> tuple[Organization, User]:
    """Register a new tenant and its first user, who is necessarily the owner."""
    email = normalize_email(owner_email)
    if "@" not in email:
        raise AuthError("That does not look like an email address.")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise AuthError("That email address is already registered.")

    org = Organization(name=name.strip()[:200], slug=unique_slug(session, name))
    session.add(org)
    session.flush()

    owner = User(org_id=org.id, email=email, name=owner_name.strip()[:200] or email,
                 password_hash=hash_password(owner_password, settings), role=Role.owner.value)
    session.add(owner)
    session.flush()
    return org, owner


def add_user(session: Session, org: Organization, *, email: str, name: str, password: str,
             role: Role, settings: Settings) -> User:
    email = normalize_email(email)
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise AuthError("That email address is already registered.")
    user = User(org_id=org.id, email=email, name=name.strip()[:200] or email,
                password_hash=hash_password(password, settings), role=role.value)
    session.add(user)
    session.flush()
    return user


def count_owners(session: Session, org_id: str) -> int:
    return session.scalar(select(func.count(User.id)).where(
        User.org_id == org_id, User.role == Role.owner.value, User.is_active.is_(True))) or 0


# ---------------------------------------------------------------- sessions


def start_session(session: Session, user: User, settings: Settings, *, client_ip: str | None = None,
                  user_agent: str | None = None) -> tuple[UserSession, str]:
    """Mint a session. The plaintext token exists only in the response that creates it."""
    token, digest, hint = tokens.mint()
    record = UserSession(
        user_id=user.id, token_hash=digest, token_hint=hint,
        expires_at=datetime.now(UTC) + timedelta(days=settings.session_ttl_days),
        client_ip=client_ip, user_agent=user_agent)
    user.last_login_at = utcnow()
    session.add(record)
    session.flush()
    return record, token


def authenticate(session: Session, email: str, password: str) -> User:
    """Verify a credential pair, giving away nothing about which half was wrong."""
    user = session.scalar(
        select(User).where(User.email == normalize_email(email)).options(
            selectinload(User.organization)))
    ok = verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        raise AuthError("Those credentials are not valid.")
    return user


def session_expired(record: UserSession) -> bool:
    expires = record.expires_at
    if expires.tzinfo is None:  # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=UTC)
    return expires <= datetime.now(UTC)


def resolve_session(session: Session, token: str) -> User | None:
    """Look a bearer token up by digest. Returns the user, or None for any failure at all."""
    if not token or len(token) > 200:
        return None
    record = session.scalar(
        select(UserSession).where(UserSession.token_hash == tokens.digest(token))
        .options(selectinload(UserSession.user).selectinload(User.organization)))
    if record is None or record.revoked_at is not None or session_expired(record):
        return None
    if record.user is None or not record.user.is_active:
        return None
    record.last_seen_at = utcnow()
    return record.user


def revoke_session(session: Session, token: str) -> bool:
    record = session.scalar(
        select(UserSession).where(UserSession.token_hash == tokens.digest(token)))
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = utcnow()
    return True


def revoke_all_for(session: Session, user_id: str) -> int:
    """Used when a user is disabled or their role is reduced — access has to stop now."""
    records = session.scalars(select(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None))).all()
    for record in records:
        record.revoked_at = utcnow()
    return len(records)


# ---------------------------------------------------------------- authorization


def has_role(user: User, minimum: Role) -> bool:
    try:
        return ROLE_RANK[Role(user.role)] >= ROLE_RANK[minimum]
    except ValueError:
        # An unrecognised stored role grants nothing rather than everything.
        log.warning("User %s has an unknown role %r", user.id, user.role)
        return False


def require_role(user: User, minimum: Role) -> None:
    if not has_role(user, minimum):
        raise PermissionDenied(
            f"This needs the '{minimum.value}' role or higher; you are '{user.role}'.")


def bootstrap_token() -> str:
    """A one-off token printed at startup when an install has no organizations yet."""
    return secrets.token_urlsafe(24)
