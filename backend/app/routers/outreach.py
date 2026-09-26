"""Outreach packets, script excerpts, and the public tokenized context view.

Two routers live here on purpose, so the boundary is visible in one file:

* `router` is the authenticated, disclaimer-gated API the producer uses.
* `public_router` is the unauthenticated token surface a rightsholder opens. It never sets
  an audit actor, never renders internal fields, and takes no identifier from the caller
  except the token itself.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import Actor, set_actor
from app.config import get_settings
from app.db import get_session
from app.deps import NOT_FOUND, WRITE, current_user_id, db, scoped, scoped_project
from app.enums import ActorType, Stage
from app.models import (Asset, ClearanceTask, ContextExcerpt, ContextView, ContextViewAccess,
                        OutreachPacket, PacketTask, Project, Rightsholder, Scene)
from app.schemas import (AccessOut, ContactOut, ContextViewCreate, ContextViewCreated,
                         ContextViewOut, ExcerptCreate, ExcerptOut, PacketCreate, PacketFinalize,
                         PacketGroupOut, PacketItemOut, PacketOut, PacketUpdate, PdfStatusOut,
                         RightsholderBrief, TemplateOut)
from app.services import context_views, packets, pdf, watermark, workflow
from app.services.mapping import effective_contact

router = APIRouter(tags=["outreach"])
public_router = APIRouter(tags=["context views"], include_in_schema=False)

NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, private", "Pragma": "no-cache"}


# ---------------------------------------------------------------- helpers

def _packet_query():
    return select(OutreachPacket).options(
        selectinload(OutreachPacket.rightsholder),
        selectinload(OutreachPacket.project),
        selectinload(OutreachPacket.excerpts),
        selectinload(OutreachPacket.context_views),
        selectinload(OutreachPacket.items).selectinload(PacketTask.task).selectinload(ClearanceTask.asset),
    )


def load_packet(session: Session, packet_id: str) -> OutreachPacket:
    packet = session.scalar(_packet_query().where(OutreachPacket.id == packet_id))
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    scoped(packet.project, session)
    return packet


def packet_out(packet: OutreachPacket) -> PacketOut:
    """Built field by field rather than from_attributes: `items` are PacketTask links, and
    what the UI wants is the task behind each one."""
    return PacketOut(
        id=packet.id, project_id=packet.project_id, template=packet.template, status=packet.status,
        rightsholder=RightsholderBrief.model_validate(packet.rightsholder),
        contact=ContactOut(**effective_contact(packet.rightsholder)),
        recipient_name=packet.recipient_name, recipient_email=packet.recipient_email,
        sender_name=packet.sender_name, sender_email=packet.sender_email,
        sender_title=packet.sender_title, subject=packet.subject, intro_note=packet.intro_note,
        finalized_at=packet.finalized_at, created_at=packet.created_at, updated_at=packet.updated_at,
        items=[PacketItemOut(task_id=item.task.id, asset_id=item.task.asset_id,
                             asset_title=item.task.asset.title, layer=item.task.layer,
                             stage=item.task.stage, estimate_low=item.task.estimate_low,
                             estimate_high=item.task.estimate_high)
               for item in packet.items if item.task is not None],
        excerpts=[ExcerptOut.model_validate(e)
                  for e in sorted(packet.excerpts, key=lambda e: e.created_at)],
        context_views=[view_out(v) for v in
                       sorted(packet.context_views, key=lambda v: v.created_at, reverse=True)],
    )


def view_out(view: ContextView) -> ContextViewOut:
    """`status` is derived from expiry and revocation, so it is computed, not stored."""
    return ContextViewOut(
        id=view.id, packet_id=view.packet_id, recipient_name=view.recipient_name,
        recipient_email=view.recipient_email, token_hint=view.token_hint,
        status=context_views.status_of(view), expires_at=view.expires_at,
        revoked_at=view.revoked_at, created_by=view.created_by, created_at=view.created_at,
        access_count=view.access_count or 0, last_accessed_at=view.last_accessed_at,
    )


def _client_ip(request: Request) -> str | None:
    """Caller IP, trusting X-Forwarded-For when present.

    Spoofable unless a proxy you control overwrites the header, so it is evidence in a
    pattern of accesses rather than proof of any single one.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _load_tasks(session: Session, project_id: str, task_ids: list[str]) -> list[ClearanceTask]:
    unique = list(dict.fromkeys(task_ids))
    tasks = list(session.scalars(
        select(ClearanceTask)
        .join(Asset, Asset.id == ClearanceTask.asset_id)
        .where(ClearanceTask.id.in_(unique), Asset.project_id == project_id)
        .options(selectinload(ClearanceTask.asset), selectinload(ClearanceTask.rightsholder))))
    found = {t.id for t in tasks}
    missing = [tid for tid in unique if tid not in found]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Not in this project: {', '.join(missing)}")
    # Preserve the caller's ordering — it becomes the order of the schedule in the letter.
    by_id = {t.id: t for t in tasks}
    return [by_id[tid] for tid in unique]


