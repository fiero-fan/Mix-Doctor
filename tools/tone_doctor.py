#!/usr/bin/env python3
"""
Mix Doctor tone engine: a Python port of the "Match a sound" logic in mix-doctor.html.

mix-doctor.html is the reference. Each function here mirrors the JS one named in its
docstring (profileFrom, toneRows, scoreOf, adviceFor) and the chain data (KIND, LIB,
SEED, CHAINS). If you change the rules there, change them here too.

Extra over the web app: guitar-range mode (150 Hz - 8 kHz) for full-song references.
"""
import math, re
import numpy as np
from scipy import signal

# ---------------------------------------------------------------- tone fingerprint
OCT = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240, 16000]
OCT_LBL = ["40", "80", "160", "320", "640", "1.3k", "2.6k", "5k", "10k"]
# Guitar-range mode: only judge what a guitar lives in, so drums, bass and cymbals
# in a full mix don't drown the comparison.
GTR = (150, 8000)
GTR_OCT = [150, 320, 640, 1280, 2560, 5120, 8000]
GTR_LBL = ["150", "320", "640", "1.3k", "2.6k", "5k"]


def r1(v):
    return math.floor(v * 10 + 0.5) / 10


def _pct(a, p):
    return a[min(len(a) - 1, max(0, int(math.floor(p * (len(a) - 1)))))]


