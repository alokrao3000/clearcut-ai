from tests.conftest import ingest, tasks_by_layer

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
LOONEY = "https://www.youtube.com/watch?v=looney0001"
GETTY = "https://www.gettyimages.com/detail/video/times-square-stock-footage/1234567"


# ---------------------------------------------------------------- disclaimer gate

def test_writes_blocked_until_disclaimer_accepted(client):
    body = {"name": "X", "distribution_scope": "festival", "production_tier": "ultra_low"}
    r = client.post("/api/projects", json=body)
    assert r.status_code == 428
    assert r.json()["detail"]["code"] == "disclaimer_required"
    assert client.get("/api/projects").status_code == 200  # reads stay open

    client.post("/api/disclaimer/accept")
    assert client.post("/api/projects", json=body).status_code == 201
    # Acceptance is per user.
    assert client.post("/api/projects", json=body, headers={"X-User-Id": "someone-else"}).status_code == 428


# ---------------------------------------------------------------- ingest + mapping

def test_music_video_becomes_composite_with_label_mapped(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK, "notes": "Jukebox in diner scene", "usage_seconds": 45})
    assert res["status"] == "complete" and not res["duplicate"]

    asset = accepted.get(f"/api/assets/{res['asset_id']}").json()
    assert asset["title"].startswith("Rick Astley")
    assert asset["inferred_keywords"] == ["Rick Astley", "Never Gonna Give You Up"]
    tasks = tasks_by_layer(accepted, res["asset_id"])
    assert set(tasks) == {"footage", "master_recording", "composition"}

    master = tasks["master_recording"]
    assert master["rightsholder"]["id"] == "ent_rca_records"
    assert master["stage"] == "rights_mapped" and master["mapping_method"] == "auto"
    # RCA has no intake of its own; contact resolves up to the parent label group.
    assert master["contact"]["via_rightsholder_id"] == "ent_sony_music_entertainment"

    # No publisher alias for this song, so composition waits for a human.
    assert tasks["composition"]["stage"] == "sourced"
    assert tasks["composition"]["rightsholder"] is None
    # Every layer still gets an estimate from the industry default.
    assert all(t["estimate_high"] is not None for t in tasks.values())


