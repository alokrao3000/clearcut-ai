"""Read a rightsholder's reply and propose — never apply — what it means.

The model is given the reply and the list of tasks the letter asked about, and returns one
reading per task it can speak to. It does not move anything. Every reading becomes a
`ProposedChange` that a human confirms, because the failure mode here is a misread fee
becoming a number in a production budget.

Three rules keep that honest:

* **Every proposal quotes the reply.** `quote_text` is copied verbatim from the message, so a
  producer confirms against the rightsholder's own words rather than a paraphrase.
* **The workflow still rules.** A proposal is checked against `workflow.allowed_targets` and
  the stage guards before it is offered; one that cannot be applied is shown with the reason,
  not silently dropped.
* **Money always needs a person.** Auto-apply, where it is switched on at all, refuses any
  proposal carrying an amount.

Without credentials the loop still records replies. It just stops proposing, which is the
safe direction to fail in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from app.config import Settings
from app.enums import REPLY_TARGET_STAGE, ReplyKind, Stage
from app.models import ClearanceTask, InboundMessage, ProposedChange, ReplyIntent
from app.services import workflow
from app.services.packets import LAYER_LABEL

log = logging.getLogger(__name__)

KIND_VALUES = tuple(k.value for k in ReplyKind)

SYSTEM_PROMPT = """You read replies from film and music rights holders for a clearance team.

You are given one reply and the list of items the original letter asked about. Decide, for
each item the reply actually speaks to, what the sender is saying.

Kinds:
- approved: they agree to license it. Use this even when no fee is named.
- quote: they name a fee, or a fee range, for the item.
- denied: they refuse, or say they do not control it and name no successor.
- needs_info: they want something from us before they can answer.
- unclear: they mention the item but you cannot tell what they mean.

Rules:
- Only report an item if the reply genuinely addresses it. A reply about one song says
  nothing about the other three items; leave those out.
- When a reply covers everything at once ("we can license all of the below at $1,500 each"),
  report every item it covers, each with the same quote.
- `quote_text` must be copied verbatim from the reply, as the shortest span that carries the
  meaning. Never paraphrase and never invent.
- `amount` is a single number with no currency symbol or separators. For a range, give the
  upper figure and say so in `note`. If no figure is named, leave it null — never guess one.
- An approval with no fee named is `approved` with a null amount, not a quote of zero. Zero
  means they said it is free.
- confidence: 0.9+ the reply is explicit, 0.6-0.9 clear in context, below 0.6 a judgement call.
- Out-of-office replies, acknowledgements and "we are looking into it" are needs_info about
  nothing, so return no items at all.