def _single_intake(tasks: list[ClearanceTask]) -> str:
    """The one licensing desk these tasks share, or a 422 explaining how they split."""
    unassigned = [t.id for t in tasks if t.rightsholder is None]
    if unassigned:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Assign a rightsholder before building a packet. Unassigned: " + ", ".join(unassigned))
    groups = packets.group_tasks(tasks)
    if len(groups) > 1:
        detail = "; ".join(f"{rid}: {len(items)} task(s)" for rid, items in groups.items())
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A packet addresses one licensing desk. These tasks split across several — "
            f"build one packet per group ({detail}).")
    return next(iter(groups))


# ---------------------------------------------------------------- catalogue

@router.get("/api/outreach/templates", response_model=list[TemplateOut])
def list_templates():
    return [TemplateOut(name=name, description=desc) for name, desc in packets.TEMPLATES.items()]


@router.get("/api/outreach/pdf-status", response_model=PdfStatusOut)
def pdf_status():
    """Whether PDF rendering works on this host. The HTML letter is available either way."""
    probe = pdf.probe()
    return PdfStatusOut(available=probe.available, version=probe.version, error=probe.error,
                        install_hint=None if probe.available else pdf.INSTALL_HINT)


# ---------------------------------------------------------------- grouping + CRUD

@router.get("/api/projects/{project_id}/packet-groups", response_model=list[PacketGroupOut])
def packet_groups(project_id: str, session: Session = Depends(db)):
    """Outreach-ready tasks bundled by the desk that would receive them.

    This is what the UI offers as "build these packets": the producer should not have to
    work out that two of their clips route to the same Warner intake.
    """
    scoped_project(session, project_id)

    existing: dict[str, list[str]] = {}
    for packet in session.scalars(select(OutreachPacket).where(OutreachPacket.project_id == project_id)):
        existing.setdefault(packet.rightsholder_id, []).append(packet.id)

    out = []
    for rid, tasks in packets.group_tasks(packets.packetable_tasks(session, project_id)).items():
        intake = packets.intake_for(tasks[0])
        holder = session.get(Rightsholder, rid)
        out.append(PacketGroupOut(
            rightsholder_id=rid, name=intake["via_name"], kind=holder.kind,
            licensing_email=intake["licensing_email"], is_placeholder=intake["is_placeholder"],
            suggested_template=packets.choose_template(holder),
            task_ids=[t.id for t in tasks],
            layers=sorted({t.layer for t in tasks}),
            asset_titles=list(dict.fromkeys(t.asset.title for t in tasks if t.asset.title)),
            existing_packet_ids=existing.get(rid, []),
        ))
    return sorted(out, key=lambda g: (-len(g.task_ids), g.name))


@router.post("/api/projects/{project_id}/packets", response_model=PacketOut, status_code=201,
             dependencies=WRITE)
def create_packet(project_id: str, body: PacketCreate, session: Session = Depends(db),
                  user_id: str = Depends(current_user_id)):
    project = scoped_project(session, project_id)

    tasks = _load_tasks(session, project_id, body.task_ids)
    rightsholder_id = _single_intake(tasks)
    holder = session.get(Rightsholder, rightsholder_id)
    settings = get_settings()

    try:
        template = (packets.validate_template(body.template) if body.template
                    else packets.choose_template(holder))
    except packets.PacketError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    set_actor(session, Actor(ActorType.user, user_id, "Created outreach packet"))
    packet = OutreachPacket(
        project_id=project.id, rightsholder_id=rightsholder_id, template=template, status="draft",
        recipient_name=body.recipient_name, recipient_email=body.recipient_email or holder.licensing_email,
        sender_name=settings.sender_name, sender_email=settings.sender_email,
        sender_title=settings.sender_title,
        subject=body.subject or packets.default_subject(project, tasks),
        intro_note=body.intro_note,
    )
    packet.items = [PacketTask(task_id=task.id) for task in tasks]
    session.add(packet)
    session.commit()
    return packet_out(load_packet(session, packet.id))


