"""Door statistics tracking for ZmwDoorman service."""
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set
from zzmw_lib.logs import build_logger

log = build_logger("DoorStats")


@dataclass
class DoorbellPressRecord:
    """Record of a doorbell press event."""
    timestamp: float
    snap_path: Optional[str] = None


@dataclass
class MotionEventRecord:
    """Record of a motion detection event."""
    start_time: float
    duration_secs: Optional[float] = None
    snap_path: Optional[str] = None


@dataclass
class VisitorRecord:
    """Record of a visitor notification (from ZmwVisitorDetect's events)."""
    timestamp: float
    msg: str
    session_id: Optional[str] = None


@dataclass
class DoorOpenRecord:
    """Record of a door open event."""
    start_time: float
    duration_secs: Optional[float] = None


class DoorStats:
    """Tracks statistics for doorbell, motion, and door events."""

    MAX_HISTORY_SIZE = 10
    STATE_KEY = "door_stats"

    def __init__(self, sched):
        self._sched = sched

        # Track in-progress events (not persisted)
        self._motion_in_progress: Optional[MotionEventRecord] = None
        self._door_open_in_progress: Optional[DoorOpenRecord] = None

        # Load persisted state or initialize fresh
        self._load_state()

        # Schedule nightly reset at midnight
        sched.add_job(
            self._nightly_reset,
            trigger=CronTrigger(hour=0, minute=0, second=0),
            id='door_stats_nightly_reset'
        )
        log.info("DoorStats initialized, nightly reset scheduled for midnight")

    def _load_state(self):
        """Load state from cache or initialize fresh."""
        cached = runtime_state_cache_get(self.STATE_KEY)
        today = date.today().isoformat()

        if cached:
            # Check if daily counters need reset (different day)
            if cached.get("counters_date") == today:
                self._doorbell_press_count_today = cached.get("doorbell_press_count_today", 0)
                self._motion_detection_count_today = cached.get("motion_detection_count_today", 0)
                self._visitor_count_today = cached.get("visitor_count_today", 0)
            else:
                self._doorbell_press_count_today = 0
                self._motion_detection_count_today = 0
                self._visitor_count_today = 0

            self._counters_date = today
            self._last_snap_path = cached.get("last_snap_path")
            self._last_snap_time = cached.get("last_snap_time")

            # Restore histories
            self._doorbell_presses = deque(
                (DoorbellPressRecord(timestamp=r["timestamp"], snap_path=r.get("snap_path"))
                 for r in cached.get("doorbell_presses", [])),
                maxlen=self.MAX_HISTORY_SIZE
            )
            self._motion_events = deque(
                (MotionEventRecord(start_time=r["start_time"], duration_secs=r.get("duration_secs"),
                                   snap_path=r.get("snap_path"))
                 for r in cached.get("motion_events", [])),
                maxlen=self.MAX_HISTORY_SIZE
            )
            self._door_open_events = deque(
                (DoorOpenRecord(start_time=r["start_time"], duration_secs=r.get("duration_secs"))
                 for r in cached.get("door_open_events", [])),
                maxlen=self.MAX_HISTORY_SIZE
            )
            self._visitors = deque(
                (VisitorRecord(timestamp=r["timestamp"], msg=r["msg"], session_id=r.get("session_id"))
                 for r in cached.get("visitors", [])),
                maxlen=self.MAX_HISTORY_SIZE
            )
            log.info("Restored state from cache: %d doorbell presses, %d motion events, %d door events",
                     len(self._doorbell_presses), len(self._motion_events), len(self._door_open_events))
        else:
            self._doorbell_press_count_today = 0
            self._motion_detection_count_today = 0
            self._visitor_count_today = 0
            self._counters_date = today
            self._last_snap_path = None
            self._last_snap_time = None
            self._doorbell_presses = deque(maxlen=self.MAX_HISTORY_SIZE)
            self._motion_events = deque(maxlen=self.MAX_HISTORY_SIZE)
            self._door_open_events = deque(maxlen=self.MAX_HISTORY_SIZE)
            self._visitors = deque(maxlen=self.MAX_HISTORY_SIZE)

    def _save_state(self):
        """Save current state to cache."""
        state = {
            "counters_date": self._counters_date,
            "doorbell_press_count_today": self._doorbell_press_count_today,
            "motion_detection_count_today": self._motion_detection_count_today,
            "visitor_count_today": self._visitor_count_today,
            "last_snap_path": self._last_snap_path,
            "last_snap_time": self._last_snap_time,
            "doorbell_presses": [
                {"timestamp": r.timestamp, "snap_path": r.snap_path}
                for r in self._doorbell_presses
            ],
            "motion_events": [
                {"start_time": r.start_time, "duration_secs": r.duration_secs, "snap_path": r.snap_path}
                for r in self._motion_events
            ],
            "door_open_events": [
                {"start_time": r.start_time, "duration_secs": r.duration_secs}
                for r in self._door_open_events
            ],
            "visitors": [
                {"timestamp": r.timestamp, "msg": r.msg, "session_id": r.session_id}
                for r in self._visitors
            ],
        }
        runtime_state_cache_set(self.STATE_KEY, state)

    def _nightly_reset(self):
        """Reset daily counters at midnight."""
        log.info("Nightly reset: doorbell_presses=%d, motion_detections=%d",
                 self._doorbell_press_count_today, self._motion_detection_count_today)
        self._doorbell_press_count_today = 0
        self._motion_detection_count_today = 0
        self._visitor_count_today = 0
        self._counters_date = date.today().isoformat()
        self._save_state()

    def record_doorbell_press(self, snap_path: Optional[str] = None):
        """Record a doorbell press event."""
        self._doorbell_press_count_today += 1
        record = DoorbellPressRecord(timestamp=time.time(), snap_path=snap_path)
        self._doorbell_presses.append(record)
        if snap_path:
            self._last_snap_path = snap_path
        log.debug("Recorded doorbell press #%d today, snap_path=%s",
                  self._doorbell_press_count_today, snap_path)
        self._save_state()

    def record_motion_start(self, snap_path: Optional[str] = None):
        """Record the start of a motion detection event."""
        self._motion_detection_count_today += 1
        self._motion_in_progress = MotionEventRecord(start_time=time.time(), snap_path=snap_path)
        log.debug("Motion started, #%d today, snap_path=%s", self._motion_detection_count_today, snap_path)
        self._save_state()

    def record_motion_end(self):
        """Record the end of a motion detection event."""
        if self._motion_in_progress is None:
            log.warning("Motion end called but no motion in progress")
            return
        self._motion_in_progress.duration_secs = time.time() - self._motion_in_progress.start_time
        self._motion_events.append(self._motion_in_progress)
        log.debug("Motion ended, duration=%.1f secs", self._motion_in_progress.duration_secs)
        self._motion_in_progress = None
        self._save_state()

    def record_door_open(self):
        """Record the start of a door open event."""
        if self._door_open_in_progress is not None:
            log.warning("Door open called but previous door open event not closed")
            self.record_door_close()
        self._door_open_in_progress = DoorOpenRecord(start_time=time.time())
        log.debug("Door opened")
        self._save_state()

    def record_door_close(self):
        """Record the end of a door open event."""
        if self._door_open_in_progress is None:
            log.warning("Door close called but no door open in progress")
            return
        self._door_open_in_progress.duration_secs = time.time() - self._door_open_in_progress.start_time
        self._door_open_events.append(self._door_open_in_progress)
        log.debug("Door closed, duration=%.1f secs", self._door_open_in_progress.duration_secs)
        self._door_open_in_progress = None
        self._save_state()

    def record_visitor(self, msg: str, session_id: Optional[str] = None):
        """Record a visitor notification. session_id is ZmwVisitorDetect's session, which its UI can show."""
        self._visitor_count_today += 1
        self._visitors.append(VisitorRecord(timestamp=time.time(), msg=msg, session_id=session_id))
        log.debug("Recorded visitor #%d today: %s (session %s)", self._visitor_count_today, msg, session_id)
        self._save_state()

    def record_snap(self, snap_path: str):
        """Record a snap path (from any source)."""
        self._last_snap_path = snap_path
        self._last_snap_time = time.time()
        log.debug("Recorded snap_path=%s", snap_path)
        self._save_state()

    def get_last_snap_path(self) -> Optional[str]:
        """Return the full path to the last snap, or None if not available."""
        return self._last_snap_path

    @staticmethod
    def _path_to_filename(path: Optional[str]) -> Optional[str]:
        """Convert a full path to just the filename."""
        if path is None:
            return None
        return os.path.basename(path)

    def get_stats(self) -> dict:
        """Return current statistics as a dictionary."""
        # Build combined history
        history = []
        for r in self._doorbell_presses:
            history.append({
                "event_type": "doorbell",
                "time": r.timestamp,
                "snap": self._path_to_filename(r.snap_path),
            })
        for r in self._motion_events:
            history.append({
                "event_type": "motion",
                "time": r.start_time,
                "duration_secs": r.duration_secs,
                "snap": self._path_to_filename(r.snap_path),
            })
        for r in self._door_open_events:
            history.append({
                "event_type": "door_open",
                "time": r.start_time,
                "duration_secs": r.duration_secs,
            })
        for r in self._visitors:
            history.append({
                "event_type": "visitor",
                "time": r.timestamp,
                "msg": r.msg,
                "session_id": r.session_id,
            })
        history.sort(key=lambda e: e["time"], reverse=True)

        return {
            "doorbell_press_count_today": self._doorbell_press_count_today,
            "motion_detection_count_today": self._motion_detection_count_today,
            "visitor_count_today": self._visitor_count_today,
            "last_snap": self._path_to_filename(self._last_snap_path),
            "last_snap_time": self._last_snap_time,
            "history": history,
            "doorbell_presses": [
                {"timestamp": r.timestamp, "snap": self._path_to_filename(r.snap_path)}
                for r in self._doorbell_presses
            ],
            "motion_events": [
                {"start_time": r.start_time, "duration_secs": r.duration_secs,
                 "snap": self._path_to_filename(r.snap_path)}
                for r in self._motion_events
            ],
            "door_open_events": [
                {"start_time": r.start_time, "duration_secs": r.duration_secs}
                for r in self._door_open_events
            ],
            "visitors": [
                {"timestamp": r.timestamp, "msg": r.msg, "session_id": r.session_id}
                for r in self._visitors
            ],
            "motion_in_progress": self._motion_in_progress is not None,
            "door_open_in_progress": self._door_open_in_progress is not None,
        }
