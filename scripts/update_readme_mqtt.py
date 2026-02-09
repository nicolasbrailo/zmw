#!/usr/bin/env python3
"""Update each zmw_* service's README.md with an MQTT section generated from get_mqtt_description().

Parses the service's main .py file using ast, extracts the dict literal returned by
get_mqtt_description(), formats it as markdown, and appends/replaces the ## MQTT section
in the service's README.md.

Usage:
    python scripts/update_readme_mqtt.py                  # update all services
    python scripts/update_readme_mqtt.py zmw_telegram     # update one service
"""
import ast
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MQTT_SECTION_HEADER = "## MQTT"


class _ReplaceSelfCalls(ast.NodeTransformer):
    """Replace self.method() calls with None so ast.literal_eval can handle the rest."""

    def visit_Call(self, node):
        self.generic_visit(node)
        func = node.func
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == 'self'):
            return ast.copy_location(ast.Constant(value=None), node)
        return node


def extract_mqtt_description(py_path):
    """Parse a .py file and extract the dict literal from get_mqtt_description()."""
    with open(py_path) as f:
        tree = ast.parse(f.read(), filename=py_path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != 'get_mqtt_description':
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                cleaned = _ReplaceSelfCalls().visit(child.value)
                try:
                    return ast.literal_eval(cleaned)
                except ValueError as e:
                    # Find the non-literal nodes to help diagnose the issue
                    bad_nodes = []
                    for n in ast.walk(cleaned):
                        if isinstance(n, ast.Call):
                            bad_nodes.append(f"line {n.lineno}: call to {ast.unparse(n.func)}()")
                        elif isinstance(n, (ast.Name, ast.Attribute)) and not isinstance(
                                getattr(n, '_parent', None), ast.Call):
                            bad_nodes.append(f"line {n.lineno}: variable ref {ast.unparse(n)}")
                    detail = "; ".join(bad_nodes[:5]) if bad_nodes else "unknown non-literal"
                    raise ValueError(
                        f"{py_path}: can't literal_eval get_mqtt_description() return value: "
                        f"{e} — non-literal expressions found: {detail}"
                    ) from e

    return None


def format_params_table(params):
    """Format a params/payload dict as a markdown table."""
    if not params:
        return "_No parameters._\n"
    if isinstance(params, str):
        return f"{params}\n"
    if isinstance(params, list):
        # payload is an example list (e.g. get_history_reply), show as-is
        return f"Payload: `{params}`\n"
    lines = ["| Param | Description |", "|-------|-------------|"]
    for k, v in params.items():
        lines.append(f"| `{k}` | {v} |")
    return "\n".join(lines) + "\n"


def format_mqtt_section(svc_topic, desc):
    """Format the MQTT description dict as a markdown section."""
    lines = [MQTT_SECTION_HEADER, "", f"**Topic:** `{svc_topic}`", ""]

    commands = desc.get("commands", {})
    if commands:
        lines.append("### Commands")
        lines.append("")
        for cmd, info in commands.items():
            lines.append(f"#### `{cmd}`")
            lines.append("")
            lines.append(info["description"])
            lines.append("")
            lines.append(format_params_table(info.get("params", {})))

    announcements = desc.get("announcements", {})
    if announcements:
        lines.append("### Announcements")
        lines.append("")
        for topic, info in announcements.items():
            lines.append(f"#### `{topic}`")
            lines.append("")
            lines.append(info["description"])
            lines.append("")
            payload = info.get("payload", {})
            if payload:
                lines.append(format_params_table(payload))

    return "\n".join(lines).rstrip() + "\n"


def get_svc_topic(py_path):
    """Extract the svc_topic string from super().__init__ call."""
    with open(py_path) as f:
        tree = ast.parse(f.read(), filename=py_path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Look for super().__init__(...) calls
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == '__init__'
                and isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Name)
                and func.value.func.id == 'super'):
            continue
        # The svc_topic is typically the 2nd positional arg or a keyword arg
        for kw in node.keywords:
            if kw.arg == 'svc_topic' and isinstance(kw.value, ast.Constant):
                return kw.value.value
        # Check positional args (cfg, svc_topic, ...)
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            return node.args[1].value

    return None


def update_readme(readme_path, mqtt_section):
    """Append or replace the ## MQTT section in a README.md."""
    with open(readme_path) as f:
        content = f.read()

    # Find existing MQTT section and remove it
    idx = content.find(f"\n{MQTT_SECTION_HEADER}\n")
    if idx != -1:
        content = content[:idx + 1]  # keep the newline before
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n"

    content += mqtt_section

    with open(readme_path, 'w') as f:
        f.write(content)


def process_service(svc_dir):
    """Process a single service directory."""
    svc_name = os.path.basename(svc_dir)
    py_path = os.path.join(svc_dir, f"{svc_name}.py")
    readme_path = os.path.join(svc_dir, "README.md")

    if not os.path.isfile(py_path):
        print(f"  SKIP {svc_name}: no {svc_name}.py")
        return False

    if not os.path.isfile(readme_path):
        print(f"  SKIP {svc_name}: no README.md")
        return False

    desc = extract_mqtt_description(py_path)
    if desc is None:
        print(f"  SKIP {svc_name}: no get_mqtt_description()")
        return False

    topic = get_svc_topic(py_path)
    if topic is None:
        print(f"  SKIP {svc_name}: can't find svc_topic")
        return False

    mqtt_section = format_mqtt_section(topic, desc)
    update_readme(readme_path, mqtt_section)
    print(f"  OK   {svc_name}")
    return True


def main():
    targets = sys.argv[1:]

    if targets:
        dirs = [os.path.join(PROJECT_DIR, t) for t in targets]
    else:
        dirs = sorted(
            os.path.join(PROJECT_DIR, d) for d in os.listdir(PROJECT_DIR)
            if d.startswith("zmw_") and os.path.isdir(os.path.join(PROJECT_DIR, d))
        )

    ok = 0
    for svc_dir in dirs:
        if process_service(svc_dir):
            ok += 1

    print(f"\nUpdated {ok}/{len(dirs)} READMEs")


if __name__ == "__main__":
    main()
