"""Script parsing, scene chunking and the extraction pipeline. No network, no API key."""

import io

import pytest

from app.config import Settings
from app.services import extract
from app.services.extract import BatchExtraction, Mention
from app.services.scripts import ScriptParseError, media_type_for, parse_script, split_scenes

SCREENPLAY = """FADE IN:

INT. DINER - NIGHT

A jukebox glows in the corner. SALLY, 30s, drops a coin.
The jukebox plays "Never Gonna Give You Up" by Rick Astley.

SALLY
Not this one again.

EXT. PARKING LOT - CONTINUOUS

Rain. A Coca-Cola sign buzzes overhead.

12  INT. SALLY'S CAR - LATER

She flips through a photo album.
"""


def fdx_bytes(*scenes: tuple[str, str]) -> bytes:
    body = "".join(
        f'<Paragraph Type="Scene Heading"><Text>{heading}</Text></Paragraph>'
        f'<Paragraph Type="Action"><Text>{action}</Text></Paragraph>'
        for heading, action in scenes
    )
    return f'<?xml version="1.0"?><FinalDraft><Content>{body}</Content></FinalDraft>'.encode()


def docx_bytes(text: str) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- chunking

def test_split_scenes_finds_each_slugline():
    scenes = split_scenes([SCREENPLAY])
    assert [s.heading for s in scenes] == [
        "INT. DINER - NIGHT",
        "EXT. PARKING LOT - CONTINUOUS",
        "12 INT. SALLY'S CAR - LATER",
    ]
    assert "jukebox" in scenes[0].text
    assert "FADE IN" not in scenes[0].text  # preamble is not swept into scene one


def test_split_scenes_records_the_page_a_scene_starts_on():
    scenes = split_scenes(["INT. A - DAY\nfirst", "EXT. B - NIGHT\nsecond"])
    assert [(s.heading, s.page_number) for s in scenes] == [("INT. A - DAY", 1), ("EXT. B - NIGHT", 2)]


def test_text_without_sluglines_becomes_one_scene():
    scenes = split_scenes(["A treatment with no headings at all.\nJust prose."])
    assert len(scenes) == 1
    assert scenes[0].heading == "(no scene headings)"
    assert "treatment" in scenes[0].text


def test_slugline_variants():
    scenes = split_scenes(["I/E. TRUCK - DAY\na\nEST. CITY - DAWN\nb\nINT./EXT. BOAT - DUSK\nc"])
    assert len(scenes) == 3


# ---------------------------------------------------------------- formats

def test_media_type_for():
    assert media_type_for("script.PDF") == "pdf"
    assert media_type_for("script.fdx") == "fdx"
    with pytest.raises(ScriptParseError):
        media_type_for("notes.txt")


def test_parse_fdx_uses_the_declared_structure():
    data = fdx_bytes(("INT. DINER - NIGHT", "A jukebox glows."), ("EXT. STREET - DAY", "Rain."))
    parsed = parse_script(data, "movie.fdx")
    assert parsed.media_type == "fdx"
    assert [s.heading for s in parsed.scenes] == ["INT. DINER - NIGHT", "EXT. STREET - DAY"]
    assert parsed.scenes[0].text == "A jukebox glows."


def test_parse_docx():
    parsed = parse_script(docx_bytes(SCREENPLAY), "movie.docx")
    assert parsed.media_type == "docx"
    assert len(parsed.scenes) == 3


def test_empty_upload_is_rejected():
    with pytest.raises(ScriptParseError):
        parse_script(b"", "movie.pdf")


def test_unreadable_pdf_is_rejected():
    with pytest.raises(ScriptParseError):
        parse_script(b"not a pdf at all", "movie.pdf")


# ---------------------------------------------------------------- extraction

class StubClient:
    """Stands in for anthropic.Anthropic; records calls and replays canned parses."""

    def __init__(self, batches):
        self._batches = list(batches)
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = self._batches.pop(0) if self._batches else BatchExtraction(mentions=[])
        return type("Response", (), {"parsed_output": payload, "stop_reason": "end_turn"})()


def settings_for(**overrides) -> Settings:
    return Settings(anthropic_api_key="test-key", **overrides)


