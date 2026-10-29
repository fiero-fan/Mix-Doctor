#!/usr/bin/env python3
"""
Vocal -> MIDI: transcribe the melody of a raw, single-voice recording.

How it works:
  1. pYIN (librosa) tracks the voice's pitch every ~6 ms, with a confidence for each moment.
  2. Notes start where you attack (a new onset or a pitch jump) and end where you stop.
  3. Each note's pitch is the stable middle of what you sang, so scoops and vibrato don't count.
  4. Self-check: the notes are compared with your actual pitch line; the score is the share
     of sung time where the MIDI note is within a quarter-tone (50 cents) of your voice.

  python3 tools/vocal_to_midi.py take.wav                      # report + score, 65 BPM grid of beats
  python3 tools/vocal_to_midi.py take.wav --bpm 65 --grid 0.25 # snap to 16ths (default: your real timing)
  python3 tools/vocal_to_midi.py take.wav --key A:minor        # snap pitches into a key
  python3 tools/vocal_to_midi.py take.wav --mid melody.mid     # also write a MIDI file (for Logic etc.)
  python3 tools/vocal_to_midi.py take.wav --json notes.json
"""
import argparse, json, struct
import numpy as np
import librosa

NAMES = "C C# D D# E F F# G G# A A# B".split()
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10],
          "chromatic": list(range(12))}
HOP = 256


def pitch_track(path, sr=22050, fmin=80):
    y, sr = librosa.load(path, sr=sr, mono=True)
    f0, voiced, prob = librosa.pyin(y, fmin=fmin, fmax=1050, sr=sr, frame_length=2048, hop_length=HOP)
    midi = librosa.hz_to_midi(np.where(voiced, f0, np.nan))
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0][:len(midi)]
    onsets = set(librosa.onset.onset_detect(y=y, sr=sr, hop_length=HOP, backtrack=True))
    return y, sr, midi, prob, rms, onsets


def segment(midi, onsets, sr, jump=0.75, min_len=0.07, gap=0.05):
    """Split the voiced pitch line into notes: (start_frame, end_frame, pitch)."""
    dt = HOP / sr
    notes, start, run = [], None, []

    def close(end):
        if start is None or (end - start) * dt < min_len:
            return
        seg = np.array(run)
        k = len(seg)
        core = seg[int(k * 0.2): max(int(k * 0.8), int(k * 0.2) + 1)]  # skip the scoop in and the fall out
        notes.append([start, end, float(np.median(core))])

    unvoiced = 0
    for i, m in enumerate(midi):
        if np.isnan(m):
            unvoiced += 1
            if start is not None and unvoiced * dt >= gap:
                close(i - unvoiced + 1); start, run = None, []
            continue
        unvoiced = 0
        if start is None:
            start, run = i, [m]; continue
        centre = np.median(run[-12:])
        # a new note: a clear pitch jump that holds for ~40 ms, or a fresh attack on a different pitch
        ahead = midi[i:i + 7]
        held = np.sum(np.abs(ahead[~np.isnan(ahead)] - m) < 0.5) >= 5
        if (abs(m - centre) > jump and held) or (i in onsets and abs(m - centre) > 0.4 and len(run) * dt > min_len):
            close(i); start, run = i, [m]
        else:
            run.append(m)
    close(len(midi))
    return notes


def fix_octaves(notes):
    """A note an octave (or two) away from the phrase around it is almost always a tracking slip."""
    for i, nt in enumerate(notes):
        around = [n[2] for n in notes[max(0, i - 3): i] + notes[i + 1: i + 4]]
        if len(around) < 2:
            continue
        mid = float(np.median(around))
        while nt[2] - mid > 9: nt[2] -= 12
        while mid - nt[2] > 9: nt[2] += 12
    return notes


def snap(p, key):
    n = int(round(p))
    if not key:
        return n
    root, scale = key
    allowed = [(root + s) % 12 for s in SCALES[scale]]
    return min((c for c in range(n - 2, n + 3) if c % 12 in allowed), key=lambda c: abs(c - p))


def score(midi, prob, notes):
    """Share of confidently sung frames where the MIDI note sits within 50 cents of the voice."""
    target = np.full(len(midi), np.nan)
    for a, b, n in notes:
        target[a:b] = n
    sung = ~np.isnan(midi) & (prob > 0.5)
    covered = sung & ~np.isnan(target)
    ok = covered & (np.abs(midi - target) <= 0.5)
    return 100 * ok.sum() / max(1, sung.sum()), 100 * covered.sum() / max(1, sung.sum())


