"""Exercise the real Transport class with stand-ins for the Live host.

These verify callback routing, not the audio engine or physical MIDI hardware.
The imported base component and constants are stand-ins; their production files
are unchanged by this feature.
"""

import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_clip_scrubber import Clip

ROOT = Path(__file__).resolve().parents[1]


class Observable:
    def __init__(self, **values):
        self.listeners = {}
        self.__dict__.update(values)

    def __getattr__(self, name):
        if name.startswith('add_') and name.endswith('_listener'):
            event = name[4:-9]
            return lambda *args: self.listeners.setdefault(event, []).append(args[-1])
        if name.startswith('remove_') and name.endswith('_listener'):
            event = name[7:-9]
            return lambda *args: self.listeners[event].remove(args[-1])
        if name.endswith('_has_listener'):
            event = name[:-13]
            return lambda callback: callback in self.listeners.get(event, [])
        raise AttributeError(name)

    def emit(self, event):
        for callback in tuple(self.listeners.get(event, [])):
            callback()


class Component:
    def __init__(self, main):
        self.main = main

    def main_script(self):
        return self.main

    def song(self):
        return self.main.song

    def application(self):
        return self.main.application

    def control_is_pressed(self):
        return self.main.control

    def option_is_pressed(self):
        return self.main.option

    def alt_is_pressed(self):
        return self.main.alt

    def shift_is_pressed(self):
        return self.main.shift

    def send_button_led(self, note, value):
        self.main.leds.append((note, value))

    def destroy(self):
        self.main.destroyed = True


