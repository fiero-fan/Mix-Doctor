#!/usr/bin/env python3
"""
Mix Doctor, chat-driven. Claude Code runs these when you talk to it.

  python3 tools/md.py target "https://youtu.be/XXXX" --start 0:40 --end 0:45   # learn a YouTube bit (full song)
  python3 tools/md.py target "https://youtu.be/XXXX" --start 0:40 --end 0:45 --isolated
  python3 tools/md.py target --file reference.wav [--full-mix]                  # learn a file
  python3 tools/md.py listen [--sec 20]        # record BlackHole, compare, open the result page
  python3 tools/md.py listen --file take.wav   # compare a bounced file instead of recording
  python3 tools/md.py show                     # reopen the latest result page
  python3 tools/md.py status                   # what's the target, how many takes

Everything for one target lives in sessions/<date-name>/ (ignored by git).
"""
import argparse, datetime, glob, json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mix_doctor import load_audio
import tone_doctor as td
import tone_page

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS = os.path.join(ROOT, "sessions")
CURRENT = os.path.join(SESSIONS, "current.txt")
DEVICE = "BlackHole 2ch"
SR = 48000


def die(msg):
    print(msg)
    sys.exit(1)


def parse_time(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(str(v).strip().split(":"))))
    except ValueError:
        die(f"Couldn't read the time '{v}'. Use 0:40 or 40.")


def fmt(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "target"


# ---------------------------------------------------------------- session state
def session_dir():
    if not os.path.exists(CURRENT):
        die("No target yet. Give me a YouTube link with start/end, or a file.")
    return os.path.join(SESSIONS, open(CURRENT).read().strip())


def load_state(d):
    return json.load(open(os.path.join(d, "state.json")))


def save_state(d, st):
    json.dump(st, open(os.path.join(d, "state.json"), "w"), indent=1)


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s24le", dst], check=True)


def profile(path, guitar_range):
    x, sr = load_audio(path)
    return td.profile_from(x, sr, guitar_range=guitar_range)


# ---------------------------------------------------------------- target
def yt_download(url, start, end, dst):
    if not shutil.which("yt-dlp"):
        die("yt-dlp is missing: brew install yt-dlp")
    tmp = tempfile.mkdtemp(prefix="md-yt-")
    try:
        r = subprocess.run(["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "--no-simulate", "--print", "%(title)s",
                            "--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts", "-o", os.path.join(tmp, "clip.%(ext)s"), url],
                           capture_output=True, text=True)
        files = glob.glob(os.path.join(tmp, "clip.*"))
        if r.returncode or not files:
            die("YouTube download failed:\n" + (r.stderr.strip().splitlines() or ["(no message)"])[-1])
        to_wav(files[0], dst)
        return r.stdout.strip().splitlines()[0] if r.stdout.strip() else "YouTube clip"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_target(a):
    if a.isolated and a.full_mix:
        die("Pick one: --isolated or --full-mix.")
    os.makedirs(SESSIONS, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="md-target-")
    wav = os.path.join(tmpdir, "target.wav")
    if a.url:
        m = re.search(r"[?&]t=(\d+)", a.url)
        start = parse_time(a.start) if a.start else (float(m.group(1)) if m else 0)
        end = parse_time(a.end) if a.end else start + 20
        if end <= start:
            die("The end time has to be after the start.")
        title = yt_download(a.url, start, end, wav)
        source = f"YouTube {fmt(start)}–{fmt(end)}"
        full_mix = not a.isolated          # YouTube links are usually whole songs
    elif a.file:
        if not os.path.exists(a.file):
            die(f"Can't find {a.file}")
        to_wav(a.file, wav)
        title = os.path.splitext(os.path.basename(a.file))[0]
        source = "file"
        full_mix = a.full_mix               # files are usually isolated parts
    else:
        die("Give me a YouTube link (with --start/--end) or --file.")
    name = a.name or title
    prof = profile(wav, full_mix)
    if not prof or prof.get("tooQuiet"):
        die("That bit is almost silent. Try other start/end times.")
    sid = datetime.datetime.now().strftime("%Y-%m-%d-%H%M-") + slug(name)
    d = os.path.join(SESSIONS, sid)
    os.makedirs(d, exist_ok=True)
    shutil.move(wav, os.path.join(d, "target.wav"))
    shutil.rmtree(tmpdir, ignore_errors=True)
    save_state(d, {"target": {"name": name, "source": source, "url": a.url, "guitarRange": full_mix, "prof": prof}, "takes": []})
    open(CURRENT, "w").write(sid)
    print(f"Target learned: {name} ({source}{', judged on guitar range 150 Hz–8 kHz' if full_mix else ', isolated'}).")
    print("Say “listen” when you're ready to play.")


# ---------------------------------------------------------------- listen
def beep(name):
    snd = f"/System/Library/Sounds/{name}.aiff"
    if os.path.exists(snd):
        subprocess.run(["afplay", snd])


def record(dst, sec):
    beep("Tink")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", f":{DEVICE}",
                        "-t", str(sec), "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s24le", dst], capture_output=True, text=True)
    beep("Glass")
    if r.returncode:
        die(f"Couldn't record from {DEVICE}:\n{r.stderr.strip()[-400:]}\n"
            "If macOS asked about the microphone, allow it and try again.")


