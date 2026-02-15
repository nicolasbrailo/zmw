import argparse
import collections
import json
import os
import pathlib
import threading
import time

from flask import request as FlaskRequest

from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

from services_tracker import ServicesTracker, build_gbnf_grammar

log = build_logger("ZmwAssistant")

_LLM_PREAMBLE = """\
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

    def create_chat_completion(self, **kwargs):
        with self._lock:
            if self._llm is None:
                return None
            return self._llm.create_chat_completion(**kwargs)

    def tokenize(self, text_bytes):
        with self._lock:
            if self._llm is None:
                return None
            return self._llm.tokenize(text_bytes)


def _parse_argv_overrides():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--llm-model-path', dest='llm_model_path')
    parser.add_argument('--llm-use-grammar', dest='llm_use_grammar',
                        type=lambda v: v.lower() in ('1', 'true', 'yes'))
    parser.add_argument('--summary-only', action='store_true', default=None)
    args, _ = parser.parse_known_args()
    return {k: v for k, v in vars(args).items() if v is not None}


class ZmwAssistant(ZmwMqttServiceMonitor):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, sched)

        cfg.update(_parse_argv_overrides())

        self._svcs = ServicesTracker(self)
        self._history = collections.deque(maxlen=20)

        self._use_grammar = cfg['llm_use_grammar']
        self._llm = LazyLlama(
            model_path=cfg['llm_model_path'],
            n_ctx=cfg['llm_context_sz'],
            verbose=False,
            # seed=1337, # Uncomment to set a specific seed
            # n_gpu_layers=-1, # Uncomment to use GPU acceleration
        )

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'))
        www.serve_url('/get_service_interfaces', self._svcs.get_svc_ifaces)
        www.serve_url('/get_services_llm_context', self._svcs.get_svcs_llm_context)
        www.serve_url('/update_llm_context', self._update_llm_context)
        www.serve_url('/debug_llm_context', self._debug_llm_context)
        www.serve_url('/assistant_ask', self._assistant_ask, methods=['POST'])
        www.serve_url('/get_history', lambda: list(self._history))

        self.subscribe_with_cb('zmw_speech_to_text', self._on_stt_message)

    def _on_connect(self, client, userdata, flags, ret_code, props):
        super()._on_connect(client, userdata, flags, ret_code, props)
        self._svcs.on_mqtt_connected(client)

    def _on_stt_message(self, subtopic, payload):
        if subtopic != 'transcription':
            return
        text = payload.get('text', '').strip()
        if not text:
            return
        source = payload.get('source', 'stt')
        log.info("STT transcription received: '%s'", text)
        reply, _, _ = self._ask_llm(text)
        log.info("LLM reply: %s", reply)
        exec_result = self._llm_exec(reply, prompt=text)
        if isinstance(exec_result, dict) and exec_result.get('error'):
            self.broadcast('zmw_telegram/send_text', {'msg': exec_result['error']})
        elif exec_result:
            self.broadcast('zmw_telegram/send_text', {
                'msg': json.dumps(exec_result, default=str),
            })
        self._history.append({
            'prompt': text, 'reply': reply, 'exec_result': exec_result,
            'time': time.time(), 'source': source,
        })

    def on_new_svc_discovered(self, svc_name, svc_meta):
        self._svcs.on_new_svc_discovered(svc_name, svc_meta)

    def _update_llm_context(self):
        from flask import redirect
        self._svcs.rediscover_all()
        return redirect('/debug_llm_context')

    def _debug_llm_context(self):
        text = _LLM_PREAMBLE + self._svcs.get_svcs_llm_context()
        grammar = build_gbnf_grammar(self._svcs.get_svc_ifaces())
        tokens = self._llm.tokenize(text.encode())
        token_count = len(tokens) if tokens is not None else "model not loaded"
        return f"<pre>Tokens: {token_count}\n\n{text}\n\nGrammar:\n{grammar}</pre>"

    def _llm_exec(self, llm_reply, prompt=''):
        """Execute an LLM command reply.

        Returns:
            dict with 'error' on failure,
            {} for fire-and-forget commands,
            service response payload for commands with replies,
            None for DONT_KNOW.
        """
        if llm_reply.strip() == 'DONT_KNOW':
            return {'error': f"I don't know how to reply to: {prompt}"}

        try:
            parsed = json.loads(llm_reply)
        except (json.JSONDecodeError, TypeError):
            log.warning("LLM reply is not valid JSON: %s", llm_reply)
            return {'error': f"LLM produced invalid response: {llm_reply}"}

        svc_name = parsed.get('service')
        cmd_name = parsed.get('command')
        args = parsed.get('args', {})

        ifaces = self._svcs.get_svc_ifaces()
        iface = ifaces.get(svc_name)
        if not iface:
            log.warning("Unknown service '%s' in LLM reply", svc_name)
            return {'error': f"Unknown service: {svc_name}"}

        mqtt_topic = iface.get('meta', {}).get('mqtt_topic')
        if not mqtt_topic:
            log.warning("Service '%s' has no mqtt_topic", svc_name)
            return {'error': f"Service {svc_name} has no MQTT topic"}

        expects_reply = f"{cmd_name}_reply" in iface.get('announcements', {})

        log.info("Executing %s.%s(%s)", svc_name, cmd_name, args)

        if not expects_reply:
            self.broadcast(f"{mqtt_topic}/{cmd_name}", args)
            return {}

        reply_topic = f"{mqtt_topic}/{cmd_name}_reply"
        result = {}
        event = threading.Event()

        def _on_reply(_client, _userdata, msg):
            try:
                result['payload'] = json.loads(msg.payload)
            except (json.JSONDecodeError, TypeError):
                result['payload'] = msg.payload.decode('utf-8', errors='replace')
            event.set()

        self.client.message_callback_add(reply_topic, _on_reply)
        self.client.subscribe(reply_topic)
        self.broadcast(f"{mqtt_topic}/{cmd_name}", args)

        got_reply = event.wait(timeout=10)

        self.client.unsubscribe(reply_topic)
        self.client.message_callback_remove(reply_topic)

        if got_reply:
            log.info("Reply from %s.%s: %s", svc_name, cmd_name, result['payload'])
            return result['payload']

        log.warning("Timeout waiting for reply from %s.%s", svc_name, cmd_name)
        return {'error': f"Timeout waiting for {svc_name}.{cmd_name}"}

    def _ask_llm(self, prompt):
        system_msg = _LLM_PREAMBLE + self._svcs.get_svcs_llm_context()

        kwargs = {}
        if self._use_grammar:
            from llama_cpp import LlamaGrammar
            kwargs['grammar'] = LlamaGrammar.from_string(
                build_gbnf_grammar(self._svcs.get_svc_ifaces()))

        output = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
            temperature=0.0,
            **kwargs,
        )
        if output is None:
            reply = "Model not loaded yet"
        else:
            reply = output['choices'][0]['message']['content']
        return reply, system_msg, prompt

    def _assistant_ask(self):
        prompt = FlaskRequest.form.get('prompt', '')
        dry_run = FlaskRequest.form.get('dry_run') == '1'
        reply, system_msg, _ = self._ask_llm(prompt)
        exec_result = None
        if not dry_run:
            exec_result = self._llm_exec(reply, prompt=prompt)
        self._history.append({
            'prompt': prompt, 'reply': reply, 'exec_result': exec_result,
            'time': time.time(), 'source': 'www',
        })
        return (f"<pre>Prompt: {prompt}\n\n</pre>"
                f"<pre>System: {system_msg}\n\n</pre>"
                f"<pre>Reply: {reply}</pre>"
                f"<pre>Result: {json.dumps(exec_result, default=str)}</pre>"
                f"<br><a href='/'>Back</a>")

service_runner(ZmwAssistant)
