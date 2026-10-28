# Mix Doctor

A virtual sound designer / engineer that the user chats with. Claude Code is the chat: it captures audio, runs the analyzer and shows results as a visual page in Chrome.

## Who you're talking to
Solo musician (rock, funk, ska, reggae, disco, electronic). Logic Pro on a MacBook Air, Scarlett 2i2. Little coding experience.
Talk as a musician, not an engineer. Keep chat text to a line or two; the result page does the showing.

## The chat loop (tone matching)
| User says | Run |
|---|---|
| a YouTube link + start/end | `python3 tools/md.py target "<url>" --start 0:40 --end 0:45` (add `--isolated` if they say it's just the guitar / a stem) |
| a reference file | `python3 tools/md.py target --file <path>` (add `--full-mix` if it's a whole song) |
| "listen", "listen again" | `python3 tools/md.py listen` (20 s from BlackHole; `--sec N` to change). Opens the page in Chrome. |
| a bounced take | `python3 tools/md.py listen --file <path>` |
| "show me again" | `python3 tools/md.py show` |
| "what's the target?" | `python3 tools/md.py status` |

Tell them before `listen` that recording starts at the "tink" and ends at the "glass" sound. Reply with the score, the ▲/▼, and the top move in one or two lines.
Sessions (target, takes, pages) live in `sessions/`, which git ignores.

## Engines
- `mix-doctor.html`: the one-page web app and **the reference for the tone logic** (profileFrom, toneRows, scoreOf, adviceFor, KIND/LIB/SEED/CHAINS).
- `tools/tone_doctor.py`: Python port of that logic, checked against the JS on the same audio (identical numbers). Change both together.
- `tools/tone_page.py`: the result page. `tools/md.py`: the commands above.
- `tools/mix_doctor.py`: whole-mix analyzer (LUFS, true peak, PLR, LRA, 7-band tone, stereo). Also provides `load_audio`.

Full-song references (YouTube targets by default) are judged on the guitar range only, 150 Hz–8 kHz; low end, fizz and width are skipped and the page says so. Take and target always use the same mode.

## Ableton Live (trial, Live 12 Suite features)
- Sets live in `~/AI/Ableton 2026/` (e.g. `project vibe coding Project/`). `.als` files are gzipped XML: read them to see saved tracks, routing and devices.
- `tools/ableton_rack.py rocket` writes Audio Effect Racks (.adg) into `~/Music/Ableton/User Library/Presets/Audio Effects/Audio Effect Rack/Mix Doctor/`, built from Live's factory presets.
- Live control: ableton-mcp (reviewed, pinned clone in `~/AI/ableton-mcp`, telemetry and dataset off) via `.mcp.json` (not committed). Remote Script in `User Library/Remote Scripts/AbletonMCP`; select AbletonMCP as Control Surface in Live. `tools/live.py` talks to it directly (port 9877).
- Live's log: `~/Library/Preferences/Ableton/Live 12.4.15/Log.txt` (load errors, script messages).
- Racks: `rocket` (first try), `rocket-notes` (clean + rocket in parallel), `rocket-blend` (the keeper: one serial chain, each device blends dry/wet, so the guitar sits inside the effect). The user prefers blended over "source + shadow".
- Rack pitfalls already fixed in the builder: devices need `Id`; the shell's chain-select zones faded in; the shell mapped chain volume to macro 8 (silenced everything). Leave macro mappings only on what we set.
- Shifter's envelope pitch is level-sensitive: hotter input needs less Climb, or pitch parks low and growls. Tune by recording BlackHole and turning macros via `tools/live.py`. The bridge only reaches top-level devices, so put anything we may tune on a macro.
- Live's audio output must be "Main Output" for BlackHole to hear it (a restart once switched it to the headphones).
- Measure one track at a time: nothing is soloed by default, so pause the other clips (stop_clip, record, fire_clip) or the beat pollutes the numbers.

## Recipes the user loved
- **Lo-fi beat:** `python3 tools/lofi_beat.py --chords Am,Gm` (65 BPM, Boom Bap Kit + E-Piano MKI Mellow + Upright Close Bass, swung). New loops go in the next free clip slot. The user keeps the first 4-bar drum loop and only swaps chords.
- **Daft Punk robot voice:**
  1. `python3 tools/robot_melody.py "<voice .wav>" --voice-track voce` transcribes the sung clip into a "Robot Carrier" MIDI track (clean saw, detune and drive off).
  2. Load the **Daft Robot** rack on the voice track, then in its Vocoder set Carrier = External, source Robot Carrier; set Robot Carrier's Audio To = Sends Only.
  3. Macros: Robot, Words (consonants), Octave Up (+12 double), Space, Gate, Formant.
  Clarity came from a clean carrier (no detune or drive) and narrow bands, not from more Enhance or level. The carrier type number for External (1) in the rack file is a guess until checked in a saved set.
- Auto pitch-tracked robot (Robot Me) works but sounds more like the user's own voice. The keyboard-carrier vocoder is the keeper.

## The user's rig ("My guitar · Heavenly Tweed", = SEED)
- Guitar (Input 1): Noise Gate → Amp Designer → Channel EQ → Compressor → Stereo Delay; send Bus 7; out Bus 5
- Mod FX (Bus 7): Modulation Delay → Flanger → Phaser; out Bus 5
- Heavenly Tweed stack (Bus 5): Compressor → Stereo Out. Stereo Out has a Mastering plugin: bypass it when comparing.

Audio: BlackHole 2ch + Multi-Output "Main Output" (Scarlett + BlackHole). Logic and macOS output → Main Output; we record "BlackHole 2ch".

## Reading results
15–30 s snippets, same notes as the reference. ±2–3 dB is small, 5 dB+ is real. Brightness, body, bite and fizz are dependable; sustain, echo and width are rough. Knob arrows mean "turn this way from where it is now": we can't read Logic's settings.

## Roadmap
1. ~~Chat loop: capture, analyze, visual page~~ (first version done)
2. Full songs as references: better moment picking, optional stem separation (Demucs)
3. Real-take testing and tuning of the advice rules
4. More genre idea chains, musician-language mix feedback, stem mode, one-click Logic presets
