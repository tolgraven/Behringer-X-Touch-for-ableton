"""Pure Python tests; no Ableton installation or audio engine is required."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / 'XTouch' / 'ClipScrubber.py'
spec = importlib.util.spec_from_file_location('clip_scrubber_test_target', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ClipScrubber = module.ClipScrubber
decode_mcu_delta = module.decode_mcu_delta


class Clip:
    def __init__(self, events=None, name='clip', **values):
        self.is_audio_clip = True
        self.warping = True
        self.is_recording = False
        self.is_overdubbing = False
        self.is_take_lane_clip = False
        self.looping = False
        self.start_marker = 0.0
        self.end_marker = 16.0
        self.loop_start = 4.0
        self.loop_end = 8.0
        self.is_playing = False
        self.playing_position = 0.0
        self.events = events if events is not None else []
        self.name = name
        self.scrubs = []
        self.stops = 0
        self.fail_scrub = False
        self.fail_stop = False
        self.__dict__.update(values)

    def scrub(self, position):
        self.events.append((self.name, 'scrub', position))
        self.scrubs.append(position)
        if self.fail_scrub:
            raise RuntimeError('simulated scrub failure')

    def stop_scrub(self):
        self.events.append((self.name, 'stop'))
        self.stops += 1
        if self.fail_stop:
            raise RuntimeError('simulated deleted clip')


class ClipScrubberTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(now=0.0)
        self.clip = Clip()
        self.recording = False
        self.messages = []
        self.scrubber = ClipScrubber(
            lambda: self.clip, lambda: self.recording,
            self.messages.append, clock=lambda: self.clock.now,
        )

    def test_signed_bit_magnitudes_and_both_zero_encodings(self):
        for value, expected in ((0, 0), (64, 0), (1, 1), (63, 63), (65, -1), (127, -63)):
            with self.subTest(value=value):
                self.assertEqual(decode_mcu_delta(value), expected)

    def test_all_128_midi_values_decode(self):
        for value in range(128):
            expected = value if value < 64 else -(value - 64)
            self.assertEqual(decode_mcu_delta(value), expected)

    def test_invalid_midi_values_rejected(self):
        for value in (-1, 128, None, 1.0, True, '1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_mcu_delta(value)

    def test_forward_reverse_and_accelerated_magnitude(self):
        self.clip.start_marker = 2.0
        for value in (4, 65, 1):
            self.scrubber.move(value)
        self.assertEqual(self.clip.scrubs, [2.25, 2.1875, 2.25])

    def test_modifiers_applied_once(self):
        for fine, coarse, expected in ((False, False, 1/16), (True, False, 1/64),
                                        (False, True, 1/4), (True, True, 1/16)):
            with self.subTest(fine=fine, coarse=coarse):
                self.scrubber.reset()
                self.scrubber.move(1, fine=fine, coarse=coarse)
                self.assertEqual(self.clip.scrubs[-1], expected)

    def test_playing_clip_uses_current_clip_time_without_playback_multiplier(self):
        self.clip.is_playing = True
        self.clip.playing_position = 5.0
        self.scrubber.move(1)
        self.assertEqual(self.clip.scrubs, [5.0625])

    def test_negative_clip_time_is_not_forced_to_zero(self):
        self.clip.start_marker = -4.0
        self.scrubber.move(1)
        self.assertEqual(self.clip.scrubs, [-3.9375])

    def test_loop_and_marker_bounds_clamp_both_directions(self):
        for looping, lower, upper in ((False, 0, 16), (True, 4, 8)):
            with self.subTest(looping=looping):
                self.scrubber.reset()
                self.clip.looping = looping
                self.scrubber.move(127, coarse=True)
                self.assertEqual(self.clip.scrubs[-1], lower)
                self.scrubber.move(63, coarse=True)
                self.scrubber.move(63, coarse=True)
                self.assertGreater(self.clip.scrubs[-1], upper - 0.001)
                self.assertLess(self.clip.scrubs[-1], upper)

    def test_marker_changes_are_applied_on_next_motion(self):
        self.scrubber.move(63)
        self.clip.end_marker = 1.0
        self.scrubber.move(1)
        self.assertLess(self.clip.scrubs[-1], 1.0)

    def test_idle_uses_elapsed_time_and_retains_cursor(self):
        self.scrubber.move(4)
        self.clock.now = 0.249
        for _ in range(20):
            self.scrubber.tick()
        self.assertEqual(self.clip.stops, 0)
        self.clock.now = 0.25
        self.scrubber.tick()
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)
        self.clock.now = 10.0
        self.scrubber.move(1)
        self.assertEqual(self.clip.scrubs[-1], 0.3125)

    def test_new_motion_renews_timeout(self):
        self.scrubber.move(1)
        self.clock.now = 0.2
        self.scrubber.move(1)
        self.clock.now = 0.3
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 0)
        self.clock.now = 0.5
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)

    def test_zero_events_do_not_scrub_or_renew_timeout(self):
        self.scrubber.move(0)
        self.scrubber.move(64)
        self.assertEqual(self.clip.scrubs, [])
        self.scrubber.move(1)
        self.clock.now = 0.2
        self.scrubber.move(64)
        self.clock.now = 0.25
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)

    def test_clip_change_stops_old_before_scrubbing_new(self):
        events = []
        old = self.clip = Clip(events, 'old')
        self.scrubber.move(1)
        self.clip = Clip(events, 'new', start_marker=2)
        self.scrubber.move(1)
        self.assertEqual(events, [('old', 'scrub', .0625), ('old', 'stop'), ('new', 'scrub', 2.0625)])
        self.assertEqual(old.stops, 1)

    def test_selection_change_without_motion_stops_on_tick(self):
        old = self.clip
        self.scrubber.move(1)
        self.clip = None
        self.scrubber.tick()
        self.assertEqual(old.stops, 1)

    def test_reset_is_immediate_idempotent_and_discards_cursor(self):
        self.scrubber.move(4)
        self.scrubber.reset()
        self.scrubber.reset()
        self.assertEqual(self.clip.stops, 1)
        self.scrubber.move(1)
        self.assertEqual(self.clip.scrubs[-1], .0625)

    def test_reset_after_idle_does_not_stop_twice(self):
        self.scrubber.move(1)
        self.clock.now = 1.0
        self.scrubber.tick()
        self.scrubber.reset()
        self.assertEqual(self.clip.stops, 1)

    def test_unsupported_clips_noop_and_report_reason(self):
        for values, message in (({'is_audio_clip': False}, 'Audio only'),
                                ({'warping': False}, 'Warp clip'),
                                ({'is_recording': True}, 'Recording'),
                                ({'is_overdubbing': True}, 'Recording'),
                                ({'is_take_lane_clip': True}, 'Take lane')):
            with self.subTest(values=values):
                self.scrubber.reset()
                self.clip = Clip(**values)
                self.scrubber.move(1)
                self.assertEqual(self.clip.scrubs, [])
                self.assertEqual(self.messages[-1], message)

    def test_missing_clip_deduplicates_notice(self):
        self.clip = None
        self.scrubber.move(1)
        self.scrubber.move(1)
        self.assertEqual(self.messages, ['No clip'])

    def test_recording_rejected_and_starting_recording_cleans_up(self):
        self.scrubber.move(1)
        self.recording = True
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)
        self.scrubber.move(1)
        self.assertEqual(len(self.clip.scrubs), 1)
        self.assertEqual(self.messages[-1], 'Recording')

    def test_unwarping_active_clip_stops_it(self):
        self.scrubber.move(1)
        self.clip.warping = False
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)

    def test_invalid_or_nonfinite_ranges_do_not_reach_scrub(self):
        for lower, upper in ((0, 0), (2, 1), (float('nan'), 4), (0, float('inf'))):
            with self.subTest(lower=lower, upper=upper):
                self.scrubber.reset()
                self.clip = Clip(start_marker=lower, end_marker=upper)
                self.scrubber.move(1)
                self.assertEqual(self.clip.scrubs, [])
                self.assertEqual(self.messages[-1], 'Scrub err')

    def test_scrub_exception_attempts_cleanup_and_allows_recovery(self):
        self.clip.fail_scrub = True
        self.scrubber.move(1)
        self.assertEqual(self.clip.stops, 1)
        self.clip.fail_scrub = False
        self.scrubber.move(1)
        self.assertEqual(self.clip.scrubs[-1], .0625)

    def test_deleted_clip_does_not_break_reset_or_tick(self):
        self.scrubber.move(1)
        self.clip.fail_stop = True
        self.scrubber.reset()
        self.scrubber.reset()
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)

    def test_deleted_proxy_getter_is_contained(self):
        self.scrubber.move(1)
        def deleted():
            raise ReferenceError('deleted proxy')
        self.scrubber._get_clip = deleted
        self.scrubber.tick()
        self.assertEqual(self.clip.stops, 1)
        self.assertEqual(self.messages[-1], 'Scrub err')


if __name__ == '__main__':
    unittest.main()
