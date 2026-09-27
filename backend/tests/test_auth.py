"""Authentication, roles, and the tenancy boundary.

The isolation tests are the point of the milestone. They are written as "a second, fully
separate organization tries the first one's ids and gets 404" rather than as unit tests of
`scoped`, because the thing that matters is that no route forgot to call it.
"""

import pytest

from app.models import Project, User
from tests.conftest import TEST_PASSWORD, ingest, register, tasks_by_layer

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# ---------------------------------------------------------------- registration and sign-in

def test_registration_creates_an_organization_and_its_owner(anon):
    body = register(anon, org="Lantern Films", email="ada@lantern.example", name="Ada")
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "ada@lantern.example"

    me = anon.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert me["organization"]["name"] == "Lantern Films"
    assert me["organization"]["slug"] == "lantern-films"


def test_an_email_can_only_be_registered_once(anon):
    register(anon, email="ada@lantern.example")
    r = anon.post("/api/auth/register", json={
        "organization_name": "Another", "email": "ada@lantern.example", "name": "Ada",
        "password": TEST_PASSWORD})
    assert r.status_code == 422
    assert "already registered" in r.json()["detail"]


def test_organization_slugs_do_not_collide(anon):
    register(anon, org="Lantern Films", email="a@x.example")
    register(anon, org="Lantern Films", email="b@x.example")
    first = anon.post("/api/auth/login", json={"email": "a@x.example",
                                               "password": TEST_PASSWORD}).json()
    second = anon.post("/api/auth/login", json={"email": "b@x.example",
                                                "password": TEST_PASSWORD}).json()
    slugs = {
        anon.get("/api/org", headers={"Authorization": f"Bearer {t['access_token']}"}).json()["slug"]
        for t in (first, second)}
    assert slugs == {"lantern-films", "lantern-films-2"}


def test_weak_passwords_are_refused(anon):
    r = anon.post("/api/auth/register", json={
        "organization_name": "X", "email": "a@x.example", "name": "A", "password": "short"})
    assert r.status_code == 422


def test_login_says_the_same_thing_however_it_fails(anon):
    register(anon, email="ada@lantern.example")
    wrong_password = anon.post("/api/auth/login", json={"email": "ada@lantern.example",
                                                        "password": "not-the-password"})
    unknown_user = anon.post("/api/auth/login", json={"email": "nobody@lantern.example",
                                                      "password": TEST_PASSWORD})
    # Identical answers, so the endpoint cannot be used to find out who has an account.
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_a_disabled_account_cannot_sign_in(anon, client):
    client.post("/api/users", json={"email": "temp@test.example", "name": "Temp",
                                    "password": TEST_PASSWORD, "role": "member"})
    users = client.get("/api/users").json()
    temp = next(u for u in users if u["email"] == "temp@test.example")
    client.patch(f"/api/users/{temp['id']}", json={"is_active": False})

    r = anon.post("/api/auth/login", json={"email": "temp@test.example", "password": TEST_PASSWORD})
    assert r.status_code == 401


# ---------------------------------------------------------------- sessions

