"""One capture session: a camera event -> frames -> events, plus a decision log explaining every step.

Port of run_event in ~/src/visitordetect/visitor_sim.py (the offline reference). Per frame, cheapest checks first:
  1. day/night (motion.thumb) selects the pipeline and the per-mode thresholds
  2. motion delta (day only): skip SCRFD when nothing changed since the last frame SCRFD analysed, and skip
     the person detector (reusing its answer) when nothing changed since its last run
  3. person detector on a timer (person_every_s per mode; person_detection = always, first (until a person
     is reported) or off), ignoring boxes under person_min_height_px -> on_person_detected, once per session
  4. face stage (day only): SCRFD -> tracker -> quality gate -> ArcFace on gated faces -> track decision
     once a track has decide_min_faces gated faces: same person as an earlier track (nothing), known
     identity (on_face_identified, once per identity per session) or unknown (on_face_detected)
The session stops when idle, still (day, no motion and nobody at the last person check) or too long.

Events carry a large notification image (visit_images.NotificationImages) when notification_img_dir is set. Each
track also keeps its best face as a large crop, for that image and for person_faces() (saved next to the camera's
recording once the session ends).
"""
import json
import logging
import os
import threading
import time
from collections import Counter

import cv2
import numpy as np

import motion
from face_gate import gate, yaw_iod
from models import align_face, clip_box, l2_normalize
from visit_images import encode_jpg

log = logging.getLogger("VisitorSession")

BEST_N = 3
MAX_LOGGED_FACES = 2000
# A frame that fails to analyse is skipped; this many in a row means something is persistently broken
MAX_CONSECUTIVE_FRAME_ERRORS = 20
LOGGED_FRAME_ERRORS = 3


