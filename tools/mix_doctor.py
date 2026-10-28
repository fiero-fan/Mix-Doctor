#!/usr/bin/env python3
"""
Mix Doctor - AI Producer, step T1 (analyzer core) + starter T3 (suggestions).

Analyzes a mix bounced from Logic Pro / GarageBand and writes a report with
measurements and concrete moves using Logic's built-in plugins.

Usage:
    python3 mix_doctor.py my_mix.wav
    python3 mix_doctor.py my_mix.wav --reference song_i_love.wav
    python3 mix_doctor.py my_mix.wav --genre funk

Needs only: Python 3, numpy, scipy.   (pip3 install numpy scipy)
Input: WAV (16/24/32-bit, any sample rate). Other formats work if ffmpeg is installed.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
import numpy as np
from scipy import signal
from scipy.io import wavfile

# ---------------------------------------------------------------- loading
def load_audio(path):
    """Return (samples float64 [n, ch], sample_rate). Converts via ffmpeg if not WAV."""
    tmp = None
    if not path.lower().endswith((".wav", ".wave")):
        if not shutil.which("ffmpeg"):
            sys.exit("Please bounce as WAV (or install ffmpeg to read other formats).")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-c:a", "pcm_f32le", tmp], check=True)
        path = tmp
    sr, x = wavfile.read(path)
    if tmp:
        os.unlink(tmp)
    if x.dtype == np.int16:
        x = x / 32768.0
    elif x.dtype == np.int32:  # 24-bit files are read as int32 by scipy
        x = x / 2147483648.0
    elif x.dtype == np.uint8:
        x = (x - 128) / 128.0
    x = x.astype(np.float64)
    if x.ndim == 1:
        x = x[:, None]
    return x[:, :2], sr

def db(v, floor=-120.0):
    return float(max(20 * np.log10(max(v, 1e-12)), floor))

# ---------------------------------------------------------------- loudness (ITU-R BS.1770-4)
def k_weight(x, sr):
    # Stage 1: high-shelf (+4 dB above ~1.5 kHz); stage 2: high-pass (~38 Hz). Coeffs from BS.1770 / pyloudnorm.
    G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.974450955533
    A = 10 ** (G / 40); w0 = 2 * np.pi * fc / sr; alpha = np.sin(w0) / (2 * Q)
    b1 = [A * ((A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha),
          -2 * A * ((A - 1) + (A + 1) * np.cos(w0)),
          A * ((A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)]
    a1 = [(A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha,
          2 * ((A - 1) - (A + 1) * np.cos(w0)),
          (A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha]
    Q2, fc2 = 0.5003270373238773, 38.13547087602444
    w0 = 2 * np.pi * fc2 / sr; alpha = np.sin(w0) / (2 * Q2)
    b2 = [(1 + np.cos(w0)) / 2, -(1 + np.cos(w0)), (1 + np.cos(w0)) / 2]
    a2 = [1 + alpha, -2 * np.cos(w0), 1 - alpha]
    y = signal.lfilter(b1, a1, x, axis=0)
    return signal.lfilter(b2, a2, y, axis=0)

def block_loudness(xk, sr, win, hop):
    n, step = int(win * sr), int(hop * sr)
    if len(xk) < n:
        return np.array([])
    starts = range(0, len(xk) - n + 1, step)
    ms = np.array([np.mean(xk[s:s + n] ** 2, axis=0).sum() for s in starts])
    return -0.691 + 10 * np.log10(np.maximum(ms, 1e-12))

def integrated_lufs(xk, sr):
    l = block_loudness(xk, sr, 0.4, 0.1)
    l = l[l > -70]
    if not len(l):
        return -70.0
    rel = 10 * np.log10(np.mean(10 ** (l / 10))) - 10
    l = l[l > rel]
    return float(10 * np.log10(np.mean(10 ** (l / 10))))

def loudness_range(xk, sr):
    st = block_loudness(xk, sr, 3.0, 1.0)
    st = st[st > -70]
    if len(st) < 2:
        return 0.0, st
    rel = 10 * np.log10(np.mean(10 ** (st / 10))) - 20
    g = st[st > rel]
    return float(np.percentile(g, 95) - np.percentile(g, 10)), st

def true_peak(x, sr):
    up = 4 if sr < 96000 else 2
    return db(np.max(np.abs(signal.resample_poly(x, up, 1, axis=0))))

# ---------------------------------------------------------------- tone & stereo
BANDS = [("sub", 20, 60), ("bass", 60, 250), ("low-mids", 250, 500), ("mids", 500, 2000),
         ("upper-mids", 2000, 4000), ("presence", 4000, 8000), ("air", 8000, 20000)]

def band_levels(mono, sr):
    """Average power per band in dB, relative to the 'mids' band (so overall volume doesn't matter)."""
    f, p = signal.welch(mono, sr, nperseg=8192)
    out = {}
    for name, lo, hi in BANDS:
        m = (f >= lo) & (f < min(hi, sr / 2))
        # sum of power in band, normalized per octave so bands of different width compare fairly
        octaves = np.log2(min(hi, sr / 2) / lo)
        out[name] = 10 * np.log10(np.sum(p[m]) / octaves + 1e-20)
    ref = out["mids"]
    return {k: round(v - ref, 1) for k, v in out.items()}

def stereo_stats(x, sr):
    if x.shape[1] < 2:
        return {"mono_file": True}
    L, R = x[:, 0], x[:, 1]
    M, S = (L + R) / 2, (L - R) / 2
    corr = float(np.corrcoef(L, R)[0, 1]) if np.std(L) > 0 and np.std(R) > 0 else 1.0
    width = db(np.sqrt(np.mean(S ** 2))) - db(np.sqrt(np.mean(M ** 2)))
    sos = signal.butter(4, 120, "low", fs=sr, output="sos")
    Ml, Sl = signal.sosfilt(sos, M), signal.sosfilt(sos, S)
    low_width = db(np.sqrt(np.mean(Sl ** 2))) - db(np.sqrt(np.mean(Ml ** 2)))
    return {"mono_file": False, "correlation": round(corr, 2),
            "side_vs_mid_db": round(width, 1), "low_end_side_vs_mid_db": round(low_width, 1)}

# ---------------------------------------------------------------- full analysis
def analyze(path):
    x, sr = load_audio(path)
    dur = len(x) / sr
    xk = k_weight(x, sr)
    lufs = integrated_lufs(xk, sr)
    lra, st = loudness_range(xk, sr)
    tp = true_peak(x, sr)
    peak = db(np.max(np.abs(x)))
    rms = db(np.sqrt(np.mean(x ** 2)))
    clipped = int(np.sum(np.abs(x) >= 0.999))
    mono = x.mean(axis=1)
    # loudest / quietest sections (short-term loudness, 3 s windows)
    sections = []
    if len(st):
        sections = [{"time": f"{int(i // 60)}:{int(i % 60):02d}", "lufs": round(float(v), 1)}
                    for i, v in enumerate(st)]
    return {
        "file": os.path.basename(path), "sample_rate": sr, "channels": x.shape[1],
        "duration_s": round(dur, 1),
        "loudness": {"integrated_lufs": round(lufs, 1), "true_peak_dbtp": round(tp, 1),
                     "sample_peak_dbfs": round(peak, 1), "loudness_range_lu": round(lra, 1),
                     "plr_db": round(tp - lufs, 1), "crest_factor_db": round(peak - rms, 1),
                     "max_short_term_lufs": round(float(st.max()), 1) if len(st) else None,
                     "clipped_samples": clipped},
        "tone_vs_mids_db": band_levels(mono, sr),
        "stereo": stereo_stats(x, sr),
        "short_term_lufs": sections,
    }

# ---------------------------------------------------------------- suggestions (starter rules)
# Rough tonal-balance ranges (dB relative to the mids band), per genre.
# These are STARTING POINTS, not truths; a reference track you love is always better.
GENRE_TONE = {
    "rock":       {"sub": (-14, -5), "bass": (-3, 4), "low-mids": (-3, 2), "upper-mids": (-5, 0), "presence": (-9, -3), "air": (-16, -8)},
    "funk":       {"sub": (-13, -5), "bass": (-2, 5), "low-mids": (-3, 2), "upper-mids": (-5, 0), "presence": (-9, -3), "air": (-16, -8)},
    "reggae":     {"sub": (-10, -1), "bass": (0, 7),  "low-mids": (-3, 2), "upper-mids": (-6, -1), "presence": (-10, -4), "air": (-17, -9)},
    "ska":        {"sub": (-13, -5), "bass": (-2, 4), "low-mids": (-3, 2), "upper-mids": (-5, 0), "presence": (-9, -3), "air": (-16, -8)},
    "disco":      {"sub": (-12, -4), "bass": (-1, 5), "low-mids": (-3, 2), "upper-mids": (-5, 0), "presence": (-8, -2), "air": (-15, -7)},
    "electronic": {"sub": (-8, 1),  "bass": (0, 7),  "low-mids": (-4, 1), "upper-mids": (-6, 0), "presence": (-9, -3), "air": (-15, -7)},
}

def suggest(a, genre="rock", ref=None):
    s = []
    L, tone, st = a["loudness"], a["tone_vs_mids_db"], a["stereo"]
    # Loudness & peaks
    if L["clipped_samples"] > 0:
        s.append(("HIGH", "Clipping", f"{L['clipped_samples']} samples hit 0 dBFS. Lower the Stereo Out fader or the master limiter output until nothing touches 0 dB, then bounce again."))
    if L["true_peak_dbtp"] > -1.0:
        s.append(("HIGH", "True peak too hot", f"True peak is {L['true_peak_dbtp']} dBTP. On the Stereo Out put Adaptive Limiter last, enable True Peak Detection, Out Ceiling -1.0 dB. Streaming services can distort peaks above -1 dBTP."))
    if L["integrated_lufs"] < -16:
        s.append(("MED", "Quiet for release", f"Integrated loudness is {L['integrated_lufs']} LUFS. For a release master aim around -14 to -9 LUFS: raise Adaptive Limiter Gain a few dB at a time (or try Logic's Mastering Assistant) and keep the ceiling at -1 dB. If this is a mix for a mastering engineer, quiet is fine; just keep peaks below -3 dBFS."))
    elif L["integrated_lufs"] > -8:
        s.append(("MED", "Very loud", f"{L['integrated_lufs']} LUFS is very loud. Spotify/Apple will turn it down to about -14/-16 anyway, so you lose punch for nothing. Back off Adaptive Limiter Gain until PLR is at least 8 dB."))
    if L["plr_db"] < 8:
        s.append(("MED", "Squashed dynamics", f"Peak-to-loudness ratio is {L['plr_db']} dB (under 8 sounds flat). Reduce limiting and bus compression; if you use Compressor on the Stereo Out, try ratio 1.5:1-2:1 with attack 20-30 ms so drum hits pass through."))
    elif L["plr_db"] > 16 and L["integrated_lufs"] < -16:
        s.append(("LOW", "Very dynamic", f"PLR is {L['plr_db']} dB. Nice and open, but it may sound weak next to commercial tracks. Light glue: Compressor on the Stereo Out (Vintage VCA, ratio 2:1, attack 10-30 ms, auto release, 1-2 dB gain reduction)."))
    # Tone
    targets = GENRE_TONE.get(genre, GENRE_TONE["rock"])
    if ref:
        rt = ref["tone_vs_mids_db"]
        for band, lo, hi in BANDS:
            if band == "mids":
                continue
            d = tone[band] - rt[band]
            if abs(d) >= 3:
                verb = "Cut" if d > 0 else "Boost"
                s.append(("MED", f"{band} vs reference", f"Your {band} ({lo}-{hi} Hz) is {d:+.1f} dB compared with the reference. {verb} about {min(abs(d)/2, 4):.1f} dB with a wide bell (Q 0.7) in Channel EQ on the Stereo Out, or better, fix it on the tracks that live in that range."))
    else:
        tips = {"sub": ("Channel EQ low cut at ~30 Hz on the Stereo Out, and high-pass instruments that don't need sub (guitars, keys, vocals) at 80-120 Hz", "bass/kick: boost 50-60 Hz on the kick or bass, or add a sub layer"),
                "bass": ("cut 2-3 dB around 100-200 Hz on bass or guitars; check kick and bass aren't stacked at the same frequency", "boost bass guitar around 80-120 Hz, or bring the bass fader up 1-2 dB"),
                "low-mids": ("this is the 'mud' zone: cut 2-4 dB at 250-400 Hz on guitars, keys and the vocal bus (wide bell)", "the mix may sound thin: add warmth with a small 200-300 Hz boost on guitars or vocals"),
                "upper-mids": ("harsh zone: cut 2-3 dB at 2.5-3.5 kHz on guitars/vocals, or use DeEsser 2 / Multipressor", "add 1-2 dB around 2-3 kHz on vocal and snare so they cut through"),
                "presence": ("sibilance/hiss: DeEsser 2 on vocals, gentle high shelf cut above 6 kHz", "add a high shelf +1.5 dB at 5 kHz on vocals or overheads"),
                "air": ("lower cymbals/hi-hat, or high shelf -1.5 dB at 10 kHz on the Stereo Out", "high shelf +1-2 dB at 10-12 kHz on the Stereo Out (Channel EQ) for air")}
        for band, (lo, hi) in targets.items():
            v = tone[band]
            if v > hi:
                s.append(("MED", f"Too much {band}", f"{band} sits at {v:+.1f} dB vs mids (typical {genre}: {lo} to {hi}). Try: {tips[band][0]}."))
            elif v < lo:
                s.append(("MED", f"Not enough {band}", f"{band} sits at {v:+.1f} dB vs mids (typical {genre}: {lo} to {hi}). Try: {tips[band][1]}."))
    # Stereo
    if not st.get("mono_file"):
        if st["correlation"] < 0.2:
            s.append(("HIGH", "Phase / mono problems", f"Stereo correlation is {st['correlation']} (close to 0 or negative). Parts may disappear on phone speakers. Check stereo wideners and doubled guitars; use Direction Mixer to narrow, and listen in mono (Gain plugin > Mono)."))
        elif st["correlation"] > 0.95:
            s.append(("LOW", "Almost mono", f"Correlation {st['correlation']}: the mix is nearly mono. Pan doubled guitars/keys left and right, add a stereo reverb (ChromaVerb) on a send."))
        if st["low_end_side_vs_mid_db"] > -15:
            s.append(("MED", "Wide low end", f"Below 120 Hz the side signal is only {abs(st['low_end_side_vs_mid_db'])} dB below the mid. Keep bass and kick centered; on the Stereo Out, Stereo Spread off for lows or use Direction Mixer on bass tracks. Wide lows hurt vinyl and club systems."))
    if not s:
        s.append(("OK", "No big issues", "Nothing out of range. Now trust your ears and compare with a reference track."))
    order = {"HIGH": 0, "MED": 1, "LOW": 2, "OK": 3}
    return sorted(s, key=lambda t: order[t[0]])

# ---------------------------------------------------------------- report
def report_md(a, sug, genre, ref=None):
    L, st = a["loudness"], a["stereo"]
    r = [f"# Mix Doctor report: {a['file']}", "",
         f"{a['duration_s']} s, {a['sample_rate']} Hz, {a['channels']} ch. Genre profile: **{genre}**" + (f". Reference: **{ref['file']}**" if ref else ""), "",
         "## Loudness", "",
         "| Measure | Value | What it means |", "|---|---|---|",
         f"| Integrated loudness | {L['integrated_lufs']} LUFS | Average loudness of the whole song. Streaming plays around -14. |",
         f"| True peak | {L['true_peak_dbtp']} dBTP | Highest real peak. Keep at -1 or lower. |",
         f"| Peak-to-loudness (PLR) | {L['plr_db']} dB | Punch. Under 8 = squashed, 9-14 = healthy. |",
         f"| Loudness range | {L['loudness_range_lu']} LU | How much verses/choruses differ. |",
         f"| Loudest 3 s | {L['max_short_term_lufs']} LUFS | Usually the chorus. |",
         f"| Clipped samples | {L['clipped_samples']} | Should be 0. |", "",
         "## Tonal balance (dB vs the mids band)", "",
         "| Band | You |" + (" Reference |" if ref else "") , "|---|---|" + ("---|" if ref else "")]
    for name, lo, hi in BANDS:
        row = f"| {name} ({lo}-{hi} Hz) | {a['tone_vs_mids_db'][name]:+.1f} |"
        if ref:
            row += f" {ref['tone_vs_mids_db'][name]:+.1f} |"
        r.append(row)
    r += ["", "## Stereo", ""]
    if st.get("mono_file"):
        r.append("Mono file.")
    else:
        r += [f"- Correlation: **{st['correlation']}** (1 = mono, 0 = very wide/phasey, negative = trouble)",
              f"- Side vs mid: **{st['side_vs_mid_db']} dB** (overall width)",
              f"- Low end (<120 Hz) side vs mid: **{st['low_end_side_vs_mid_db']} dB** (should be well below -15)"]
    r += ["", "## Suggested moves (Logic Pro stock plugins)", ""]
    for i, (prio, title, text) in enumerate(sug, 1):
        r.append(f"{i}. **[{prio}] {title}**: {text}")
    r += ["", "---", "", "## Ask Claude for a deeper opinion", "",
          "Paste this whole report into Claude with: *\"I'm mixing a {genre} song in Logic Pro. Here is my Mix Doctor report. "
          "Give me the 5 most important moves, in order, with exact plugin settings, and tell me which track to apply each one to. "
          "My tracks are: [list your tracks].\"*".replace("{genre}", genre), "",
          "_Numbers are measured; suggestions are rules of thumb. Your ears and a reference track have the final say._"]
    return "\n".join(r)

def main():
    p = argparse.ArgumentParser(description="Analyze a bounced mix and suggest Logic Pro moves.")
    p.add_argument("mix")
    p.add_argument("--reference", "-r", help="a commercial track you want to sound close to")
    p.add_argument("--genre", "-g", default="rock", choices=sorted(GENRE_TONE))
    p.add_argument("--out", "-o", help="output folder (default: next to the mix)")
    args = p.parse_args()
    a = analyze(args.mix)
    ref = analyze(args.reference) if args.reference else None
    sug = suggest(a, args.genre, ref)
    out = args.out or os.path.dirname(os.path.abspath(args.mix))
    base = os.path.join(out, os.path.splitext(os.path.basename(args.mix))[0] + "_mixdoctor")
    with open(base + ".md", "w") as f:
        f.write(report_md(a, sug, args.genre, ref))
    a_out = dict(a, suggestions=[{"priority": p_, "title": t, "text": x} for p_, t, x in sug])
    if ref:
        a_out["reference"] = ref
    with open(base + ".json", "w") as f:
        json.dump(a_out, f, indent=2)
    L = a["loudness"]
    print(f"{a['file']}: {L['integrated_lufs']} LUFS, true peak {L['true_peak_dbtp']} dBTP, PLR {L['plr_db']} dB")
    for prio, title, _ in sug:
        print(f"  [{prio}] {title}")
    print(f"Report: {base}.md")

if __name__ == "__main__":
    main()
