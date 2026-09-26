"""Script upload, the inline job path, and confirming a mention into an asset."""

import pytest

from app.services import extract, handlers
from app.services.extract import ExtractionResult, Mention
from tests.test_scripts import SCREENPLAY, docx_bytes, fdx_bytes


@pytest.fixture
def stub_extractor(monkeypatch):
    """Replace the network call. The job, the DB writes and the API stay real."""
    def fake(scenes, settings, client=None):
        return ExtractionResult(
            model="claude-opus-5",
            scenes_read=len(scenes),
            mentions=[
                Mention(scene_index=0, title="Never Gonna Give You Up", owner_name="Rick Astley",
                        kind="music", quote='The jukebox plays "Never Gonna Give You Up" by Rick Astley.',
                        suggested_layers=["master_recording", "composition"], confidence=0.95,
                        reasoning="A named recording plays on screen."),
                Mention(scene_index=1, title="Coca-Cola", kind="trademark",
                        quote="A Coca-Cola sign buzzes overhead.", suggested_layers=["trademark"],
                        confidence=0.8, reasoning="Brand signage is visible."),
            ],
        )

    monkeypatch.setattr(extract, "extract_mentions", fake)
    monkeypatch.setattr(handlers.extract, "extract_mentions", fake)
    return fake


def upload(client, project_id, data=None, filename="movie.fdx"):
    data = data if data is not None else fdx_bytes(
        ("INT. DINER - NIGHT", 'The jukebox plays "Never Gonna Give You Up" by Rick Astley.'),
        ("EXT. PARKING LOT - NIGHT", "A Coca-Cola sign buzzes overhead."),
    )
    return client.post(f"/api/projects/{project_id}/scripts",
                       files={"file": (filename, data, "application/octet-stream")})


def test_upload_parses_scenes_and_runs_extraction_inline(project, accepted, stub_extractor):
    response = upload(accepted, project["id"])
    assert response.status_code == 201, response.text
    script = response.json()

    assert script["media_type"] == "fdx"
    assert script["scene_count"] == 2
    assert script["status"] == "complete"
    assert script["mention_count"] == 2
    assert script["extraction_model"] == "claude-opus-5"

    job = accepted.get(f"/api/jobs/{script['job_id']}").json()
    assert job["kind"] == "extract_script"
    assert job["status"] == "complete"
    assert job["result"]["mentions"] == 2


