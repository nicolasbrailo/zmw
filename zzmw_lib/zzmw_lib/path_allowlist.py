"""Restrict which files a service opens when a request (MQTT, HTTP) names a path."""
import os
from .logs import build_logger

log = build_logger("PathAllowlist")


class PathAllowlist:
    """
    Checks requested paths against the dirs in the service config's `allowed_paths`.

    Paths are resolved with realpath, so symlinks (eg planted in a shared dir) can't point out of the allowed dirs.
    `allowed_paths` is required (a KeyError at startup if it's missing); empty or null means nothing is allowed. A
    rejected path is logged as an error: it's either a misconfig or someone probing, and errors in the journal trigger a
    notification.
    """

    def __init__(self, cfg, feature_name):
        """
        Args:
            cfg: The service config; reads its `allowed_paths` list
            feature_name: What the paths are for, for the logs (eg "send_photo")
        """
        self._feature = feature_name
        self._dirs = [os.path.realpath(d) for d in cfg['allowed_paths'] or []]
        if not self._dirs:
            log.warning("'allowed_paths' is empty, %s will reject every path", feature_name)
        # Find out now, not when a request first needs it (eg the next doorbell ring)
        for d in self._dirs:
            if not os.path.isdir(d) or not os.access(d, os.R_OK | os.X_OK):
                log.error("%s: allowed_paths has '%s', but it isn't accessible: it doesn't exist, or the service's "
                          "unit doesn't bind it (after changing config.json, make update_units regenerates it)",
                          feature_name, d)

    @property
    def allowed_dirs(self):
        """The resolved allowed dirs."""
        return list(self._dirs)

    def check(self, path):
        """
        Returns the resolved path if it's inside one of the allowed dirs, or None (and logs an error) if not.
        The file isn't required to exist.
        """
        if not isinstance(path, str) or not path:
            log.error("%s: rejected invalid path %r", self._feature, path)
            return None
        resolved = os.path.realpath(path)
        for d in self._dirs:
            if resolved == d or resolved.startswith(d + os.sep):
                return resolved
        log.error("%s: rejected '%s' (resolves to '%s'), not inside allowed_paths %s",
                  self._feature, path, resolved, self._dirs)
        return None