def transcribe(path, bpm=65.0, grid=None, key=None, beats=None):
    """Notes in beats, ready for Live: [{"pitch", "start_time", "duration", "velocity", "mute"}], plus a report."""
    y, sr, midi, prob, rms, onsets = pitch_track(path)
    raw = fix_octaves(segment(midi, onsets, sr))
    dt, spb = HOP / sr, 60.0 / bpm
    loud = 20 * np.log10(rms + 1e-9)
    top = np.percentile(loud[~np.isnan(midi)], 95) if np.any(~np.isnan(midi)) else 0
    out, kept = [], []
    for a, b, p in raw:
        n = snap(p, key)
        s, e = a * dt / spb, b * dt / spb
        if grid:
            s = round(s / grid) * grid
            e = max(s + grid, round(e / grid) * grid)
        if beats and s >= beats:
            continue
        if beats:
            e = min(e, beats)
        if out and s < out[-1]["start_time"] + out[-1]["duration"]:
            out[-1]["duration"] = max(0.01, s - out[-1]["start_time"])
        if out and out[-1]["pitch"] == n and abs(out[-1]["start_time"] + out[-1]["duration"] - s) < 1e-6 and grid:
            out[-1]["duration"] = e - out[-1]["start_time"]; kept[-1][1] = b; continue
        v = int(np.clip(64 + 2.2 * (np.mean(loud[a:b]) - top + 12), 40, 120))  # louder singing, harder note
        out.append({"pitch": n, "start_time": round(s, 4), "duration": round(e - s, 4), "velocity": v, "mute": False})
        kept.append([a, b, n])
    acc, coverage = score(midi, prob, kept)
    return out, {"accuracy": acc, "coverage": coverage, "seconds": len(y) / sr}


def write_mid(notes, path, bpm):
    """Minimal type-0 MIDI file, no extra libraries."""
    tpq, ev = 480, []
    for n in notes:
        ev.append((round(n["start_time"] * tpq), 0x90, n["pitch"], n["velocity"]))
        ev.append((round((n["start_time"] + n["duration"]) * tpq), 0x80, n["pitch"], 0))
    ev.sort(key=lambda e: (e[0], e[1] == 0x90))
    def vlq(x):
        b = [x & 0x7F]; x >>= 7
        while x: b.insert(0, (x & 0x7F) | 0x80); x >>= 7
        return bytes(b)
    data, last = bytearray(b"\x00\xFF\x51\x03" + int(60e6 / bpm).to_bytes(3, "big")), 0
    for t, st, p, v in ev:
        data += vlq(t - last) + bytes([st, p, v]); last = t
    data += b"\x00\xFF\x2F\x00"
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, tpq) + b"MTrk" + struct.pack(">I", len(data)) + data)


def parse_key(k):
    if not k:
        return None
    root, _, scale = k.partition(":")
    root = root[0].upper() + root[1:]
    flats = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    return NAMES.index(flats.get(root, root)), (scale or "major").lower()


def main():
    p = argparse.ArgumentParser(description="Transcribe a raw vocal to MIDI, with an accuracy score.")
    p.add_argument("audio")
    p.add_argument("--bpm", type=float, default=65)
    p.add_argument("--grid", type=float, help="snap to this many beats (0.25 = 16ths). Default: real timing")
    p.add_argument("--key", help="snap pitches into a key, e.g. A:minor, C:major, D:dorian")
    p.add_argument("--beats", type=float, help="cut at this clip length in beats")
    p.add_argument("--mid", help="write a .mid file")
    p.add_argument("--json", help="write the notes as JSON (Live format)")
    a = p.parse_args()
    notes, rep = transcribe(a.audio, a.bpm, a.grid, parse_key(a.key), a.beats)
    print(f"{len(notes)} notes from {rep['seconds']:.1f} s | accuracy {rep['accuracy']:.0f}% of sung time within 50 cents"
          f" | notes cover {rep['coverage']:.0f}% of the singing")
    print(" ".join(f"{NAMES[n['pitch'] % 12]}{n['pitch'] // 12 - 2}@{n['start_time']:g}" for n in notes))
    if a.mid:
        write_mid(notes, a.mid, a.bpm); print("MIDI file:", a.mid)
    if a.json:
        json.dump(notes, open(a.json, "w")); print("JSON:", a.json)


if __name__ == "__main__":
    main()
