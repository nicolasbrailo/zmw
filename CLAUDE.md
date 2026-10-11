# ZMW (zigbee2mqtt2web)

A set of generic home automation services talking over MQTT, each with a small web UI. Despite the name, not
just Zigbee: lights, sensors, heating, Sonos, Spotify, cameras, Telegram, TTS/STT, a local LLM assistant, etc.
See `README.md` for the list, the architecture and the MQTT topic map. Part of baticasa (see `../CLAUDE.md`).

## Layout

- `zzmw_lib/`: shared lib. Service base classes (`zzmw_lib/*mqtt*`), `service_runner`, web helpers (`www/`),
  and `z2m/`: the device proxy. `Z2MProxy` reads both `zigbee2mqtt` and `matter2mqtt` topics by default, so
  Zigbee vs Matter is transparent to services.
- `zmw_<name>/`: one service each; entry point is `zmw_<name>/zmw_<name>.py`, UI in `www/app.js`.
- `common.mk`: shared Makefile targets (`devrun`, `test`, `rebuild_ui`, `install_svc`, ...).
- `scripts/`: install/ops helpers, README/MQTT map generators.

## Rules

- `zzmw_lib` is also used by `../baticasa`: grep it too when changing lib APIs.
- Service READMEs are regenerated from `get_mqtt_description()`; everything after `## MQTT` is overwritten.
  Keep prose above it.
- Don't run tests or `make rebuild_ui` on the dev machine; edit `www/app.js` only, never the built bundles.
- Don't read `config.json` / token caches: they hold live credentials. Use `config.json.example`.
- New deps go in the service's Pipfile / `rebuild_deps` target; don't probe local packages.
