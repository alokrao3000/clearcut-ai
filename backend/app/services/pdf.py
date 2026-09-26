"""HTML to PDF, with an honest answer when the renderer is unavailable.

WeasyPrint is a Python package wrapping native Pango/cairo libraries. `pip install` pulls
the wrapper but not the libraries, which is fine on most Linux images and routinely not
fine on a Windows dev box. Importing it therefore happens lazily and once, behind a probe:
the HTML letter is always available, and a missing native stack degrades to a 503 that
says what to install rather than a 500 stack trace from inside cffi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "PDF rendering needs WeasyPrint's native libraries (Pango, cairo, gdk-pixbuf). "
    "On Windows install the GTK3 runtime (https://github.com/tschoonj/GTK-for-Windows-Runtime-"
    "Environment-Installer/releases) and restart the API; on Debian/Ubuntu "
    "`apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev`; "
    "on macOS `brew install pango`. The HTML letter is available meanwhile."
)


class PdfUnavailable(RuntimeError):
    """Raised when the native rendering stack is missing. Carries an actionable message."""


@dataclass(frozen=True)
class Probe:
    available: bool
    version: str | None
    error: str | None


@lru_cache(maxsize=1)
def probe() -> Probe:
    """Import WeasyPrint once and remember whether it actually works.

    Cached because the failure is a missing shared library: it cannot resolve itself while
    the process is running, and retrying the import per request is slow and noisy in logs.
    """
    try:
        import weasyprint

        # Importing succeeds before the libraries are dlopen'd, so render something tiny.
        weasyprint.HTML(string="<p>probe</p>").write_pdf()
    except Exception as exc:  # noqa: BLE001 - cffi, OSError and weasyprint errors all land here
        log.warning("PDF rendering unavailable: %s", exc)
        return Probe(False, None, str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc))
    return Probe(True, getattr(weasyprint, "__version__", None), None)


def available() -> bool:
    return probe().available


def render(html: str, *, base_url: str | None = None) -> bytes:
    """Render a full HTML document to PDF bytes.

    `base_url` resolves relative URLs in the document. Pass the directory the templates
    live in when the letter references local assets.
    """
    state = probe()
    if not state.available:
        raise PdfUnavailable(f"{INSTALL_HINT} (underlying error: {state.error})")

    import weasyprint

    return weasyprint.HTML(string=html, base_url=base_url).write_pdf()
