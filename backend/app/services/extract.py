"""Claude-backed extraction of clearable assets from script scenes.

The model is asked for one thing only: what in this scene would need clearing, and the
exact line that says so. It never assigns rightsholders, prices anything, or moves a task
— the existing matcher and budget matrix keep doing that, so an LLM mistake stays visible
and correctable instead of silently becoming a number in a budget.

Output is constrained with structured outputs (`messages.parse`), so a malformed answer is
a validation error rather than something we have to parse defensively.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.config import Settings
from app.enums import Layer
from app.services.scripts import ParsedScene

log = logging.getLogger(__name__)

MENTION_KINDS = ("music", "footage", "still", "artwork", "trademark", "other")

# What the model may suggest, and what each suggestion means downstream.
LAYER_VALUES = tuple(layer.value for layer in Layer)

SYSTEM_PROMPT = """You read film scripts for a rights clearance team.

Find every element in the scene text that would need third-party clearance before it could
appear in a film: recorded music, needle drops, on-screen TV or film clips, archival footage,
photographs, posters, artwork, book covers, branded products, logos and signage.

Rules:
- Only report things actually present in the text. Never infer a song or brand that is not written.
- `quote` must be copied verbatim from the scene, as the shortest span that shows the element.
- If a scene needs nothing cleared, return an empty list for it. Most scenes need nothing.
- Generic set dressing ("a television plays in the corner", "a framed photo") is only a mention
  when the text identifies a specific work, brand or performer.
- confidence: 0.9+ named and unambiguous, 0.6-0.9 named but vague about what is used,
  below 0.6 a judgement call.

Layer meanings, for `suggested_layers`:
- master_recording: the specific recording of a song
- composition: the underlying song, needed whenever a recording is used or performed
- footage: moving images someone else shot
- still_image: a photograph or single frame
- performance: an identifiable person's likeness or performance
- trademark: a brand, logo or product identity

A song playing on screen needs both master_recording and composition. A character singing
unaccompanied needs composition only."""


MISSING_CREDENTIALS = (
    "No Claude credentials found. Set CLEARCUT_ANTHROPIC_API_KEY, or ANTHROPIC_API_KEY, "
    "or sign in with `ant auth login`."
)


class ExtractionUnavailable(RuntimeError):
    """No API key configured, or the SDK is not installed. Parsing still succeeded."""


class Mention(BaseModel):
    """One clearable element the model found."""

    scene_index: int = Field(description="Index of the scene this was found in, as labelled in the input")
    title: str = Field(description="The work, brand or performer, as named in the script")
    owner_name: str | None = Field(default=None, description="Artist, studio or brand owner, if the text names one")
    kind: str = Field(description=f"One of: {', '.join(MENTION_KINDS)}")
    quote: str = Field(description="The exact span of scene text showing this element")
    suggested_layers: list[str] = Field(description=f"Any of: {', '.join(LAYER_VALUES)}")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One sentence on why this needs clearing")


class BatchExtraction(BaseModel):
    mentions: list[Mention]


@dataclass
class ExtractionResult:
    mentions: list[Mention]
    model: str
    scenes_read: int


def _client(settings: Settings):
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ExtractionUnavailable("The anthropic SDK is not installed.") from exc

    # An unset key is not the same as no credentials: the SDK also resolves
    # ANTHROPIC_AUTH_TOKEN and `ant auth login` profiles on its own. It raises
    # TypeError when it can resolve none of them — that is a missing configuration,
    # not a job failure, so the script stays usable without the LLM pass.
    try:
        if settings.anthropic_api_key:
            return anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return anthropic.Anthropic()
    except TypeError as exc:
        raise ExtractionUnavailable(MISSING_CREDENTIALS) from exc


def _split_oversized(scene: ParsedScene, limit: int) -> list[tuple[int, str, str]]:
    """Long scenes are sent in parts rather than truncated — no text is dropped."""
    if len(scene.text) <= limit:
        return [(scene.index, scene.heading, scene.text)]

    parts: list[tuple[int, str, str]] = []
    remaining = scene.text
    part = 1
    while remaining:
        head, remaining = remaining[:limit], remaining[limit:]
        parts.append((scene.index, f"{scene.heading} (part {part})", head))
        part += 1
    return parts


def build_batches(scenes: list[ParsedScene], settings: Settings) -> list[list[tuple[int, str, str]]]:
    pieces: list[tuple[int, str, str]] = []
    for scene in scenes:
        if scene.text.strip():
            pieces.extend(_split_oversized(scene, settings.extraction_max_scene_chars))

    size = max(1, settings.extraction_max_scenes_per_call)
    return [pieces[i:i + size] for i in range(0, len(pieces), size)]


def _render(batch: list[tuple[int, str, str]]) -> str:
    blocks = [
        f"<scene index=\"{index}\">\n{heading}\n\n{text}\n</scene>"
        for index, heading, text in batch
    ]
    return "Scenes:\n\n" + "\n\n".join(blocks)


def _valid(mention: Mention, known_indexes: set[int]) -> bool:
    if mention.scene_index not in known_indexes:
        log.warning("Dropping mention for unknown scene index %s", mention.scene_index)
        return False
    if not mention.quote.strip() or not mention.title.strip():
        return False
    return True


def _normalise(mention: Mention) -> Mention:
    layers = [layer for layer in mention.suggested_layers if layer in LAYER_VALUES]
    if not layers:
        # A mention with no usable layer would create an asset with nothing to clear.
        layers = ["footage"] if mention.kind == "footage" else ["trademark"] if mention.kind == "trademark" else []
    kind = mention.kind if mention.kind in MENTION_KINDS else "other"
    return mention.model_copy(update={"suggested_layers": layers, "kind": kind})


def extract_mentions(scenes: list[ParsedScene], settings: Settings, client=None) -> ExtractionResult:
    """Read every scene and return the clearable elements found. Network call per batch."""
    import anthropic

    client = client or _client(settings)
    batches = build_batches(scenes, settings)
    known = {scene.index for scene in scenes}
    found: list[Mention] = []

    for batch in batches:
        try:
            response = client.messages.parse(
                model=settings.extraction_model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _render(batch)}],
                output_format=BatchExtraction,
            )
        except TypeError as exc:
            # The SDK resolves credentials lazily, at request time, and raises a bare
            # TypeError when it finds none. Anything else is a real bug, so re-raise it.
            if "authentication" not in str(exc).lower():
                raise
            raise ExtractionUnavailable(MISSING_CREDENTIALS) from exc
        except anthropic.NotFoundError as exc:
            raise ExtractionUnavailable(f"Model '{settings.extraction_model}' is not available: {exc}") from exc
        except anthropic.RateLimitError:
            raise
        except anthropic.APIStatusError as exc:
            log.warning("Extraction batch failed (%s); continuing with the rest", exc)
            continue
        except anthropic.APIConnectionError as exc:
            raise ExtractionUnavailable(f"Could not reach the Claude API: {exc}") from exc

        if response.stop_reason == "refusal":
            log.warning("Extraction batch refused: %s", getattr(response, "stop_details", None))
            continue

        parsed = response.parsed_output
        if parsed is None:
            continue
        found.extend(_normalise(m) for m in parsed.mentions if _valid(m, known))

    return ExtractionResult(mentions=found, model=settings.extraction_model, scenes_read=len(scenes))
