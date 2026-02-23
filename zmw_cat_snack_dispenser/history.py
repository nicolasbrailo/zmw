from collections import deque
from datetime import datetime
import threading

from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("DispensingHistory")

class DispensingHistory:
    def __init__(self, cat_feeder_name, history_len, cb_on_dispense):
        self._cat_feeder_name = cat_feeder_name
        self._history_len = history_len
        self._feed_history = deque(maxlen=history_len)
        self._last_dispense_request_id = 0
        self._dispense_ack_timeout = 15
        self._pending_dispense_timeout_job = None
        self._notify_dispense_event = cb_on_dispense

        self._state_key = f"dispensing_history_{cat_feeder_name}"
        self._load_state()

    def get_history(self):
        return list(self._feed_history)

    def _load_state(self):
        """Load history from cache."""
        cached = runtime_state_cache_get(self._state_key)
        if not cached:
            return

        self._last_dispense_request_id = cached.get("last_dispense_request_id", 0)
        history_entries = cached.get("feed_history", [])

        for entry in history_entries:
            # Deserialize datetime fields
            restored = dict(entry)
            if restored.get("time_requested"):
                restored["time_requested"] = datetime.fromisoformat(restored["time_requested"])
            if restored.get("time_acknowledged"):
                restored["time_acknowledged"] = datetime.fromisoformat(restored["time_acknowledged"])
            self._feed_history.append(restored)

        log.info("Restored %d history entries from cache", len(self._feed_history))

    def _save_state(self):
        """Save history to cache."""
        serialized_history = []
        for entry in self._feed_history:
            serialized = dict(entry)
            # Serialize datetime fields
            if serialized.get("time_requested"):
                serialized["time_requested"] = serialized["time_requested"].isoformat()
            if serialized.get("time_acknowledged"):
                serialized["time_acknowledged"] = serialized["time_acknowledged"].isoformat()
            serialized_history.append(serialized)

        state = {
            "last_dispense_request_id": self._last_dispense_request_id,
            "feed_history": serialized_history,
        }
        runtime_state_cache_set(self._state_key, state)

    def register_request(self, source, serving_size):
        """ Call when a feeding request is triggered, to append to history and start a timer that will monitor that
        an ACK is received. If a request is pending ACK, it will log an error and return False. """

        if self._pending_dispense_timeout_job is not None:
            self.register_error(source,
                f"Unacknowledged dispensing in progress (event {self._last_dispense_request_id}) "
                f"for '{self._cat_feeder_name}', timeout {self._dispense_ack_timeout}")
            return False

        log.info("Requesting '%s' to dispense snacks", self._cat_feeder_name)
        self._last_dispense_request_id += 1
        self._history_add(source, serving_size_requested=serving_size,
                          dispense_event_id=self._last_dispense_request_id)

        def _on_dispense_timeout(event_id):
            if self._last_dispense_request_id != event_id:
                # Timer fired but event was already acknowledged or superseded
                return

            # Find and update the history entry for this event
            missed_entry = {}
            for entry in reversed(self._feed_history):
                if entry['dispense_event_id'] == event_id:
                    entry['error'] = f"Unit failed to acknowledge dispensing within {self._dispense_ack_timeout}s"
                    missed_entry = entry
                    break
                # if we go can't find an entry to match it to, there isn't much we can do other than log

            self._save_state()
            log.error("'%s' failed to acknowledge dispensing event %s, make sure unit is responding",
                      self._cat_feeder_name, event_id)
            self._pending_dispense_timeout_job = None
            self._notify_dispense_event(source=missed_entry.get('source'),
                                        error='Failed to confirm snack deliver, make sure unit is working',
                                        portions_dispensed=0)

        self._pending_dispense_timeout_job = threading.Timer(
            self._dispense_ack_timeout,
            _on_dispense_timeout,
            args=[self._last_dispense_request_id]
        )
        self._pending_dispense_timeout_job.start()
        return True

    def register_zigbee_dispense(self, portions_dispensed, weight_dispensed):
        """ Call when a dispense event was triggered via Zigbee. If this service triggered the request, it should
        be pending in the history, and we'll mark it as ACKd. If it's not requested by this service, log it as an
        unauthorized dispense event. """
        if self._pending_dispense_timeout_job is not None:
            self._pending_dispense_timeout_job.cancel()
            self._pending_dispense_timeout_job = None

        # Find most recent unacknowledged entry within some reasonable time, even if its timeout expired
        unacked_entry = None
        for entry in reversed(self._feed_history):
            if entry['unit_acknowledged']:
                continue
            elapsed = (datetime.now() - entry['time_requested']).total_seconds()
            if elapsed <= self._dispense_ack_timeout:
                unacked_entry = entry
                break
            if elapsed <= 5 * self._dispense_ack_timeout:
                log.warning("'%s' took %s seconds to acknowledge request %s, make sure Z2M network is working fine",
                            self._cat_feeder_name, elapsed, entry["dispense_event_id"])
                unacked_entry = entry
                break

        if unacked_entry is not None:
            unacked_entry['unit_acknowledged'] = True
            unacked_entry['time_acknowledged'] = datetime.now()
            unacked_entry['portions_dispensed'] = portions_dispensed
            unacked_entry['weight_dispensed'] = weight_dispensed
            self._save_state()
            log.info("'%s' acknowledged dispensing event %s, dispensed %s portions",
                      self._cat_feeder_name, unacked_entry['dispense_event_id'], portions_dispensed)
            self._notify_dispense_event(source=unacked_entry['source'],
                                        error=unacked_entry['error'],
                                        portions_dispensed=portions_dispensed)
        else:
            log.warning("Unauthorized snack dispensing on '%s', dispensed %s portions",
                        self._cat_feeder_name, portions_dispensed)
            self.register_dispense('Unauthorized Zigbee request', portions_dispensed, weight_dispensed,
                                   error='There may be a different service trying to control this unit')

    def register_scheduled_dispense_on_time(self, portions_dispensed, weight_dispensed):
        """ Called when the unit reports schedule-feeding, and we can match it to a known feeding schedule slot """
        self.register_dispense('Schedule, on-time', portions_dispensed, weight_dispensed)

    def register_unmatched_scheduled_dispense(self, portions_dispensed, weight_dispensed):
        """ Called when the unit reports it served food at schedule, but the unit's schedule doesn't match ours """
        msg = f"Food dispensing on '{self._cat_feeder_name}' triggered by schedule, however we were not expecting a "\
              f"dispense now. Dispensed {portions_dispensed} portions. Is something else controling this unit?"
        log.warning(msg)
        self.register_dispense(source='Not in schedule, reported as scheduled',
                               error=msg,
                               portions_dispensed=portions_dispensed,
                               weight_dispensed=weight_dispensed)

    def register_missed_scheduled_dispense(self, scheduled_hour, scheduled_minute, tolerance_secs):
        """ Called when we were expecting the unit to deliver food, but it missed a scheduled slot """
        msg = f"Food dispensing on '{self._cat_feeder_name}' was expected at {scheduled_hour}:{scheduled_minute}. "\
              f"The unit is late by more than {tolerance_secs} seconds. Will attempt to trigger emergency dispense. "\
               "Ensure the unit is powered and connected to the Zigbee network"
        log.error(msg)
        self._history_add(source='Schedule expected, device missed', error=msg)
        self._notify_dispense_event(source='Schedule', error=msg, portions_dispensed=0)

    def register_dispense(self, source, portions_dispensed, weight_dispensed, error=None):
        """ Call when a dispense event has been registered which can't be traced back to a request initiated by
        this service (eg a user pressed a button on the unit) """
        log.info("Food dispensing on '%s' triggered by '%s', dispensed %s portions",
                 self._cat_feeder_name, source, portions_dispensed)
        self._history_add(source=source,
                          portions_dispensed=portions_dispensed,
                          weight_dispensed=weight_dispensed,
                          error=error)
        self._feed_history[-1]['unit_acknowledged'] = True
        self._feed_history[-1]['time_acknowledged'] = datetime.now()
        self._save_state()
        self._notify_dispense_event(source, error, portions_dispensed)

    def register_error(self, source, msg):
        """ Call when we attempted to dispense, but failed for some reason """
        log.error(msg)
        self._history_add(source, error=msg)

    def _history_add(self, source, error=None,
                     serving_size_requested=None,
                     portions_dispensed=None, weight_dispensed=None,
                     dispense_event_id=None):
        self._feed_history.append({
            "dispense_event_id": dispense_event_id,
            "time_requested": datetime.now(),
            "error": error,
            "source": source, # Manual, schedule, www, telegram, ...
            "serving_size_requested": serving_size_requested,

            # When we heard back from the unit, confirming this was dispensed
            "unit_acknowledged": False,
            "time_acknowledged": None,

            # Serving stats
            "portions_dispensed": portions_dispensed,
            "weight_dispensed": weight_dispensed,
            "start_portions_per_day": None,
            "start_weight_per_day": None,
        })
        self._save_state()