def load_transport():
    name = '_xtouch_scrub_tests'
    package = types.ModuleType(name)
    package.__path__ = [str(ROOT / 'XTouch')]
    component = types.ModuleType(name + '.MackieControlComponent')
    component.MackieControlComponent = Component
    source = (ROOT / 'XTouch' / 'Transport.py').read_text()
    constants = sorted({node.id for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.Name) and node.id.isupper()})
    for index, constant in enumerate(constants):
        setattr(component, constant, index + 1000)
    component.BUTTON_PRESSED = 1
    component.BUTTON_RELEASED = 0
    component.BUTTON_STATE_ON = 127
    component.BUTTON_STATE_OFF = 0
    component.BUTTON_STATE_BLINKING = 1
    component.SID_JOG_SCRUB = 101
    component.SID_TRANSPORT_SOLO = 90
    for group in ('transport_control_switch_ids', 'jog_wheel_switch_ids', 'marker_control_switch_ids'):
        setattr(component, group, [])
    component.Live = types.SimpleNamespace(Application=types.SimpleNamespace(
        Application=types.SimpleNamespace(View=types.SimpleNamespace(
            NavDirection=types.SimpleNamespace(up=0, down=1, left=2, right=3)))))
    past = types.ModuleType('past')
    past.__path__ = []
    past_utils = types.ModuleType('past.utils')
    past_utils.old_div = lambda a, b: a / b
    stubs = {name: package, name + '.MackieControlComponent': component,
             'past': past, 'past.utils': past_utils}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(name + '.Transport', ROOT / 'XTouch' / 'Transport.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


transport_module = load_transport()
Transport = transport_module.Transport


class TransportScrubTests(unittest.TestCase):
    def setUp(self):
        self.actions = []
        self.clip = Clip()
        self.now = 0.0
        self.session = False
        self.scene = types.SimpleNamespace(fire_as_selected=lambda: self.actions.append('scene'))
        self.slot = types.SimpleNamespace(
            has_clip=True, clip=self.clip, has_stop_button=True,
            fire=lambda: self.actions.append('clip'), stop=lambda: self.actions.append('clip-stop'))
        self.view = Observable(detail_clip=self.clip, highlighted_clip_slot=self.slot,
                               selected_scene=self.scene, follow_song=False)
        self.song = Observable(
            view=self.view, scenes=[self.scene], record_mode=False, session_record=False,
            is_playing=False, loop=False, punch_in=False, punch_out=False, metronome=False,
            can_jump_to_prev_cue=False, can_jump_to_next_cue=False,
            tempo=120.0, signature_numerator=4, loop_start=0.0, loop_length=16.0,
            jump_by=lambda delta: self.actions.append(('jump', delta)),
            scrub_by=lambda delta: self.actions.append(('song-scrub', delta)),
            stop_playing=lambda: self.actions.append('stop'),
            start_playing=lambda: self.actions.append('play'),
            continue_playing=lambda: self.actions.append('continue'),
            stop_all_clips=lambda: self.actions.append('stop-all'),
            jump_to_prev_cue=lambda: self.actions.append('prev-cue'),
        )
        self.app_view = Observable(
            is_view_visible=lambda name: self.session,
            zoom_view=lambda *args: self.actions.append(('zoom', args)),
            scroll_view=lambda *args: self.actions.append(('scroll', args)),
        )
        self.messages = []
        display = types.SimpleNamespace(
            show_priority_message=lambda message, duration: self.messages.append(message),
            show_permanent_message=lambda message: self.messages.append(message),
        )
        self.main = types.SimpleNamespace(
            song=self.song, application=types.SimpleNamespace(view=self.app_view),
            control=False, option=False, alt=False, shift=False, leds=[], destroyed=False,
            _preferences_spec={}, debug=False,
            get_debug_parameter_1=lambda: self.main.debug,
            get_metronome_blinks_in_time=lambda: False,
            time_display=lambda: display,
        )
        self.transport = Transport(self.main)
        self.transport._clip_scrubber._clock = lambda: self.now

    def button(self, name, pressed=True):
        self.transport.handle_jog_wheel_switch_ids(getattr(transport_module, name), int(pressed))

    def enable(self):
        self.button('SID_JOG_SCRUB')
        self.button('SID_JOG_SCRUB', False)

    def test_default_jog_is_unchanged(self):
        self.transport.handle_jog_wheel_rotation(1)
        self.transport.handle_jog_wheel_rotation(65)
        self.assertEqual(self.actions, [('jump', 1.0), ('jump', -1.0)])
        self.assertEqual(self.clip.scrubs, [])

    def test_scrub_toggle_uses_clip_not_song(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.clip.scrubs, [.0625])
        self.assertEqual(self.actions, [])
        self.button('SID_JOG_SCRUB')
        self.assertEqual(self.clip.stops, 1)
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.actions, [('jump', 1.0)])

    def test_modifier_scaling_is_not_doubled_while_playing(self):
        self.song.is_playing = True
        self.clip.is_playing = True
        self.clip.playing_position = 2.0
        self.enable()
        self.main.alt = True
        self.main.shift = True
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.clip.scrubs, [2.0625])

    def test_clutch_release_stops_immediately_even_after_shift_release(self):
        self.main.shift = True
        self.button('SID_JOG_SCRUB')
        self.main.shift = False
        self.transport.handle_jog_wheel_rotation(1)
        self.button('SID_JOG_SCRUB', False)
        self.assertEqual(self.clip.stops, 1)
        self.assertEqual(self.main.leds[-1], (transport_module.SID_JOG_SCRUB, 0))
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.actions, [('jump', 1.0)])

    def test_clutch_does_not_clear_preexisting_latched_mode(self):
        self.enable()
        self.main.shift = True
        self.button('SID_JOG_SCRUB')
        self.main.shift = False
        self.transport.handle_jog_wheel_rotation(1)
        self.button('SID_JOG_SCRUB', False)
        self.assertEqual(self.clip.stops, 1)
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(len(self.clip.scrubs), 2)
        self.assertEqual(self.actions, [])

    def test_control_still_changes_tempo_and_stops_active_scrub(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.main.control = True
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.song.tempo, 121.0)
        self.assertEqual(self.clip.stops, 1)

    def test_option_still_moves_arrangement_loop(self):
        self.enable()
        self.main.option = True
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.song.loop_start, 1.0)
        self.main.alt = True
        self.transport.handle_jog_wheel_rotation(65)
        self.assertEqual(self.song.loop_length, 15.0)
        self.assertEqual(self.clip.scrubs, [])

    def test_zoom_still_takes_precedence(self):
        self.enable()
        self.button('SID_JOG_ZOOM')
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.actions[0][0], 'zoom')
        self.assertEqual(self.clip.scrubs, [])

    def test_no_clip_does_not_fall_back_to_song_jump(self):
        self.view.detail_clip = None
        # A hidden Session slot must not become the Arrangement scrub target.
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.actions, [])
        self.assertEqual(self.clip.scrubs, [])
        self.assertEqual(self.messages, ['No clip'])

    def test_recording_and_unwarped_targets_never_fall_back_to_song_jump(self):
        self.enable()
        for record_mode, warped in ((True, True), (False, False)):
            self.song.record_mode = record_mode
            self.clip.warping = warped
            self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.actions, [])
        self.assertEqual(self.clip.scrubs, [])

    def test_session_scene_launch_and_option_stop_all_are_preserved(self):
        self.session = True
        self.button('SID_JOG_SCRUB')
        self.main.option = True
        self.button('SID_JOG_SCRUB')
        self.assertEqual(self.actions, ['scene', 'stop-all'])

    def test_session_clutch_scrubs_highlighted_slot_without_launching_scene(self):
        self.session = True
        self.view.detail_clip = None
        self.main.shift = True
        self.button('SID_JOG_SCRUB')
        self.main.shift = False
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.clip.scrubs, [.0625])
        self.assertEqual(self.actions, [])
        self.button('SID_JOG_SCRUB', False)
        self.assertEqual(self.clip.stops, 1)

    def test_session_jog_still_scrolls_scenes(self):
        self.session = True
        second = types.SimpleNamespace(fire_as_selected=lambda: None)
        self.song.scenes = [self.scene, second]
        for _ in range(4):
            self.transport.handle_jog_wheel_rotation(1)
        self.assertIs(self.view.selected_scene, second)
        self.assertEqual(self.clip.scrubs, [])

    def test_idle_callback_stops_scrub_but_keeps_cursor(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(4)
        self.now = .3
        self.transport.on_update_display_timer()
        self.assertEqual(self.clip.stops, 1)
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.clip.scrubs[-1], .3125)

    def test_detail_clip_listener_cleans_up_without_waiting_for_tick(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.view.detail_clip = Clip()
        self.view.emit('detail_clip')
        self.assertEqual(self.clip.stops, 1)

    def test_switching_views_cleans_up_and_unlatches_mode(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.session = True
        # Application visibility listeners carry the view name in Live.
        self.transport._Transport__on_session_is_visible_changed()
        self.assertEqual(self.clip.stops, 1)
        self.assertFalse(self.transport._Transport__scrub_button_down)

    def test_stop_button_cleans_up_before_stopping_transport(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.transport.handle_transport_switch_ids(transport_module.SID_TRANSPORT_STOP, 1)
        self.assertEqual(self.clip.stops, 1)
        self.assertEqual(self.actions, ['stop'])

    def test_external_transport_stop_cleans_up(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.song.emit('is_playing')
        self.assertEqual(self.clip.stops, 1)

    def test_refresh_cleans_up_and_clears_clutch(self):
        self.main.shift = True
        self.button('SID_JOG_SCRUB')
        self.transport.handle_jog_wheel_rotation(1)
        self.transport.refresh_state()
        self.assertEqual(self.clip.stops, 1)
        self.assertFalse(self.transport._scrub_clutch_down)

    def test_destroy_removes_the_new_listener_and_stops_scrub(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.transport.destroy()
        self.assertEqual(self.clip.stops, 1)
        self.assertEqual(self.view.listeners['detail_clip'], [])
        self.assertTrue(self.main.destroyed)

    def test_settings_entry_stops_scrub_and_preserves_menu_controls(self):
        self.enable()
        self.transport.handle_jog_wheel_rotation(1)
        self.main.shift = True
        self.button('SID_JOG_ZOOM')
        self.assertTrue(self.transport._in_settings_menu)
        self.assertEqual(self.clip.stops, 1)
        self.transport.handle_jog_wheel_rotation(1)
        self.button('SID_JOG_SCRUB')
        self.assertFalse(self.transport._scrub_clutch_down)
        self.assertEqual(len(self.clip.scrubs), 1)

    def test_alternative_layout_uses_assigned_scrub_button(self):
        self.main.debug = True
        self.transport.refresh_state()
        self.button('SID_TRANSPORT_SOLO')
        self.transport.handle_jog_wheel_rotation(1)
        self.assertEqual(self.clip.scrubs, [.0625])

    def test_zero_midi_events_never_seek(self):
        for value in (0, 64):
            self.transport.handle_jog_wheel_rotation(value)
        self.assertEqual(self.actions, [])


if __name__ == '__main__':
    unittest.main()