@router.get("/api/projects/{project_id}/packets", response_model=list[PacketOut])
def list_packets(project_id: str, session: Session = Depends(db)):
    scoped_project(session, project_id)
    rows = session.scalars(_packet_query().where(OutreachPacket.project_id == project_id)
                           .order_by(OutreachPacket.created_at.desc())).unique().all()
    return [packet_out(p) for p in rows]


@router.get("/api/packets/{packet_id}", response_model=PacketOut)
def get_packet(packet_id: str, session: Session = Depends(db)):
    return packet_out(load_packet(session, packet_id))


@router.patch("/api/packets/{packet_id}", response_model=PacketOut, dependencies=WRITE)
def update_packet(packet_id: str, body: PacketUpdate, session: Session = Depends(db),
                  user_id: str = Depends(current_user_id)):
    packet = load_packet(session, packet_id)
    if packet.status == "finalized":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This packet is finalized. Its letter is frozen as the record of what "
                            "was sent; create a new packet to change the ask.")

    set_actor(session, Actor(ActorType.user, user_id, body.reason or "Edited outreach packet"))
    fields = body.model_fields_set - {"reason", "task_ids"}

    if body.template is not None:
        try:
            packets.validate_template(body.template)
        except packets.PacketError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    for field in fields:
        setattr(packet, field, getattr(body, field))

    if body.task_ids is not None:
        tasks = _load_tasks(session, packet.project_id, body.task_ids)
        new_intake = _single_intake(tasks)
        if new_intake != packet.rightsholder_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"These tasks are addressed to '{new_intake}', but the packet is addressed to "
                f"'{packet.rightsholder_id}'. Create a separate packet instead.")
        packet.items = [PacketTask(task_id=task.id) for task in tasks]

    session.commit()
    return packet_out(load_packet(session, packet.id))


@router.delete("/api/packets/{packet_id}", status_code=204, dependencies=WRITE)
def delete_packet(packet_id: str, session: Session = Depends(db), user_id: str = Depends(current_user_id)):
    packet = load_packet(session, packet_id)
    set_actor(session, Actor(ActorType.user, user_id, "Deleted outreach packet"))
    session.delete(packet)
    session.commit()


# ---------------------------------------------------------------- render

@router.get("/api/packets/{packet_id}/preview", response_class=HTMLResponse)
def preview(packet_id: str, internal: bool = True, session: Session = Depends(db)):
    """The letter as HTML.

    `internal=true` (the default for the producer's own preview) appends the estimates
    panel. `internal=false` shows exactly what the recipient gets.
    """
    packet = load_packet(session, packet_id)
    if packet.rendered_html and not internal:
        return HTMLResponse(packet.rendered_html, headers=NO_STORE)
    try:
        return HTMLResponse(packets.render_html(packet, internal=internal), headers=NO_STORE)
    except packets.PacketError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/api/packets/{packet_id}/pdf")
def packet_pdf(packet_id: str, session: Session = Depends(db)):
    packet = load_packet(session, packet_id)
    try:
        data = packets.render_pdf(packet)
    except pdf.PdfUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except packets.PacketError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    slug = "".join(c if c.isalnum() else "-" for c in (packet.project.name or "packet"))[:40].strip("-")
    filename = f"{slug or 'packet'}-{packet.rightsholder_id}.pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', **NO_STORE})


