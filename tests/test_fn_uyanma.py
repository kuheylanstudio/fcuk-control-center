# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Fn+F1: uyku, hazirda bekleme ve acilistan sonra da calisir. Donanima ve touchpad'e dokunmaz."""
import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import control_center as cc  # noqa: E402
import donanim as hw  # noqa: E402
import fntus  # noqa: E402
import tepsi  # noqa: E402


class Machine:
    """Sahte saat + izni uykuda unutan denetleyici."""

    def __init__(self):
        self.now = self.slept = 0
        self.enabled = False
        self.ready_at = 0
        self.sends = []
        self.lines = []
        self.keeper = fntus.EventKeeper(self.send, self.lines.append, fntus.WakeWatch(lambda: self.slept),
                                        lambda: self.now)

    def send(self):
        self.sends.append(self.now)
        if self.now < self.ready_at:
            raise OSError("hazir degil")
        self.enabled = True

    def run(self, seconds):
        for _ in range(seconds):
            self.keeper.step()
            self.now += 1

    def sleep(self, seconds, not_ready=0):
        self.enabled = False
        self.now += seconds
        self.slept += seconds
        self.ready_at = self.now + not_ready


class KeeperTest(unittest.TestCase):
    def test_start(self):
        m = Machine()
        m.run(1)
        self.assertTrue(m.enabled)

    def test_every_sleep_length(self):
        m = Machine()
        m.run(100)
        for length in (2, 10, 3600, 12 * 3600, 5 * 86400):
            m.sleep(length)
            m.run(1)
            self.assertTrue(m.enabled, length)
            m.run(50)

    def test_sleep_during_startup_burst(self):
        m = Machine()
        m.run(2)
        m.sleep(2)
        m.run(1)
        self.assertTrue(m.enabled)

    def test_controller_late_after_wake(self):
        for late in (1, 2, 6, 14, 29, 55, 300):
            m = Machine()
            m.run(40)
            m.sleep(600, not_ready=late)
            m.run(late + 31)
            self.assertTrue(m.enabled, late)

    def test_lost_without_sleep(self):
        m = Machine()
        m.run(100)
        m.enabled = False
        m.run(31)
        self.assertTrue(m.enabled)

    def test_idle_cost(self):
        m = Machine()
        m.run(3600)
        self.assertLess(len(m.sends), 130)

    def test_failure_logged_once(self):
        m = Machine()
        m.ready_at = 500
        m.run(400)
        self.assertEqual(len(m.lines), 1)

    def test_real_clock_is_not_a_wake(self):
        self.assertFalse(fntus.WakeWatch().woke())


class ReprobeTest(unittest.TestCase):
    def test_failed_probe_is_not_cached_forever(self):
        d = hw.DCHU.__new__(hw.DCHU)
        d._support = {"ec": {"state": "no", "why": "x"}}
        d.set_data = mock.Mock(side_effect=lambda *a: d._need("ec"))
        with mock.patch("destek.clevo", return_value={"ec": {"state": "ok", "why": ""}}):
            d.enable_fn_events()
        self.assertEqual(d.set_data.call_args[0][0], 0x46)

    def test_silent_controller_gets_no_write(self):
        d = hw.DCHU.__new__(hw.DCHU)
        d._support = None
        d.dll = mock.Mock()
        with mock.patch("destek.clevo", return_value={"ec": {"state": "no", "why": "x"}}):
            self.assertRaises(hw.Unsupported, d.enable_fn_events)
        d.dll.SetDCHU_Data.assert_not_called()


class ListenerTest(unittest.TestCase):
    def test_reregisters_after_wake(self):
        li = fntus.Listener(lambda code: None)
        li.watch = fntus.WakeWatch(iter([0, 600]).__next__)
        with mock.patch.object(fntus, "bridge_path", return_value="kopru"), \
                mock.patch.object(fntus, "k32") as k, mock.patch.object(fntus, "log"):
            k.CreateFileW.return_value = 11
            k.CreateEventW.return_value = 22
            k.WaitForSingleObject.return_value = 0x102
            li._session()
        self.assertEqual(k.CloseHandle.call_count, 2)
        self.assertLess(li.wait, 1)

    def test_missing_bridge_is_retried_quickly_once_seen(self):
        li = fntus.Listener(lambda code: None)
        li._found = True
        with mock.patch.object(fntus, "bridge_path", return_value=None), mock.patch.object(fntus, "log"):
            for _ in range(8):
                li._session()
        self.assertEqual(li.wait, 1)


