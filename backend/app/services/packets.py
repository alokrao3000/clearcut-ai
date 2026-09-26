"""Build, group and render outreach packets.

A packet is addressed to a *licensing intake*, not to a task. A desk that handles six clips
from the same archive wants one letter listing six items, so the grouping key is the
effective contact — which may be a parent of the assigned rightsholder, since WB Animation's
mail goes to WB Discovery.

Two rules are enforced here rather than left to the templates:

1. **Internal budget estimates never reach the recipient-facing render.** Quoting our own
   range to a licensing desk anchors the negotiation against the production. Estimates
   appear only when `internal=True`, which the public token route can never set.
2. **The screenplay is never a template variable.** Only frozen, individually selected
   excerpts are exposed, and only as images, from the context view.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import DISCLAIMER_TEXT
from app.enums import DistributionScope, Layer, ProductionTier, RightsholderKind, Stage
from app.models import ClearanceTask, OutreachPacket, Project, Rightsholder
from app.services import pdf
from app.services.mapping import effective_contact

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

DEFAULT_TEMPLATE = "clip_clearance_request"

# Every template a packet may use, with the wording a producer picks from. The registry is
# the allowlist: `template` arrives from the client, so it is never used to build a path.
TEMPLATES: dict[str, str] = {
    "clip_clearance_request": "Clip clearance request — studios and production companies",
    "news_footage_request": "News footage request — broadcasters and news archives",
    "master_use_request": "Master use request — record labels",
    "sync_license_request": "Synchronisation licence request — music publishers",
    "stock_license_quote": "Quotation request — stock agencies",
    "archival_reproduction_request": "Reproduction request — archives and libraries",
    "deal_memo_short_form": "Short-form deal memo — once a fee is agreed",
}

# Fallback when a directory entry carries no template preference.
KIND_TEMPLATE: dict[str, str] = {
    RightsholderKind.studio: "clip_clearance_request",
    RightsholderKind.broadcaster: "news_footage_request",
    RightsholderKind.label: "master_use_request",
    RightsholderKind.publisher: "sync_license_request",
    RightsholderKind.stock_agency: "stock_license_quote",
    RightsholderKind.archive: "archival_reproduction_request",
    RightsholderKind.individual: "clip_clearance_request",
    RightsholderKind.brand: "clip_clearance_request",
}

LAYER_LABEL: dict[str, str] = {
    Layer.footage: "Footage licence",
    Layer.still_image: "Still image licence",
    Layer.master_recording: "Master use",
    Layer.composition: "Synchronisation",
    Layer.performance: "Performance / likeness",
    Layer.trademark: "Trademark / logo",
}

SCOPE_LABEL: dict[str, str] = {
    DistributionScope.festival: "Festival exhibition only",
    DistributionScope.worldwide_streaming: "Worldwide streaming",
    DistributionScope.all_media_perpetual: "All media, in perpetuity",
}

TIER_LABEL: dict[str, str] = {
    ProductionTier.ultra_low: "Ultra-low-budget independent feature",
    ProductionTier.sag_moderate_low: "SAG moderate-low-budget feature",
    ProductionTier.studio_feature: "Studio feature",
}

# Territory and term the letter asks for, derived from the project's distribution scope so
# the ask cannot silently contradict the budget the estimate was priced against.
SCOPE_TERMS: dict[str, tuple[str, str]] = {
    DistributionScope.festival: ("Worldwide, festival exhibition and non-theatrical promotion",
                                 "Three (3) years from first festival screening"),
    DistributionScope.worldwide_streaming: ("Worldwide", "Five (5) years from first release"),
    DistributionScope.all_media_perpetual: ("Worldwide, all media now known or hereafter devised",
                                            "In perpetuity"),
}

STAGE_LABEL: dict[str, str] = {
    Stage.sourced: "Sourced",
    Stage.rights_mapped: "Rights mapped",
    Stage.budget_approved: "Budget approved",
    Stage.outreach_sent: "Outreach sent",
    Stage.quote_received: "Quote received",
    Stage.deal_memo_signed: "Deal memo signed",
    Stage.denied: "Denied",
    Stage.dropped: "Dropped",
}

# A packet is an outreach action, so it only makes sense for tasks that have not been sent
# yet or are mid-conversation. Denied and dropped tasks are excluded from grouping.
PACKETABLE_STAGES = {Stage.rights_mapped, Stage.budget_approved, Stage.outreach_sent,
                     Stage.quote_received}


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class PacketError(ValueError):
    """A packet cannot be built as asked. The message is shown to the user verbatim."""


# ---------------------------------------------------------------- grouping


def intake_for(task: ClearanceTask) -> dict | None:
    """The licensing desk this task's letter goes to, or None if nothing is assigned."""
    if task.rightsholder is None:
        return None
    contact = effective_contact(task.rightsholder)
    if contact["via_rightsholder_id"] is None:
        # No intake anywhere up the chain: address the assigned entity itself and let the
        # UI show the missing email rather than silently dropping the task from grouping.
        return {"via_rightsholder_id": task.rightsholder.id, "via_name": task.rightsholder.name,
                "licensing_email": None, "address": task.rightsholder.address,
                "preferred_templates": task.rightsholder.preferred_templates or [],
                "is_placeholder": task.rightsholder.is_placeholder}
    return contact


def group_tasks(tasks: list[ClearanceTask]) -> dict[str, list[ClearanceTask]]:
    """Bucket tasks by the intake that would receive their letter, preserving order."""
    groups: dict[str, list[ClearanceTask]] = {}
    for task in tasks:
        intake = intake_for(task)
        if intake is None:
            continue
        groups.setdefault(intake["via_rightsholder_id"], []).append(task)
    return groups


