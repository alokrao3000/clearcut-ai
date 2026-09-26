import os

os.environ.setdefault("CLEARCUT_DATABASE_URL", "sqlite://")
os.environ.setdefault("CLEARCUT_SEED_ON_STARTUP", "false")
# Every test registers an organization, and bcrypt at production cost would dominate the
# run. The cost lives inside each hash, so turning it down here changes nothing about how
# production hashes are stored or verified.
os.environ.setdefault("CLEARCUT_BCRYPT_ROUNDS", "4")
# Each test builds its own schema on its own engine, but the app still runs its startup
# check against the configured (throwaway, in-memory) one. Letting it migrate keeps that
# code path exercised; it happens once per process because the engine is module-level.
os.environ.setdefault("CLEARCUT_AUTO_MIGRATE", "true")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import db as db_module  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services.ingest import MetadataFetcher, PoliteClient, get_fetcher  # noqa: E402

YOUTUBE_OEMBED = {
    "dQw4w9WgXcQ": {"title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
                    "author_name": "Rick Astley", "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg"},
    "looney0001": {"title": "Duck Amuck | Classic Cartoon", "author_name": "Looney Tunes",
                   "thumbnail_url": "https://i.ytimg.com/vi/looney0001/hq.jpg"},
}


def fake_web(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.host == "www.youtube.com" and url.path == "/oembed":
        vid = url.params["url"].split("v=")[-1]
        if vid in YOUTUBE_OEMBED:
            return httpx.Response(200, json=YOUTUBE_OEMBED[vid])
        return httpx.Response(404)
    if url.host == "vimeo.com" and url.path == "/api/oembed.json":
        return httpx.Response(200, json={"title": "Aerial NYC", "author_name": "Jane Filmmaker",
                                         "duration": 95, "upload_date": "2019-04-02 10:00:00"})
    if url.host == "www.gettyimages.com":
        return httpx.Response(403, text="blocked")
    if url.host == "www.pond5.com":
        html = ('<html><head><meta property="og:title" content="Sunset over desert">'
                '<meta property="og:image" content="https://p5.example/t.jpg"></head></html>')
        return httpx.Response(200, text=html)
    return httpx.Response(404)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def SessionTest(engine):
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        seed(s)
    return maker


# A password that satisfies the strength floor without being interesting.
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def anon(SessionTest):
    """A client with no credentials at all, for checking that routes actually require them."""
    def _session():
        with SessionTest() as s:
            yield s

    settings = get_settings()
    fetcher = MetadataFetcher(PoliteClient(settings, transport=httpx.MockTransport(fake_web), sleep=lambda _: None),
                              settings)
    fetcher.http.limiter.min_interval = 0
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    # Inline jobs open their own session; point that at the test database too.
    original_factory = db_module.SessionLocal
    db_module.SessionLocal = SessionTest
    with TestClient(app) as c:
        yield c
    db_module.SessionLocal = original_factory
    app.dependency_overrides.clear()


def register(client, *, org="Test Productions", email="owner@test.example", name="Owner"):
    """Create an organization and sign its owner in. Returns the client, authenticated."""
    r = client.post("/api/auth/register", json={
        "organization_name": org, "email": email, "name": name, "password": TEST_PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def client(anon):
    """Signed in as an owner, but the disclaimer is not accepted yet.

    Matches the pre-M6 meaning of this fixture: reads work, writes return 428.
    """
    token = register(anon)["access_token"]
    anon.headers["Authorization"] = f"Bearer {token}"
    return anon


@pytest.fixture
def accepted(client):
    assert client.post("/api/disclaimer/accept").json()["accepted"] is True
    return client


@pytest.fixture
def other_org(anon, client):
    """A second, fully separate tenant, for proving the boundary holds.

    Built on the same `anon` client so both organizations share one database, then handed
    back as its own client object carrying the other token.
    """
    from fastapi.testclient import TestClient as _TC

    token = register(anon, org="Rival Pictures", email="rival@test.example",
                     name="Rival")["access_token"]
    other = _TC(app)
    other.headers["Authorization"] = f"Bearer {token}"
    other.post("/api/disclaimer/accept")
    return other


@pytest.fixture
def project(accepted):
    r = accepted.post("/api/projects", json={"name": "Diner", "distribution_scope": "festival",
                                             "production_tier": "ultra_low"})
    assert r.status_code == 201, r.text
    return r.json()


def ingest(client, project_id, *items):
    r = client.post(f"/api/projects/{project_id}/ingest", json={"items": list(items)})
    assert r.status_code == 200, r.text
    return r.json()


def tasks_by_layer(client, asset_id):
    return {t["layer"]: t for t in client.get(f"/api/assets/{asset_id}").json()["tasks"]}
