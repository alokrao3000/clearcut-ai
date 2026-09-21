"""The actual background work. Imported for its side effect of registering handlers."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import acting_as
from app.config import get_settings
from app.enums import ActorType
from app.models import Asset, AssetMention, Project, Scene, ScriptDocument
from app.services import extract, pipeline, storage
from app.services.extract import ExtractionUnavailable
from app.services.ingest import get_fetcher
from app.services.queue import handler
from app.services.scripts import ParsedScene

log = logging.getLogger(__name__)


@handler("extract_script")
def extract_script(session: Session, payload: dict) -> dict:
    """Read a parsed script's scenes with Claude and store the proposed mentions."""
    script = session.get(ScriptDocument, payload["script_id"])
    if script is None:
        return {"skipped": "script deleted"}

    scenes = list(session.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.index)))
    parsed = [ParsedScene(index=s.index, heading=s.heading, page_number=s.page_number, text=s.text)
              for s in scenes]
    by_index = {s.index: s for s in scenes}
    settings = get_settings()

    try:
        result = extract.extract_mentions(parsed, settings)
    except ExtractionUnavailable as exc:
        # Parsing already succeeded; the script is usable without the LLM pass.
        script.status, script.error = "complete", f"Extraction skipped: {exc}"
        session.commit()
        return {"mentions": 0, "extraction": "unavailable"}

    with acting_as(session, ActorType.llm, settings.extraction_model):
        for mention in result.mentions:
            scene = by_index.get(mention.scene_index)
            if scene is None:
                continue
            session.add(AssetMention(
                scene_id=scene.id,
                project_id=script.project_id,
                title=mention.title.strip(),
                owner_name=(mention.owner_name or None),
                kind=mention.kind,
                quote=mention.quote.strip(),
                suggested_layers=mention.suggested_layers,
                confidence=mention.confidence,
                reasoning=mention.reasoning,
            ))
        script.status = "complete"
        script.extraction_model = result.model
        script.error = None

    session.commit()
    return {"mentions": len(result.mentions), "scenes_read": result.scenes_read}


@handler("ingest_urls")
def ingest_urls(session: Session, payload: dict) -> dict:
    """Deferred version of the synchronous ingest endpoint."""
    project = session.get(Project, payload["project_id"])
    if project is None:
        return {"skipped": "project deleted"}

    items = [(item["url"], item.get("notes"), item.get("usage_seconds")) for item in payload["items"]]
    outcomes = pipeline.ingest_into_project(session, project, items, get_fetcher())
    session.commit()
    return {
        "ingested": sum(1 for o in outcomes if not o.duplicate),
        "duplicates": sum(1 for o in outcomes if o.duplicate),
        "asset_ids": [o.asset.id for o in outcomes],
    }


@handler("remap_asset")
def remap_asset(session: Session, payload: dict) -> dict:
    asset = session.get(Asset, payload["asset_id"])
    if asset is None:
        return {"skipped": "asset deleted"}
    pipeline.map_and_estimate(session, asset.project, asset.tasks)
    session.commit()
    return {"tasks": len(asset.tasks)}


@handler("cache_thumbnail")
def cache_thumbnail(session: Session, payload: dict) -> dict:
    """Copy a platform thumbnail into our own object store so the board stops hotlinking."""
    asset = session.get(Asset, payload["asset_id"])
    if asset is None or not asset.thumbnail_url:
        return {"skipped": "no thumbnail"}

    cached = storage.cache_thumbnail(asset.id, asset.thumbnail_url)
    if cached is None:
        return {"skipped": "cache disabled or unreachable"}

    with acting_as(session, ActorType.system, "thumbnail_cache"):
        asset.thumbnail_url = cached
    session.commit()
    return {"thumbnail_url": cached}


def load_all() -> None:
    """Called for the import side effect; keeps the registry import explicit at call sites."""
    _ = (extract_script, ingest_urls, remap_asset, cache_thumbnail)


__all__ = ["cache_thumbnail", "extract_script", "ingest_urls", "load_all", "remap_asset"]
