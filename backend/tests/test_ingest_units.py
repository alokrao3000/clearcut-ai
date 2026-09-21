import pytest

from app.enums import Layer, Platform
from app.services.ingest import default_layers, detect_platform, infer_keywords, parse_iso_duration, parse_opengraph
from app.services.mapping import normalize


@pytest.mark.parametrize("url,platform,asset_id,kind", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", Platform.youtube, "dQw4w9WgXcQ", "video"),
    ("https://youtu.be/dQw4w9WgXcQ", Platform.youtube, "dQw4w9WgXcQ", "video"),
    ("https://youtube.com/shorts/abcDEF12345", Platform.youtube, "abcDEF12345", "video"),
    ("https://vimeo.com/76979871", Platform.vimeo, "76979871", "video"),
    ("https://www.gettyimages.com/detail/video/times-square-stock-footage/1234567", Platform.getty, "1234567", "video"),
    ("https://www.gettyimages.com/detail/photo/moon-landing-high-res-stock-photo/515170", Platform.getty, "515170",
     "image"),
    ("https://www.shutterstock.com/video/clip-1012345-aerial-city", Platform.shutterstock, "1012345", "video"),
    ("https://www.shutterstock.com/image-photo/red-apple-white-background-99887766", Platform.shutterstock,
     "99887766", "image"),
    ("https://www.pond5.com/stock-footage/item/12345678-sunset-desert", Platform.pond5, "12345678", "video"),
    ("https://archive.org/details/Duck_and_Cover_1951", Platform.internet_archive, "Duck_and_Cover_1951", "unknown"),
    ("https://catalog.archives.gov/id/2569", Platform.nara, "2569", "unknown"),
    ("https://example.com/thing", Platform.other, None, "unknown"),
])
def test_detect_platform(url, platform, asset_id, kind):
    src = detect_platform(url)
    assert (src.platform, src.asset_id, src.media_kind) == (platform, asset_id, kind)


def test_default_layers_split_online_video_into_picture_and_music_rights():
    assert default_layers(detect_platform("https://youtu.be/x123456")) == [
        Layer.footage, Layer.master_recording, Layer.composition]
    assert default_layers(detect_platform("https://www.gettyimages.com/detail/photo/x/515170")) == [Layer.still_image]


def test_infer_keywords_strips_noise_and_splits_artist_title():
    kws = infer_keywords("Rick Astley - Never Gonna Give You Up (Official Music Video)", "Rick Astley",
                         "1987-07-27")
    assert kws == ["Rick Astley", "Never Gonna Give You Up", "1987"]


def test_parse_iso_duration():
    assert parse_iso_duration("PT3M33S") == 213
    assert parse_iso_duration("PT1H") == 3600
    assert parse_iso_duration("garbage") is None


def test_parse_opengraph():
    meta = parse_opengraph('<meta property="og:title" content="X"><meta name="author" content="Y"><title>Z</title>')
    assert (meta.title, meta.owner_name) == ("X", "Y")


def test_normalize_channel_handles():
    assert normalize("RickAstleyVEVO") == "rick astley"
    assert normalize("Warner Bros. Pictures") == "warner bros pictures"
