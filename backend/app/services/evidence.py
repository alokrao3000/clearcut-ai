"""Read ownership claims out of the material we already hold.

This is the automated version of "check the publication directly": the copyright page, the
credit line, the caption. It is the most reliable signal we can get without a paid database,
because it is the owner's own assertion rather than a name-similarity guess.

Two notices matter and they mean different things, which maps exactly onto our layers:
    (C) 2019 Some Publisher      -> the underlying work      -> composition / still_image
    (P) 2019 Some Records        -> the sound recording      -> master_recording

YouTube's auto-generated music descriptions carry "Provided to YouTube by <distributor>"
and a (P) line, which together identify the label far more precisely than the channel name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.enums import Layer

# Ownership phrasings, strongest first. Each yields the entity name in group "name".
# The capture runs to a comma or end of line, never to a full stop: entity names are full
# of them ("Warner Bros. Pictures"). Sentence boundaries are cut afterwards, in _tidy.
_NAME = r"(?P<name>[^\n\r,;|]{2,160}?)"
_YEAR = r"(?:19|20)\d{2}"

PATTERNS: list[tuple[str, str, list[Layer], float]] = [
    # (label, regex, layers the claim speaks to, base strength 0-100)
    ("phonogram_notice", rf"[℗(]\s*[Pp]?\s*[)]?\s*(?:{_YEAR}\s+)?{_NAME}(?=$|[,;|\n])",
     [Layer.master_recording], 92.0),
    ("copyright_notice", rf"(?:©|\(c\)|\bcopyright\b)\s*(?:{_YEAR}\s+)?(?:by\s+)?{_NAME}(?=$|[,;|\n])",
     [Layer.composition, Layer.still_image, Layer.footage], 90.0),
    ("provided_to_youtube", rf"provided to youtube by\s+{_NAME}(?=$|[,;|\n])",
     [Layer.master_recording], 88.0),
    ("licensed_by", rf"licen[sc]ed (?:to youtube )?by\s+{_NAME}(?=$|[,;|\n])",
     [Layer.master_recording, Layer.footage], 85.0),
    ("courtesy_of", rf"(?:image |footage |photo )?courtesy of\s+{_NAME}(?=$|[,;|\n])",
     [Layer.footage, Layer.still_image], 80.0),
    ("published_by", rf"published by\s+{_NAME}(?=$|[,;|\n])", [Layer.composition], 86.0),
    ("distributed_by", rf"distributed by\s+{_NAME}(?=$|[,;|\n])", [Layer.footage], 70.0),
    ("a_production_of", rf"an? {_NAME} production(?=$|[,;|\n])", [Layer.footage], 72.0),
    ("credit_line", rf"(?:credit|source|photo|photograph)\s*[:/]\s*{_NAME}(?=$|[,;|\n])",
     [Layer.still_image, Layer.footage], 75.0),
]

_COMPILED = [(label, re.compile(pattern, re.IGNORECASE), layers, strength)
             for label, pattern, layers, strength in PATTERNS]

# Words that mean the capture ran past the entity name into prose.
_STOP_TRAILERS = re.compile(
    r"\b(all rights reserved|under (?:exclusive )?licen[sc]e|a division of|used with permission)\b.*$",
    re.IGNORECASE,
)
_NOISE = re.compile(r"^(the\s+)?(video|audio|song|track|film|image|photo)\b", re.IGNORECASE)

# Abbreviations whose full stop belongs to the name, not to the end of a sentence.
_ABBREVIATIONS = {"bros", "inc", "ltd", "co", "corp", "llc", "plc", "gmbh", "st", "mt",
                  "dr", "jr", "sr", "no", "dept", "univ", "assn"}
_SENTENCE_BREAK = re.compile(r"\.\s+(?=[A-Z0-9])")


def _cut_at_sentence_end(text: str) -> str:
    """Stop at the first full stop that ends a sentence rather than an abbreviation.

    "Warner Bros. Pictures. All rights reserved." keeps the first stop and drops the second.
    """
    position = 0
    while True:
        match = _SENTENCE_BREAK.search(text, position)
        if match is None:
            return text
        preceding = re.split(r"[\s.]+", text[:match.start()].strip())[-1].lower()
        if preceding in _ABBREVIATIONS:
            position = match.end()
            continue
        return text[:match.start()]


@dataclass
class OwnershipClaim:
    """One assertion of ownership found in the material, with where it came from."""

    name: str
    claim_type: str
    layers: list[str]
    strength: float
    source_field: str
    excerpt: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "claim_type": self.claim_type,
            "layers": self.layers,
            "strength": self.strength,
            "source_field": self.source_field,
            "excerpt": self.excerpt,
        }


@dataclass
class EvidenceSet:
    claims: list[OwnershipClaim] = field(default_factory=list)

    def for_layer(self, layer: Layer) -> list[OwnershipClaim]:
        return sorted((c for c in self.claims if layer.value in c.layers),
                      key=lambda c: -c.strength)


def _tidy(raw: str) -> str | None:
    name = _cut_at_sentence_end(raw.strip())
    name = _STOP_TRAILERS.sub("", name).strip(" \t-–—•·:;,.\"'")
    name = re.sub(r"\s+", " ", name)
    if len(name) < 2 or len(name) > 120 or _NOISE.match(name):
        return None
    # A bare year, a URL or a pure number is not an entity.
    if re.fullmatch(r"[\d\s.\-]+", name) or "http" in name.lower():
        return None
    # Entity names carry a proper noun. Without one this is prose that merely contains the
    # word "copyright" — "a copyright notice on a wall" is not a rightsholder.
    if not any(token[:1].isupper() for token in name.split()):
        return None
    return name


def scan_text(text: str | None, source_field: str) -> list[OwnershipClaim]:
    if not text:
        return []
    claims: list[OwnershipClaim] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for label, pattern, layers, strength in _COMPILED:
            for match in pattern.finditer(line):
                name = _tidy(match.group("name"))
                if name is None or (label, name.lower()) in seen:
                    continue
                seen.add((label, name.lower()))
                claims.append(OwnershipClaim(
                    name=name,
                    claim_type=label,
                    layers=[layer.value for layer in layers],
                    strength=strength,
                    source_field=source_field,
                    excerpt=line[:300],
                ))
    return claims


def collect(asset) -> EvidenceSet:
    """Scan every field of an asset that could carry a credit line."""
    claims: list[OwnershipClaim] = []
    claims += scan_text(asset.description, "description")
    claims += scan_text(asset.user_notes, "user_notes")
    claims += scan_text(asset.title, "title")

    payload = asset.ingest_payload or {}
    for key in ("description", "credit", "copyright", "attribution", "rights", "quote"):
        value = payload.get(key)
        if isinstance(value, str):
            claims += scan_text(value, f"ingest_payload.{key}")

    # Keep the strongest claim per (name, layer-set); duplicates across fields add nothing.
    best: dict[tuple[str, str], OwnershipClaim] = {}
    for claim in claims:
        key = (claim.name.lower(), claim.claim_type)
        if key not in best or claim.strength > best[key].strength:
            best[key] = claim
    return EvidenceSet(claims=sorted(best.values(), key=lambda c: -c.strength))
