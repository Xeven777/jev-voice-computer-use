"""Linux tests: no desktop side effects (all subprocess/AT-SPI calls mocked)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


class ScreenParseTest(unittest.TestCase):
    def test_wmctrl_skips_panels_and_keeps_hwnd_alias(self):
        from voice_control.platforms.linux import screen
        sample = ("0x01000003 -1 2376 xeven xfce4-panel\n"
                  "0x01600017  0 4830 xeven ChatGPT — Mozilla Firefox\n")
        with patch.object(screen, "_run", return_value=sample):
            with patch.object(screen, "process_name", return_value="firefox-bin"):
                wins = screen.open_windows()
        self.assertEqual(len(wins), 1)
        self.assertEqual(wins[0]["title"], "ChatGPT — Mozilla Firefox")
        self.assertEqual(wins[0]["wid"], wins[0]["hwnd"])

    def test_window_rect_parses_shell_geometry(self):
        from voice_control.platforms.linux import screen
        geo = "WINDOW=23068695\nX=0\nY=24\nWIDTH=1920\nHEIGHT=1056\nSCREEN=0\n"
        with patch.object(screen, "_run", return_value=geo):
            self.assertEqual(screen.window_rect(123), (0, 24, 1920, 1080))


class OllamaAdapterTest(unittest.TestCase):
    def test_normalises_choice_and_noul(self):
        from voice_control.models import ollama
        fake = {"message": {"content": json.dumps({
            "verb": {"choice": "LEFT_CLICK", "probability": 0.9},
            "goal_done": {"noul": 1.7}})}}
        resp = MagicMock(status_code=200, json=MagicMock(return_value=fake))
        resp.raise_for_status = MagicMock()
        questions = {
            "verb": {"type": "choice", "criteria": {"left_click": "click", "none": "nothing"}},
            "goal_done": {"type": "noul"},
        }
        with patch.object(ollama.requests, "post", return_value=resp):
            answers, _ = ollama.ask_questions("", "click it", {}, questions)
        self.assertEqual(answers["verb"]["choice"], "left_click")
        self.assertEqual(answers["goal_done"]["noul"], 1.0)

    def test_unreachable_host_raises_helpfully(self):
        from voice_control.models import ollama
        with patch.object(ollama.requests, "post", side_effect=OSError("nope")):
            with self.assertRaises(RuntimeError):
                ollama.ask_questions("", "t", {}, {"d": {"type": "noul"}})


class OllayaAdapterTest(unittest.TestCase):
    def test_returns_jev_shaped_answers(self):
        from voice_control.models import ollaya
        fake = {"model": "laya:en", "answers": {
            "verb": {"type": "choice", "choice": "left_click", "confidence": 0.8,
                     "probabilities": {"left_click": 0.8, "none": 0.2}},
            "goal_done": {"type": "noul", "noul": 0.1}}}
        resp = MagicMock(status_code=200, json=MagicMock(return_value=fake))
        resp.raise_for_status = MagicMock()
        questions = {
            "verb": {"type": "choice", "criteria": {"left_click": "click", "none": "nothing"}},
            "goal_done": {"type": "noul"},
        }
        with patch.object(ollaya.requests, "post", return_value=resp) as post:
            answers, _ = ollaya.ask_questions("", "click it", {}, questions)
            self.assertIn("/api/decide", post.call_args[0][0])
        self.assertEqual(answers["verb"]["choice"], "left_click")
        self.assertEqual(answers["goal_done"]["noul"], 0.1)

    def test_unreachable_host_raises_helpfully(self):
        from voice_control.models import ollaya
        with patch.object(ollaya.requests, "post", side_effect=OSError("nope")):
            with self.assertRaises(RuntimeError):
                ollaya.ask_questions("", "t", {}, {"d": {"type": "noul"}})

    def test_single_option_choice_is_synthesized_without_http(self):
        from voice_control.models import ollaya
        questions = {"target": {"type": "choice", "criteria": {"none": "nothing fits"}}}
        with patch.object(ollaya.requests, "post") as post:
            answers, _ = ollaya.ask_questions("", "t", {}, questions, trace=[])
            post.assert_not_called()
        self.assertEqual(answers["target"]["choice"], "none")

    def test_router_install_patches_core_and_goal(self):
        import os
        from voice_control import core, goal
        from voice_control.models import router
        orig_core, orig_goal = core.ask_questions, goal.ask_questions
        try:
            with patch.dict(os.environ, {"JEV_MODEL": "ollaya"}):
                self.assertEqual(router.install(), "ollaya")
            self.assertIs(core.ask_questions, router.ask_questions)
            self.assertIs(goal.ask_questions, router.ask_questions)
        finally:
            core.ask_questions, goal.ask_questions = orig_core, orig_goal


class CaptureSettledTest(unittest.TestCase):
    def test_sparse_still_screen_returns_after_two_rereads(self):
        from voice_control.platforms.linux import backend
        state = {"activeWindow": {"wid": 1}, "loading": []}
        calls: list = []

        def fake_capture(wid=None):
            calls.append(wid)
            return state, [object()]

        with patch.object(backend, "capture", side_effect=fake_capture):
            with patch("time.sleep"):
                backend.capture_settled(timeout_s=30)
        self.assertEqual(len(calls), 3)  # first look + 2 still re-reads, not ~75

    def test_growing_screen_keeps_waiting(self):
        from voice_control.platforms.linux import backend
        state = {"activeWindow": {"wid": 1}, "loading": []}
        counts = [1, 2, 3]
        calls: list = []

        def fake_capture(wid=None):
            calls.append(wid)
            return state, [object()] * counts[min(len(calls), 2)]

        with patch.object(backend, "capture", side_effect=fake_capture):
            with patch("time.sleep"):
                _, controls = backend.capture_settled(timeout_s=30)
        self.assertTrue(len(calls) > 3)  # new controls kept it watching
        self.assertEqual(len(controls), 3)


class ExecuteGuardsTest(unittest.TestCase):
    def test_unknown_target_rejected_without_touching_desktop(self):
        from voice_control.platforms.linux import execute
        with patch.object(execute, "_wait_foreground", return_value=None):
            with self.assertRaises(RuntimeError):
                execute.execute("left_click", {"id": "c9999"},
                                {"activeWindow": {"wid": 1}}, [], [], "click it")


if __name__ == "__main__":
    unittest.main()
