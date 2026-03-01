from flask import Flask
from flask import redirect
from flask import request as FlaskRequest
from flask import send_from_directory
from flask import url_for
from flask import jsonify
import types
import json

from zzmw_lib.logs import build_logger
log = build_logger("Z2Mwww")

def _make_serializable(obj):
  if isinstance(obj, dict):
      return {k: _make_serializable(v) for k, v in obj.items()}
  elif isinstance(obj, (list, tuple)):
      return [_make_serializable(item) for item in obj]
  elif isinstance(obj, (types.FunctionType, types.LambdaType, types.MethodType, types.BuiltinFunctionType)):
      return str(obj)
  elif isinstance(obj, (str, int, float, bool, type(None))):
      return obj
  else:
      return str(obj)

def _safe_jsonify(cb):
    def _apply_cb(thing_name):
        obj = cb(thing_name)
        return jsonify(_make_serializable(obj))
    return _apply_cb


def _get_request_data():
    """Get request data from form, json, or args - whichever has data."""
    if FlaskRequest.form and len(FlaskRequest.form) > 0:
        return dict(FlaskRequest.form.items())
    json_data = FlaskRequest.get_json(silent=True)
    if json_data:
        return json_data
    if FlaskRequest.args and len(FlaskRequest.args) > 0:
        return dict(FlaskRequest.args.items())
    return None

def _set_props_of_thing(z2m, thing_name, data):
    for key, val in data.items():
        z2m.get_thing(thing_name).set(key, val)

    z2m.broadcast_thing(thing_name)

def _thing_put(z2m, thing_name):
    data = _get_request_data()
    if data is None or len(data) == 0:
        raise RuntimeError('Set prop requires at least one PUT/POST value')

    # Validate all k,v's are valid and exist before applying any. Note values may be empty or non existent
    for key, val in data.items():
        if key is None or len(key) == 0:
            raise RuntimeError(f'Invalid set of PUT/POST values f{key}:f{val}')

    try:
        res = _set_props_of_thing(z2m, thing_name, data)
        return json.dumps(res, default=_make_serializable)
    except KeyError as ex:
        log.warn('User requested non-existing thing. %s', ex, exc_info=True)
        return str(ex), 404
    except AttributeError as ex:
        log.warn('User requested non-existing action for existing thing. %s', ex, exc_info=True)
        return str(ex), 415
    except ValueError as ex:
        log.warn('User attempted to set an invalid value for an action %s', ex, exc_info=True)
        return str(ex), 422
    except RuntimeError as ex:
        log.warn('User request error %s', ex, exc_info=True)
        return str(ex), 400

def _thing_get(z2m, thing_name):
    try:
        return z2m.get_thing(thing_name).get_json_state()
    except KeyError as ex:
        log.warn('User requested non-existing thing. %s', ex, exc_info=True)
        return f"Thing doesn't exist: {ex}", 404
    except AttributeError as ex:
        log.warn('User requested non-existing action for existing thing. %s', ex, exc_info=True)
        return str(ex), 415
    except RuntimeError as ex:
        log.warn('User request error %s', ex, exc_info=True)
        return str(ex), 400

class Z2Mwebservice:
    def __init__(self, www, z2m):
        www.serve_url('/z2m/get_known_things_hash', z2m.get_known_things_hash)
        www.serve_url('/z2m/ls', z2m.get_thing_names)
        www.serve_url('/z2m/get_world', z2m.get_world_state)
        www.serve_url('/z2m/meta/<thing_name>', _safe_jsonify(z2m.get_thing_meta))
        www.serve_url('/z2m/set/<thing_name>', lambda thing_name: _thing_put(z2m, thing_name), ['PUT', 'POST'])
        www.serve_url('/z2m/get/<thing_name>', lambda thing_name: _thing_get(z2m, thing_name))
