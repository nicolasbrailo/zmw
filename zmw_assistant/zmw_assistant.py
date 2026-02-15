import argparse
import os
import pathlib
import threading

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

    def _on_connect(self, client, userdata, flags, ret_code, props):
        super()._on_connect(client, userdata, flags, ret_code, props)
        self._svcs.on_mqtt_connected(client)

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
        reply, system_msg, prompt = self._ask_llm(FlaskRequest.form.get('prompt', ''))
        return (f"<pre>Prompt: {prompt}\n\n</pre>"
                f"<pre>System: {system_msg}\n\n</pre>"
                f"<pre>Reply: {reply}</pre>"
                f"<br><a href='/assistant.html'>Back</a>")

service_runner(ZmwAssistant)
