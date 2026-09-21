"""Screenplay parsing: .pdf / .docx / .fdx -> pages -> scenes.

Scene chunking is deliberately boring and inspectable. Screenplays are a rigid format:
a scene starts at a slugline (INT./EXT./EST./I/E) and runs to the next one. Final Draft
files carry the structure explicitly, so .fdx never has to be guessed at.

Nothing here touches the network or an LLM — extraction is a separate, optional step.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SUPPORTED_MEDIA_TYPES = {"pdf", "docx", "fdx"}

EXTENSION_MEDIA_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".fdx": "fdx",
}

# INT. / EXT. / INT./EXT. / I/E / EST., optionally numbered ("12  INT. DINER - NIGHT").
_SLUGLINE = re.compile(
    r"^\s*(?:[0-9]{1,4}[A-Z]?[.)]?\s+)?"          # optional scene number
    r"(INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?|EST\.?)"
    r"(?=\s|$)",
    re.IGNORECASE,
)
_PAGE_BREAK = re.compile(r"\f")
_WHITESPACE_RUN = re.compile(r"[ \t]+")


class ScriptParseError(ValueError):
    """The upload could not be read as the media type it claims to be."""


@dataclass
class ParsedScene:
    index: int
    heading: str
    page_number: int | None
    text: str


@dataclass
class ParsedScript:
    media_type: str
    page_count: int | None
    scenes: list[ParsedScene] = field(default_factory=list)


def media_type_for(filename: str) -> str:
    for extension, media_type in EXTENSION_MEDIA_TYPE.items():
        if filename.lower().endswith(extension):
            return media_type
    raise ScriptParseError(
        f"Unsupported file type '{filename}'. Upload a .pdf, .docx or .fdx screenplay."
    )


# ---------------------------------------------------------------- text extraction

def _pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        return [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise ScriptParseError(f"Could not read the PDF: {exc}") from exc


def _docx_pages(data: bytes) -> list[str]:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError) as exc:
        raise ScriptParseError(f"Could not read the .docx: {exc}") from exc

    # A .docx has no fixed pages; treat explicit page breaks as boundaries and fall
    # back to one long page when the writer never inserted any.
    pages: list[list[str]] = [[]]
    for paragraph in document.paragraphs:
        if _PAGE_BREAK.search(paragraph.text) or _has_page_break(paragraph):
            pages.append([])
        pages[-1].append(paragraph.text)
    return ["\n".join(lines) for lines in pages if any(line.strip() for line in lines)]


def _has_page_break(paragraph) -> bool:
    # w:br/@w:type="page" is how Word marks a hard page break.
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return any(br.get(f"{ns}type") == "page" for br in paragraph._element.iter(f"{ns}br"))


def _fdx_scenes(data: bytes) -> list[ParsedScene]:
    """Final Draft XML already labels every paragraph, so structure is read, not inferred."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ScriptParseError(f"Could not read the .fdx: {exc}") from exc

    scenes: list[ParsedScene] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_heading is None:
            return
        scenes.append(
            ParsedScene(
                index=len(scenes),
                heading=current_heading,
                page_number=None,
                text=_clean("\n".join(current_lines)),
            )
        )

    for paragraph in root.iter("Paragraph"):
        text = "".join(node.text or "" for node in paragraph.iter("Text")).strip()
        if not text:
            continue
        if paragraph.get("Type") == "Scene Heading":
            flush()
            current_heading, current_lines = text, []
        else:
            current_lines.append(text)

    flush()
    if not scenes:
        raise ScriptParseError("No scene headings found in the .fdx.")
    return scenes


# ---------------------------------------------------------------- scene chunking

def _clean(text: str) -> str:
    lines = [_WHITESPACE_RUN.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def split_scenes(pages: list[str]) -> list[ParsedScene]:
    """Split page text into scenes at sluglines, remembering which page each began on."""
    scenes: list[ParsedScene] = []
    heading: str | None = None
    page_number: int | None = None
    buffer: list[str] = []
    preamble: list[str] = []

    def flush() -> None:
        nonlocal heading, buffer
        if heading is None:
            return
        scenes.append(
            ParsedScene(index=len(scenes), heading=heading, page_number=page_number,
                        text=_clean("\n".join(buffer)))
        )
        buffer = []

    for page_index, page in enumerate(pages, start=1):
        for line in page.splitlines():
            if _SLUGLINE.match(line) and line.strip():
                flush()
                heading = _WHITESPACE_RUN.sub(" ", line).strip()
                page_number = page_index
            elif heading is None:
                preamble.append(line)
            else:
                buffer.append(line)
    flush()

    if not scenes:
        # Treatments and outlines have no sluglines; keep the text as a single scene
        # rather than dropping the upload on the floor.
        body = _clean("\n".join(preamble))
        if body:
            scenes.append(ParsedScene(index=0, heading="(no scene headings)", page_number=1, text=body))
    return scenes


def parse_script(data: bytes, filename: str) -> ParsedScript:
    media_type = media_type_for(filename)
    if not data:
        raise ScriptParseError("The uploaded file is empty.")

    if media_type == "fdx":
        scenes = _fdx_scenes(data)
        return ParsedScript(media_type=media_type, page_count=None, scenes=scenes)

    pages = _pdf_pages(data) if media_type == "pdf" else _docx_pages(data)
    if not any(page.strip() for page in pages):
        raise ScriptParseError(
            "No text could be extracted. A scanned screenplay needs OCR before it can be read."
        )
    return ParsedScript(media_type=media_type, page_count=len(pages), scenes=split_scenes(pages))
