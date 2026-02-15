import json
import re
import threading

from zzmw_lib.logs import build_logger
log = build_logger("ZmwAssistantSvcTracker")


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


def _build_service_keywords(svc_name, iface):
    """Build a searchable text blob for a service from its name, description, and commands."""
    parts = []
    # Split CamelCase name into words (e.g. "ZmwLights" -> "zmw lights")
    parts.append(' '.join(_CAMEL_SPLIT_RE.split(svc_name)).lower())
    if iface.get('description'):
        parts.append(iface['description'].lower())
    for cmd_name, cmd in iface.get('commands', {}).items():
        parts.append(cmd_name.replace('_', ' ').lower())
        if cmd.get('description'):
            parts.append(cmd['description'].lower())
    return ' '.join(parts)


def _tokenize_query(user_query):
    """Tokenize and filter a user query: lowercase, strip punctuation, remove stopwords."""
    words = re.findall(r'[a-z0-9]+', user_query.lower())
    return [w for w in words if w not in _STOPWORDS]


def _normalize_word(w):
    """Strip punctuation and trailing 's' for basic stemming."""
    w = re.sub(r'[^a-z0-9]', '', w)
    if len(w) > 3 and w.endswith('s'):
        w = w[:-1]
    return w


def _score_keywords(query_words, keywords_text):
    """Count how many query words appear as whole words in the keywords text."""
    kw_words = set(_normalize_word(w) for w in keywords_text.split() if w)
    return sum(1 for w in query_words if _normalize_word(w) in kw_words)


def _gbnf_lit(text):
    """Escape a plain string for use as a GBNF quoted literal."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _get_required_params(params):
    """Extract required (non-optional) param names from a command's params dict."""
    required = []
    for p_name, p_desc in params.items():
        is_optional = (p_name.endswith('?')
                       or ('(optional)' in str(p_desc).lower() if p_desc else False))
        if not is_optional:
            required.append(p_name)
    return required


def build_gbnf_grammar(svcs_ifaces):
    """Build a GBNF grammar constraining LLM output to valid service commands or DONT_KNOW.

    The grammar is dynamically generated from discovered service interfaces,
    so only real service names, command names, and arg structures are valid output."""
    svc_rule_names = []
    rules = []

    for svc_name, iface in sorted(svcs_ifaces.items()):
        commands = iface.get('commands', {})
        if not commands:
            continue

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
                # Build GBNF with val slots: literal "...prefix..." val literal "...suffix..."
                parts = []
                prefix = f'{{"service": "{svc_name}", "command": "{cmd_name}", "args": {{'
                for i, p in enumerate(required_params):
                    if i > 0:
                        prefix += ', '
                    prefix += f'"{p}": "'
                    parts.append(_gbnf_lit(prefix))
                    parts.append('val')
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

    def get_svcs_llm_context_filtered(self, user_query, max_results=3):
        """Return (compact_text, filtered_ifaces_dict) for services relevant to user_query."""
        query_words = _tokenize_query(user_query)
        if not query_words:
            with self._ifaces_lock:
                all_ifaces = dict(self._svcs_ifaces)
            return self.get_svcs_llm_context(), all_ifaces

        with self._ifaces_lock:
            scored = []
            for svc_name, iface in self._svcs_ifaces.items():
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


