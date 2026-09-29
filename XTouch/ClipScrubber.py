"""Native clip scrubbing; Live API calls must stay on Live's callback thread.

This moves a clip-time cursor. It is not a reverse/varispeed audio engine.
See https://docs.cycling74.com/apiref/lom/clip/#scrub.
"""

import math
import time


BEATS_PER_STEP = 1.0 / 16.0
IDLE_SECONDS = 0.25
LIVE_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError)


def decode_mcu_delta(value):
    """Decode the MCU signed-bit magnitude, including both zero encodings."""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 127:
        raise ValueError("Expected a 7-bit MCU value")
    magnitude = value & 0x3f
    return -magnitude if value & 0x40 else magnitude


class ClipScrubber(object):
    """Own at most one scrub and retain its cursor across wheel-idle gaps.

    get_clip returns the visible target; recording returns whether the Set is
    recording. Injecting a monotonic clock keeps tests independent of Live's
    display callback cadence. report accepts a short controller display message.
    """

    def __init__(self, get_clip, recording, report, clock=time.monotonic):
        self._get_clip = get_clip
        self._recording = recording
        self._report = report
        self._clock = clock
        self._clip = None
        self._position = None
        self._active = False
        self._last_motion = None
        self._last_message = None

    def reset(self):
        """Release ownership immediately; safe on repeated calls or deletion."""
        self._stop(forget=True)
        self._last_message = None

    def move(self, value, fine=False, coarse=False):
        delta = decode_mcu_delta(value)
        if not delta:
            return
        try:
            clip = self._get_clip()
            problem = self._problem(clip)
            if problem:
                self._stop(forget=True)
                self._notice(problem)
                return

            lower, upper = self._bounds(clip)
            if clip != self._clip:
                self.reset()  # stop the old clip BEFORE acquiring the new one
                self._clip = clip
                position = clip.playing_position if clip.is_playing else clip.start_marker
                if not math.isfinite(position):
                    raise ValueError("Non-finite clip position")
                self._position = max(lower, min(upper, position))

            step = BEATS_PER_STEP * (0.25 if fine else 1.0) * (4.0 if coarse else 1.0)
            self._position = max(lower, min(upper, self._position + delta * step))
            self._last_motion = self._clock()
            self._active = True  # permit cleanup even if scrub() partially fails
            clip.scrub(self._position)
            self._last_message = None
        except LIVE_ERRORS as error:
            self._stop(forget=True)
            self._notice("Scrub err", error)

    def tick(self):
        """Called by Live's display timer, never by a background Python thread."""
        if self._clip is None:
            return
        try:
            if self._get_clip() != self._clip or self._problem(self._clip):
                self.reset()
                return
            # Validate edited markers and clamp the next movement to new bounds.
            self._bounds(self._clip)
            if self._active and self._clock() - self._last_motion >= IDLE_SECONDS:
                self._stop(forget=False)
        except LIVE_ERRORS as error:
            self._stop(forget=True)
            self._notice("Scrub err", error)

    def _problem(self, clip):
        if self._recording():
            return "Recording"
        if clip is None:
            return "No clip"
        if not clip.is_audio_clip:
            return "Audio only"
        if not clip.warping:
            # Unwarped marker/playhead units are seconds, but scrub takes beats.
            return "Warp clip"
        if clip.is_recording or clip.is_overdubbing:
            return "Recording"
        if getattr(clip, "is_take_lane_clip", False):
            return "Take lane"
        return None

    @staticmethod
    def _bounds(clip):
        if clip.looping:
            lower, end = clip.loop_start, clip.loop_end
        else:
            lower, end = clip.start_marker, clip.end_marker
        if not math.isfinite(lower) or not math.isfinite(end) or end <= lower:
            raise ValueError("Invalid clip range")
        # Avoid seeking exactly onto the exclusive end marker.
        upper = end - min(1e-6, (end - lower) / 2.0)
        return lower, upper

    def _stop(self, forget):
        clip, active = self._clip, self._active
        self._active = False
        self._last_motion = None
        if forget:
            self._clip = None
            self._position = None
        if active and clip is not None:
            try:
                clip.stop_scrub()
            except LIVE_ERRORS as error:
                self._notice("Scrub err", error)

    def _notice(self, message, error=None):
        if message != self._last_message:
            self._last_message = message
            if error is not None:
                print("XTouch clip scrub: {}".format(error))
            self._report(message)
