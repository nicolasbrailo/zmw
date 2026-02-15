import json
import re
import logging
import time

from llama_cpp import Llama
from llama_cpp import LlamaGrammar

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

LLM_PREAMBLE = """\
You are a home assistant. Pick a command from the services below.
Reply JSON: {"service": "...", "command": "...", "args": {...}}
Only use listed commands and args. Leave args empty ({}) unless the user gives a value.
Pick the command whose description best matches the request.
If nothing matches, reply exactly: DONT_KNOW
Do not explain or add any other text.

Examples:
User: turn on the living room lights
{"service": "ZmwLights", "command": "all_lights_on", "args": {"prefix": "LivingRoom"}}
User: announce dinner is ready
{"service": "ZmwSpeakerAnnounce", "command": "tts", "args": {"msg": "Dinner is ready"}}
User: what is the meaning of life
DONT_KNOW

Available services:
"""

LLM_CONTEXT_SZ = 8192
LLM_MODEL_PATH = "models/7B/qwen2.5-1.5b-instruct-q4_k_m.gguf"
COMPACT_SVCS = False

# Each entry: (prompt, expected_service, expected_command)
# Args are not checked — only service + command matter for correctness.
PROMPTS = [
    # Lights
    ("turn kitchen lights on",              "ZmwLights", "all_lights_on"),
    ("turn kitchen lights off",             "ZmwLights", "all_lights_off"),
    ("turn off all lights",                 "ZmwLights", "all_lights_off"),
    ("are there any lights on?",            "ZmwLights", "get_lights"),
    ("are there any lights on",             "ZmwLights", "get_lights"),
    ("set color of EntradaColor to red",    "ZmwLights", "all_lights_on"),
    ("EntradaColor color purple",           "ZmwLights", "all_lights_on"),

    # Music
    ("stop all music",                      "ZmwSonosCtrl", "stop_all"),
    ("stop music",                          "ZmwSpotify", "stop"),
    ("volume up",                           "ZmwSonosCtrl", "volume_up"),
    ("raise the TV volume",                 "ZmwSonosCtrl", "volume_up"),
    ("please raise the volume",             "ZmwSonosCtrl", "volume_up"),
    ("what music is playing?",              "ZmwSpotify", "get_status"),
    ("what song is playing",               "ZmwSpotify", "get_status"),

    # DONT_KNOW
    ("what is the meaning of life",         None, "DONT_KNOW"),
    ("how do i get to my work",             None, "DONT_KNOW"),
    ("what color is the sky?",              None, "DONT_KNOW"),

    # Heating
    ("turn heating on",                     "ZmwHeating", "boost"),
    ("boost heating",                       "ZmwHeating", "boost"),

    # Temperature / sensors
    ("what's the temperature",              "ZmwSensormon", "get_all_sensor_values"),
    ("what's the temperature in TVRoom",    "ZmwSensormon", "get_sensor_values"),
    ("Is the TV room cold?",               "ZmwSensormon", "get_sensor_values"),
    ("is it cold outside?",                 "ZmwSensormon", "get_sensor_values"),
    ("is it cold?",                         "ZmwSensormon", "get_all_sensor_values"),

    # Cat
    ("feed the cat",                        "ZmwCatSnackDispenser", "feed_now"),
    ("did the cat eat today?",              "ZmwCatSnackDispenser", "get_history"),

    # Doors / windows / contact sensors
    ("is the door open?",                   "ZmwContactmon", "publish_state"),
    ("is the window open?",                 "ZmwContactmon", "publish_state"),
    ("disable door open alarms",            "ZmwContactmon", "skip_chimes"),
    ("disable door open chimes",            "ZmwContactmon", "skip_chimes"),

    # Announcements
    ("announce on the speakers that the food is ready", "ZmwSpeakerAnnounce", "tts"),
    ("announce it's time to go",            "ZmwSpeakerAnnounce", "tts"),
    ("call Nico to the kitchen",            "ZmwSpeakerAnnounce", "tts"),
]

# ---------------------------------------------------------------------------
# Helpers (standalone versions of services_tracker logic)
# ---------------------------------------------------------------------------

_SKIP_SERVICES = {'ZmwDoorman', 'ZmwShellyPlug', 'ZmwSpeechToText', 'ZmwTelegram', 'ZmwWhatsapp'}

