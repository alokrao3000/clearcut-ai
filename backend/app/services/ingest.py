"""URL ingestion: platform detection, sanctioned metadata fetches, normalization.

We only use official or public endpoints (oEmbed, YouTube Data API, archive.org metadata)
plus one identified OpenGraph fetch. If a site blocks us we do NOT evade it: the asset is
created from URL-derived fields and flagged `partial` for manual completion.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import Settings, get_settings
from app.enums import IngestStatus, Layer, Platform, SourceType


# ---------------------------------------------------------------- platform detection

@dataclass(frozen=True)
class DetectedSource:
    platform: Platform
    asset_id: str | None
    media_kind: str  # video | image | unknown


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def detect_platform(url: str) -> DetectedSource:
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        vid = None
        if host == "youtu.be":
            vid = path.strip("/").split("/")[0] or None
        elif path == "/watch":
            vid = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(?:shorts|embed|live|v)/([\w-]{6,})", path)
            vid = m.group(1) if m else None
        return DetectedSource(Platform.youtube, vid, "video")

    if host in {"vimeo.com", "player.vimeo.com"}:
        m = re.search(r"/(\d{5,})", path)
        return DetectedSource(Platform.vimeo, m.group(1) if m else None, "video")

    if host.endswith("gettyimages.com"):
        m = re.search(r"/(\d{5,})/?$", path)
        kind = "video" if "/video/" in path else "image" if "/photo/" in path or "/illustration/" in path else "unknown"
        return DetectedSource(Platform.getty, m.group(1) if m else None, kind)

    if host.endswith("shutterstock.com"):
        m = re.search(r"clip-(\d+)", path) or re.search(r"-(\d{5,})/?$", path)
        kind = "video" if "/video/" in path else "image" if "/image-" in path else "unknown"
        return DetectedSource(Platform.shutterstock, m.group(1) if m else None, kind)

    if host.endswith("pond5.com"):
        m = re.search(r"/item/(\d+)", path)
        kind = "image" if "/photo" in path or "/illustration" in path else "video"
        return DetectedSource(Platform.pond5, m.group(1) if m else None, kind)

    if host == "archive.org":
        m = re.match(r"^/details/([^/?#]+)", path)
        return DetectedSource(Platform.internet_archive, m.group(1) if m else None, "unknown")

    if host == "catalog.archives.gov":
        m = re.search(r"/id/(\d+)", path)
        return DetectedSource(Platform.nara, m.group(1) if m else None, "unknown")

    return DetectedSource(Platform.other, None, "unknown")


# Platforms that are themselves the licensor for everything they host.
AGENCY_OWNERS = {
    Platform.getty: "Getty Images",
    Platform.shutterstock: "Shutterstock",
    Platform.pond5: "Pond5",
    Platform.nara: "U.S. National Archives and Records Administration",
}


def default_layers(src: DetectedSource) -> list[Layer]:
    """Rights layers a fresh asset should be split into. Users can add or drop layers later."""
    if src.platform in {Platform.youtube, Platform.vimeo}:
        # Online video almost always carries a soundtrack: clear picture and both music rights separately.
        return [Layer.footage, Layer.master_recording, Layer.composition]
    if src.media_kind == "image":
        return [Layer.still_image]
    return [Layer.footage]


# ---------------------------------------------------------------- polite HTTP

class DomainRateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready_at = self._last.get(host, 0.0) + self.min_interval
            delay = max(0.0, ready_at - now)
            self._last[host] = now + delay
        if delay:
            time.sleep(delay)


class FetchBlocked(Exception):
    """The site refused us (403/401/451 or a challenge page). We stop rather than evade."""


class PoliteClient:
    RETRY_STATUSES = {429, 500, 502, 503, 504}
    BLOCK_STATUSES = {401, 403, 451}

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        self.settings = settings
        self.limiter = DomainRateLimiter(settings.per_domain_min_interval_seconds)
        self.sleep = sleep
        self.client = httpx.Client(
            headers={"User-Agent": settings.http_user_agent},
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        host = _host(url)
        last_exc: Exception | None = None
        for attempt in range(self.settings.http_max_attempts):
            self.limiter.wait(host)
            try:
                resp = self.client.get(url, params=params or None)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code in self.BLOCK_STATUSES:
                    raise FetchBlocked(f"{host} returned HTTP {resp.status_code}")
                if resp.status_code not in self.RETRY_STATUSES:
                    resp.raise_for_status()
                    return resp
                last_exc = httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    self.sleep(min(int(retry_after), 30))
                    continue
            self.sleep(min(2 ** attempt, 8))  # exponential backoff: 1s, 2s, 4s...
        raise last_exc or RuntimeError("request failed")


# ---------------------------------------------------------------- metadata fetchers

@dataclass
class Metadata:
    title: str | None = None
    owner_name: str | None = None
    description: str | None = None
    published_at: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    fetched_via: list[str] = field(default_factory=list)


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and data.strip() and not self.title:
            self.title = data.strip()


def parse_opengraph(html: str) -> Metadata:
    p = _MetaParser()
    p.feed(html)
    m = p.meta
    return Metadata(
        title=m.get("og:title") or m.get("twitter:title") or p.title,
        owner_name=m.get("author") or m.get("article:author") or m.get("og:site_name"),
        description=m.get("og:description") or m.get("description"),
        published_at=m.get("article:published_time") or m.get("uploaddate") or m.get("datepublished"),
        thumbnail_url=m.get("og:image") or m.get("twitter:image"),
        fetched_via=["opengraph"],
    )


_ISO_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_iso_duration(value: str) -> int | None:
    m = _ISO_DURATION.fullmatch(value or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _merge(base: Metadata, extra: Metadata) -> Metadata:
    for f in ("title", "owner_name", "description", "published_at", "thumbnail_url", "duration_seconds"):
        if getattr(base, f) is None and getattr(extra, f) is not None:
            setattr(base, f, getattr(extra, f))
    base.fetched_via += extra.fetched_via
    return base


class MetadataFetcher:
    def __init__(self, client: PoliteClient, settings: Settings):
        self.http = client
        self.settings = settings

    def fetch(self, url: str, src: DetectedSource) -> Metadata:
        handler = {
            Platform.youtube: self._youtube,
            Platform.vimeo: self._vimeo,
            Platform.internet_archive: self._archive,
        }.get(src.platform, self._opengraph)
        return handler(url, src)

    def _youtube(self, url: str, src: DetectedSource) -> Metadata:
        data = self.http.get("https://www.youtube.com/oembed", {"url": url, "format": "json"}).json()
        meta = Metadata(title=data.get("title"), owner_name=data.get("author_name"),
                        thumbnail_url=data.get("thumbnail_url"), fetched_via=["youtube_oembed"])
        if self.settings.youtube_api_key and src.asset_id:
            items = self.http.get("https://www.googleapis.com/youtube/v3/videos", {
                "id": src.asset_id, "part": "snippet,contentDetails", "key": self.settings.youtube_api_key}).json()
            if items.get("items"):
                item = items["items"][0]
                snip = item.get("snippet", {})
                meta.description = snip.get("description")
                meta.published_at = snip.get("publishedAt")
                meta.duration_seconds = parse_iso_duration(item.get("contentDetails", {}).get("duration", ""))
                meta.fetched_via.append("youtube_data_api")
        return meta

    def _vimeo(self, url: str, src: DetectedSource) -> Metadata:
        data = self.http.get("https://vimeo.com/api/oembed.json", {"url": url}).json()
        return Metadata(title=data.get("title"), owner_name=data.get("author_name"),
                        description=data.get("description"), published_at=data.get("upload_date"),
                        thumbnail_url=data.get("thumbnail_url"), duration_seconds=data.get("duration"),
                        fetched_via=["vimeo_oembed"])

    def _archive(self, url: str, src: DetectedSource) -> Metadata:
        if not src.asset_id:
            return self._opengraph(url, src)
        md = self.http.get(f"https://archive.org/metadata/{src.asset_id}").json().get("metadata", {})

        def first(v):
            return v[0] if isinstance(v, list) and v else v

        return Metadata(title=first(md.get("title")), owner_name=first(md.get("creator")),
                        description=first(md.get("description")), published_at=first(md.get("date")),
                        thumbnail_url=f"https://archive.org/services/img/{src.asset_id}",
                        fetched_via=["archive_metadata_api"])

    def _opengraph(self, url: str, src: DetectedSource) -> Metadata:
        return parse_opengraph(self.http.get(url).text)


# ---------------------------------------------------------------- normalization

_NOISE = re.compile(r"\s*[\(\[](official|lyric|music|hd|4k|remaster|audio|video)[^\)\]]*[\)\]]", re.I)


def infer_keywords(title: str | None, owner: str | None, published_at: str | None) -> list[str]:
    words: list[str] = []
    if title:
        clean = _NOISE.sub("", title).strip()
        # "Artist - Song" is the dominant convention for music uploads.
        words += [part.strip() for part in re.split(r"\s+[-–—|]\s+", clean) if part.strip()]
    if owner:
        words.append(owner.strip())
    if published_at and (m := re.match(r"(\d{4})", published_at)):
        words.append(m.group(1))
    seen, out = set(), []
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


@dataclass
class IngestResult:
    status: IngestStatus
    source: DetectedSource
    payload: dict
    error: str | None
    layers: list[Layer]


def ingest_url(url: str, notes: str | None, fetcher: MetadataFetcher) -> IngestResult:
    url = url.strip()
    src = detect_platform(url)
    meta = Metadata()
    status, error = IngestStatus.complete, None
    try:
        meta = fetcher.fetch(url, src)
    except FetchBlocked as exc:
        status, error = IngestStatus.partial, f"Metadata fetch refused ({exc}). Enter details manually."
    except (httpx.HTTPError, ValueError) as exc:
        status, error = IngestStatus.partial, f"Metadata fetch failed: {str(exc).splitlines()[0]}"

    if meta.owner_name is None and src.platform in AGENCY_OWNERS:
        meta.owner_name = AGENCY_OWNERS[src.platform]
    if not meta.title and status is IngestStatus.complete:
        status = IngestStatus.partial

    payload = {
        "source_type": SourceType.url_ingest.value,
        "raw_source": url,
        "platform": src.platform.value,
        "platform_asset_id": src.asset_id,
        "media_kind": src.media_kind,
        **{k: v for k, v in asdict(meta).items() if k != "fetched_via"},
        "inferred_keywords": infer_keywords(meta.title, meta.owner_name, meta.published_at),
        "user_timeline_notes": notes,
        "fetched_via": meta.fetched_via,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    return IngestResult(status, src, payload, error, default_layers(src))


_default_fetcher: MetadataFetcher | None = None


def get_fetcher() -> MetadataFetcher:
    global _default_fetcher
    if _default_fetcher is None:
        settings = get_settings()
        _default_fetcher = MetadataFetcher(PoliteClient(settings), settings)
    return _default_fetcher
