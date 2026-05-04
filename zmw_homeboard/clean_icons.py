#!/usr/bin/env python3
"""Bake class-based CSS into presentation attributes, then run picosvg.

Picosvg's pipeline drops <style> blocks and class attributes without
translating one into the other, so colors defined via .cls-N { fill: ... }
disappear. This script does that translation first, then hands the result
to picosvg for the rest of the cleanup (transform flattening, etc.).

Usage: clean_icons.py [path]
  path: directory of *.svg or a single file (default: ./icons_weather)
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

_SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", _SVG_NS)

# CSS properties with direct SVG presentation-attribute equivalents.
_PRES_ATTRS = frozenset({
    "fill", "fill-opacity", "fill-rule",
    "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset",
    "opacity", "color",
})

# Elements removed wholesale: <style> is now redundant, the rest are
# unsupported by nanosvg and decorative in these icons.
_STRIP_TAGS = frozenset({"style", "text", "tspan", "title", "desc"})

_RULE_RE = re.compile(r"\.([a-zA-Z][\w-]*)\s*\{([^}]*)\}")
_DECL_RE = re.compile(r"\s*([a-zA-Z-]+)\s*:\s*([^;]+?)\s*(?:;|$)")


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_css(text):
    rules = {}
    for m in _RULE_RE.finditer(text):
        cls = m.group(1)
        decls = {}
        for d in _DECL_RE.finditer(m.group(2)):
            decls[d.group(1).strip().lower()] = d.group(2).strip()
        rules[cls] = decls
    return rules


def _collect_css(root):
    return "\n".join(
        el.text for el in root.iter()
        if _local(el.tag) == "style" and el.text
    )


def _remove(root, target):
    # ElementTree has no parent pointers — find the parent by walking.
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                parent.remove(child)
                return


def inline_classes(svg_text):
    root = ET.fromstring(svg_text)
    rules = _parse_css(_collect_css(root))

    for el in root.iter():
        cls_attr = el.get("class")
        if not cls_attr:
            continue
        for cls in cls_attr.split():
            for prop, val in rules.get(cls, {}).items():
                if prop in _PRES_ATTRS and el.get(prop) is None:
                    el.set(prop, val)
        del el.attrib["class"]

    for n in [el for el in root.iter() if _local(el.tag) in _STRIP_TAGS]:
        _remove(root, n)

    for n in [
        el for el in root.iter()
        if _local(el.tag) == "defs" and len(el) == 0
        and not (el.text and el.text.strip())
    ]:
        _remove(root, n)

    return ET.tostring(root, encoding="unicode")


def process(path):
    with open(path, "r", encoding="utf-8") as f:
        inlined = inline_classes(f.read())

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".svg", delete=False, encoding="utf-8",
    ) as tmp:
        tmp.write(inlined)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["picosvg", tmp_path],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip()
    finally:
        os.unlink(tmp_path)

    with open(path, "w", encoding="utf-8") as f:
        f.write(result.stdout)
    return True, None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "path", nargs="?", default=os.path.join(here, "icons_weather"),
        help="Directory of *.svg or a single file (default: ./icons_weather)",
    )
    args = ap.parse_args()

    if os.path.isdir(args.path):
        files = sorted(
            os.path.join(args.path, n) for n in os.listdir(args.path)
            if n.endswith(".svg")
        )
    else:
        files = [args.path]

    failures = 0
    for f in files:
        print(f"Processing {f}", flush=True)
        ok, err = process(f)
        if not ok:
            failures += 1
            print(f"  FAILED ({err}); original left untouched", file=sys.stderr)

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
