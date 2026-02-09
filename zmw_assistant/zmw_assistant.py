import json
import pathlib
import os
import threading

from flask import request as FlaskRequest

from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

from services_tracker import ServicesTracker
from z2m_tracker import Z2mTracker

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
        www.serve_url('/foo', self._foo)

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

    def _assistant_ask(self):
        prompt = FlaskRequest.form.get('prompt', '')
        output = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        if output is None:
            reply = "Model not loaded yet"
        else:
            reply = output['choices'][0]['message']['content']
        return (f"<pre>Prompt: {prompt}\n\nReply: {reply}</pre>"
                f"<br><a href='/assistant.html'>Back</a>")

    def _foo(self):
        output = self._llm(
              "Q: What color us the sky in Jupiter? A: ", # Prompt
              max_tokens=32, # Generate up to 32 tokens, set to None to generate up to the end of the context window
              stop=["Q:", "\n"], # Stop generating just before the model would generate a new question
              echo=True # Echo the prompt back in the output
        )
        return output

service_runner(ZmwAssistant)
