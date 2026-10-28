#!/usr/bin/env python3
"""
Daft Punk-style robot, step 1: turn a sung clip into the synth melody that drives the vocoder.

Transcribes the vocal recording to MIDI (16th grid, one note at a time, folded into the
singer's range), then writes it into a "Robot Carrier" track playing a bright saw synth,
right after the voice track. Step 2 is the "Daft Robot" rack on the voice track with its
Vocoder carrier set to External -> Robot Carrier, and Robot Carrier's Audio To on Sends Only.

  python3 tools/robot_melody.py "path/to/voice.wav" --voice-track voce
  python3 tools/robot_melody.py take.wav --voice-track voce --low 48 --high 64 --synth "Mega Saw.adg"
"""
import argparse, json
import numpy as np
from scipy.signal import medfilt
from mix_doctor import load_audio
from live import call

NAMES = "C C# D D# E F F# G G# A A# B".split()


def transcribe(path, bpm, low, high, beats, gate=-120):
    x, sr = load_audio(path)
    x = x.mean(axis=1)
    spb, hop, N = 60 / bpm, 256, 2048
    t, f = [], []
    for i in range(0, len(x) - N, hop):
        s = x[i:i + N]
        t.append((i + N / 2) / sr)
        if np.sqrt(np.mean(s ** 2)) < 10 ** (gate / 20):
            f.append(-1); continue
        s = s - s.mean(); ac = np.correlate(s, s, "full")[N - 1:]
        lo, hi = int(sr / 900), int(sr / 70); k = lo + np.argmax(ac[lo:hi])
        f.append(round(69 + 12 * np.log2(sr / k / 440)) if ac[k] > 0.35 * ac[0] else -1)
    f = medfilt(np.array(f, dtype=float), 9)  # steady notes, ignore blips
    raw, cur = [], None
    for ti, n in zip(t, f):
        if cur and n == cur[0] and ti - cur[2] < 0.06:
            cur[2] = ti; continue
        if cur and cur[2] - cur[1] >= 0.09:
            raw.append(cur)
        cur = [n, ti, ti] if n > 0 else None
    if cur and cur[2] - cur[1] >= 0.09:
        raw.append(cur)
    # pass 1: snap to the 16th grid, joining repeats of the same detected note
    q, grid = 0.25, []
    for n, a, b in raw:
        s = round(a / spb / q) * q
        e = max(s + q, round((b + hop / sr) / spb / q) * q)
        if grid and grid[-1]["pitch"] == int(n) and s - (grid[-1]["start_time"] + grid[-1]["duration"]) <= q:
            grid[-1]["duration"] = e - grid[-1]["start_time"]; continue
        grid.append({"pitch": int(n), "start_time": s, "duration": e - s, "velocity": 100, "mute": False})
    # pass 2: fold overtone slips into the singer's range, then keep one note at a time
    for n in grid:
        while n["pitch"] > high: n["pitch"] -= 12
        while n["pitch"] < low: n["pitch"] += 12
    grid = [n for n in grid if n["start_time"] < beats]
    grid.sort(key=lambda n: (n["start_time"], -n["duration"]))
    notes = []
    for n in grid:
        if notes and n["start_time"] == notes[-1]["start_time"]:
            continue
        if notes and notes[-1]["start_time"] + notes[-1]["duration"] > n["start_time"]:
            notes[-1]["duration"] = n["start_time"] - notes[-1]["start_time"]
        if notes and notes[-1]["pitch"] == n["pitch"] and notes[-1]["start_time"] + notes[-1]["duration"] == n["start_time"]:
            notes[-1]["duration"] += n["duration"]; continue
        notes.append(n)
    if notes:
        notes[-1]["duration"] = min(notes[-1]["duration"], beats - notes[-1]["start_time"])
    return notes


def track_named(name):
    for i in range(call("get_session_info")["result"]["track_count"]):
        if call("get_track_info", track_index=i)["result"]["name"] == name:
            return i
    return None


def main():
    p = argparse.ArgumentParser(description="Sung clip -> Robot Carrier melody track in Live.")
    p.add_argument("audio")
    p.add_argument("--voice-track", required=True, help="name of the track with the vocal")
    p.add_argument("--voice-slot", type=int, default=1, help="clip slot of the vocal, to start both together")
    p.add_argument("--beats", type=float, help="clip length in beats (default: the recording's length)")
    p.add_argument("--low", type=int, default=52, help="lowest MIDI note you sing (Live: 52 = E2)")
    p.add_argument("--high", type=int, default=64, help="highest MIDI note you sing (Live: 64 = E3)")
    p.add_argument("--synth", default="Bright SAW Lead.adv", help="a preset in Sounds > Synth Lead")
    p.add_argument("--gate", type=float, default=-120,
                   help="ignore audio quieter than this (dB). Default: off, which also catches word tails,"
                        " the version the user liked; try -42 for fewer, cleaner notes")
    a = p.parse_args()
    bpm = call("get_session_info")["result"]["tempo"]
    x, sr = load_audio(a.audio)
    beats = a.beats or round(len(x) / sr / (60 / bpm) * 4) / 4
    notes = transcribe(a.audio, bpm, a.low, a.high, beats, a.gate)
    v = track_named(a.voice_track)
    if v is None:
        raise SystemExit(f"No track called {a.voice_track!r} in the open set.")
    t = track_named("Robot Carrier")
    if t is None:
        t = v + 1
        call("create_midi_track", index=t)
        call("set_track_name", track_index=t, name="Robot Carrier")
        uri = next((i["uri"] for i in call("get_browser_items_at_path", path="sounds/Synth Lead")["result"]["items"]
                    if i["name"] == a.synth), None)
        if not uri:
            raise SystemExit(f"Synth preset not found: {a.synth}")
        call("load_browser_item", track_index=t, item_uri=uri)
    slots = call("get_track_info", track_index=t)["result"]["clip_slots"]
    slot = next((s["index"] for s in slots if not s["has_clip"]), len(slots))
    call("create_clip", track_index=t, clip_index=slot, length=beats)
    call("add_notes_to_clip", track_index=t, clip_index=slot, notes=notes)
    call("set_clip_name", track_index=t, clip_index=slot, name="Your melody")
    call("fire_clip", track_index=t, clip_index=slot)
    call("fire_clip", track_index=v, clip_index=a.voice_slot - 1)
    print(f"{len(notes)} notes at {bpm:g} BPM into Robot Carrier (track {t + 1}, slot {slot + 1}):")
    print(" ".join(f"{NAMES[n['pitch'] % 12]}{n['pitch'] // 12 - 2}@{n['start_time']:g}" for n in notes))


if __name__ == "__main__":
    main()
