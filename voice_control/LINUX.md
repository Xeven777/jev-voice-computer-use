# Linux support (X11)

Status: working from source on MX Linux / XFCE / X11, tested 2026-10-05. The
`observe → decide → act` loop (`core.py`, `goal.py`) is shared with Windows; only
the platform layer and model transport differ.

## What works

| Piece | Linux implementation |
| --- | --- |
| Screen reading | AT-SPI via `gi.repository.Atspi` (`platforms/linux/atspi.py`), falls back to a content-area surface when a window exposes no controls |
| Window inventory / focus / settle | `wmctrl -l -p` + `xdotool getactivewindow/getwindowgeometry` (`screen.py`) |
| Mouse & keyboard | `xdotool` (`input.py`): click, double/right, hover, scroll, type, key, chords, window ops |
| App launching | `.desktop` catalog scan + direct `Exec=` run (`apps.py`) |
| Push-to-talk | `pynput` Right Ctrl listener, `sounddevice` mic capture, `faster-whisper base.en` on CPU |
| Pill UI | tkinter bottom-center pill (`voice_linux.py`) |
| Model | OpenRouter Decisions API: `typesafe/jev-1.13`, `cloudflare/clef`, `cloudflare/clef-flash`; or local Ollama (`JEV_MODEL=ollama`) |

## Install

```bash
sudo apt install xdotool wmctrl gir1.2-atspi-2.0 python3-gi python3-tk \
                 portaudio19-dev libportaudio2
python3 -m venv .venv-voice
.venv-voice/bin/pip install -r requirements-linux.txt
.venv-voice/bin/pip install sounddevice faster-whisper pynput
```

If `pynput` fails to build `evdev`, `sudo apt install python3-evdev python3-pynput`
instead. Tk is needed for the pill (`python3-tk`).

## Run

```bash
# push-to-talk app (hold Right Ctrl, speak, release)
JEV_MODEL_ID=cloudflare/clef python3 -m voice_control.voice_linux

# headless one-shot / goal / repl
JEV_MODEL_ID=cloudflare/clef python3 -m voice_control.app_linux "launch thunar"
JEV_MODEL_ID=cloudflare/clef python3 -m voice_control.app_linux --goal "open the file manager"
python3 -m voice_control.app_linux --repl
```

Configuration, all optional:

| Env var | Meaning |
| --- | --- |
| `JEV_MODEL_ID` | Decisions-API model (e.g. `typesafe/jev-1.13`, `cloudflare/clef`, `cloudflare/clef-flash`) |
| `JEV_MODEL=ollama` | use local Ollama instead of OpenRouter (needs `ollama serve`) |
| `JEV_OLLAMA_MODEL` | Ollama model name (default `qwen2.5:1.5b`) |
| `JEV_PLATFORM=linux` | force the Linux backend (auto-detected on Linux) |
| `JEV_DEBUG=0` | quiet mode: hide every `$ xdotool ...` and `POST ...` trace line |
| `JEV_VOICE_HOME` | data folder (default `~/.local/share/Jev Voice Control`) |

The OpenRouter key is read from `OPENROUTER_API_KEY` or
`~/.local/share/Jev Voice Control/.env.openrouter` (chmod 600). Ollama needs no key.

## Model notes

- The Decisions API (`https://openrouter.ai/api/alpha/decisions`) is what `core.ask_questions`
  speaks. `typesafe/jev-1.13`, `cloudflare/clef` and `cloudflare/clef-flash` all accept its
  choice + noul questions and return calibrated probabilities in ~1 s.
- `respan/*` accepts only `noul` questions — it cannot answer "which action / which target",
  so it cannot drive the loop.
- Ollama models get the same questions but must generate JSON back; probabilities are
  uncalibrated and large state prompts are slow. Usable, but the decision models are better.

## Known limits

- **X11 only.** `xdotool`/`wmctrl` do not work on Wayland; a Wayland backend would need
  `ydotool`/`wtype` + a different capture path. XFCE on X11 is the tested target.
- **AT-SPI coverage varies.** Firefox needs accessibility enabled
  (`about:config → accessibility.force_disabled = -1`, restart); some GTK apps expose no
  controls until `at-spi-bus-launcher` is running. Sparse windows fall back to a content
  surface for right/double clicks.
- `set_slider` is not implemented on Linux (raise + use keys); everything else in the
  verb catalog executes.
- No installer, no tray menu settings, no Wayland, no GPU speech — speech is CPU `base.en`
  (~2.5–3 s to transcribe).
- Live click-through was verified manually (`launch_app`, target clicks); the Windows-only
  harnesses (`goal_eval`, `bench_*`) still import Win32 and do not run on Linux.

## Tests

```bash
python3 -m unittest voice_control.test_linux -v   # platform + adapter tests (no desktop needed)
```

`test_goal` / `test_core` import the Windows app and only run on Windows.
