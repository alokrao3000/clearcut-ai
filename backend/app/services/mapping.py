"""Resolve an asset layer to a rightsholder in the directory.

Scoring is deliberately simple and explainable: exact alias match, whole-word containment,
then rapidfuzz token-sort similarity. Every candidate records which alias and which query
produced it, so a reviewer can see why the matcher suggested it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.enums import LAYER_KINDS, Layer, RightsholderKind, Stage
from app.models import ClearanceTask, Rightsholder

_CHANNEL_NOISE = re.compile(r"\b(vevo|official|channel|topic|tv)\b", re.I)
_NON_WORD = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    # Split CamelCase channel handles: "RickAstleyVEVO" -> "Rick Astley VEVO"
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = _NON_WORD.sub(" ", text.lower())
    text = _CHANNEL_NOISE.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def score(query: str, alias: str) -> float:
    if not query or not alias:
        return 0.0
    if query == alias:
        return 100.0
    if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", query):
        return 95.0
    return float(fuzz.token_sort_ratio(query, alias))


@dataclass
class Candidate:
    rightsholder_id: str
    name: str
    score: float
    matched_alias: str
    matched_query: str


@dataclass
class _IndexEntry:
    alias_norm: str
    alias_raw: str
    layers: set[str] | None
    rightsholder: Rightsholder


def build_index(session: Session) -> list[_IndexEntry]:
    rows = session.scalars(select(Rightsholder).options(selectinload(Rightsholder.aliases))).all()
    index = []
    for rh in rows:
        index.append(_IndexEntry(normalize(rh.name), rh.name, None, rh))
        for a in rh.aliases:
            index.append(_IndexEntry(normalize(a.alias), a.alias, set(a.layers) if a.layers else None, rh))
    return index


def _queries(task: ClearanceTask) -> list[tuple[str, str, float]]:
    """(normalized, raw, weight). The uploader/owner is the strongest signal."""
    asset = task.asset
    out: list[tuple[str, str, float]] = []
    if asset.owner_name:
        out.append((normalize(asset.owner_name), asset.owner_name, 1.0))
    for kw in asset.inferred_keywords or []:
        if re.fullmatch(r"\d{4}", kw) or kw == asset.owner_name:
            continue
        out.append((normalize(kw), kw, 0.95))
    return [q for q in out if q[0]]


def rank_candidates(task: ClearanceTask, index: list[_IndexEntry], limit: int = 5) -> list[Candidate]:
    layer = Layer(task.layer)
    allowed_kinds = LAYER_KINDS[layer]
    best: dict[str, Candidate] = {}
    for q_norm, q_raw, weight in _queries(task):
        for entry in index:
            if RightsholderKind(entry.rightsholder.kind) not in allowed_kinds:
                continue
            if entry.layers is not None and layer.value not in entry.layers:
                continue
            s = round(score(q_norm, entry.alias_norm) * weight, 1)
            rh = entry.rightsholder
            if s > 0 and (rh.id not in best or s > best[rh.id].score):
                best[rh.id] = Candidate(rh.id, rh.name, s, entry.alias_raw, q_raw)
    ranked = sorted(best.values(), key=lambda c: (-c.score, c.name))
    return [c for c in ranked if c.score >= 60][:limit]


def _ancestors(rh: Rightsholder) -> set[str]:
    out, node = set(), rh.parent
    while node is not None and node.id not in out:
        out.add(node.id)
        node = node.parent
    return out


def choose(candidates: list[Candidate], session: Session, settings: Settings) -> Candidate | None:
    """Auto-assign only when the top match is strong and clearly ahead of any unrelated rival.

    A parent company scoring close behind its own subsidiary is not ambiguity: the subsidiary wins.
    """
    if not candidates or candidates[0].score < settings.auto_assign_min_score:
        return None
    top = candidates[0]
    related = _ancestors(session.get(Rightsholder, top.rightsholder_id))
    for other in candidates[1:]:
        if other.rightsholder_id in related:
            continue
        if top.score - other.score < settings.auto_assign_min_margin:
            return None
        break
    return top


def map_task(session: Session, task: ClearanceTask, index: list[_IndexEntry], settings: Settings) -> bool:
    """Run the matcher on one task. Never overwrites a manual assignment. Returns True if assigned."""
    if task.mapping_method == "manual" or task.stage not in (Stage.sourced, Stage.rights_mapped):
        return False
    candidates = rank_candidates(task, index)
    task.mapping_candidates = [asdict(c) for c in candidates]
    chosen = choose(candidates, session, settings)
    if chosen is None:
        return False
    task.rightsholder_id = chosen.rightsholder_id
    task.mapping_method = "auto"
    task.mapping_confidence = chosen.score
    if task.stage == Stage.sourced:
        task.stage = Stage.rights_mapped
    return True


def effective_contact(rh: Rightsholder) -> dict:
    """Walk up the corporate hierarchy to the nearest entity with a licensing intake."""
    node, seen = rh, set()
    while node is not None and node.id not in seen:
        seen.add(node.id)
        if node.licensing_email:
            return {
                "via_rightsholder_id": node.id,
                "via_name": node.name,
                "licensing_email": node.licensing_email,
                "address": node.address,
                "preferred_templates": node.preferred_templates or [],
                "is_placeholder": node.is_placeholder,
            }
        node = node.parent
    return {"via_rightsholder_id": None, "via_name": None, "licensing_email": None, "address": None,
            "preferred_templates": [], "is_placeholder": rh.is_placeholder}