The overall `kind` summarises the message. Use the strongest reading present: a reply that
quotes one item and denies another is a quote overall."""

MISSING_CREDENTIALS = (
    "No Claude credentials found. Set CLEARCUT_ANTHROPIC_API_KEY, or ANTHROPIC_API_KEY, "
    "or sign in with `ant auth login`."
)


class ParserUnavailable(RuntimeError):
    """No credentials or SDK. The reply is still stored; it just gets no reading."""


class ItemReading(BaseModel):
    """What the reply says about one clearance task."""

    task_ref: int = Field(description="The item number, as labelled in the input")
    kind: str = Field(description=f"One of: {', '.join(KIND_VALUES)}")
    amount: float | None = Field(default=None, description="Fee named for this item, if any")
    currency: str | None = Field(default=None, description="ISO code if the reply names one, e.g. USD")
    quote_text: str = Field(description="The exact span of the reply that carries this")
    confidence: float = Field(ge=0.0, le=1.0)
    note: str | None = Field(default=None, description="One sentence of context, if it helps")


class ReplyReading(BaseModel):
    kind: str = Field(description=f"Overall reading. One of: {', '.join(KIND_VALUES)}")
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="One sentence a producer can scan")
    reasoning: str | None = Field(default=None, description="Why you read it this way")
    items: list[ItemReading] = Field(default_factory=list)


@dataclass
class ParseOutcome:
    intent: ReplyIntent
    changes: list[ProposedChange]
    auto_applied: list[ProposedChange]


def _client(settings: Settings):
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ParserUnavailable("The anthropic SDK is not installed.") from exc
    try:
        if settings.anthropic_api_key:
            return anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return anthropic.Anthropic()
    except TypeError as exc:
        raise ParserUnavailable(MISSING_CREDENTIALS) from exc


def render_prompt(message: InboundMessage, tasks: list[ClearanceTask]) -> str:
    """Number the items so the model refers to them by position, never by our ids."""
    lines = ["Items the original letter asked about:", ""]
    for number, task in enumerate(tasks, start=1):
        title = (task.asset.title or "Untitled material").strip()
        lines.append(f"{number}. {title} — {LAYER_LABEL.get(task.layer, task.layer)}")
    lines += ["", f"Reply from: {message.from_email}", f"Subject: {message.subject or '(none)'}",
              "", "<reply>", message.text_body.strip(), "</reply>"]
    return "\n".join(lines)


def _amount(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def _proposal(task: ClearanceTask, reading: ItemReading) -> ProposedChange:
    """Turn one reading into a proposal, pre-checked against the workflow.

    The check happens now rather than at confirm time so the queue tells a producer what is
    actually actionable, instead of handing them a button that will fail.
    """
    kind = ReplyKind(reading.kind) if reading.kind in KIND_VALUES else ReplyKind.unclear
    current = Stage(task.stage)
    target = REPLY_TARGET_STAGE.get(kind)
    amount = _amount(reading.amount)

    blocked: str | None = None
    if target is None:
        blocked = "Correspondence only — nothing to move."
    elif target is current:
        blocked = f"Task is already {current.value.replace('_', ' ')}."
    elif target not in workflow.allowed_targets(current):
        allowed = ", ".join(sorted(s.value for s in workflow.allowed_targets(current))) or "none"
        blocked = (f"Cannot move from '{current.value}' to '{target.value}'. Allowed: {allowed}.")
    elif target is Stage.quote_received and amount is None and task.quoted_amount is None:
        blocked = "No fee named, and none recorded yet — add the amount before moving this on."

    return ProposedChange(
        task_id=task.id, kind=kind.value, from_stage=current.value,
        to_stage=target.value if target else None, quoted_amount=amount,
        currency=(reading.currency or None), quote_text=reading.quote_text.strip()[:4000],
        confidence=reading.confidence, note=reading.note, status="pending",
        blocked_reason=blocked,
    )


def parse(message: InboundMessage, tasks: list[ClearanceTask], settings: Settings,
          client=None) -> tuple[ReplyIntent, list[ProposedChange]]:
    """One network call. Returns the intent and its proposals, neither of them persisted."""
    if not tasks:
        raise ParserUnavailable("This thread has no clearance tasks to read the reply against.")

    client = client or _client(settings)
    try:
        response = client.messages.parse(
            model=settings.reply_parser_model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": render_prompt(message, tasks)}],
            output_format=ReplyReading,
        )
    except TypeError as exc:
        # The SDK resolves credentials lazily and raises a bare TypeError when it cannot.
        raise ParserUnavailable(MISSING_CREDENTIALS) from exc

    reading: ReplyReading = response.parsed
    kind = reading.kind if reading.kind in KIND_VALUES else ReplyKind.unclear.value
    intent = ReplyIntent(
        inbound_id=message.id, model=settings.reply_parser_model, kind=kind,
        confidence=reading.confidence, summary=reading.summary.strip()[:2000],
        reasoning=reading.reasoning,
    )

    changes: list[ProposedChange] = []
    seen: set[str] = set()
    for item in reading.items:
        index = item.task_ref - 1
        if not 0 <= index < len(tasks):
            log.warning("Dropping reading for unknown item %s", item.task_ref)
            continue
        task = tasks[index]
        if task.id in seen:  # one proposal per task; the first reading wins
            continue
        if not item.quote_text.strip():
            continue
        seen.add(task.id)
        changes.append(_proposal(task, item))

    intent.changes = changes
    return intent, changes


# ---------------------------------------------------------------- applying


def can_auto_apply(change: ProposedChange, settings: Settings) -> bool:
    """Whether this proposal may skip human confirmation.

    Off unless switched on, above the confidence floor, unblocked, and never for a proposal
    that carries a figure. A wrong stage is an annoyance a producer will spot on the board;
    a wrong fee is a number that ends up in a budget.
    """
    if not settings.auto_apply_replies:
        return False
    if change.blocked_reason or change.to_stage is None:
        return False
    if change.quoted_amount is not None:
        return False
    return (change.confidence or 0.0) >= settings.auto_apply_min_confidence


def apply_change(change: ProposedChange, task: ClearanceTask) -> None:
    """Move the task as proposed. Raises WorkflowError if the guard refuses it.

    Re-checked here rather than trusted from `blocked_reason`: the task may have moved
    between the reply arriving and a human getting to it.
    """
    if change.to_stage is None:
        raise workflow.WorkflowError("This proposal is correspondence only — there is nothing to apply.")
    if change.quoted_amount is not None:
        task.quoted_amount = change.quoted_amount
    workflow.transition(task, Stage(change.to_stage))
