# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Muzik ayristirma (muzik.py): secim dogrulamasi ve sentetik seslerle parca ayrimi.
Ses aygitina dokunmaz; analiz dogrudan ornek dizileriyle beslenir."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import muzik  # noqa: E402

np = muzik.np
SR = 48000


def signals(seconds=6.0):
    """Ayri ayri bas, davul, sola acik gitar, ortada vokal (stereo float32)."""
    t = np.arange(int(SR * seconds)) / SR
    rng = np.random.default_rng(1)

    def pulses(period, tau, off=0.0):
        return np.exp(-((t - off) % period) / tau)

    def tone(freqs, step):
        f = np.asarray(freqs)[(t // step).astype(int) % len(freqs)]
        return 2 * np.pi * np.cumsum(f) / SR

    ph = tone([55, 55, 73.4, 65.4], 0.5)
    bass = 0.5 * np.sin(ph) + 0.2 * np.sin(2 * ph)
    kick = np.sin(2 * np.pi * (50 + 80 * pulses(0.5, 0.02)) * t) * pulses(0.5, 0.08)
    snare = rng.normal(0, 1, len(t)) * pulses(1.0, 0.06, 0.5) * 0.5
    drums = kick + snare
    gtr = np.tanh(3 * np.sin(tone([196, 246.9, 293.7, 196, 220, 261.6], 0.25))) * 0.3
    f0 = 220 * (1 + 0.01 * np.sin(2 * np.pi * 5.5 * t)) * np.where((t // 1.0) % 2, 1.0, 1.26)
    vph = 2 * np.pi * np.cumsum(f0) / SR
    voc = sum(np.sin(k * vph) / k for k in range(1, 15)) * 0.15
    return {"bas": np.stack([bass, bass], 1), "davul": np.stack([drums, drums], 1),
            "gitar": np.stack([gtr, gtr * 0.15], 1), "vokal": np.stack([voc, voc], 1)}


def run(sig):
    """Sinyali 30 kare/sn motor gibi besler; ilk 2 sn (otomatik hassasiyet oturur) atlanir.
    Parca basina 90. yuzdelik seviye (vurusa tepki verenler cogu zaman sifirdir, tepeleri onemlidir)."""
    a = muzik.MusicAnalyzer(SR)
    hop = SR // 30
    acc = {p: [] for p in muzik.PARTS}
    for i in range(0, len(sig) - hop, hop):
        a.feed(sig[i:i + hop].astype(np.float32), SR)
        lv = a.frame(1 / 30, 0.4)
        if i > SR * 2:
            for p in muzik.PARTS:
                acc[p].append(lv[p])
    return {p: float(np.percentile(v, 90)) for p, v in acc.items()}


class Secim(unittest.TestCase):
    def test_clean_parts(self):
        self.assertEqual(muzik.clean_parts(None), ["tum"])
        self.assertEqual(muzik.clean_parts([]), ["tum"])
        self.assertEqual(muzik.clean_parts(["bas"]), ["bas"])
        self.assertEqual(muzik.clean_parts(["tum", "bas", "bas", "x", 3]), ["bas"])  # tum + parca: parca kalir
        self.assertEqual(muzik.clean_parts("bas"), ["tum"])
        self.assertEqual(muzik.clean_parts(["x"], ["davul"]), ["davul"])

    def test_sanitize_keeps_parts(self):
        import control_center as cc
        import klavye_rgb as core
        base = core.DEFAULTS["modes"]["ses"]
        self.assertEqual(cc._mode_values("ses", {"parts": ["davul", "riff"]}, base)["parts"], ["davul", "riff"])
        self.assertEqual(cc._mode_values("ses", {"parts": "kotu"}, base)["parts"], ["tum"])
        self.assertNotIn("parts", cc._mode_values("sabit", {"parts": ["bas"]}, core.DEFAULTS["modes"]["sabit"]))

    def test_snapshot_passes_parts(self):
        import json
        import klavye_rgb as core
        cfg = json.loads(json.dumps(core.DEFAULTS))
        cfg["mode"] = "ses"
        cfg["modes"]["ses"]["parts"] = ["vokal"]
        self.assertEqual(core.snapshot(cfg)[5], {"parts": ["vokal"]})


@unittest.skipUnless(muzik.available(), "numpy yok")
class Ayrim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {name: run(sig) for name, sig in signals().items()}

    def test_each_part_lights_its_own_signal(self):
        for name in ("bas", "davul", "gitar", "vokal"):
            lv = self.res[name]
            self.assertGreater(lv[name], 0.5, "%s kendi sinyalinde yanmali: %r" % (name, lv))

    def test_parts_stay_dark_on_other_signals(self):
        self.assertLess(self.res["bas"]["davul"], 0.2)
        self.assertLess(self.res["bas"]["vokal"], 0.2)
        self.assertLess(self.res["vokal"]["gitar"], 0.2)
        self.assertLess(self.res["vokal"]["bas"], 0.2)
        self.assertLess(self.res["davul"]["gitar"], 0.2)
        self.assertLess(self.res["davul"]["riff"], 0.2)  # kick tonu riff sayilmaz
        self.assertLess(self.res["gitar"]["davul"], 0.2)

    def test_silence_decays_to_zero(self):
        a = muzik.MusicAnalyzer(SR)
        sig = signals(2.0)["bas"].astype(np.float32)
        for i in range(0, len(sig), 1600):
            a.feed(sig[i:i + 1600], SR)
            a.frame(1 / 30, 0.4)
        for _ in range(60):
            a.feed(np.zeros((1600, 2), np.float32), SR)
            lv = a.frame(1 / 30, 0.4)
        self.assertEqual(max(lv.values()), 0.0)


if __name__ == "__main__":
    unittest.main()
