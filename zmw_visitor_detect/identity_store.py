"""Identities, the unknown pool and discovery of frequent visitors, persisted in SQLite.

Nothing here is trained: models are fixed, and the store only keeps face embeddings grouped into identities.
Every threshold is a runtime comparison, so changing one never requires discarding data.

- Per-face records are kept (embedding + aligned crop), never only a per-identity summary, so any decision can
  be recomputed (split a merged identity, re-embed with another model).
- A *track* is one person in one session with >= decide_min_faces gated faces; its embedding is the mean of
  its faces. Tracks are 'unknown' (in the discovery pool), 'identity' (belong to an identity) or 'discarded'.
- An identity's gallery is a capped subset of its tracks; matching takes the best similarity over a gallery.
- Discovery clusters the unknown pool (average linkage) from scratch after every session; a cluster seen in
  enough visits on enough days becomes an identity ("Visitor N"). Prefer splitting a person over merging two.
"""
import json
import logging
import os
import shutil
import sqlite3
import threading
import time

import numpy as np

log = logging.getLogger("IdentityStore")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, cam_alias TEXT, start_ts REAL, end_ts REAL, visit_id INTEGER, day TEXT,
    summary TEXT);
CREATE TABLE IF NOT EXISTS identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_ts REAL, discovered_session TEXT,
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, track_id INTEGER, cam_alias TEXT, ts REAL,
    visit_id INTEGER, day TEXT, state TEXT, identity_id INTEGER, sim REAL, in_gallery INTEGER NOT NULL DEFAULT 0,
    emb BLOB, best TEXT);
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT, track_row INTEGER, t REAL, quality REAL, emb BLOB, crop TEXT);
CREATE INDEX IF NOT EXISTS tracks_state ON tracks(state, identity_id);
CREATE INDEX IF NOT EXISTS faces_track ON faces(track_row);
"""


def _blob(emb):
    return np.asarray(emb, dtype=np.float32).tobytes()


def _emb(blob):
    return np.frombuffer(blob, dtype=np.float32)


def _l2(v):
    return v / (np.linalg.norm(v) + 1e-10)


def average_linkage(embs, thr):
    """Agglomerative clustering of L2-normalised embeddings: merge the two clusters with the highest mean
    pairwise similarity while it is >= thr. Returns a list of index lists, biggest first."""
    n = len(embs)
    if n == 0:
        return []
    e = np.stack(embs).astype(np.float64)
    s = e @ e.T
    np.fill_diagonal(s, -np.inf)
    sizes = np.ones(n)
    members = {i: [i] for i in range(n)}
    while len(members) > 1:
        a, b = np.unravel_index(np.argmax(s), s.shape)
        if s[a, b] < thr:
            break
        # Lance-Williams update for average linkage: the merged row is the size-weighted mean of the two rows
        row = (sizes[a] * s[a] + sizes[b] * s[b]) / (sizes[a] + sizes[b])
        s[a, :] = row
        s[:, a] = row
        s[a, a] = -np.inf
        s[b, :] = -np.inf
        s[:, b] = -np.inf
        sizes[a] += sizes[b]
        members[a] += members.pop(b)
    return sorted(members.values(), key=len, reverse=True)


class IdentityStore:
    def __init__(self, data_dir, cfg):
        self._dir = os.path.abspath(data_dir)
        self._faces_dir = os.path.join(self._dir, 'faces')
        os.makedirs(self._faces_dir, exist_ok=True)
        self._cfg = cfg
        self._names = cfg.get('visitor_names', {})
        self._lock = threading.RLock()
        self._db = sqlite3.connect(os.path.join(self._dir, 'visitor_store.sqlite'), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._galleries = None

    # ------------------------------------------------------------------ names and paths

    @staticmethod
    def visitor_key(identity_id):
        return f"visitor_{identity_id}"

    def display_name(self, identity_id):
        return self._names.get(self.visitor_key(identity_id), f"Visitor {identity_id}")

    def abs_path(self, rel):
        return os.path.join(self._dir, rel)

    # ------------------------------------------------------------------ sessions

    def begin_session(self, session_id, cam_alias, start_ts):
        """Registers a session; sessions closer than visit_gap_s to the previous one are the same visit."""
        with self._lock:
            prev = self._db.execute(
                'SELECT visit_id, end_ts, start_ts FROM sessions ORDER BY start_ts DESC LIMIT 1').fetchone()
            if prev and start_ts - (prev['end_ts'] or prev['start_ts']) <= self._cfg['visit_gap_s']:
                visit_id = prev['visit_id']
            else:
                visit_id = (self._db.execute('SELECT MAX(visit_id) FROM sessions').fetchone()[0] or 0) + 1
            day = time.strftime('%Y-%m-%d', time.localtime(start_ts))
            self._db.execute('INSERT OR REPLACE INTO sessions (id, cam_alias, start_ts, visit_id, day) '
                             'VALUES (?, ?, ?, ?, ?)', (session_id, cam_alias, start_ts, visit_id, day))
            self._db.commit()
            return visit_id

    def end_session(self, session_id, end_ts, summary):
        with self._lock:
            self._db.execute('UPDATE sessions SET end_ts = ?, summary = ? WHERE id = ?',
                             (end_ts, json.dumps(summary), session_id))
            self._db.commit()

    def sessions(self, limit=200, before_ts=None):
        with self._lock:
            q = 'SELECT * FROM sessions'
            args = []
            if before_ts is not None:
                q += ' WHERE start_ts < ?'
                args.append(before_ts)
            q += ' ORDER BY start_ts DESC LIMIT ?'
            args.append(limit)
            rows = self._db.execute(q, args).fetchall()
        return [{'id': r['id'], 'cam_alias': r['cam_alias'], 'start_ts': r['start_ts'], 'end_ts': r['end_ts'],
                 'visit_id': r['visit_id'], 'summary': json.loads(r['summary']) if r['summary'] else None}
                for r in rows]

    def session_ids_to_prune(self, keep):
        """Sessions beyond the newest `keep` (their decision logs can go; their tracks stay)."""
        with self._lock:
            return [r[0] for r in self._db.execute(
                'SELECT id FROM sessions ORDER BY start_ts DESC LIMIT -1 OFFSET ?', (keep,)).fetchall()]

    # ------------------------------------------------------------------ matching

    def _load_galleries(self):
        if self._galleries is None:
            gal = {}
            for r in self._db.execute(
                    'SELECT t.identity_id, t.emb FROM tracks t JOIN identities i ON i.id = t.identity_id '
                    "WHERE t.state = 'identity' AND t.in_gallery = 1 AND i.deleted = 0"):
                gal.setdefault(r['identity_id'], []).append(_emb(r['emb']))
            self._galleries = {k: np.stack(v) for k, v in gal.items()}
        return self._galleries

    def _invalidate(self):
        self._galleries = None

    def match(self, emb):
        """(identity_id, sim) of the best matching identity, or (None, -1)."""
        with self._lock:
            best, best_sim = None, -1.0
            for iid, gal in self._load_galleries().items():
                s = float(np.max(gal @ emb))
                if s > best_sim:
                    best, best_sim = iid, s
            return best, best_sim

    # ------------------------------------------------------------------ storing tracks

    def store_track(self, session_id, cam_alias, ts, visit_id, track, state, identity_id=None, sim=None):
        """track: {'id', 'emb', 'faces': [{'t', 'quality', 'emb', 'crop' (abs path)}], 'best': [{'crop', 'ctx'}]}.
        Crops are copied into the store (session decision logs are pruned, the store is not)."""
        day = time.strftime('%Y-%m-%d', time.localtime(ts))
        prefix = f"{session_id}_t{track['id']}"

        def _keep(src, suffix):
            if not src or not os.path.isfile(src):
                return None
            rel = os.path.join('faces', f"{prefix}_{suffix}{os.path.splitext(src)[1]}")
            shutil.copyfile(src, self.abs_path(rel))
            return rel

        best = [{'crop': _keep(b['crop'], f'best{i}'), 'ctx': _keep(b.get('ctx'), f'best{i}_ctx')}
                for i, b in enumerate(track['best'])]
        faces = [(f['t'], f['quality'], _blob(f['emb']), _keep(f['crop'], f"f{int(f['t'] * 1000):07d}"))
                 for f in track['faces']]
        in_gallery = int(state == 'identity' and sim is not None and sim >= self._cfg['gallery_add_thr'])
        with self._lock:
            cur = self._db.execute(
                'INSERT INTO tracks (session_id, track_id, cam_alias, ts, visit_id, day, state, identity_id, sim, '
                'in_gallery, emb, best) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (session_id, track['id'], cam_alias, ts, visit_id, day, state, identity_id, sim, in_gallery,
                 _blob(track['emb']), json.dumps(best)))
            row = cur.lastrowid
            self._db.executemany('INSERT INTO faces (track_row, t, quality, emb, crop) VALUES (?, ?, ?, ?, ?)',
                                 [(row, *f) for f in faces])
            if in_gallery:
                self._cap_gallery(identity_id)
            self._db.commit()
            self._invalidate()
            return row

    def _cap_gallery(self, identity_id):
        rows = self._db.execute("SELECT id, emb FROM tracks WHERE identity_id = ? AND state = 'identity' "
                                'AND in_gallery = 1', (identity_id,)).fetchall()
        while len(rows) > self._cfg['gallery_cap']:
            # Drop the most redundant embedding (highest summed similarity to the rest)
            e = np.stack([_emb(r['emb']) for r in rows])
            drop = int(np.argmax((e @ e.T).sum(1)))
            self._db.execute('UPDATE tracks SET in_gallery = 0 WHERE id = ?', (rows[drop]['id'],))
            rows.pop(drop)

    # ------------------------------------------------------------------ discovery

    def _pool(self, now_ts):
        cutoff = now_ts - self._cfg['unknown_ttl_days'] * 86400
        return self._db.execute("SELECT * FROM tracks WHERE state = 'unknown' AND identity_id IS NULL AND ts >= ? "
                                'ORDER BY ts', (cutoff,)).fetchall()

    def _clusters(self, rows):
        groups = average_linkage([_emb(r['emb']) for r in rows], self._cfg['same_person_thr'])
        out = []
        for g in groups:
            members = [rows[i] for i in g]
            out.append({'rows': members,
                        'visits': len({m['visit_id'] for m in members}),
                        'days': len({m['day'] for m in members})})
        return out

    def _promotable(self, cluster):
        return (cluster['visits'] >= self._cfg['discovery_min_visits']
                and cluster['days'] >= self._cfg['discovery_min_days'])

    def _new_identity(self, rows, session_id, now_ts):
        cur = self._db.execute('INSERT INTO identities (created_ts, discovered_session) VALUES (?, ?)',
                               (now_ts, session_id))
        iid = cur.lastrowid
        self._db.executemany("UPDATE tracks SET state = 'identity', identity_id = ?, in_gallery = 1 WHERE id = ?",
                             [(iid, r['id']) for r in rows])
        self._cap_gallery(iid)
        return iid

    def discover(self, now_ts, session_id):
        """Expire old unknowns, cluster the pool, promote frequent visitors. Returns the new identities."""
        with self._lock:
            self._expire_unknowns(now_ts)
            new = []
            for c in self._clusters(self._pool(now_ts)):
                if not self._promotable(c):
                    continue
                iid = self._new_identity(c['rows'], session_id, now_ts)
                log.info("Discovered %s: %d tracks over %d visits on %d days", self.display_name(iid),
                         len(c['rows']), c['visits'], c['days'])
                new.append(iid)
            self._db.commit()
            self._invalidate()
        return [self.identity(iid) for iid in new]

    def _expire_unknowns(self, now_ts):
        cutoff = now_ts - self._cfg['unknown_ttl_days'] * 86400
        rows = self._db.execute("SELECT id FROM tracks WHERE state IN ('unknown', 'discarded') "
                                'AND identity_id IS NULL AND ts < ?', (cutoff,)).fetchall()
        for r in rows:
            self._delete_track(r['id'])

    def _delete_track(self, row_id):
        """Removes a track, its faces and their crops."""
        t = self._db.execute('SELECT best FROM tracks WHERE id = ?', (row_id,)).fetchone()
        paths = [f['crop'] for f in self._db.execute('SELECT crop FROM faces WHERE track_row = ?', (row_id,))]
        if t and t['best']:
            for b in json.loads(t['best']):
                paths += [b.get('crop'), b.get('ctx')]
        for p in paths:
            if p:
                try:
                    os.remove(self.abs_path(p))
                except FileNotFoundError:
                    pass
        self._db.execute('DELETE FROM faces WHERE track_row = ?', (row_id,))
        self._db.execute('DELETE FROM tracks WHERE id = ?', (row_id,))

    # ------------------------------------------------------------------ views for the UI and events

    def _track_view(self, r):
        return {'row': r['id'], 'session_id': r['session_id'], 'track_id': r['track_id'], 'ts': r['ts'],
                'visit_id': r['visit_id'], 'day': r['day'], 'sim': r['sim'], 'in_gallery': bool(r['in_gallery']),
                'best': json.loads(r['best']) if r['best'] else []}

    def identity(self, iid):
        with self._lock:
            i = self._db.execute('SELECT * FROM identities WHERE id = ?', (iid,)).fetchone()
            if i is None:
                return None
            rows = self._db.execute("SELECT * FROM tracks WHERE identity_id = ? AND state = 'identity' "
                                    'ORDER BY ts DESC', (iid,)).fetchall()
            return {'id': iid, 'key': self.visitor_key(iid), 'name': self.display_name(iid),
                    'named': self.visitor_key(iid) in self._names, 'created_ts': i['created_ts'],
                    'discovered_session': i['discovered_session'], 'deleted': bool(i['deleted']),
                    'visits': len({r['visit_id'] for r in rows}), 'days': len({r['day'] for r in rows}),
                    'gallery_size': sum(r['in_gallery'] for r in rows),
                    'first_seen': min((r['ts'] for r in rows), default=None),
                    'last_seen': max((r['ts'] for r in rows), default=None),
                    'tracks': [self._track_view(r) for r in rows]}

    def identities(self):
        with self._lock:
            ids = [r[0] for r in self._db.execute('SELECT id FROM identities WHERE deleted = 0 ORDER BY id')]
            return [self.identity(i) for i in ids]

    def unknown_clusters(self, now_ts=None):
        """The current discovery pool, clustered the same way discovery does, with progress towards promotion."""
        with self._lock:
            out = []
            for c in self._clusters(self._pool(now_ts or time.time())):
                out.append({'track_rows': [r['id'] for r in c['rows']], 'visits': c['visits'], 'days': c['days'],
                            'needs_visits': self._cfg['discovery_min_visits'],
                            'needs_days': self._cfg['discovery_min_days'],
                            'tracks': [self._track_view(r) for r in c['rows']]})
            return out

    # ------------------------------------------------------------------ admin operations

    def _require_identity(self, iid):
        r = self._db.execute('SELECT deleted FROM identities WHERE id = ?', (iid,)).fetchone()
        if r is None or r['deleted']:
            raise ValueError(f"No visitor with id {iid}")

    def reset_tracks(self, track_rows):
        """Remove unknown tracks from the pool (eg a cluster of a courier)."""
        with self._lock:
            for r in track_rows:
                self._delete_track(int(r))
            self._db.commit()
            self._invalidate()

    def remove_track_from_identity(self, track_row):
        """A wrong face in an identity: drop it (it does not go back to the pool)."""
        with self._lock:
            self._db.execute("UPDATE tracks SET state = 'discarded', identity_id = NULL, in_gallery = 0 "
                             'WHERE id = ?', (int(track_row),))
            self._db.commit()
            self._invalidate()

    def delete_identity(self, iid, to_pool):
        """Delete an identity. Its tracks go back to the unknown pool (they may be rediscovered later) or are
        dropped."""
        with self._lock:
            self._require_identity(iid)
            self._db.execute('UPDATE identities SET deleted = 1 WHERE id = ?', (iid,))
            if to_pool:
                self._db.execute("UPDATE tracks SET state = 'unknown', identity_id = NULL, in_gallery = 0 "
                                 'WHERE identity_id = ?', (iid,))
            else:
                for r in self._db.execute('SELECT id FROM tracks WHERE identity_id = ?', (iid,)).fetchall():
                    self._delete_track(r['id'])
            self._db.commit()
            self._invalidate()

    def merge_identities(self, keep_id, other_id):
        if keep_id == other_id:
            raise ValueError("Can't merge a visitor with itself")
        with self._lock:
            self._require_identity(keep_id)
            self._require_identity(other_id)
            self._db.execute('UPDATE tracks SET identity_id = ? WHERE identity_id = ?', (keep_id, other_id))
            self._db.execute('UPDATE identities SET deleted = 1 WHERE id = ?', (other_id,))
            self._cap_gallery(keep_id)
            self._db.commit()
            self._invalidate()

    def split_identity(self, iid, thr, now_ts=None):
        """Re-cluster an identity's tracks at a stricter threshold (eg two siblings merged). The biggest group
        keeps the identity; groups that qualify as frequent visitors become new identities, the rest go back
        to the unknown pool. Returns the ids of the identities involved."""
        now_ts = now_ts or time.time()
        with self._lock:
            self._require_identity(iid)
            rows = self._db.execute("SELECT * FROM tracks WHERE identity_id = ? AND state = 'identity'",
                                    (iid,)).fetchall()
            groups = average_linkage([_emb(r['emb']) for r in rows], thr)
            out = [iid]
            for g in groups[1:]:
                members = [rows[i] for i in g]
                c = {'rows': members, 'visits': len({m['visit_id'] for m in members}),
                     'days': len({m['day'] for m in members})}
                if self._promotable(c):
                    out.append(self._new_identity(members, f'split of {self.visitor_key(iid)}', now_ts))
                else:
                    self._db.executemany("UPDATE tracks SET state = 'unknown', identity_id = NULL, in_gallery = 0 "
                                         'WHERE id = ?', [(m['id'],) for m in members])
            if groups:
                # The group that stays may now be under the gallery cap with tracks that had been dropped
                self._db.executemany('UPDATE tracks SET in_gallery = 1 WHERE id = ?',
                                     [(rows[i]['id'],) for i in groups[0]])
                self._cap_gallery(iid)
            self._db.commit()
            self._invalidate()
            return out
