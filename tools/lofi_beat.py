#!/usr/bin/env python3
"""
Build a lo-fi beat in the open Live set through the AbletonMCP bridge.

Drums, keys and bass on three MIDI tracks with organic sounds from Live's Core Library,
a swung loop (one chord per bar) and some lo-fi colour. If the "Lo-fi" tracks already
exist, the new loop goes into their next empty clip slot so earlier loops stay.

  python3 tools/lofi_beat.py                       # 65 BPM, Am | Gm
  python3 tools/lofi_beat.py --chords Fmaj9,Em9,Dm9,G13 --bpm 70
"""
import argparse, random
from live import call

KIT = ("drums", "Boom Bap Kit.adg")
KEYS = ("sounds/Piano & Keys", "E-Piano MKI Mellow.adv")
BASS = ("sounds/Bass", "Upright Close Bass.adv")
DRUM_FX = ("audio_effects/Roar", "Drum Break Duster.adv")
KEYS_FX = ("audio_effects/Roar", "VHS Mild.adv")
# Boom Bap Kit pads
KICK, RIM, SNARE, HAT, OPEN_HAT = 36, 37, 40, 42, 46

# keys voicing (9th chords, warm middle register) and bass root / fifth
CHORDS = {
    "Am":    ([57, 60, 64, 67, 71], 45, 40),   # A C E G B
    "Gm":    ([55, 58, 62, 65, 69], 43, 38),   # G Bb D F A
    "Fmaj9": ([53, 57, 60, 64, 67], 41, 48),
    "Em9":   ([52, 55, 59, 62, 66], 40, 47),
    "Dm9":   ([50, 53, 57, 60, 64], 38, 45),
    "G13":   ([53, 57, 59, 64], 43, 38),
}

random.seed(65)


def human(t, amount=0.015):
    return max(0.0, t + random.uniform(-amount, amount))


def vel(v, spread=8):
    return int(max(1, min(127, v + random.randint(-spread, spread))))


def swing(t, amount=0.08):
    """Push every off-beat 8th late: the lazy, behind-the-beat lo-fi feel."""
    beat, frac = divmod(t, 1.0)
    return beat + (frac + amount if abs(frac - 0.5) < 1e-6 else frac)


def n(pitch, start, dur, v):
    return {"pitch": pitch, "start_time": round(start, 4), "duration": dur, "velocity": v, "mute": False}


def drums(bars):
    out = []
    for bar in range(bars):
        b, last = bar * 4, bar == bars - 1
        for k in (0, 1.5, 2.75) + ((3.5,) if last else ()):
            out.append(n(KICK, human(b + swing(k)), 0.25, vel(100 if k == 0 else 82)))
        for s in (1, 3):
            out.append(n(SNARE, b + s + 0.03, 0.25, vel(100, 5)))  # laid back
        out += [n(RIM, human(b + 2.75 + 0.05), 0.1, vel(34, 6)), n(RIM, human(b + 3.75 + 0.05), 0.1, vel(28, 6))]
        for i in range(8):
            t = i * 0.5
            if last and i == 7:
                out.append(n(OPEN_HAT, human(b + swing(t)), 0.4, vel(60)))
            else:
                out.append(n(HAT, human(b + swing(t)), 0.1, vel(68 if i % 2 == 0 else 42)))
    return out


def keys(prog):
    out = []
    for bar, name in enumerate(prog):
        b = bar * 4
        for hit, dur, v in ((0, 1.4, 70), (swing(2.5), 1.3, 58)):
            for i, p in enumerate(CHORDS[name][0]):  # a soft roll, low to high
                out.append(n(p, b + hit + i * 0.018, dur, vel(v, 6)))
    return out


def bass(prog):
    out = []
    for bar, name in enumerate(prog):
        b = bar * 4
        root, fifth = CHORDS[name][1:]
        nxt = CHORDS[prog[(bar + 1) % len(prog)]][1]
        approach = nxt + 1 if nxt + 1 != root else nxt - 1  # a half step into the next root
        out += [n(root, human(b), 1.3, vel(96, 5)),
                n(fifth, human(b + swing(2.5)), 0.7, vel(80, 6)),
                n(approach, human(b + swing(3.5)), 0.4, vel(70, 6))]
    return out


def find(path, name):
    items = call("get_browser_items_at_path", path=path)["result"]["items"]
    hit = next((i for i in items if i["name"] == name), None)
    if not hit:
        raise SystemExit(f"Not in Live's browser: {path}/{name}")
    return hit["uri"]


def track_named(name):
    for t in range(call("get_session_info")["result"]["track_count"]):
        if call("get_track_info", track_index=t)["result"]["name"] == name:
            return t
    return None


def free_slot(t):
    slots = call("get_track_info", track_index=t)["result"].get("clip_slots", [])
    return next((s.get("index", i) for i, s in enumerate(slots) if not s.get("has_clip")), len(slots))


def add_part(name, sound, notes, bars, label, fx=None):
    t = track_named(name)
    if t is None:
        call("create_midi_track", index=-1)
        t = call("get_session_info")["result"]["track_count"] - 1
        call("set_track_name", track_index=t, name=name)
        call("load_browser_item", track_index=t, item_uri=find(*sound))
        if fx:
            call("load_browser_item", track_index=t, item_uri=find(*fx))
    slot = free_slot(t)
    call("create_clip", track_index=t, clip_index=slot, length=4.0 * bars)
    call("add_notes_to_clip", track_index=t, clip_index=slot, notes=notes)
    call("set_clip_name", track_index=t, clip_index=slot, name=label)
    return t, slot


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bpm", type=float, default=65)
    p.add_argument("--chords", default="Am,Gm", help="one chord per bar, e.g. Am,Gm")
    a = p.parse_args()
    prog = a.chords.split(",")
    unknown = [c for c in prog if c not in CHORDS]
    if unknown:
        raise SystemExit(f"Don't know these chords yet: {unknown}. Known: {sorted(CHORDS)}")
    label, bars = " | ".join(prog), len(prog)
    call("set_tempo", tempo=a.bpm)
    parts = [add_part("Lo-fi Drums", KIT, drums(bars), bars, label, DRUM_FX),
             add_part("Lo-fi Keys", KEYS, keys(prog), bars, label, KEYS_FX),
             add_part("Lo-fi Bass", BASS, bass(prog), bars, label)]
    for t, slot in parts:
        call("fire_clip", track_index=t, clip_index=slot)
    print(f"{a.bpm:g} BPM · {label} · clip slot {parts[0][1] + 1} on tracks {', '.join(str(t + 1) for t, _ in parts)}")


if __name__ == "__main__":
    main()
