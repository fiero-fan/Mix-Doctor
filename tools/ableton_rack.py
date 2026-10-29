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
    p = dev.find(name)  # a knob, or a path to a plain setting like "CarrierSource/Type"
    if p is None:
        sys.exit(f"{dev.tag} has no knob called {name}")
    target = p.find("Manual") if p.find("Manual") is not None else p
    target.set("Value", str(value).lower() if isinstance(value, bool) else str(value))


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
    # The shell maps its chain selector and chain volumes to macros 7 and 8; left in,
    # macro 8 at 0 turns every chain down to -70 dB. Drop all macro mappings we inherit.
    for holder in (rack, tmpl_branch.find("MixerPreset")):
        for p in holder.iter():
            km = p.find("KeyMidi")
            if km is not None and km.find("Channel").get("Value") == "16":
                p.remove(km)
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
        mixer = b.find(".//AudioBranchMixerDevice")
        mixer.find("Volume/Manual").set("Value", str(chain.get("volume", 1)))
        if "volume_macro" in chain:  # (macro, 0) -> chain level from -70 dB up to +6 dB
            map_macro(mixer, "Volume", chain["volume_macro"], 0.0003162277571, 1.99526238)
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
# v2: your notes stay clear on a dry chain; a parallel chain turns each note into a launch.
# Shifter's envelope drops the pitch on the pick attack, then it swoops up to Height;
# Auto Filter's negative envelope closes on the attack and sweeps open as the note rings.
ROCKET_NOTES = {
    "name": "Rocket Notes",
    # Tuned by ear-and-analysis on the user's guitar at a healthy input level (peaks ~-8 dB).
    # Climb is level-sensitive: hotter input needs less Climb, or the pitch parks low and growls.
    "macros": [("Guitar", 98), ("Rocket", 90), ("Climb", 25), ("Whoosh", 100),
               ("Roar", 20), ("Sky", 38), ("Gate", 55), ("Height", 64)],
    "chains": [
        {"name": "Guitar", "volume_macro": 0, "devices": []},
        {"name": "Rocket", "volume_macro": 1, "devices": [
            {"preset": "Gate/Soft Reducer", "label": "Silence between notes",
             "set": {"Gain": -75, "Release": 150},
             "macros": {"Threshold": (6, 0.003, 0.1)}},
            {"preset": "Roar/Bass Fuzz", "label": "Engine roar",
             "macros": {"Input_InputGain": (4, 1.0, 3.16)}},
            {"preset": "Shifter/Twisted Riser", "label": "Swoop up per note",
             "set": {"Global_ShifterMode": 0, "Lfo_Amount": 0, "Lfo_AmountPitch": 0, "Delay_On": False,
                     "EnvelopeFollower_On": True, "EnvelopeFollower_Attack": 0.002,
                     "EnvelopeFollower_Release": 0.4, "Global_DryWet": 1},
             "macros": {"EnvelopeFollower_AmountPitch": (2, 0, -24), "Pitch_Coarse": (7, 0, 24)}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Whoosh opening up",
             "set": {"Filter_Frequency": 6000, "Lfo_Amount": 0, "Envelope_Attack": 0.01, "Envelope_Release": 2.5},
             "macros": {"Envelope_Amount": (3, 0, -1)}},
            {"preset": "Echo/Vintage Delay/Long Tape", "label": "Exhaust trail",
             "set": {"Noise_On": False, "Wobble_On": False, "Feedback": 0.45, "DryWet": 0.3}},
            {"preset": "Hybrid Reverb/Space/Large Dark Space", "label": "Into the sky",
             "set": {"Algorithm_Decay": 6},
             "macros": {"DryWet": (5, 0, 0.7)}},
        ]},
    ],
}
# v3: one chain. The guitar goes through every stage and each device blends clean and
# rocket itself, so there is no clean "source" with an effect "shadow" beside it.
ROCKET_BLEND = {
    "name": "Rocket Blend",
    "macros": [("Blend", 108), ("Climb", 25), ("Height", 64), ("Whoosh", 100),
               ("Roar", 68), ("Sky", 35), ("Gate", 35), ("Trail", 28)],
    "chains": [
        {"name": "Rocket guitar", "devices": [
            {"preset": "Gate/Soft Reducer", "label": "Quiet between notes",
             "set": {"Gain": -75, "Release": 200},
             "macros": {"Threshold": (6, 0.003, 0.1)}},
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Even notes",
             "set": {"Threshold": 0.15, "Ratio": 4, "Attack": 5, "Release": 200, "Gain": 0}},
            {"preset": "Roar/Bass Fuzz", "label": "Engine grit",
             "set": {"Input_InputGain": 1.4},
             "macros": {"Output_DryWet": (4, 0, 0.8)}},
            {"preset": "Shifter/Twisted Riser", "label": "Swoop up",
             "set": {"Global_ShifterMode": 0, "Lfo_Amount": 0, "Lfo_AmountPitch": 0, "Delay_On": False,
                     "EnvelopeFollower_On": True, "EnvelopeFollower_Attack": 0.002, "EnvelopeFollower_Release": 0.4},
             "macros": {"Global_DryWet": (0, 0, 1), "EnvelopeFollower_AmountPitch": (1, 0, -24),
                        "Pitch_Coarse": (2, 0, 24)}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Whoosh",
             "set": {"Filter_Frequency": 7000, "Lfo_Amount": 0, "Envelope_Attack": 0.01,
                     "Envelope_Release": 2.5, "DryWet": 0.8},
             "macros": {"Envelope_Amount": (3, 0, -1)}},
            {"preset": "Echo/Vintage Delay/Long Tape", "label": "Exhaust trail",
             "set": {"Noise_On": False, "Wobble_On": False, "Feedback": 0.45},
             "macros": {"DryWet": (7, 0, 0.6)}},
            {"preset": "Hybrid Reverb/Space/Large Dark Space", "label": "Into the sky",
             "set": {"Algorithm_Decay": 6},
             "macros": {"DryWet": (5, 0, 0.7)}},
        ]},
    ],
}
# Robot voice that stays melodic: Auto Shift snaps the voice to the nearest note (hard tune),
# then the Vocoder's pitch-tracking carrier plays a synth that follows that melody, blended
# with the voice. Ring modulation adds the metal. One serial chain, blended like Rocket Blend.
ROBOT_ME = {
    "name": "Robot Me",
    # v2 after listening: tune measured 10 cents off-note and the vocoder layer pulled it back
    # to 19, so: no pitch smoothing (instant steps), Retro vocoder with narrow bands, a light
    # digital crush, and more robot by default.
    # v4: v2 was robotic but muffled with unclear words, so: unvoiced detection on (consonants),
    # crush at a higher sample rate, a bit less robot and room. Retro stays on (measured brighter
    # than off). Wave is on a macro; 0 measured brightest, 85 darkest.
    "macros": [("Robot", 105), ("Tune", 127), ("Metal", 40), ("Space", 30),
               ("Octave", 64), ("Formant", 64), ("Crush", 40), ("Wave", 0)],
    "chains": [
        {"name": "Robot voice", "devices": [
            {"preset": "Auto Shift/Tune Hard", "label": "Snap to notes",
             "set": {"Quantizer_Smooth": False, "Quantizer_SmoothingTime": 0},
             "macros": {"Quantizer_Amount": (1, 0, 1), "PitchShift_FormantShift": (5, -1, 1)}},
            {"preset": "Vocoder/Chromatic", "label": "Synth follows your melody",
             "set": {"CarrierSource/Type": 3, "CarrierSource/DetectionLowerBound": 70,
                     "CarrierSource/DetectionUpperBound": 900, "CarrierSource/OscillatorWaveform": 0,
                     "LowFrequency": 80, "HighFrequency": 12000, "OutputGain": 6, "FormantShift": 0,
                     "Retro": True, "FilterBandWidth": 0.15, "EnvelopeRate": 60,
                     "UvdLevel": 0.35, "UvdThreshold": 0.5},
             "macros": {"DryWet": (0, 0, 1), "CarrierSource/OscillatorPitch": (4, -12, 12),
                        "CarrierSource/OscillatorWaveform": (7, 0, 3)}},
            {"preset": "Redux/Synth Bite", "label": "Digital edge",
             "set": {"SampleRate": 30000, "BitDepth": 10, "Jitter": 0,
                     "EnablePreFilter": False, "EnablePostFilter": False},
             "macros": {"DryWet": (6, 0, 0.7)}},
            {"preset": "Shifter/Spacebirds", "label": "Metal",
             "set": {"Global_ShifterMode": 2, "ModBasedShifting_RingMod_Coarse": 60,
                     "ModBasedShifting_RingMod_Drive": False, "Lfo_Amount": 0, "Delay_On": False},
             "macros": {"Global_DryWet": (2, 0, 0.6)}},
            {"preset": "Hybrid Reverb/Room/Modest Corner", "label": "Room",
             "macros": {"DryWet": (3, 0, 0.5)}},
        ]},
    ],
}
# Daft Punk-style robot for the voice track: the Vocoder's carrier is an External synth track
# ("Robot Carrier", made by tools/robot_melody.py) playing the melody, so the robot is exactly
# in tune and the voice only supplies the words. Values copied from the version the user loved
# (set through the bridge; Live shows release and band edges as log10 of ms / Hz).
# After loading: pick the carrier source (Robot Carrier) in the Vocoder; Live can't store it.
DAFT_ROBOT = {
    "name": "Daft Robot",
    # Cleaned after "too distorted, melody unclear": no Enhance, less consonant noise, narrower
    # bands, quieter double, almost no raw voice. Melody tone strength went from 4 to 10 dB.
    "macros": [("Robot", 121), ("Words", 64), ("Octave Up", 38), ("Space", 25),
               ("Gate", 70), ("Formant", 64)],
    "chains": [
        {"name": "Daft robot", "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Even voice",
             "set": {"Threshold": 0.15, "Ratio": 4, "Attack": 5, "Release": 100, "Gain": 0}},
            {"preset": "Vocoder/Chromatic", "label": "Synth sings, you talk",
             "set": {"CarrierSource/Type": 1, "LowFrequency": 80, "HighFrequency": 12000,
                     "FilterBandWidth": 0.5, "Retro": False, "CarrierFlatten": False, "OutputGain": -9,
                     "EnvelopeRelease": 63, "UvdThreshold": 0.85, "MonoStereo": 1, "ModulatorAmount": 1},
             "macros": {"DryWet": (0, 0, 1), "UvdLevel": (1, 0, 1), "LevelGate": (4, -60, -20),
                        "FormantShift": (5, -12, 12)}},
            {"preset": "Shifter/Wobbly Octave Down", "label": "Octave-up double",
             "set": {"Global_ShifterMode": 0, "Pitch_Coarse": 12, "Pitch_Fine": 0, "Lfo_Amount": 0,
                     "Lfo_AmountPitch": 0, "Lfo_SpinOn": False, "Delay_On": False, "Global_Wide": True},
             "macros": {"Global_DryWet": (2, 0, 1)}},
            {"preset": "Hybrid Reverb/Room/Modest Corner", "label": "Room",
             "macros": {"DryWet": (3, 0, 0.5)}},
        ]},
    ],
}
# "Like a liquid squirming, the sound when you open a yogurt" for guitar chords: a vowel filter
# that squelches open on every strum with a random squirm, liquid vibrato, gloopy comb delays,
# grain bubbles and a dripping resonance. One serial chain, each stage blended.
YOGURT = {
    "name": "Yogurt",
    # soft and controlled (user): gentle resonance, short tails, small amounts
    "macros": [("Squelch", 60), ("Squirm", 25), ("Wobble", 40), ("Goo", 25),
               ("Bubbles", 22), ("Drip", 15)],
    "chains": [
        {"name": "Liquid chords", "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Even strums",
             "set": {"Threshold": 0.15, "Ratio": 4, "Attack": 5, "Release": 100, "Gain": 0}},
            {"preset": "Auto Filter/Vocal Quivver", "label": "Squelch",
             "set": {"Envelope_Release": 0.5, "Lfo_Frequency": 3, "Filter_Resonance": 0.4, "DryWet": 0.7},
             "macros": {"Envelope_Amount": (0, 0, 1), "Lfo_Amount": (1, 0, 0.5)}},
            {"preset": "Chorus-Ensemble/Vibrato Wobble", "label": "Liquid wobble",
             "set": {"Rate": 1.0},
             "macros": {"DryWet": (2, 0, 1)}},
            {"preset": "Echo/Modulated Delay/Liqourice Whip", "label": "Goo",
             "set": {"Feedback": 0.35, "InputGain": 0, "Noise_On": False},
             "macros": {"DryWet": (3, 0, 0.6)}},
            {"preset": "Grain Delay/Bubbles", "label": "Bubbles",
             "set": {"Feedback": 0.2},
             "macros": {"NewDryWet": (4, 0, 0.6)}},
            {"preset": "Spectral Resonator/Dripping Grains", "label": "Drip",
             "set": {"DecayDamping_DecayTime": 1.2},
             "macros": {"Global_DryWet": (5, 0, 0.5)}},
        ]},
    ],
}
# "Yogurt falling on other yogurt, with a cosmic-ray vibe on the tail", soft and controlled.
# Body: a dark low-pass that plops open on each strum and a pitch that dips down like a
# falling dollop (Shifter: up with the attack's envelope, sliding back as the chord decays).
# Tail lane is effect-only (no dry): shimmer echoes -> photon ray -> octave-shimmer space.
YOGURT_DROP = {
    "name": "Yogurt Drop",
    "macros": [("Plooah", 127), ("Drop", 30), ("Wobble", 35), ("Cosmos", 88),
               ("Ray", 55), ("Tail", 60), ("Pop", 60), ("Pl", 50), ("Flutter", 55)],
    "chains": [
        {"name": "Body", "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Soft and even",
             "set": {"Threshold": 0.15, "Ratio": 3, "Attack": 10, "Release": 150, "Gain": 0}},
            # "pl-": Drum Buss' Boom fires a short low pop (tuned to A, the loop's key) on every
            # attack, Transients sharpen the pick; drive and compression off to stay soft
            {"preset": "Drum Buss/Boom in A", "label": "Pl- pop",
             "set": {"EnableCompression": False, "DriveAmount": 0.1, "CrunchAmount": 0, "InputTrim": 1,
                     "OutputGain": 1, "DampingFrequency": 9000, "BoomFrequency": 55, "BoomDecay": 0.25,
                     "DryWet": 1},
             "macros": {"BoomAmount": (6, 0, 0.8), "TransientShaping": (7, 0, 0.8)}},
            # "plooah": vowel filter, envelope negative -> each strum starts closed ("oo")
            # and opens into "ah" as the envelope releases
            {"preset": "Auto Filter/Vocal Quivver", "label": "Plooah",
             "set": {"Filter_Frequency": 5000, "Filter_Resonance": 0.5, "Lfo_Amount": 0,
                     "Envelope_Attack": 0.005, "Envelope_Release": 1.2, "DryWet": 0.9},
             "macros": {"Envelope_Amount": (0, 0, -0.9)}},
            {"preset": "Shifter/Wobbly Octave Down", "label": "Falling dollop",
             "set": {"Global_ShifterMode": 0, "Pitch_Coarse": 0, "Pitch_Fine": 0, "Lfo_Amount": 0,
                     "Lfo_AmountPitch": 0, "Lfo_SpinOn": False, "Delay_On": False,
                     "EnvelopeFollower_On": True, "EnvelopeFollower_Attack": 0.002,
                     "EnvelopeFollower_Release": 0.4, "Global_DryWet": 0.6},
             "macros": {"EnvelopeFollower_AmountPitch": (1, 0, 12)}},
            {"preset": "Chorus-Ensemble/Vibrato Wobble", "label": "Gloopy wobble",
             "set": {"Rate": 0.8},
             "macros": {"DryWet": (2, 0, 0.8)}},
            # very fast, quickly fading repeats (45 / 60 ms): the yogurt rippling after the drop
            {"preset": "Echo/Clean Delay/Slapback", "label": "Ripple",
             "set": {"Delay_SyncL": False, "Delay_SyncR": False, "Delay_TimeLink": False,
                     "Delay_TimeL": 0.045, "Delay_TimeR": 0.06, "Feedback": 0.5,
                     "Filter_LowPassFrequency": 5000, "Noise_On": False, "Wobble_On": False},
             "macros": {"DryWet": (8, 0, 0.6)}},
        ]},
        {"name": "Cosmic tail", "volume_macro": 3, "devices": [
            {"preset": "Echo/Ambient Spaces/Shimmery", "label": "Shimmer echoes",
             "set": {"DryWet": 1, "Noise_On": False}},
            {"preset": "Shifter/Autonomous Photon Ray", "label": "Cosmic ray",
             "macros": {"Global_DryWet": (4, 0, 1)}},
            {"preset": "Hybrid Reverb/Space/Large Octave Shimmer", "label": "Space",
             "set": {"DryWet": 1},
             "macros": {"Algorithm_Decay": (5, 1.5, 12)}},
        ]},
    ],
}
# Yogurt falling on yogurt, modeled from the physics, live on guitar. Each lane is one part:
#  Guitar: the blob, thick and soft (pick attack rounded, dark low-pass) + a low thud (Boom in A)
#  Bloop: the collapsing air pocket, a damped band-pass that drops on the attack and chirps
#         UP in ~0.1 s (collapsing cavities rise in pitch; thick goo = low, slow, damped)
#  Smear: sticky spreading, noise shaped by the strum (noise-carrier vocoder), muffled and short
#  Cosmic tail: effect-only shimmer/ray space from Yogurt Drop, low by default
YOGURT_PLOP = {
    "name": "Yogurt Plop",
    "macros": [("Guitar", 100), ("Bloop", 108), ("Chirp time", 40), ("Blob size", 50),
               ("Thud", 70), ("Smear", 80), ("Thickness", 70), ("Cosmos", 70)],
    "chains": [
        {"name": "Guitar", "volume_macro": 0, "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Soft and even",
             "set": {"Threshold": 0.15, "Ratio": 3, "Attack": 10, "Release": 150, "Gain": 0}},
            {"preset": "Drum Buss/Boom in A", "label": "Rounded attack + thud",
             "set": {"EnableCompression": False, "DriveAmount": 0.05, "CrunchAmount": 0, "InputTrim": 1,
                     "OutputGain": 1, "DampingFrequency": 4000, "BoomFrequency": 55, "BoomDecay": 0.3,
                     "TransientShaping": -0.6, "DryWet": 1},
             "macros": {"BoomAmount": (4, 0, 1)}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Thick",
             "set": {"Filter_Resonance": 0.2, "Lfo_Amount": 0, "Envelope_Amount": 0, "DryWet": 1},
             "macros": {"Filter_Frequency": (6, 8000, 900)}},
        ]},
        {"name": "Bloop", "volume_macro": 1, "devices": [
            {"preset": "Auto Filter/Band-pass Spinner", "label": "Bubble chirp",
             "set": {"Filter_Resonance": 0.6, "Lfo_Amount": 0, "Envelope_Amount": -1, "Envelope_Attack": 0,
                     "Envelope_HoldOn": False, "DryWet": 1},
             "macros": {"Envelope_Release": (2, 0.04, 0.3), "Filter_Frequency": (3, 1600, 350)}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Soft edges",
             "set": {"Filter_Frequency": 2500, "Filter_Resonance": 0.1, "Lfo_Amount": 0,
                     "Envelope_Amount": 0, "DryWet": 1}},
        ]},
        {"name": "Smear", "volume_macro": 5, "devices": [
            {"preset": "Vocoder/Noise Drums", "label": "Sticky noise",
             "set": {"LevelGate": -40, "EnvelopeRelease": 120, "OutputGain": 0, "DryWet": 1}},
            {"preset": "Auto Filter/Cut-O-Move LPF", "label": "Muffled",
             "set": {"Filter_Frequency": 1200, "Filter_Resonance": 0.15, "Lfo_Amount": 0,
                     "Envelope_Amount": 0, "DryWet": 1}},
        ]},
        {"name": "Cosmic tail", "volume_macro": 7, "devices": [
            {"preset": "Echo/Ambient Spaces/Shimmery", "label": "Shimmer echoes",
             "set": {"DryWet": 1, "Noise_On": False}},
            {"preset": "Shifter/Autonomous Photon Ray", "label": "Cosmic ray", "set": {"Global_DryWet": 0.5}},
            {"preset": "Hybrid Reverb/Space/Large Octave Shimmer", "label": "Space",
             "set": {"DryWet": 1, "Algorithm_Decay": 6}},
        ]},
    ],
}
# "Dense Greek yogurt violently hitting a wall": a splat, not a plop. Dense = almost no air
# pocket (little bloop); violent = hard, fast attack and a short punchy thud; wall = a bright,
# short slap of splatter noise, then a sticky smear. Same lanes and macro order as Yogurt Plop.
GREEK_SPLAT = copy.deepcopy(YOGURT_PLOP)
GREEK_SPLAT["name"] = "Greek Splat"
GREEK_SPLAT["macros"] = [("Guitar", 100), ("Bloop", 80), ("Chirp time", 15), ("Blob size", 70),
                         ("Thud", 95), ("Smear", 112), ("Thickness", 55), ("Cosmos", 50)]
