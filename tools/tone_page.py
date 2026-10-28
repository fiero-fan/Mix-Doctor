"""
Mix Doctor result page: one self-contained HTML file per take.
Looks like the Compare and Fix cards in mix-doctor.html (same colours, sliders, mixer strips).
"""
import html, math, re
from tone_doctor import KIND, verdict

esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)

CSS = """
:root{color-scheme:light;--bg:#f3f2ef;--surface-1:#fcfcfb;--surface-2:#f0efec;--line:#dedcd6;
 --text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7974;--series-1:#2a78d6;--series-2:#eb6834;
 --range:#e4e2dc;--accent:#2a78d6;--hot:#eb6834;--good:#1b7a3f}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#121211;--surface-1:#1a1a19;--surface-2:#232321;--line:#33332f;
 --text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;--series-1:#3987e5;--series-2:#d95926;--range:#2c2c29;
 --accent:#3987e5;--hot:#e0743f;--good:#4cc27a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text-primary);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0}
.top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.muted{color:var(--text-muted);font-size:13px}
.badge{display:inline-block;background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);border-radius:999px;padding:3px 10px;font-size:13px;font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px;min-width:0}
.card h2{font-size:16px;margin:0 0 10px}
.cmp-top{display:flex;gap:18px;align-items:center}
.score{position:relative;width:96px;height:96px;flex:0 0 96px}
.score span{position:absolute;inset:0;display:grid;place-items:center;font-size:24px;font-weight:700}
.verdict{font-size:19px;font-weight:600}
.up{color:var(--good);font-weight:600}.down{color:var(--hot);font-weight:600}
.legend{display:flex;gap:14px;font-size:13px;color:var(--text-secondary);margin:14px 0 4px;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:4px}
svg text{fill:var(--text-secondary);font-size:11px}
.dims{display:grid;grid-template-columns:92px minmax(150px,1fr) 92px;gap:2px 10px;align-items:center;font-size:14px}
.track{position:relative;height:38px}
.track::before{content:"";position:absolute;left:0;right:0;top:10px;height:2px;background:var(--line)}
.track .ok{position:absolute;top:6px;height:10px;background:var(--range);border-radius:5px}
.track .tg{position:absolute;top:2px;width:2px;height:18px;background:var(--series-2);margin-left:-1px}
.track .me{position:absolute;top:4px;width:14px;height:14px;border-radius:50%;background:var(--series-1);margin-left:-7px;border:2px solid var(--surface-1)}
.track .was{position:absolute;top:5px;width:12px;height:12px;border-radius:50%;border:2px solid var(--series-1);margin-left:-6px;opacity:.45}
.track .ends{position:absolute;top:21px;left:0;right:0;display:flex;justify-content:space-between;font-size:10.5px;color:var(--text-muted)}
.st{font-size:13px;text-align:right}
.moves{display:grid;gap:8px;margin-bottom:14px}
.adv{display:flex;gap:10px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.adv .num{width:26px;height:26px;border-radius:50%;background:var(--hot);color:#fff;display:grid;place-items:center;font-weight:700;flex:0 0 26px}
.adv i{width:6px;align-self:stretch;border-radius:3px;flex:0 0 6px}
.adv b{display:block;font-size:15px}.adv small{color:var(--text-muted);font-size:13px}
.adv .arw{margin-left:auto;font-size:26px;font-weight:700;color:var(--hot)}
.mixer{display:flex;gap:10px;background:#1d1d1f;border-radius:14px;padding:12px;overflow-x:auto}
.strip{width:170px;flex:0 0 170px;background:#2a2a2d;border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:6px}
.strip .lbl{font-size:11px;color:#a1a1a6;text-transform:uppercase;letter-spacing:.06em;margin:2px 2px 0}
.strip .nm{color:#f5f5f7;font-weight:600;font-size:14px;text-align:center;padding:6px 0 2px;border-top:1px solid #3a3a3d;margin-top:auto}
.strip .out{color:#a1a1a6;font-size:11.5px;text-align:center}
.slot{display:flex;align-items:center;gap:7px;border-radius:6px;padding:7px 8px;background:#3a3a3e;color:#f5f5f7;font-size:13px;position:relative}
.slot.hit{outline:2px solid var(--hot);outline-offset:1px}
.slot i{width:6px;align-self:stretch;border-radius:3px;flex:0 0 6px}
.slot small{display:block;color:#a1a1a6;font-size:11px}
.slot .bdg{position:absolute;right:-6px;top:-6px;display:flex;gap:2px}
.slot .bdg span{width:18px;height:18px;border-radius:50%;background:var(--hot);color:#fff;font-size:11px;font-weight:700;display:grid;place-items:center;box-shadow:0 0 0 2px #2a2a2d}
.slot.add{background:transparent;border:1px dashed #5a5a5e;color:#a1a1a6;font-size:12px}
.send{display:flex;justify-content:space-between;background:#323236;border-radius:6px;padding:5px 8px;color:#d1d1d6;font-size:12px}
.plug{margin-top:16px}
.plug h3{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}
.plug h3 i{width:12px;height:12px;border-radius:3px;display:inline-block}
.knobs{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}
.knob{width:84px;text-align:center;position:relative;border-radius:10px;padding:4px 0}
.knob.hit{background:color-mix(in srgb,var(--hot) 14%,transparent)}
.knob .kv{font-weight:650;font-size:13.5px}.knob .kl{font-size:12px;color:var(--text-muted)}
.takes{list-style:none;margin:0;padding:0}
.takes li{display:flex;justify-content:space-between;padding:6px 2px;border-top:1px solid var(--line);font-size:14px}
.takes li:first-child{border-top:0}
.takes li.now{font-weight:650}
.note{font-size:12.5px;color:var(--text-muted);background:var(--surface-2);border-radius:9px;padding:8px 10px;margin-top:12px}
.warn{background:color-mix(in srgb,var(--hot) 12%,transparent);color:var(--text-primary)}
"""