def _save(img, path, max_h=None):
    if max_h and img.shape[0] > max_h:
        img = cv2.resize(img, (int(img.shape[1] * max_h / img.shape[0]), max_h), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def _context(frame, box):
    """A crop around a face, big enough to recognise the person (the 112px aligned face often is not)."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy, s = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 2.5
    b = clip_box([cx - s / 2, cy - s / 2.5, cx + s / 2, cy + s * 0.6], w, h)
    return frame[b[1]:b[3], b[0]:b[2]].copy()


class Track:
    """One face moving through the session. Every SCRFD face is tracked; only gated faces are embedded."""

    def __init__(self, tid, box, t):
        self.id = tid
        self.box = box
        self.first_t = self.last_t = t
        self.n_seen = 1
        self.prev = None          # (box, last_t) before the latest association, to undo a bad one
        self.gated = []           # dicts: t, emb, quality, crop, ctx (abs paths)
        self.rejects = Counter()  # gate rejection reasons
        self.decision = None      # ('identified', identity_id, sim) | ('unknown', closest id, sim) | ('same_as', track, sim)
        self.last_embed_t = None
        self.first_ctx = None       # crop of its first face (gated or not), so every track has a photo in the UI
        self.large = None           # (quality, t, jpg bytes): its best gated face, large crop, for notifications/NVR

    def embedding(self):
        return l2_normalize(np.mean([g['emb'] for g in self.gated], axis=0)).astype(np.float32)

    def best(self, n=BEST_N):
        return sorted(self.gated, key=lambda g: -g['quality'])[:n]


class _LoopState:
    """What the frame loop carries from one frame to the next."""

    def __init__(self):
        self.last_activity = 0.0     # last person or face, or an extension request
        self.last_motion = 0.0
        self.prev_g = None           # (thumbnail, night) of the previous frame
        self.scrfd_ref = None        # ... of the last frame SCRFD analysed
        self.person_ref = None       # ... of the last frame the person detector ran on
        self.person_last = []        # its result
        self.last_person_t = None
        self.next_track_id = 1


def _centre_w(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, max(1.0, b[2] - b[0])


class Session:
    def __init__(self, session_id, cam_alias, start_ts, trigger, cfg, models, models_lock, store, data_dir, emit,
                 notification_imgs=None):
        self.id = session_id
        self.cam_alias = cam_alias
        self.start_ts = start_ts
        self.trigger = trigger
        self._cfg = cfg
        self._models = models
        self._models_lock = models_lock
        self._store = store
        self._data_dir = data_dir
        self._rel_dir = os.path.join('sessions', session_id)
        self._dir = os.path.join(data_dir, self._rel_dir)
        os.makedirs(self._dir, exist_ok=True)
        self._emit_cb = emit
        self._notification_imgs = notification_imgs
        self._extend_req = threading.Event()
        self._stop_req = threading.Event()
        self._source = None

        self.visit_id = store.begin_session(session_id, cam_alias, start_ts)
        self.t = 0.0
        self.wall_start = time.monotonic()
        self.tracks = []
        self.stats = Counter()
        self.timing = Counter()
        self.night_frames = 0
        self.log = {'session_id': session_id, 'cam_alias': cam_alias, 'trigger': trigger, 'start_ts': start_ts,
                    'inference': getattr(models, 'inference', None),
                    'visit_id': self.visit_id, 'person_checks': [], 'faces': [], 'events': [], 'person_crop': None}
        self._person_emitted = False
        self._identified = set()
        self._max_persons = 0

    # ------------------------------------------------------------------ control (called from other threads)

    def extend(self):
        """Another camera event arrived for this camera: reset the idle timer."""
        self._extend_req.set()

    def stop(self):
        self._stop_req.set()
        if self._source is not None:
            self._source.stop()

    def live_status(self):
        wall = time.monotonic() - self.wall_start
        return {'session_id': self.id, 'cam_alias': self.cam_alias, 'trigger': self.trigger, 't': round(self.t, 1),
                'wall_s': round(wall, 1), 'compute_s': round(sum(self.timing.values()), 1), 'frames': self.stats['frames'],
                'dropped': self._source.dropped if self._source else 0,
                'events': [e['type'] for e in self.log['events']]}

    # ------------------------------------------------------------------ helpers

    def _rel(self, name):
        return os.path.join(self._rel_dir, name)

    def _abs(self, rel):
        return os.path.join(self._data_dir, rel) if rel else None

    def _mode(self, night):
        return 'night' if night else 'day'

    def _emit(self, kind, t, night, **payload):
        ev = {'event': kind, 'cam_alias': self.cam_alias, 'session_id': self.id, 'trigger': self.trigger,
              'timestamp': self.start_ts + t, 't': round(t, 2), 'day_night': self._mode(night), **payload}
        self.log['events'].append({'type': kind, **ev})
        log.info("%s %s t=%.1f %s", self.id, kind, t,
                 {k: v for k, v in payload.items() if not k.endswith('path') and k != 'face_crop_paths'})
        self._emit_cb(kind, ev)

    def _notification_img(self, name, jpg):
        """Writes a notification image, returns its path (None if disabled or it couldn't be written)."""
        if self._notification_imgs is None or jpg is None:
            return None
        return self._notification_imgs.write(f"{self.id}_{name}.jpg", jpg)

    def _timed(self, stage, fn, *args):
        c0 = time.perf_counter()
        with self._models_lock:
            r = fn(*args)
        self.timing[stage] += time.perf_counter() - c0
        return r

    # ------------------------------------------------------------------ main loop

    def run(self, source):
        """Analyse frames until a stop rule fires. Returns the stop reason. Never raises: a frame that fails is
        logged and skipped; only MAX_CONSECUTIVE_FRAME_ERRORS failures in a row stop the session."""
        cfg = self._cfg
        self._source = source
        s = _LoopState()
        stop_reason = 'stream ended'
        consecutive_errors = 0
        try:
            for t, frame in source.frames():
                self.t = t
                self.stats['frames'] += 1
                if self._stop_req.is_set():
                    stop_reason = 'stopped'
                    break
                if self._extend_req.is_set():
                    self._extend_req.clear()
                    s.last_activity = t
                if t > cfg['max_session_s']:
                    stop_reason = f"max duration {cfg['max_session_s']}s"
                    break
                if t - s.last_activity > cfg['idle_stop_s']:
                    stop_reason = f"idle {cfg['idle_stop_s']}s"
                    break
                if t - max(s.last_motion, s.last_activity) > cfg['motion_stop_s'] and not s.person_last:
                    stop_reason = f"still {cfg['motion_stop_s']}s"
                    break
                try:
                    self._analyse_frame(t, frame, s)
                    consecutive_errors = 0
                except Exception as ex:  # pylint: disable=broad-except
                    consecutive_errors += 1
                    self.stats['frame_errors'] += 1
                    if self.stats['frame_errors'] <= LOGGED_FRAME_ERRORS:
                        log.error("Session %s: analysing the frame at %.2fs failed, skipped", self.id, t,
                                  exc_info=True)
                    if consecutive_errors >= MAX_CONSECUTIVE_FRAME_ERRORS:
                        stop_reason = f'error: {consecutive_errors} frames in a row failed, last: {ex!r}'
                        break
        except Exception as ex:  # pylint: disable=broad-except
            # The frame source itself failed
            log.error("Session %s: stream failed", self.id, exc_info=True)
            stop_reason = f'error: {ex!r}'
        finally:
            source.stop()
        if self.stats['frame_errors']:
            log.error("Session %s: %d frames failed to analyse (see the first %d above)", self.id,
                      self.stats['frame_errors'], min(self.stats['frame_errors'], LOGGED_FRAME_ERRORS))
        if source.error and stop_reason == 'stream ended':
            stop_reason = f'stream error: {source.error}'
        self.log['stop_reason'] = stop_reason
        return stop_reason

    def _analyse_frame(self, t, frame, s):
        cfg = self._cfg
        st = self.stats
        c0 = time.perf_counter()
        g, night = motion.thumb(frame)
        self.night_frames += night
        mode = self._mode(night)
        thr = cfg['motion_min_px'][mode]

        def moved(ref):
            # A day/night switch between the two frames always counts as a change
            return thr is None or ref is None or ref[1] != night or motion.delta(ref[0], g) >= thr

        if moved(s.prev_g):
            s.last_motion = t
        s.prev_g = (g, night)
        self.timing['cheap_checks'] += time.perf_counter() - c0

        if self._person_checks_done():
            # No more person checks: the stop rules then rely on motion and faces alone
            s.person_last = []
        elif s.last_person_t is None or t - s.last_person_t >= cfg['person_every_s'][mode] - 1e-6:
            s.last_person_t = t
            if moved(s.person_ref):
                found = self._timed('person_detection', self._models.detect_persons, frame, cfg['person_thr'])
                st['person_runs'] += 1
                persons = [p for p in found if p['box'][3] - p['box'][1] >= cfg['person_min_height_px']]
                small = [p for p in found if p not in persons]
                st['persons_too_small'] += len(small)
                s.person_ref, s.person_last = (g, night), persons
                self.log['person_checks'].append({
                    't': round(t, 2), 'ran': True, 'mode': mode,
                    'persons': [{'conf': p['conf'], 'sources': p['sources'], 'box': p['box']} for p in persons],
                    'too_small': [{'conf': p['conf'], 'box': p['box']} for p in small]})
            else:
                # Nothing changed since the last run: same answer (a still person is still there)
                st['person_skipped_still'] += 1
                persons = s.person_last
                self.log['person_checks'].append({'t': round(t, 2), 'ran': False, 'mode': mode,
                                                  'persons_reused': len(persons)})
            if persons:
                s.last_activity = t
                self._on_persons(t, night, frame, persons)
            return

        if night:
            st['skipped_night'] += 1
            return
        if not moved(s.scrfd_ref):
            st['skipped_still'] += 1
            return
        s.scrfd_ref = (g, night)

        dets = self._timed('face_detection', self._models.scrfd.detect, frame)
        st['scrfd_runs'] += 1
        if not dets:
            return
        s.last_activity = t
        s.next_track_id = self._on_faces(t, night, frame, dets, s.next_track_id)

    # ------------------------------------------------------------------ persons

    def _person_checks_done(self):
        mode = self._cfg['person_detection']
        return mode == 'off' or (mode == 'first' and self._person_emitted)

    def _on_persons(self, t, night, frame, persons):
        self._max_persons = max(self._max_persons, len(persons))
        if self._person_emitted:
            return
        self._person_emitted = True
        best = max(persons, key=lambda p: p['conf'])
        b = best['box']
        rel = self._rel('person.jpg')
        person = frame[b[1]:b[3], b[0]:b[2]]
        _save(person, self._abs(rel), 360)
        self.log['person_crop'] = rel
        notify = self._notification_img('person', encode_jpg(person)) if self._notification_imgs else None
        self._emit('on_person_detected', t, night, via='person_detector', conf=best['conf'],
                   person_count=len(persons), crop_path=self._abs(rel), notify_img_path=notify)

    # ------------------------------------------------------------------ faces

    def _update_tracks(self, dets, t, next_id):
        """Greedy nearest-centre association. Returns ([(track, det)], next_id)."""
        cfg = self._cfg
        active = [tr for tr in self.tracks if t - tr.last_t <= cfg['track_max_gap_s']]
        pairs = []
        for di, d in enumerate(dets):
            cx, cy, w = _centre_w(d[0])
            for tr in active:
                tx, ty, tw = _centre_w(tr.box)
                dist = np.hypot(cx - tx, cy - ty) / max(w, tw)
                if dist <= cfg['track_max_jump'] * max(t - tr.last_t, 0.25) + 0.5:
                    pairs.append((dist, di, tr))
        pairs.sort(key=lambda p: p[0])
        used_d, used_t, out = set(), set(), []
        for _, di, tr in pairs:
            if di in used_d or tr.id in used_t:
                continue
            used_d.add(di)
            used_t.add(tr.id)
            tr.prev = (tr.box, tr.last_t)
            tr.box, tr.last_t = dets[di][0], t
            tr.n_seen += 1
            out.append((tr, dets[di]))
        for di, d in enumerate(dets):
            if di not in used_d:
                tr = Track(next_id, d[0], t)
                next_id += 1
                self.tracks.append(tr)
                out.append((tr, d))
        return out, next_id

    def _on_faces(self, t, night, frame, dets, next_id):
        cfg = self._cfg
        st = self.stats
        assoc, next_id = self._update_tracks(dets, t, next_id)
        for tr, (box, conf, kps) in assoc:
            if tr.first_ctx is None:
                tr.first_ctx = self._rel(f"t{tr.id}_first_ctx.jpg")
                _save(_context(frame, box), self._abs(tr.first_ctx), 160)
            ok, reason = gate(kps, night, conf, self._cfg['face_gate'])
            yaw, iod = yaw_iod(kps)
            entry = {'t': round(t, 2), 'track': tr.id, 'conf': round(conf, 2), 'iod': round(iod), 'yaw': round(yaw, 2),
                     'gate': reason}
            if not ok:
                st['gate_rejected'] += 1
                tr.rejects[reason.split(' (')[0]] += 1
                self._log_face(entry)
                continue
            st['gated_faces'] += 1
            if (tr.decision is not None and tr.last_embed_t is not None
                    and t - tr.last_embed_t < cfg['decided_embed_every_s']):
                # Decided tracks need few more faces (split check, best faces to store); ArcFace is ~80 ms each
                st['embed_skipped'] += 1
                entry['gate'] = 'ok (not embedded: track already decided)'
                self._log_face(entry)
                continue
            aligned = align_face(frame, kps)
            emb = self._timed('embedding', self._models.arcface.embed, aligned)
            if tr.gated and float(np.dot(emb, tr.embedding())) < cfg['track_split_thr']:
                # The tracker jumped to someone else (people crossing): undo and start a new track
                tr.box, tr.last_t = tr.prev
                tr.n_seen -= 1
                tr = Track(next_id, box, t)
                next_id += 1
                self.tracks.append(tr)
                st['track_splits'] += 1
                entry['track'] = tr.id
                entry['split'] = True
            # Set on the track that keeps the face (a split hands it to a new track)
            tr.last_embed_t = t
            self._log_face(entry)
            name = f"t{tr.id}_{int(t * 1000):07d}"
            crop, ctx = self._rel(name + '.jpg'), self._rel(name + '_ctx.jpg')
            ctx_img = _context(frame, box)
            _save(aligned, self._abs(crop))
            _save(ctx_img, self._abs(ctx), 240)
            quality = conf + iod / 100 - yaw
            tr.gated.append({'t': t, 'emb': emb, 'quality': quality, 'crop': crop, 'ctx': ctx})
            if tr.large is None or quality > tr.large[0]:
                # Same ranking as Track.best(): the face its event reports
                tr.large = (quality, t, encode_jpg(ctx_img))
            if len(tr.gated) == 1:
                # Someone already seen in this session (tracker lost them)? Decisions themselves wait for
                # decide_min_faces: single faces are too noisy to tell a new person apart.
                same = self._same_person(emb, tr)
                if same is not None:
                    tr.decision = ('same_as', same[0].id, same[1])
            if not self._person_emitted:
                # A face implies a person even if the person detector hasn't run (or fired) yet
                self._person_emitted = True
                self.log['person_crop'] = ctx
                self._emit('on_person_detected', t, night, via='face', conf=None, person_count=1,
                           crop_path=self._abs(ctx), notify_img_path=self._notification_img('person', tr.large[2]))
            self._decide(tr, t, night)
        return next_id

    def _log_face(self, entry):
        if len(self.log['faces']) < MAX_LOGGED_FACES:
            self.log['faces'].append(entry)
        else:
            self.stats['faces_not_logged'] += 1

    def _same_person(self, emb, tr):
        """(track, sim) of an earlier, already reported track in this session that emb matches, or None."""
        best = None
        for other in self.tracks:
            # Only tracks that were reported (unknown or identified): matching an undecided one (eg a single gated
            # face) would silence this person for the rest of the session
            if other is tr or not other.decision or other.decision[0] == 'same_as':
                continue
            s = float(np.dot(emb, other.embedding()))
            if s >= self._cfg['same_person_thr'] and (best is None or s > best[1]):
                best = (other, s)
        return best

    def _decide(self, tr, t, night):
        """Called on each new gated face of a track. A track is decided once (an unknown can still be upgraded
        to identified as more faces arrive)."""
        cfg = self._cfg
        if len(tr.gated) < cfg['decide_min_faces'] or (tr.decision and tr.decision[0] not in ('unknown',)):
            return
        emb = tr.embedding()
        if tr.decision is None:
            same = self._same_person(emb, tr)
            if same is not None:
                tr.decision = ('same_as', same[0].id, same[1])
                return
        iid, s = self._store.match(emb)
        best = tr.best()[0]
        faces = {'track_id': tr.id, 'gated_faces': len(tr.gated), 'face_crop_path': self._abs(best['crop']),
                 'context_crop_path': self._abs(best['ctx'])}
        if iid is not None and s >= cfg['id_thr']:
            upgraded = tr.decision is not None
            tr.decision = ('identified', iid, s)
            if iid in self._identified:
                return
            self._identified.add(iid)
            faces['notify_img_path'] = self._notification_img(f"t{tr.id}", tr.large[2])
            self._emit('on_face_identified', t, night, visitor_id=self._store.visitor_key(iid),
                       name=self._store.display_name(iid), sim=round(s, 3), upgraded=upgraded, **faces)
        elif tr.decision is None:
            tr.decision = ('unknown', iid, s)
            faces['notify_img_path'] = self._notification_img(f"t{tr.id}", tr.large[2])
            self._emit('on_face_detected', t, night, closest=self._store.visitor_key(iid) if iid else None,
                       closest_sim=round(s, 3) if iid else None, **faces)

    # ------------------------------------------------------------------ end of session

    def person_faces(self):
        """Each reported person's best face, as a large crop: [{'person', 'named', 'label', 'ts', 'jpg'}]. A person
        is a reported track with the tracks found to be the same person; tracks of the same visitor are one person."""
        by_id = {tr.id: tr for tr in self.tracks}
        best = {}
        for tr in self.tracks:
            if tr.large is None or not tr.decision:
                continue
            owner = by_id.get(tr.decision[1]) if tr.decision[0] == 'same_as' else tr
            if owner is None or not owner.decision or owner.decision[0] == 'same_as':
                continue
            kind, iid, _ = owner.decision
            if kind == 'identified':
                person, named, label = f"visitor_{iid}", True, self._store.display_name(iid)
            else:
                person, named, label = f"track_{owner.id}", False, 'unknown'
            quality, t, jpg = tr.large
            if person not in best or quality > best[person]['quality']:
                best[person] = {'person': person, 'named': named, 'label': label, 'quality': quality,
                                'ts': self.start_ts + t, 'jpg': jpg}
        return sorted(({k: v for k, v in f.items() if k != 'quality'} for f in best.values()), key=lambda f: f['ts'])

    def _stream_stats(self):
        """How quickly the stream started (camera event -> first frame) and how far the analysis lagged."""
        src = self._source
        if src is None or src.first_frame_at is None:
            return None
        return {'decoder': src.decoder, 'event_to_first_frame_s': round(src.first_frame_at - self.start_ts, 2),
                'ffmpeg_to_first_frame_s': round(src.first_frame_s, 2), 'max_lag_s': round(src.max_lag_s, 2),
                'decode_cpu_s': round(src.decode_cpu_s, 2),
                'size': src.size}

    def finish(self, end_ts):
        """Store decided tracks, run discovery, write the decision log. Returns the session summary."""
        cfg = self._cfg
        for tr in self.tracks:
            if not tr.decision or len(tr.gated) < cfg['decide_min_faces'] or tr.decision[0] == 'same_as':
                continue
            track = {'id': tr.id, 'emb': tr.embedding(),
                     'faces': [{'t': g['t'], 'quality': g['quality'], 'emb': g['emb'], 'crop': self._abs(g['crop'])}
                               for g in tr.gated],
                     'best': [{'crop': self._abs(g['crop']), 'ctx': self._abs(g['ctx'])} for g in tr.best()]}
            kind, iid, s = tr.decision
            if kind == 'identified':
                self._store.store_track(self.id, self.cam_alias, self.start_ts, self.visit_id, track, 'identity',
                                        iid, s)
            else:
                self._store.store_track(self.id, self.cam_alias, self.start_ts, self.visit_id, track, 'unknown')

        new_ids = self._store.discover(self.start_ts, self.id)
        for ident in new_ids:
            self._emit('on_new_frequent_visitor', self.t, False, visitor_id=ident['key'], name=ident['name'],
                       visits=ident['visits'], days=ident['days'],
                       face_crop_paths=[self._store.abs_path(b['ctx'] or b['crop'])
                                        for tr in ident['tracks'][:3] for b in tr['best'][:1]])
        self.log['discovery'] = [{'visitor_id': i['key'], 'name': i['name'], 'visits': i['visits'],
                                  'days': i['days']} for i in new_ids]

        wall = time.monotonic() - self.wall_start
        frames = max(1, self.stats['frames'])
        mode = 'night' if self.night_frames > frames * 0.9 else 'day' if self.night_frames < frames * 0.1 else 'mixed'
        self.log.update({
            'end_ts': end_ts, 'mode': mode, 'analysed_s': round(self.t, 2), 'wall_s': round(wall, 2),
            'dropped_frames': self._source.dropped if self._source else 0,
            'stream': self._stream_stats(),
            'stats': dict(self.stats), 'timing': {k: round(v, 2) for k, v in self.timing.items()},
            'max_persons': self._max_persons,
            'tracks': [{
                'id': tr.id, 'first_t': round(tr.first_t, 2), 'last_t': round(tr.last_t, 2), 'seen': tr.n_seen,
                'gated': len(tr.gated), 'rejects': dict(tr.rejects),
                'decision': None if tr.decision is None else {
                    'kind': tr.decision[0],
                    'who': (f'track {tr.decision[1]}' if tr.decision[0] == 'same_as'
                            else self._store.display_name(tr.decision[1]) if tr.decision[1] else None),
                    'sim': round(tr.decision[2], 3)},
                'stored': bool(tr.decision and tr.decision[0] != 'same_as'
                               and len(tr.gated) >= cfg['decide_min_faces']),
                'best': [{'crop': g['crop'], 'ctx': g['ctx']} for g in tr.best()],
                # The face its decision started from (first gated face), else the first face seen
                'photo': tr.gated[0]['ctx'] if tr.gated else tr.first_ctx,
                'same_as': tr.decision[1] if tr.decision and tr.decision[0] == 'same_as' else None,
            } for tr in self.tracks],
        })
        with open(os.path.join(self._dir, 'log.json'), 'w') as f:
            json.dump(self.log, f)

        summary = {
            'mode': mode, 'trigger': self.trigger, 'stop_reason': self.log['stop_reason'],
            'analysed_s': self.log['analysed_s'], 'wall_s': self.log['wall_s'],
            'dropped_frames': self.log['dropped_frames'], 'stream': self.log['stream'],
            'person_crop': self.log['person_crop'],
            'max_persons': self._max_persons, 'tracks': len(self.tracks),
            'gated_faces': self.stats['gated_faces'],
            'events': [{'type': e['type'], 't': e['t'], 'name': e.get('name')} for e in self.log['events']],
        }
        self._store.end_session(self.id, end_ts, summary)
        return summary
