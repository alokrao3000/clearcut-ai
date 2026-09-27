"""The E&O export: does the record actually evidence how each decision was made?"""

import csv
import io

from tests.conftest import ingest, tasks_by_layer

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def worked_project(client, project):
    """A project taken far enough to have provenance worth exporting."""
    [res] = ingest(client, project["id"], {"url": RICK, "notes": "Diner jukebox",
                                           "usage_seconds": 45})
    tasks = tasks_by_layer(client, res["asset_id"])
    master, comp = tasks["master_recording"], tasks["composition"]

    # One assignment by the matcher, one overridden by a person with a stated reason.
    client.patch(f"/api/tasks/{comp['id']}",
                 json={"rightsholder_id": "ent_sony_music_publishing",
                       "reason": "Confirmed against the PRO database"})
    client.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    client.patch(f"/api/tasks/{master['id']}", json={"quoted_amount": "2500.00"})
    return {"asset_id": res["asset_id"], "master": master["id"], "composition": comp["id"]}


def rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


# ---------------------------------------------------------------- summary

def test_summary_separates_automated_from_human_decisions(accepted, project):
    worked_project(accepted, project)
    body = accepted.get(f"/api/projects/{project['id']}/export").json()

    assert body["tasks"] == 3
    assert body["assigned_by_a_person"] == 1
    assert body["assigned_automatically"] >= 1
    assert body["ledger_entries"] > 0
    # The point of the actor column: a reviewer can see which changes were not human.
    assert set(body["actor_breakdown"]) >= {"user", "scraper", "system"}


def test_the_database_check_admits_when_it_cannot_run(accepted, project):
    """On SQLite there is no trigger, and saying so beats implying a clean result."""
    body = accepted.get(f"/api/projects/{project['id']}/export").json()
    assert body["reconciliation"]["available"] is False
    assert "cannot be ruled out" in body["reconciliation"]["note"]


def test_the_disclaimer_version_is_part_of_the_record(accepted, project):
    body = accepted.get(f"/api/projects/{project['id']}/export").json()
    assert body["disclaimer_version"]
    assert "advisory" in body["disclaimer_text"]


# ---------------------------------------------------------------- rights CSV

def test_rights_csv_states_the_basis_for_every_assignment(accepted, project):
    worked_project(accepted, project)
    r = accepted.get(f"/api/projects/{project['id']}/export/rights.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    data = rows(r.text)
    assert len(data) == 3
    bases = {row["layer"]: row["assignment_basis"] for row in data}
    assert bases["Synchronisation"] == "Manual override by a named user"
    assert bases["Master use"].startswith("Automated match, confidence")

    master = next(row for row in data if row["layer"] == "Master use")
    assert master["quoted"] == "2500.00"
    assert master["rightsholder"]
    assert master["licensing_contact"].endswith(".example")


def test_rights_csv_does_not_leak_internal_script_locators(accepted, project):
    worked_project(accepted, project)
    text = accepted.get(f"/api/projects/{project['id']}/export/rights.csv").text
    assert "script:" not in text


# ---------------------------------------------------------------- ledger CSV

def test_ledger_csv_carries_actor_and_reason_per_field(accepted, project):
    worked_project(accepted, project)
    data = rows(accepted.get(f"/api/projects/{project['id']}/export/ledger.csv").text)
    assert data

    override = [row for row in data
                if row["field"] == "rightsholder_id" and row["actor_type"] == "user"]
    assert override, "the manual assignment should be in the ledger"
    assert override[0]["reason"] == "Confirmed against the PRO database"
    assert override[0]["new_value"] == "ent_sony_music_publishing"

    # The matcher's own work is attributed to the system, not to the person who was signed in.
    assert any(row["actor_type"] == "system" for row in data)


def test_ledger_export_is_scoped_to_one_organization(accepted, other_org, project):
    worked_project(accepted, project)
    # The other tenant cannot export this project at all.
    assert other_org.get(f"/api/projects/{project['id']}/export").status_code == 404
    assert other_org.get(f"/api/projects/{project['id']}/export/ledger.csv").status_code == 404


# ---------------------------------------------------------------- report

def test_the_report_shows_the_decisions_and_the_caveat(accepted, project):
    worked_project(accepted, project)
    html = accepted.get(f"/api/projects/{project['id']}/export/report.html").text

    assert "Clearance record" in html
    assert "Basis for that assignment" in html
    assert "Manual override by a named user" in html
    assert "Independent database check" in html
    # The report must not read as a clearance certificate.
    assert "not a legal opinion" in html
    assert "advisory structural drafts" in html


def test_the_report_pdf_either_renders_or_explains_itself(accepted, project):
    worked_project(accepted, project)
    r = accepted.get(f"/api/projects/{project['id']}/export/report.pdf")
    if accepted.get("/api/outreach/pdf-status").json()["available"]:
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
    else:
        assert r.status_code == 503
        assert "native libraries" in r.json()["detail"]


def test_outreach_and_disclosure_appear_in_the_record(accepted, project):
    """What went out, and every tokenized link issued and opened."""
    ids = worked_project(accepted, project)
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [ids["master"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    view = accepted.post(f"/api/packets/{packet['id']}/context-views",
                         json={"recipient_name": "Dana Reyes"}).json()
    accepted.get(f"/view/{view['token']}")

    body = accepted.get(f"/api/projects/{project['id']}/export").json()
    assert body["packets"] == 1
    assert body["context_links"] == 1

    html = accepted.get(f"/api/projects/{project['id']}/export/report.html").text
    assert "Outreach and disclosure" in html
    assert "Times opened" in html


def test_the_ledger_covers_every_table_it_claims_to(accepted, project):
    """The packet-side records are keyed by their own ids, not the packet's.

    Collecting only project, asset, task and packet ids silently drops the context views,
    excerpts, outreach messages and reply trail — the exact things the export exists to
    evidence.
    """
    from app.services.export import LEDGER_TABLES

    ids = worked_project(accepted, project)
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [ids["master"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    accepted.post(f"/api/packets/{packet['id']}/context-views",
                  json={"recipient_name": "Dana Reyes"})

    tables = {row["table"] for row in
              rows(accepted.get(f"/api/projects/{project['id']}/export/ledger.csv").text)}

    # Everything this project actually produced must be present.
    for expected in ("projects", "assets", "clearance_tasks", "outreach_packets",
                     "packet_tasks", "context_views"):
        assert expected in tables, f"{expected} missing from the ledger export"
    assert tables <= set(LEDGER_TABLES)


def test_outreach_messages_and_the_reply_trail_reach_the_ledger(accepted, project, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_reserved_tld_recipients", True)
    ids = worked_project(accepted, project)
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [ids["master"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    assert accepted.post(f"/api/packets/{packet['id']}/send",
                         json={"allow_unverified": True}).status_code == 200

    tables = {row["table"] for row in
              rows(accepted.get(f"/api/projects/{project['id']}/export/ledger.csv").text)}
    assert "outbound_messages" in tables, "what was actually sent must be in the record"
