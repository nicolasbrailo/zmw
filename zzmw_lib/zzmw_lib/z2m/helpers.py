from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

def bind_callbacks_to_z2m_actions(obj, prefix, known_things, global_pre_cb=None):
    """ Bind object methods to Z2M action. For example:
    1. in a network with a thing called 'Button',
    2. where Button has an action 'On',
    calling bind_actions(obj, "z2m_cbs_", things) will search for a method called `obj.z2m_cbs_Button_On`.
    Every time Button.On is triggered over MQTT, this callback will be invoked.

    Returns a tuple with {[methods NOT bound to a thing], [methods bound to a thing]}
    """
    def get_z2m_callback_methods(prefix, obj):
        methods = {}
        for name in dir(obj):
            if name.startswith(prefix):
                f = getattr(obj, name)
                if callable(f):
                    methods[name[len(prefix):]] = f
        return methods

    cbs = get_z2m_callback_methods(prefix, obj)
    unbound_cbs = set(cbs.keys())
    for thing_name, thing in known_things.items():
        # log.debug("Thing %s actions: %s", thing_name, ", ".join(thing.actions.keys()))
        for cb_name in cbs.keys():
            if cb_name == thing_name:
                log.debug("Bind %s.on_any_change_from_mqtt -> %s%s", thing_name, prefix, cb_name)
                thing.on_any_change_from_mqtt = cbs[cb_name]
                unbound_cbs.remove(cb_name)
            elif cb_name.startswith(thing_name):
                for action_name in thing.actions.keys():
                    if cb_name == f'{thing_name}_{action_name}':
                        log.debug("Bind %s.%s -> %s%s", thing_name, action_name, prefix, cb_name)
                        if global_pre_cb:
                            def _wrap(*a, thing_name=thing.name, action=action_name, callback=cbs[cb_name], **kw):
                                global_pre_cb(thing_name, action, *a, **kw)
                                callback(*a, **kw)
                            thing.actions[action_name].value.on_change_from_mqtt = _wrap
                        else:
                            thing.actions[action_name].value.on_change_from_mqtt = cbs[cb_name]
                        unbound_cbs.remove(cb_name)
                        break

    if len(unbound_cbs) != 0:
        log.error("Can't bind actions (%s) to Z2M things. Is Z2M network missing expected things, or are there callbacks that bind to multiple objects?", unbound_cbs)

    return list(unbound_cbs), list(set(cbs.keys()) - unbound_cbs)

