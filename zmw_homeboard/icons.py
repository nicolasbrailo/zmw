import os

import xml.etree.ElementTree as ET

from zzmw_lib.logs import build_logger


log = build_logger("Icons")

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

def _find_unsupported_svg_tags(root):
    def _local(tag):
        return tag.split("}", 1)[1] if "}" in tag else tag
    bad = set()
    for el in root.iter():
        tag = _local(el.tag)
        if tag in _UNSUPPORTED_TAGS:
            bad.add(tag)
    return bad

_DEFAULT_ICON_SIZE = 80

class Icons:
    def __init__(self, search_path):
        self._icons = {}
        icons_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "icons_weather"
        )

        for name in sorted(os.listdir(icons_dir)):
            if not name.endswith(".svg"):
                continue
            path = os.path.join(icons_dir, name)

            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as e:
                log.critical("Cannot parse icon '%s': %s", path, e)
                continue

            bad = _find_unsupported_svg_tags(root)
            if bad:
                log.critical(
                    "Icon '%s' contains tags unsupported by nanosvg: %s. Run clean_icons.py",
                    name, sorted(bad),
                )
            viewbox = root.get("viewBox")
            if not viewbox:
                w = root.get("width", str(_DEFAULT_ICON_SIZE))
                h = root.get("height", str(_DEFAULT_ICON_SIZE))
                viewbox = f"0 0 {w} {h}"
            self._icons[name[:-len('.svg')]] = (root, viewbox)
        log.info("Loaded %d weather icons from %s", len(self._icons), icons_dir)

    def get_icon_names(self):
        return list(self._icons.keys())

    def get_icon(self, k):
        return self._icons[k]

