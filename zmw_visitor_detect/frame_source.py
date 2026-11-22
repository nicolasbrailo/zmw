"""Decoded frames from an RTSP stream, sampled at a fixed fps by ffmpeg.

The first seconds of a stream are usually the most valuable (someone walking up to the door), so startup keeps
everything: a single ffmpeg connection (the frame size comes from the yuv4mpeg header, no separate probe), and
the frames ffmpeg decodes in a burst after its stream analysis are queued, not dropped. The queue holds up to
`backlog_s` of frames; when the analysis falls further behind, the oldest frames are dropped (counted in
`dropped`). Frame times are stream times (n / fps), so a burst keeps its real spacing.

Decoding uses the GPU (VA-API) when HwDecoder says it works, else the CPU. A GPU decode that fails before the
first frame switches GPU decoding off for the service and the session restarts on the CPU, so a broken driver
costs one failed attempt, not a lost session.

A recorded clip can be injected as if it were the stream (`injected`, decoded at real-time pace), to test the
service end to end.

RTSP URLs carry credentials: they are never logged, and ffmpeg's stderr is redacted before logging.
"""
import logging
import os
import queue
import re
import subprocess
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("FrameSource")

# ffmpeg's stream analysis before the first frame (its defaults are 5 s / 5 MB). Packets read while analysing are
# still decoded afterwards, so this only adds latency, never loses frames. Video only: no audio to analyse.
RTSP_INPUT_OPTS = ['-rtsp_transport', 'tcp', '-allowed_media_types', 'video',
                   '-analyzeduration', '1000000', '-probesize', '1000000']
HW_SELF_TEST_TIMEOUT_S = 10
_CLK_TCK = os.sysconf('SC_CLK_TCK')


class FrameSourceError(Exception):
    pass


def _proc_cpu_s(pid):
    """CPU seconds (user + system) used so far by a running or exited-but-not-reaped process, None if gone."""
    try:
        with open(f'/proc/{pid}/stat') as f:
            fields = f.read().rsplit(')', 1)[1].split()
    except OSError:
        return None
    # After the command name: state is field 3 of proc(5), utime 14, stime 15
    return (int(fields[11]) + int(fields[12])) / _CLK_TCK


def _strip_ffmpeg_prefix(line):
    """'[VAAPI @ 0x55...] No VA display found.' -> 'No VA display found'"""
    return re.sub(r'^(\[[^]]*\]\s*)+', '', line).rstrip('.')


class HwDecoder:
    """Whether video is decoded on the GPU (VA-API). One per service: tested once at startup, and switched off for
    good when a session's GPU decode fails."""

    def __init__(self, mode='vaapi', device='/dev/dri/renderD128'):
        self.device = device
        self.active = False
        self.reason = None
        if mode == 'off':
            self.reason = 'disabled in config (hw_decode: "off")'
        elif mode == 'vaapi':
            self._self_test()
        else:
            self._fail_at_startup(f'hw_decode is "{mode}", must be "vaapi" or "off"')

    def _self_test(self):
        # Opens the device and uploads a frame: fails when the driver is missing or the device isn't accessible
        # (the service user must be in the device's group, usually "render")
        cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-init_hw_device', f'vaapi=va:{self.device}',
               '-filter_hw_device', 'va', '-f', 'lavfi', '-i', 'testsrc=size=256x256:rate=1',
               '-vf', 'format=nv12,hwupload', '-frames:v', '1', '-f', 'null', '-']
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=HW_SELF_TEST_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as ex:
            self._fail_at_startup(f'GPU self test failed: {ex}')
            return
        if out.returncode != 0:
            # ffmpeg's first error is the cause (eg "No VA display found": no driver, or no access to the device)
            lines = [l for l in out.stderr.strip().splitlines() if l.strip()]
            cause = _strip_ffmpeg_prefix(lines[0]) if lines else f'ffmpeg exited with {out.returncode}'
            self._fail_at_startup(f'GPU self test failed: {cause}. Needs a VA driver (Intel: intel-media-va-driver) '
                                  f'and the service user in the group of {self.device} (make setup_gpu)')
            return
        self.active = True
        log.info("Video decoding on the GPU (VA-API, %s)", self.device)

    def _fail_at_startup(self, reason):
        # GPU decoding was asked for and doesn't work: an error, once, so a degraded service is noticed
        self.active = False
        self.reason = reason
        log.error("GPU video decoding unavailable, running in degraded mode (CPU decoding): %s", reason)

    def disable(self, reason):
        """A session's GPU decode failed after the startup self test passed: CPU from now on."""
        self.active = False
        self.reason = reason
        log.warning("Video decoding on the CPU: %s", reason)

    def input_opts(self):
        # Frames stay on the GPU until the fps filter has picked the ones to keep; only those are downloaded
        return ['-hwaccel', 'vaapi', '-hwaccel_device', self.device, '-hwaccel_output_format', 'vaapi']

    def status(self):
        return {'decoder': 'gpu' if self.active else 'cpu', 'device': self.device, 'reason': self.reason}