@router.post("/api/packets/{packet_id}/finalize", response_model=PacketOut, dependencies=WRITE)
def finalize(packet_id: str, body: PacketFinalize, session: Session = Depends(db),
             user_id: str = Depends(current_user_id)):
    """Freeze the letter and, by default, move its tasks to 'outreach sent'.

    Freezing matters for the ledger: templates and the directory both change, so the record
    of an inquiry has to be the bytes that went out, not a re-render of them months later.
    """
    packet = load_packet(session, packet_id)
    if not packet.items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "A packet with no material cannot be finalized.")

    tasks = [item.task for item in packet.items if item.task is not None]
    if body.transition_tasks:
        blocked = [t for t in tasks
                   if Stage(t.stage) is not Stage.outreach_sent
                   and Stage.outreach_sent not in workflow.allowed_targets(Stage(t.stage))]
        if blocked:
            detail = ", ".join(f"{t.id} ({t.stage})" for t in blocked)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "These tasks cannot move to 'outreach sent' yet — approve their budgets first, "
                f"or finalize with transition_tasks=false: {detail}")

    set_actor(session, Actor(ActorType.user, user_id, body.reason or "Finalized outreach packet"))
    try:
        packet.rendered_html = packets.render_html(packet, internal=False)
    except packets.PacketError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    packet.status = "finalized"
    packet.finalized_at = datetime.now(UTC)

    if body.transition_tasks:
        for task in tasks:
            if Stage(task.stage) is not Stage.outreach_sent:
                workflow.transition(task, Stage.outreach_sent)

    session.commit()
    return packet_out(load_packet(session, packet.id))


# ---------------------------------------------------------------- excerpts

@router.post("/api/packets/{packet_id}/excerpts", response_model=ExcerptOut, status_code=201,
             dependencies=WRITE)
def add_excerpt(packet_id: str, body: ExcerptCreate, session: Session = Depends(db),
                user_id: str = Depends(current_user_id)):
    """Share one passage of script, chosen by hand.

    The text is copied here rather than referenced, so later edits to the scene cannot
    widen what an already-issued context view discloses.
    """
    packet = load_packet(session, packet_id)
    scene = session.scalar(
        select(Scene).where(Scene.id == body.scene_id).options(selectinload(Scene.script)))
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found")
    if scene.script.project_id != packet.project_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "That scene belongs to a different project.")

    settings = get_settings()
    start = body.start or 0
    end = body.end if body.end is not None else len(scene.text)
    if end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`end` must be greater than `start`.")
    text = scene.text[start:end].strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That selection is empty.")
    if len(text) > settings.excerpt_max_chars:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"An excerpt is limited to {settings.excerpt_max_chars} characters. Select a narrower "
            "range — a rightsholder needs the passage, not the scene.")

    page = f", p. {scene.page_number}" if scene.page_number else ""
    # Scene.index is 0-based internally; a recipient counts from one.
    label = (body.label or f"{scene.heading} (scene {scene.index + 1}{page})")[:300]

    set_actor(session, Actor(ActorType.user, user_id, f"Shared excerpt from scene {scene.index}"))
    excerpt = ContextExcerpt(packet_id=packet.id, scene_id=scene.id, label=label, text=text)
    session.add(excerpt)
    session.commit()
    return ExcerptOut.model_validate(excerpt)


@router.delete("/api/excerpts/{excerpt_id}", status_code=204, dependencies=WRITE)
def delete_excerpt(excerpt_id: str, session: Session = Depends(db),
                   user_id: str = Depends(current_user_id)):
    excerpt = session.get(ContextExcerpt, excerpt_id)
    if excerpt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    load_packet(session, excerpt.packet_id)
    set_actor(session, Actor(ActorType.user, user_id, "Withdrew shared excerpt"))
    session.delete(excerpt)
    session.commit()


# ---------------------------------------------------------------- context views

@router.post("/api/packets/{packet_id}/context-views", response_model=ContextViewCreated,
             status_code=201, dependencies=WRITE)
def create_context_view(packet_id: str, body: ContextViewCreate, session: Session = Depends(db),
                        user_id: str = Depends(current_user_id)):
    """Mint a recipient-specific link. The token is in this response and nowhere else."""
    packet = load_packet(session, packet_id)
    settings = get_settings()
    set_actor(session, Actor(ActorType.user, user_id,
                             f"Issued context view to {body.recipient_name}"))
    try:
        view, token = context_views.issue(
            session, packet, recipient_name=body.recipient_name, recipient_email=body.recipient_email,
            created_by=user_id, settings=settings, ttl_days=body.ttl_days)
    except context_views.ViewError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()

    return ContextViewCreated(**view_out(view).model_dump(), token=token,
                              url=context_views.view_url(token, settings))


