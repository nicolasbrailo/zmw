import json
import os
import pathlib
import signal
import sys
import time
import threading

from flask import request as FlaskRequest

from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

from services_tracker import ServicesTracker
from z2m_tracker import Z2mTracker

log = build_logger("ZmwAssistant")

_LLM_PREAMBLE = """\
You are a home assistant. Respond ONLY with a JSON command or DONT_KNOW.

Examples:
User: turn on the living room lights
{"service": "ZmwLights", "command": "all_lights_on", "args": {"prefix": "LivingRoom"}}
User: what song is playing
{"service": "ZmwSpotify", "command": "get_status", "args": {}}
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


class ZmwAssistant(ZmwMqttServiceMonitor):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, sched)

        self._svcs = ServicesTracker(self)
        self._zigbee_things = Z2mTracker(cfg, self, sched)

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
        www.serve_url('/get_z2m_llm_context', self._zigbee_things.get_z2m_llm_context)
        www.serve_url('/debug_llm_context', self._debug_llm_context)
        www.serve_url('/assistant_ask', self._assistant_ask, methods=['POST'])

        threading.Thread(target=_run_benchmark, args=(self,), daemon=True).start()

    def _on_connect(self, client, userdata, flags, ret_code, props):
        super()._on_connect(client, userdata, flags, ret_code, props)
        self._svcs.on_mqtt_connected(client)

    def on_new_svc_discovered(self, svc_name, svc_meta):
        self._svcs.on_new_svc_discovered(svc_name, svc_meta)

    def _debug_llm_context(self):
        svc_text = self._svcs.get_svcs_llm_context()
        z2m_text = self._zigbee_things.get_z2m_llm_context()
        text = svc_text + "\n" + z2m_text
        tokens = self._llm.tokenize(text.encode())
        token_count = len(tokens) if tokens is not None else "model not loaded"
        return f"<pre>Tokens: {token_count}\n\n{text}</pre>"

    def _ask_llm(self, prompt):
        svc_context = self._svcs.get_svcs_llm_context_filtered(prompt)
        z2m_context = self._zigbee_things.get_z2m_llm_context_filtered(prompt)
        system_msg = _LLM_PREAMBLE + svc_context + "\n" + z2m_context
        output = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
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

_BENCHMARK_QUERIES = [
    ("feed the cat",
     '{"service": "ZmwCatSnackDispenser", "command": "feed_now", "args": {}}'),
    ("did the cat eat today?",
     '{"service": "ZmwCatSnackDispenser", "command": "get_history", "args": {}}'),
    ("turn kitchen lights on",
     '{"service": "ZmwLights", "command": "all_lights_on", "args": {"prefix": "kitchen"}}'),
    ("turn kitchen lights off",
     '{"service": "ZmwLights", "command": "all_lights_off", "args": {"prefix": "kitchen"}}'),
    ("what music is playing?",
     '{"service": "ZmwSpotify", "command": "get_status", "args": {}}'),
    ("stop music",
     '{"service": "ZmwSpotify", "command": "stop", "args": {}}'),
    ("is the door open?",
     '{"service": "ZmwContactmon", "command": "publish_state", "args": {}}'),
]


def _run_benchmark(assistant, delay=2):
    time.sleep(delay)
    log.info("Starting LLM benchmark (%d queries)...", len(_BENCHMARK_QUERIES))
    results = []
    for query, expected in _BENCHMARK_QUERIES:
        reply, system_msg, prompt = assistant._ask_llm(query)
        results.append({"prompt": prompt, "expected": expected, "system_msg": system_msg, "reply": reply})

    print("\n" + "=" * 60)
    print("LLM BENCHMARK RESULTS")
    print("=" * 60)
    print(f"""
The following are benchmark results for a small local LLM used as a home assistant.
The LLM receives a system message with available services and a user prompt.
It should respond with a JSON command or DONT_KNOW.

Expected JSON format: {{"service": "...", "command": "...", "args": {{...}}}}

Preamble (included at the start of every system message):
```
{_LLM_PREAMBLE}```
""")
    for i, r in enumerate(results, 1):
        print(f"--- Test {i}/{len(results)} ---")
        print(f"Prompt: {r['prompt']}")
        print(f"Expected: {r['expected']}")
        print(f"Reply: {r['reply']}")
        print(f"System message (after preamble):")
        # Strip preamble from system_msg since it's already shown above
        context = r['system_msg'][len(_LLM_PREAMBLE):]
        print(f"```\n{context}```")
        print()
    print("--- SUMMARY ---")
    for r in results:
        match = "PASS" if r['reply'].strip() == r['expected'] else "FAIL"
        print(f"[{match}] {r['prompt']}")
        print(f"  expected: {r['expected']}")
        print(f"  got:      {r['reply']}")
    print()
    print("=" * 60)
    print("END BENCHMARK")
    print("=" * 60 + "\n")
    sys.stdout.flush()
    time.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)


service_runner(ZmwAssistant)
