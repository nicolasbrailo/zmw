import copy
import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

from icons import Icons
from overlay import Fragment, panel_rect, PANEL_PAD
from text_to_path import render_text
from weather_report import build_weather_report

log = build_logger("WeatherOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"


class WeatherOverlay:
    PANEL_W = 340

    ICON_SIZE = 90
    ROW_GAP = 8

    TEXT_COLOR = "#1a1a1a"
    TEXT_COLOR_MUTED = "#444"
    FONT_SIZE_LABEL = 26
    FONT_SIZE_TEMP = 22
    FONT_SIZE_PRECIP = 18

    def __init__(self, icons_dir, lat, lon, tz="auto"):
        self._icons = Icons(icons_dir)
        self._lat = lat
        self._lon = lon
        self._tz = tz

    def build_fragment(self):
        """Render the weather panel as a Fragment, or None on fetch failure."""
        report = build_weather_report(self._lat, self._lon, self._tz)
        if report is None:
            return None
        blocks = report["blocks"]
        if not blocks:
            return None

        row_h = self.ICON_SIZE + self.ROW_GAP
        panel_h = PANEL_PAD * 2 + max(0, len(blocks) * row_h - self.ROW_GAP)

        g = ET.Element(f"{{{_SVG_NS}}}g")
        g.append(panel_rect(self.PANEL_W, panel_h))

        row_x = PANEL_PAD
        row_y = PANEL_PAD
        for block in blocks:
            self._render_row(g, row_x, row_y, block)
            row_y += row_h

        return Fragment(element=g, width=self.PANEL_W, height=panel_h)

    def _render_row(self, out, x, y, block):
        self._render_icon(out, block["category"], x, y)

        text_x = x + self.ICON_SIZE + 14
        label_y = y + self.FONT_SIZE_LABEL + 2
        temp_str = (f"{block['temp_min']:.0f}°C – "
                    f"{block['temp_max']:.0f}°C")
        render_text(out, temp_str, text_x, label_y,
                    self.FONT_SIZE_LABEL, fill=self.TEXT_COLOR, weight="bold")

        temp_y = label_y + self.FONT_SIZE_TEMP + 6
        render_text(out, block["label"], text_x, temp_y,
                    self.FONT_SIZE_TEMP, fill=self.TEXT_COLOR_MUTED)

        if "precipitation_mm" in block:
            precip_y = temp_y + self.FONT_SIZE_PRECIP + 4
            render_text(out, f"{block['precipitation_mm']:.1f} mm",
                        text_x, precip_y,
                        self.FONT_SIZE_PRECIP, fill=self.TEXT_COLOR_MUTED)

    def _render_icon(self, out, category, x, y):
        try:
            root, viewbox = self._icons.get_icon(category)
        except KeyError:
            log.error("No weather icon for category '%s'", category)
            return
        tx, ty, scale = self._fit(viewbox, x, y)
        g = ET.SubElement(out, f"{{{_SVG_NS}}}g", {
            "transform": f"translate({tx:.3f},{ty:.3f}) scale({scale:.6f})",
        })
        for child in list(root):
            g.append(copy.deepcopy(child))

    def _fit(self, viewbox, x, y):
        parts = viewbox.split()
        if len(parts) != 4:
            return x, y, 1.0
        try:
            vx, vy, vw, vh = (float(p) for p in parts)
        except ValueError:
            return x, y, 1.0
        scale = self.ICON_SIZE / max(vw, vh)
        return x - vx * scale, y - vy * scale, scale
