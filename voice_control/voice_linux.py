"""Linux push-to-talk voice app: hold Right Ctrl, speak, release -> act.

Same flow as Windows app.py, minus Win32:
   key down ......... start mic stream + background AT-SPI capture (for hotwords)
   while held ........ live captions via faster-whisper (CPU base.en)
   key up ........... final transcribe -> plan (single or goal mode) -> execute
   pill ............. tkinter bottom dot, no Win32 click-through tricks
   tray ............. pystray if present, else headless
   model ............ JEV_MODEL=ollaya (local Ollaya/Laya), ollama (local LLM),
                      or jev (OpenRouter/TypeSafe key)

Run:  JEV_MODEL=ollaya python3 -m voice_control.voice_linux
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

from . import goal as goal_loop
from .core import (
    append_log,
    asr_hotwords,
    collapse_repeats,
    plan_command,
    read_key,
)
from .models import router
from .platform_api import load_backend

SAMPLE_RATE = 16000
HOME = Path(os.environ.get("JEV_VOICE_HOME") or Path.home() / ".local" / "share" / "Jev Voice Control")
KEY_FILE = HOME / ".env.openrouter"
LOG = HOME / "logs" / "voice-actions.jsonl"
AUDIO_DIR = HOME / "logs" / "audio"
SETTINGS = HOME / ".voice-settings.json"
REPLAY_FIELDS = {"inputs", "prompts", "jev_calls"}

backend = load_backend("linux")
router.install()
def save_clip(audio, uid: str) -> str:
    import wave
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / f"{uid}.wav"
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return str(path.relative_to(HOME))


def load_settings() -> dict:
    base = {"auto_run": True, "goal_mode": True, "hide_when_idle": False,
            "keep_logs": False, "pill_anchor": None}
    try:
        return {**base, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except Exception:
        return base


class Pill:
    """Minimal bottom pill: dot -> listening -> working -> done/error."""

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#1c1c1e")
        self.label = tk.Label(self.win, text="●", fg="#3ecf8e", bg="#1c1c1e",
                              font=("Sans", 13), padx=14, pady=6)
        self.label.pack()
        self.state = "idle"
        self._place()

    def _place(self):
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth() or 120
        x = (self.win.winfo_screenwidth() - w) // 2
        y = self.win.winfo_screenheight() - 90
        self.win.geometry(f"+{x}+{y}")

    def _set(self, text: str, color: str):
        self.label.config(text=text, fg=color)
        self._place()

    def show(self, state, transcript="", step="", title="", detail="", **_):
        self.state = state
        if state == "listening":
            self._set(f"mic {transcript[-60:]}", "#ff9f0a")
        elif state == "working":
            self._set(f">> {step or transcript or title}"[:80], "#5aa9ff")
        elif state == "done":
            self._set(f"ok {title or transcript}"[:80], "#3ecf8e")
        elif state == "review":
            self._set(f"? {title}"[:80], "#f5b544")
        else:
            self._set(f"x {title or 'error'}"[:80], "#ff5a5a")

    def update(self, transcript="", step=""):
        if self.state == "listening" and transcript:
            self._set(f"mic {transcript[-60:]}", "#ff9f0a")
        elif step:
            self._set(f">> {step}"[:80], "#5aa9ff")

    def collapse(self):
        self.state = "idle"
class VoiceLinux:
    def __init__(self):
        try:
            self.key = read_key(KEY_FILE)
        except RuntimeError:
            self.key = ""  # Ollama needs no key; single-shot Jev mode will complain later
        self.settings = load_settings()
        self.root = tk.Tk()
        self.root.withdraw()
        self.auto = tk.BooleanVar(value=self.settings["auto_run"])
        self.goal_mode = tk.BooleanVar(value=self.settings["goal_mode"])
        self.pill = Pill(self.root)
        self.events: queue.Queue = queue.Queue()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jev-voice")
        self.capturer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jev-capture")
        self.model = None
        self.model_device = "loading"
        self.model_name = "base.en"
        self.key_held = False
        self.key_chorded = False
        self.stream = None
        self.frames: list = []
        self.scene = None
        self.apps_cache: list = []
        self.apps_at = 0.0
        self.take = 0
        self.uid = ""
        self.busy = False
        self.goal_active = False
        self.goal_stop = threading.Event()
        self.partial_busy = False
        self.partial_len = 0
        self.recording = False
        self._load_model()
        self._start_tray()
        from pynput import keyboard as kb
        self._kb = kb
        self.listener = kb.Listener(on_press=self._press, on_release=self._release)
        self.listener.start()
        self.root.after(100, self._drain)
        try:
            self.apps_cache = backend.installed_apps()
            self.apps_at = time.monotonic()
        except Exception:
            pass

    def _load_model(self):
        def load():
            try:
                name = os.environ.get("JEV_WHISPER_MODEL", "base.en")
                print(f"loading whisper {name} (cpu)...", flush=True)
                from faster_whisper import WhisperModel
                self.model = WhisperModel(name, device="cpu", compute_type="int8")
                self.model_device = "cpu"
                self.model_name = name
                print("whisper ready.", flush=True)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(f"whisper FAILED: {exc}", flush=True)
                self.model = exc
                self.model_device = "failed"
        threading.Thread(target=load, daemon=True).start()

    def _warm(self):
        while self.model is None:
            time.sleep(0.1)
        if isinstance(self.model, Exception):
            raise RuntimeError(f"Speech model failed: {self.model}")
        if self.model_device == "cpu" and self.model_name != "warmed":
            try:
                zeros = np.zeros(SAMPLE_RATE, dtype=np.float32)
                list(self.model.transcribe(zeros, language="en"))
                self.model_name = "warmed"
            except Exception:
                pass

    def _transcribe(self, audio, hotwords="") -> str:
        self._warm()
        prompt = ("A voice command. " + hotwords[:400]) if hotwords else "A voice command."
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                        vad_filter=True, initial_prompt=prompt)
        return collapse_repeats(" ".join(s.text for s in segs).strip())

    def _press(self, key) -> None:
        if key == self._kb.Key.ctrl_r and not self.key_held:
            self.key_held = True
            self.key_chorded = False
            self.events.put(("start", None))
        elif self.key_held:
            self.key_chorded = True
            self.events.put(("cancel", None))

    def _release(self, key) -> None:
        if key == self._kb.Key.ctrl_r and self.key_held:
            self.key_held = False
            self.events.put(("stop" if not self.key_chorded else "cancelled", None))
    def _capture_scene(self, wid):
        try:
            return (wid, *backend.capture_settled(wid))
        except Exception as exc:
            return (wid, {"error": str(exc)[:200]}, [])

    def _on_start(self):
        if self.busy:
            return
        import sounddevice as sd
        self.busy = True
        self.recording = True
        self.take += 1
        try:
            from .platforms.linux import screen
            active = screen.active_window_id()
        except Exception:
            active = None
        self.scene = (active, self.capturer.submit(self._capture_scene, active))
        self.frames = []
        self.partial_busy, self.partial_len = False, 0
        self.uid = f"linux-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.pill.show("listening", transcript="Listening...")
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                     dtype="float32", blocksize=2048,
                                     callback=self._audio_cb)
        self.stream.start()

    def _audio_cb(self, indata, frames_count, time_info, status):
        if getattr(self, "recording", False):
            self.frames.append(indata.copy().reshape(-1))
            total = sum(len(f) for f in self.frames)
            if total - self.partial_len > SAMPLE_RATE * 0.7 and not self.partial_busy:
                self.partial_busy = True
                self.partial_len = total
                audio = np.concatenate(self.frames)
                threading.Thread(target=self._partial, args=(audio,), daemon=True).start()

    def _partial(self, audio):
        try:
            text = self._transcribe(audio)
            if text and getattr(self, "recording", False):
                self.events.put(("caption", text))
        except Exception:
            pass
        finally:
            self.partial_busy = False

    def _finish(self):
        self.recording = False
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        if not self.frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.frames)


        self._set("●", "#3ecf8e")

    def _on_stop(self):
        audio = self._finish()
        if len(audio) < SAMPLE_RATE * 0.25:
            self.pill.collapse()
            self.busy = False
            return
        uid = self.uid
        self.pill.show("working", step="Hearing you...")
        self.worker.submit(self._plan_audio, audio, self.scene, uid)

    def _plan_audio(self, audio, scene, uid):
        t_start = time.monotonic()
        print(f"[{uid}] audio {len(audio)/SAMPLE_RATE:.1f}s, waiting for screen capture...",
              flush=True)
        try:
            hotwords = ""
            state, controls = {"error": "no scene"}, []
            if scene is not None:
                try:
                    _, state, controls = scene[1].result(timeout=10)
                    hotwords = asr_hotwords(state, controls)
                    print(f"[{uid}] screen: {state.get('activeWindow', {}).get('title', '?')} "
                          f"({len(controls)} controls)", flush=True)
                except Exception as exc:
                    print(f"[{uid}] capture failed: {exc}", flush=True)
                    state, controls = {"error": "capture failed"}, []
            print(f"[{uid}] transcribing with {self.model_name} ({self.model_device})...",
                  flush=True)
            transcript = self._transcribe(audio, hotwords)
            t_heard = time.monotonic()
            print(f"[{uid}] heard: {transcript!r} "
                  f"({round((t_heard-t_start)*1000)}ms)", flush=True)
            if len(audio) / SAMPLE_RATE < 0.4 or not transcript:
                self.events.put(("result", (uid, transcript, "too short", "")))
                return
            record = {"utterance_id": uid, "task": transcript, "take": self.take,
                      "model": {"name": self.model_name, "device": self.model_device},
                      "jev_calls": []}
            if time.monotonic() - self.apps_at > 300 or not self.apps_cache:
                try:
                    self.apps_cache = backend.installed_apps()
                    self.apps_at = time.monotonic()
                except Exception:
                    pass
            from .core import snapshot_inputs
            record["inputs"] = snapshot_inputs(transcript, state, self.apps_cache)
            t_state = time.monotonic()
            self.events.put(("heard", transcript))
            if self.goal_mode.get():
                print(f"[{uid}] goal mode: asking {os.environ.get('JEV_OLLAMA_MODEL', 'model')}...",
                      flush=True)
                self._run_goal(uid, transcript, record)
                return
            t_jev = time.monotonic()
            print(f"[{uid}] asking model to plan...", flush=True)
            plan_command(self.key, transcript, state, controls, self.apps_cache, record)
            t_planned = time.monotonic()
            verb = record.get("verb", {}).get("choice")
            print(f"[{uid}] plan: {verb} "
                  f"({round((t_planned-t_jev)*1000)}ms) full={json.dumps(record.get('verb', {}))[:200]}",
                  flush=True)
            if self.auto.get() and verb not in (None, "no_action"):
                print(f"[{uid}] executing {verb}...", flush=True)
                msg = backend.execute(verb, record.get("target", {}),
                                      state, controls, self.apps_cache, transcript,
                                      None, record.get("text"))
                print(f"[{uid}] done: {msg}", flush=True)
                record["result"] = msg
                record["outcome"] = "executed"
            else:
                record["outcome"] = "planned"
            record["timings_ms"] = {"t": round((t_heard - t_start) * 1000)}
            try:
                record["audio"] = save_clip(audio, uid)
            except Exception:
                pass
            if self.settings.get("keep_logs"):
                append_log(LOG, record)
            self.events.put(("result", (uid, transcript, record.get("outcome", "?"),
                                        record.get("result", verb or ""))))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"[{uid}] FAILED: {exc}", flush=True)
            self.events.put(("result", (uid, "", f"error: {exc}", "")))

    def _run_goal_debug(self):
        pass

    def _run_goal(self, uid, transcript, record):
        self.goal_active = True
        self.goal_stop.clear()
        apps = self.apps_cache
        box = {}

        def observe(_hwnd=None):
            try:
                s, c = backend.capture_settled()
                box["state"], box["controls"] = s, c
            except Exception:
                pass
            return box.get("state", {}), box.get("controls", []), apps

        def act(verb, target, st, ct, app_list, text):
            msg = backend.execute(verb, target, st, ct, app_list, transcript, None, text)
            self.events.put(("step", msg))
            return msg

        outcome = goal_loop.run_goal(self.key, transcript, observe, act, record,
                                progress=lambda *_: None,
                                should_stop=lambda: self.goal_stop.is_set())
        self.goal_active = False
        steps = record.get("steps", [])
        if steps and steps[-1].get("error"):
            print(f"[{uid}] step error: {steps[-1]['error']}", flush=True)
            tb = steps[-1].get("traceback", "")
            if tb:
                print(tb, flush=True)
        if record.get("jev_calls"):
            last = record["jev_calls"][-1]
            print(f"[{uid}] last jev call: http={last.get('http_status')} "
                  f"err={str(last.get('error_body', ''))[:300]}", flush=True)
        self.events.put(("result", (uid, transcript, f"goal: {outcome}",
                                    f"{len(steps)} steps")))

    def _start_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse([8, 8, 56, 56], fill=(62, 207, 142, 255))
            menu = pystray.Menu(pystray.MenuItem("Quit", lambda *_: self.quit()))
            self.tray = pystray.Icon("jev-voice", img, "Jev Voice (Linux)", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            self.tray = None

    def quit(self):
        try:
            self.listener.stop()
        except Exception:
            pass
        try:
            if getattr(self, "tray", None):
                self.tray.stop()
        except Exception:
            pass
        self.root.quit()

    def _drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "start":
                    self._on_start()
                elif kind == "stop":
                    self._on_stop()
                elif kind in ("cancel", "cancelled"):
                    self.recording = False
                    try:
                        if self.stream:
                            self.stream.stop()
                            self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
                    self.goal_stop.set()
                    self.goal_active = False
                    self.busy = False
                    self.pill.collapse()
                elif kind == "caption":
                    if self.pill.state == "listening":
                        self.pill.update(transcript=value)
                elif kind == "heard":
                    self.pill.show("working", transcript=value, step="Reading...")
                elif kind == "step":
                    self.pill.show("working", step=str(value)[:70])
                elif kind == "result":
                    uid, transcript, outcome, detail = value
                    self.busy = False
                    if outcome in ("executed",) or outcome.startswith("goal: done"):
                        self.pill.show("done", title=f"{outcome} - {detail}"[:80])
                    elif outcome in ("too short",):
                        self.pill.collapse()
                    else:
                        self.pill.show("error", title=f"{outcome} {detail}"[:80])
                    self.root.after(4000, lambda: self.pill.collapse()
                                    if self.pill.state in ("done", "error") else None)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def run(self):
        print("Jev Voice (Linux): hold Right Ctrl and speak. Ctrl+C quits.")
        self.root.mainloop()


def main() -> int:
    VoiceLinux().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
