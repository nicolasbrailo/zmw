import json
import re
import threading

from zzmw_lib.logs import build_logger
log = build_logger("ZmwAssistantSvcTracker")


_SKIP_SERVICES = {'ZmwDoorman', 'ZmwShellyPlug', 'ZmwSpeechToText', 'ZmwTelegram', 'ZmwWhatsapp'}

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
        if svc_name in _SKIP_SERVICES:
            continue
        lines.append(f"## {svc_name}")
        if iface.get('description'):
            lines.append(iface['description'])
        if iface.get('llm_context_extra'):
            lines.append(iface['llm_context_extra'])
        commands = iface.get('commands', {})
        if commands:
            lines.append("Commands:")
            skip_cmds = set(iface.get('llm_skip_commands', []))
            for cmd_name, cmd in sorted(commands.items()):
                if cmd_name == 'get_mqtt_description' or cmd_name in skip_cmds:
                    continue
                params = cmd.get('params', {})
                desc = _strip_reply_suffix(cmd.get('description', ''))
                param_names = [p.rstrip('?') for p in params if p != '?']
                if param_names:
                    params_str = ', '.join(param_names)
                    lines.append(f"- {cmd_name}({params_str}): {desc}")
                else:
                    lines.append(f"- {cmd_name}: {desc}")
        lines.append("")
    return '\n'.join(lines)



def _gbnf_lit(text):
    """Escape a plain string for use as a GBNF quoted literal."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _get_params(params):
    """Classify params into required and optional lists (names with '?' stripped)."""
    required = []
    optional = []
    for p_name, p_desc in params.items():
        is_optional = (p_name.endswith('?')
                       or ('(optional)' in str(p_desc).lower() if p_desc else False))
        clean_name = p_name.rstrip('?')
        if is_optional:
            optional.append(clean_name)
        else:
            required.append(clean_name)
    return required, optional


def build_gbnf_grammar(svcs_ifaces):
    """Build a GBNF grammar constraining LLM output to valid service commands or DONT_KNOW.

    The grammar is dynamically generated from discovered service interfaces,
    so only real service names, command names, and arg structures are valid output."""
    svc_rule_names = []
    rules = []
    needs_val = False

    for svc_name, iface in sorted(svcs_ifaces.items()):
        if svc_name in _SKIP_SERVICES:
            continue
        commands = iface.get('commands', {})
        if not commands:
            continue

        param_values = iface.get('llm_grammar_values', {})
        skip_cmds = set(iface.get('llm_skip_commands', []))
        rule_name = 'svc-' + re.sub(r'[^a-zA-Z0-9]', '-', svc_name)
        cmd_alts = []

        for cmd_name, cmd in sorted(commands.items()):
            if cmd_name == 'get_mqtt_description' or cmd_name in skip_cmds:
                continue

            required, optional = _get_params(cmd.get('params', {}))
            all_params = required + optional

            def _build_args_alt(param_list):
                if not param_list:
                    return _gbnf_lit(f'{{"service": "{svc_name}", "command": "{cmd_name}", "args": {{}}}}')
                parts = []
                pfx = f'{{"service": "{svc_name}", "command": "{cmd_name}", "args": {{'
                for i, p in enumerate(param_list):
                    if i > 0:
                        pfx += ', '
                    pfx += f'"{p}": "'
                    parts.append(_gbnf_lit(pfx))
                    known = param_values.get(p)
                    if known:
                        parts.append('(' + ' | '.join(_gbnf_lit(v) for v in known) + ')')
                    else:
                        parts.append('val')
                        nonlocal needs_val
                        needs_val = True
                    pfx = '"'
                pfx += '}}'
                parts.append(_gbnf_lit(pfx))
                return ' '.join(parts)

            # Always allow the full-params version
            cmd_alts.append(_build_args_alt(all_params))
            # If there are optional params, also allow required-only (or empty args)
            if optional:
                cmd_alts.append(_build_args_alt(required))

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


_IFACE_REPLY_WILDCARD = "+/get_mqtt_description_reply"

class ServicesTracker:
    def __init__(self, mqtt_client):
        # Use paho's per-topic callback for wildcard matching (subscribe_with_cb
        # only does prefix matching, which doesn't support MQTT '+' wildcards)
        # Hacky, but since this is the only service that needs this, it's not part of ZmwMqttServiceMonitor
        mqtt_client.client.message_callback_add(_IFACE_REPLY_WILDCARD, self._on_iface_published)

        self.mqtt_client = mqtt_client
        self._ifaces_lock = threading.Lock()
        self._svcs_ifaces = {}

    def on_mqtt_connected(self, client):
        # It's important to subscribe here: the subscription to a topic is async, so if
        # we subscribe when the first service is discovered, we'll miss responses
        client.subscribe(_IFACE_REPLY_WILDCARD, qos=1)

    def on_new_svc_discovered(self, svc_name, svc_meta):
        if svc_meta.get('mqtt_topic') is None:
            log.debug("Service %s came up, but exposes no MQTT interface. Ignoring.", svc_name)
            return

        log.info("Requesting interface for %s", svc_name)
        self.mqtt_client.broadcast(f"{svc_meta['mqtt_topic']}/get_mqtt_description", {})

    def _on_iface_published(self, _client, _userdata, msg):
        try:
            iface = json.loads(msg.payload)
        except (TypeError, json.JSONDecodeError):
            log.warning("Ignoring non-json interface reply on '%s'", msg.topic)
            return

        if "meta" not in iface or "name" not in iface["meta"]:
            log.warning("Ignoring service with unknown meta format in '%s'", msg.topic)
            return

        with self._ifaces_lock:
            svc_name = iface["meta"]["name"]
            log.info("Received interface definition for %s", svc_name)
            self._svcs_ifaces[svc_name] = iface

    def rediscover_all(self):
        """Re-request interface definitions from all known services."""
        with self._ifaces_lock:
            ifaces = dict(self._svcs_ifaces)
        for svc_name, iface in ifaces.items():
            meta = iface.get('meta', {})
            mqtt_topic = meta.get('mqtt_topic')
            if mqtt_topic:
                log.info("Re-requesting interface for %s", svc_name)
                self.mqtt_client.broadcast(f"{mqtt_topic}/get_mqtt_description", {})

    def get_svc_ifaces(self):
        with self._ifaces_lock:
            return self._svcs_ifaces

    def get_svcs_llm_context(self):
        with self._ifaces_lock:
            return compact_ifaces_for_llm(self._svcs_ifaces)