_CAMEL_SPLIT_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_STOPWORDS = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'do', 'does', 'did',
    'i', 'me', 'my', 'we', 'our', 'you', 'your', 'it', 'its',
    'what', "what's", 'which', 'who', 'how', 'when', 'where', 'why',
    'can', 'will', 'would', 'could', 'should', 'please',
    'to', 'of', 'in', 'for', 'at', 'by', 'with', 'from',
    'and', 'or', 'but', 'not', 'if', 'then', 'than', 'that', 'this',
    'all', 'some', 'any', 'no', 'so',
}
_REPLY_TOPIC_RE = re.compile(r'\s*\.?\s*Response\s+(published\s+)?on\s+\S+\s*$', re.IGNORECASE)


def _tokenize_query(user_query):
    words = re.findall(r'[a-z0-9]+', user_query.lower())
    return [w for w in words if w not in _STOPWORDS]


def _normalize_word(w):
    w = re.sub(r'[^a-z0-9]', '', w)
    if len(w) > 3 and w.endswith('s'):
        w = w[:-1]
    return w


def _score_keywords(query_words, keywords_text):
    kw_words = set(_normalize_word(w) for w in keywords_text.split() if w)
    return sum(1 for w in query_words if _normalize_word(w) in kw_words)


def _strip_reply_suffix(description):
    return _REPLY_TOPIC_RE.sub('', description)


def _get_required_params(params):
    required = []
    for p_name, p_desc in params.items():
        is_optional = (p_name.endswith('?')
                       or ('(optional)' in str(p_desc).lower() if p_desc else False))
        if not is_optional:
            required.append(p_name)
    return required


