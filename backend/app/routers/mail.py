"""The mail loop: send a packet, receive the reply, queue what it means for a human.

The inbound webhook is the only route here that is not disclaimer-gated, because the caller
is a mail provider rather than a person. It is authenticated by signature, it is idempotent
on the provider's message id, and it never returns anything a caller could probe with: an
unroutable message and a routed one both come back 200, so the endpoint cannot be used to
discover which reply-to tokens are live.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import Actor, acting_as, set_actor
from app.config import get_settings
from app.db import get_session
from app.deps import NOT_FOUND, WRITE, current_user_id, db, scoped, scoped_project
from app.enums import ActorType, Layer, Stage
from app.models import (Asset, ClearanceTask, InboundMessage, MailThread, OutboundMessage,
                        OutreachPacket, PacketTask, ProposedChange, ReplyIntent, utcnow)
from app.schemas import (ApplyRequest, DecisionRequest, InboundAck, InboundOut, LedgerOut,
                         OutboundOut, ProposedChangeOut, ReplyIntentOut, SendRequest, ThreadOut)
from app.services import ledger, mail, replies, workflow
from app.services.mapping import effective_contact

log = logging.getLogger(__name__)

router = APIRouter(tags=["mail"])
public_router = APIRouter(tags=["mail webhook"], include_in_schema=False)


# ---------------------------------------------------------------- presenters

def outbound_out(message: OutboundMessage) -> OutboundOut:
    return OutboundOut.model_validate(message)


def change_out(change: ProposedChange) -> ProposedChangeOut:
    out = ProposedChangeOut.model_validate(change)
    if change.task is not None:
        out.layer = Layer(change.task.layer)
        if change.task.asset is not None:
            out.asset_title = change.task.asset.title
    return out


def intent_out(intent: ReplyIntent) -> ReplyIntentOut:
    out = ReplyIntentOut.model_validate(intent)
    out.changes = [change_out(c) for c in intent.changes]
    return out


def inbound_out(message: InboundMessage) -> InboundOut:
    out = InboundOut.model_validate(message)
    out.intent = intent_out(message.intent) if message.intent else None
    if message.thread is not None and message.thread.packet is not None:
        out.packet_id = message.thread.packet_id
        out.rightsholder_name = message.thread.packet.rightsholder.name
    return out


def thread_out(thread: MailThread, settings) -> ThreadOut:
    """`reply_to` is derived from the token and the configured domain, not stored."""
    return ThreadOut(
        id=thread.id, packet_id=thread.packet_id,
        reply_to=mail.reply_to_address(thread.token, settings),
        closed_at=thread.closed_at, created_at=thread.created_at,
        outbound=[outbound_out(m) for m in thread.outbound],
        inbound=[inbound_out(m) for m in thread.inbound],
    )


def _packet(session: Session, packet_id: str) -> OutreachPacket:
    """Loaded and scoped exactly as in the outreach router; the webhook never uses this."""
    packet = session.scalar(
        select(OutreachPacket).where(OutreachPacket.id == packet_id)
        .options(selectinload(OutreachPacket.rightsholder), selectinload(OutreachPacket.project),
                 selectinload(OutreachPacket.thread),
                 selectinload(OutreachPacket.items).selectinload(PacketTask.task)
                 .selectinload(ClearanceTask.asset)))
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped(packet.project, session)
    return packet


def _html_to_text(html: str) -> str:
    """A plain-text part good enough to read, without pulling in a parser.

    The HTML is ours and comes from our own templates, so the shape is known; this is a
    fallback body, not a rendering engine.
    """
    import re
    from html import unescape

    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?i)</td>", "  ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1])).strip()


# ---------------------------------------------------------------- sending

@router.post("/api/packets/{packet_id}/send", response_model=OutboundOut, dependencies=WRITE)
def send_packet(packet_id: str, body: SendRequest, session: Session = Depends(db),
                user_id: str = Depends(current_user_id)):
    """Send the finalized letter and open the reply thread.

    Finalization is required first: the frozen HTML is what gets mailed, so the thing sent and
    the thing recorded cannot drift apart.
    """
    packet = _packet(session, packet_id)
    settings = get_settings()

    if packet.status != "finalized" or not packet.rendered_html:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Finalize the packet before sending it. The frozen letter is what goes out.")

    contact = effective_contact(packet.rightsholder)
    to_email = (packet.recipient_email or contact["licensing_email"] or "").strip()
    try:
        mail.check_recipient(to_email, settings, is_placeholder=contact["is_placeholder"],
                             allow_unverified=body.allow_unverified)
    except mail.MailError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    set_actor(session, Actor(ActorType.user, user_id, body.reason or "Sent outreach packet"))

    thread = packet.thread
    if thread is None:
        thread = MailThread(packet_id=packet.id, token=mail.new_thread_token())
        session.add(thread)
        session.flush()

    reply_to = mail.reply_to_address(thread.token, settings)
    outgoing = mail.Outgoing(
        to_email=to_email, subject=packet.subject or "Clearance request",
        body_html=packet.rendered_html, body_text=_html_to_text(packet.rendered_html),
        reply_to=reply_to, from_email=settings.mail_from, from_name=settings.mail_from_name)

    message = OutboundMessage(
        thread_id=thread.id, to_email=to_email, from_email=settings.mail_from, reply_to=reply_to,
        subject=outgoing.subject, body_html=outgoing.body_html, body_text=outgoing.body_text,
        provider=(settings.mail_provider or "console").lower(), status="queued", sent_by=user_id)
    session.add(message)

    try:
        result = mail.send(outgoing, settings)
    except mail.MailError as exc:
        # Record the failure rather than losing it: a bounced send is part of the trail.
        message.status, message.error = "failed", str(exc)
        session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    message.status = "sent"
    message.provider_message_id = result.message_id
    message.sent_at = datetime.now(UTC)
    message.note = result.note
    session.commit()
    return outbound_out(message)


@router.get("/api/packets/{packet_id}/thread", response_model=ThreadOut)
def get_thread(packet_id: str, session: Session = Depends(db)):
    packet = _packet(session, packet_id)
    if packet.thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This packet has not been sent yet.")
    return thread_out(packet.thread, get_settings())


# ---------------------------------------------------------------- inbound webhook

def _tasks_for(thread: MailThread) -> list[ClearanceTask]:
    return [item.task for item in thread.packet.items if item.task is not None]


def _org_of(session: Session, thread: MailThread) -> str | None:
    """The organization a reply belongs to, reached through packet -> project."""
    from app.models import Project

    project = session.get(Project, thread.packet.project_id)
    return project.org_id if project is not None else None


@public_router.post("/api/mail/inbound", response_model=InboundAck)
async def inbound(request: Request, session: Session = Depends(get_session)):
    """Receive a reply, store it, and read it if we can.

    Storing comes first and parsing second, on purpose: a reply that arrived must survive
    even when the parser is unavailable or wrong.
    """
    raw = await request.body()
    settings = get_settings()
    try:
        mail.verify_signature(raw, dict(request.headers), settings)
    except mail.SignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        payload = await request.json()
        normalized = mail.normalize_inbound(payload, settings)
    except mail.MailError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not valid JSON.") from exc

    existing = session.scalar(select(InboundMessage).where(
        InboundMessage.provider == normalized.provider,
        InboundMessage.provider_message_id == normalized.message_id))
    if existing is not None:
        # Webhook delivery is at-least-once; a retry must not produce a second reading.
        return InboundAck(status="duplicate", inbound_id=existing.id)

    token = mail.token_from_address(normalized.to_email, *normalized.recipients)
    thread = session.scalar(
        select(MailThread).where(MailThread.token == token)
        .options(selectinload(MailThread.packet).selectinload(OutreachPacket.items)
                 .selectinload(PacketTask.task).selectinload(ClearanceTask.asset))) if token else None

    if thread is not None and thread.packet is not None:
        # The webhook is unauthenticated, so the tenant comes from the thread rather than
        # from a caller. Set before the first write, so every audit row it causes is owned.
        session.info["org_id"] = thread.packet.project_id and _org_of(session, thread)

    message = InboundMessage(
        thread_id=thread.id if thread else None, provider=normalized.provider,
        provider_message_id=normalized.message_id, from_email=normalized.from_email[:300],
        from_name=normalized.from_name, to_email=normalized.to_email,
        subject=normalized.subject, text_body=mail.strip_quoted(normalized.text_body or ""),
        status="received" if thread else "unroutable",
    )
    if thread is None:
        message.error = "No open thread matched the address this reply was sent to."
    session.add(message)
    session.commit()

    if thread is None:
        # Same 200 either way: the webhook must not become an oracle for live tokens.
        log.warning("Unroutable inbound message %s", message.id)
        return InboundAck(status="stored", inbound_id=message.id)

    proposals = _read_reply(session, message, thread, settings)
    return InboundAck(status="stored", inbound_id=message.id, proposals=proposals)


def _read_reply(session: Session, message: InboundMessage, thread: MailThread, settings) -> int:
    """Parse and persist. Never raises: a failed reading must not lose the reply."""
    tasks = _tasks_for(thread)
    try:
        with acting_as(session, ActorType.llm, settings.reply_parser_model, "Read inbound reply"):
            intent, changes = replies.parse(message, tasks, settings)
            session.add(intent)
            message.status = "parsed"
            session.flush()
    except replies.ParserUnavailable as exc:
        message.status, message.error = "received", str(exc)
        session.commit()
        log.info("Reply %s stored without a reading: %s", message.id, exc)
        return 0
    except Exception as exc:  # noqa: BLE001 - SDK and network errors are all non-fatal here
        session.rollback()
        stored = session.get(InboundMessage, message.id)
        if stored is not None:
            stored.status, stored.error = "failed", f"Could not read this reply: {exc}"
            session.commit()
        log.exception("Reply parsing failed for %s", message.id)
        return 0

    by_id = {task.id: task for task in tasks}
    applied = 0
    for change in changes:
        if not replies.can_auto_apply(change, settings):
            continue
        task = by_id.get(change.task_id)
        if task is None:
            continue
        try:
            with acting_as(session, ActorType.system, "reply_auto_apply",
                           f"Auto-applied from reply {message.id}"):
                replies.apply_change(change, task)
        except workflow.WorkflowError as exc:
            change.blocked_reason = str(exc)
            continue
        change.status = "applied"
        change.decided_by = "system:auto_apply"
        change.decided_at = utcnow()
        applied += 1

    session.commit()
    if applied:
        log.info("Auto-applied %d change(s) from reply %s", applied, message.id)
    return len(changes)


# ---------------------------------------------------------------- inbox + queue

@router.get("/api/projects/{project_id}/inbox", response_model=list[InboundOut])
def inbox(project_id: str, limit: int = 100, session: Session = Depends(db)):
    scoped_project(session, project_id)
    rows = session.scalars(
        select(InboundMessage)
        .join(MailThread, MailThread.id == InboundMessage.thread_id)
        .join(OutreachPacket, OutreachPacket.id == MailThread.packet_id)
        .where(OutreachPacket.project_id == project_id)
        .options(selectinload(InboundMessage.intent).selectinload(ReplyIntent.changes)
                 .selectinload(ProposedChange.task).selectinload(ClearanceTask.asset),
                 selectinload(InboundMessage.thread).selectinload(MailThread.packet)
                 .selectinload(OutreachPacket.rightsholder))
        .order_by(InboundMessage.received_at.desc()).limit(min(limit, 500))).all()
    return [inbound_out(m) for m in rows]


@router.get("/api/projects/{project_id}/proposed-changes", response_model=list[ProposedChangeOut])
def proposed_changes(project_id: str, status_filter: str = "pending", session: Session = Depends(db)):
    """The human-confirm queue. Blocked proposals are included — with their reason."""
    scoped_project(session, project_id)
    stmt = (select(ProposedChange)
            .join(ClearanceTask, ClearanceTask.id == ProposedChange.task_id)
            .join(Asset, Asset.id == ClearanceTask.asset_id)
            .where(Asset.project_id == project_id)
            .options(selectinload(ProposedChange.task).selectinload(ClearanceTask.asset))
            .order_by(ProposedChange.created_at.desc()))
    if status_filter and status_filter != "all":
        stmt = stmt.where(ProposedChange.status == status_filter)
    return [change_out(c) for c in session.scalars(stmt).all()]


def _load_change(session: Session, change_id: str) -> ProposedChange:
    change = session.scalar(
        select(ProposedChange).where(ProposedChange.id == change_id)
        .options(selectinload(ProposedChange.task).selectinload(ClearanceTask.asset)))
    if change is None or change.task is None or change.task.asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped(change.task.asset.project, session)
    return change


@router.post("/api/proposed-changes/{change_id}/apply", response_model=ProposedChangeOut,
             dependencies=WRITE)
def apply_proposal(change_id: str, body: ApplyRequest, session: Session = Depends(db),
                   user_id: str = Depends(current_user_id)):
    """Confirm a proposal. The workflow is re-checked now, not trusted from when it was made."""
    change = _load_change(session, change_id)
    if change.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This proposal was already {change.status}.")

    if body.quoted_amount is not None:
        change.quoted_amount = body.quoted_amount

    reason = body.reason or f"Confirmed from reply reading {change.intent_id}"
    set_actor(session, Actor(ActorType.user, user_id, reason))
    try:
        replies.apply_change(change, change.task)
    except workflow.WorkflowError as exc:
        # Surface it and keep the proposal pending: the task may just need another step first.
        change.blocked_reason = str(exc)
        session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    change.status = "applied"
    change.blocked_reason = None
    change.decided_by = user_id
    change.decided_at = utcnow()

    # Any other pending proposal for the same task is now reading a stale stage.
    for other in session.scalars(select(ProposedChange).where(
            ProposedChange.task_id == change.task_id, ProposedChange.status == "pending",
            ProposedChange.id != change.id)):
        other.status = "superseded"
        other.decided_by = user_id
        other.decided_at = utcnow()

    session.commit()
    return change_out(change)


@router.post("/api/proposed-changes/{change_id}/reject", response_model=ProposedChangeOut,
             dependencies=WRITE)
def reject_proposal(change_id: str, body: DecisionRequest, session: Session = Depends(db),
                    user_id: str = Depends(current_user_id)):
    change = _load_change(session, change_id)
    if change.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This proposal was already {change.status}.")
    set_actor(session, Actor(ActorType.user, user_id, body.reason or "Rejected the reply reading"))
    change.status = "rejected"
    change.decided_by = user_id
    change.decided_at = utcnow()
    session.commit()
    return change_out(change)


# ---------------------------------------------------------------- ledger

@router.get("/api/projects/{project_id}/ledger", response_model=LedgerOut)
def cost_ledger(project_id: str, session: Session = Depends(db)):
    """Estimated vs quoted vs signed, per task, with the variance against the estimate."""
    scoped_project(session, project_id)
    tasks = list(session.scalars(
        select(ClearanceTask).join(Asset, Asset.id == ClearanceTask.asset_id)
        .where(Asset.project_id == project_id)
        .options(selectinload(ClearanceTask.asset), selectinload(ClearanceTask.rightsholder))
        .order_by(Asset.created_at, ClearanceTask.layer)))

    report = ledger.build(tasks)
    return LedgerOut(
        lines=[{
            "task_id": line.task.id, "asset_id": line.task.asset_id,
            "asset_title": line.task.asset.title, "layer": line.task.layer,
            "stage": line.task.stage,
            "rightsholder_name": line.task.rightsholder.name if line.task.rightsholder else None,
            "estimate_low": line.estimate_low, "estimate_high": line.estimate_high,
            "quoted": line.quoted, "agreed": line.agreed, "exposure": line.exposure,
            "basis": line.basis, "variance": line.variance, "closed": line.closed,
        } for line in report["lines"]],
        totals=report["totals"],
    )
