import re
import json

from zz2m.z2mproxy import Z2MProxy
from services_tracker import _tokenize_query, _score_keywords

from zzmw_lib.logs import build_logger
log = build_logger("ZmwZ2mTracker")

_CAMEL_SPLIT_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')

_Z2M_SKIP_ACTIONS = {
    'linkquality', 'update',
    'identify', 'battery', 'power_on_behavior', 'color_temp_startup',
    'effect', 'execute_if_off',
}

_Z2M_SKIP_THING_TYPES = {'button'}
_Z2M_SKIP_THINGS = {'SnacksPurrveyor'}

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
    """Compact Z2M things into a short text format for LLM context, grouped by type.

    Each type group is emitted as a top-level ## section (same level as services)
    so the LLM sees a uniform format."""
    lines = []

    # Group things by type
    by_type = {}
    for thing in things:
        if (thing.broken or thing.name in _Z2M_SKIP_THINGS
                or thing.thing_type in _Z2M_SKIP_THING_TYPES or len(thing.actions) == 0):
            continue
        type_key = thing.thing_type or 'other'
        by_type.setdefault(type_key, []).append(thing)

    # Controllable devices first
    sensors = by_type.pop('sensor', [])
    for type_key in sorted(by_type.keys()):
        label = type_key.title()
        label = f"{label}es" if label.endswith(('s', 'sh', 'ch', 'x', 'z')) else f"{label}s"
        lines.append(f"## Z2M {label}")
        lines.append("Commands:")
        for thing in sorted(by_type[type_key], key=lambda t: t.name):
            params = []
            descs = []
            for action in thing.actions.values():
                desc = _compact_action_inline(action)
                if desc:
                    params.append(action.name)
                    descs.append(desc)
            if params:
                params_str = ', '.join(params)
                descs_str = ', '.join(descs)
                lines.append(f"- {thing.name}({params_str}): {descs_str}")
            else:
                lines.append(f"- {thing.name}")
        lines.append("")

    # Sensors last (queried via service, not directly via z2m)
    if sensors:
        lines.append("## Z2M Sensors")
        lines.append("Commands:")
        for thing in sorted(sensors, key=lambda t: t.name):
            metrics = [a.name for a in thing.actions.values()
                       if a.name not in _Z2M_SKIP_ACTIONS]
            if metrics:
                params_str = ', '.join(metrics)
                lines.append(f"- {thing.name}({params_str}): read-only sensor")
        lines.append("")

    return '\n'.join(lines)

def _build_thing_keywords(thing):
    """Build a searchable text blob for a Z2M thing from its name, type, and actions."""
    parts = []
    parts.append(' '.join(_CAMEL_SPLIT_RE.split(thing.name)).lower())
    if thing.thing_type:
        parts.append(thing.thing_type.lower())
    for action in thing.actions.values():
        if action.name not in _Z2M_SKIP_ACTIONS:
            parts.append(action.name.replace('_', ' ').lower())
    return ' '.join(parts)


class Z2mTracker:
    def __init__(self, cfg, mqtt_client, sched):
        self._z2m = Z2MProxy(cfg, mqtt_client, sched)

    def get_z2m_llm_context(self):
        things = self._z2m.get_all_registered_things()
        return compact_z2m_things_for_llm(things)

    def get_z2m_llm_context_filtered(self, user_query):
        d = {}
        for t in self._z2m.get_all_registered_things():
            d[t.name] = t.dictify()
        log.warning(json.dumps(d, default=str, indent=2))
        return ""
        """Return compact Z2M context for only things relevant to user_query."""
        things = self._z2m.get_all_registered_things()
        query_words = _tokenize_query(user_query)
        if not query_words:
            return compact_z2m_things_for_llm(things)

        matched = [t for t in things
                   if _score_keywords(query_words, _build_thing_keywords(t)) > 0]
        if not matched:
            return ''
        return compact_z2m_things_for_llm(matched)