def test_extraction_maps_mentions_back_to_scenes():
    scenes = split_scenes([SCREENPLAY])
    client = StubClient([BatchExtraction(mentions=[
        Mention(scene_index=0, title="Never Gonna Give You Up", owner_name="Rick Astley", kind="music",
                quote='The jukebox plays "Never Gonna Give You Up" by Rick Astley.',
                suggested_layers=["master_recording", "composition"], confidence=0.95,
                reasoning="A named recording plays on screen."),
        Mention(scene_index=1, title="Coca-Cola", owner_name=None, kind="trademark",
                quote="A Coca-Cola sign buzzes overhead.", suggested_layers=["trademark"],
                confidence=0.8, reasoning="Brand signage is visible."),
    ])])

    result = extract.extract_mentions(scenes, settings_for(), client=client)

    assert [m.title for m in result.mentions] == ["Never Gonna Give You Up", "Coca-Cola"]
    assert result.mentions[0].suggested_layers == ["master_recording", "composition"]
    assert result.scenes_read == 3
    # The prompt carries the scene index the model must echo back.
    assert '<scene index="0">' in client.calls[0]["messages"][0]["content"]
    assert client.calls[0]["model"] == "claude-opus-5"


def test_mentions_for_unknown_scenes_are_dropped():
    scenes = split_scenes([SCREENPLAY])
    client = StubClient([BatchExtraction(mentions=[
        Mention(scene_index=99, title="Ghost", kind="music", quote="q", suggested_layers=["composition"],
                confidence=0.9, reasoning="hallucinated scene"),
    ])])
    assert extract.extract_mentions(scenes, settings_for(), client=client).mentions == []


def test_unknown_layers_are_filtered_out():
    scenes = split_scenes([SCREENPLAY])
    client = StubClient([BatchExtraction(mentions=[
        Mention(scene_index=0, title="Something", kind="footage", quote="q",
                suggested_layers=["sync_rights", "footage"], confidence=0.7, reasoning="r"),
    ])])
    mention = extract.extract_mentions(scenes, settings_for(), client=client).mentions[0]
    assert mention.suggested_layers == ["footage"]


def test_long_scenes_are_split_not_truncated():
    scenes = split_scenes(["INT. LONG - DAY\n" + ("word " * 5000)])
    batches = extract.build_batches(scenes, settings_for(extraction_max_scene_chars=1000))
    pieces = [piece for batch in batches for piece in batch]
    assert len(pieces) > 1
    assert sum(len(text) for _, _, text in pieces) == len(scenes[0].text)
    assert {index for index, _, _ in pieces} == {0}


def test_batches_respect_the_per_call_scene_limit():
    scenes = split_scenes(["\n".join(f"INT. ROOM {i} - DAY\naction {i}" for i in range(10))])
    batches = extract.build_batches(scenes, settings_for(extraction_max_scenes_per_call=3))
    assert [len(batch) for batch in batches] == [3, 3, 3, 1]


def test_extraction_without_credentials_is_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(extract, "_client", lambda _s: (_ for _ in ()).throw(
        extract.ExtractionUnavailable("no key")))
    with pytest.raises(extract.ExtractionUnavailable):
        extract.extract_mentions(split_scenes([SCREENPLAY]), Settings())


def test_missing_credentials_surface_as_unavailable(monkeypatch):
    """The SDK raises TypeError when it cannot resolve any credential; that is config, not failure."""
    import anthropic

    def refuse(*args, **kwargs):
        raise TypeError("Could not resolve authentication method.")

    monkeypatch.setattr(anthropic, "Anthropic", refuse)
    with pytest.raises(extract.ExtractionUnavailable, match="No Claude credentials"):
        extract._client(Settings())


class AuthlessClient:
    """The SDK resolves credentials lazily, so the failure lands on the request, not the client."""

    def __init__(self):
        self.messages = self

    def parse(self, **kwargs):
        raise TypeError("Could not resolve authentication method. Expected one of api_key, ...")


class BrokenClient:
    def __init__(self):
        self.messages = self

    def parse(self, **kwargs):
        raise TypeError("parse() got an unexpected keyword argument 'nonsense'")


def test_request_time_auth_failure_is_unavailable_not_a_crash():
    scenes = split_scenes([SCREENPLAY])
    with pytest.raises(extract.ExtractionUnavailable, match="No Claude credentials"):
        extract.extract_mentions(scenes, settings_for(), client=AuthlessClient())


def test_an_unrelated_typeerror_still_propagates():
    scenes = split_scenes([SCREENPLAY])
    with pytest.raises(TypeError, match="unexpected keyword"):
        extract.extract_mentions(scenes, settings_for(), client=BrokenClient())
