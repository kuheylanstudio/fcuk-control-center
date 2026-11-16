# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""LoL skin renk temasi: oyunda Q/W/E/R parlamalari secilen sampiyonun ve skinin renklerini alir.

Akis (hepsi ayri, dusuk oncelikli bir is parcaciginda; klavye motoru ve oyun hic beklemez):
  1. Hangi sampiyon/skin?  Sampiyon seciminde LoL istemcisinin yerel API'si (LCU, lockfile ile;
     /lol-champ-select/v1/session -> championId, selectedSkinId; kroma secimi dahil). Oyunda Riot'un Live
     Client Data API'si (playerlist -> rawChampionName, skinID) yedek yoldur. Ikisi de 127.0.0.1'dedir.
  2. Skin gorseli ve sampiyon verisi: once yine LCU'nun kendi yerel varliklarindan (/lol-game-data/assets),
     istemci kapaliysa CommunityDragon'dan (ayni yol duzeni) bir kez indirilir.
  3. Renk: kare skin gorseli (tile) 48x48'e kucultulur, merkeze, doygunluga ve parlakliga agirlik verilir; koyu ve
     soluk pikseller elenir, renk tonu histograminin en guclu tepeleri Q/W/E'ye, ana tonun parlak hali R'ye verilir. Kromalarin
     Riot'un verdigi hazir renkleri varsa ana renk odur.
  4. Sonuc skin kimligine gore diske yazilir (lol_tema.json): ayni skin bir daha ne indirilir ne hesaplanir.

Ping/FPS: oyun sirasinda yapilan tek is, mac basina bir kez yerel playerlist okumasidir; skin daha once gorulmemis
ve istemci de kapaliysa bir kerelik kucuk bir indirme. Oyun bellegi okunmaz, ekran yakalanmaz, enjeksiyon yoktur.
"""
import base64
import colorsys
import http.client
import io
import json
import math
import os
import re
import ssl
import threading
import time
import urllib.request

CDRAGON = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/"
ASSETS = "/lol-game-data/assets/"
SAFE_PATH = re.compile(r"/lol-game-data/assets/[A-Za-z0-9_./-]+")
MAX_BYTES = 6 << 20
CACHE_VERSION = 1
SELECT_KEEP = 1800.0  # sampiyon secimindeki kayit (kroma dahil) bu kadar sn oyundaki kaba kayittan once gelir
LOCK_DIRS = [r"C:\Riot Games\League of Legends"]
RIOT_INSTALLS = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Riot Games",
                             "RiotClientInstalls.json")


# ----------------------------------------------------------------------------- renk
def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(x)))) for x in c)


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hsv(c):
    return colorsys.rgb_to_hsv(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)


def hue_dist(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def led(h, s):
    """Ekran rengini klavye LED'ine uyarlar: tam parlaklik, doygunluk yukari (LED'de soluk renkler beyaza kacar)."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.7, s * 1.35)), 1.0)
    return (r * 255, g * 255, b * 255)


def hue_peaks(pixels, bins=36, keep=4):
    """Renk tonu histogrami: [((r,g,b), pay)] en guclu tonlar, guce gore azalan.

    Her piksel doygunlugu ve parlakligiyla agirliklanir: gri/siyah agirlikli bir skinin kucuk ama canli vurgu
    rengi (ornegin koyu kostumdeki kirmizi) gri yigininda kaybolmaz. Hic renkli piksel yoksa []."""
    acc = [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(bins)]  # agirlik, cos, sin, doygunluk, parlaklik
    total = 0.0
    for (r, g, b), cw in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        total += cw
        if s < 0.2 or v < 0.15:
            continue
        w = cw * s * min(1.0, v * 1.6)
        a = acc[int(h * bins) % bins]
        a[0] += w
        a[1] += w * math.cos(2 * math.pi * h)
        a[2] += w * math.sin(2 * math.pi * h)
        a[3] += w * s
        a[4] += w * v
    if total <= 0:
        return []
    smooth = [acc[i - 1][0] * 0.5 + acc[i][0] + acc[(i + 1) % bins][0] * 0.5 for i in range(bins)]
    if max(smooth) < total * 0.008:  # renkli kisim yok denecek kadar az: gri skin (paletteki renkler kalir)
        return []
    out, used = [], set()
    for i in sorted(range(bins), key=lambda j: -smooth[j]):
        if len(out) == keep or smooth[i] < max(smooth) * 0.08:
            break
        if i in used:
            continue
        near = [(i + d) % bins for d in (-1, 0, 1)]
        used.update((i + d) % bins for d in (-2, -1, 0, 1, 2))
        w = sum(acc[j][0] for j in near)
        if w <= 0:
            continue
        h = (math.atan2(sum(acc[j][2] for j in near), sum(acc[j][1] for j in near)) / (2 * math.pi)) % 1.0
        sat = sum(acc[j][3] for j in near) / w
        val = sum(acc[j][4] for j in near) / w
        r, g, b = colorsys.hsv_to_rgb(h, sat, val)
        out.append(((r * 255, g * 255, b * 255), smooth[i] / total))
    return out