def cmd_listen(a):
    d = session_dir()
    st = load_state(d)
    tg = st["target"]
    n = len(st["takes"]) + 1
    wav = os.path.join(d, f"take-{n}.wav")
    if a.file:
        to_wav(a.file, wav)
    else:
        record(wav, a.sec)
    prof = profile(wav, tg["guitarRange"])
    if not prof or prof.get("tooQuiet"):
        os.remove(wav)
        die("I heard almost nothing. Is Logic playing, and is its output set to Main Output?")
    rows = td.tone_rows(tg["prof"], prof)
    take = {"n": n, "name": f"Take {n}", "file": os.path.basename(wav), "prof": prof, "score": td.score_of(rows),
            "at": datetime.datetime.now().isoformat(timespec="seconds")}
    prev = st["takes"][-1] if st["takes"] else None
    prev_rows = td.tone_rows(tg["prof"], prev["prof"]) if prev else None
    chain = td.SEED
    adv = td.advice_for(rows, chain)
    st["takes"].append(take)
    save_state(d, st)
    page = os.path.join(d, f"take-{n}.html")
    with open(page, "w") as f:
        f.write(tone_page.render(take=take, prev=prev, target=tg, rows=rows, prev_rows=prev_rows,
                                 adv=adv, chain=chain, takes=st["takes"]))
    # short line for the chat
    delta = ""
    if prev:
        dd = take["score"] - prev["score"]
        delta = f" ({'▲' if dd >= 0 else '▼'}{abs(dd)} vs take {prev['n']})"
    print(f"Take {n}: {take['score']}% close{delta}. {td.verdict(take['score'])}")
    for i, m in enumerate(adv, 1):
        print(f"  {i}. {m['plugin']} · {m['knob'].split('|')[0]} {m['dir']} {m['amt']}".rstrip() + f": {m['why']}")
    print(f"Page: {page}")
    if not a.no_open:
        open_page(page)


def open_page(page):
    if os.path.exists("/Applications/Google Chrome.app"):
        subprocess.run(["open", "-a", "Google Chrome", page])
    else:
        subprocess.run(["open", page])


def cmd_show(a):
    d = session_dir()
    pages = sorted(glob.glob(os.path.join(d, "take-*.html")), key=lambda p: int(re.search(r"take-(\d+)", p).group(1)))
    if not pages:
        die("No takes yet. Say “listen”.")
    open_page(pages[-1])
    print(f"Opened {pages[-1]}")


def cmd_status(a):
    d = session_dir()
    st = load_state(d)
    t = st["target"]
    print(f"Target: {t['name']} ({t['source']}, {'guitar range only' if t['guitarRange'] else 'isolated'})")
    for k in st["takes"]:
        print(f"  {k['name']}: {k['score']}%")
    if not st["takes"]:
        print("  no takes yet")


def main():
    p = argparse.ArgumentParser(description="Mix Doctor, chat-driven tone matching.")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("target", help="learn a target sound")
    t.add_argument("url", nargs="?")
    t.add_argument("--start"); t.add_argument("--end")
    t.add_argument("--file"); t.add_argument("--name")
    t.add_argument("--isolated", action="store_true", help="the reference is just the guitar")
    t.add_argument("--full-mix", action="store_true", help="the reference file is a whole song")
    l = sub.add_parser("listen", help="record a take and compare")
    l.add_argument("--sec", type=float, default=20)
    l.add_argument("--file", help="use a bounced file instead of recording")
    l.add_argument("--no-open", action="store_true")
    sub.add_parser("show"); sub.add_parser("status")
    a = p.parse_args()
    {"target": cmd_target, "listen": cmd_listen, "show": cmd_show, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
