"""QR-code overlay fragment.

The homeboard renders SVG with nanosvg, which doesn't support <image>, so
the QR is emitted as one <rect> per dark module on a solid white card.
The card is opaque (not the translucent family panel) to keep the code
scannable.
"""

import xml.etree.ElementTree as ET

import qrcode
from qrcode.constants import ERROR_CORRECT_L

from zzmw_lib.logs import build_logger

from overlay import Fragment

log = build_logger("QrOverlay")

_SVG_NS = "http://www.w3.org/2000/svg"


class QrOverlay:
    CARD_SIZE = 120           # px, square
    QUIET_ZONE_PX = 12        # white margin around the QR matrix
    CARD_RADIUS = 12
    CARD_FILL = "#ffffff"
    CARD_STROKE = "rgb(40,40,40)"
    CARD_STROKE_OPACITY = "0.25"
    MODULE_FILL = "#000000"

    def build_fragment(self, payload):
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_L,
            border=0,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.modules
        n = len(matrix)
        if n == 0:
            return None

        module_size = (self.CARD_SIZE - 2 * self.QUIET_ZONE_PX) / n

        g = ET.Element(f"{{{_SVG_NS}}}g")
        ET.SubElement(g, f"{{{_SVG_NS}}}rect", {
            "x": "0",
            "y": "0",
            "width": f"{self.CARD_SIZE}",
            "height": f"{self.CARD_SIZE}",
            "rx": f"{self.CARD_RADIUS}",
            "ry": f"{self.CARD_RADIUS}",
            "fill": self.CARD_FILL,
            "stroke": self.CARD_STROKE,
            "stroke-opacity": self.CARD_STROKE_OPACITY,
            "stroke-width": "2",
        })

        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if not dark:
                    continue
                x = self.QUIET_ZONE_PX + c * module_size
                y = self.QUIET_ZONE_PX + r * module_size
                ET.SubElement(g, f"{{{_SVG_NS}}}rect", {
                    "x": f"{x:.3f}",
                    "y": f"{y:.3f}",
                    "width": f"{module_size:.3f}",
                    "height": f"{module_size:.3f}",
                    "fill": self.MODULE_FILL,
                })

        return Fragment(element=g, width=self.CARD_SIZE, height=self.CARD_SIZE)