def test_scenes_keep_their_text_and_order(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    scenes = accepted.get(f"/api/scripts/{script['id']}/scenes").json()
    assert [s["index"] for s in scenes] == [0, 1]
    assert scenes[0]["heading"] == "INT. DINER - NIGHT"
    assert "jukebox" in scenes[0]["text"]


def test_mentions_link_back_to_their_scene(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mentions = accepted.get(f"/api/scripts/{script['id']}/mentions").json()

    assert [m["title"] for m in mentions] == ["Never Gonna Give You Up", "Coca-Cola"]
    first = mentions[0]
    assert first["scene_heading"] == "INT. DINER - NIGHT"
    assert first["scene_index"] == 0
    assert first["quote"].startswith("The jukebox plays")
    assert first["suggested_layers"] == ["master_recording", "composition"]
    assert first["status"] == "proposed"
    assert first["asset_id"] is None


def test_extraction_creates_no_assets_until_a_human_confirms(project, accepted, stub_extractor):
    upload(accepted, project["id"])
    assert accepted.get(f"/api/projects/{project['id']}/assets").json() == []


def test_confirming_a_mention_creates_the_asset_and_its_layer_tasks(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]

    response = accepted.post(f"/api/mentions/{mention['id']}/confirm", json={"usage_seconds": 40})
    assert response.status_code == 200, response.text
    asset = response.json()

    assert asset["source_type"] == "script_ingest"
    assert asset["title"] == "Never Gonna Give You Up"
    assert asset["usage_seconds"] == 40
    assert asset["user_notes"].startswith("The jukebox plays")
    assert sorted(t["layer"] for t in asset["tasks"]) == ["composition", "master_recording"]
    # The frozen payload records where the claim came from, for the audit trail.
    assert asset["raw_source"].startswith("script:")

    refreshed = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]
    assert refreshed["status"] == "confirmed"
    assert refreshed["asset_id"] == asset["id"]


def test_confirming_runs_the_matcher_and_budget(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]
    asset = accepted.post(f"/api/mentions/{mention['id']}/confirm", json={}).json()

    master = next(t for t in asset["tasks"] if t["layer"] == "master_recording")
    assert master["estimate_high"] is not None
    assert master["estimate_breakdown"]["rate_basis"]


def test_confirm_can_override_the_suggested_layers(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]
    asset = accepted.post(f"/api/mentions/{mention['id']}/confirm",
                          json={"layers": ["composition"], "title": "Corrected Title"}).json()
    assert [t["layer"] for t in asset["tasks"]] == ["composition"]
    assert asset["title"] == "Corrected Title"


def test_confirm_is_idempotent(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]
    first = accepted.post(f"/api/mentions/{mention['id']}/confirm", json={}).json()
    second = accepted.post(f"/api/mentions/{mention['id']}/confirm", json={}).json()
    assert first["id"] == second["id"]
    assert len(accepted.get(f"/api/projects/{project['id']}/assets").json()) == 1


def test_a_mention_with_no_layers_cannot_be_confirmed_blindly(project, accepted, monkeypatch):
    def no_layers(scenes, settings, client=None):
        return ExtractionResult(model="claude-opus-5", scenes_read=len(scenes), mentions=[
            Mention(scene_index=0, title="Unclear thing", kind="other", quote="something",
                    suggested_layers=[], confidence=0.3, reasoning="unclear"),
        ])

    monkeypatch.setattr(handlers.extract, "extract_mentions", no_layers)
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[0]

    assert accepted.post(f"/api/mentions/{mention['id']}/confirm", json={}).status_code == 422
    ok = accepted.post(f"/api/mentions/{mention['id']}/confirm", json={"layers": ["trademark"]})
    assert ok.status_code == 200


def test_dismissing_a_mention(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    mention = accepted.get(f"/api/scripts/{script['id']}/mentions").json()[1]
    assert accepted.post(f"/api/mentions/{mention['id']}/dismiss").json()["status"] == "dismissed"


def test_extraction_failure_leaves_the_scenes_usable(project, accepted, monkeypatch):
    def unavailable(scenes, settings, client=None):
        raise extract.ExtractionUnavailable("no credentials configured")

    monkeypatch.setattr(handlers.extract, "extract_mentions", unavailable)
    script = upload(accepted, project["id"]).json()

    assert script["status"] == "complete"
    assert "Extraction skipped" in script["error"]
    assert script["scene_count"] == 2
    assert accepted.get(f"/api/scripts/{script['id']}/scenes").json()[0]["heading"]


def test_a_crashing_handler_marks_the_job_failed(project, accepted, monkeypatch):
    def boom(scenes, settings, client=None):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(handlers.extract, "extract_mentions", boom)
    script = upload(accepted, project["id"]).json()

    job = accepted.get(f"/api/jobs/{script['job_id']}").json()
    assert job["status"] == "failed"
    assert "model exploded" in job["error"]
    # Parsing still happened, so the upload is not lost.
    assert len(accepted.get(f"/api/scripts/{script['id']}/scenes").json()) == 2


def test_unsupported_file_type_is_rejected(project, accepted):
    response = upload(accepted, project["id"], data=b"just notes", filename="notes.txt")
    assert response.status_code == 422
    assert "pdf" in response.json()["detail"].lower()


def test_docx_upload(project, accepted, stub_extractor):
    script = upload(accepted, project["id"], data=docx_bytes(SCREENPLAY), filename="movie.docx").json()
    assert script["media_type"] == "docx"
    assert script["scene_count"] == 3


def test_script_upload_needs_the_disclaimer(project, accepted):
    """Acceptance is per user: a colleague in the same organization must accept it too."""
    from tests.conftest import TEST_PASSWORD

    accepted.post("/api/users", json={"email": "colleague@test.example", "name": "Colleague",
                                      "password": TEST_PASSWORD, "role": "member"})
    token = accepted.post("/api/auth/login", json={
        "email": "colleague@test.example", "password": TEST_PASSWORD}).json()["access_token"]

    response = accepted.post(
        f"/api/projects/{project['id']}/scripts",
        files={"file": ("movie.fdx", fdx_bytes(("INT. A - DAY", "action")), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "disclaimer_required"


def test_deferred_ingest_returns_a_job(project, accepted):
    response = accepted.post(f"/api/projects/{project['id']}/ingest", json={
        "items": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "usage_seconds": 30}],
        "defer": True,
    })
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "ingest_urls"
    assert job["status"] == "complete"  # inline without a worker
    assert job["result"]["ingested"] == 1
    assert len(accepted.get(f"/api/projects/{project['id']}/assets").json()) == 1


def test_jobs_can_be_listed_per_project(project, accepted, stub_extractor):
    upload(accepted, project["id"])
    jobs = accepted.get("/api/jobs", params={"project_id": project["id"]}).json()
    assert [j["kind"] for j in jobs] == ["extract_script"]


def test_deleting_a_script_removes_its_scenes_and_mentions(project, accepted, stub_extractor):
    script = upload(accepted, project["id"]).json()
    assert accepted.delete(f"/api/scripts/{script['id']}").status_code == 204
    assert accepted.get(f"/api/scripts/{script['id']}").status_code == 404