def test_unauthenticated_requests_are_refused(anon):
    assert anon.get("/api/projects").status_code == 401
    assert anon.get("/api/auth/me").status_code == 401
    r = anon.get("/api/projects", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_only_the_intended_routes_answer_without_a_session(anon):
    """The catalogue endpoints take no parameters, so it is easy for them to end up open.

    `pdf-status` in particular carries the native loader's error string.
    """
    assert anon.get("/api/outreach/templates").status_code == 401
    assert anon.get("/api/outreach/pdf-status").status_code == 401
    # These four are public by design: two are how you get a session, two are probes.
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/health/ready").status_code in (200, 503)
    assert anon.post("/api/auth/login", json={"email": "x@y.example",
                                              "password": "nope"}).status_code == 401


def test_the_token_is_not_recoverable_from_the_session_list(client):
    token = client.headers["Authorization"].split(" ", 1)[1]
    [session] = client.get("/api/auth/sessions").json()
    assert session["status"] == "active"
    assert session["token_hint"] == token[:8]
    assert token not in str(session)


def test_logging_out_ends_the_session_immediately(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/projects").status_code == 401


def test_revoking_a_session_from_the_list_ends_it(client):
    [session] = client.get("/api/auth/sessions").json()
    assert client.post(f"/api/auth/sessions/{session['id']}/revoke").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_changing_a_password_ends_every_session_but_not_the_caller(anon, client):
    """Every session goes, including this one — a fresh token comes back in its place.

    Carving out the current session would mean trusting that it is not the compromised one.
    """
    old_token = client.headers["Authorization"].split(" ", 1)[1]
    r = client.post("/api/auth/password", json={
        "current_password": TEST_PASSWORD,
        "new_password": "a-completely-different-passphrase"})
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    assert new_token != old_token

    # The old token is dead...
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    # ...and the caller is not signed out for their trouble.
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {new_token}"}).status_code == 200

    assert anon.post("/api/auth/login", json={
        "email": "owner@test.example",
        "password": "a-completely-different-passphrase"}).status_code == 200


def test_a_second_session_is_ended_by_a_password_change(anon, client):
    client.post("/api/users", json={"email": "other@test.example", "name": "Other",
                                    "password": TEST_PASSWORD, "role": "member"})
    first = anon.post("/api/auth/login", json={"email": "other@test.example",
                                               "password": TEST_PASSWORD}).json()["access_token"]
    second = anon.post("/api/auth/login", json={"email": "other@test.example",
                                                "password": TEST_PASSWORD}).json()["access_token"]

    changed = anon.post("/api/auth/password",
                        headers={"Authorization": f"Bearer {second}"},
                        json={"current_password": TEST_PASSWORD,
                              "new_password": "yet-another-good-passphrase"})
    assert changed.status_code == 200
    assert anon.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {first}"}).status_code == 401


def test_the_wrong_current_password_does_not_change_anything(client):
    r = client.post("/api/auth/password", json={"current_password": "wrong",
                                                "new_password": "another-good-passphrase"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 200


# ---------------------------------------------------------------- roles

@pytest.fixture
def viewer(accepted):
    """A read-only account in the same organization as `accepted`."""
    accepted.post("/api/users", json={"email": "viewer@test.example", "name": "Viewer",
                                      "password": TEST_PASSWORD, "role": "viewer"})
    token = accepted.post("/api/auth/login", json={"email": "viewer@test.example",
                                                   "password": TEST_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_viewer_can_read_but_not_write(accepted, viewer, project):
    assert accepted.get("/api/projects", headers=viewer).status_code == 200
    assert accepted.get(f"/api/projects/{project['id']}", headers=viewer).status_code == 200

    r = accepted.post("/api/projects", headers=viewer, json={
        "name": "Nope", "distribution_scope": "festival", "production_tier": "ultra_low"})
    assert r.status_code == 403
    assert "'member' role or higher" in r.json()["detail"]


def test_a_member_cannot_manage_users_or_the_directory(accepted):
    accepted.post("/api/users", json={"email": "member@test.example", "name": "Member",
                                      "password": TEST_PASSWORD, "role": "member"})
    token = accepted.post("/api/auth/login", json={"email": "member@test.example",
                                                   "password": TEST_PASSWORD}).json()["access_token"]
    member = {"Authorization": f"Bearer {token}"}

    assert accepted.post("/api/users", headers=member, json={
        "email": "x@test.example", "name": "X", "password": TEST_PASSWORD}).status_code == 403
    assert accepted.post("/api/rightsholders", headers=member, json={
        "id": "ent_nope", "name": "Nope", "kind": "studio"}).status_code == 403


def test_only_an_owner_can_create_or_change_another_owner(accepted):
    accepted.post("/api/users", json={"email": "admin@test.example", "name": "Admin",
                                      "password": TEST_PASSWORD, "role": "admin"})
    token = accepted.post("/api/auth/login", json={"email": "admin@test.example",
                                                   "password": TEST_PASSWORD}).json()["access_token"]
    admin = {"Authorization": f"Bearer {token}"}

    r = accepted.post("/api/users", headers=admin, json={
        "email": "owner2@test.example", "name": "Owner2", "password": TEST_PASSWORD,
        "role": "owner"})
    assert r.status_code == 403

    owner = next(u for u in accepted.get("/api/users").json() if u["role"] == "owner")
    assert accepted.patch(f"/api/users/{owner['id']}", headers=admin,
                          json={"role": "viewer"}).status_code == 403


def test_the_last_owner_cannot_be_demoted(accepted):
    owner = next(u for u in accepted.get("/api/users").json() if u["role"] == "owner")
    r = accepted.patch(f"/api/users/{owner['id']}", json={"role": "admin"})
    assert r.status_code == 409
    assert "last active owner" in r.json()["detail"]


def test_reducing_a_role_ends_that_users_sessions_at_once(accepted):
    """A downgrade has to bite now, not when a token happens to expire."""
    accepted.post("/api/users", json={"email": "demoted@test.example", "name": "D",
                                      "password": TEST_PASSWORD, "role": "member"})
    token = accepted.post("/api/auth/login", json={"email": "demoted@test.example",
                                                   "password": TEST_PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert accepted.get("/api/auth/me", headers=headers).status_code == 200

    target = next(u for u in accepted.get("/api/users").json() if u["email"] == "demoted@test.example")
    accepted.patch(f"/api/users/{target['id']}", json={"role": "viewer"})
    assert accepted.get("/api/auth/me", headers=headers).status_code == 401


# ---------------------------------------------------------------- tenancy

@pytest.fixture
def their_project(accepted, project):
    """A project, some assets and a packet belonging to the first organization."""
    [res] = ingest(accepted, project["id"], {"url": RICK, "usage_seconds": 45})
    tasks = tasks_by_layer(accepted, res["asset_id"])
    master = tasks["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [master["id"]]}).json()
    return {"project": project, "asset_id": res["asset_id"], "task_id": master["id"],
            "packet_id": packet["id"]}


def test_another_organization_sees_none_of_it(other_org, their_project):
    assert other_org.get("/api/projects").json() == []


@pytest.mark.parametrize("path", [
    "/api/projects/{project}",
    "/api/projects/{project}/assets",
    "/api/projects/{project}/tasks",
    "/api/projects/{project}/board",
    "/api/projects/{project}/budget",
    "/api/projects/{project}/ledger",
    "/api/projects/{project}/inbox",
    "/api/projects/{project}/packets",
    "/api/projects/{project}/packet-groups",
    "/api/projects/{project}/proposed-changes",
    "/api/projects/{project}/scripts",
    "/api/assets/{asset}",
    "/api/tasks/{task}",
    "/api/tasks/{task}/history",
    "/api/tasks/{task}/contacts",
    "/api/packets/{packet}",
    "/api/packets/{packet}/preview",
    "/api/packets/{packet}/thread",
])
def test_every_read_route_refuses_another_organizations_ids(other_org, their_project, path):
    """404, not 403: confirming an id is real but not yours is itself a disclosure."""
    url = path.format(project=their_project["project"]["id"], asset=their_project["asset_id"],
                      task=their_project["task_id"], packet=their_project["packet_id"])
    assert other_org.get(url).status_code == 404, url


@pytest.mark.parametrize("method,path,body", [
    ("patch", "/api/projects/{project}", {"name": "Mine now"}),
    ("delete", "/api/projects/{project}", None),
    ("patch", "/api/assets/{asset}", {"title": "Mine now"}),
    ("delete", "/api/assets/{asset}", None),
    ("patch", "/api/tasks/{task}", {"notes": "Mine now"}),
    ("post", "/api/tasks/{task}/transition", {"to": "dropped"}),
    ("post", "/api/tasks/{task}/estimate", None),
    ("patch", "/api/packets/{packet}", {"subject": "Mine now"}),
    ("delete", "/api/packets/{packet}", None),
    ("post", "/api/packets/{packet}/finalize", {}),
    ("post", "/api/packets/{packet}/context-views", {"recipient_name": "Someone"}),
])
def test_every_write_route_refuses_another_organizations_ids(other_org, their_project, method,
                                                             path, body):
    url = path.format(project=their_project["project"]["id"], asset=their_project["asset_id"],
                      task=their_project["task_id"], packet=their_project["packet_id"])
    kwargs = {"json": body} if body is not None else {}
    assert getattr(other_org, method)(url, **kwargs).status_code == 404, url


def test_a_packet_cannot_be_built_from_another_organizations_tasks(other_org, their_project):
    mine = other_org.post("/api/projects", json={
        "name": "Mine", "distribution_scope": "festival", "production_tier": "ultra_low"}).json()
    r = other_org.post(f"/api/projects/{mine['id']}/packets",
                       json={"task_ids": [their_project["task_id"]]})
    assert r.status_code == 422
    assert "Not in this project" in r.json()["detail"]


def test_the_audit_ledger_does_not_leak_across_organizations(other_org, accepted, their_project):
    mine = other_org.get("/api/audit", params={"limit": 500}).json()
    theirs = accepted.get("/api/audit", params={"limit": 500}).json()
    assert theirs, "the first organization has history"

    # Row ids are only unique within a table, so compare the pair.
    def keys(rows):
        return {(r["table_name"], r["row_id"]) for r in rows}

    assert keys(mine).isdisjoint(keys(theirs))
    # And nothing the first organization owns appears in the second one's ledger at all.
    owned = {their_project["project"]["id"], their_project["asset_id"],
             their_project["task_id"], their_project["packet_id"]}
    assert {r["row_id"] for r in mine}.isdisjoint(owned)


def test_background_work_is_attributed_to_the_right_tenant(accepted, project):
    """Jobs run in their own session; their audit rows must still belong to someone."""
    r = accepted.post(f"/api/projects/{project['id']}/ingest", json={
        "items": [{"url": RICK, "usage_seconds": 30}], "defer": True})
    assert r.status_code == 200
    rows = accepted.get("/api/audit", params={"table": "assets", "limit": 50}).json()
    assert rows, "the deferred ingest should be visible in this organization's ledger"


# ---------------------------------------------------------------- shared directory

def test_the_seeded_directory_is_shared_and_read_only(accepted, other_org):
    for client in (accepted, other_org):
        assert client.get("/api/rightsholders/ent_sony_music_entertainment").status_code == 200
    r = accepted.patch("/api/rightsholders/ent_sony_music_entertainment",
                       json={"licensing_email": "mine@example.com"})
    assert r.status_code == 409


def test_a_directory_entry_one_tenant_creates_is_invisible_to_another(accepted, other_org):
    created = accepted.post("/api/rightsholders", json={
        "id": "ent_private_label", "name": "Private Label", "kind": "label",
        "licensing_email": "private@test.example"})
    assert created.status_code == 201

    assert accepted.get("/api/rightsholders/ent_private_label").status_code == 200
    assert other_org.get("/api/rightsholders/ent_private_label").status_code == 404
    found = {r["id"] for r in other_org.get("/api/rightsholders",
                                            params={"q": "Private Label"}).json()}
    assert "ent_private_label" not in found


def test_users_are_only_visible_inside_their_own_organization(accepted, other_org):
    mine = {u["email"] for u in accepted.get("/api/users").json()}
    theirs = {u["email"] for u in other_org.get("/api/users").json()}
    assert mine.isdisjoint(theirs)


def test_a_project_always_carries_its_tenant(accepted, project, SessionTest):
    with SessionTest() as session:
        row = session.get(Project, project["id"])
        owner = session.query(User).filter_by(email="owner@test.example").one()
        assert row.org_id == owner.org_id


# ---------------------------------------------------- directory leakage through matching

def test_a_private_directory_entry_never_matches_another_tenants_asset(accepted, other_org):
    """Scoping the directory endpoint is not enough — the matcher reads the table directly.

    The rights matcher and the contact resolver both build their own index. If that index is
    unscoped, one tenant's private licensing address is disclosed to another tenant, can be
    auto-assigned to their task, and destroys the score margin their own match needed.
    """
    created = accepted.post("/api/rightsholders", json={
        "id": "ent_secret_label", "name": "Rick Astley", "kind": "label",
        "licensing_email": "deals@secret.example", "aliases": ["Rick Astley"]})
    assert created.status_code == 201

    [res] = ingest(other_org, other_org.post("/api/projects", json={
        "name": "Rival Doc", "distribution_scope": "festival",
        "production_tier": "ultra_low"}).json()["id"], {"url": RICK})
    tasks = tasks_by_layer(other_org, res["asset_id"])
    master = tasks["master_recording"]

    candidate_ids = {c["rightsholder_id"] for c in master["mapping_candidates"]}
    assert "ent_secret_label" not in candidate_ids
    assert (master["rightsholder"] or {}).get("id") != "ent_secret_label"

    resolution = other_org.get(f"/api/tasks/{master['id']}/contacts").json()
    contacts_seen = {o["rightsholder_id"] for o in resolution["options"]}
    assert "ent_secret_label" not in contacts_seen
    assert "deals@secret.example" not in str(resolution)


def test_a_private_child_is_hidden_from_another_tenants_view_of_a_shared_parent(accepted,
                                                                                other_org):
    """`children` comes from a relationship, which the query filter never touches."""
    accepted.post("/api/rightsholders", json={
        "id": "ent_secret_co", "name": "Secret Co", "kind": "studio",
        "parent_id": "ent_warner_bros_discovery"})

    mine = accepted.get("/api/rightsholders/ent_warner_bros_discovery").json()
    theirs = other_org.get("/api/rightsholders/ent_warner_bros_discovery").json()

    assert "ent_secret_co" in {c["id"] for c in mine["children"]}
    assert "ent_secret_co" not in {c["id"] for c in theirs["children"]}
    # The shared children are still there for both.
    assert "ent_warner_bros_pictures" in {c["id"] for c in theirs["children"]}