def _gbnf_lit(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Services: compact, filter, grammar
# ---------------------------------------------------------------------------

def compact_ifaces_for_llm(svcs_ifaces):
    lines = []
    for svc_name, iface in sorted(svcs_ifaces.items()):
        if svc_name in _SKIP_SERVICES:
            continue
        lines.append(f"## {svc_name}")
        if iface.get('description'):
            lines.append(iface['description'])
        enrich = _SVC_ENRICHERS.get(svc_name)
        if enrich:
            extra = enrich(iface)
            if extra:
                lines.append(extra)
        commands = iface.get('commands', {})
        if commands:
            lines.append("Commands:")
            for cmd_name, cmd in sorted(commands.items()):
                if cmd_name == 'get_mqtt_description':
                    continue
                params = cmd.get('params', {})
                desc = _strip_reply_suffix(cmd.get('description', ''))
                if params:
                    required_params = _get_required_params(params)
                    if required_params:
                        params_str = ', '.join(required_params)
                        lines.append(f"- {cmd_name}({params_str}): {desc}")
                    else:
                        lines.append(f"- {cmd_name}: {desc}")
                else:
                    lines.append(f"- {cmd_name}: {desc}")
        lines.append("")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Per-service enrichers: add extra context from service state/metadata
# ---------------------------------------------------------------------------

def _enrich_lights(iface):
    parts = []
    groups = iface.get('known_groups', [])
    if groups:
        parts.append("Groups: " + ', '.join(g['name'] for g in groups))
    lights = iface.get('known_lights', [])
    if lights:
        parts.append("Lights: " + ', '.join(sorted(l['name'] for l in lights)))
    return '\n'.join(parts)


def _enrich_contactmon(iface):
    sensors = iface.get('sensors', [])
    if not sensors:
        return ''
    items = []
    for s in sensors:
        state = 'closed' if s.get('normal_state', True) else 'open'
        items.append(f"{s['name']} ({state})")
    return "Sensors: " + ', '.join(items)


def _enrich_reolink(iface):
    cams = iface.get('known_cameras', [])
    if not cams:
        return ''
    names = [c.get('alias') or c['cam_host'] for c in cams]
    return "Cameras: " + ', '.join(names)


def _enrich_sensormon(iface):
    sensors = iface.get('sensors', [])
    if not sensors:
        return ''
    # Only show sensors users would actually query about (temperature,
    # humidity, air quality, weather). Skip power monitors, motion, buttons.
    _USEFUL_METRICS = {'temperature', 'humidity', 'pm25', 'voc_index', 'feels_like_temp'}
    items = []
    for s in sensors:
        useful = [m for m in s.get('metrics', []) if m in _USEFUL_METRICS]
        if not useful:
            continue
        items.append(f"{s['name']} ({', '.join(useful)})")
    return "Sensors: " + '; '.join(items)


def _enrich_sonos(iface):
    parts = []
    state = iface.get('sonos_state', {})
    speakers = state.get('speakers', [])
    if speakers:
        names = sorted(s['speaker_info']['zone_name'] for s in speakers)
        parts.append("Speakers: " + ', '.join(names))
    groups = state.get('groups', {})
    if groups:
        grp_strs = [f"{name}: [{', '.join(members)}]" for name, members in sorted(groups.items())]
        parts.append("Groups: " + '; '.join(grp_strs))
    return '\n'.join(parts)


_SVC_ENRICHERS = {
    'ZmwLights': _enrich_lights,
    'ZmwContactmon': _enrich_contactmon,
    'ZmwReolinkCams': _enrich_reolink,
    'ZmwSensormon': _enrich_sensormon,
    'ZmwSonosCtrl': _enrich_sonos,
}


# ---------------------------------------------------------------------------
# Per-service grammar values: constrain params to known valid values
# ---------------------------------------------------------------------------

def _grammar_vals_lights(iface):
    vals = {}
    names = set()
    for g in iface.get('known_groups', []):
        names.add(g['name'])
    for l in iface.get('known_lights', []):
        names.add(l['name'])
    if names:
        vals['prefix'] = sorted(names)
    return vals


def _grammar_vals_sonos(iface):
    vals = {}
    state = iface.get('sonos_state', {})
    speakers = state.get('speakers', [])
    if speakers:
        names = [s['speaker_info']['zone_name'] for s in speakers]
        vals['<speaker_name>'] = sorted(names)
    return vals


def _grammar_vals_reolink(iface):
    vals = {}
    cams = iface.get('known_cameras', [])
    if cams:
        vals['cam_host'] = [c.get('alias') or c['cam_host'] for c in cams]
    return vals


def _grammar_vals_sensormon(iface):
    vals = {}
    sensors = iface.get('sensors', [])
    if sensors:
        vals['name'] = sorted(set(s['name'] for s in sensors))
        all_metrics = set()
        for s in sensors:
            all_metrics.update(s.get('metrics', []))
        if all_metrics:
            vals['metric'] = sorted(all_metrics)
    return vals


def _get_param_values(svc_name, iface):
    """Return {param_name: [valid_values]} for a service, or {} if unconstrained."""
    fn = _SVC_GRAMMAR_VALUES.get(svc_name)
    return fn(iface) if fn else {}


_SVC_GRAMMAR_VALUES = {
    'ZmwLights': _grammar_vals_lights,
    'ZmwSonosCtrl': _grammar_vals_sonos,
    'ZmwReolinkCams': _grammar_vals_reolink,
    'ZmwSensormon': _grammar_vals_sensormon,
}


# ---------------------------------------------------------------------------
# Description overrides: improve LLM disambiguation for confusing commands
# ---------------------------------------------------------------------------

_SVC_DESC_OVERRIDES = {
}

_CMD_DESC_OVERRIDES = {
}


def _patch_descriptions(svcs_ifaces):
    """Apply description overrides to improve LLM accuracy."""
    for svc_name, iface in svcs_ifaces.items():
        if svc_name in _SVC_DESC_OVERRIDES:
            iface['description'] = _SVC_DESC_OVERRIDES[svc_name]
        for cmd_name, cmd in iface.get('commands', {}).items():
            key = (svc_name, cmd_name)
            if key in _CMD_DESC_OVERRIDES:
                cmd['description'] = _CMD_DESC_OVERRIDES[key]


def _build_service_keywords(svc_name, iface):
    parts = []
    parts.append(' '.join(_CAMEL_SPLIT_RE.split(svc_name)).lower())
    if iface.get('description'):
        parts.append(iface['description'].lower())
    for cmd_name, cmd in iface.get('commands', {}).items():
        parts.append(cmd_name.replace('_', ' ').lower())
        if cmd.get('description'):
            parts.append(cmd['description'].lower())
    # Include enrichment data (light names, sensor names, etc.)
    enrich = _SVC_ENRICHERS.get(svc_name)
    if enrich:
        extra = enrich(iface)
        if extra:
            parts.append(extra.lower())
    # Include grammar-constrained values (known valid param values)
    param_values = _get_param_values(svc_name, iface)
    for values in param_values.values():
        for v in values:
            parts.append(' '.join(_CAMEL_SPLIT_RE.split(v)).lower())
    return ' '.join(parts)


def filter_svcs(svcs_ifaces, user_query, max_results=3):
    """Return (compact_text, filtered_ifaces_dict) for services relevant to user_query."""
    query_words = _tokenize_query(user_query)
    if not query_words:
        return compact_ifaces_for_llm(svcs_ifaces), dict(svcs_ifaces)

    scored = []
    for svc_name, iface in svcs_ifaces.items():
        if svc_name in _SKIP_SERVICES:
            continue
        kw_text = _build_service_keywords(svc_name, iface)
        score = _score_keywords(query_words, kw_text)
        if score > 0:
            scored.append((score, svc_name, iface))

    if not scored:
        return '', {}

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_results]
    filtered = {name: iface for _, name, iface in top}
    return compact_ifaces_for_llm(filtered), filtered


