"""Render text as SVG <path> elements via a TTF font.

The homeboard renders SVG with nanosvg, which silently drops <text>. To get
labels/temperatures into the overlay we trace each glyph from a TTF font and
emit absolute-coordinate <path> commands inside a transformed <g>.
"""

import os
from functools import lru_cache
from xml.etree import ElementTree as ET

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

from zzmw_lib.logs import build_logger

log = build_logger("TextToPath")

_SVG_NS = "http://www.w3.org/2000/svg"

_FONT_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
}


def _find_font(weight):
    for p in _FONT_CANDIDATES.get(weight, []):
        if os.path.exists(p):
            return p
    if weight != "regular":
        return _find_font("regular")
    raise FileNotFoundError(
        "No DejaVuSans TTF found in the usual locations. "
        "Install fonts-dejavu (Debian/Ubuntu) or extend _FONT_CANDIDATES."
    )


@lru_cache(maxsize=4)
def _load_font(weight):
    path = _find_font(weight)
    font = TTFont(path)
    return (
        font,
        font.getBestCmap(),
        font.getGlyphSet(),
        font["head"].unitsPerEm,
    )


def measure_text(text, font_size, weight="regular"):
    """Return the rendered width (px) of `text` without emitting any SVG."""
    font, cmap, _glyph_set, upem = _load_font(weight)
    scale = font_size / upem
    cum = 0
    for ch in text:
        glyph_name = cmap.get(ord(ch)) or cmap.get(ord("?"))
        if glyph_name is None:
            continue
        advance, _lsb = font["hmtx"][glyph_name]
        cum += advance
    return cum * scale


def render_text(parent, text, x, y, font_size, fill="#000", weight="regular"):
    """Append a <g> of glyph <path>s to `parent`.

    (x, y) is the baseline-left position in SVG (px). Returns the rendered
    width in px so callers can measure / right-align if needed.
    """
    font, cmap, glyph_set, upem = _load_font(weight)
    scale = font_size / upem

    # Glyph outlines are y-up in font units; flip y on the group.
    g = ET.SubElement(parent, f"{{{_SVG_NS}}}g", {
        "transform": (f"translate({x:.3f},{y:.3f}) "
                      f"scale({scale:.6f},{-scale:.6f})"),
        "fill": fill,
    })

    cum = 0  # cumulative advance in font units
    for ch in text:
        glyph_name = cmap.get(ord(ch)) or cmap.get(ord("?"))
        if glyph_name is None:
            continue
        glyph = glyph_set[glyph_name]
        pen = SVGPathPen(glyph_set)
        glyph.draw(pen)
        d = pen.getCommands()
        if d:
            ET.SubElement(g, f"{{{_SVG_NS}}}path", {
                "d": d,
                "transform": f"translate({cum},0)",
            })
        advance, _lsb = font["hmtx"][glyph_name]
        cum += advance

    return cum * scale