def ring(p):
    r, c = 40, 2 * math.pi * 40
    col = "var(--good)" if p >= 80 else "var(--accent)" if p >= 60 else "var(--hot)"
    return (f'<svg width="96" height="96" viewBox="0 0 96 96" aria-hidden="true">'
            f'<circle cx="48" cy="48" r="{r}" style="stroke:var(--surface-2)" stroke-width="9" fill="none"/>'
            f'<circle cx="48" cy="48" r="{r}" style="stroke:{col}" stroke-width="9" fill="none" stroke-linecap="round" '
            f'stroke-dasharray="{c * p / 100:.1f} {c:.1f}" transform="rotate(-90 48 48)"/></svg>')


def curve_svg(labels, tv, yv, pv=None):
    W, H, m = 520, 190, dict(l=34, r=10, t=10, b=24)
    iw, ih = W - m["l"] - m["r"], H - m["t"] - m["b"]
    allv = tv + yv + (pv or [])
    lo, hi = math.floor((min(allv) - 2) / 6) * 6, math.ceil((max(allv) + 2) / 6) * 6
    x = lambda i: m["l"] + i / (len(labels) - 1) * iw
    y = lambda v: m["t"] + (hi - v) / (hi - lo) * ih
    g = ""
    for v in range(lo, hi + 1, 6):
        g += (f'<line x1="{m["l"]}" x2="{W - m["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" style="stroke:var(--line)"/>'
              f'<text x="{m["l"] - 5}" y="{y(v) + 4:.1f}" text-anchor="end">{"+" if v > 0 else ""}{v}</text>')
    for i, l in enumerate(labels):
        g += f'<text x="{x(i):.1f}" y="{H - 6}" text-anchor="middle">{l}</text>'
    path = lambda a: "".join(f'{"L" if i else "M"}{x(i):.1f},{y(v):.1f}' for i, v in enumerate(a))
    if pv:
        g += f'<path d="{path(pv)}" fill="none" style="stroke:var(--series-1)" stroke-width="2" stroke-dasharray="4 4" opacity=".45"/>'
    g += f'<path d="{path(tv)}" fill="none" style="stroke:var(--series-2)" stroke-width="2.5" stroke-linejoin="round"/>'
    g += f'<path d="{path(yv)}" fill="none" style="stroke:var(--series-1)" stroke-width="2.5" stroke-linejoin="round"/>'
    for i, v in enumerate(yv):
        d = v - tv[i]
        g += (f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" style="fill:var(--series-1);stroke:var(--surface-1)" stroke-width="2">'
              f'<title>{labels[i]} Hz: you {d:+.1f} dB vs target</title></circle>')
    return f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Tone curve, target vs you">{g}</svg>'