def build_gbnf_grammar(svcs_ifaces):
    svc_rule_names = []
    rules = []
    needs_val = False

    for svc_name, iface in sorted(svcs_ifaces.items()):
        commands = iface.get('commands', {})
        if not commands:
            continue

        param_values = _get_param_values(svc_name, iface)
        rule_name = 'svc-' + re.sub(r'[^a-zA-Z0-9]', '-', svc_name)
        cmd_alts = []

        for cmd_name, cmd in sorted(commands.items()):
            if cmd_name == 'get_mqtt_description':
                continue

            required_params = _get_required_params(cmd.get('params', {}))

            if not required_params:
                json_str = f'{{"service": "{svc_name}", "command": "{cmd_name}", "args": {{}}}}'
                cmd_alts.append(_gbnf_lit(json_str))
            else:
                parts = []
                prefix = f'{{"service": "{svc_name}", "command": "{cmd_name}", "args": {{'
                for i, p in enumerate(required_params):
                    if i > 0:
                        prefix += ', '
                    prefix += f'"{p}": "'
                    parts.append(_gbnf_lit(prefix))
                    known = param_values.get(p)
                    if known:
                        parts.append('(' + ' | '.join(_gbnf_lit(v) for v in known) + ')')
                    else:
                        parts.append('val')
                        needs_val = True
                    prefix = '"'
                prefix += '}}'
                parts.append(_gbnf_lit(prefix))
                cmd_alts.append(' '.join(parts))

        if cmd_alts:
            svc_rule_names.append(rule_name)
            rules.append(f'{rule_name} ::= {" | ".join(cmd_alts)}')

    if not svc_rule_names:
        return 'root ::= "DONT_KNOW"'

    root = 'root ::= ' + ' | '.join(svc_rule_names) + ' | "DONT_KNOW"'
    rules.insert(0, root)
    if needs_val:
        rules.append('val ::= [a-zA-Z0-9_ ]+')

    return '\n'.join(rules)


# ---------------------------------------------------------------------------
# Context assembly + LLM run
# ---------------------------------------------------------------------------

def build_context(svcs_ifaces):
    """Build system context and grammar ifaces."""
    if COMPACT_SVCS:
        raise ValueError("Compact mode is no longer supported in single-config playground")
    svc_ctx = compact_ifaces_for_llm(svcs_ifaces)
    return svc_ctx, svcs_ifaces


def check_reply(reply, expected_svc, expected_cmd):
    """Check if reply matches expected service+command. Returns True/False."""
    if expected_cmd == "DONT_KNOW":
        return reply.strip() == "DONT_KNOW"
    try:
        parsed = json.loads(reply)
        return parsed.get('service') == expected_svc and parsed.get('command') == expected_cmd
    except (json.JSONDecodeError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with open('svcs.json') as f:
        svcs_ifaces = json.load(f)

    _patch_descriptions(svcs_ifaces)
    sys_ctx, svc_ifaces_for_grammar = build_context(svcs_ifaces)
    grammar = LlamaGrammar.from_string(build_gbnf_grammar(svc_ifaces_for_grammar))
    system_msg = LLM_PREAMBLE + sys_ctx

    log.info("Loading model '%s'...", LLM_MODEL_PATH)
    llm = Llama(model_path=LLM_MODEL_PATH, n_ctx=LLM_CONTEXT_SZ, verbose=False)

    # Prewarm: feed system context so KV cache is populated
    log.info("Prewarming KV cache...")
    llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "hi"},
        ],
        max_tokens=1,
        temperature=0.0,
        grammar=grammar,
    )

    print(f"Model: {LLM_MODEL_PATH}")
    print(f"Compact: {COMPACT_SVCS}")
    print(f"Prompts: {len(PROMPTS)}")
    print(f"{'='*80}")

    passed = 0
    total = len(PROMPTS)

    for prompt, expected_svc, expected_cmd in PROMPTS:
        t0 = time.monotonic()
        output = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
            temperature=0.0,
            grammar=grammar,
        )
        elapsed = time.monotonic() - t0
        reply = output['choices'][0]['message']['content']

        ok = check_reply(reply, expected_svc, expected_cmd)
        if ok:
            passed += 1
        status = "OK" if ok else "FAIL"

        expected_str = f'{expected_svc}.{expected_cmd}' if expected_svc else expected_cmd
        print(f"\n  [{status}] ({elapsed:.1f}s) {prompt}")
        print(f"    Got:      {reply}")
        print(f"    Expected: {expected_str}")

    print(f"\n{'='*80}")
    print(f"Score: {passed}/{total} ({100*passed/total:.0f}%)")
    print(f"\n{'='*80}")
    print(f"System context:\n{system_msg}")
