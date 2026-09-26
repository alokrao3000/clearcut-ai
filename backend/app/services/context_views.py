"""Issue, resolve and log tokenized context views.

The security model, stated plainly so it is not mistaken for more than it is:

* The token is the only credential. It is 256 bits from `secrets`, stored as a SHA-256
  digest, and looked up by digest — so a database dump yields no working links.
* Expiry is enforced on every request, not at issue time, and revocation is immediate.
* Expired, revoked and unknown tokens produce the *same* page. Telling a stranger that a
  link used to work confirms it existed.
* Every hit is logged, refusals included. Repeated attempts on a dead token are exactly
  what a clearance audit wants to see.
* The watermark is deterrence and attribution, not DRM. Anyone determined can strip it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.models import ContextView, ContextViewAccess, OutreachPacket, utcnow
from app.services import tokens


class ViewError(ValueError):
    pass


def watermark_text(recipient_name: str, recipient_email: str | None, project_name: str) -> str:
    """The string tiled across the page and burned into every excerpt image."""
    who = f"{recipient_name} ({recipient_email})" if recipient_email else recipient_name
    return f"{project_name} · confidential · {who} · do not redistribute"


def view_url(token: str, settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/view/{token}"


def issue(session: Session, packet: OutreachPacket, *, recipient_name: str,
          recipient_email: str | None, created_by: str, settings: Settings,
          ttl_days: int | None = None) -> tuple[ContextView, str]:
    """Mint a view and return it with its plaintext token — the only time that exists."""
    days = settings.context_view_ttl_days if ttl_days is None else ttl_days
    if days < 1 or days > settings.context_view_max_ttl_days:
        raise ViewError(f"Expiry must be between 1 and {settings.context_view_max_ttl_days} days.")

    token, digest, hint = tokens.mint()
    view = ContextView(
        packet_id=packet.id, token_hash=digest, token_hint=hint,
        recipient_name=recipient_name.strip()[:300],
        recipient_email=(recipient_email or None),
        watermark_text=watermark_text(recipient_name, recipient_email, packet.project.name)[:300],
        expires_at=datetime.now(UTC) + timedelta(days=days),
        created_by=created_by,
    )
    session.add(view)
    session.flush()
    return view, token


def revoke(view: ContextView) -> ContextView:
    if view.revoked_at is None:
        view.revoked_at = utcnow()
    return view


def status_of(view: ContextView) -> str:
    if view.revoked_at is not None:
        return "revoked"
    if _expired(view):
        return "expired"
    return "active"


def _expired(view: ContextView) -> bool:
    expires = view.expires_at
    if expires.tzinfo is None:  # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=UTC)
    return expires <= datetime.now(UTC)


def resolve(session: Session, token: str) -> tuple[ContextView | None, str]:
    """Look up a token. Returns (view, outcome) where outcome is ok|expired|revoked|unknown.

    A `None` view with outcome `unknown` is indistinguishable to the caller's page from the
    other refusals by design; only the log tells them apart.
    """
    if not token or len(token) > 200:
        return None, "unknown"
    view = session.scalar(
        select(ContextView)
        .where(ContextView.token_hash == tokens.digest(token))
        .options(selectinload(ContextView.packet).selectinload(OutreachPacket.items),
                 selectinload(ContextView.packet).selectinload(OutreachPacket.excerpts),
                 selectinload(ContextView.packet).selectinload(OutreachPacket.project),
                 selectinload(ContextView.packet).selectinload(OutreachPacket.rightsholder)))
    if view is None:
        return None, "unknown"
    status = status_of(view)
    return view, ("ok" if status == "active" else status)


def log_access(session: Session, view: ContextView, outcome: str, *, path: str,
               client_ip: str | None, user_agent: str | None, referer: str | None) -> None:
    """Record a hit and, when it succeeded, advance the view's access counters."""
    session.add(ContextViewAccess(
        view_id=view.id, outcome=outcome, path=path[:300], client_ip=client_ip,
        user_agent=(user_agent or None), referer=(referer or None)))
    if outcome == "ok":
        view.access_count = (view.access_count or 0) + 1
        view.last_accessed_at = utcnow()
    session.commit()
