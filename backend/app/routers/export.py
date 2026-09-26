"""E&O export endpoints: the clearance record as JSON, CSV or PDF.

Reads only, and scoped like everything else. The PDF goes through the same probed WeasyPrint
seam as the outreach letters, so a host without the native stack still serves the HTML and
both CSVs rather than failing the whole export.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.deps import db, scoped_project
from app.models import Organization
from app.services import export, pdf
from app.services.mapping import effective_contact
from app.services.packets import (LAYER_LABEL, SCOPE_LABEL, STAGE_LABEL, TEMPLATES, TIER_LABEL,
                                  _env)

router = APIRouter(prefix="/api/projects/{project_id}/export", tags=["export"])

# The printable report shows the most recent slice; the CSV carries everything.
MAX_LEDGER_ROWS = 400


def _filename(project_name: str, suffix: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in (project_name or "project"))[:50].strip("-")
    return f"{slug or 'project'}-clearance-record.{suffix}"


def _attachment(body: bytes | str, media_type: str, filename: str) -> Response:
    data = body.encode("utf-8") if isinstance(body, str) else body
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store, private",
    })


def _money(value) -> str:
    return "—" if value is None else f"${value:,.0f}"


# Some audited values are whole JSON documents — an estimate breakdown runs to several
# hundred characters. Printed in full they bury the column that matters. The untruncated
# value is in the ledger CSV, which is what a reviewer reads when they want the detail.
MAX_VALUE_CHARS = 120


def _short(value) -> str:
    if value is None:
        return "—"
    text = str(value)
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS].rstrip() + "…"


def _report_context(session: Session, data: export.ExportData) -> dict:
    project = data.project
    summary = export.summary(data)

    rights = []
    for task in data.tasks:
        holder = task.rightsholder
        rights.append({
            "title": task.asset.title or "Untitled material",
            "source": "" if task.asset.raw_source.startswith("script:") else task.asset.raw_source,
            "layer": LAYER_LABEL.get(task.layer, task.layer),
            "stage": STAGE_LABEL.get(task.stage, task.stage),
            "rightsholder": holder.name if holder else None,
            "contact": effective_contact(holder)["licensing_email"] if holder else None,
            "basis": export._mapping_basis(task),
            "estimate": (f"{_money(task.estimate_low)} – {_money(task.estimate_high)}"
                         if task.estimate_high is not None else "—"),
            "quoted": _money(task.quoted_amount),
            "agreed": _money(task.agreed_amount),
        })

    packets = []
    for packet in data.packets:
        sent = [m for m in (packet.thread.outbound if packet.thread else []) if m.status == "sent"]
        packets.append({
            "rightsholder": packet.rightsholder.name,
            "template": TEMPLATES.get(packet.template, packet.template).split("—")[0].strip(),
            "sent_at": sent[0].sent_at.strftime("%d %b %Y %H:%M") if sent and sent[0].sent_at else None,
            "to_email": sent[0].to_email if sent else packet.recipient_email,
            "links_issued": len(packet.context_views),
            "link_opens": sum(len([a for a in v.accesses if a.outcome == "ok"])
                              for v in packet.context_views),
            "excerpts": len(packet.excerpts),
        })

    ledger = []
    for row in reversed(data.audit):
        for name, (old, new) in (row.changes or {}).items():
            ledger.append({
                "at": row.at.strftime("%d %b %Y %H:%M") if row.at else "",
                "table": row.table_name, "actor_type": row.actor_type, "actor_id": row.actor_id,
                "field": name, "reason": row.reason,
                "change": (f"{_short(old)} → {_short(new)}" if row.action == "update"
                           else ("set to " + _short(new) if row.action == "insert" else "removed")),
            })

    acceptances = [{
        "user": user.email if user else row.user_id,
        "version": row.version,
        "at": row.accepted_at.strftime("%d %b %Y %H:%M") if row.accepted_at else "",
    } for row, user in data.acceptances]

    return {
        "project": project,
        "organization": session.get(Organization, project.org_id),
        "scope_label": SCOPE_LABEL.get(project.distribution_scope, project.distribution_scope),
        "tier_label": TIER_LABEL.get(project.production_tier, project.production_tier),
        "generated_at": data.generated_at.strftime("%d %B %Y, %H:%M UTC"),
        "summary": summary,
        "rights": rights,
        "packets": packets,
        "ledger": ledger[:MAX_LEDGER_ROWS],
        "truncated": len(ledger) > MAX_LEDGER_ROWS,
        "acceptances": acceptances,
    }


def _collect(session: Session, project_id: str) -> export.ExportData:
    return export.collect(session, scoped_project(session, project_id))


@router.get("")
def export_summary(project_id: str, session: Session = Depends(db)):
    """The headline numbers, including whether the independent database check was available."""
    return export.summary(_collect(session, project_id))


@router.get("/rights.csv")
def rights_csv(project_id: str, session: Session = Depends(db)):
    """One row per clearance task: what it is, who it went to, and on what basis."""
    data = _collect(session, project_id)
    return _attachment(export.to_csv(data), "text/csv; charset=utf-8",
                       _filename(data.project.name, "csv"))


@router.get("/ledger.csv")
def ledger_csv(project_id: str, session: Session = Depends(db)):
    """The complete field-level history, one row per recorded change."""
    data = _collect(session, project_id)
    return _attachment(export.ledger_csv(data), "text/csv; charset=utf-8",
                       _filename(data.project.name + "-ledger", "csv"))


@router.get("/report.html", response_class=HTMLResponse)
def report_html(project_id: str, session: Session = Depends(db)):
    data = _collect(session, project_id)
    html = _env.get_template("export/eo_report.html").render(**_report_context(session, data))
    return HTMLResponse(html, headers={"Cache-Control": "no-store, private"})


@router.get("/report.pdf")
def report_pdf(project_id: str, session: Session = Depends(db)):
    data = _collect(session, project_id)
    html = _env.get_template("export/eo_report.html").render(**_report_context(session, data))
    try:
        rendered = pdf.render(html)
    except pdf.PdfUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _attachment(rendered, "application/pdf", _filename(data.project.name, "pdf"))