_g, _b, _s, _t = GREEK_SPLAT["chains"]
_g["devices"][1]["set"].update({"TransientShaping": 0.7, "DriveAmount": 0.3, "CrunchAmount": 0.15,
                                "BoomDecay": 0.15, "DampingFrequency": 9000})
_b["devices"][0]["macros"]["Envelope_Release"] = (2, 0.02, 0.12)       # faster, shorter chirp
_s["devices"][0]["set"].update({"LevelGate": -35, "EnvelopeRelease": 60, "OutputGain": 3})
_s["devices"][1]["set"].update({"Filter_Frequency": 4500})             # brighter splatter
# "Slowly pouring a 10 kg can of yogurt from 3 m into a pool of Greek yogurt; then a high-pitched
# delay on the tail; very clear and soft, not muffled or distorted." The strum is the pour hitting
# the pool (soft heavy gloop), the ringing chord is the stream folding into the pool (slow,
# irregular glug: smoothed-random resonant band-pass), and the tail is a +12 delay that only blooms
# as the chord fades (Echo ducking). No drive, no dark low-pass on the guitar itself.
YOGURT_POUR = {
    "name": "Yogurt Pour",
    # v3 after "sounds like cosmic wind, full of rumble": only the pick attack feeds the gloop lane
    # (gated short), so each echo is a separate droplet with silence around it; tighter resonant
    # gloops, fewer repeats, no chorus wash; thud off and high-passes against rumble.
    "macros": [("Guitar", 72), ("Gloop", 100), ("Gloop speed", 60), ("Accelerate", 100),
               ("Drops", 64), ("Tail", 115), ("Tail pitch", 64), ("Tail repeats", 64)],
    "chains": [
        {"name": "Guitar", "volume_macro": 0, "devices": [
            {"preset": "Compressor/Sustained Lead Vocal", "label": "Soft and even",
             "set": {"Threshold": 0.2, "Ratio": 2.5, "Attack": 15, "Release": 150, "Gain": 0}},
            {"preset": "Auto Filter/Cut-O-Move HPF", "label": "No rumble",
             "set": {"Filter_Frequency": 110, "Filter_Resonance": 0.1, "Lfo_Amount": 0, "Envelope_Amount": 0,
                     "DryWet": 1}},
        ]},
        {"name": "Gloop", "volume_macro": 1, "devices": [
            {"preset": "Gate/Soft Reducer", "label": "Only the pick",
             "set": {"Attack": 0.1, "Hold": 20, "Release": 35, "Return": 3, "Gain": -75},  # Gain = floor
             "macros": {"Threshold": (4, 0.6, 0.05)}},
            {"preset": "Auto Filter/Band-pass Spinner", "label": "Each drop a gloop",
             "set": {"Filter_Frequency": 600, "Filter_Resonance": 0.7, "Lfo_Amount": 0, "Envelope_Amount": 0.8,
                     "Envelope_Attack": 0.001, "Envelope_Release": 0.08, "Envelope_HoldOn": False, "DryWet": 1}},
            {"preset": "Echo/Vintage Delay/Long Tape", "label": "Faster and higher",
             "set": {"Delay_SyncL": False, "Delay_SyncR": False, "Delay_TimeLink": True, "Delay_TimeR": 0.25,
                     "Delay_Repitch": True, "Delay_RepitchSmoothingTime": 0.1, "Feedback": 0.55,
                     "Modulation_EnvelopeMix": 1, "Modulation_AmountDelayTimesFour": True,
                     "Modulation_AmountFilter": 0, "Noise_On": False, "Wobble_On": False, "Reverb_Level": 0,
                     "Gate_On": False, "Ducking_On": False, "Filter_HighPassFrequency": 400,
                     "Filter_LowPassFrequency": 9000, "InputGain": 0, "OutputGain": 1, "DryWet": 1},
             "macros": {"Delay_TimeL": (2, 0.45, 0.1), "Modulation_AmountDelay": (3, 0, 1)}},
        ]},
        {"name": "High tail", "volume_macro": 5, "devices": [
            {"preset": "Shifter/Wobbly Octave Down", "label": "Up high",
             "set": {"Global_ShifterMode": 0, "Pitch_Fine": 0, "Lfo_Amount": 0, "Lfo_AmountPitch": 0,
                     "Lfo_SpinOn": False, "Delay_On": False, "Global_DryWet": 1},
             "macros": {"Pitch_Coarse": (6, 0, 24)}},
            {"preset": "Echo/Clean Delay/Simple Long Digi Delay", "label": "Blooms as the chord fades",
             "set": {"Ducking_On": True, "Ducking_Threshold": -30, "Ducking_Release": 0.4,
                     "Wobble_On": False, "Noise_On": False, "Filter_HighPassFrequency": 800,
                     "Filter_LowPassFrequency": 12000, "DryWet": 1},
             "macros": {"Feedback": (7, 0.2, 0.8)}},
        ]},
    ],
}
RACKS = {"rocket": ROCKET, "rocket-notes": ROCKET_NOTES, "rocket-blend": ROCKET_BLEND, "robot-me": ROBOT_ME,
         "daft-robot": DAFT_ROBOT, "yogurt": YOGURT, "yogurt-drop": YOGURT_DROP, "yogurt-plop": YOGURT_PLOP,
         "greek-splat": GREEK_SPLAT, "yogurt-pour": YOGURT_POUR}


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