class FrameSource:
    def __init__(self, src, fps, backlog_s=3.0, hw=None):
        self._src = src
        self._is_rtsp = src.startswith('rtsp')
        self._fps = fps
        self._hw = hw
        self._proc = None
        self._reader = None
        self._stopped = False
        self._stderr_head = []   # ffmpeg's first error lines: the first one names the cause
        # Frames are queued as YUV 4:2:0 (half the size of BGR) and converted when taken
        self._frames = queue.Queue(maxsize=max(1, int(backlog_s * fps)))
        self._started = None
        self.decoder = None
        self.size = None
        self.dropped = 0
        self.decoded = 0
        self.error = None
        # Seconds from starting ffmpeg to the first decoded frame, and the largest delay between a frame being
        # decoded and the analysis taking it
        self.first_frame_s = None
        self.first_frame_at = None   # wall clock (time.time()) of the first frame
        self.max_lag_s = 0.0
        self._decode_cpu = {}   # ffmpeg pid -> CPU seconds (a GPU fallback runs a second ffmpeg)

    @staticmethod
    def rtsp(url, fps, backlog_s=3.0, hw=None):
        return FrameSource(url, fps, backlog_s, hw)

    @staticmethod
    def injected(path, fps, backlog_s=3.0, hw=None):
        """A recorded clip played as if it were the live stream, at real-time pace."""
        if not os.path.isfile(path):
            raise FrameSourceError(f"No such file {path}")
        return FrameSource(path, fps, backlog_s, hw)

    def _start(self, use_gpu):
        self.decoder = 'gpu' if use_gpu else 'cpu'
        self.error = None
        # One decode thread on the CPU: ~10x faster than real time on the main stream, and less than half the CPU
        # of the default threading, which competes with the models
        cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1']
        if use_gpu:
            cmd += self._hw.input_opts()
        if self._is_rtsp:
            cmd += RTSP_INPUT_OPTS
        else:
            # Injected clip: decode at the clip's own speed, like the camera would deliver it
            cmd += ['-re']
        vf = f'fps={self._fps},hwdownload,format=nv12' if use_gpu else f'fps={self._fps}'
        cmd += ['-i', self._src, '-an', '-vf', vf, '-pix_fmt', 'yuv420p', '-f', 'yuv4mpegpipe', '-']
        self._started = time.monotonic()
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=self._log_stderr, args=(self._proc,), daemon=True).start()
        self._reader = threading.Thread(target=self._read, args=(self._proc,), daemon=True)
        self._reader.start()

    def frames(self):
        """Yields (t_secs, BGR frame). t is the frame's time in the stream (n / fps) since the first frame."""
        self._start(self._hw is not None and self._hw.active)
        try:
            while True:
                try:
                    t, decoded_at, yuv = self._frames.get(timeout=1)
                except queue.Empty:
                    if self._stopped:
                        return
                    if self._reader.is_alive():
                        continue
                    if self.decoder == 'gpu' and self.first_frame_s is None:
                        cause = _strip_ffmpeg_prefix(self._stderr_head[0]) if self._stderr_head else self.error
                        self._hw.disable(f'GPU decode failed: {cause}')
                        self._start(False)
                        continue
                    return
                self.max_lag_s = max(self.max_lag_s, time.monotonic() - decoded_at)
                yield t, cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
        finally:
            self.stop()
            self._reader.join(timeout=5)

    @property
    def decode_cpu_s(self):
        """CPU seconds ffmpeg used so far (decoding, sampling, format conversion)."""
        if self._proc is not None and self._proc.returncode is None:
            self._sample_cpu(self._proc)
        return sum(self._decode_cpu.values())

    def _sample_cpu(self, proc):
        cpu = _proc_cpu_s(proc.pid)
        if cpu is not None:
            self._decode_cpu[proc.pid] = max(cpu, self._decode_cpu.get(proc.pid, 0.0))

    def stop(self):
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._sample_cpu(proc)
            # Kill rather than terminate: we don't need a clean shutdown, and it avoids broken pipe noise
            proc.kill()

    def _read(self, proc):
        try:
            self._read_frames(proc)
        except Exception as ex:  # pylint: disable=broad-except
            log.error("Reading frames from ffmpeg failed", exc_info=True)
            self.error = f'frame reader failed: {ex!r}'

    def _read_frames(self, proc):
        out = proc.stdout
        try:
            header = out.readline().decode(errors='replace').split()
            if not header or header[0] != 'YUV4MPEG2':
                if not self._stopped:
                    self._sample_cpu(proc)
                    self.error = f"ffmpeg exited with {proc.wait()} before the first frame"
                return
            w = int(next(p[1:] for p in header if p.startswith('W')))
            h = int(next(p[1:] for p in header if p.startswith('H')))
            self.size = (w, h)
            size = w * h * 3 // 2
            n = 0
            while not self._stopped:
                tag = out.readline()
                buf = out.read(size) if tag.startswith(b'FRAME') else b''
                if len(buf) < size:
                    # Before wait() reaps it: its CPU counters disappear with it
                    self._sample_cpu(proc)
                    if not self._stopped and proc.wait() != 0 and self.error is None:
                        self.error = f"ffmpeg exited with {proc.returncode}"
                    break
                now = time.monotonic()
                if self.first_frame_s is None:
                    self.first_frame_s = now - self._started
                    self.first_frame_at = time.time()
                item = (n / self._fps, now, np.frombuffer(buf, np.uint8).reshape(h * 3 // 2, w))
                n += 1
                self.decoded = n
                # Analysis too far behind: drop the oldest frame, keep the newest
                while True:
                    try:
                        self._frames.put_nowait(item)
                        break
                    except queue.Full:
                        try:
                            self._frames.get_nowait()
                            self.dropped += 1
                        except queue.Empty:
                            pass
        finally:
            out.close()

    def _log_stderr(self, proc):
        for line in proc.stderr:
            msg = line.decode(errors='replace').replace(self._src, '<stream>').strip()
            if msg:
                if len(self._stderr_head) < 3:
                    self._stderr_head.append(msg)
                log.warning("ffmpeg: %s", msg)
