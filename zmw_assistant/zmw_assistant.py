import pathlib
import os
import threading

from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

log = build_logger("ZmwAssistant")

class ZmwAssistant(ZmwMqttServiceMonitor):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, sched)

        self._ifaces_lock = threading.Lock()
        self._svcs_ifaces = {}

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'))
        www.serve_url('/get_service_interfaces', lambda: self._svcs_ifaces)

    def on_new_svc_discovered(self, svc_name, svc_meta):
        if svc_meta['mqtt_topic'] is None:
            log.debug("Service %s came up, but exposes no MQTT interface. Ignoring.", svc_name)
            return

        def _on_iface(subtopic, iface):
            with self._ifaces_lock:
                log.info("Received interface definition for %s in %s", svc_name, subtopic)
                self._svcs_ifaces[svc_name] = iface

        with self._ifaces_lock:
            topic = f"{svc_meta['mqtt_topic']}/get_mqtt_description"
            self.subscribe_with_cb(f"{topic}_reply", _on_iface)
            log.info("Requesting interface for %s", svc_name)
            self.broadcast(topic, {})

service_runner(ZmwAssistant)
