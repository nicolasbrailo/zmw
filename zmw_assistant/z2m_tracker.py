from zz2m.z2mproxy import Z2MProxy

_Z2M_SKIP_ACTIONS = {
    'linkquality', 'update',
    'identify', 'battery', 'power_on_behavior', 'color_temp_startup',
    'effect', 'execute_if_off',
}

_Z2M_SKIP_THING_TYPES = {'button'}

def _compact_action_inline(action):
    """Format a single action as an inline string, or None to skip."""
    if action.name in _Z2M_SKIP_ACTIONS:
        return None
    meta = action.value.meta
    if meta['type'] in ('composite', 'list', 'user_defined'):
        return None

    if meta['type'] == 'binary':
        return f"{action.name} {meta['value_on']}/{meta['value_off']}"
    if meta['type'] == 'numeric':
        lo = meta.get('value_min', '')
        hi = meta.get('value_max', '')
        if lo != '' or hi != '':
            return f"{action.name} {lo}-{hi}"
        return action.name
    if meta['type'] == 'enum':
        vals = '/'.join(str(v) for v in meta.get('values', []))
        return f"{action.name} {vals}" if vals else action.name
    return action.name


def compact_z2m_things_for_llm(things):
    """Compact Z2M things into a short text format for LLM context, grouped by type."""
    lines = [
        "## Zigbee2MQTT Devices",
        "Control devices by publishing JSON to zigbee2mqtt/{device_name}/set",
        "",
    ]

    # Group things by type
    by_type = {}
    for thing in things:
        if thing.broken or thing.thing_type in _Z2M_SKIP_THING_TYPES or len(thing.actions) == 0:
            continue
        type_key = thing.thing_type or 'other'
        by_type.setdefault(type_key, []).append(thing)

    # Controllable devices first (next to the "how to control" heading)
    sensors = by_type.pop('sensor', [])
    for type_key in sorted(by_type.keys()):
        label = type_key.title()
        label = f"{label}es" if label.endswith(('s', 'sh', 'ch', 'x', 'z')) else f"{label}s"
        lines.append(f"### {label}")
        for thing in sorted(by_type[type_key], key=lambda t: t.name):
            actions = []
            for action in thing.actions.values():
                desc = _compact_action_inline(action)
                if desc:
                    actions.append(desc)
            if actions:
                lines.append(f"- {thing.name}: {', '.join(actions)}")
            else:
                lines.append(f"- {thing.name}")
        lines.append("")

    # Sensors last (queried via service, not directly via z2m)
    if sensors:
        lines.append("### Sensors (query via ZmwSensormon)")
        for thing in sorted(sensors, key=lambda t: t.name):
            metrics = [a.name for a in thing.actions.values()
                       if a.name not in _Z2M_SKIP_ACTIONS]
            if metrics:
                lines.append(f"- {thing.name}: {', '.join(metrics)}")
        lines.append("")

    return '\n'.join(lines)

class Z2mTracker:
    def __init__(self, cfg, mqtt_client, sched):
        self._z2m = Z2MProxy(cfg, mqtt_client, sched)

    def get_z2m_llm_context(self):
        things = self._z2m.get_all_registered_things()
        return compact_z2m_things_for_llm(things)