def image_pixels(data, size=48):
    """Gorsel baytlari -> merkeze agirlikli piksel listesi. Pillow yoksa ya da gorsel bozuksa []."""
    try:
        from PIL import Image
    except ImportError:
        return []
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > 40_000_000:
            return []
        img.draft("RGB", (size * 2, size * 2))  # JPEG'i kucuk boyutta coz: hizli
        img = img.convert("RGB").resize((size, size))
    except Exception:
        return []
    out = []
    c = (size - 1) / 2.0
    raw = img.tobytes()
    for i in range(size * size):
        p = (raw[3 * i], raw[3 * i + 1], raw[3 * i + 2])
        if max(p) < 38:  # nerdeyse siyah: arka plan / golge
            continue
        x, y = i % size, i // size
        d2 = ((x - c) ** 2 + (y - c) ** 2) / (c * c)
        out.append((p, 0.25 + 0.75 * max(0.0, 1.0 - d2)))  # sampiyon cogunlukla ortada: kenarlar az sayilir
    return out


def build_theme(groups, prefer=()):
    """Kumelerden Q/W/E/R renkleri. prefer: once kullanilacak hazir renkler (kroma, hex). Renk yoksa None."""
    cands = []
    for hx in prefer:
        try:
            h, s, v = _hsv(_rgb(hx))
        except (ValueError, TypeError):
            continue
        if s >= 0.15 and v >= 0.15:
            cands.append((h, s, v, 10.0 - len(cands)))  # hazir renk her kumenin onunde, verilen sirayla
    for col, w in groups:
        h, s, v = _hsv(col)
        if v < 0.2:
            continue
        if s < 0.3:  # gri-mavi gibi soluk tonlar: LED'de doygunlastirilinca skinde olmayan canli bir renge donerdi
            continue
        score = w * (s ** 0.8) * (v ** 0.5)
        if score > 0.0008:
            cands.append((h, s, v, score))
    cands.sort(key=lambda c: -c[3])
    picks = []
    for c in cands:
        if all(hue_dist(c[0], p[0]) >= 0.07 for p in picks):
            picks.append(c)
        if len(picks) == 3:
            break
    if not picks:
        return None
    h1, s1 = picks[0][0], picks[0][1]
    q = led(h1, s1)
    w = led(picks[1][0], picks[1][1]) if len(picks) > 1 else led(h1 + 0.05, s1)
    e = led(picks[2][0], picks[2][1]) if len(picks) > 2 else led(h1 - 0.05, s1)
    r = tuple(x + (255 - x) * 0.4 for x in q)  # ulti: ana rengin parlak, beyaza yakin hali
    return {"q": _hex(q), "w": _hex(w), "e": _hex(e), "r": _hex(r)}


# ----------------------------------------------------------------------------- yerel istemci (LCU)
def lock_dirs():
    """LoL kurulum klasoru adaylari: Riot istemcisinin kayitli kurulumlari + varsayilan yol."""
    dirs = []
    try:
        with open(RIOT_INSTALLS, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in (data.get("associated_client") or {}):
            if isinstance(k, str) and "league" in k.lower():
                dirs.append(os.path.normpath(k))
    except (OSError, ValueError, AttributeError):
        pass
    for d in LOCK_DIRS:
        if d.lower() not in [x.lower() for x in dirs]:
            dirs.append(d)
    return dirs


def read_lockfile(text):
    """'LeagueClient:pid:port:sifre:https' -> (port, sifre) ya da None."""
    parts = (text or "").strip().split(":")
    if len(parts) < 5:
        return None
    try:
        port = int(parts[2])
    except ValueError:
        return None
    return (port, parts[3]) if 0 < port < 65536 and parts[3] else None


class Lcu:
    """LoL istemcisinin yerel API'si. Yalnizca GET; adres 127.0.0.1, sertifika Riot'un kendi imzali sertifikasi."""

    def __init__(self, dirs=None):
        self.dirs = dirs
        self.auth = None
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def find(self):
        self.auth = None
        for d in (self.dirs if self.dirs is not None else lock_dirs()):
            try:
                with open(os.path.join(d, "lockfile"), "r", encoding="utf-8") as f:
                    self.auth = read_lockfile(f.read(200))
            except OSError:
                continue
            if self.auth:
                return True
        return False

    def get(self, path, raw=False):
        if not self.auth:
            raise OSError("LCU yok")
        port, pw = self.auth
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=3, context=self._ctx)
        try:
            tok = base64.b64encode(("riot:" + pw).encode()).decode()
            conn.request("GET", path, headers={"Authorization": "Basic " + tok, "Accept": "application/json"})
            r = conn.getresponse()
            body = r.read(MAX_BYTES + 1)
        finally:
            conn.close()
        if r.status != 200:
            raise OSError("HTTP %d" % r.status)
        if len(body) > MAX_BYTES:
            raise OSError("cok buyuk")
        return body if raw else json.loads(body.decode("utf-8", "replace"))