class ToggleTest(unittest.TestCase):
    def setUp(self):
        self.on = True
        for p in (mock.patch.object(fntus, "touchpad_enabled", lambda: self.on),
                  mock.patch.object(fntus, "log"), mock.patch.object(fntus.time, "sleep")):
            p.start()
            self.addCleanup(p.stop)

    def flip(self):
        self.on = not self.on

    def test_engine_path_presses_once(self):
        backup = mock.Mock()
        self.assertIs(fntus.toggle_touchpad([self.flip, backup]), False)
        backup.assert_not_called()

    def test_engine_down(self):
        self.assertIs(fntus.toggle_touchpad([mock.Mock(side_effect=OSError), self.flip]), False)

    def test_ignored_press(self):
        self.assertIs(fntus.toggle_touchpad([lambda: None, self.flip]), False)

    def test_timeout_after_press_does_not_double(self):
        def pressed_then_timeout():
            self.flip()
            raise TimeoutError

        backup = mock.Mock(side_effect=self.flip)
        self.assertIs(fntus.toggle_touchpad([pressed_then_timeout, backup]), False)
        backup.assert_not_called()

    def test_unknown_state_presses_once(self):
        self.on = None
        a, b = mock.Mock(), mock.Mock()
        fntus.toggle_touchpad([a, b])
        self.assertEqual((a.call_count, b.call_count), (1, 0))

    def test_all_fail(self):
        self.assertIs(fntus.toggle_touchpad([lambda: None, lambda: None]), True)

    def test_every_code_and_state_flips(self):
        t = tepsi.Tray.__new__(tepsi.Tray)
        t.tp_lock = threading.Lock()
        t.api = mock.Mock()
        t.api.post.side_effect = lambda *a, **k: self.flip() or {"ok": True}
        t._show_touchpad = mock.Mock()
        with mock.patch.object(tepsi.threading, "Thread", lambda target, daemon: mock.Mock(start=target)):
            for code in (fntus.FN_TOUCHPAD_OFF, fntus.FN_TOUCHPAD_ON):
                for start in (True, False):
                    self.on = start
                    t._on_fn(code)
                    self.assertIs(self.on, not start, (code, start))


class TrayPollTest(unittest.TestCase):
    """Gercek soketlerle: gec yanit veren motor tepsiyi kapatmaz, kapali motor kapatir."""

    def poll(self, port, rounds):
        t = tepsi.Tray.__new__(tepsi.Tray)
        t.api = tepsi.Api("http://127.0.0.1:%d" % port)
        real_get = t.api.get
        t.api.get = lambda path: real_get(path, timeout=0.2)
        t.running, t.seen_engine, t.down_since, t.hwnd = True, True, None, None
        left = [rounds]

        def tick(_):
            left[0] -= 1
            t.running = left[0] > 0

        with mock.patch.object(tepsi, "u32") as u, mock.patch.object(tepsi.time, "sleep", tick), \
                mock.patch.object(fntus, "awake_seconds", iter(range(0, 1000, 10)).__next__), \
                mock.patch.object(fntus, "log"):
            t.poll()
        return any(c[0][1] == tepsi.WM_CLOSE_TRAY for c in u.PostMessageW.call_args_list)

    def test_slow_engine_keeps_tray(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(50)  # baglantiyi kabul eder, hic yanit vermez
            self.assertFalse(self.poll(s.getsockname()[1], 4))

    def test_stopped_engine_closes_tray(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.assertTrue(self.poll(port, 4))


class EndpointTest(unittest.TestCase):
    def test_touchpad_endpoint(self):
        srv = cc.Server(("127.0.0.1", 0), cc.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(cc.Handler, "_allowed", return_value=True), \
                mock.patch.object(cc.App, "manager", None, create=True), \
                mock.patch.object(cc.fntus, "press_touchpad_hotkey") as press:
            req = urllib.request.Request("http://127.0.0.1:%d/api/touchpad" % srv.server_address[1], b"{}",
                                         {"Content-Type": "application/json"})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as r:
                self.assertEqual(json.load(r), {"ok": True})
        press.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
