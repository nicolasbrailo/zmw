"""Helper class for managing snapshots on movement detection."""
import os
from datetime import datetime

from zzmw_lib.logs import build_logger

log = build_logger("SnapOnMovement")


class SnapOnMovement:
    """Manages snapshots when movement is detected, with per-camera subdirectories."""

    def __init__(self, cfg):
        """
        Initialize the snapshot manager from config.

        Args:
            cfg: Configuration dict containing:
                - cam_host: Camera host (used for logging)
                - cam_alias: Camera name (used for subdirectory name)
                - snap_path_on_movement: Base directory for storing snapshots (optional)
                - snap_count_on_movement: Maximum snapshots to keep per camera (default 10)
        """
        self._cam_host = cfg['cam_host']
        self._snaps_enabled = cfg.get('snap_on_movement_enabled')
        self._max_snaps = cfg.get('snap_history_len', 10)
        self._snap_dir = None
        self._last_snap = None
        if not self._snaps_enabled:
            log.info("Cam %s: will not save snapshots on movement.", self._cam_host)
            return

        base_path = cfg.get('snap_path_on_movement')
        if base_path is None:
            log.info("Cam %s: snap_path_on_movement not configured, snapshots disabled", self._cam_host)
            return

        self._snap_dir = os.path.join(base_path, cfg['cam_alias'])
        if not os.path.exists(self._snap_dir):
            try:
                os.makedirs(self._snap_dir)
                log.info("Cam %s: created snapshot directory at %s", self._cam_host, self._snap_dir)
            except OSError as e:
                log.error("Cam %s: failed to create snapshot directory %s: %s", self._cam_host, self._snap_dir, e)
                self._snap_dir = None
                return

        log.info("Cam %s: snapshots will be saved at %s (max %d)", self._cam_host, self._snap_dir, self._max_snaps)

    def is_enabled(self):
        """Check if snapshot saving is enabled."""
        return self._snap_dir is not None

    def save_snapshot(self, snapshot_data):
        """
        Save snapshot data to a new file.

        Args:
            snapshot_data: Binary image data to save

        Returns:
            Path to saved snapshot, or None if disabled/failed
        """
        if not self.is_enabled():
            log.debug("Cam %s: snapshots disabled, skipping save", self._cam_host)
            return None

        if snapshot_data is None:
            log.error("Cam %s: received empty snapshot data", self._cam_host)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = os.path.join(self._snap_dir, f"snap_{timestamp}.jpg")

        log.info("Cam %s: saving snapshot to %s", self._cam_host, fpath)
        try:
            with open(fpath, 'wb') as fp:
                fp.write(snapshot_data)
        except IOError as e:
            log.error("Cam %s: failed to write snapshot to %s: %s", self._cam_host, fpath, e)
            return None

        self._last_snap = fpath
        self._cleanup_old_snaps()
        return fpath

    def get_last_snap(self):
        """Get the path to the most recent snapshot."""
        return self._last_snap

    def get_snap_dir(self):
        """Get the snapshot directory for this camera."""
        return self._snap_dir

    def get_all_snaps(self):
        """Get all snapshots for this camera, sorted newest first."""
        if not self.is_enabled():
            return []

        snaps = []
        try:
            for fname in os.listdir(self._snap_dir):
                if fname.endswith('.jpg'):
                    fpath = os.path.join(self._snap_dir, fname)
                    ftime = os.path.getmtime(fpath)
                    snaps.append((fname, fpath, ftime))
            snaps.sort(key=lambda x: x[2], reverse=True)
        except OSError as e:
            log.error("Cam %s: failed to list snapshots: %s", self._cam_host, e)

        return snaps

    def _cleanup_old_snaps(self):
        """Remove old snapshots if we have more than max_snaps."""
        if not self.is_enabled():
            return

        snaps = self.get_all_snaps()
        if len(snaps) <= self._max_snaps:
            return

        for _, fpath, _ in snaps[self._max_snaps:]:
            try:
                os.remove(fpath)
                log.debug("Cam %s: removed old snapshot %s", self._cam_host, fpath)
            except OSError as e:
                log.error("Cam %s: failed to remove old snapshot %s: %s", self._cam_host, fpath, e)