def packetable_tasks(session: Session, project_id: str) -> list[ClearanceTask]:
    from app.models import Asset

    return list(session.scalars(
        select(ClearanceTask)
        .join(Asset, Asset.id == ClearanceTask.asset_id)
        .where(Asset.project_id == project_id,
               ClearanceTask.stage.in_([s.value for s in PACKETABLE_STAGES]),
               ClearanceTask.rightsholder_id.is_not(None))
        .options(selectinload(ClearanceTask.asset), selectinload(ClearanceTask.rightsholder))
        .order_by(ClearanceTask.created_at)))


# ---------------------------------------------------------------- template choice


def choose_template(rightsholder: Rightsholder) -> str:
    """First preference we actually have a template for, else the kind default."""
    for name in rightsholder.preferred_templates or []:
        if name in TEMPLATES:
            return name
    return KIND_TEMPLATE.get(rightsholder.kind, DEFAULT_TEMPLATE)


def validate_template(name: str) -> str:
    if name not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise PacketError(f"Unknown template '{name}'. Available: {known}.")
    return name


def default_subject(project: Project, tasks: list[ClearanceTask]) -> str:
    layers = {LAYER_LABEL.get(t.layer, t.layer) for t in tasks}
    what = next(iter(layers)) if len(layers) == 1 else f"{len(tasks)} items"
    return f"Clearance request — {project.name} — {what}"


# ---------------------------------------------------------------- render context


def _money(low: Decimal | None, high: Decimal | None) -> str | None:
    if low is None or high is None:
        return None
    return f"${low:,.0f} – ${high:,.0f}"


def _usage(task: ClearanceTask) -> str | None:
    seconds = task.asset.usage_seconds
    if not seconds:
        return None
    if seconds < 60:
        return f"Approx. {seconds} seconds on screen"
    minutes, rest = divmod(seconds, 60)
    tail = f" {rest}s" if rest else ""
    return f"Approx. {minutes}m{tail} on screen"


def _source(task: ClearanceTask) -> str | None:
    """What to show a rightsholder as the item's origin.

    Script-sourced assets carry an internal `script:<id>#scene-N` locator, which means
    nothing to a recipient and leaks our internal ids, so it is suppressed.
    """
    asset = task.asset
    if asset.raw_source and asset.raw_source.startswith("script:"):
        return None
    parts = [p for p in (asset.platform_asset_id and f"ID {asset.platform_asset_id}",
                         asset.raw_source) if p]
    return " · ".join(parts) or None


def item_context(task: ClearanceTask, *, internal: bool) -> dict:
    asset = task.asset
    item = {
        "task_id": task.id,
        "title": asset.title,
        "owner_name": asset.owner_name,
        "source": _source(task),
        "layer": task.layer,
        "layer_label": LAYER_LABEL.get(task.layer, task.layer),
        "usage": _usage(task),
        "context": asset.user_notes,
        "published_at": asset.published_at,
    }
    if internal:
        item["estimate"] = _money(task.estimate_low, task.estimate_high)
        item["stage_label"] = STAGE_LABEL.get(task.stage, task.stage)
    return item


def project_context(project: Project) -> dict:
    territory, term = SCOPE_TERMS.get(project.distribution_scope, ("Worldwide", "To be agreed"))
    return {
        "name": project.name,
        "scope_label": SCOPE_LABEL.get(project.distribution_scope, project.distribution_scope),
        "tier_label": TIER_LABEL.get(project.production_tier, project.production_tier),
        "territory": territory,
        "term": term,
    }


def build_context(packet: OutreachPacket, *, internal: bool, watermark: str | None = None,
                  context_view_url: str | None = None,
                  context_view_expires: str | None = None) -> dict:
    tasks = [item.task for item in packet.items if item.task is not None]
    return {
        "packet": packet,
        "project": project_context(packet.project),
        "rightsholder": packet.rightsholder,
        "items": [item_context(task, internal=internal) for task in tasks],
        "today": datetime.now(UTC).strftime("%d %B %Y"),
        "disclaimer": DISCLAIMER_TEXT,
        "internal": internal,
        "watermark": watermark,
        "context_view_url": context_view_url,
        "context_view_expires": context_view_expires,
    }


# ---------------------------------------------------------------- rendering


def render_html(packet: OutreachPacket, *, internal: bool = False, **kwargs) -> str:
    """Render the letter. `internal=True` adds the estimates panel, never sent to a recipient."""
    name = validate_template(packet.template)
    try:
        template = _env.get_template(f"outreach/{name}.html")
    except TemplateNotFound as exc:  # registry and disk out of step
        raise PacketError(f"Template '{name}' is registered but its file is missing.") from exc
    return template.render(**build_context(packet, internal=internal, **kwargs))


def render_pdf(packet: OutreachPacket, **kwargs) -> bytes:
    """PDF of the recipient-facing letter. Raises pdf.PdfUnavailable without the native stack."""
    html = render_html(packet, internal=False, **kwargs)
    return pdf.render(html, base_url=str(TEMPLATE_DIR))


def render_context_view(packet: OutreachPacket, view, excerpts: list[dict], *,
                        watermark_tile: str) -> str:
    """The recipient-facing context page. Excerpts arrive pre-rendered as image URLs."""
    template = _env.get_template("context/view.html")
    return template.render(
        project=project_context(packet.project),
        rightsholder=packet.rightsholder,
        view=view,
        items=[item_context(item.task, internal=False) for item in packet.items if item.task],
        excerpts=excerpts,
        watermark_tile=watermark_tile,
        expires_on=view.expires_at.strftime("%d %B %Y"),
        issued_on=view.created_at.strftime("%d %B %Y"),
        disclaimer=DISCLAIMER_TEXT,
    )


def render_unavailable() -> str:
    return _env.get_template("context/unavailable.html").render()
