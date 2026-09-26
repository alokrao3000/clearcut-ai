"""Recipient-specific watermarking for shared context.

Two jobs, one string:

* **Web and PDF pages** get the watermark as a tiled SVG background. It is decorative, so
  it is defeatable by anyone who opens devtools — its purpose is deterrence and, if a
  screenshot circulates, attribution.
* **Script excerpts** get it burned into a raster image. Excerpts are the only part of a
  screenplay that ever leaves the system, and shipping them as pixels rather than text
  means a leaked excerpt carries the recipient's name with it and cannot be silently
  copy-pasted into a larger document.

Neither is DRM and neither is claimed to be. They make casual redistribution traceable.
"""

from __future__ import annotations

import io
import textwrap
from functools import lru_cache
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

TILE_WIDTH = 420
TILE_HEIGHT = 240
ANGLE = -30

# Screenplay excerpts read as screenplays, so a monospace face if the host has one.
MONO_CANDIDATES = [
    "C:/Windows/Fonts/cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


# Mid-grey, not ink. The same tile has to stay visible on a white letter and on the dark
# theme of the context page, and a watermark nobody can see attributes nothing.
TILE_FILL = "#8a8a8a"


@lru_cache(maxsize=8)
def tile_data_uri(text: str, *, opacity: float = 0.22, size: int = 15) -> str:
    """A repeating SVG tile as a CSS `url(...)` value.

    Inlined as a data URI rather than served as a file: the page must render identically
    in a browser, in WeasyPrint, and when saved to disk, none of which can be relied on to
    fetch a second request with the right token.
    """
    safe = _xml_escape(text)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TILE_WIDTH}" height="{TILE_HEIGHT}">'
        f'<text x="{TILE_WIDTH // 2}" y="{TILE_HEIGHT // 2}" fill="{TILE_FILL}" '
        f'fill-opacity="{opacity}" font-family="Helvetica, Arial, sans-serif" font-size="{size}" '
        f'text-anchor="middle" '
        f'transform="rotate({ANGLE} {TILE_WIDTH // 2} {TILE_HEIGHT // 2})">{safe}</text>'
        "</svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg, safe='')}"


@lru_cache(maxsize=4)
def _font(path_size: tuple[str | None, int]):
    path, size = path_size
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1: bitmap default, fixed size
        return ImageFont.load_default()


def _mono(size: int):
    import os

    for candidate in MONO_CANDIDATES:
        if os.path.exists(candidate):
            return _font((candidate, size))
    return _font((None, size))


def excerpt_png(text: str, watermark: str, *, label: str | None = None, width: int = 820,
                scale: int = 2) -> bytes:
    """Rasterize a script excerpt with the recipient's watermark tiled across it.

    Rendered at `scale`x and downsampled so the text stays sharp on high-density displays
    without shipping a font stack to the browser.
    """
    pad, line_height, font_size = 28 * scale, 22 * scale, 14 * scale
    body_font, label_font = _mono(font_size), _mono(int(font_size * 0.8))
    canvas_width = width * scale

    # Wrap on the real glyph width rather than a guess; excerpts are monospace but the
    # fallback face may not be.
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    char_width = max(probe.textlength("M", font=body_font), 1)
    columns = max(int((canvas_width - 2 * pad) / char_width), 20)

    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=columns) or [""])

    header = (label or "").strip()
    height = pad * 2 + line_height * len(lines) + (line_height + 8 * scale if header else 0)

    image = Image.new("RGB", (canvas_width, max(height, 80 * scale)), "#fbfbf9")
    draw = ImageDraw.Draw(image)

    y = pad
    if header:
        draw.text((pad, y), header, font=label_font, fill="#8a8578")
        y += line_height + 8 * scale
    for line in lines:
        draw.text((pad, y), line, font=body_font, fill="#1a1a1a")
        y += line_height

    image = Image.alpha_composite(image.convert("RGBA"), _watermark_layer(image.size, watermark, scale))
    image = image.convert("RGB").resize((width, image.height // scale), Image.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _watermark_layer(size: tuple[int, int], text: str, scale: int) -> Image.Image:
    """A transparent layer of tiled, rotated watermark text sized to cover `size`.

    Drawn on an oversized square and rotated, so the rotation leaves no bare corners.
    """
    width, height = size
    diagonal = int((width**2 + height**2) ** 0.5) + 2
    layer = Image.new("RGBA", (diagonal, diagonal), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font((None, 13 * scale))

    step_x, step_y = TILE_WIDTH * scale, (TILE_HEIGHT // 2) * scale
    for row, y in enumerate(range(0, diagonal, step_y)):
        offset = (step_x // 2) if row % 2 else 0  # brick-lay the tiles
        for x in range(-step_x, diagonal, step_x):
            draw.text((x + offset, y), text, font=font, fill=(26, 26, 26, 30))

    layer = layer.rotate(ANGLE, resample=Image.BICUBIC)
    left, top = (diagonal - width) // 2, (diagonal - height) // 2
    return layer.crop((left, top, left + width, top + height))
