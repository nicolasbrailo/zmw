"""Restrict which files a service opens when a request (MQTT, HTTP) names a path."""
import os
from .logs import build_logger

log = build_logger("PathAllowlist")


class PathAllowlist:
    """
    Checks requested paths against the dirs in the service config's `allowed_paths`.

    Paths are resolved with realpath, so symlinks (eg planted in a shared dir) can't point out of the allowed dirs.
    No `allowed_paths` means nothing is allowed. A rejected path is logged as an error: it's either a misconfig or
    someone probing, and errors in the journal trigger a notification.
    """

    def __init__(self, cfg, feature_name):
        """
        Args:
            cfg: The service config; reads its `allowed_paths` list
            feature_name: What gets disabled without `allowed_paths`, for the logs (eg "send_photo")
        """
        self._feature = feature_name
        self._dirs = [os.path.realpath(d) for d in cfg.get('allowed_paths', [])]
        if not self._dirs:
            log.warning("No 'allowed_paths' in config, %s will reject every path", feature_name)

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