def knob_svg(hot):
    """Your settings aren't visible, so every knob is a '?' knob; hot ones get the accent ring."""
    col = "var(--hot)" if hot else "var(--line)"
    return (f'<svg width="64" height="58" viewBox="0 0 72 66" aria-hidden="true">'
            f'<path d="M16.2,55.8A28,28 0 1 1 55.8,55.8" style="stroke:var(--line)" stroke-width="6" fill="none" stroke-linecap="round"/>'
            f'<circle cx="36" cy="36" r="15" style="fill:var(--surface-2);stroke:{col}" stroke-width="{2 if hot else 1}"/>'
            f'<text x="36" y="41" text-anchor="middle" style="font-size:14px;fill:var(--text-muted)">?</text></svg>')


ARROW_WORD = {"↑": "turn up", "↓": "turn down"}


def render(*, take, prev, target, rows, prev_rows, adv, chain, takes):
    sc = take["score"]
    d = sc - prev["score"] if prev and prev.get("score") is not None else None
    gr = target.get("guitarRange")
    # --- compare card
    delta = (f'<div class="{"up" if d >= 0 else "down"}">{"▲" if d >= 0 else "▼"} {abs(d)} since {esc(prev["name"])}</div>'
             if d is not None else '<div class="muted">Fix something, then say “listen again”.</div>')
    dims = ""
    for i, r in enumerate(rows):
        pos = lambda v: 50 + 50 * max(-1, min(1, v / r["scale"]))
        ok = abs(r["diff"]) <= r["tol"]
        pr = next((p for p in (prev_rows or []) if p["key"] == r["key"]), None)
        rough = " <span class='muted'>(rough)</span>" if r["key"] in ("sustain", "space", "width") else ""
        dims += (f'<div>{r["label"]}{rough}</div><div class="track">'
                 f'<div class="ok" style="left:{pos(-r["tol"]):.1f}%;width:{pos(r["tol"]) - pos(-r["tol"]):.1f}%"></div><div class="tg" style="left:50%"></div>'
                 + (f'<div class="was" style="left:{pos(pr["diff"]):.1f}%"></div>' if pr else "")
                 + f'<div class="me" style="left:{pos(r["diff"]):.1f}%"></div><div class="ends"><span>{r["less"]}</span><span>{r["more"]}</span></div></div>'
                 f'<div class="st" style="color:{"var(--good)" if ok else "var(--hot)"}">{"✓ close" if ok else (r["more"] if r["diff"] > 0 else r["less"])}</div>')
    legend = ('<div class="legend"><span><i style="background:var(--series-2)"></i>Target</span>'
              '<span><i style="background:var(--series-1)"></i>You</span>'
              + ('<span><i style="background:var(--series-1);opacity:.45"></i>Last take</span>' if prev else "") + "</div>")
    compare = (f'<div class="card"><h2>Compare</h2><div class="cmp-top"><div class="score">{ring(sc)}<span>{sc}%</span></div>'
               f'<div><div class="verdict">{verdict(sc)}</div>{delta}</div></div>{legend}'
               f'{curve_svg(target["prof"]["labels"], target["prof"]["curve"], take["prof"]["curve"], prev["prof"]["curve"] if prev else None)}'
               f'<div class="dims">{dims}</div>'
               + ('<div class="note">Full song: judged on the guitar range only (150 Hz – 8 kHz). Low end, fizz and width are left out.</div>' if gr else "")
               + '<div class="note">±2–3 dB is small, 5 dB+ is real. Brightness, body and bite are dependable; sustain and echo are rough.</div></div>')
    # --- fix card
    badges = {}
    for i, a in enumerate(adv):
        if a["slot"]:
            badges.setdefault(tuple(a["slot"]), []).append(i + 1)
    if adv:
        moves = "".join(
            f'<div class="adv"><span class="num">{i + 1}</span><i style="background:{KIND.get(a["kind"], KIND["utility"])[0]}"></i>'
            f'<span><b>{esc(a["plugin"])} · {esc(a["knob"].split("|")[0])}</b><small>{ARROW_WORD.get(a["dir"], a["dir"])} {esc(a["amt"])} · {esc(a["why"])}</small></span>'
            f'<span class="arw">{a["dir"]}</span></div>' for i, a in enumerate(adv))
    else:
        moves = '<div class="note">Nothing to change: every slider is in the close zone. 🎉</div>'
    strips = ""
    for si, s in enumerate(chain["strips"]):
        slots = ""
        for i, sl in enumerate(s["slots"]):
            k, b = KIND.get(sl["kind"], KIND["utility"]), badges.get((si, i))
            slots += (f'<div class="slot{" hit" if b else ""}"><i style="background:{k[0]}"></i><span>{esc(sl["plugin"])}<small>{k[1]}</small></span>'
                      + (f'<span class="bdg">{"".join(f"<span>{n}</span>" for n in b)}</span>' if b else "") + "</div>")
        if si == 0:
            slots += "".join(f'<div class="slot add">+ {esc(a["plugin"])}</div>' for a in adv if not a["slot"] and a["kind"] != "tracks")
        sends = (('<div class="lbl">Sends</div>' + "".join(f'<div class="send"><span>{esc(x[0])}</span><span>{esc(x[1])}</span></div>' for x in s["sends"]))
                 if s.get("sends") else "")
        strips += (f'<div class="strip"><div class="lbl">Audio FX</div>{slots}{sends}<div class="nm">{esc(s["name"])}</div>'
                   + (f'<div class="out">→ {esc(s["out"])}</div>' if s.get("out") else "") + "</div>")
    plugs = ""
    for (si, i), nums in badges.items():
        sl = chain["strips"][si]["slots"][i]
        here = [a for a in adv if a["slot"] and tuple(a["slot"]) == (si, i)]
        kn = ""
        for l, v, _ in sl.get("knobs") or []:
            h = next((a for a in here if re.search(a["knob"], l, re.I)), None)
            kn += (f'<div class="knob{" hit" if h else ""}">{knob_svg(bool(h))}'
                   f'<div class="kv">{(h["dir"] + " " + esc(h["amt"])) if h else esc(v or "–")}</div><div class="kl">{esc(l)}</div></div>')
        k = KIND.get(sl["kind"], KIND["utility"])
        plugs += (f'<div class="plug"><div class="muted">{esc(chain["strips"][si]["name"])} · slot {i + 1} · move {", ".join(map(str, nums))}</div>'
                  f'<h3><i style="background:{k[0]}"></i>{esc(sl["plugin"])}</h3><div class="knobs">{kn}</div></div>')
    fix = (f'<div class="card"><h2>Fix · on {esc(chain["name"])}</h2><div class="moves">{moves}</div>'
           f'<div class="mixer">{strips}</div>{plugs}'
           '<div class="note">Arrows mean “turn this way from where it is now”: the app can’t see your Logic settings. '
           'Bypass the Mastering plugin on Stereo Out while comparing.</div></div>')
    # --- takes
    lis = "".join(f'<li class="{"now" if t["n"] == take["n"] else ""}"><span>{esc(t["name"])}</span><span>{t["score"]}%</span></li>'
                  for t in reversed(takes))
    hist = f'<div class="card"><h2>Takes</h2><ul class="takes">{lis}</ul></div>'
    src = target.get("source") or ""
    head = (f'<div class="top"><h1>Mix Doctor</h1><span class="muted">{esc(take["name"])} vs <b>{esc(target["name"])}</b>'
            + (f' · {esc(src)}' if src else "") + '</span>'
            + ('<span class="badge">Guitar range only</span>' if gr else "") + "</div>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Mix Doctor · {esc(take["name"])}</title><style>{CSS}</style></head><body><div class="wrap">{head}'
            f'<div class="grid"><div>{compare}{hist}</div><div>{fix}</div></div></div></body></html>')
