import os

os.environ.setdefault("CLEARCUT_DATABASE_URL", "sqlite://")
os.environ.setdefault("CLEARCUT_SEED_ON_STARTUP", "false")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

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


@pytest.fixture
def client(SessionTest):
    def _session():
        with SessionTest() as s:
            yield s

    settings = get_settings()
    fetcher = MetadataFetcher(PoliteClient(settings, transport=httpx.MockTransport(fake_web), sleep=lambda _: None),
                              settings)
    fetcher.http.limiter.min_interval = 0
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def accepted(client):
    assert client.post("/api/disclaimer/accept").json()["accepted"] is True
    return client


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
