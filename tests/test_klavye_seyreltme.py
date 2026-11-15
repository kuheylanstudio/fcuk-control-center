# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Klavye yazma seyreltmesi: motor 30 FPS hesaplar ama klavyeye yalnizca gozun ayirt edecegi degisimi yazar.
Donanima dokunmaz; sahte klavyeyle calisir."""
import colorsys
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import klavye_rgb as k  # noqa: E402


def rainbow_writes(seconds, speed, fullscreen=False):
    """Gokkusagi modunu motorun formuluyle 30 FPS'te calistirir; (yazma sayisi, en buyuk sapma) dondurur.
    Sapma: klavyedeki renk ile o anki gercek renk arasindaki en buyuk kanal farki."""
    dt, phase = 1.0 / 30, 0.0
    sent, sent_at, writes, worst = None, -99.0, 0, 0
    for i in range(int(seconds * 30)):
        now = i * dt
        phase += dt / k.rainbow_period(speed)
        r, g, b = colorsys.hsv_to_rgb(phase % 1.0, 1.0, 1.0)
        key = (int(r * 255 + .5), int(g * 255 + .5), int(b * 255 + .5))
        if k.should_send(key, sent, now - sent_at, fullscreen, False, False, 1.0 / k.RAINBOW_FPS):
            sent, sent_at, writes = key, now, writes + 1
        worst = max(worst, k.color_delta(key, sent))
    return writes, worst


class DeltaTest(unittest.TestCase):
    def test_single_and_zones(self):
        self.assertEqual(k.color_delta((10, 20, 30), (10, 25, 29)), 5)
        self.assertEqual(k.color_delta(((0, 0, 0), (9, 0, 0)), ((0, 0, 0), (0, 0, 0))), 9)

    def test_shape_change_forces_write(self):
        # Sabit -> Bolgeler gecisinde bicim degisir: fark 255 sayilir, renk hemen yazilir
        self.assertEqual(k.color_delta((1, 2, 3), ((1, 2, 3),)), 255)
        self.assertEqual(k.color_delta(None, (1, 2, 3)), 255)


class ShouldSendTest(unittest.TestCase):
    def test_first_frame_and_resend(self):
        self.assertTrue(k.should_send((1, 1, 1), None, 0))
        self.assertTrue(k.should_send((1, 1, 1), (1, 1, 1), k.RESEND))  # uyku / Fn sonrasi geri getirme
        self.assertFalse(k.should_send((1, 1, 1), (1, 1, 1), k.RESEND - .01))

    def test_small_change_waits_big_change_goes(self):
        self.assertFalse(k.should_send((0, 0, 3), (0, 0, 0), 0.03))
        self.assertTrue(k.should_send((0, 0, 3), (0, 0, 0), k.SLOW_GAP))
        self.assertTrue(k.should_send((0, 0, k.STEP), (0, 0, 0), 0.03))  # nabiz / nefes gecikmez

    def test_fullscreen_only_slows_non_reactive(self):
        self.assertFalse(k.should_send((0, 0, 10), (0, 0, 0), 0.2, fullscreen=True))
        self.assertTrue(k.should_send((0, 0, 10), (0, 0, 0), 0.2, fullscreen=True, reactive=True))

    def test_static_change_is_instant(self):
        # Sabit renkte renk seciciyle yapilan kucuk degisim beklemeden yazilir
        self.assertTrue(k.should_send((0, 0, 1), (0, 0, 0), 0.0, instant=True))


class RainbowBudgetTest(unittest.TestCase):
    """Olculen sorun: 30 FPS'te her kare yazilinca 3 bolgeli Clevo klavyede saniyede 90 kitaplik cagrisi."""

    def test_default_speed_writes_far_less_and_stays_accurate(self):
        writes, worst = rainbow_writes(24, 17)  # hiz 17: bir tur ~24 sn (kullanicinin ayari)
        self.assertLess(writes / 24.0, 10)       # eskiden saniyede 30 yazma
        self.assertLess(worst, k.STEP + 6)       # klavyedeki renk gercek renkten en fazla birkac birim geride

    def test_max_speed_stays_in_budget_and_smooth(self):
        # %100 hiz guvenli ust sinirdir: yazma butcesini asmaz, yine de akici kalir
        writes, worst = rainbow_writes(24, 100)
        self.assertLessEqual(writes / 24.0, k.RAINBOW_FPS + 0.1)
        self.assertGreater(writes / 24.0, k.RAINBOW_FPS - 1)
        self.assertLessEqual(worst, 24)  # klavyedeki renk en fazla ~%9 geride

    def test_budget_does_not_delay_other_modes(self):
        # Nabiz / nefes gibi hizli efektler min_gap almaz: buyuk degisim hemen gider
        self.assertTrue(k.should_send((0, 0, k.STEP), (0, 0, 0), 0.03))
        self.assertFalse(k.should_send((0, 0, 50), (0, 0, 0), 0.03, min_gap=1.0 / k.RAINBOW_FPS))

    def test_fullscreen_game_writes_rarely(self):
        writes, _ = rainbow_writes(24, 17, fullscreen=True)
        self.assertLess(writes / 24.0, 5)


class FakeKb:
    available = True

    def __init__(self):
        self.calls = []

    def set_color(self, r, g, b):
        self.calls.append((time.monotonic(), (r, g, b)))


class EngineTest(unittest.TestCase):
    def run_engine(self, settings, seconds):
        kb = FakeKb()
        eng = k.Engine(kb)
        eng.settings = settings
        eng.start()
        time.sleep(seconds)
        return eng, kb

    def stop(self, eng):
        eng.running = False
        eng._wake.set()
        eng.join(2)

    def test_static_mode_idles_and_wakes_on_change(self):
        eng, kb = self.run_engine(("sabit", ((255, 0, 0),), 50, "cpu_temp", 1.0), 0.3)
        try:
            self.assertEqual([c for _, c in kb.calls], [(255, 0, 0)])  # tek yazma, sonra uyur
            t0 = time.monotonic()
            eng.settings = ("sabit", ((0, 0, 255),), 50, "cpu_temp", 1.0)
            deadline = t0 + 1.0
            while time.monotonic() < deadline and kb.calls[-1][1] != (0, 0, 255):
                time.sleep(0.01)
            self.assertEqual(kb.calls[-1][1], (0, 0, 255))
            self.assertLess(kb.calls[-1][0] - t0, 0.2)  # uyuyan dongu ayarla hemen uyanir
        finally:
            self.stop(eng)

    def test_rainbow_write_rate(self):
        eng, kb = self.run_engine(("gokkusagi", (), 17, "cpu_temp", 1.0), 2.0)
        self.stop(eng)
        self.assertLess(len(kb.calls), 2.0 * 12)  # eskiden ~60 yazma


if __name__ == "__main__":
    unittest.main()
