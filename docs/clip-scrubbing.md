# Jog-wheel clip scrubbing

This adds native `Clip.scrub(beat_time)` control to the existing XTouch surface.
It is audible clip seeking using Live's mouse-scrub behavior, **not** a Traktor
platter, reverse playback, or a whole-Arrangement varispeed engine. No Max for
Live device, additional MIDI mapping, IAC port, or renamed surface is required.

## Controls

| Context / gesture | Behavior |
| --- | --- |
| Arrangement: press SCRUB | Toggle native clip-scrub mode; its LED shows the mode. Press again to stop scrubbing and return to ordinary seeking. |
| Either view: hold Shift, press and hold SCRUB | Momentary clip-scrub clutch. Release SCRUB to end the current scrub immediately, even if Shift was released first. A pre-existing Arrangement latch remains latched. |
| Scrub mode + wheel | Move the clip-time cursor by `1/16` beat per MCU increment, retaining the encoder's magnitude and direction. |
| Scrub mode + Alt + wheel | Fine: `1/64` beat per increment. |
| Scrub mode + Shift + wheel | Coarse: `1/4` beat per increment. Shift + Alt combines to the normal increment. |
| No scrub mode | Existing jog behavior is unchanged. |
| Control / Option / zoom / settings menu | Existing tempo, loop, zoom and menu behavior takes priority. |
| Session: SCRUB without Shift | Existing scene launch; Option + SCRUB still stops all clips. |

Shift remains the coarse modifier while held. For a normal-speed clutch, hold
Shift, press SCRUB, then release Shift while continuing to hold SCRUB.

Here a beat is one quarter note: `1/16` beat is not a sixteenth note.
The logical SCRUB button follows the script's existing layout preference,
including the alternative assignment to the physical SOLO button.

## Target and boundaries

The target is `song.view.detail_clip`, the clip displayed in Detail View. In
Session only, an empty Detail View may fall back to the highlighted Session
slot. An Arrangement operation never falls back to a hidden Session slot.

Only warped audio clips are supported. MIDI clips, unwarped audio, take-lane
clips, missing/deleted clips, and recording/overdub states are rejected with a
short controller display notice. There is **no** silent fallback to a coarse
Arrangement jump. Turn scrub mode off for ordinary Arrangement navigation.

The cursor begins at the clip's playing position when playing, otherwise its
start marker. It is clamped to the loop bounds when looping, or the start/end
markers otherwise. The end marker is treated as exclusive. Negative clip beat
times are valid. No clip markers, warp settings, tempo, or quantization are
changed by the clip-scrub path.

The cursor survives idle gaps until the target or control context is reset.
After 250 ms without wheel movement, the next Live display callback calls
`stop_scrub()`. This is elapsed-time-based, not a fixed number of display ticks;
the effective timeout includes Live's callback scheduling delay. Both MCU zero
encodings (`0` and `64`) are ignored and do not renew the timeout.

Scrub ownership is also released on target change, mode/clutch exit, transport
commands, view changes, settings entry, refresh and disconnect. A Detail View
selection listener handles target changes immediately; timer checks also catch
changes in the Session-slot fallback and invalidated clips. No worker thread
calls the Live API.

## What this does not guarantee

`stop_scrub()` releases the native scrub operation; it is not `clip.stop()` or
`song.stop_playing()`. Normal playback may continue afterward. This feature does
not forcibly start or stop the entire transport, restore a prior playback
state, or guarantee silence when the wheel stops. Native scrubbing can affect
playback in the same way as mouse scrubbing, so test on a duplicate Set first.

Global Quantization is respected. For a first test, set it manually to **None**
or a small interval such as **1/32**. Long quantization intervals may postpone
an audible result past the idle timeout. Changing Warp mode to Re-Pitch does
not make wheel velocity control playback speed or implement reverse playback.

The implementation does not change XTouchXT, bank linking, faders, display
routing, MCU MIDI routing, or the surface's package name.

## Install / revert on macOS

Quit Live and back up the installed `XTouch` folder **outside** Remote Scripts.
From a checkout of this branch, copy `XTouch/ClipScrubber.py` and the updated
`XTouch/Transport.py` into the existing `XTouch` folder in your User Library's
`Remote Scripts` directory. Keep the package named `XTouch`; leave `XTouchXT`
and its existing control-surface row unchanged. Use the actual location of your
User Library, which may differ from the default.

Restart Live with the existing `XTouch` surface selected. Do not add a second
surface or a manual CC 60 mapping on the same input. To revert, quit Live,
restore the backed-up `Transport.py`, remove the added `ClipScrubber.py`, and
restart Live.

## Automated tests

From the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile XTouch/ClipScrubber.py XTouch/Transport.py
```

The suite uses only the standard library. `test_clip_scrubber.py` tests the
cursor, MIDI decoder and lifecycle against fake clips and a fake clock.
`test_transport_scrub.py` imports the actual `Transport.py` with a stub Live
host, base component and constants to test callback routing. These are not
hardware tests and do not validate audio, quantization timing or physical LED
behavior. No Ableton runtime or controller was available during implementation.

## Manual acceptance checklist — not yet performed

- [ ] In a duplicate Set, choose a warped audio clip with distinctive transients; set Global Quantization to None and enable SCRUB in Arrangement. Verify audible seeking in both wheel directions, without interpreting reverse seeking as reverse audio playback.
- [ ] Verify normal / Alt / Shift steps, including while transport is running, and verify that the cursor does not snap back after pausing the wheel.
- [ ] Exercise Shift + SCRUB in both views; release Shift first, then SCRUB. Check immediate scrub release and the correct LED state.
- [ ] Change/delete the target while moving the wheel. Verify the previous scrub ends; test a playing clip, a stopped clip, negative beat times, and loop boundaries.
- [ ] Test MIDI/unwarped/no-clip/recording targets. Check the notice and ensure no hidden Session clip launches and no Arrangement jump occurs.
- [ ] Press Stop, switch views, enter settings, refresh/reload the script, and disconnect the controller during scrubbing. Check for stale scrub playback and errors in Live's Log.txt.
- [ ] Check original Session scene launch/stop-all, scene scrolling, Control tempo, Option loop edits, zoom, both button layouts and the XTouchXT bank link.
- [ ] Compare Global Quantization None / 1/32 / 1 Bar, then confirm what normal playback does after `stop_scrub()` on the installed Live version.

## API references

- [Clip.scrub and Clip.stop_scrub](https://docs.cycling74.com/apiref/lom/clip/#scrub): native mouse-style scrubbing in beats, respecting Global Quantization.
- [Clip time units](https://docs.cycling74.com/apiref/lom/clip/#playing_position): warped/MIDI clip positions use beats, unwarped positions use seconds. This implementation intentionally rejects unwarped clips rather than guessing a conversion.
- [Song.scrub_by](https://docs.cycling74.com/apiref/lom/song/#scrub_by): documented as equivalent to `jump_by` at present.
- [Song.View.detail_clip](https://docs.cycling74.com/apiref/lom/song_view/#detail_clip): observable Detail View clip selection.
