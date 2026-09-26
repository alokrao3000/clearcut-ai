"""Outreach packets, script excerpts, and the tokenized context view.

The security-shaped assertions here are the point of the milestone: internal estimates must
not reach a recipient render, a dead token must be indistinguishable from a made-up one, and
every hit on a link must land in the access log.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ContextView
from app.services import packets
from tests.conftest import ingest, tasks_by_layer
from tests.test_scripts import fdx_bytes

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
PATHE = "https://www.britishpathe.com/video/some-newsreel"


# ---------------------------------------------------------------- fixtures

def approve(client, task):
    """Walk a task to budget_approved, the stage outreach actually starts from."""
    r = client.post(f"/api/tasks/{task['id']}/transition", json={"to": "budget_approved"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def music_tasks(accepted, project):
    """A Rick Astley ingest: master -> RCA (under Sony), composition -> unmapped."""
    [res] = ingest(accepted, project["id"], {"url": RICK, "notes": "Jukebox in the diner",
                                             "usage_seconds": 45})
    return res["asset_id"], tasks_by_layer(accepted, res["asset_id"])


@pytest.fixture
def packet(accepted, project, music_tasks):
    _, tasks = music_tasks
    master = approve(accepted, tasks["master_recording"])
    r = accepted.post(f"/api/projects/{project['id']}/packets",
                      json={"task_ids": [master["id"]]})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- grouping

def test_groups_are_keyed_on_the_licensing_desk_not_the_rightsholder(accepted, project, music_tasks):
    """RCA has no intake of its own, so its mail groups under Sony Music Entertainment."""
    _, tasks = music_tasks
    approve(accepted, tasks["master_recording"])

    groups = accepted.get(f"/api/projects/{project['id']}/packet-groups").json()
    by_id = {g["rightsholder_id"]: g for g in groups}
    assert "ent_sony_music_entertainment" in by_id
    group = by_id["ent_sony_music_entertainment"]
    assert group["licensing_email"] == "sync@sonymusic.example"
    assert group["task_ids"] == [tasks["master_recording"]["id"]]
    # Seed data is unverified, and the UI has to be able to say so.
    assert group["is_placeholder"] is True


def test_group_suggests_the_directorys_preferred_template(accepted, project, music_tasks):
    _, tasks = music_tasks
    approve(accepted, tasks["master_recording"])
    [group] = [g for g in accepted.get(f"/api/projects/{project['id']}/packet-groups").json()
               if g["rightsholder_id"] == "ent_sony_music_entertainment"]
    assert group["suggested_template"] == "master_use_request"


def test_unmapped_and_unapproved_tasks_stay_out_of_grouping(accepted, project, music_tasks):
    """A task nobody is assigned to has no desk to be grouped under."""
    _, tasks = music_tasks
    assert tasks["composition"]["rightsholder"] is None
    groups = accepted.get(f"/api/projects/{project['id']}/packet-groups").json()
    grouped = {tid for g in groups for tid in g["task_ids"]}
    assert tasks["composition"]["id"] not in grouped


# ---------------------------------------------------------------- creation

def test_packet_defaults_come_from_the_directory(packet):
    assert packet["template"] == "master_use_request"
    assert packet["rightsholder"]["id"] == "ent_sony_music_entertainment"
    assert packet["recipient_email"] == "sync@sonymusic.example"
    assert packet["status"] == "draft"
    assert "Master use" in packet["subject"]
    assert len(packet["items"]) == 1


def test_tasks_for_different_desks_cannot_share_a_packet(accepted, project, music_tasks):
    _, tasks = music_tasks
    approve(accepted, tasks["master_recording"])
    [res] = ingest(accepted, project["id"], {"url": PATHE})
    pathe = tasks_by_layer(accepted, res["asset_id"])["footage"]
    accepted.patch(f"/api/tasks/{pathe['id']}", json={"rightsholder_id": "ent_british_pathe"})
    approve(accepted, accepted.get(f"/api/tasks/{pathe['id']}").json())

    r = accepted.post(f"/api/projects/{project['id']}/packets",
                      json={"task_ids": [tasks["master_recording"]["id"], pathe["id"]]})
    assert r.status_code == 422
    assert "one licensing desk" in r.json()["detail"]


def test_packet_needs_an_assigned_rightsholder(accepted, project, music_tasks):
    _, tasks = music_tasks
    r = accepted.post(f"/api/projects/{project['id']}/packets",
                      json={"task_ids": [tasks["composition"]["id"]]})
    assert r.status_code == 422
    assert "Assign a rightsholder" in r.json()["detail"]


def test_tasks_from_another_project_are_refused(accepted, project, music_tasks):
    _, tasks = music_tasks
    other = accepted.post("/api/projects", json={"name": "Other", "distribution_scope": "festival",
                                                 "production_tier": "ultra_low"}).json()
    r = accepted.post(f"/api/projects/{other['id']}/packets",
                      json={"task_ids": [tasks["master_recording"]["id"]]})
    assert r.status_code == 422
    assert "Not in this project" in r.json()["detail"]


def test_unknown_template_is_rejected_by_name(accepted, project, music_tasks):
    _, tasks = music_tasks
    master = approve(accepted, tasks["master_recording"])
    r = accepted.post(f"/api/projects/{project['id']}/packets",
                      json={"task_ids": [master["id"]], "template": "../../etc/passwd"})
    assert r.status_code == 422
    assert "Unknown template" in r.json()["detail"]


def test_disclaimer_gate_covers_the_new_write_endpoints(client):
    """`client` has not accepted the disclaimer; the gate runs before the handler does."""
    assert client.post("/api/projects/p/packets", json={"task_ids": ["x"]}).status_code == 428
    assert client.post("/api/packets/p/excerpts", json={"scene_id": "s"}).status_code == 428
    assert client.post("/api/packets/p/context-views",
                       json={"recipient_name": "Jane"}).status_code == 428
    assert client.post("/api/packets/p/finalize", json={}).status_code == 428


# ---------------------------------------------------------------- rendering

def test_internal_preview_shows_estimates_and_the_recipient_render_does_not(accepted, packet):
    internal = accepted.get(f"/api/packets/{packet['id']}/preview").text
    external = accepted.get(f"/api/packets/{packet['id']}/preview?internal=false").text

    assert "Internal only" in internal
    assert "Sony Music Entertainment" in external
    assert "Internal only" not in external
    # The estimate range itself must not appear in what a licensing desk reads.
    estimate = packet["items"][0]["estimate_low"]
    assert estimate is not None
    assert f"{float(estimate):,.0f}" not in external


def test_letter_carries_the_ask_and_the_disclaimer(accepted, packet):
    html = accepted.get(f"/api/packets/{packet['id']}/preview?internal=false").text
    assert "Festival exhibition only" in html          # project distribution scope
    assert "Three (3) years" in html                   # term derived from that scope
    assert "advisory structural drafts" in html        # disclaimer footer survives
    assert "Jukebox in the diner" in html              # per-asset context
    assert "Approx. 45 seconds" in html                # planned usage


def test_pdf_either_renders_or_explains_itself(accepted, packet):
    """WeasyPrint needs native libraries that a dev box often lacks; neither path may 500."""
    r = accepted.get(f"/api/packets/{packet['id']}/pdf")
    status = accepted.get("/api/outreach/pdf-status").json()

    if status["available"]:
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        assert "attachment" in r.headers["content-disposition"]
    else:
        assert r.status_code == 503
        assert "native libraries" in r.json()["detail"]
        assert status["install_hint"]


def test_template_catalogue_is_the_allowlist(accepted):
    names = {t["name"] for t in accepted.get("/api/outreach/templates").json()}
    assert names == set(packets.TEMPLATES)


# ---------------------------------------------------------------- finalize

def test_finalize_freezes_the_letter_and_moves_the_tasks(accepted, packet):
    r = accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "finalized"
    assert out["finalized_at"]
    assert out["items"][0]["stage"] == "outreach_sent"

    # Editing a frozen record of what was sent is refused.
    assert accepted.patch(f"/api/packets/{packet['id']}", json={"subject": "new"}).status_code == 409


def test_finalized_letter_is_served_from_the_snapshot(accepted, packet):
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    frozen = accepted.get(f"/api/packets/{packet['id']}/preview?internal=false").text
    assert "Sony Music Entertainment" in frozen
    # The snapshot is what the ledger holds, not a re-render.
    assert "advisory structural drafts" in frozen


def test_finalize_refuses_to_skip_the_budget_gate(accepted, project, music_tasks):
    _, tasks = music_tasks
    master = tasks["master_recording"]  # still rights_mapped, budget not approved
    created = accepted.post(f"/api/projects/{project['id']}/packets",
                            json={"task_ids": [master["id"]]}).json()
    r = accepted.post(f"/api/packets/{created['id']}/finalize", json={})
    assert r.status_code == 409
    assert "approve their budgets first" in r.json()["detail"]

    # ...but the letter itself can still be frozen without moving anything.
    r = accepted.post(f"/api/packets/{created['id']}/finalize", json={"transition_tasks": False})
    assert r.status_code == 200
    assert r.json()["items"][0]["stage"] == "rights_mapped"


# ---------------------------------------------------------------- excerpts

@pytest.fixture
def scene(accepted, project):
    data = fdx_bytes(("INT. DINER - NIGHT",
                      "MARIA feeds the jukebox a quarter. The record drops and the room changes."))
    script = accepted.post(f"/api/projects/{project['id']}/scripts",
                           files={"file": ("movie.fdx", data, "application/octet-stream")}).json()
    return accepted.get(f"/api/scripts/{script['id']}/scenes").json()[0]


def test_excerpt_freezes_the_selected_text(accepted, packet, scene):
    r = accepted.post(f"/api/packets/{packet['id']}/excerpts", json={"scene_id": scene["id"]})
    assert r.status_code == 201, r.text
    excerpt = r.json()
    assert "jukebox" in excerpt["text"]
    assert "INT. DINER - NIGHT" in excerpt["label"]


def test_excerpt_honours_an_explicit_range(accepted, packet, scene):
    r = accepted.post(f"/api/packets/{packet['id']}/excerpts",
                      json={"scene_id": scene["id"], "start": 0, "end": 30})
    assert r.status_code == 201
    assert len(r.json()["text"]) <= 30


def test_excerpt_range_must_be_non_empty(accepted, packet, scene):
    r = accepted.post(f"/api/packets/{packet['id']}/excerpts",
                      json={"scene_id": scene["id"], "start": 10, "end": 5})
    assert r.status_code == 422


def test_excerpt_cannot_cross_project_boundaries(accepted, packet, scene):
    other = accepted.post("/api/projects", json={"name": "Other", "distribution_scope": "festival",
                                                 "production_tier": "ultra_low"}).json()
    tasks = tasks_by_layer(accepted, ingest(accepted, other["id"], {"url": RICK})[0]["asset_id"])
    approve(accepted, tasks["master_recording"])
    foreign = accepted.post(f"/api/projects/{other['id']}/packets",
                            json={"task_ids": [tasks["master_recording"]["id"]]}).json()

    r = accepted.post(f"/api/packets/{foreign['id']}/excerpts", json={"scene_id": scene["id"]})
    assert r.status_code == 422
    assert "different project" in r.json()["detail"]


def test_oversized_excerpt_is_refused(accepted, packet, scene, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "excerpt_max_chars", 10)
    r = accepted.post(f"/api/packets/{packet['id']}/excerpts", json={"scene_id": scene["id"]})
    assert r.status_code == 422
    assert "limited to 10 characters" in r.json()["detail"]


# ---------------------------------------------------------------- context views

def mint(client, packet_id, **body):
    payload = {"recipient_name": "Jane Doe", "recipient_email": "jane@sonymusic.example", **body}
    r = client.post(f"/api/packets/{packet_id}/context-views", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_token_is_returned_once_and_never_stored(accepted, packet, SessionTest):
    view = mint(accepted, packet["id"])
    assert view["token"] and view["url"].endswith(view["token"])
    assert view["status"] == "active"

    # Nothing in the row lets anyone reconstruct the link.
    with SessionTest() as s:
        row = s.get(ContextView, view["id"])
        assert view["token"] not in row.token_hash
        assert len(row.token_hash) == 64

    # Listing views never discloses it either.
    listed = accepted.get(f"/api/packets/{packet['id']}/context-views").json()
    assert "token" not in listed[0]
    assert listed[0]["token_hint"] == view["token"][:8]


def test_default_expiry_is_fourteen_days(accepted, packet):
    view = mint(accepted, packet["id"])
    expires = datetime.fromisoformat(view["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    assert timedelta(days=13) < expires - datetime.now(UTC) <= timedelta(days=14)


def test_context_page_is_watermarked_for_its_recipient(accepted, packet, scene):
    accepted.post(f"/api/packets/{packet['id']}/excerpts", json={"scene_id": scene["id"]})
    view = mint(accepted, packet["id"])

    r = accepted.get(f"/view/{view['token']}")
    assert r.status_code == 200
    html = r.text
    assert "Jane Doe" in html
    assert "background-image" in html                      # the tiled watermark
    assert "jane%40sonymusic.example" in html or "jane@sonymusic.example" in html
    assert "noindex" in html
    assert r.headers["cache-control"].startswith("no-store")


def test_script_text_never_reaches_the_context_page(accepted, packet, scene):
    """The excerpt is offered as an image. Its words must not be in the markup."""
    accepted.post(f"/api/packets/{packet['id']}/excerpts", json={"scene_id": scene["id"]})
    view = mint(accepted, packet["id"])
    html = accepted.get(f"/view/{view['token']}").text

    assert "MARIA feeds the jukebox" not in html
    assert f"/view/{view['token']}/excerpt/" in html


def test_excerpt_is_served_as_a_png(accepted, packet, scene):
    excerpt = accepted.post(f"/api/packets/{packet['id']}/excerpts",
                            json={"scene_id": scene["id"]}).json()
    view = mint(accepted, packet["id"])

    r = accepted.get(f"/view/{view['token']}/excerpt/{excerpt['id']}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:4] == b"\x89PNG"


def test_a_withdrawn_excerpt_stops_resolving(accepted, packet, scene):
    excerpt = accepted.post(f"/api/packets/{packet['id']}/excerpts",
                            json={"scene_id": scene["id"]}).json()
    view = mint(accepted, packet["id"])
    assert accepted.get(f"/view/{view['token']}/excerpt/{excerpt['id']}.png").status_code == 200

    accepted.delete(f"/api/excerpts/{excerpt['id']}")
    assert accepted.get(f"/view/{view['token']}/excerpt/{excerpt['id']}.png").status_code == 404


def test_estimates_never_reach_the_context_page(accepted, packet):
    view = mint(accepted, packet["id"])
    html = accepted.get(f"/view/{view['token']}").text
    estimate = packet["items"][0]["estimate_high"]
    assert estimate is not None
    assert f"{float(estimate):,.0f}" not in html


# ---------------------------------------------------------------- expiry, revocation, logging

def test_revoked_link_stops_working_and_says_nothing_about_why(accepted, packet):
    view = mint(accepted, packet["id"])
    assert accepted.post(f"/api/context-views/{view['id']}/revoke").json()["status"] == "revoked"

    r = accepted.get(f"/view/{view['token']}")
    assert r.status_code == 404
    assert "no longer available" in r.text
    assert "revoked" not in r.text.lower()


def test_expired_link_stops_working(accepted, packet, SessionTest):
    view = mint(accepted, packet["id"])
    with SessionTest() as s:
        row = s.get(ContextView, view["id"])
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()

    assert accepted.get(f"/view/{view['token']}").status_code == 404
    assert accepted.get(f"/api/packets/{packet['id']}/context-views").json()[0]["status"] == "expired"


def test_an_unknown_token_looks_exactly_like_a_dead_one(accepted, packet):
    view = mint(accepted, packet["id"])
    accepted.post(f"/api/context-views/{view['id']}/revoke")

    dead = accepted.get(f"/view/{view['token']}")
    invented = accepted.get("/view/not-a-real-token-at-all")
    assert dead.status_code == invented.status_code == 404
    assert dead.text == invented.text


def test_every_hit_is_logged_including_the_refusals(accepted, packet, scene):
    excerpt = accepted.post(f"/api/packets/{packet['id']}/excerpts",
                            json={"scene_id": scene["id"]}).json()
    view = mint(accepted, packet["id"])

    accepted.get(f"/view/{view['token']}")
    accepted.get(f"/view/{view['token']}/excerpt/{excerpt['id']}.png")
    accepted.post(f"/api/context-views/{view['id']}/revoke")
    accepted.get(f"/view/{view['token']}")

    log = accepted.get(f"/api/context-views/{view['id']}/accesses").json()
    outcomes = [row["outcome"] for row in log]
    assert outcomes.count("ok") == 2
    assert outcomes.count("revoked") == 1
    assert any(row["path"].endswith(".png") for row in log)

    # Successful hits advance the counters the producer sees; the refusal does not.
    state = accepted.get(f"/api/packets/{packet['id']}/context-views").json()[0]
    assert state["access_count"] == 2
    assert state["last_accessed_at"]


def test_access_log_records_the_caller(accepted, packet):
    view = mint(accepted, packet["id"])
    accepted.get(f"/view/{view['token']}",
                 headers={"User-Agent": "LicensingDesk/1.0", "X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    [row] = accepted.get(f"/api/context-views/{view['id']}/accesses").json()
    assert row["user_agent"] == "LicensingDesk/1.0"
    assert row["client_ip"] == "203.0.113.9"  # leftmost hop, not the proxy


def test_ttl_beyond_the_ceiling_is_refused(accepted, packet):
    r = accepted.post(f"/api/packets/{packet['id']}/context-views",
                      json={"recipient_name": "Jane Doe", "ttl_days": 900})
    assert r.status_code == 422


# ---------------------------------------------------------------- audit

def test_the_ledger_records_who_shared_what(accepted, packet, scene, SessionTest):
    accepted.post(f"/api/packets/{packet['id']}/excerpts", json={"scene_id": scene["id"]})
    mint(accepted, packet["id"])

    history = accepted.get("/api/audit", params={"limit": 500}).json()
    rows = {(r["table_name"], r["action"]) for r in history}
    assert ("outreach_packets", "insert") in rows
    assert ("context_excerpts", "insert") in rows
    assert ("context_views", "insert") in rows

    reasons = [r["reason"] for r in history if r["table_name"] == "context_views"]
    assert any("Issued context view to Jane Doe" == reason for reason in reasons)

    # The token digest is deliberately kept out of the append-only ledger.
    for row in history:
        assert "token_hash" not in row["changes"]
