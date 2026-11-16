# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Muzik ayristirma: hoparlore giden sesten bas, davul, gitar, vokal, melodi ve riff seviyeleri (0..1).

Ses, Windows'un varsayilan hoparlor cikisindan WASAPI loopback ile alinir (ses kartina dokunulmaz, yalnizca
okunur). Her karede son ~43 ms'lik pencerenin spektrumu (FFT) cikarilir ve parcalar uc ipucuyla tahmin edilir:

* Harmonik / perkusif ayrimi (HPSS): zamanda kalici frekanslar notadir (harmonik), frekansta genis ama kisa
  patlamalar vurmali calgidir (perkusif). Davul perkusif kisimdan, digerleri harmonik kisimdan olculur.
* Stereo orta / yan: vokal neredeyse her miksajda ortadadir; gitarlar cogunlukla sola-saga acilir.
* Frekans bantlari: bas 35-200 Hz, vokal 250-4000 Hz, gitar 150-6000 Hz ...

Bu gercek bir kaynak ayirma (yapay zeka ile "stem" ayirma) degildir; gercek zamanli ve hafif bir tahmindir.
Ayrimin kalitesi sarkinin miksajina gore degisir. numpy gerekir; yoksa available() False doner.
"""
import ctypes
import time

c_void_p = ctypes.c_void_p
c_int = ctypes.c_int
c_uint32 = ctypes.c_uint32

try:
    import numpy as np
except ImportError:  # paket eksikse muzik ayristirma kapali kalir, genel ses seviyesi calisir
    np = None

# Arayuz sirasi. "tum" eski davranis: yalnizca toplam ses seviyesi (ek islem yok)
PARTS = ("bas", "davul", "gitar", "vokal", "melodi", "riff")
ALL = "tum"
PART_IDS = (ALL,) + PARTS
ONSET = ("davul", "riff")  # vuruslara (atak) tepki verenler; digerleri enerjiye


def available():
    return np is not None


def clean_parts(v, default=(ALL,)):
    """Kayitli secimi dogrular: bilinen, tekrarsiz kimlikler; "tum" digerleriyle birlikte secilmez."""
    if not isinstance(v, list):
        return list(default)
    out = []
    for p in v:
        if p in PART_IDS and p not in out:
            out.append(p)
    if len(out) > 1 and ALL in out:
        out.remove(ALL)
    return out or list(default)


# ----------------------------------------------------------------------------- WASAPI loopback (COM, ctypes)
class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


def _vcall(ptr, index, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtbl[index])


def _release(p):
    if p:
        _vcall(p, 2)(p)


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16), ("nSamplesPerSec", c_uint32),
                ("nAvgBytesPerSec", c_uint32), ("nBlockAlign", ctypes.c_uint16), ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16), ("wValidBits", ctypes.c_uint16), ("dwChannelMask", c_uint32),
                ("sub", c_uint32)]  # SubFormat GUID'in ilk 4 bayti: 1 PCM, 3 IEEE float


CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_CLIENT = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"
IID_CAPTURE = "{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"
LOOPBACK = 0x00020000      # AUDCLNT_STREAMFLAGS_LOOPBACK
SILENT = 0x2               # AUDCLNT_BUFFERFLAGS_SILENT
BUFFER_EMPTY = 0x08890001  # AUDCLNT_S_BUFFER_EMPTY


class Loopback:
    """Varsayilan hoparlor cikisinin ornekleri (stereo float32). Kullanildigi is parcaciginda olusturulmali."""

    def __init__(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        self._free = ctypes.WINFUNCTYPE(None, c_void_p)(("CoTaskMemFree", ole32))  # ortak imzalar degismesin
        self.enum = self.client = self.capture = None
        self.dev_id = None
        self.rate = 48000
        self.channels = 2
        self.kind = "f32"
        self.block = 8
        self.checked = 0.0
        self.opened = -10.0

    def _default_device(self):
        """(IMMDevice, kimlik metni) ya da (None, None). Donen aygit cagiranca birakilir."""
        dev = c_void_p()
        if _vcall(self.enum, 4, c_int, c_int, c_void_p)(self.enum, 0, 1, ctypes.byref(dev)) != 0:
            return None, None
        p = c_void_p()
        ident = None
        if _vcall(dev, 5, c_void_p)(dev, ctypes.byref(p)) == 0 and p.value:  # IMMDevice::GetId
            ident = ctypes.wstring_at(p.value)
            self._free(p)
        return dev, ident

    def close(self):
        if self.client:
            try:
                _vcall(self.client, 11)(self.client)  # IAudioClient::Stop
            except OSError:
                pass
        _release(self.capture)
        _release(self.client)
        self.capture = self.client = None
        self.dev_id = None

    def shutdown(self):
        self.close()
        _release(self.enum)
        self.enum = None

    def _open(self):
        self.close()
        ole32 = ctypes.windll.ole32
        if self.enum is None:
            enum = c_void_p()
            create = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, ctypes.c_ulong, c_void_p, c_void_p)(
                ("CoCreateInstance", ole32))
            if create(ctypes.byref(_guid(CLSID_ENUM)), None, 23, ctypes.byref(_guid(IID_ENUM)),
                      ctypes.byref(enum)) != 0:
                return
            self.enum = enum
        dev, ident = self._default_device()
        if not dev:
            return
        client = c_void_p()
        try:
            if _vcall(dev, 3, c_void_p, ctypes.c_ulong, c_void_p, c_void_p)(
                    dev, ctypes.byref(_guid(IID_CLIENT)), 23, None, ctypes.byref(client)) != 0:
                return
        finally:
            _release(dev)
        fmt = c_void_p()
        if _vcall(client, 8, c_void_p)(client, ctypes.byref(fmt)) != 0:  # GetMixFormat
            _release(client)
            return
        try:
            wf = ctypes.cast(fmt, ctypes.POINTER(WAVEFORMATEX)).contents
            tag, bits = wf.wFormatTag, wf.wBitsPerSample
            if tag == 0xFFFE and wf.cbSize >= 22:  # WAVE_FORMAT_EXTENSIBLE
                tag = wf.sub
            kind = {(3, 32): "f32", (1, 16): "i16", (1, 32): "i32"}.get((tag, bits))
            hr = -1
            if kind:
                self.kind = kind
                self.rate, self.channels, self.block = wf.nSamplesPerSec, max(1, wf.nChannels), wf.nBlockAlign
                # 200 ms tampon: motor 30 kare/sn okur, araya giren takilmada ornek kaybolmaz
                hr = _vcall(client, 3, c_int, ctypes.c_ulong, ctypes.c_longlong, ctypes.c_longlong, c_void_p,
                            c_void_p)(client, 0, LOOPBACK, 2000000, 0, fmt, None)
        finally:
            self._free(fmt)
        if hr != 0:
            _release(client)
            return
        capture = c_void_p()
        if _vcall(client, 14, c_void_p, c_void_p)(client, ctypes.byref(_guid(IID_CAPTURE)),
                                                  ctypes.byref(capture)) != 0:
            _release(client)
            return
        if _vcall(client, 10)(client) != 0:  # Start
            _release(capture)
            _release(client)
            return
        self.client, self.capture, self.dev_id = client, capture, ident

    def read(self):
        """Son okumadan beri gelen ornekler: (n, 2) float32 dizi (bos olabilir) ya da None (aygit yok)."""
        now = time.monotonic()
        if self.capture is None:
            if now - self.opened < 2.0:
                return None
            self.opened = now
            self._open()
            if self.capture is None:
                return None
        elif now - self.checked > 3.0:  # varsayilan cikis degistiyse (kulaklik takildi) yeniden ac
            self.checked = now
            dev, ident = self._default_device()
            _release(dev)
            if ident and ident != self.dev_id:
                self._open()
                if self.capture is None:
                    return None
        chunks = []
        cap = self.capture
        get = _vcall(cap, 3, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
        rel = _vcall(cap, 4, c_uint32)
        nxt = _vcall(cap, 5, c_void_p)
        size = c_uint32()
        for _ in range(64):
            if nxt(cap, ctypes.byref(size)) != 0:
                self.close()  # aygit kayboldu (AUDCLNT_E_DEVICE_INVALIDATED): sonra yeniden acilir
                return None
            if size.value == 0:
                break
            data, frames, flags = c_void_p(), c_uint32(), ctypes.c_ulong()
            hr = get(cap, ctypes.byref(data), ctypes.byref(frames), ctypes.byref(flags), None, None)
            if hr == BUFFER_EMPTY:
                break
            if hr != 0:
                self.close()
                return None
            n = frames.value
            if n:
                if flags.value & SILENT or not data.value:
                    chunks.append(np.zeros((n, 2), np.float32))
                else:
                    chunks.append(self._convert(ctypes.string_at(data.value, n * self.block), n))
            rel(cap, n)
        if not chunks:
            return np.zeros((0, 2), np.float32)
        return np.concatenate(chunks)

    def _convert(self, raw, n):
        if self.kind == "f32":
            a = np.frombuffer(raw, np.float32)
        elif self.kind == "i16":
            a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        else:
            a = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
        a = a.reshape(n, self.channels)
        if self.channels == 1:
            return np.repeat(a, 2, axis=1)
        return a[:, :2]  # 5.1 / 7.1: on sol ve on sag


# ----------------------------------------------------------------------------- analiz
# Parcanin, toplam sesin otomatik hassasiyetine gore en az bu kadar olmasi gerekir ki tam parlasin: yoksa sarkida
# o calgi hic yokken otomatik hassasiyet kalan izi buyutup klavyeyi yakardi (ornegin piyano sarkisinda "gitar").
REL = {"bas": 0.35, "davul": 0.30, "gitar": 0.30, "vokal": 0.30, "melodi": 0.25, "riff": 0.20}


class MusicAnalyzer:
    N = 2048            # FFT penceresi (48 kHz'de ~43 ms, 23 Hz cozunurluk: bas icin yeterli)
    HIST = 7            # harmonik tahmini icin zaman medyani (kare, ~230 ms)
    PERC_K = 15         # perkusif tahmini icin frekans medyani (kutu, ~350 Hz)
    TOP = 12000.0       # ust frekans siniri (Hz)

    def __init__(self, rate=48000):
        self.buf = np.zeros((self.N, 2), np.float32)
        self.win = np.hanning(self.N).astype(np.float32)
        self.gain = {p: 1e-3 for p in PARTS}
        self.total_gain = 1e-3
        self.level = {p: 0.0 for p in PARTS}
        self.raw = {p: 0.0 for p in PARTS}
        self._setup(rate)

    def _setup(self, rate):
        self.rate = rate
        hz = rate / float(self.N)
        self.K = min(self.N // 2 + 1, int(self.TOP / hz) + 1)
        self.hist = np.zeros((self.HIST, self.K), np.float32)
        self.hi = 0
        self.prev_p = np.zeros(self.K, np.float32)
        self.prev_h = np.zeros(self.K, np.float32)
        f = np.arange(self.K) * hz

        def band(lo, hi):
            return slice(int(np.searchsorted(f, lo)), int(np.searchsorted(f, hi)))
        self.b_total = band(30, self.TOP)
        self.b_bass = band(30, 150)
        self.b_voc = band(250, 4000)
        self.b_gtr = band(150, 6000)
        self.b_mel = band(300, 4000)
        self.b_riff = band(100, 1500)
        self.b_drum = band(40, self.TOP)
        fv = f[self.b_voc]
        # vokal: sarki formantlari (0,9-3,5 kHz) agir basar
        self.w_voc = np.where((fv > 900) & (fv < 3500), 1.6, 1.0).astype(np.float32)

    def feed(self, samples, rate):
        """Yeni ornekleri (n, 2) tampona ekler."""
        if rate and rate != self.rate:
            self._setup(rate)
            self.buf[:] = 0
        if samples is None or not len(samples):
            return
        if len(samples) >= self.N:
            self.buf = np.array(samples[-self.N:], np.float32)
        else:
            self.buf = np.concatenate((self.buf[len(samples):], samples)).astype(np.float32, copy=False)

    @staticmethod
    def _rms(x):
        return float(np.sqrt(np.mean(x * x))) if x.size else 0.0

    def analyze(self):
        """Ham parca degerleri (birimsiz) ve toplam seviye."""
        x = self.buf * self.win[:, None]
        mid = np.abs(np.fft.rfft(x[:, 0] + x[:, 1]))[:self.K] * 0.5
        side = np.abs(np.fft.rfft(x[:, 0] - x[:, 1]))[:self.K] * 0.5
        self.hist[self.hi] = mid
        self.hi = (self.hi + 1) % self.HIST
        harm = np.median(self.hist, axis=0)
        k = self.PERC_K // 2
        perc = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(mid, k, mode="edge"), self.PERC_K), axis=1)
        h2, p2 = harm * harm, perc * perc
        hc = mid * (h2 / (h2 + p2 + 1e-12))   # bu karenin harmonik kismi (nota)
        pc = mid - hc                          # perkusif kismi (vurus)
        center = np.clip(1.0 - side / (mid + 1e-9), 0.0, 1.0) ** 2  # 1: tam ortada (vokal), 0: tam yanda

        raw = {"bas": self._rms(hc[self.b_bass]),
               "vokal": self._rms((hc * center)[self.b_voc] * self.w_voc),
               "gitar": self._rms((hc * (1.0 - center))[self.b_gtr]) * 1.4}
        seg = hc[self.b_mel]
        tonal = float(np.clip((seg.max() / (seg.mean() + 1e-9) - 4.0) / 16.0, 0.0, 1.0)) if seg.size else 0.0
        raw["melodi"] = self._rms(seg) * tonal * 2.0  # tek belirgin ton (sarkinin ana cizgisi) one cikar
        # Ataklar: davul, frekansta yumusatilmis spektrumu (perc) birden yukseltir; yeni bir nota ise yalnizca
        # yerel tepeleri (mid - perc). Harmonik maske zaman medyanina dayandigi icin ataklari ~0,1 sn gec gorur,
        # bu yuzden akis (flux) maskeden degil, anlik spektrumdan olculur. Karekok: tek gurultulu frekans baskin
        # olmasin.
        sp, sh = np.sqrt(perc), np.sqrt(np.maximum(mid - perc, 0.0))
        dp = np.maximum(sp - self.prev_p, 0.0)
        dh = np.maximum(sh - self.prev_h, 0.0)[self.b_riff]
        self.prev_p, self.prev_h = sp, sh
        raw["davul"] = float(np.mean(dp[self.b_drum])) ** 2 * 6.0  # yeni vuruslar
        # yeni notalar (bas/gitar cizgisinin ataklari); ayni anda gelen davul vurusunun payi dusulur (kick tonu)
        raw["riff"] = max(0.0, float(np.mean(dh)) - 1.5 * float(np.mean(dp[self.b_riff]))) ** 2 * 8.0
        return raw, self._rms(mid[self.b_total])

    def frame(self, dt, fall):
        """Parca seviyeleri 0..1. fall: tepe noktadan sifira inis suresi (sn)."""
        if float(np.max(np.abs(self.buf[-512:]))) < 1e-4:  # sessiz (~ -80 dB): hesap yok, seviyeler soner
            for p in PARTS:
                self.level[p] = max(0.0, self.level[p] - dt / fall)
            return dict(self.level)
        raw, total = self.analyze()
        self.raw = raw
        decay = 1.0 - 0.08 * dt
        self.total_gain = max(self.total_gain * decay, total, 1e-4)
        for p in PARTS:
            v = raw[p]
            self.gain[p] = max(self.gain[p] * decay, v, REL[p] * self.total_gain, 1e-5)
            x = min(1.0, v / self.gain[p]) ** 1.4
            f = fall * (0.6 if p in ONSET else 1.0)  # vuruslar daha keskin soner
            lv = self.level[p]
            self.level[p] = x if x > lv else max(x, lv - dt / f)
        return dict(self.level)


class Music:
    """Motorun kullandigi parca: loopback + analiz. Yalnizca olusturuldugu (motor) is parcaciginda kullanilir."""

    def __init__(self):
        self.src = Loopback()
        self.ana = MusicAnalyzer()
        self.ok = False  # ses aygiti acik mi

    def levels(self, dt, fall):
        s = self.src.read()
        self.ok = s is not None
        self.ana.feed(s, self.src.rate)
        return self.ana.frame(dt, fall)

    def close(self):
        self.src.shutdown()


def selftest(seconds=5.0):
    """Hoparlorden calan sesi birkac saniye dinleyip parca seviyelerini yazar."""
    m = Music()
    t0 = last = time.monotonic()
    while time.monotonic() - t0 < seconds:
        time.sleep(1 / 30)
        now = time.monotonic()
        lv = m.levels(now - last, 0.4)
        last = now
        print("aygit=%s %s" % ("acik" if m.ok else "YOK", "  ".join("%s=%.2f" % (p, lv[p]) for p in PARTS)))
    m.close()


if __name__ == "__main__":
    selftest()
