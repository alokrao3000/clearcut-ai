from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import Actor, set_actor
from app.config import get_settings
from app.deps import (NOT_FOUND, WRITE, current_user_id, db, scoped, scoped_project,
                      session_org)
from app.enums import ActorType, IngestStatus, Layer, Platform, SourceType
from app.models import Asset, AssetMention, ClearanceTask, Job, Project, Scene, ScriptDocument
from app.presenters import asset_out
from app.schemas import AssetOut, ConfirmMentionRequest, JobOut, MentionOut, SceneOut, ScriptOut
from app.services import pipeline
from app.services.queue import enqueue
from app.services.scripts import ScriptParseError, parse_script

router = APIRouter(tags=["scripts"])


def load_script(session: Session, script_id: str) -> ScriptDocument:
    script = session.get(ScriptDocument, script_id)
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped(script.project, session)
    return script


def _script_out(session: Session, script: ScriptDocument, job_id: str | None = None) -> ScriptOut:
    out = ScriptOut.model_validate(script)
    out.mention_count = session.scalar(
        select(func.count(AssetMention.id))
        .join(Scene, Scene.id == AssetMention.scene_id)
        .where(Scene.script_id == script.id)
    ) or 0
    out.job_id = job_id
    return out


def _mentions_for(session: Session, script_id: str) -> list[AssetMention]:
    return list(session.scalars(
        select(AssetMention).join(Scene, Scene.id == AssetMention.scene_id)
        .where(Scene.script_id == script_id)
        .options(selectinload(AssetMention.scene))
        .order_by(Scene.index, AssetMention.created_at)))


def _mention_out(mention: AssetMention) -> MentionOut:
    out = MentionOut.model_validate(mention)
    if mention.scene is not None:
        out.scene_heading = mention.scene.heading
        out.scene_index = mention.scene.index
        out.page_number = mention.scene.page_number
    return out


@router.post("/api/projects/{project_id}/scripts", response_model=ScriptOut, status_code=201,
             dependencies=WRITE)
