"""NVR-ish web interface for camera recordings and snapshots."""
import os
from datetime import datetime, timedelta
from flask import send_from_directory, jsonify, redirect, request
from ffmpeg_helper import get_thumbnail_path


def _get_cams(base_path):
    if not os.path.exists(base_path) or not os.path.isdir(base_path):
        return []
    cams = []
    for entry in os.listdir(base_path):
        full_path = os.path.join(base_path, entry)
        if os.path.isdir(full_path):
            cams.append(entry)
    return cams


def _format_file_size(sz):
    if sz < 1024:
        return f"{sz} bytes"
    if sz < 1024 * 1024:
        return f"{sz / 1024:.0f} KB"
    return f"{sz / (1024 * 1024):.0f} MB"


def _get_cam_recordings(base_path, cam, days=None):
    path = os.path.join(base_path, cam)
    if not os.path.exists(path) or not os.path.isdir(path):
        return None, None

    ftimelimit = None
    if days is not None:
        ftimelimit = datetime.today() - timedelta(days=days)
    recs = []
    for root, _, filenames in os.walk(path):
        for fname in filenames:
            fpath = os.path.join(root, fname)
            fsize = os.path.getsize(fpath)
            fsize = _format_file_size(fsize)
            ftime = os.path.getmtime(fpath)

            is_in_requested_time = ftimelimit is None or datetime.fromtimestamp(ftime) > ftimelimit
            # .small.mp4 files are reencodings of a recording (eg for Telegram), not recordings of their own
            is_movie = fname.endswith('.mp4') and not fname.endswith('.small.mp4')
            if is_in_requested_time and is_movie:
                recs.append((fname, fpath, fsize, ftime))
    recs.sort(reverse=True)
    return path, recs


def _get_cam_snapshots(base_path, cam):
    """Get all snapshots for a camera, sorted newest first."""
    if base_path is None:
        return None, None

    path = os.path.join(base_path, cam)
    if not os.path.exists(path) or not os.path.isdir(path):
        return None, None

    snaps = []
    for fname in os.listdir(path):
        if fname.endswith('.jpg'):
            fpath = os.path.join(path, fname)
            ftime = os.path.getmtime(fpath)
            snaps.append((fname, fpath, ftime))
    snaps.sort(key=lambda x: x[2], reverse=True)
    return path, snaps


class Nvr:
    """Web interface for browsing and viewing camera recordings and snapshots."""
    def __init__(self, nvr_path, snap_path, flask_app):
        self._nvr_path = nvr_path
        self._snap_path = snap_path

        # Redirect /nvr to the React app
        flask_app.add_url_rule('/nvr', None, lambda: redirect('/nvr.html'))
        flask_app.add_url_rule('/nvr/api/cameras', None, self._api_list_cams)
        flask_app.add_url_rule('/nvr/api/<cam>/recordings', None, self._api_list_recordings)
        flask_app.add_url_rule('/nvr/api/<cam>/snapshots', None, self._api_list_snapshots)
        flask_app.add_url_rule('/nvr/<cam>/get_recording/<file>', None, self._get_recording)
        flask_app.add_url_rule('/nvr/<cam>/get_snapshot/<file>', None, self._get_snapshot)

    def _api_list_cams(self):
        """Return JSON list of available cameras."""
        cameras = _get_cams(self._nvr_path)
        return jsonify({'cameras': cameras})

    def _api_list_recordings(self, cam):
        """Return JSON list of recordings for a camera."""
        # Get days parameter from query string (default to all if not specified)
        days = request.args.get('days', type=int)
        if days == 0:
            days = None  # 0 means show all recordings

        path, recs = _get_cam_recordings(self._nvr_path, cam, days)

        if path is None:
            return jsonify({'error': f'Unknown camera {cam}'}), 404

        recordings = []
        for (fname, fpath, fsize, _) in recs:
            # Thumbnails are generated when a recording completes; never spawn ffmpeg from here, as
            # listing many recordings would spawn one ffmpeg per recording in parallel
            img_path = get_thumbnail_path(fpath)
            if not os.path.exists(img_path):
                thumbnail_url = None
            else:
                img_fname = os.path.basename(img_path)
                thumbnail_url = f'/nvr/{cam}/get_recording/{img_fname}'

            recordings.append({
                'filename': fname,
                'size': fsize,
                'video_url': f'/nvr/{cam}/get_recording/{fname}',
                'thumbnail_url': thumbnail_url
            })

        return jsonify({'recordings': recordings})

    def _api_list_snapshots(self, cam):
        """Return JSON list of snapshots for a camera."""
        path, snaps = _get_cam_snapshots(self._snap_path, cam)

        if path is None:
            return jsonify({'snapshots': []})

        snapshots = []
        for (fname, _, ftime) in snaps:
            snapshots.append({
                'filename': fname,
                'timestamp': ftime,
                'url': f'/nvr/{cam}/get_snapshot/{fname}'
            })

        return jsonify({'snapshots': snapshots})

    def _get_recording(self, cam, file):
        path = os.path.join(self._nvr_path, cam)
        if not os.path.exists(path) or not os.path.isdir(path):
            return f"Can't get recording for unknown cam {cam}", 404

        fpath = os.path.join(path, file)
        if not os.path.exists(fpath) or not os.path.isfile(fpath):
            return f"Can't get unknown recording {file} for unknown cam {cam}", 404

        return send_from_directory(path, file)

    def _get_snapshot(self, cam, file):
        """Serve a snapshot file."""
        if self._snap_path is None:
            return "Snapshots not configured", 404

        path = os.path.join(self._snap_path, cam)
        if not os.path.exists(path) or not os.path.isdir(path):
            return f"Can't get snapshot for unknown cam {cam}", 404

        fpath = os.path.join(path, file)
        if not os.path.exists(fpath) or not os.path.isfile(fpath):
            return f"Can't get unknown snapshot {file} for cam {cam}", 404

        return send_from_directory(path, file)
