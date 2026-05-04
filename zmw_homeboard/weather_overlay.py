import copy
import os
import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger

log = build_logger("WeatherOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"

# Tags nanosvg silently drops. Local names only (namespace stripped).
_UNSUPPORTED_TAGS = frozenset({
    "text", "tspan", "textPath",
    "use", "symbol",
    "style",
    "image", "foreignObject",
    "pattern",
    "filter", "mask", "clipPath",
    "animate", "animateTransform", "animateMotion", "set",
})


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


class WeatherOverlay:
    CANVAS_W = 1920
    CANVAS_H = 1080
    ICON_SIZE = 80
    ICON_PAD = 10

    def __init__(self, icons_dir=None):
        if icons_dir is None:
            icons_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "icons_weather"
            )
        self._icons = []
        for name in sorted(os.listdir(icons_dir)):
            if not name.endswith(".svg"):
                continue
            path = os.path.join(icons_dir, name)
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as e:
                log.critical("Cannot parse icon '%s': %s", path, e)
                continue
            bad = self._find_unsupported(root)
            if bad:
                log.critical(
                    "Icon '%s' contains tags unsupported by nanosvg: %s. Run clean_icons.py",
                    name, sorted(bad),
                )
            viewbox = root.get("viewBox")
            if not viewbox:
                w = root.get("width", str(self.ICON_SIZE))
                h = root.get("height", str(self.ICON_SIZE))
                viewbox = f"0 0 {w} {h}"
            self._icons.append((name, root, viewbox))
        log.info("Loaded %d weather icons from %s", len(self._icons), icons_dir)

    @staticmethod
    def _find_unsupported(root):
        bad = set()
        for el in root.iter():
            tag = _local(el.tag)
            if tag in _UNSUPPORTED_TAGS:
                bad.add(tag)
        return bad

    def generate_svg(self):
        ET.register_namespace("", _SVG_NS)
        out = ET.Element(f"{{{_SVG_NS}}}svg", {
            "width": str(self.CANVAS_W),
            "height": str(self.CANVAS_H),
            "viewBox": f"0 0 {self.CANVAS_W} {self.CANVAS_H}",
        })
        step = self.ICON_SIZE + self.ICON_PAD
        x, y = self.ICON_PAD, self.ICON_PAD
        for _name, root, viewbox in self._icons:
            if x + self.ICON_SIZE > self.CANVAS_W:
                x = self.ICON_PAD
                y += step
            tx, ty, scale = self._fit(viewbox, x, y)
            g = ET.SubElement(out, f"{{{_SVG_NS}}}g", {
                "transform": f"translate({tx:.3f},{ty:.3f}) scale({scale:.6f})",
            })
            for child in list(root):
                g.append(copy.deepcopy(child))
            x += step
        return ET.tostring(out, encoding="unicode")

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
