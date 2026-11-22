"""Cheap frame checks: day/night classification and a motion delta, both on a 160x120 thumbnail (~1 ms).

The delta is the number of pixels whose grey level changed by more than CHANGE_LEVELS, after scaling the
second frame to the first one's mean brightness (cloud shadows, auto-exposure and the IR switch shift the
whole frame). It is a count, not a fraction: a face turning towards the camera moves only a few thumbnail
pixels. It only ever lets the pipeline skip work; it never fires an event.

No ignore mask: masks learned from empty clips came out empty. In daytime nothing (trees included) changes
often enough at this threshold; at night the IR noise is spread over the whole frame.
"""
import cv2
import numpy as np

THUMB_W, THUMB_H = 160, 120
CHANGE_LEVELS = 15


def thumb(frame):
    """BGR frame -> (grey float32 thumbnail, is_night). IR night mode produces (near) greyscale frames."""
    small = cv2.resize(frame, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
    s = small.astype(np.int16)
    sat = np.abs(s[:, :, 0] - s[:, :, 1]).mean() + np.abs(s[:, :, 1] - s[:, :, 2]).mean()
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32), bool(sat < 3)


def delta(a, b):
    """Number of pixels that changed between thumbnails a and b, brightness-normalised."""
    mb = b.mean()
    scaled = b * (a.mean() / mb) if mb > 1 else b
    return int((np.abs(a - scaled) > CHANGE_LEVELS).sum())