def safe_path(path):
    return isinstance(path, str) and bool(SAFE_PATH.fullmatch(path)) and ".." not in path


def cdragon_url(path):
    """/lol-game-data/assets/... -> CommunityDragon'daki ayni dosya (kucuk harf)."""
    if not safe_path(path):
        raise ValueError("gecersiz yol")
    return CDRAGON + path[len(ASSETS):].lower()


def cdragon_get(path, raw=False):
    req = urllib.request.Request(cdragon_url(path), headers={"User-Agent": "FCUKControlCenter"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise OSError("cok buyuk")
    return body if raw else json.loads(body.decode("utf-8", "replace"))


class Assets:
    """Oyun verisi: once yerel istemci, olmazsa CommunityDragon."""

    def __init__(self, lcu, remote=cdragon_get):
        self.lcu = lcu
        self.remote = remote

    def get(self, path, raw=False):
        if not safe_path(path):
            raise ValueError("gecersiz yol")
        if self.lcu is not None and self.lcu.auth:
            try:
                return self.lcu.get(path, raw)
            except Exception:
                pass
        return self.remote(path, raw)


# ----------------------------------------------------------------------------- secim -> tema
def find_skin(champ, skin_id):
    """Sampiyon verisinde skin/kroma/kademe kaydi: (skin kaydi, kroma renkleri, gosterilecek ad)."""
    skins = [s for s in (champ.get("skins") or []) if isinstance(s, dict)]
    for s in skins:
        if s.get("id") == skin_id:
            return s, [], s.get("name") or ""
        for ch in s.get("chromas") or []:
            if isinstance(ch, dict) and ch.get("id") == skin_id:
                cols = [c for c in (ch.get("colors") or []) if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c)]
                return s, cols, ch.get("name") or s.get("name") or ""
        for tier in ((s.get("questSkinInfo") or {}).get("tiers") or []):
            if isinstance(tier, dict) and tier.get("id") == skin_id:
                paths = {k: v for k, v in tier.items() if k.endswith("Path") and v}
                return dict(s, **paths), [], tier.get("name") or s.get("name") or ""
    base = skins[0] if skins else None
    return base, [], (base or {}).get("name") or champ.get("name") or ""


def make_theme(assets, champ_id, skin_id):
    """Sampiyon + skin kimliginden tema. Veri alinamazsa istisna; renk cikmazsa colors None."""
    champ = assets.get("%sv1/champions/%d.json" % (ASSETS, champ_id))
    if not isinstance(champ, dict):
        raise ValueError("sampiyon verisi yok")
    skin, chroma, name = find_skin(champ, skin_id)
    groups = []
    skin = skin or {}
    path = skin.get("tilePath") or skin.get("loadScreenPath") or skin.get("splashPath")
    if safe_path(path):
        groups = hue_peaks(image_pixels(assets.get(path, raw=True)))
    return {"name": name, "champion": champ.get("name") or "", "colors": build_theme(groups, chroma)}


def alias_of(raw_name):
    """Live API rawChampionName ('game_character_displayname_MissFortune') -> 'MissFortune'."""
    raw_name = raw_name or ""
    return raw_name.rsplit("_", 1)[-1] if raw_name.startswith("game_character_displayname_") else raw_name


def champ_select_pick(session):
    """LCU champ-select oturumundan kendi secimin: (championId, skinId) ya da None."""
    if not isinstance(session, dict):
        return None
    me = session.get("localPlayerCellId")
    for p in session.get("myTeam") or []:
        if isinstance(p, dict) and p.get("cellId") == me:
            cid, sid = p.get("championId"), p.get("selectedSkinId")
            if isinstance(cid, int) and cid > 0:
                return cid, sid if isinstance(sid, int) and sid > 0 else cid * 1000
    return None


class ThemeWatcher(threading.Thread):
    """Secilen sampiyon/skini izler ve temayi hazir tutar. theme: {"name", "champion", "colors": {q,w,e,r}} ya da None.

    live: oyun ici kaynak (oyun.LolClient); .connected ve .champ ((rawChampionName, skinID)) okunur."""

    def __init__(self, live, cache_dir, lcu=None, assets=None, on_start=None):
        super().__init__(daemon=True)
        self.live = live
        self.cache_path = os.path.join(cache_dir, "lol_tema.json")
        self.lcu = lcu if lcu is not None else Lcu()
        self.assets = assets if assets is not None else Assets(self.lcu)
        self.on_start = on_start
        self.wanted = False
        self.running = True
        self.theme = None
        self.pick = None          # (championId, skinId) son belirlenen secim
        self.select = None        # sampiyon secimindeki son kayit
        self.select_at = -1e9
        self._cache = None
        self._failed = {}         # skin kimligi -> son basarisiz deneme zamani

    # --- onbellek
    def _load(self):
        if self._cache is None:
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if (isinstance(data, dict) and data.get("v") == CACHE_VERSION and isinstance(data.get("skins"), dict)
                        and isinstance(data.get("ids"), dict)):
                    self._cache = data
            except (OSError, ValueError):
                pass
            if self._cache is None:
                self._cache = {"v": CACHE_VERSION, "skins": {}, "ids": {}}
        return self._cache

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    # --- cozumleme
    def resolve(self, champ_id, skin_id):
        """Temayi onbellekten ya da hesaplayarak ayarlar. Basarisizsa 60 sn sonra yeniden denenir."""
        if self.pick != (champ_id, skin_id):
            self.theme = None  # baska sampiyonun renkleri kalmasin
        self.pick = (champ_id, skin_id)
        cache = self._load()["skins"]
        key = str(skin_id)
        item = cache.get(key)
        if isinstance(item, dict):
            self.theme = item if isinstance(item.get("colors"), dict) else None
            return
        if time.monotonic() - self._failed.get(key, -1e9) < 60:
            return
        try:
            th = make_theme(self.assets, champ_id, skin_id)
        except Exception:
            self._failed[key] = time.monotonic()
            return
        cache[key] = th
        self._save()
        self.theme = th if th.get("colors") else None

    def champion_id(self, alias):
        ids = self._load()["ids"]
        if alias not in ids:
            summary = self.assets.get(ASSETS + "v1/champion-summary.json")
            for c in summary if isinstance(summary, list) else []:
                if isinstance(c, dict) and isinstance(c.get("alias"), str) and isinstance(c.get("id"), int):
                    ids[c["alias"]] = c["id"]
            self._save()
        return ids.get(alias)

    def step(self, now=None):
        """Bir yoklama adimi; bir sonraki adima kadar beklenecek sure (sn)."""
        now = time.monotonic() if now is None else now
        live = self.live
        if live is not None and live.connected:
            champ = getattr(live, "champ", None)
            if not champ:
                return 2.0
            try:
                cid = self.champion_id(alias_of(champ[0]))
            except Exception:
                return 15.0
            if cid is None:
                return 15.0
            if self.select and self.select[0] == cid and now - self.select_at < SELECT_KEEP:
                self.resolve(*self.select)  # secimdeki kayit (kroma dahil) daha ayrintili
            else:
                self.resolve(cid, cid * 1000 + champ[1])
            return 5.0
        if not self.lcu.auth and not self.lcu.find():
            return 10.0
        try:
            pick = champ_select_pick(self.lcu.get("/lol-champ-select/v1/session"))
        except Exception:  # sampiyon seciminde degil (404) ya da istemci kapandi
            return 3.0 if self.lcu.find() else 10.0
        if pick:
            self.select, self.select_at = pick, now
            self.resolve(*pick)
        return 2.0

    def run(self):
        if self.on_start:
            self.on_start()
        while self.running:
            if not self.wanted:
                time.sleep(1.0)
                continue
            try:
                wait = self.step()
            except Exception:
                wait = 10.0
            end = time.monotonic() + wait
            while self.running and self.wanted and time.monotonic() < end:
                time.sleep(0.5)
