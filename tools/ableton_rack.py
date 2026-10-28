#!/usr/bin/env python3
"""
Build Ableton Live Audio Effect Racks (.adg) from Live's own factory presets.

An .adg is gzipped XML. We take a factory rack as the shell, then fill its chains with
devices copied from factory device presets (.adv), override knob values (in the device's
real units: Hz, ms, semitones, 0-1 for dry/wet) and map knobs to the rack's macros.

  python3 tools/ableton_rack.py rocket          # writes Rocket.adg into your User Library
  python3 tools/ableton_rack.py rocket --out x.adg
"""
import argparse, copy, gzip, os, sys
import xml.etree.ElementTree as ET

APP = next((os.path.join("/Applications", a) for a in sorted(os.listdir("/Applications"))
            if a.startswith("Ableton Live 12")), None)
CORE = os.path.join(APP or "", "Contents/App-Resources/Core Library")
DEVICES = os.path.join(CORE, "Devices/Audio Effects")
SHELL = os.path.join(CORE, "Racks/Audio Effect Racks/Mixing & Mastering/Master EQ & Compressor.adg")
USER_RACKS = os.path.expanduser("~/Music/Ableton/User Library/Presets/Audio Effects/Audio Effect Rack/Mix Doctor")


def read_gz(path):
    return ET.fromstring(gzip.decompress(open(path, "rb").read()))


def load_device(preset):
    """Device element (e.g. <Roar>) from a factory preset like 'Roar/Bass Fuzz'."""
    path = os.path.join(DEVICES, preset + ".adv")
    if not os.path.exists(path):
        sys.exit(f"Factory preset not found: {preset}")
    return read_gz(path)[0]


def set_param(dev, name, value):
    p = dev.find(name)
    if p is None or p.find("Manual") is None:
        sys.exit(f"{dev.tag} has no knob called {name}")
    p.find("Manual").set("Value", str(value).lower() if isinstance(value, bool) else str(value))


def map_macro(dev, name, macro, lo, hi):
    """Map a knob to rack macro `macro` (0-based), sweeping lo..hi as the macro goes 0..127."""
    p = dev.find(name)
    old = p.find("KeyMidi")
    if old is not None:
        p.remove(old)
    km = ET.Element("KeyMidi")
    for tag, v in [("PersistentKeyString", ""), ("IsNote", "false"), ("Channel", "16"), ("NoteOrController", str(macro)),
                   ("LowerRangeNote", "-1"), ("UpperRangeNote", "-1"), ("ControllerMapMode", "0")]:
        ET.SubElement(km, tag, Value=v)
    p.insert(1, km)  # right after LomId, like Live writes it
    rng = p.find("MidiControllerRange")
    rng.find("Min").set("Value", str(lo))
    rng.find("Max").set("Value", str(hi))


