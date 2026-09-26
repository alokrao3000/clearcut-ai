"""External rightsholder sources, and where to send a human when they run out.

The public registries people actually use for this work are not machine-readable:

* **U.S. Copyright Office public records (CPRS)** — no documented public API. Registration
  data is published as bulk files; point `copyright_office_api_url` at a loaded copy or a
  gateway and the provider turns on.
* **WATCH** (Harry Ransom Center / University of Reading) — a searchable web database with no
  API and no stated terms for automated access. We do not scrape it.
* **BISG Find a Rightsholder** and **Copyright Clearance Center** — commercial services behind
  a subscription and an API key.

So the rule from M1 holds: sanctioned endpoints only, and where none exists we generate a
pre-filled search link instead of pretending to have queried. A lead is a research task for a
person, and it says plainly which of the two it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from app.config import Settings
from app.enums import Layer

# Which databases are worth a human's time, per layer.
LAYER_SOURCES: dict[Layer, tuple[str, ...]] = {
    Layer.master_recording: ("copyright_office", "ccc"),
    Layer.composition: ("copyright_office", "ccc"),
    Layer.still_image: ("copyright_office", "watch", "bisg"),
    Layer.footage: ("copyright_office", "bisg"),
    Layer.performance: ("copyright_office",),
    Layer.trademark: ("uspto",),
}


@dataclass
class Lead:
    source: str
    label: str
    url: str
    why: str
    automatable: bool

    def to_dict(self) -> dict:
        return {"source": self.source, "label": self.label, "url": self.url, "why": self.why,
                "automatable": self.automatable}


def _cprs(query: str) -> Lead:
    return Lead(
        source="copyright_office",
        label="U.S. Copyright Office public records",
        url=f"https://publicrecords.copyright.gov/search?q={quote_plus(query)}",
        why="Registrations since 1978 name the claimant and any recorded transfer of ownership.",
        automatable=False,
    )


def _watch(query: str) -> Lead:
    return Lead(
        source="watch",
        label="WATCH — Writers, Artists and Their Copyright Holders",
        url=f"https://norman.hrc.utexas.edu/watch/search.cfm?keyword={quote_plus(query)}",
        why="Best source for literary and artistic estates, including heirs of deceased creators.",
        automatable=False,
    )


def _bisg(query: str) -> Lead:
    return Lead(
        source="bisg",
        label="BISG Find a Rightsholder",
        url="https://www.bisg.org/find-a-rightsholder",
        why=f"Rights contacts for active, inactive and defunct publishers — search “{query}”.",
        automatable=True,
    )


def _ccc(query: str) -> Lead:
    return Lead(
        source="ccc",
        label="Copyright Clearance Center",
        url=f"https://marketplace.copyright.com/rs-ui-web/mp/search/all/{quote_plus(query)}",
        why="Clears reprint and republication rights for published text and journal articles.",
        automatable=True,
    )


def _uspto(query: str) -> Lead:
    return Lead(
        source="uspto",
        label="USPTO trademark search",
        url=f"https://tmsearch.uspto.gov/search/search-results?q={quote_plus(query)}",
        why="Identifies the registered owner of a mark and their counsel of record.",
        automatable=False,
    )


def _alliance() -> Lead:
    return Lead(
        source="copyright_alliance",
        label="Copyright Alliance — finding an owner",
        url="https://copyrightalliance.org/resources/find-a-copyright-ownercreator/",
        why="Walks the remaining options when the registries come up empty: estates, probate "
            "records, firms-out-of-business directories.",
        automatable=False,
    )


BUILDERS = {
    "copyright_office": _cprs,
    "watch": _watch,
    "bisg": _bisg,
    "ccc": _ccc,
    "uspto": _uspto,
}


def configured_providers(settings: Settings) -> set[str]:
    """Sources we hold credentials or an endpoint for, and may therefore call directly."""
    live = set()
    if settings.copyright_office_api_url:
        live.add("copyright_office")
    if settings.ccc_api_key:
        live.add("ccc")
    if settings.bisg_api_key:
        live.add("bisg")
    return live


def research_leads(task, claims, settings: Settings, unresolved: bool) -> list[dict]:
    """Pre-filled searches for the layer in hand, best query first.

    Returned whenever nothing could be recommended; a resolved task gets none, because a
    producer does not need homework for a question already answered.
    """
    if not unresolved:
        return []

    asset = task.asset
    query = next((claim.name for claim in claims), None) or asset.owner_name or asset.title or ""
    query = query.strip()
    if not query:
        return [_alliance().to_dict()]

    live = configured_providers(settings)
    leads = []
    for source in LAYER_SOURCES.get(Layer(task.layer), ()):
        lead = BUILDERS[source](query)
        # A configured source is one we could query automatically; say so honestly.
        lead.automatable = source in live
        leads.append(lead.to_dict())
    leads.append(_alliance().to_dict())
    return leads
