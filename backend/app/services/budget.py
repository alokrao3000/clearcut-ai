"""Budget estimation matrix.

Estimated fee = base rate (Studio Feature / Worldwide Streaming reference)
                x distribution multiplier x production tier factor x billable units.

Every estimate stores its full breakdown so the number can be explained and audited.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DistributionScope, Layer, ProductionTier, RateUnit, Stage
from app.models import ClearanceTask, Project, RateCard, Rightsholder

DISTRIBUTION_MULTIPLIER: dict[DistributionScope, Decimal] = {
    DistributionScope.festival: Decimal("0.35"),
    DistributionScope.worldwide_streaming: Decimal("1.00"),
    DistributionScope.all_media_perpetual: Decimal("1.80"),
}
TIER_FACTOR: dict[ProductionTier, Decimal] = {
    ProductionTier.ultra_low: Decimal("0.50"),
    ProductionTier.sag_moderate_low: Decimal("0.75"),
    ProductionTier.studio_feature: Decimal("1.00"),
}
ROUND_TO = Decimal(50)
RECOMMENDED_CONTINGENCY = Decimal("0.15")

UNIT_LABEL = {RateUnit.per_minute: "per clip minute", RateUnit.per_use: "per use", RateUnit.per_image: "per image"}
SCOPE_LABEL = {
    DistributionScope.festival: "Film Festivals Only",
    DistributionScope.worldwide_streaming: "Worldwide Streaming",
    DistributionScope.all_media_perpetual: "All Media Perpetual",
}
LAYER_LABEL = {
    Layer.footage: "footage", Layer.still_image: "still image", Layer.master_recording: "master recording",
    Layer.composition: "composition (sync)", Layer.performance: "performer likeness", Layer.trademark: "trademark",
}


def _round(value: Decimal) -> Decimal:
    return (value / ROUND_TO).quantize(Decimal(1), rounding=ROUND_HALF_UP) * ROUND_TO


def _visible_cards(session: Session):
    """Rate cards this session may price against: the shared ones plus its own.

    Same rule and the same fail-closed default as the rightsholder directory — one tenant's
    negotiated rate must never set another tenant's budget.
    """
    org_id = session.info.get("org_id")
    if org_id is None:
        return RateCard.org_id.is_(None)
    return (RateCard.org_id.is_(None)) | (RateCard.org_id == org_id)


def find_rate_card(session: Session, rh: Rightsholder | None, layer: Layer) -> tuple[RateCard | None, str]:
    visible = _visible_cards(session)
    node, depth, seen = rh, 0, set()
    while node is not None and node.id not in seen:
        seen.add(node.id)
        card = session.scalar(select(RateCard).where(
            RateCard.rightsholder_id == node.id, RateCard.layer == layer, visible))
        if card:
            return card, "rightsholder" if depth == 0 else f"parent:{node.id}"
        node, depth = node.parent, depth + 1
    card = session.scalar(select(RateCard).where(
        RateCard.rightsholder_id.is_(None), RateCard.layer == layer, visible))
    return card, "industry_default"


def estimate_task(session: Session, task: ClearanceTask, project: Project) -> None:
    layer = Layer(task.layer)
    rh = task.rightsholder
    card, basis = find_rate_card(session, rh, layer)
    assumptions: list[str] = []
    if rh is None:
        assumptions.append("No rightsholder assigned; using the industry default rate.")
    if card is None:
        task.estimate_low = task.estimate_high = None
        task.estimate_breakdown = {"assumptions": assumptions + [f"No rate card for layer '{layer}'."]}
        return

    unit = RateUnit(card.unit)
    usage = task.asset.usage_seconds
    if unit is RateUnit.per_minute:
        if usage is None:
            units = card.minimum_units
            assumptions.append(f"Planned usage not set; assumed the {card.minimum_units:g}-minute minimum.")
        else:
            units = max(math.ceil(usage / 6) / 10, card.minimum_units)  # tenth-of-a-minute resolution
    else:
        units = 1.0
    if card.is_placeholder:
        assumptions.append("Rate card is unverified placeholder data.")

    scope, tier = DistributionScope(project.distribution_scope), ProductionTier(project.production_tier)
    dist, tier_f, u = DISTRIBUTION_MULTIPLIER[scope], TIER_FACTOR[tier], Decimal(str(units))
    low = _round(card.base_low * dist * tier_f * u)
    high = max(_round(card.base_high * dist * tier_f * u), low)

    who = rh.name if rh else "Typical rightsholder"
    task.estimate_low, task.estimate_high = low, high
    task.estimate_breakdown = {
        "formula": "base x distribution_multiplier x tier_factor x units",
        "rate_card_id": card.id,
        "rate_basis": basis,
        "unit": unit.value,
        "base_low": str(card.base_low),
        "base_high": str(card.base_high),
        "units": units,
        "distribution_scope": scope.value,
        "distribution_multiplier": str(dist),
        "production_tier": tier.value,
        "tier_factor": str(tier_f),
        "assumptions": assumptions,
        "summary": (
            f"{who} {LAYER_LABEL[layer]} clearance for {SCOPE_LABEL[scope]} typically runs "
            f"${card.base_low * dist * tier_f:,.0f} - ${card.base_high * dist * tier_f:,.0f} {UNIT_LABEL[unit]}."
        ),
    }


ACTIVE_STAGES = {s for s in Stage} - {Stage.denied, Stage.dropped}


def project_totals(tasks: list[ClearanceTask]) -> dict:
    active = [t for t in tasks if t.stage in ACTIVE_STAGES]
    est_low = sum((t.estimate_low or Decimal(0) for t in active), Decimal(0))
    est_high = sum((t.estimate_high or Decimal(0) for t in active), Decimal(0))
    quoted = sum((t.quoted_amount or Decimal(0) for t in active), Decimal(0))
    agreed = sum((t.agreed_amount or Decimal(0) for t in active), Decimal(0))
    return {
        "active_tasks": len(active),
        "unestimated_tasks": sum(1 for t in active if t.estimate_high is None),
        "estimate_low": est_low,
        "estimate_high": est_high,
        "recommended_contingency": _round(est_high * RECOMMENDED_CONTINGENCY),
        "quoted_total": quoted,
        "agreed_total": agreed,
    }
