import json
import re
import threading

from zzmw_lib.logs import build_logger
log = build_logger("ZmwAssistantSvcTracker")


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

    def get_svc_ifaces(self):
        with self._ifaces_lock:
            return self._svcs_ifaces

    def get_svcs_llm_context(self):
        with self._ifaces_lock:
            return compact_ifaces_for_llm(self._svcs_ifaces)