def build(spec, out):
    root = read_gz(SHELL)
    g = root.find("GroupDevicePreset")
    rack = g.find("Device")[0]
    rack.find("UserName").set("Value", spec["name"])
    rack.find("AreDevicesVisible").set("Value", "true")
    rack.find("ChainSelector/Manual").set("Value", "0")
    # macros: names and starting positions; clear factory snapshots
    for i in range(16):
        m = spec["macros"][i] if i < len(spec["macros"]) else None
        rack.find(f"MacroDisplayNames.{i}").set("Value", m[0] if m else f"Macro {i + 1}")
        rack.find(f"MacroControls.{i}/Manual").set("Value", str(m[1] if m else 0))
        rack.find(f"MacroDefaults.{i}").set("Value", str(m[1] if m else -1))
        rack.find(f"MacroColor.{i}").set("Value", "-1")
    rack.find("NumVisibleMacroControls").set("Value", "8" if len(spec["macros"]) <= 8 else "16")
    snaps = rack.find("MacroVariations/MacroSnapshots")
    for s in list(snaps):
        snaps.remove(s)
    # chains
    branches = g.find("BranchPresets")
    tmpl_branch = copy.deepcopy(branches[0])
    tmpl_dev = copy.deepcopy(tmpl_branch.find("DevicePresets")[0])
    for b in list(branches):
        branches.remove(b)
    for ci, chain in enumerate(spec["chains"]):
        b = copy.deepcopy(tmpl_branch)
        b.set("Id", str(ci))
        b.find("Name").set("Value", chain["name"])
        dps = b.find("DevicePresets")
        for d in list(dps):
            dps.remove(d)
        for di, d in enumerate(chain["devices"]):
            dev = load_device(d["preset"])
            dev.set("Id", "0")  # .adv files leave it out, but inside a rack every list member needs one
            dev.find("UserName").set("Value", d.get("label", ""))
            for k, v in d.get("set", {}).items():
                set_param(dev, k, v)
            for k, (macro, lo, hi) in d.get("macros", {}).items():
                map_macro(dev, k, macro, lo, hi)
            w = copy.deepcopy(tmpl_dev)
            w.set("Id", str(di))
            holder = w.find("Device")
            holder.remove(holder[0])
            holder.append(dev)
            dps.append(w)
        b.find(".//AudioBranchMixerDevice/Volume/Manual").set("Value", str(chain.get("volume", 1)))
        # Full chain-select zone with no fades. The shell's zones fade in across 0-127,
        # which silences every chain when the selector sits at 0.
        for tag, v in [("Min", 0), ("Max", 127), ("CrossfadeMin", 0), ("CrossfadeMax", 127)]:
            b.find(f"BranchSelectorRange/{tag}").set("Value", str(v))
        branches.append(b)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with gzip.open(out, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8"))
    return out


# ---------------------------------------------------------------- racks
ROCKET = {
    "name": "Rocket",
    # (name, starting position 0-127)
    "macros": [("Launch", 0), ("Spiral", 64), ("Roar", 64), ("Sky", 55)],
    "chains": [
        {"name": "Engine & climb", "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Sustain",
             "set": {"Threshold": 0.1, "Ratio": 8, "Attack": 5, "Release": 300, "Gain": 0}},
            {"preset": "Roar/Bass Fuzz", "label": "Engine roar",
             "macros": {"Input_InputGain": (2, 1.0, 3.16)}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Whoosh",
             "set": {"Filter_Resonance": 0.6},
             "macros": {"Filter_Frequency": (0, 300, 8000)}},
            {"preset": "Shifter/Twisted Riser", "label": "Climbing spiral",
             "set": {"Delay_Feedback": 0.85},
             "macros": {"Pitch_Coarse": (0, 0, 12), "Global_DryWet": (1, 0, 1)}},
            {"preset": "Echo/Vintage Delay/Long Tape", "label": "Exhaust trail",
             "set": {"DryWet": 0.3}},
            {"preset": "Hybrid Reverb/Space/Large Dark Space", "label": "Into the sky",
             "set": {"Algorithm_Decay": 8},
             "macros": {"DryWet": (3, 0, 0.7)}},
        ]},
        {"name": "Rumble", "volume": 0.4, "devices": [
            {"preset": "Shifter/Wobbly Octave Down", "label": "Octave down",
             "set": {"Global_DryWet": 1, "Delay_On": False}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Only the shake",
             "set": {"Filter_Frequency": 200, "Filter_Resonance": 0.2, "Lfo_Amount": 0}},
        ]},
    ],
}
RACKS = {"rocket": ROCKET}


def main():
    p = argparse.ArgumentParser(description="Write a Mix Doctor rack into Ableton's User Library.")
    p.add_argument("rack", choices=sorted(RACKS))
    p.add_argument("--out")
    a = p.parse_args()
    if not APP:
        sys.exit("Ableton Live 12 isn't in /Applications.")
    spec = RACKS[a.rack]
    out = build(spec, a.out or os.path.join(USER_RACKS, spec["name"] + ".adg"))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