def profile_from(x, sr, guitar_range=False):
    """profileFrom(): tone fingerprint of a take. x is float [n, ch]."""
    if guitar_range:
        sos = signal.butter(4, GTR, "bandpass", fs=sr, output="sos")
        x = signal.sosfilt(sos, x, axis=0)
    L = x[:, 0]
    R = x[:, 1] if x.shape[1] > 1 else L
    n = len(L)
    M = (L + R) / 2
    fr = int(math.floor(sr * 0.05 + 0.5))
    nf = n // fr
    if not nf:
        return None
    fdb = 10 * np.log10((M[:nf * fr] ** 2).reshape(nf, fr).sum(axis=1) / fr + 1e-20)
    p95 = _pct(np.sort(fdb), .95)
    thr = max(-60, p95 - 30)
    on = np.nonzero(fdb > thr)[0]
    active_sec = len(on) * 0.05
    if active_sec < 2:
        return {"tooQuiet": True, "activeSec": active_sec}
    act = np.sort(fdb[on])
    dyn = _pct(act, .9) - _pct(act, .1)
    region = np.sort(fdb[on[0]:on[-1] + 1])
    space = _pct(region, .15) - _pct(region, .9)
    # spectrum of the active parts only
    N = 4096
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)
    pw = np.zeros(N // 2)
    cnt = 0
    sm = ss = sl = sr2 = slr = 0.0
    for s in range(0, n - N + 1, N):
        m = M[s:s + N]
        if 10 * math.log10(np.sum(m * m) / N + 1e-20) <= thr:
            continue
        cnt += 1
        l, r = L[s:s + N], R[s:s + N]
        d = (l - r) / 2
        sm += np.sum(m * m); ss += np.sum(d * d)
        sl += np.sum(l * l); sr2 += np.sum(r * r); slr += np.sum(l * r)
        pw += np.abs(np.fft.fft(m * win)[:N // 2]) ** 2
    if not cnt:
        return {"tooQuiet": True, "activeSec": active_sec}
    bh = sr / N

    def ks(lo, hi):
        k0 = math.ceil(lo / bh)
        k1 = min(len(pw), math.ceil(min(hi, sr / 2) / bh))
        return np.arange(k0, max(k0, k1))

    def total(lo, hi):
        return float(pw[ks(lo, hi)].sum())

    edges = GTR_OCT if guitar_range else OCT
    lo_all, hi_all = (GTR if guitar_range else (40, 16000))
    raw = [10 * math.log10(total(edges[i], edges[i + 1]) / math.log2(edges[i + 1] / edges[i]) + 1e-30)
           for i in range(len(edges) - 1)]
    mean = sum(raw) / len(raw)
    tot = total(lo_all, hi_all)

    def share(lo, hi):
        return 10 * math.log10(total(lo, hi) / tot + 1e-30)

    k = ks(lo_all, hi_all)
    centroid = float(np.sum(k * bh * pw[k]) / np.sum(pw[k]))
    k = ks(1000, 5000)
    grit = 10 * math.log10(math.exp(np.mean(np.log(pw[k] + 1e-30))) / np.mean(pw[k]) + 1e-30)
    return {
        "curve": [r1(v - mean) for v in raw],
        "labels": GTR_LBL if guitar_range else OCT_LBL,
        "guitarRange": guitar_range,
        "centroid": centroid,
        "low": None if guitar_range else share(40, 120),
        "body": share(150, 500),
        "bite": share(1500, 5000),
        "fizz": None if guitar_range else share(6000, 16000),
        "grit": grit, "dyn": float(dyn), "space": float(space),
        "width": max(-30, 10 * math.log10((ss + 1e-20) / (sm + 1e-20))),
        "corr": slr / math.sqrt(sl * sr2) if sl > 0 and sr2 > 0 else 1,
        "activeSec": active_sec,
    }


# ---------------------------------------------------------------- chains
KIND = {"dynamics": ["#2a78d6", "Dynamics"], "drive": ["#eb6834", "Drive"], "amp": ["#eda100", "Amp"],
        "eq": ["#1baf7a", "EQ"], "modulation": ["#e87ba4", "Modulation"], "delay": ["#6250d6", "Delay"],
        "reverb": ["#9085e9", "Reverb"], "limiter": ["#e34948", "Limiter"], "utility": ["#8e8e93", "Utility"],
        "tracks": ["#8e8e93", "Your tracks"]}

# Logic stock plugins the chain editor knows, with the knobs advice can point at
LIB = [["Noise Gate", "utility", ["Threshold"]], ["Compressor", "dynamics", ["Threshold", "Ratio", "Attack", "Release"]],
       ["Pedalboard", "drive", ["Drive", "Tone", "Level"]],
       ["Amp Designer", "amp", ["Gain", "Bass", "Mids", "Treble", "Presence"]],
       ["Bass Amp Designer", "amp", ["Gain", "Bass", "Mids", "Treble"]],
       ["Channel EQ", "eq", ["Low cut", "Low shelf", "300 Hz", "3 kHz", "High shelf", "High cut"]],
       ["Stereo Delay", "delay", ["Time", "Feedback", "Mix"]], ["Tape Delay", "delay", ["Time", "Feedback", "Mix", "High cut"]],
       ["Modulation Delay", "modulation", ["Rate", "Depth", "Mix"]], ["Chorus", "modulation", ["Rate", "Depth", "Mix"]],
       ["Flanger", "modulation", ["Rate", "Depth", "Feedback", "Mix"]], ["Phaser", "modulation", ["Rate", "Depth", "Mix"]],
       ["ChromaVerb", "reverb", ["Decay", "Mix"]], ["Space Designer", "reverb", ["Decay", "Mix"]],
       ["Multipressor", "dynamics", ["Threshold", "Ratio"]], ["DeEsser 2", "utility", ["Strength"]],
       ["Direction Mixer", "utility", ["Spread"]], ["Adaptive Limiter", "limiter", ["Gain", "Ceiling"]],
       ["Gain", "utility", ["Gain"]]]


def slot_from_lib(name):
    l = next((x for x in LIB if x[0] == name), [name, "utility", []])
    return {"plugin": l[0], "kind": l[1], "knobs": [[k, "", None] for k in l[2]]}


SEED = {"id": "my-heavenly", "ctx": "tone", "name": "My guitar · Heavenly Tweed", "strips": [
    {"name": "Guitar (Input 1)", "out": "Bus 5",
     "slots": [slot_from_lib(n) for n in ["Noise Gate", "Amp Designer", "Channel EQ", "Compressor", "Stereo Delay"]],
     "sends": [["Bus 7 → Mod FX", ""]]},
    {"name": "Mod FX (Bus 7)", "out": "Bus 5",
     "slots": [slot_from_lib(n) for n in ["Modulation Delay", "Flanger", "Phaser"]]},
    {"name": "Heavenly Tweed (stack)", "out": "Stereo Out", "slots": [slot_from_lib("Compressor")]}]}


# ---------------------------------------------------------------- compare
def _row(key, label, less, more, diff, tol, scale, plus, minus):
    return {"key": key, "label": label, "less": less, "more": more, "diff": diff, "tol": tol,
            "scale": scale, "plus": plus, "minus": minus}


def tone_rows(t, y):
    """toneRows(): diff > 0 means YOU have more of it than the target.
    In guitar-range mode, low end, fizz and width are left out (a full mix can't tell us the guitar's)."""
    gr = t.get("guitarRange")
    rows = [
        _row("bright", "Brightness", "darker", "brighter", 12 * math.log2(y["centroid"] / t["centroid"]), 2, 12,
             [["amp", "Treble", "↓"], ["eq", "High cut", "↓"]], [["amp", "Treble", "↑"], ["eq", "High shelf", "↑"], ["amp", "Presence", "↑"]]),
        None if gr else _row("low", "Low end", "thinner", "boomier", y["low"] - t["low"], 2, 10,
                             [["eq", "Low cut", "↑"], ["amp", "Bass", "↓"]], [["amp", "Bass", "↑"]]),
        _row("body", "Body", "thinner", "muddier", y["body"] - t["body"], 2, 10,
             [["eq", "300 Hz", "↓"], ["amp", "Bass", "↓"]], [["amp", "Mids", "↑"]]),
        _row("bite", "Bite", "softer", "harsher", y["bite"] - t["bite"], 2, 10,
             [["eq", "3 kHz", "↓"], ["amp", "Presence", "↓"]], [["amp", "Presence", "↑"], ["amp", "Mids", "↑"]]),
        None if gr else _row("fizz", "Fizz / air", "duller", "fizzier", y["fizz"] - t["fizz"], 2.5, 12,
                             [["eq", "High cut", "↓"], ["drive", "Tone", "↓"]], [["eq", "High shelf", "↑"], ["eq", "High cut", "↑"], ["amp", "Presence", "↑"]]),
        _row("grit", "Grit", "cleaner", "dirtier", y["grit"] - t["grit"], 1.5, 8,
             [["drive", "Fuzz|Drive", "↓"], ["amp", "Gain", "↓"]], [["drive", "Fuzz|Drive", "↑"], ["amp", "Gain", "↑"]]),
        _row("sustain", "Sustain", "choppier", "more squashed", t["dyn"] - y["dyn"], 1.5, 8,
             [["dynamics", "Ratio", "↓"], ["drive", "Fuzz|Drive", "↓"]], [["dynamics", "Ratio", "↑"], ["drive", "Fuzz|Drive", "↑"]]),
        _row("space", "Echo / space", "drier", "wetter", y["space"] - t["space"], 2, 12,
             [["delay", "Mix", "↓"], ["reverb", "Mix", "↓"], ["modulation", "Mix", "↓"]], [["delay", "Mix", "↑"], ["reverb", "Mix", "↑"], ["delay", "Feedback", "↑"]]),
        None if gr else _row("width", "Width", "narrower", "wider", y["width"] - t["width"], 3, 15,
                             [["modulation", "Mix", "↓"], ["delay", "Mix", "↓"]], [["modulation", "Mix", "↑"], ["delay", "Mix", "↑"]]),
    ]
    return [r for r in rows if r]


def score_of(rows):
    """scoreOf(): closeness 0-100."""
    if not rows:
        return None
    m = sum(min(1, max(0, abs(r["diff"]) - r["tol"] / 2) / r["scale"]) for r in rows) / len(rows)
    return int(math.floor(100 * (1 - m) + 0.5))


def amount_word(r):
    x = abs(r["diff"]) / r["tol"]
    return "a little" if x < 2.5 else "" if x < 5 else "a lot"


def find_slot(ch, kind, knob=None):
    for si, st in enumerate(ch["strips"]):
        for i, s in enumerate(st["slots"]):
            if s["kind"] == kind and (not knob or any(re.search(knob, k[0], re.I) for k in s.get("knobs") or [])):
                return [si, i]
    return None


def advice_for(rows, ch):
    """adviceFor(), tone mode: up to 4 moves placed on the chain's plugins."""
    out = []
    for r in rows or []:
        if abs(r["diff"]) <= r["tol"]:
            continue
        opts = r["plus"] if r["diff"] > 0 else r["minus"]
        pick = (next((o for o in opts if o[0] == "tracks" or find_slot(ch, o[0], o[1])), None)
                or next((o for o in opts if find_slot(ch, o[0])), None) or opts[0])
        word = r["more"] if r["diff"] > 0 else r["less"]
        out.append({"kind": pick[0], "knob": pick[1], "dir": pick[2], "amt": amount_word(r), "why": f"You're {word}",
                    "word": word, "w": abs(r["diff"]) / r["tol"], "key": r["key"]})
    out.sort(key=lambda a: -a["w"])
    seen, top = {}, []
    for a in out:
        k = a["kind"] + a["knob"]
        if k in seen:
            seen[k]["why"] += f" and {a['word']}"
            continue
        seen[k] = a
        top.append(a)
    top = top[:4]
    for a in top:
        if a["word"]:
            a["why"] += " than the target"
        a["slot"] = None if a["kind"] == "tracks" else (find_slot(ch, a["kind"], a["knob"]) or find_slot(ch, a["kind"]))
        a["plugin"] = (ch["strips"][a["slot"][0]]["slots"][a["slot"][1]]["plugin"] if a["slot"]
                       else "In your tracks" if a["kind"] == "tracks" else f"Add a {KIND.get(a['kind'], [0, a['kind']])[1]} plugin")
    return top


def verdict(score):
    return ("Very close!" if score >= 85 else "Getting close" if score >= 70
            else "Some way to go" if score >= 50 else "Quite different")
