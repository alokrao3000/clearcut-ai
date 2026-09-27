"""Pick who to approach for one clearance task, and show the working.

Three questions, kept separate on purpose:

1. **Can this party actually grant the right?**  `identity` — the matcher's score, raised
   when the material itself credits them (a (P) line beats a channel-name guess).
2. **Will approaching them work?**  `reliability` — how established the entity is, whether a
   human has verified the licensing intake, how direct that intake is, and (once the M5 mail
   loop has data) whether they actually reply.
3. **What will it cost?**  `cost` — the existing budget matrix, run per candidate.

Cost only breaks ties *among parties that could plausibly grant the right*. The cheapest
licence from someone who does not own the work clears nothing, so an option below
`contact_min_identity` is listed but never recommended.

Every number here carries its inputs, the same way budget estimates do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import Layer
from app.models import ClearanceTask, Rightsholder
from app.services import budget, evidence, mapping, providers
from app.services.mapping import effective_contact, normalize, score

# How established the entity is. A major has a licensing desk; an unknown may never reply.
TIER_SCORE = {"major": 100.0, "notable": 80.0, "independent": 60.0, "unknown": 40.0}
TIER_NOTE = {
    "major": "Major rightsholder with a staffed licensing desk.",
    "notable": "Established rightsholder, licenses regularly.",
    "independent": "Independent party; expect slower, less formal handling.",
    "unknown": "Standing unknown — treat the contact as unverified.",
}

# Weights for the final ranking. Identity dominates: being right matters more than being cheap.
WEIGHT_IDENTITY = 0.45
WEIGHT_RELIABILITY = 0.35
WEIGHT_COST = 0.20


@dataclass
class ContactOption:
    rightsholder_id: str
    name: str
    kind: str
    identity: float
    reliability: float
    cost_low: Decimal | None
    cost_high: Decimal | None
    overall: float
    contact: dict
    reliability_breakdown: dict
    evidence: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def recommendable(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict:
        return {
            "rightsholder_id": self.rightsholder_id,
            "name": self.name,
            "kind": self.kind,
            "identity": round(self.identity, 1),
            "reliability": round(self.reliability, 1),
            "cost_low": str(self.cost_low) if self.cost_low is not None else None,
            "cost_high": str(self.cost_high) if self.cost_high is not None else None,
            "overall": round(self.overall, 1),
            "contact": self.contact,
            "reliability_breakdown": self.reliability_breakdown,
            "evidence": self.evidence,
            "reasons": self.reasons,
            "blockers": self.blockers,
        }


# ---------------------------------------------------------------- reliability

def reliability_of(rh: Rightsholder, contact: dict) -> tuple[float, dict]:
    """Weighted over whichever components have data, so a new entity is not punished twice."""
    components: dict[str, dict] = {}

    tier = rh.tier if rh.tier in TIER_SCORE else "unknown"
    components["standing"] = {"weight": 0.35, "score": TIER_SCORE[tier], "note": TIER_NOTE[tier]}

    if rh.verified_at is not None:
        verification = {"weight": 0.25, "score": 100.0,
                        "note": f"Contact verified via {rh.verification_source or 'manual check'}."}
    elif rh.is_placeholder:
        verification = {"weight": 0.25, "score": 20.0,
                        "note": "Seed placeholder data — nobody has verified this contact."}
    else:
        verification = {"weight": 0.25, "score": 55.0, "note": "Contact entered but never verified."}
    components["verification"] = verification

    if not contact.get("licensing_email"):
        directness = {"weight": 0.20, "score": 15.0, "note": "No licensing intake on file."}
    elif contact.get("via_rightsholder_id") == rh.id:
        directness = {"weight": 0.20, "score": 100.0, "note": "Direct licensing intake."}
    else:
        directness = {"weight": 0.20, "score": 70.0,
                      "note": f"Reached via parent {contact.get('via_name')}."}
    components["contact_directness"] = directness

    if rh.outreach_attempts:
        rate = (rh.outreach_responses / rh.outreach_attempts) * 100
        note = f"Replied to {rh.outreach_responses} of {rh.outreach_attempts} approaches"
        if rh.avg_response_days:
            note += f", median {rh.avg_response_days:.0f} days"
        components["track_record"] = {"weight": 0.20, "score": round(rate, 1), "note": note + "."}

    total_weight = sum(c["weight"] for c in components.values())
    value = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    return value, {"components": components, "formula": "weighted mean of the components present"}


# ---------------------------------------------------------------- identity

def _evidence_boost(rh: Rightsholder, claims: list[evidence.OwnershipClaim]) -> tuple[float, list[dict]]:
    """A credit line naming this entity is the material asserting ownership itself."""
    names = [rh.name] + [alias.alias for alias in rh.aliases]
    matched: list[dict] = []
    best = 0.0
    for claim in claims:
        claim_norm = normalize(claim.name)
        for name in names:
            if score(claim_norm, normalize(name)) >= 88:
                matched.append(claim.to_dict())
                best = max(best, claim.strength)
                break
    return best, matched


# ---------------------------------------------------------------- resolution

@dataclass
class Resolution:
    options: list[ContactOption]
    recommended: ContactOption | None
    cheapest: ContactOption | None
    leads: list[dict]

    def to_task_fields(self) -> dict:
        recommended = None
        if self.recommended is not None:
            recommended = self.recommended.to_dict()
            recommended["why"] = self.recommended.reasons
            if self.cheapest and self.cheapest.rightsholder_id != self.recommended.rightsholder_id:
                recommended["cheaper_alternative"] = {
                    "rightsholder_id": self.cheapest.rightsholder_id,
                    "name": self.cheapest.name,
                    "cost_low": str(self.cheapest.cost_low) if self.cheapest.cost_low is not None else None,
                    "cost_high": str(self.cheapest.cost_high) if self.cheapest.cost_high is not None else None,
                    "reliability": round(self.cheapest.reliability, 1),
                }
        return {
            "contact_options": [option.to_dict() for option in self.options],
            "recommended_contact": recommended,
            "research_leads": self.leads,
        }


@dataclass
class _Probe:
    """A stand-in for a task, carrying exactly what the budget matrix reads and writes.

    Deliberately not a ClearanceTask: assigning `.asset` on a real one appends it to the
    asset's task collection, which would persist a phantom task per candidate priced.
    """

    layer: str
    stage: str
    asset: object
    rightsholder: Rightsholder | None
    estimate_low: Decimal | None = None
    estimate_high: Decimal | None = None
    estimate_breakdown: dict | None = None


def _cost_for(session: Session, task: ClearanceTask, rh: Rightsholder) -> tuple[Decimal | None, Decimal | None]:
    """Price this layer as if it were assigned to this candidate, without touching the task."""
    card, _basis = budget.find_rate_card(session, rh, Layer(task.layer))
    if card is None:
        return None, None
    probe = _Probe(layer=task.layer, stage=task.stage, asset=task.asset, rightsholder=rh)
    budget.estimate_task(session, probe, task.asset.project)
    return probe.estimate_low, probe.estimate_high


def _cost_advantage(option: ContactOption, options: list[ContactOption]) -> float:
    """100 for the cheapest priced option, 0 for the dearest; unpriced sits in the middle."""
    priced = [o.cost_high for o in options if o.cost_high is not None]
    if option.cost_high is None or len(priced) < 2:
        return 50.0
    low, high = min(priced), max(priced)
    if high == low:
        return 100.0
    return float((high - option.cost_high) / (high - low)) * 100.0


def resolve(session: Session, task: ClearanceTask, settings: Settings,
            index: list | None = None) -> Resolution:
    """Rank everyone who could grant this right, and say who to approach first."""
    layer = Layer(task.layer)
    index = index if index is not None else mapping.build_index(session)
    claims = evidence.collect(task.asset).for_layer(layer)

    candidates = mapping.rank_candidates(task, index, limit=8)
    by_id = {c.rightsholder_id: c for c in candidates}

    # Whoever is already assigned is always in the running, and ranks on how that choice was
    # made: a person picking them is a stronger signal than any name-similarity score.
    assigned_id = task.rightsholder_id
    if assigned_id and assigned_id not in by_id:
        assigned = session.get(Rightsholder, assigned_id)
        if assigned is not None:
            confidence = 100.0 if task.mapping_method == "manual" else (task.mapping_confidence or 0.0)
            by_id[assigned_id] = mapping.Candidate(
                assigned_id, assigned.name, confidence, assigned.name,
                "currently assigned" if task.mapping_method == "manual" else "auto-mapped",
            )

    # A credited party may not rank highly by name similarity alone; pull it in explicitly.
    for claim in claims:
        for rh in mapping.rightsholders_named(session, claim.name, layer):
            by_id.setdefault(rh.id, mapping.Candidate(rh.id, rh.name, 0.0, rh.name, claim.name))

    options: list[ContactOption] = []
    for rid, candidate in by_id.items():
        rh = session.get(Rightsholder, rid)
        if rh is None:
            continue
        contact = effective_contact(rh)
        boost, matched = _evidence_boost(rh, claims)
        identity = max(candidate.score, boost)
        reliability, breakdown = reliability_of(rh, contact)
        cost_low, cost_high = _cost_for(session, task, rh)

        reasons: list[str] = []
        if rh.id == task.rightsholder_id:
            reasons.append("Currently assigned to this task"
                           + (" by a person." if task.mapping_method == "manual" else " by the matcher."))
        if matched:
            reasons.append(f"The material credits them: “{matched[0]['excerpt'][:120]}”")
        elif candidate.score:
            reasons.append(f"Name match on “{candidate.matched_alias}” (score {candidate.score:.0f}).")
        reasons.append(breakdown["components"]["standing"]["note"])
        if contact.get("licensing_email") and contact.get("via_rightsholder_id") != rh.id:
            reasons.append(f"Licensing runs through {contact['via_name']}.")

        blockers: list[str] = []
        if identity < settings.contact_min_identity:
            blockers.append(
                f"Identity confidence {identity:.0f} is below the {settings.contact_min_identity:.0f} "
                "threshold — confirm they own this right before approaching them."
            )
        if not contact.get("licensing_email"):
            blockers.append("No licensing intake on file for them or any parent.")

        options.append(ContactOption(
            rightsholder_id=rh.id, name=rh.name, kind=rh.kind, identity=identity,
            reliability=reliability, cost_low=cost_low, cost_high=cost_high, overall=0.0,
            contact=contact, reliability_breakdown=breakdown, evidence=matched,
            reasons=reasons, blockers=blockers,
        ))

    for option in options:
        advantage = _cost_advantage(option, options)
        option.overall = (WEIGHT_IDENTITY * option.identity
                          + WEIGHT_RELIABILITY * option.reliability
                          + WEIGHT_COST * advantage)
        option.reliability_breakdown["cost_advantage"] = round(advantage, 1)

    options.sort(key=lambda o: (-o.overall, o.name))
    recommendable = [o for o in options if o.recommendable]
    recommended = recommendable[0] if recommendable else None

    priced = [o for o in recommendable if o.cost_high is not None]
    cheapest = min(priced, key=lambda o: o.cost_high) if priced else None

    if recommended is not None:
        if cheapest is not None and cheapest.rightsholder_id == recommended.rightsholder_id:
            recommended.reasons.insert(0, "Cheapest of the credible options, and the best overall.")
        elif cheapest is not None:
            # `recommended` wins on overall score, `cheapest` purely on price, so the cheaper
            # option can score the same or better on reliability. Saying it "scores -12 points
            # lower" reads as a bug and undermines the advice.
            gap = recommended.reliability - cheapest.reliability
            if gap > 0.5:
                why = f"scores {gap:.0f} points lower on reliability"
            elif gap < -0.5:
                why = f"is a weaker identity match despite scoring {-gap:.0f} points higher on reliability"
            else:
                why = "is a weaker identity match"
            recommended.reasons.insert(0, f"{cheapest.name} would be cheaper, but {why}.")

    leads = providers.research_leads(task, claims, settings,
                                     unresolved=recommended is None)
    return Resolution(options=options, recommended=recommended, cheapest=cheapest, leads=leads)


def apply(session: Session, task: ClearanceTask, settings: Settings,
          index: list | None = None) -> Resolution:
    """Resolve and record on the task, without changing who is assigned."""
    resolution = resolve(session, task, settings, index)
    for field_name, value in resolution.to_task_fields().items():
        setattr(task, field_name, value)
    return resolution
