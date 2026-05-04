from icons import Icons
from text_to_path import render_text
from weather_report import build_weather_report

import copy
import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

log = build_logger("WeatherOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"


class WeatherOverlay:
    CANVAS_W = 1920
    CANVAS_H = 1080

    # Panel layout
    PANEL_W = 340
    PANEL_MARGIN = 20
    PANEL_PAD = 12
    PANEL_RADIUS = 24
    PANEL_FILL = "rgb(255,255,255)"
    PANEL_FILL_OPACITY = "0.78"
    PANEL_STROKE = "rgb(40,40,40)"
    PANEL_STROKE_OPACITY = "0.25"

    # Row layout
    ICON_SIZE = 90
    ROW_GAP = 8

    # Text
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

    def generate_svg(self):
        ET.register_namespace("", _SVG_NS)
        out = ET.Element(f"{{{_SVG_NS}}}svg", {
            "width": str(self.CANVAS_W),
            "height": str(self.CANVAS_H),
            "viewBox": f"0 0 {self.CANVAS_W} {self.CANVAS_H}",
        })

        report = build_weather_report(self._lat, self._lon, self._tz)
        blocks = report["blocks"]

        row_h = self.ICON_SIZE + self.ROW_GAP
        panel_h = self.PANEL_PAD * 2 + max(0, len(blocks) * row_h - self.ROW_GAP)
        panel_x = self.CANVAS_W - self.PANEL_W - self.PANEL_MARGIN
        panel_y = self.PANEL_MARGIN

        ET.SubElement(out, f"{{{_SVG_NS}}}rect", {
            "x": f"{panel_x}",
            "y": f"{panel_y}",
            "width": f"{self.PANEL_W}",
            "height": f"{panel_h}",
            "rx": f"{self.PANEL_RADIUS}",
            "ry": f"{self.PANEL_RADIUS}",
            "fill": self.PANEL_FILL,
            "fill-opacity": self.PANEL_FILL_OPACITY,
            "stroke": self.PANEL_STROKE,
            "stroke-opacity": self.PANEL_STROKE_OPACITY,
            "stroke-width": "2",
        })

        row_x = panel_x + self.PANEL_PAD
        row_y = panel_y + self.PANEL_PAD
        for block in blocks:
            self._render_row(out, row_x, row_y, block)
            row_y += row_h

        return ET.tostring(out, encoding="unicode")

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
