"""Orchestration: ingest -> split into layer tasks -> map rightsholders -> estimate budget.

Each stage runs under its own audit actor so the ledger shows exactly which component
produced each value.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import acting_as
from app.config import get_settings
from app.enums import ActorType, Layer, SourceType, Stage
from app.models import Asset, ClearanceTask, Project, Rightsholder
from app.services import budget, mapping, workflow
from app.services.ingest import MetadataFetcher, ingest_url

ESTIMABLE_STAGES = {Stage.sourced, Stage.rights_mapped}


@dataclass
class IngestOutcome:
    url: str
    asset: Asset
    duplicate: bool


def ingest_into_project(session: Session, project: Project, items: list[tuple[str, str | None, int | None]],
                        fetcher: MetadataFetcher) -> list[IngestOutcome]:
    outcomes = []
    index = None
    for url, notes, usage in items:
        existing = session.scalar(select(Asset).where(Asset.project_id == project.id, Asset.raw_source == url))
        if existing:
            outcomes.append(IngestOutcome(url, existing, True))
            continue

        result = ingest_url(url, notes, fetcher)
        p = result.payload
        with acting_as(session, ActorType.scraper, f"ingest:{result.source.platform.value}"):
            asset = Asset(
                project_id=project.id, source_type=SourceType.url_ingest.value, raw_source=url,
                platform=result.source.platform.value, platform_asset_id=result.source.asset_id,
                title=p["title"], owner_name=p["owner_name"], description=p["description"],
                published_at=p["published_at"], thumbnail_url=p["thumbnail_url"],
                duration_seconds=p["duration_seconds"], inferred_keywords=p["inferred_keywords"],
                user_notes=notes, usage_seconds=usage, ingest_status=result.status.value,
                ingest_error=result.error, ingest_payload=p,
            )
            asset.tasks = [ClearanceTask(layer=layer.value, stage=Stage.sourced.value, mapping_candidates=[])
                           for layer in result.layers]
            session.add(asset)

        index = index or mapping.build_index(session)
        map_and_estimate(session, project, asset.tasks, index)
        outcomes.append(IngestOutcome(url, asset, False))
    return outcomes


def map_and_estimate(session: Session, project: Project, tasks: list[ClearanceTask], index=None) -> None:
    settings = get_settings()
    index = index or mapping.build_index(session)
    with acting_as(session, ActorType.system, "rights_matcher"):
        for task in tasks:
            if mapping.map_task(session, task, index, settings):
                task.rightsholder = session.get(Rightsholder, task.rightsholder_id)
    estimate(session, project, tasks)


def estimate(session: Session, project: Project, tasks: list[ClearanceTask]) -> None:
    """(Re)estimate tasks whose budget has not been approved yet. Approved budgets are never silently changed."""
    with acting_as(session, ActorType.system, "budget_matrix"):
        for task in tasks:
            if task.stage in ESTIMABLE_STAGES:
                budget.estimate_task(session, task, project)


def add_layer(session: Session, asset: Asset, layer: Layer) -> ClearanceTask:
    if any(t.layer == layer for t in asset.tasks):
        raise workflow.WorkflowError(f"Asset already has a '{layer}' task.")
    task = ClearanceTask(layer=layer.value, stage=Stage.sourced.value, mapping_candidates=[])
    asset.tasks.append(task)
    session.flush()
    map_and_estimate(session, asset.project, [task])
    return task


def assign_rightsholder(session: Session, task: ClearanceTask, rightsholder_id: str | None) -> None:
    """Manual override by the current user. Locks the task against future auto-mapping."""
    stage = Stage(task.stage)
    if stage not in workflow.REASSIGNABLE:
        raise workflow.WorkflowError(
            f"Rightsholder cannot change once a task is '{stage}'. Move it back to budget_approved first.")
    rh = None
    if rightsholder_id is not None:
        rh = session.get(Rightsholder, rightsholder_id)
        if rh is None:
            raise LookupError(f"Unknown rightsholder '{rightsholder_id}'.")
    task.rightsholder_id, task.rightsholder = rightsholder_id, rh
    task.mapping_method = "manual" if rh else None
    task.mapping_confidence = None
    if rh and stage is Stage.sourced:
        task.stage = Stage.rights_mapped.value
    elif rh is None:
        task.stage = Stage.sourced.value
    elif stage is Stage.budget_approved:
        task.stage = Stage.rights_mapped.value  # budget basis changed; needs re-approval
    session.flush()
    estimate(session, task.asset.project, [task])
