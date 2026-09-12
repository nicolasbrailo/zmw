"""FFmpeg helper functions for RTSP recording and reencoding."""
import os
import tempfile
import subprocess

from zzmw_lib.logs import build_logger
log = build_logger("FFmpegHelper")

def _run_cmd(cmd):
    stdout = tempfile.TemporaryFile(mode='w+')
    stderr = tempfile.TemporaryFile(mode='w+')
    try:
        proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
    except OSError as e:
        # OSError covers FileNotFoundError, PermissionError, and other OS-level failures
        log.error("Failed to run command %s: %s", cmd[0] if cmd else "<empty>", e)
        stdout.close()
        stderr.close()
        return None, None, None
    return proc, stdout, stderr


def rtsp_to_local_file(rtsp_url, outpath):
    """Start recording from RTSP stream to local file."""
    return _run_cmd(["ffmpeg",
                     "-i", rtsp_url,
                     # Copy incoming streams, otherwise ffmpeg will try to reencode (and spend tons of cpu)
                     "-c:v", "copy", "-c:a", "copy",
                     outpath])


def reencode_to_telegram_vid(fpath, reencode_out_file):
    """Reencode video to Telegram-compatible format (640x360 x264)."""
    return _run_cmd(["ffmpeg",
                     "-i", fpath,
                     # Eg to reencode @ 720p
                     # "-vf", "scale=-1:720",
                     # Telegram format
                     "-vf", "scale=640:360",
                     "-c:v", "libx264",
                     "-crf", "23",
                     "-preset", "veryfast",
                     "-c:a", "copy",
                     reencode_out_file,
                     ])


def get_thumbnail_path(fpath):
    """Path where the thumbnail for a video file is stored."""
    return f'{fpath}.thumb.png'


def gen_thumbnail_from_video(fpath, timeout_secs=30):
    """Generate a thumbnail image from video file. Blocks until ffmpeg is done."""
    if not isinstance(fpath, str) or not fpath.endswith('.mp4'):
        log.error("Requested thumbnail for non-movie %s", fpath)
        return None

    fout = get_thumbnail_path(fpath)
    if os.path.exists(fout):
        return fout

    proc, stdout, stderr = _run_cmd(['ffmpeg',
                                     # Don't read stdin (eg for an overwrite prompt), and overwrite partial output
                                     '-nostdin', '-y',
                                     # Single decoder thread, a thumbnail isn't worth using all cores
                                     '-threads', '1',
                                     '-i', fpath,
                                     # Commas in a filter expression must be escaped, or they split the filtergraph
                                     '-vf', r'select=eq(n\,42),scale=192:168',
                                     '-frames:v', '1',
                                     fout])
    if proc is None:
        return None

    try:
        proc.wait(timeout_secs)
    except subprocess.TimeoutExpired:
        log.error("Thumbnail for %s not ready after %s seconds, killing ffmpeg", fpath, timeout_secs)
        proc.kill()
        proc.wait()

    ok = proc.returncode == 0 and os.path.exists(fout)
    if not ok:
        stderr.seek(0)
        log.error("Failed to generate thumbnail for %s, ret=%s: %s", fpath, proc.returncode, stderr.read()[-2000:])
        if os.path.exists(fout):
            os.remove(fout)

    stdout.close()
    stderr.close()
    return fout if ok else None
