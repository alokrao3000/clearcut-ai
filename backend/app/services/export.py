"""Errors-and-omissions export: the evidence a project's clearances were actually done.

An E&O reviewer is not asking "what is the status?" — the board answers that. They are
asking "show me, per item, who decided what, on what basis, and when". So the export is
built around provenance rather than state:

* every clearance task, with the rightsholder assigned to it and **how** it was assigned —
  matcher, with its score, or a named person overriding it;
* the money at each stage: estimated range, quoted, agreed;
* the outreach that actually went out, and every tokenized link issued and opened;
* the full field-level ledger, with the actor type on each entry, so an automated decision
  is visibly distinguishable from a human one;
* a reconciliation line against the database trigger, which either confirms nothing changed
  outside the application or says that it cannot tell.

The last point matters: on SQLite there is no trigger, so the export says the check was not
available rather than implying a clean result.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import DISCLAIMER_TEXT, DISCLAIMER_VERSION
from app.models import (Asset, AuditLog, ClearanceTask, ContextView, DbAuditLog,
                        DisclaimerAcceptance, InboundMessage, MailThread, OutreachPacket,
                        Project, ReplyIntent, User)
from app.services.packets import LAYER_LABEL, SCOPE_LABEL, STAGE_LABEL, TIER_LABEL

# Tables whose history belongs to a project's clearance file.
LEDGER_TABLES = ("projects", "assets", "clearance_tasks", "outreach_packets", "packet_tasks",
                 "context_excerpts", "context_views", "outbound_messages", "reply_intents",
                 "proposed_changes")


@dataclass
class Reconciliation:
    """Whether anything changed the data without going through the application."""

    available: bool
    unmatched: int = 0
    note: str = ""


@dataclass
class ExportData:
    project: Project
    tasks: list[ClearanceTask]
    packets: list[OutreachPacket]
    audit: list[AuditLog]
    acceptances: list[tuple[DisclaimerAcceptance, User | None]]
    reconciliation: Reconciliation
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _mapping_basis(task: ClearanceTask) -> str:
    if task.rightsholder_id is None:
        return "Unassigned"
    if task.mapping_method == "manual":
        return "Manual override by a named user"
    if task.mapping_confidence is not None:
        return f"Automated match, confidence {task.mapping_confidence:.0f}"
    return "Automated match"


def reconcile(session: Session, project_id: str, row_ids: set[str]) -> Reconciliation:
    """Compare the trigger's record against the application's, for this project's rows.

    A trigger row with no application entry for the same table and row means something
    changed the database outside the app. That is not necessarily wrong — a migration or a
    deliberate correction would do it — but it has to be visible.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return Reconciliation(
            available=False,
            note="The database trigger is a PostgreSQL feature and is not installed on this "
                 "database, so changes made outside the application cannot be ruled out.")

    if not row_ids:
        return Reconciliation(available=True, unmatched=0,
                              note="No rows to reconcile.")

    app_keys = {
        (row.table_name, row.row_id)
        for row in session.scalars(select(AuditLog).where(AuditLog.row_id.in_(row_ids)))
    }
    unmatched = sum(
        1 for row in session.scalars(select(DbAuditLog).where(DbAuditLog.row_id.in_(row_ids)))
        if (row.table_name, row.row_id) not in app_keys
    )
    note = ("Every recorded database change has a matching application entry."
            if unmatched == 0 else
            f"{unmatched} database change(s) have no matching application entry and were "
            "made outside the application.")
    return Reconciliation(available=True, unmatched=unmatched, note=note)


def collect(session: Session, project: Project) -> ExportData:
    tasks = list(session.scalars(
        select(ClearanceTask).join(Asset, Asset.id == ClearanceTask.asset_id)
        .where(Asset.project_id == project.id)
        .options(selectinload(ClearanceTask.asset), selectinload(ClearanceTask.rightsholder))
        .order_by(Asset.created_at, ClearanceTask.layer)))

    packets = list(session.scalars(
        select(OutreachPacket).where(OutreachPacket.project_id == project.id)
        .options(selectinload(OutreachPacket.rightsholder),
                 selectinload(OutreachPacket.context_views).selectinload(ContextView.accesses),
                 selectinload(OutreachPacket.excerpts),
                 selectinload(OutreachPacket.items),
                 selectinload(OutreachPacket.thread).selectinload(MailThread.outbound))
        .order_by(OutreachPacket.created_at)))

    # Every row whose history belongs to this project's clearance file. The packet-side
    # records are keyed by their own ids, not the packet's, so collecting only projects,
    # assets, tasks and packets silently drops the context views, excerpts, outreach
    # messages and reply trail — in an export whose entire purpose is that trail.
    row_ids = ({project.id} | {t.id for t in tasks} | {t.asset_id for t in tasks}
               | {p.id for p in packets})
    for packet in packets:
        row_ids |= {v.id for v in packet.context_views}
        row_ids |= {e.id for e in packet.excerpts}
        row_ids |= {str(item.id) for item in packet.items}
        if packet.thread is not None:
            row_ids |= {m.id for m in packet.thread.outbound}

    # Reply intents and the changes they proposed hang off inbound mail, which is reached
    # through the thread rather than the packet.
    intents = list(session.scalars(
        select(ReplyIntent).join(InboundMessage, InboundMessage.id == ReplyIntent.inbound_id)
        .join(MailThread, MailThread.id == InboundMessage.thread_id)
        .where(MailThread.packet_id.in_({p.id for p in packets} or {""}))
        .options(selectinload(ReplyIntent.changes))))
    for intent in intents:
        row_ids.add(intent.id)
        row_ids |= {c.id for c in intent.changes}

    audit = list(session.scalars(
        select(AuditLog)
        .where(AuditLog.org_id == project.org_id,
               AuditLog.table_name.in_(LEDGER_TABLES),
               AuditLog.row_id.in_(row_ids))
        .order_by(AuditLog.id)))

    # Who accepted the disclaimer, and when — the gate exists to be evidenced.
    actor_ids = {row.actor_id for row in audit}
    users = {u.id: u for u in session.scalars(
        select(User).where(User.org_id == project.org_id))}
    acceptances = [
        (row, users.get(row.user_id))
        for row in session.scalars(
            select(DisclaimerAcceptance)
            .where(DisclaimerAcceptance.user_id.in_(set(users) | actor_ids))
            .order_by(DisclaimerAcceptance.accepted_at))
    ]

    return ExportData(project=project, tasks=tasks, packets=packets, audit=audit,
                      acceptances=acceptances,
                      reconciliation=reconcile(session, project.id, row_ids))


