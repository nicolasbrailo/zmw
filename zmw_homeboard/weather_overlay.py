from icons import Icons
from text_to_path import render_text
from weather_report import build_weather_report

import copy
import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

log = build_logger("WeatherOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"


class WeatherOverlay:
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

    def generate_svg(self, hostinfo):
        log.info("Render weather SVG for %s", hostinfo)
        canvas_w = hostinfo.get('resolution_w', 1920)
        canvas_h = hostinfo.get('resolution_h', 1080)
        rotation = hostinfo.get('rotation', 0) % 360
        v_align = hostinfo.get('v_align', 'center')
        h_align = hostinfo.get('h_align', 'center')

        # The picture is rotated in software: at 90/270 the visible canvas
        # axes are swapped relative to the physical resolution. We lay the
        # panel out in this "logical" frame, then a single wrapper transform
        # maps it back onto the physical SVG.
        if rotation in (90, 270):
            logical_w, logical_h = canvas_h, canvas_w
        else:
            logical_w, logical_h = canvas_w, canvas_h

        ET.register_namespace("", _SVG_NS)
        out = ET.Element(f"{{{_SVG_NS}}}svg", {
            "width": str(canvas_w),
            "height": str(canvas_h),
            "viewBox": f"0 0 {canvas_w} {canvas_h}",
        })

        report = build_weather_report(self._lat, self._lon, self._tz)
        if report is None:
            return None
        blocks = report["blocks"]

        row_h = self.ICON_SIZE + self.ROW_GAP
        panel_h = self.PANEL_PAD * 2 + max(0, len(blocks) * row_h - self.ROW_GAP)

        # Place panel on the side opposite the picture's weight, so it sits
        # over the empty area instead of covering the photo.
        if h_align == 'left':
            panel_x = logical_w - self.PANEL_W - self.PANEL_MARGIN
        else:
            panel_x = self.PANEL_MARGIN
        if v_align == 'top':
            panel_y = logical_h - panel_h - self.PANEL_MARGIN
        else:
            panel_y = self.PANEL_MARGIN

        transform = self._rotation_transform(rotation, canvas_w, canvas_h)
        content = ET.SubElement(out, f"{{{_SVG_NS}}}g", {"transform": transform}) \
            if transform else out

        ET.SubElement(content, f"{{{_SVG_NS}}}rect", {
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
            self._render_row(content, row_x, row_y, block)
            row_y += row_h

        return ET.tostring(out, encoding="unicode")

    @staticmethod
    def _rotation_transform(rotation, canvas_w, canvas_h):
        # Map the logical (pre-rotation) frame onto the physical SVG canvas.
        # Rotation is interpreted as clockwise, matching the picture renderer.
        if rotation == 90:
            return f"translate({canvas_w},0) rotate(90)"
        if rotation == 180:
            return f"translate({canvas_w},{canvas_h}) rotate(180)"
        if rotation == 270:
            return f"translate(0,{canvas_h}) rotate(270)"
        return None

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
