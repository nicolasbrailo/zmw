"""SVG overlay composer.

Stitches together independent overlay fragments (weather, QR, announce, ...)
onto the homeboard canvas. Each fragment is laid out at local origin (0,0)
and the composer takes care of anchor placement, stacking when several
fragments target the same anchor, and the rotation transform that maps the
logical frame onto the physical SVG.
"""

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

log = build_logger("Overlay")

_SVG_NS = "http://www.w3.org/2000/svg"

# Shared visual constants reused by fragments so they look like a family.
PANEL_MARGIN = 20
PANEL_PAD = 12
PANEL_RADIUS = 24
PANEL_FILL = "rgb(255,255,255)"
PANEL_FILL_OPACITY = "0.78"
PANEL_STROKE = "rgb(40,40,40)"
PANEL_STROKE_OPACITY = "0.25"

INTER_FRAGMENT_GAP = 12


@dataclass
class Fragment:
    """A self-contained overlay piece, drawn at local (0,0).

    `element` is an SVG element (typically a <g>) holding the fragment's
    content. `width`/`height` describe its bounding box so the composer can
    place it. `preferred_anchor` is the default anchor when the caller
    doesn't override.
    """
    element: ET.Element
    width: float
    height: float
    preferred_anchor: str = "free"


def panel_rect(width, height, fill_opacity=PANEL_FILL_OPACITY):
    """Build the shared rounded translucent panel used by fragments."""
    return ET.Element(f"{{{_SVG_NS}}}rect", {
        "x": "0",
        "y": "0",
        "width": f"{width}",
        "height": f"{height}",
        "rx": f"{PANEL_RADIUS}",
        "ry": f"{PANEL_RADIUS}",
        "fill": PANEL_FILL,
        "fill-opacity": str(fill_opacity),
        "stroke": PANEL_STROKE,
        "stroke-opacity": PANEL_STROKE_OPACITY,
        "stroke-width": "2",
    })


class Overlay:
    """Compose fragments into a single SVG for one homeboard."""

    def __init__(self, hostinfo):
        self._canvas_w = int(hostinfo.get('resolution_w', 1920))
        self._canvas_h = int(hostinfo.get('resolution_h', 1080))
        self._rotation = int(hostinfo.get('rotation', 0)) % 360
        self._h_align = hostinfo.get('h_align', 'center')
        self._v_align = hostinfo.get('v_align', 'center')
        self._fragments = []  # list of (Fragment, resolved_anchor)

    @property
    def logical_size(self):
        """(w, h) of the canvas after rotation — what fragments should fit in."""
        if self._rotation in (90, 270):
            return (self._canvas_h, self._canvas_w)
        return (self._canvas_w, self._canvas_h)

    def add(self, fragment, anchor=None):
        """Queue a fragment. None fragments are silently dropped."""
        if fragment is None:
            return
        anchor = anchor or fragment.preferred_anchor or "free"
        self._fragments.append((fragment, self._resolve_anchor(anchor)))

    def compose(self):
        """Return the composed SVG string, or None if there's nothing to draw."""
        if not self._fragments:
            return None

        logical_w, logical_h = self.logical_size

        ET.register_namespace("", _SVG_NS)
        out = ET.Element(f"{{{_SVG_NS}}}svg", {
            "width": str(self._canvas_w),
            "height": str(self._canvas_h),
            "viewBox": f"0 0 {self._canvas_w} {self._canvas_h}",
        })

        rot = self._rotation_transform()
        content = ET.SubElement(out, f"{{{_SVG_NS}}}g", {"transform": rot}) \
            if rot else out

        by_anchor = {}
        for frag, anchor in self._fragments:
            by_anchor.setdefault(anchor, []).append(frag)

        for anchor, frags in by_anchor.items():
            self._place_stack(content, anchor, frags, logical_w, logical_h)

        return ET.tostring(out, encoding="unicode")

    def _resolve_anchor(self, anchor):
        if anchor != "free":
            return anchor
        # Free corner = opposite of the picture's weight.
        h = "right" if self._h_align == "left" else "left"
        v = "bottom" if self._v_align == "top" else "top"
        return f"{v}-{h}"

    def _place_stack(self, content, anchor, frags, logical_w, logical_h):
        total_h = (sum(f.height for f in frags)
                   + max(0, len(frags) - 1) * INTER_FRAGMENT_GAP)

        if anchor == "center":
            y = (logical_h - total_h) / 2
        elif "bottom" in anchor:
            y = logical_h - PANEL_MARGIN - total_h
        else:
            y = PANEL_MARGIN

        for frag in frags:
            if anchor == "center":
                x = (logical_w - frag.width) / 2
            elif "right" in anchor:
                x = logical_w - PANEL_MARGIN - frag.width
            else:
                x = PANEL_MARGIN
            wrapper = ET.SubElement(content, f"{{{_SVG_NS}}}g", {
                "transform": f"translate({x:.3f},{y:.3f})",
            })
            wrapper.append(frag.element)
            y += frag.height + INTER_FRAGMENT_GAP

    def _rotation_transform(self):
        # Map logical (pre-rotation) frame onto physical SVG canvas.
        # Rotation is clockwise, matching the picture renderer.
        if self._rotation == 90:
            return f"translate({self._canvas_w},0) rotate(90)"
        if self._rotation == 180:
            return f"translate({self._canvas_w},{self._canvas_h}) rotate(180)"
        if self._rotation == 270:
            return f"translate(0,{self._canvas_h}) rotate(270)"
        return None