# ---------------------------------------------------------------- CSV


def _money(value) -> str:
    return "" if value is None else f"{value:.2f}"


def to_csv(data: ExportData) -> str:
    """One row per clearance task, which is the unit a reviewer works through."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([
        "project", "distribution_scope", "production_tier", "asset_title", "asset_source",
        "layer", "stage", "rightsholder", "licensing_contact", "assignment_basis",
        "estimate_low", "estimate_high", "quoted", "agreed", "outreach_sent_at",
        "context_links_issued", "context_link_opens", "task_id", "last_updated",
    ])

    sent_by_holder: dict[str, str] = {}
    links: dict[str, tuple[int, int]] = {}
    for packet in data.packets:
        sent = [m for m in (packet.thread.outbound if packet.thread else []) if m.status == "sent"]
        if sent:
            sent_by_holder[packet.rightsholder_id] = sent[0].sent_at.isoformat() if sent[0].sent_at else ""
        issued = len(packet.context_views)
        opens = sum(len([a for a in v.accesses if a.outcome == "ok"]) for v in packet.context_views)
        previous = links.get(packet.rightsholder_id, (0, 0))
        links[packet.rightsholder_id] = (previous[0] + issued, previous[1] + opens)

    for task in data.tasks:
        holder = task.rightsholder
        contact = ""
        if holder is not None:
            from app.services.mapping import effective_contact

            contact = effective_contact(holder)["licensing_email"] or ""
        issued, opens = links.get(task.rightsholder_id or "", (0, 0))
        writer.writerow([
            data.project.name,
            SCOPE_LABEL.get(data.project.distribution_scope, data.project.distribution_scope),
            TIER_LABEL.get(data.project.production_tier, data.project.production_tier),
            task.asset.title or "", task.asset.raw_source,
            LAYER_LABEL.get(task.layer, task.layer),
            STAGE_LABEL.get(task.stage, task.stage),
            holder.name if holder else "", contact, _mapping_basis(task),
            _money(task.estimate_low), _money(task.estimate_high),
            _money(task.quoted_amount), _money(task.agreed_amount),
            sent_by_holder.get(task.rightsholder_id or "", ""),
            issued, opens, task.id,
            task.updated_at.isoformat() if task.updated_at else "",
        ])
    return out.getvalue()


def ledger_csv(data: ExportData) -> str:
    """The field-level history, one row per recorded change."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["at", "table", "row_id", "action", "actor_type", "actor_id", "reason",
                     "field", "old_value", "new_value"])
    for row in data.audit:
        for field_name, (old, new) in (row.changes or {}).items():
            writer.writerow([
                row.at.isoformat() if row.at else "", row.table_name, row.row_id, row.action,
                row.actor_type, row.actor_id, row.reason or "", field_name,
                "" if old is None else str(old), "" if new is None else str(new),
            ])
    return out.getvalue()


# ---------------------------------------------------------------- report context


def summary(data: ExportData) -> dict:
    """The numbers that go at the top of the report, and into the JSON export."""
    tasks = data.tasks
    by_stage: dict[str, int] = {}
    for task in tasks:
        label = STAGE_LABEL.get(task.stage, task.stage)
        by_stage[label] = by_stage.get(label, 0) + 1

    automated = sum(1 for t in tasks if t.mapping_method == "auto")
    manual = sum(1 for t in tasks if t.mapping_method == "manual")
    return {
        "tasks": len(tasks),
        "unassigned": sum(1 for t in tasks if t.rightsholder_id is None),
        "by_stage": by_stage,
        "assigned_automatically": automated,
        "assigned_by_a_person": manual,
        "signed": sum(1 for t in tasks if t.agreed_amount is not None),
        "packets": len(data.packets),
        "context_links": sum(len(p.context_views) for p in data.packets),
        "ledger_entries": len(data.audit),
        "actor_breakdown": {
            actor: sum(1 for r in data.audit if r.actor_type == actor)
            for actor in sorted({r.actor_type for r in data.audit})
        },
        "reconciliation": {
            "available": data.reconciliation.available,
            "unmatched": data.reconciliation.unmatched,
            "note": data.reconciliation.note,
        },
        "disclaimer_version": DISCLAIMER_VERSION,
        "disclaimer_text": DISCLAIMER_TEXT,
        "generated_at": data.generated_at.isoformat(),
    }
