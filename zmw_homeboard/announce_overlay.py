"""Free-form text overlay fragment.

Renders the message big and centered so it's readable from across the room.
Uses a more translucent panel than the other fragments — it covers most of
the screen, so we don't want to fully obscure the picture behind it.
"""

import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

from overlay import Fragment, panel_rect
from text_to_path import measure_text, render_text

log = build_logger("AnnounceOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"


class AnnounceOverlay:
    FONT_SIZE = 96
    LINE_GAP = 16
    PAD_X = 48
    PAD_Y = 36
    TEXT_COLOR = "#0a0a0a"
    PANEL_FILL_OPACITY = 0.55

    # When a canvas width is provided, the panel takes up to this fraction of
    # it; otherwise we fall back to a fixed reasonable width.
    WIDTH_FRACTION = 0.85
    DEFAULT_WIDTH = 1200

    def build_fragment(self, text, canvas_width=None):
        text = (text or "").strip()
        if not text:
            return None

        if canvas_width is not None:
            panel_w = int(canvas_width * self.WIDTH_FRACTION)
        else:
            panel_w = self.DEFAULT_WIDTH

        max_text_w = panel_w - 2 * self.PAD_X
        lines = self._wrap(text, max_text_w)
        if not lines:
            return None

        line_h = self.FONT_SIZE + self.LINE_GAP
        panel_h = (self.PAD_Y * 2
                   + len(lines) * self.FONT_SIZE
                   + max(0, len(lines) - 1) * self.LINE_GAP)

        g = ET.Element(f"{{{_SVG_NS}}}g")
        g.append(panel_rect(panel_w, panel_h,
                            fill_opacity=self.PANEL_FILL_OPACITY))

        baseline_y = self.PAD_Y + self.FONT_SIZE
        for line in lines:
            render_text(g, line, self.PAD_X, baseline_y,
                        self.FONT_SIZE, fill=self.TEXT_COLOR, weight="bold")
            baseline_y += line_h

        log.info("RENDER %s", text)
        return Fragment(element=g, width=panel_w, height=panel_h,
                        preferred_anchor="center")

    def _wrap(self, text, max_w):
        lines = []
        for paragraph in text.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                lines.append("")
                continue
            words = paragraph.split()
            current = ""
            for w in words:
                candidate = w if not current else f"{current} {w}"
                if measure_text(candidate, self.FONT_SIZE, weight="bold") <= max_w:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                # Word alone may overflow the panel; render it anyway rather
                # than dropping content.
                current = w
            if current:
                lines.append(current)
        return lines