def test_studio_cartoon_maps_to_subsidiary_and_uses_parent_rate_card(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": LOONEY, "usage_seconds": 90})
    footage = tasks_by_layer(accepted, res["asset_id"])["footage"]
    assert footage["rightsholder"]["id"] == "ent_warner_bros_animation"
    assert footage["contact"]["licensing_email"] == "animation-clips@wbd.example"

    b = footage["estimate_breakdown"]
    assert b["rate_basis"] == "parent:ent_warner_bros_discovery"
    assert b["units"] == 1.5
    # 2500..5000 per min x festival 0.35 x ultra-low 0.5 x 1.5 min, rounded to $50
    assert (float(footage["estimate_low"]), float(footage["estimate_high"])) == (650.0, 1300.0)


def test_blocked_site_yields_partial_asset_mapped_to_agency(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": GETTY})
    assert res["status"] == "partial"
    assert "refused" in res["error"]
    asset = accepted.get(f"/api/assets/{res['asset_id']}").json()
    assert asset["platform_asset_id"] == "1234567"
    footage = tasks_by_layer(accepted, res["asset_id"])["footage"]
    assert footage["rightsholder"]["id"] == "ent_getty_images"
    assert footage["estimate_breakdown"]["rate_basis"] == "rightsholder"


def test_duplicate_url_is_not_reingested(accepted, project):
    first = ingest(accepted, project["id"], {"url": RICK})[0]
    again = ingest(accepted, project["id"], {"url": RICK})[0]
    assert again["duplicate"] and again["asset_id"] == first["asset_id"]


def test_editing_metadata_remaps(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": "https://www.pond5.com/stock-footage/item/12345678-sunset"})
    footage = tasks_by_layer(accepted, res["asset_id"])["footage"]
    assert footage["rightsholder"]["id"] == "ent_pond5"

    [res2] = ingest(accepted, project["id"], {"url": "https://example.com/some-newsreel"})
    assert tasks_by_layer(accepted, res2["asset_id"])["footage"]["rightsholder"] is None
    r = accepted.patch(f"/api/assets/{res2['asset_id']}", json={"owner_name": "British Pathé", "title": "Newsreel"})
    assert r.status_code == 200
    assert tasks_by_layer(accepted, res2["asset_id"])["footage"]["rightsholder"]["id"] == "ent_british_pathe"


# ---------------------------------------------------------------- workflow

def test_kanban_guards(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK})
    tasks = tasks_by_layer(accepted, res["asset_id"])
    comp, master = tasks["composition"], tasks["master_recording"]

    def move(task, to, **extra):
        return accepted.post(f"/api/tasks/{task['id']}/transition", json={"to": to, **extra})

    assert move(comp, "rights_mapped").status_code == 409  # no rightsholder
    assert move(master, "outreach_sent").status_code == 409  # cannot skip stages
    assert move(master, "budget_approved").status_code == 200
    assert move(master, "outreach_sent").status_code == 200
    r = move(master, "quote_received")
    assert r.status_code == 409 and "quoted amount" in r.json()["detail"]

    accepted.patch(f"/api/tasks/{master['id']}", json={"quoted_amount": "1800.00"})
    assert move(master, "quote_received").status_code == 200
    assert move(master, "denied").status_code == 200
    assert move(master, "sourced").json()["stage"] == "sourced"  # reopen

    board = accepted.get(f"/api/projects/{project['id']}/board").json()
    assert len(board["sourced"]) == 3


def test_manual_override_is_audited_and_locks_task(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK})
    comp = tasks_by_layer(accepted, res["asset_id"])["composition"]

    r = accepted.patch(f"/api/tasks/{comp['id']}", headers={"X-User-Id": "dev-user"},
                       json={"rightsholder_id": "ent_sony_music_publishing", "reason": "Per PRO lookup"})
    assert r.status_code == 200, r.text
    comp = r.json()
    assert comp["mapping_method"] == "manual" and comp["stage"] == "rights_mapped"

    # Re-running the matcher must not undo a human decision.
    accepted.post(f"/api/assets/{res['asset_id']}/remap")
    assert tasks_by_layer(accepted, res["asset_id"])["composition"]["rightsholder"]["id"] == \
        "ent_sony_music_publishing"

    history = accepted.get(f"/api/tasks/{comp['id']}/history").json()
    actors = [(h["action"], h["actor_type"], h["actor_id"]) for h in history]
    assert actors[0] == ("insert", "scraper", "ingest:youtube")
    assert ("update", "system", "budget_matrix") in actors
    override = next(h for h in history if "rightsholder_id" in h["changes"] and h["actor_type"] == "user")
    assert override["actor_id"] == "dev-user" and override["reason"] == "Per PRO lookup"
    assert override["changes"]["rightsholder_id"] == [None, "ent_sony_music_publishing"]

    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    auto = accepted.get(f"/api/tasks/{master['id']}/history").json()
    assert any(h["actor_id"] == "rights_matcher" and "rightsholder_id" in h["changes"] for h in auto)


def test_reassignment_blocked_after_outreach(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    for stage in ("budget_approved", "outreach_sent"):
        accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": stage})
    r = accepted.patch(f"/api/tasks/{master['id']}", json={"rightsholder_id": "ent_universal_music_group"})
    assert r.status_code == 409


def test_add_layer(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": LOONEY})
    r = accepted.post(f"/api/assets/{res['asset_id']}/layers", json={"layer": "trademark"})
    assert r.status_code == 201 and r.json()["layer"] == "trademark"
    assert accepted.post(f"/api/assets/{res['asset_id']}/layers", json={"layer": "trademark"}).status_code == 409


# ---------------------------------------------------------------- budget

def test_scope_change_reestimates_open_tasks_only(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": LOONEY, "usage_seconds": 60})
    tasks = tasks_by_layer(accepted, res["asset_id"])
    footage, master = tasks["footage"], tasks["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "sourced"})  # stays unmapped
    before_budget = accepted.get(f"/api/projects/{project['id']}/budget").json()

    accepted.post(f"/api/tasks/{footage['id']}/transition", json={"to": "budget_approved"})
    approved_high = footage["estimate_high"]

    accepted.patch(f"/api/projects/{project['id']}",
                   json={"distribution_scope": "all_media_perpetual", "production_tier": "studio_feature"})
    after = tasks_by_layer(accepted, res["asset_id"])
    assert after["footage"]["estimate_high"] == approved_high  # approved budget untouched
    assert float(after["composition"]["estimate_high"]) > float(tasks["composition"]["estimate_high"])

    totals = accepted.get(f"/api/projects/{project['id']}/budget").json()
    assert float(totals["estimate_high"]) > float(before_budget["estimate_high"])
    assert float(totals["recommended_contingency"]) > 0


# ---------------------------------------------------------------- directory + audit

def test_directory_search_and_hierarchy(accepted):
    results = accepted.get("/api/rightsholders", params={"q": "warner bros"}).json()
    ids = [r["id"] for r in results]
    assert "ent_warner_bros_pictures" in ids[:3]

    wbd = accepted.get("/api/rightsholders/ent_warner_bros_discovery").json()
    assert {c["id"] for c in wbd["children"]} >= {"ent_warner_bros_pictures", "ent_warner_bros_animation"}

    labels = accepted.get("/api/rightsholders", params={"layer": "master_recording"}).json()
    assert {r["kind"] for r in labels} <= {"label", "individual"}

    r = accepted.patch("/api/rightsholders/ent_warner_bros_discovery",
                       json={"parent_id": "ent_warner_bros_animation"})
    assert r.status_code == 422  # cycle


def test_user_created_rightsholder(accepted):
    r = accepted.post("/api/rightsholders", json={
        "id": "ent_jane_filmmaker", "name": "Jane Filmmaker", "kind": "individual",
        "licensing_email": "jane@filmmaker.example", "aliases": ["Jane F."]})
    assert r.status_code == 201
    assert r.json()["is_placeholder"] is False
    audit = accepted.get("/api/audit", params={"table": "rightsholders", "row_id": "ent_jane_filmmaker"}).json()
    assert audit[0]["actor_type"] == "user"