@router.get("/api/packets/{packet_id}/context-views", response_model=list[ContextViewOut])
def list_context_views(packet_id: str, session: Session = Depends(db)):
    load_packet(session, packet_id)
    rows = session.scalars(select(ContextView).where(ContextView.packet_id == packet_id)
                           .order_by(ContextView.created_at.desc())).all()
    return [view_out(v) for v in rows]


@router.post("/api/context-views/{view_id}/revoke", response_model=ContextViewOut, dependencies=WRITE)
def revoke_context_view(view_id: str, session: Session = Depends(db),
                        user_id: str = Depends(current_user_id)):
    view = session.get(ContextView, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    load_packet(session, view.packet_id)
    set_actor(session, Actor(ActorType.user, user_id, "Revoked context view"))
    context_views.revoke(view)
    session.commit()
    return view_out(view)


@router.get("/api/context-views/{view_id}/accesses", response_model=list[AccessOut])
def list_accesses(view_id: str, limit: int = 200, session: Session = Depends(db)):
    view = session.get(ContextView, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    load_packet(session, view.packet_id)  # scopes the view through its packet's project
    return session.scalars(
        select(ContextViewAccess).where(ContextViewAccess.view_id == view_id)
        .order_by(ContextViewAccess.at.desc()).limit(min(limit, 500))).all()


# ---------------------------------------------------------------- public token surface

def _refuse(session: Session, view: ContextView | None, outcome: str, request: Request) -> HTMLResponse:
    if view is not None:
        context_views.log_access(session, view, outcome, path=request.url.path,
                                 client_ip=_client_ip(request),
                                 user_agent=request.headers.get("user-agent"),
                                 referer=request.headers.get("referer"))
    # 404 for every refusal: an expired link and a made-up one look identical from outside.
    return HTMLResponse(packets.render_unavailable(), status_code=404, headers=NO_STORE)


@public_router.get("/view/{token}", response_class=HTMLResponse)
def context_view_page(token: str, request: Request, session: Session = Depends(get_session)):
    view, outcome = context_views.resolve(session, token)
    if outcome != "ok":
        return _refuse(session, view, outcome, request)

    context_views.log_access(session, view, "ok", path=request.url.path,
                             client_ip=_client_ip(request),
                             user_agent=request.headers.get("user-agent"),
                             referer=request.headers.get("referer"))

    excerpts = [{"id": e.id, "label": e.label,
                 "image_url": f"/view/{token}/excerpt/{e.id}.png"}
                for e in sorted(view.packet.excerpts, key=lambda e: e.created_at)]
    html = packets.render_context_view(
        view.packet, view, excerpts,
        watermark_tile=watermark.tile_data_uri(view.watermark_text))
    return HTMLResponse(html, headers={**NO_STORE, "X-Robots-Tag": "noindex, nofollow",
                                       "Referrer-Policy": "no-referrer"})


@public_router.get("/view/{token}/excerpt/{excerpt_id}.png")
def context_view_excerpt(token: str, excerpt_id: str, request: Request,
                         session: Session = Depends(get_session)):
    """A script excerpt as a watermarked image.

    Rendered per request rather than cached: the watermark is specific to this recipient,
    and an excerpt withdrawn by the producer must stop resolving immediately.
    """
    view, outcome = context_views.resolve(session, token)
    if outcome != "ok":
        if view is not None:
            context_views.log_access(session, view, outcome, path=request.url.path,
                                     client_ip=_client_ip(request),
                                     user_agent=request.headers.get("user-agent"),
                                     referer=request.headers.get("referer"))
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    excerpt = next((e for e in view.packet.excerpts if e.id == excerpt_id), None)
    if excerpt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    context_views.log_access(session, view, "ok", path=request.url.path,
                             client_ip=_client_ip(request),
                             user_agent=request.headers.get("user-agent"),
                             referer=request.headers.get("referer"))

    settings = get_settings()
    png = watermark.excerpt_png(excerpt.text, view.watermark_text, label=excerpt.label,
                                width=settings.excerpt_image_width)
    return Response(png, media_type="image/png",
                    headers={**NO_STORE, "X-Robots-Tag": "noindex, noimageindex"})
