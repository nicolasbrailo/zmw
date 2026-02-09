import json
import pathlib
import os
import re
import threading

from zz2m.z2mproxy import Z2MProxy
from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

log = build_logger("ZmwAssistant")


class LazyLlama:
    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._llm = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._load, daemon=True)
        self._thread.start()

    def _load(self):
        from llama_cpp import Llama
        log.info("Loading Llama model '%s'...", self._kwargs.get('model_path'))
        llm = Llama(**self._kwargs)
        with self._lock:
            self._llm = llm
        log.info("Llama model loaded")

    def __call__(self, *args, **kwargs):
        with self._lock:
            if self._llm is None:
                return None
            return self._llm(*args, **kwargs)

    def tokenize(self, text_bytes):
        with self._lock:
            if self._llm is None:
                return None
            return self._llm.tokenize(text_bytes)


_IFACE_REPLY_WILDCARD = "+/get_mqtt_description_reply"


_REPLY_TOPIC_RE = re.compile(r'\s*\.?\s*Response\s+(published\s+)?on\s+\S+\s*$', re.IGNORECASE)


def _strip_reply_suffix(description):
    """Strip 'Response on X_reply' / 'Response published on X' suffixes."""
    return _REPLY_TOPIC_RE.sub('', description)


def compact_ifaces_for_llm(svcs_ifaces):
    """Compact service interface descriptions into a short text format for LLM context.

    Strips announcements, reply schemas, and metadata. Keeps only service descriptions
    and commands with their parameters."""
    lines = []
    for svc_name, iface in sorted(svcs_ifaces.items()):
        lines.append(f"## {svc_name}")
        if iface.get('description'):
            lines.append(iface['description'])
        commands = iface.get('commands', {})
        if commands:
            lines.append("Commands:")
            for cmd_name, cmd in sorted(commands.items()):
                if cmd_name == 'get_mqtt_description':
                    continue
                params = cmd.get('params', {})
                desc = _strip_reply_suffix(cmd.get('description', ''))
                if params:
                    param_parts = []
                    for p_name, p_desc in params.items():
                        optional = '(optional)' in str(p_desc).lower() if p_desc else False
                        param_parts.append(f"{p_name}?" if optional else p_name)
                    params_str = ', '.join(param_parts)
                    lines.append(f"- {cmd_name}({params_str}): {desc}")
                else:
                    lines.append(f"- {cmd_name}: {desc}")
        lines.append("")
    return '\n'.join(lines)

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


class ZmwAssistant(ZmwMqttServiceMonitor):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, sched)

        self._ifaces_lock = threading.Lock()
        self._svcs_ifaces = {}
        self._z2m = Z2MProxy(cfg, self, sched)

        self._llm = LazyLlama(
            model_path=cfg['llm_model_path'],
            n_ctx=cfg['llm_context_sz'],
            # seed=1337, # Uncomment to set a specific seed
            # n_gpu_layers=-1, # Uncomment to use GPU acceleration
        )

        # Use paho's per-topic callback for wildcard matching (subscribe_with_cb
        # only does prefix matching, which doesn't support MQTT '+' wildcards)
        # Since this is the only service that needs this, it's not part of ZmwMqttServiceMonitor
        self.client.message_callback_add(_IFACE_REPLY_WILDCARD, self._on_iface_reply)

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'))
        www.serve_url('/get_service_interfaces', lambda: self._svcs_ifaces)
        www.serve_url('/get_service_interfaces_for_llm', self._get_ifaces_for_llm)
        www.serve_url('/debug_llm_context', self._debug_llm_context)
        www.serve_url('/debug_z2m_context', self._debug_z2m_context)
        www.serve_url('/debug_services_context', self._debug_services_context)
        www.serve_url('/foo', self._foo)

    def _on_connect(self, client, userdata, flags, ret_code, props):
        super()._on_connect(client, userdata, flags, ret_code, props)
        client.subscribe(_IFACE_REPLY_WILDCARD, qos=1)

    def _on_iface_reply(self, _client, _userdata, msg):
        try:
            iface = json.loads(msg.payload)
        except (TypeError, json.JSONDecodeError):
            log.warning("Ignoring non-json interface reply on '%s'", msg.topic)
            return

        # Topic is "{svc_mqtt_topic}/get_mqtt_description_reply"
        svc_topic = msg.topic.rsplit("/get_mqtt_description_reply", 1)[0]
        with self._ifaces_lock:
            svc_name = None
            for name, meta in self._all_services_ever_seen.items():
                if meta.get('mqtt_topic') == svc_topic:
                    svc_name = name
                    break
            if svc_name:
                log.info("Received interface definition for %s", svc_name)
                self._svcs_ifaces[svc_name] = iface
            else:
                log.warning("Received interface reply from unknown topic '%s'", svc_topic)

    def on_new_svc_discovered(self, svc_name, svc_meta):
        if svc_meta.get('mqtt_topic') is None:
            log.debug("Service %s came up, but exposes no MQTT interface. Ignoring.", svc_name)
            return

        topic = f"{svc_meta['mqtt_topic']}/get_mqtt_description"
        log.info("Requesting interface for %s", svc_name)
        self.broadcast(topic, {})

    def _get_ifaces_for_llm(self):
        with self._ifaces_lock:
            return compact_ifaces_for_llm(self._svcs_ifaces)

    def _debug_services_context(self):
        with self._ifaces_lock:
            text = compact_ifaces_for_llm(self._svcs_ifaces)
        tokens = self._llm.tokenize(text.encode())
        token_count = len(tokens) if tokens is not None else "model not loaded"
        return f"<pre>Tokens: {token_count}\n\n{text}</pre>"

    def _debug_z2m_context(self):
        things = self._z2m.get_all_registered_things()
        text = compact_z2m_things_for_llm(things)
        tokens = self._llm.tokenize(text.encode())
        token_count = len(tokens) if tokens is not None else "model not loaded"
        return f"<pre>Tokens: {token_count}\n\n{text}</pre>"

    def _debug_llm_context(self):
        with self._ifaces_lock:
            svc_text = compact_ifaces_for_llm(self._svcs_ifaces)
        things = self._z2m.get_all_registered_things()
        z2m_text = compact_z2m_things_for_llm(things)
        text = svc_text + "\n" + z2m_text
        tokens = self._llm.tokenize(text.encode())
        token_count = len(tokens) if tokens is not None else "model not loaded"
        return f"<pre>Tokens: {token_count}\n\n{text}</pre>"

    def _foo(self):
        output = self._llm(
              "Q: What color us the sky in Jupiter? A: ", # Prompt
              max_tokens=32, # Generate up to 32 tokens, set to None to generate up to the end of the context window
              stop=["Q:", "\n"], # Stop generating just before the model would generate a new question
              echo=True # Echo the prompt back in the output
        )
        return output

service_runner(ZmwAssistant)
