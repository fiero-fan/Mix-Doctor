---
name: vocal-to-midi
description: Transcribe the melody of a raw sung vocal into MIDI (notes, timing, accuracy score) and put it into Ableton Live, e.g. as the Robot Carrier melody for the Daft Robot vocoder. Use when the user asks to transcribe, map, or extract the melody from their voice or a vocal clip, or to "make the Daft robot" from a take.
---

# Vocal → MIDI

The user is a musician, not an engineer: keep replies short, in musical words, and say what you heard.

## 1. Find the recording
- Clip in Live: `python3 tools/live.py get_track_info '{"track_index": N}'` lists clips (name, slot, length in beats).
- The audio file: recorded takes live in `<Live project>/Samples/Recorded/` (projects are in `~/AI/Ableton 2026/`). A clip named "voce 2" usually maps to `voce 0002 [...].wav`. To be sure, read the saved set: `.als` is gzipped XML; each `AudioClip` has `Name` and `SampleRef/FileRef/Path`. Ask the user to save (Cmd+S) if the clip is newer than the `.als`.
- Files are often 24-bit. Load audio through `mix_doctor.load_audio` or librosa, never raw `wavfile` + `/32768`.

## 2. Transcribe
```bash
python3 tools/vocal_to_midi.py "<take.wav>" --bpm <Live tempo> [--beats <clip length>] [--grid 0.25] [--key A:minor] [--mid out.mid]
```
- pYIN pitch tracking, notes split on attacks and pitch jumps, pitch = the stable middle of each note, octave slips fixed against the neighbouring notes.
- Default timing is the singer's real phrasing; `--grid 0.25` snaps to 16ths (costs a few % accuracy). `--key` snaps to a scale.
- It prints **accuracy** (share of sung time where the MIDI note is within 50 cents of the voice) and **coverage**. On this user's takes: 80–89% accuracy, about 90%+ coverage. Under ~70% means slides or vibrato, or a wrong pitch floor: `pitch_track(fmin=80)` suits a voice whose low notes are around E2 in Live names (MIDI 52).

## 3. Into Live (Daft Robot)
```bash
python3 tools/robot_melody.py "<take.wav>" --voice-track <voice track name> --voice-slot <slot> --name "<clip> melody"
```
It uses `vocal_to_midi` by default, takes the clip length from the voice clip, creates or reuses the **Robot Carrier** track (clean saw: detune and drive off), writes the notes into the next free slot, and starts it together with the vocal. Then the voice track needs the **Daft Robot** rack, with the Vocoder's carrier set to External → Robot Carrier and Robot Carrier's Audio To on Sends Only (Live can't store that source in a preset; carrier type 1 = External).

## 4. Check by ear and by measurement
- Nothing is soloed by default: solo the voice track, or pause the other clips (`stop_clip`, record, `fire_clip`) before recording BlackHole. Live's output must be **Main Output** for BlackHole to hear it.
- A clean vocoder robot should not clip: Vocoder output around −9 dB with a saw carrier.
- Fix single wrong notes in the clip (`add_notes_to_clip` / `clear_notes_from_clip`) when the user says where it sounds wrong.
