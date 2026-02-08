import json
import pathlib
import os
import threading

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


_IFACE_REPLY_WILDCARD = "+/get_mqtt_description_reply"

class ZmwAssistant(ZmwMqttServiceMonitor):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, sched)

        self._ifaces_lock = threading.Lock()
        self._svcs_ifaces = {}
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

    def _foo(self):
        output = self._llm(
              "Q: What color us the sky in Jupiter? A: ", # Prompt
              max_tokens=32, # Generate up to 32 tokens, set to None to generate up to the end of the context window
              stop=["Q:", "\n"], # Stop generating just before the model would generate a new question
              echo=True # Echo the prompt back in the output
        )
        return output

service_runner(ZmwAssistant)
