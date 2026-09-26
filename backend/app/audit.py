"""Field-level audit ledger.

Every insert/update/delete on an audited table writes an AuditLog row inside the same
transaction, tagged with the actor (user / system / scraper / llm) held in session.info.
This is what lets an E&O insurer see whether a rightsholder assignment came from the
matcher or from a named user override.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.enums import ActorType
from app.models import AuditLog

AUDITED_TABLES = {
    "projects", "assets", "clearance_tasks", "rightsholders", "rightsholder_aliases", "rate_cards",
    "disclaimer_acceptances",
    # M4. Who was sent what, and who was handed a link to it, is the part of the record an
    # E&O review actually asks about. `context_view_accesses` is itself a log, so it is not
    # double-recorded here.
    "outreach_packets", "packet_tasks", "context_excerpts", "context_views",
    # M5. What went out, what the model made of the answer, and who confirmed it. Inbound
    # messages and mail threads are left out: an inbound row is itself the record of a reply,
    # and a thread row would copy its plaintext reply-to token into the ledger.
    "outbound_messages", "reply_intents", "proposed_changes",
}
# `token_hash` is the lookup key for a live context view; copying it into an append-only
# ledger widens its blast radius for no audit value. The view's id already identifies it.
IGNORED_FIELDS = {"updated_at", "token_hash"}


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str
    reason: str | None = None


UNATTRIBUTED = Actor(ActorType.system, "unattributed")


def set_actor(session: Session, actor: Actor) -> None:
    session.info["actor"] = actor


@contextmanager
def acting_as(session: Session, actor_type: ActorType, actor_id: str, reason: str | None = None):
    """Temporarily attribute changes to another actor, e.g. the scraper during ingest.

    Flushes on entry and exit so changes land under the right actor.
    """
    session.flush()
    previous = session.info.get("actor")
    session.info["actor"] = Actor(actor_type, actor_id, reason)
    try:
        yield
        session.flush()
    finally:
        if previous is None:
            session.info.pop("actor", None)
        else:
            session.info["actor"] = previous


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, default=str))
    return value


def _row_id(state) -> str:
    return ",".join(str(v) for v in state.mapper.primary_key_from_instance(state.obj()))


def _snapshot(state) -> dict:
    out = {}
    for attr in state.mapper.column_attrs:
        value = getattr(state.obj(), attr.key)
        if value is not None and attr.key not in IGNORED_FIELDS:
            out[attr.key] = _jsonable(value)
    return out


@event.listens_for(Session, "after_flush")
def _write_audit(session: Session, _flush_context) -> None:
    # after_flush: PKs are assigned but attribute history is still intact.
    actor: Actor = session.info.get("actor") or UNATTRIBUTED
    rows = []

    # Tenant stamped from the request's session, so an E&O export can never cross
    # organizations even though the ledger is one physical table.
    org_id = session.info.get("org_id")

    def add(state, action, changes):
        rows.append({
            "org_id": org_id,
            "table_name": state.mapper.local_table.name,
            "row_id": _row_id(state),
            "action": action,
            "changes": changes,
            "actor_type": actor.type.value,
            "actor_id": actor.id,
            "reason": actor.reason,
        })

    for obj in session.new:
        state = inspect(obj)
        if state.mapper.local_table.name in AUDITED_TABLES:
            add(state, "insert", {k: [None, v] for k, v in _snapshot(state).items()})

    for obj in session.dirty:
        state = inspect(obj)
        if state.mapper.local_table.name not in AUDITED_TABLES:
            continue
        changes = {}
        for attr in state.mapper.column_attrs:
            if attr.key in IGNORED_FIELDS:
                continue
            hist = state.attrs[attr.key].history
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old != new:
                changes[attr.key] = [_jsonable(old), _jsonable(new)]
        if changes:
            add(state, "update", changes)

    for obj in session.deleted:
        state = inspect(obj)
        if state.mapper.local_table.name in AUDITED_TABLES:
            add(state, "delete", {k: [v, None] for k, v in _snapshot(state).items()})

    if rows:
        session.connection().execute(AuditLog.__table__.insert(), rows)