async def upload_script(project_id: str, file: UploadFile = File(...), session: Session = Depends(db)):
    """Parse a screenplay into scenes now; read it with the extractor in the background.

    The file itself is never stored — only its parsed text, which is what M4's tokenized
    context views are allowed to quote from.
    """
    project = scoped_project(session, project_id)

    settings = get_settings()
    data = await file.read()
    if len(data) > settings.script_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Scripts are limited to {settings.script_max_bytes // (1024 * 1024)} MB.")

    try:
        parsed = parse_script(data, file.filename or "upload")
    except ScriptParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    script = ScriptDocument(
        project_id=project.id, filename=(file.filename or "upload")[:300], media_type=parsed.media_type,
        byte_size=len(data), page_count=parsed.page_count, scene_count=len(parsed.scenes),
        status="extracting",
    )
    script.scenes = [
        Scene(index=scene.index, heading=scene.heading, page_number=scene.page_number, text=scene.text)
        for scene in parsed.scenes
    ]
    session.add(script)
    session.commit()

    job = enqueue(session, "extract_script", {"script_id": script.id},
                  project_id=project.id, subject_id=script.id)
    session.refresh(script)
    return _script_out(session, script, job.id)


@router.get("/api/projects/{project_id}/scripts", response_model=list[ScriptOut])
def list_scripts(project_id: str, session: Session = Depends(db)):
    scoped_project(session, project_id)
    scripts = session.scalars(
        select(ScriptDocument).where(ScriptDocument.project_id == project_id)
        .order_by(ScriptDocument.created_at.desc())).all()
    return [_script_out(session, script) for script in scripts]


@router.get("/api/scripts/{script_id}", response_model=ScriptOut)
def get_script(script_id: str, session: Session = Depends(db)):
    return _script_out(session, load_script(session, script_id))


@router.get("/api/scripts/{script_id}/scenes", response_model=list[SceneOut])
def list_scenes(script_id: str, session: Session = Depends(db)):
    load_script(session, script_id)
    return session.scalars(select(Scene).where(Scene.script_id == script_id).order_by(Scene.index)).all()


@router.get("/api/scripts/{script_id}/mentions", response_model=list[MentionOut])
def list_mentions(script_id: str, session: Session = Depends(db)):
    load_script(session, script_id)
    return [_mention_out(m) for m in _mentions_for(session, script_id)]


@router.delete("/api/scripts/{script_id}", status_code=204, dependencies=WRITE)
def delete_script(script_id: str, session: Session = Depends(db)):
    session.delete(load_script(session, script_id))
    session.commit()


@router.post("/api/mentions/{mention_id}/confirm", response_model=AssetOut, dependencies=WRITE)
def confirm_mention(mention_id: str, body: ConfirmMentionRequest, session: Session = Depends(db),
                    user_id: str = Depends(current_user_id)):
    """A human accepts the extractor's proposal, and only then does an asset exist."""
    mention = session.get(AssetMention, mention_id)
    if mention is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped_project(session, mention.project_id)
    if mention.status == "confirmed" and mention.asset_id:
        return asset_out(session.get(Asset, mention.asset_id))

    layers = [layer.value for layer in (body.layers or [])] or list(mention.suggested_layers)
    if not layers:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "This mention has no rights layers. Pass `layers` to say what needs clearing.")

    scene = mention.scene
    set_actor(session, Actor(ActorType.user, user_id, f"Confirmed script mention from scene {scene.index}"))

    title = (body.title or mention.title).strip()
    asset = Asset(
        project_id=mention.project_id,
        source_type=SourceType.script_ingest.value,
        raw_source=f"script:{scene.script_id}#scene-{scene.index}",
        platform=Platform.other.value,
        platform_asset_id=None,
        title=title,
        owner_name=(body.owner_name or mention.owner_name),
        description=mention.reasoning,
        published_at=None,
        thumbnail_url=None,
        duration_seconds=None,
        inferred_keywords=[word for word in title.split() if len(word) > 3][:8],
        user_notes=mention.quote,
        usage_seconds=body.usage_seconds,
        ingest_status=IngestStatus.complete.value,
        ingest_error=None,
        # The frozen record of what the extractor claimed, kept for the audit trail.
        ingest_payload={
            "source": "script_extraction",
            "script_id": scene.script_id,
            "scene_index": scene.index,
            "scene_heading": scene.heading,
            "page_number": scene.page_number,
            "quote": mention.quote,
            "kind": mention.kind,
            "confidence": mention.confidence,
            "suggested_layers": list(mention.suggested_layers),
        },
    )
    asset.tasks = [ClearanceTask(layer=Layer(layer).value, stage="sourced", mapping_candidates=[])
                   for layer in dict.fromkeys(layers)]
    session.add(asset)
    session.flush()

    pipeline.map_and_estimate(session, asset.project, asset.tasks)
    mention.status, mention.asset_id = "confirmed", asset.id
    session.commit()
    return asset_out(asset)


@router.post("/api/mentions/{mention_id}/dismiss", response_model=MentionOut, dependencies=WRITE)
def dismiss_mention(mention_id: str, session: Session = Depends(db)):
    mention = session.get(AssetMention, mention_id)
    if mention is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped_project(session, mention.project_id)
    mention.status = "dismissed"
    session.commit()
    return _mention_out(mention)


# ---------------------------------------------------------------- jobs

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(db)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    if job.project_id:
        scoped_project(session, job.project_id)
    return job


@jobs_router.get("", response_model=list[JobOut])
def list_jobs(project_id: str | None = None, kind: str | None = None, limit: int = 50,
              session: Session = Depends(db)):
    # A job list with no project is scoped to this tenant's projects rather than global.
    own = select(Project.id).where(Project.org_id == session_org(session))
    stmt = (select(Job).where(Job.project_id.in_(own))
            .order_by(Job.enqueued_at.desc()).limit(min(limit, 200)))
    if project_id:
        scoped_project(session, project_id)
        stmt = stmt.where(Job.project_id == project_id)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    return session.scalars(stmt).all()
