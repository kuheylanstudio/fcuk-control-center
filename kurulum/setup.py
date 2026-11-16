# -*- coding: utf-8 -*-
# FCUK Control Center - kurulum programı (setup.exe)
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
"""setup.exe: yönetici olarak açılır (PyInstaller --uac-admin), derlenmiş uygulamayı içinde taşır.

İşin kendisini kurulum.ps1 yapar; bu dosya yalnızca pencere ve satır satır ilerleme gösterir.
  setup.exe              pencereli kurulum (önce eski Control Center taraması gösterilir)
  setup.exe /S           sessiz kurulum, çıkış kodu: 0 tamam, 2 uyarılı tamam, 1 hata
  setup.exe /S /restore  sessiz kurulum, önce sistem geri yükleme noktası oluşturur
  setup.exe /guncelle    uygulama içi güncelleme: uygulamadan bağımsız, kendi penceresinde ilerlemeyi gösterir,
                         bitince yeni sürümü açar. (Eski sürümlerin güncelleyicisi "/S /open" çağırır; o da aynı
                         pencereyi açar.)
  setup.exe /S /reboot   sessiz kurulum, başarılıysa bilgisayarı yeniden başlatır (yoksa elle yeniden başlatın)
  setup.exe /S /ccengel     (Clevo) eski Control Center'ın Windows Update / Store ile geri yüklenmesini engeller
  setup.exe /S /ccengelyok  bu engeli kaldırır (geri alır). İkisi de yoksa önceki seçim korunur.
Pencereli kurulum aynı seçimi bir kutuyla sunar (Clevo/Monster'da; varsayılan: önceki seçim, ilk kurulumda açık).
Kurulum sonrası yeniden başlatma gerekir; pencereli kurulum bunu söyler ve "Şimdi yeniden başlat" düğmesi sunar.
"""
import os
import queue
import subprocess
import sys
import threading

BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(BUNDLE, "kurulum.ps1")
PAYLOAD = os.path.join(BUNDLE, "payload")
NO_WINDOW = 0x08000000
TITLE = "FCUK Control Center"
LOG = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "FCUK Control Center", "kurulum.log")
EXE = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "FCUK Control Center", "FCUKControlCenter.exe")


def version():
    try:
        with open(os.path.join(BUNDLE, "surum.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


# kurulum.ps1'in tespit ettiği cihaz -> (görünen ad, üreticinin kendi uygulaması)
MARKA = {
    "alienware": ("Alienware / Dell G", "Alienware Command Center"),
    "asus": ("Asus ROG / TUF", "Armoury Crate"),
    "ideapad": ("Lenovo IdeaPad", "Lenovo Vantage"),
    "lenovo": ("Lenovo Legion / LOQ", "Lenovo Vantage / Legion Zone"),
    "msi": ("MSI", "MSI Center"),
    "hp": ("HP Omen / Victus", "OMEN Gaming Hub"),
    "acer": ("Acer Predator / Nitro", "PredatorSense / NitroSense"),
    "gigabyte": ("Gigabyte Aorus / Aero", "Gigabyte Control Center"),
}


def device_text(kind):
    """Clevo dışı bir cihaz için kurulum penceresindeki açıklama."""
    if kind in MARKA:
        name, app = MARKA[kind]
        return ("Bu bilgisayar %s olarak tespit edildi. Kurulum yalnızca bu cihaza ait adımları uygular: Monster/Clevo "
                "bileşenleri kurulmaz, %s dahil hiçbir üretici yazılımı, sürücüsü ya da hizmeti kaldırılmaz. İkisi "
                "birlikte çalışır; aynı ayarı (fan, güç modu, klavye ışığı) ikisi birden değiştirirse son değiştirenin "
                "ayarı geçerli olur. Bu cihazda desteklenmeyen özellikler arayüzde 'kullanılamaz' görünür ve donanıma "
                "komut gönderilmez." % (name, app))
    return ("Bu bilgisayarda desteklenen bir denetleyici arayüzü bulunamadı. Kurulum yalnızca FCUK Control Center'ı "
            "kurar; bilgisayarın kendi uygulamasına, sürücülerine ve hizmetlerine dokunmaz, hiçbir şey kaldırılmaz. "
            "Fan eğrisi, denetleyici güç modu ve klavye RGB bu bilgisayarda yoktur; arayüzde 'kullanılamaz' görünür "
            "ve donanıma komut gönderilmez.")


def run_script(mode, on_line, launch=True, restore=False, guard=None):
    """kurulum.ps1'i çalıştırır, her çıktı satırını (tür, metin) olarak on_line'a verir. Çıkış kodunu döndürür.
    guard: eski Control Center'ın geri yüklenmesini engelle (True/False); None önceki seçimi korur."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SCRIPT,
           "-Mode", mode, "-Version", version()]
    if mode == "Install":
        cmd += ["-Payload", PAYLOAD]
        if not launch:
            cmd.append("-NoLaunch")
        if restore:
            cmd.append("-RestorePoint")
        if guard is not None:
            cmd += ["-CCGuard", "On" if guard else "Off"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, cwd=BUNDLE)
    for raw in p.stdout:
        try:  # betik satırları UTF-8; PowerShell'in kendi hata metinleri Windows kod sayfasında gelebilir
            line = raw.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            line = raw.decode("mbcs", "replace").rstrip()
        if not line.strip():
            continue
        kind, sep, msg = line.partition("|")
        if sep and kind in ("ADIM", "BILGI", "OK", "UYARI", "HATA", "CIHAZ"):  # CIHAZ: tespit edilen cihaz (bkz. MARKA)
            on_line(kind, msg)
        else:
            on_line("HAM", line)
    return p.wait()


TRAY_CLASS = "KendiControlCenterTray"           # tepsi.py TRAY_CLASS ile aynı
OPEN_MESSAGE = "FCUKControlCenter.PencereyiAc"  # tepsi.py OPEN_MESSAGE ile aynı


def _ask_tray_to_open(wait=15.0):
    """Kurulumun başlattığı (normal yetkili) tepsiden pencereyi açmasını ister: tepsideki 'Aç' ile aynı yol.
    Tepsi pencereyi motor yanıt verdiğinde açar. Tepsi bulunamazsa False."""
    import ctypes
    import time
    from ctypes import wintypes as wt
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    u32.FindWindowW.restype = wt.HWND
    u32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
    u32.RegisterWindowMessageW.restype = wt.UINT
    u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.PostMessageW.restype = wt.BOOL
    msg = u32.RegisterWindowMessageW(OPEN_MESSAGE)
    if not msg:
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        hwnd = u32.FindWindowW(TRAY_CLASS, None)
        if hwnd and u32.PostMessageW(hwnd, msg, 0, 0):
            return True
        time.sleep(0.25)
    return False


def open_app():
    """Arayüzü NORMAL kullanıcı yetkisiyle açar. Kurulum yönetici olarak çalışır; pencereyi buradan açmak
    yönetici tarayıcı, yönetici ortam değişkenleri ya da henüz hazır olmayan motor yüzünden 'siteye
    ulaşılamıyor / IP adresi bulunamadı' sayfası bırakabiliyordu. Bu yüzden açmayı tepsi yapar; tepsi
    yoksa uygulama explorer aracılığıyla (yükseltilmemiş) başlatılır ve o da motoru bekleyip açar."""
    try:
        if _ask_tray_to_open():
            return
    except Exception:
        pass
    if os.path.exists(EXE):
        subprocess.Popen(["explorer.exe", EXE], creationflags=NO_WINDOW)


def silent(restore=False, reboot=False, open_after=False, guard=None):
    dev = {}
    rc = run_script("Install", lambda k, m: dev.update(clevo=(m == "clevo")) if k == "CIHAZ" else None, restore=restore,
                    guard=guard)
    if open_after and rc != 1:  # uygulama içi güncelleme: kapanan pencere yeni sürümle yeniden açılır
        open_app()
    # /reboot: başarılı kurulumdan sonra yeniden başlat. Clevo/Monster değilse sürücü/Fn değişikliği yok: gerekmez.
    if reboot and rc != 1 and dev.get("clevo", True):
        subprocess.Popen(["shutdown.exe", "/r", "/t", "10"], creationflags=NO_WINDOW)
    return rc


# ----------------------------------------------------------------------------- pencere
# Kurulum adımları (güncelleme penceresiyle aynı düzen). Her biri kurulum.ps1'in "ADIM|..." satırlarından birine
# (küçük harfle) eşlenir; adım geriye gitmez. (başlık, başlangıç yüzdesi, eşleşen ifadeler)
INSTALL_STEPS = [
    ("Hazırlanıyor", 0, ()),
    ("Eski Control Center kaldırılıyor", 12, ("kapatılıyor", "durduruluyor", "engelleniyor", "paketleri kaldırılıyor",
                                             "temizleniyor", "dosyaları ve kurulum kaydı", "sürücüleri ve donanım")),
    ("Dosyalar kopyalanıyor", 45, ("kopyalanıyor", "cihaza özel")),
    ("Ayarlar uygulanıyor", 72, ("açılış görevleri", "kısayollar", "geri yükleme engeli")),
    ("Başlatılıyor ve doğrulanıyor", 86, ("başlatılıyor ve doğrulanıyor",)),
]
GUARD_KEY = r"SOFTWARE\FCUK Control Center"   # engelle.py REG_KEY ile aynı


def guard_state():
    """Önceki kurulumdaki 'geri yükleme engeli' seçimi: True / False; hiç kurulmamışsa None."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GUARD_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return int(winreg.QueryValueEx(k, "CCKoruma")[0]) == 1
    except (OSError, ValueError, TypeError):
        return None


CLEVO_TEXT = ("Eski Monster / Clevo Control Center yedek alınarak kaldırılır, FCUK Control Center yerine kurulur. "
              "Üreticinin kaldırıcısı çalıştırılmaz (AcpiBridge sürücülerini de siler); sürücüler ve CCDCHUService "
              "korunur ve sonunda doğrulanır.")


def gui():
    import time
    import ctypes
    import tkinter as tk
    from tkinter import ttk
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass

    BG, SURFACE, SURFACE2, LINE = "#0a0c0f", "#111419", "#181c23", "#252a33"
    TEXT, TEXT2, TEXT3 = "#eceff4", "#a9b1be", "#818a99"
    GOOD, WARN, BAD, LIVE = "#5fd38d", "#ffc861", "#ff6b6b", "#7cc4ff"
    FONT = "Bahnschrift"
    PREFIX = {"ADIM": "\n▸ ", "OK": "  ✓ ", "UYARI": "  ! ", "HATA": "  ✗ ", "BILGI": "  · ", "HAM": "    "}
    COLORS = {"ADIM": "#ffffff", "BILGI": TEXT2, "OK": GOOD, "UYARI": WARN, "HATA": BAD, "HAM": TEXT3}

    old, new = installed_version(), version()
    root = tk.Tk()
    root.title("%s %s Kurulumu" % (TITLE, new))
    root.configure(bg=BG)
    s = root.winfo_fpixels("1i") / 96.0
    w = int(560 * s)
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(BUNDLE, "uygulama.ico"))
    except tk.TclError:
        pass

    pad = int(26 * s)
    wrap = w - 2 * pad
    tk.Label(root, text=TITLE, bg=BG, fg=TEXT3, font=(FONT, 10), anchor="w").pack(fill="x", padx=pad, pady=(pad - 6, 0))
    head = tk.Label(root, text="Kurulum", bg=BG, fg="#ffffff", font=(FONT, 20, "bold"), anchor="w")
    head.pack(fill="x", padx=pad)
    ver = ("Sürüm %s  →  %s" % (old, new)) if old and new and old != new else ("Sürüm %s" % new if new else "")
    def sub_text(t):
        return "%s  ·  %s" % (ver, t) if ver else t[:1].upper() + t[1:]

    sub = tk.Label(root, text=sub_text("bilgisayar taranıyor..."), bg=BG, fg=LIVE, font=(FONT, 11), anchor="w")
    sub.pack(fill="x", padx=pad)
    note = tk.Label(root, text="Bilgisayar ve eski Control Center taranıyor. Henüz hiçbir şey değiştirilmedi.",
                    bg=BG, fg=TEXT, font=(FONT, 11), justify="left", anchor="w", wraplength=wrap)
    note.pack(fill="x", padx=pad, pady=(14, 8))

    steps = tk.Frame(root, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
    steps.pack(fill="x", padx=pad)
    marks, names = [], []
    for title, _, _ in INSTALL_STEPS:
        row = tk.Frame(steps, bg=SURFACE)
        row.pack(fill="x", padx=14, pady=4)
        m = tk.Label(row, text="○", width=2, bg=SURFACE, fg=TEXT3, font=(FONT, 12))
        m.pack(side="left")
        n = tk.Label(row, text=title, bg=SURFACE, fg=TEXT3, font=(FONT, 11), anchor="w")
        n.pack(side="left", fill="x", expand=True)
        marks.append(m)
        names.append(n)

    # Seçenekler: yalnızca kurulumdan önce görünür (güncelleme penceresinin adım kutusuyla aynı yüzey)
    opts = tk.Frame(root, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
    opts.pack(fill="x", padx=pad, pady=(10, 0))

    def option(var, text, desc=None):
        row = tk.Frame(opts, bg=SURFACE)
        row.pack(fill="x", padx=10, pady=(6, 0 if desc else 6))
        c = tk.Checkbutton(row, text=text, variable=var, bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                           activebackground=SURFACE, activeforeground="#ffffff", font=(FONT, 11), anchor="w",
                           highlightthickness=0, bd=0, cursor="hand2")
        c.pack(fill="x")
        if desc:
            tk.Label(row, text=desc, bg=SURFACE, fg=TEXT3, font=(FONT, 9), justify="left", anchor="w",
                     wraplength=wrap - int(60 * s)).pack(fill="x", padx=(int(26 * s), 0), pady=(0, 6))
        return row

    prev = guard_state()
    guard = tk.BooleanVar(value=True if prev is None else prev)
    restore = tk.BooleanVar(value=False)
    launch = tk.BooleanVar(value=True)
    guard_row = option(
        guard, "Eski Control Center'ın geri yüklenmesini engelle",
        "Windows Update ya da Microsoft Store eski Fn / Control Center paketlerini geri kurarsa FCUK onları açılışta ve "
        "10 dakikada bir kaldırır. Hız aşırtma, Flexikey ve pil uygulamalarına dokunmaz. Geri alınabilir: kurulumu bu "
        "kutu işaretsiz yeniden çalıştırın ya da FCUK'u kaldırın.")
    guard_row.pack_forget()  # yalnızca Clevo/Monster tespit edilince görünür
    rp_row = option(restore, "Önce sistem geri yükleme noktası oluştur", "Birkaç dakika sürebilir.")
    option(launch, "Bitince uygulamayı aç")

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("U.Horizontal.TProgressbar", troughcolor=SURFACE, background=LIVE, bordercolor=LINE,
                    lightcolor=LIVE, darkcolor=LIVE, thickness=int(8 * s))
    bar = ttk.Progressbar(root, mode="indeterminate", maximum=100, style="U.Horizontal.TProgressbar")
    bar.pack(fill="x", padx=pad, pady=(14, 4))
    info = tk.Frame(root, bg=BG)
    info.pack(fill="x", padx=pad)
    elapsed = tk.Label(info, text="", bg=BG, fg=TEXT3, font=(FONT, 9), anchor="w")
    elapsed.pack(side="left")
    foot = tk.Label(root, text="Taranıyor...", bg=BG, fg=TEXT2, font=(FONT, 10), justify="left", anchor="w",
                    wraplength=wrap)
    foot.pack(fill="x", padx=pad, pady=(10, 0))

    btns = tk.Frame(root, bg=BG)
    btns.pack(side="bottom", fill="x", padx=pad, pady=(12, pad - 8))
    box = tk.Frame(root, bg=LINE, padx=1, pady=1)
    txt = tk.Text(box, bg=SURFACE, fg=TEXT2, relief="flat", font=("Consolas", 9), wrap="word", padx=8, pady=6,
                  highlightthickness=0, height=8)
    sb = tk.Scrollbar(box, command=txt.yview)
    txt.configure(yscrollcommand=sb.set, state="disabled")
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    for k, c in COLORS.items():
        txt.tag_configure(k, foreground=c)
    txt.tag_configure("ADIM", font=("Consolas", 9, "bold"))

    def button(text, cmd, primary=False):
        return tk.Button(btns, text=text, command=cmd, font=(FONT, 10, "bold" if primary else "normal"), relief="flat",
                         bd=0, padx=16, pady=6, cursor="hand2", bg=TEXT if primary else SURFACE2,
                         fg=BG if primary else TEXT, activebackground="#ffffff" if primary else LINE,
                         activeforeground=BG if primary else "#ffffff", disabledforeground=TEXT3)

    def fit():
        """Pencere içeriğe göre boylanır; alt kenar (düğmeler) ekranın / görev çubuğunun altına taşmaz."""
        root.update_idletasks()
        h = root.winfo_reqheight()
        y = root.winfo_y()
        limit = root.winfo_screenheight() - int(56 * s)
        if y + h > limit:
            y = max(0, limit - h)
        root.geometry("%dx%d+%d+%d" % (w, h, root.winfo_x(), y))

    q = queue.Queue()
    st = {"phase": "scan", "step": 0, "val": 1.0, "rc": None, "errors": [], "warns": [], "t0": 0.0,
          "details": False, "clevo": True}

    def paint():
        for i, (m, n) in enumerate(zip(marks, names)):
            if st["phase"] in ("scan", "ready"):
                m.configure(text="○", fg=TEXT3)
                n.configure(fg=TEXT2)
            elif st["rc"] is not None and st["rc"] != 1 or i < st["step"]:
                m.configure(text="✓", fg=GOOD)
                n.configure(fg=TEXT2)
            elif i == st["step"] and st["rc"] is None:
                m.configure(text="●", fg=LIVE)
                n.configure(fg="#ffffff")
            elif i == st["step"]:  # hata: bu adımda kaldı
                m.configure(text="✗", fg=BAD)
                n.configure(fg=BAD)
            else:
                m.configure(text="○", fg=TEXT3)
                n.configure(fg=TEXT3)

    def log_line(kind, msg):
        txt.configure(state="normal")
        txt.insert("end", PREFIX[kind] + msg + "\n", kind)
        txt.see("end")
        txt.configure(state="disabled")

    def set_device(kind):
        st["clevo"] = kind == "clevo"
        if st["clevo"]:
            sub.configure(text=sub_text("Clevo / Monster: Monster Control Center'ın yerine geçer"))
            note.configure(text=CLEVO_TEXT)
            guard_row.pack(fill="x", padx=10, pady=(6, 0), before=rp_row)
        else:
            sub.configure(text=sub_text(MARKA.get(kind, ("Diğer cihaz",))[0]))
            note.configure(text=device_text(kind))
            names[1].configure(text="Önceki sürüm kapatılıyor")
            guard_row.pack_forget()
        fit()

    def pump():
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "line":
                    _, kind, msg = item
                    if kind == "CIHAZ":
                        if st["phase"] == "scan":
                            set_device(msg)
                        continue
                    if st["phase"] == "install":
                        if kind == "HATA":
                            st["errors"].append(msg)
                        elif kind == "UYARI":
                            st["warns"].append(msg)
                    log_line(kind, msg)
                    if kind == "ADIM" and st["phase"] == "install":
                        nxt = update_step(msg, st["step"], INSTALL_STEPS)
                        if nxt != st["step"]:
                            st["step"] = nxt
                            st["val"] = max(st["val"], INSTALL_STEPS[nxt][1])
                            paint()
                        foot.configure(text=msg + "...", fg=TEXT2)
                else:
                    item[1]()
        except queue.Empty:
            pass
        root.after(60, pump)

    def tick():
        if st["phase"] == "install" and st["rc"] is None:
            end = (INSTALL_STEPS[st["step"] + 1][1] if st["step"] + 1 < len(INSTALL_STEPS) else 99) - 2
            st["val"] = min(st["val"] + 0.08, end)  # adım içinde yavaşça ilerler: pencere donmuş görünmesin
            bar["value"] = st["val"]
            sec = int(time.monotonic() - st["t0"])
            elapsed.configure(text="Geçen süre %d:%02d" % (sec // 60, sec % 60))
            marks[st["step"]].configure(fg=LIVE if int(time.monotonic() * 2) % 2 else "#ffffff")
        root.after(100, tick)

    def toggle_details():
        st["details"] = not st["details"]
        if st["details"]:
            # Kutu ekranda kalan yere göre boylanır (1080p'de seçenekler açıkken pencere ekranı aşmasın)
            root.update_idletasks()
            from tkinter import font as tkfont
            line = tkfont.Font(family="Consolas", size=9).metrics("linespace")
            room = root.winfo_screenheight() - int(110 * s) - root.winfo_reqheight()
            txt.configure(height=max(4, min(14, room // max(1, line))))
            box.pack(fill="x", padx=pad, pady=(10, 0), before=btns)
            more.configure(text="Ayrıntıları gizle")
        else:
            box.pack_forget()
            more.configure(text="Ayrıntılar")
        fit()

    def open_log():
        if os.path.exists(LOG):
            subprocess.Popen(["notepad.exe", LOG], creationflags=NO_WINDOW)

    def report_done(rc):
        bar.stop()
        bar.configure(mode="determinate", value=0)
        st["phase"] = "ready"
        foot.configure(text="Hazır. Seçenekleri gözden geçirip 'Kur'a basın. Bulunanlar 'Ayrıntılar'da."
                       if rc == 0 else "Tarama tamamlanamadı (ayrıntılarda); yine de kurabilirsiniz.",
                       fg=TEXT2 if rc == 0 else WARN)
        go.configure(state="normal")

    def start_install():
        if st["phase"] != "ready":
            return
        st.update(phase="install", step=0, val=1.0, rc=None, errors=[], warns=[], t0=time.monotonic())
        head.configure(text="Kuruluyor")
        note.configure(text="Kurulum sürüyor. Bilgisayarı kapatmayın; pencere kapatılırsa kurulum yarıda kalmaz, "
                            "görev çubuğuna küçülür.", fg=TEXT)
        opts.pack_forget()
        go.pack_forget()
        cancel.pack_forget()
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disabled")
        bar.configure(mode="determinate", value=1)
        paint()
        fit()
        guard_choice = guard.get() if st["clevo"] else None
        restore_choice = restore.get()

        def work():
            try:
                rc = run_script("Install", lambda k, m: q.put(("line", k, m)), restore=restore_choice,
                                guard=guard_choice)
            except Exception as e:  # powershell bulunamadı vb.
                q.put(("line", "HATA", str(e)))
                rc = 1
            q.put(("call", lambda: finished(rc)))
        threading.Thread(target=work, daemon=True).start()

    def finished(rc):
        st["rc"] = rc
        st["phase"] = "done"
        bar["value"] = 100 if rc != 1 else st["val"]
        sec = int(time.monotonic() - st["t0"])
        elapsed.configure(text="Süre %d:%02d" % (sec // 60, sec % 60))
        paint()
        root.deiconify()
        root.lift()
        button("Kapat", finish, primary=True).pack(side="right")
        if rc == 1:
            head.configure(text="Kurulum tamamlanamadı", fg=BAD)
            why = st["errors"][-1] if st["errors"] else "ayrıntı kayıt dosyasında"
            note.configure(text="Sorun: %s" % why, fg=BAD)
            foot.configure(text="Eski Control Center yedekleri ve kayıt: %s" % os.path.dirname(LOG), fg=TEXT2)
            button("Kaydı aç", open_log).pack(side="right", padx=(0, 8))
            if not st["details"]:
                toggle_details()
            fit()
            return
        if rc == 2:
            head.configure(text="Kurulum tamamlandı", fg=WARN)
            note.configure(text="FCUK Control Center kuruldu, ancak %d uyarı var (ayrıntılarda sarı satırlar)."
                           % len(st["warns"]), fg=WARN)
            button("Kaydı aç", open_log).pack(side="right", padx=(0, 8))
            if not st["details"]:
                toggle_details()
        else:
            head.configure(text="Kurulum tamamlandı", fg=GOOD)
            note.configure(text=("FCUK Control Center eski Control Center'ın yerini aldı." if st["clevo"] else
                                 "FCUK Control Center kuruldu. Diğer uygulamalara dokunulmadı."), fg=GOOD)
        if st["clevo"]:
            # Sürücü, hizmet ve Fn tuşu değişiklikleri tam olarak yeniden başlatınca devreye girer
            foot.configure(text="Tam çalışması için bilgisayarı yeniden başlatın: eski Control Center kalıntıları ve "
                                "Fn tuşu engelleri ancak yeniden başlatınca tamamen devreye girer.", fg=WARN)
            button("Şimdi yeniden başlat", reboot_now).pack(side="right", padx=(0, 8))
        else:
            foot.configure(text="Kapat'a basınca uygulama açılır." if launch.get() else "", fg=TEXT2)
        fit()

    def finish():
        if st["rc"] not in (None, 1) and launch.get():
            root.withdraw()  # tepsi beklenirken donmuş pencere görünmesin
            open_app()
        root.destroy()

    def on_close():
        if st["phase"] == "install":
            root.iconify()  # kurulum yarıda kesilmez: pencere yalnızca görev çubuğuna küçülür
            return
        if st["phase"] == "done":
            finish()
            return
        root.destroy()

    def reboot_now():
        from tkinter import messagebox
        if messagebox.askyesno(TITLE, "Bilgisayar 10 saniye içinde yeniden başlatılacak.\nAçık işleriniz kaydedildi mi?"):
            subprocess.Popen(["shutdown.exe", "/r", "/t", "10", "/c", TITLE + " kurulumu için yeniden başlatılıyor"],
                             creationflags=NO_WINDOW)
            root.destroy()

    more = button("Ayrıntılar", toggle_details)
    more.pack(side="left")
    go = button("Kur", start_install, primary=True)
    go.configure(state="disabled")
    go.pack(side="right")
    cancel = button("İptal", on_close)
    cancel.pack(side="right", padx=(0, 8))
    root.protocol("WM_DELETE_WINDOW", on_close)

    log_line("ADIM", "Bu bilgisayarda bulunanlar")
    bar.start(12)
    paint()
    fit()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2,
                              max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3)))

    def scan():
        try:
            rc = run_script("Report", lambda k, m: q.put(("line", k, m)))
        except Exception as e:
            q.put(("line", "HATA", str(e)))
            rc = 1
        q.put(("call", lambda: report_done(rc)))
    threading.Thread(target=scan, daemon=True).start()
    pump()
    tick()
    root.mainloop()


# ----------------------------------------------------------------------------- güncelleme penceresi
UPDATE_TITLE = "FCUK Control Center güncelleniyor"  # pencere.py UPDATE_TITLE ile aynı: uygulama penceresi bunu bekler
# Güncelleme adımları. Her biri kurulum.ps1'in "ADIM|..." satırlarından birine (küçük harfle) eşlenir; eşleşmeyen
# satır adımı değiştirmez, adım geriye gitmez. (başlık, başlangıç yüzdesi, eşleşen ifadeler)
UPDATE_STEPS = [
    ("Güncelleme hazırlanıyor", 0, ()),
    ("Uygulama kapatılıyor", 8, ("kapatılıyor", "durduruluyor", "engelleniyor", "paketleri kaldırılıyor")),
    ("Dosyalar güncelleniyor", 40, ("kopyalanıyor", "cihaza özel")),
    ("Ayarlar uygulanıyor", 78, ("açılış görevleri", "kısayollar", "geri yükleme engeli")),
    ("Yeni sürüm başlatılıyor", 88, ("başlatılıyor ve doğrulanıyor",)),
]


def update_step(text, current=0, steps=None):
    """kurulum.ps1 adım satırına karşılık gelen adımın sırası (varsayılan: güncelleme adımları); yalnızca ilerler."""
    steps = UPDATE_STEPS if steps is None else steps
    low = (text or "").lower()
    for i in range(len(steps) - 1, current, -1):
        if any(k in low for k in steps[i][2]):
            return i
    return current


def installed_version():
    """Kurulu (güncellenmeden önceki) sürüm: Uygulamalar listesi kaydından. Okunamazsa boş."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\FCUKControlCenter") as k:
            return str(winreg.QueryValueEx(k, "DisplayVersion")[0]).strip()
    except OSError:
        return ""


def update_gui():
    """/guncelle: uygulamadan bağımsız güncelleme penceresi. Uygulama bu pencere görününce kendi penceresini kapatır;
    kurulum burada, ilerlemesi gösterilerek sürer, bitince yeni sürüm açılır. Çıkış kodunu döndürür; pencere hiç
    açılamazsa None (çağıran sessiz kuruluma düşer)."""
    import time
    try:
        import ctypes
        import tkinter as tk
        from tkinter import ttk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
        root = tk.Tk()
    except Exception:
        return None

    BG, SURFACE, SURFACE2, LINE = "#0a0c0f", "#111419", "#181c23", "#252a33"
    TEXT, TEXT2, TEXT3 = "#eceff4", "#a9b1be", "#818a99"
    GOOD, WARN, BAD, LIVE = "#5fd38d", "#ffc861", "#ff6b6b", "#7cc4ff"
    FONT = "Bahnschrift"
    PREFIX = {"ADIM": "\n▸ ", "OK": "  ✓ ", "UYARI": "  ! ", "HATA": "  ✗ ", "BILGI": "  · ", "HAM": "    "}
    COLORS = {"ADIM": "#ffffff", "BILGI": TEXT2, "OK": GOOD, "UYARI": WARN, "HATA": BAD, "HAM": TEXT3}

    old, new = installed_version(), version()
    root.title(UPDATE_TITLE)
    root.configure(bg=BG)
    s = root.winfo_fpixels("1i") / 96.0
    w, h = int(520 * s), int(470 * s)
    root.geometry("%dx%d+%d+%d" % (w, h, (root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(BUNDLE, "uygulama.ico"))
    except tk.TclError:
        pass
    try:  # güncellerken bilgisayar uykuya geçmesin
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except (OSError, AttributeError):
        pass

    pad = int(26 * s)
    tk.Label(root, text=TITLE, bg=BG, fg=TEXT3, font=(FONT, 10), anchor="w").pack(fill="x", padx=pad, pady=(pad - 6, 0))
    head = tk.Label(root, text="Güncelleniyor", bg=BG, fg="#ffffff", font=(FONT, 20, "bold"), anchor="w")
    head.pack(fill="x", padx=pad)
    sub = tk.Label(root, text=("Sürüm %s  →  %s" % (old, new)) if old and new else ("Sürüm %s" % new if new else ""),
                   bg=BG, fg=LIVE, font=(FONT, 11), anchor="w")
    sub.pack(fill="x", padx=pad)
    note = tk.Label(root, bg=BG, fg=TEXT, font=(FONT, 11), justify="left", anchor="w", wraplength=w - 2 * pad)
    note.pack(fill="x", padx=pad, pady=(14, 8))

    steps = tk.Frame(root, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
    steps.pack(fill="x", padx=pad)
    marks, names = [], []
    for title, _, _ in UPDATE_STEPS:
        row = tk.Frame(steps, bg=SURFACE)
        row.pack(fill="x", padx=14, pady=4)
        m = tk.Label(row, text="○", width=2, bg=SURFACE, fg=TEXT3, font=(FONT, 12))
        m.pack(side="left")
        n = tk.Label(row, text=title, bg=SURFACE, fg=TEXT3, font=(FONT, 11), anchor="w")
        n.pack(side="left", fill="x", expand=True)
        marks.append(m)
        names.append(n)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("U.Horizontal.TProgressbar", troughcolor=SURFACE, background=LIVE, bordercolor=LINE,
                    lightcolor=LIVE, darkcolor=LIVE, thickness=int(8 * s))
    bar = ttk.Progressbar(root, mode="determinate", maximum=100, style="U.Horizontal.TProgressbar")
    bar.pack(fill="x", padx=pad, pady=(14, 4))
    info = tk.Frame(root, bg=BG)
    info.pack(fill="x", padx=pad)
    elapsed = tk.Label(info, text="Geçen süre 0:00", bg=BG, fg=TEXT3, font=(FONT, 9), anchor="w")
    elapsed.pack(side="left")
    foot = tk.Label(root, text="Bilgisayarı kapatmayın. Bitince uygulama kendiliğinden açılır.", bg=BG, fg=TEXT2,
                    font=(FONT, 10), justify="left", anchor="w", wraplength=w - 2 * pad)
    foot.pack(fill="x", padx=pad, pady=(10, 0))

    btns = tk.Frame(root, bg=BG)
    btns.pack(side="bottom", fill="x", padx=pad, pady=(8, pad - 8))
    box = tk.Frame(root, bg=LINE, padx=1, pady=1)
    txt = tk.Text(box, bg=SURFACE, fg=TEXT2, relief="flat", font=("Consolas", 9), wrap="word", padx=8, pady=6,
                  highlightthickness=0, height=9)
    sb = tk.Scrollbar(box, command=txt.yview)
    txt.configure(yscrollcommand=sb.set, state="disabled")
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    for k, c in COLORS.items():
        txt.tag_configure(k, foreground=c)
    txt.tag_configure("ADIM", font=("Consolas", 9, "bold"))

    def button(text, cmd, primary=False):
        return tk.Button(btns, text=text, command=cmd, font=(FONT, 10, "bold" if primary else "normal"), relief="flat",
                         bd=0, padx=16, pady=6, cursor="hand2", bg=TEXT if primary else SURFACE2,
                         fg=BG if primary else TEXT, activebackground="#ffffff" if primary else LINE,
                         activeforeground=BG if primary else "#ffffff")

    q = queue.Queue()
    st = {"step": 0, "val": 1.0, "rc": None, "errors": [], "warns": [], "t0": time.monotonic(), "details": False,
          "left": 0}

    def paint():
        for i, (m, n) in enumerate(zip(marks, names)):
            if st["rc"] is not None and st["rc"] != 1 or i < st["step"]:
                m.configure(text="✓", fg=GOOD)
                n.configure(fg=TEXT2)
            elif i == st["step"] and st["rc"] is None:
                m.configure(text="●", fg=LIVE)
                n.configure(fg="#ffffff")
            elif i == st["step"]:  # hata: bu adımda kaldı
                m.configure(text="✗", fg=BAD)
                n.configure(fg=BAD)
            else:
                m.configure(text="○", fg=TEXT3)
                n.configure(fg=TEXT3)

    def set_note():
        if st["rc"] is not None:
            return
        note.configure(text=("Güncelleme hazırlanıyor. Birazdan uygulama kapanacak; bu normal." if st["step"] == 0 else
                             "Uygulama kapatıldı. Güncelleme bu pencerede sürüyor; uygulamayı yeniden açmayın."),
                       fg=TEXT)

    def log_line(kind, msg):
        txt.configure(state="normal")
        txt.insert("end", PREFIX[kind] + msg + "\n", kind)
        txt.see("end")
        txt.configure(state="disabled")

    def pump():
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "line":
                    _, kind, msg = item
                    if kind == "CIHAZ":
                        continue
                    if kind == "HATA":
                        st["errors"].append(msg)
                    elif kind == "UYARI":
                        st["warns"].append(msg)
                    log_line(kind, msg)
                    if kind == "ADIM":
                        nxt = update_step(msg, st["step"])
                        if nxt != st["step"]:
                            st["step"] = nxt
                            st["val"] = max(st["val"], UPDATE_STEPS[nxt][1])
                            paint()
                            set_note()
                else:
                    item[1]()
        except queue.Empty:
            pass
        root.after(60, pump)

    def tick():
        if st["rc"] is None:
            end = (UPDATE_STEPS[st["step"] + 1][1] if st["step"] + 1 < len(UPDATE_STEPS) else 99) - 2
            st["val"] = min(st["val"] + 0.12, end)  # adım içinde yavaşça ilerler: pencere donmuş görünmesin
            bar["value"] = st["val"]
            sec = int(time.monotonic() - st["t0"])
            elapsed.configure(text="Geçen süre %d:%02d" % (sec // 60, sec % 60))
            marks[st["step"]].configure(fg=LIVE if int(time.monotonic() * 2) % 2 else "#ffffff")
        root.after(100, tick)

    def toggle_details():
        st["details"] = not st["details"]
        if st["details"]:
            box.pack(fill="x", padx=pad, pady=(10, 0), before=btns)
            root.geometry("%dx%d" % (w, h + int(170 * s)))
            more.configure(text="Ayrıntıları gizle")
        else:
            box.pack_forget()
            root.geometry("%dx%d" % (w, h))
            more.configure(text="Ayrıntılar")

    def open_log():
        if os.path.exists(LOG):
            subprocess.Popen(["notepad.exe", LOG], creationflags=NO_WINDOW)

    def close():
        if st["rc"] is None:  # güncelleme yarıda kesilmez: pencere yalnızca görev çubuğuna küçülür
            root.iconify()
            return
        root.destroy()

    def countdown():
        if st["left"] <= 0:
            root.destroy()
            return
        foot.configure(text="Bu pencere %d sn sonra kapanır." % st["left"], fg=TEXT2)
        st["left"] -= 1
        root.after(1000, countdown)

    def finished(rc):
        st["rc"] = rc
        bar["value"] = 100 if rc != 1 else st["val"]
        sec = int(time.monotonic() - st["t0"])
        elapsed.configure(text="Süre %d:%02d" % (sec // 60, sec % 60))
        paint()
        closebtn = button("Kapat", close, primary=True)
        if rc == 1:
            root.deiconify()
            root.lift()
            head.configure(text="Güncelleme tamamlanamadı", fg=BAD)
            why = st["errors"][-1] if st["errors"] else "ayrıntı kayıt dosyasında"
            note.configure(text="Sorun: %s" % why, fg=BAD)
            foot.configure(text="Uygulamayı açmayı deneyebilirsiniz. Sorun sürerse kaydı açıp bize iletin.", fg=TEXT2)
            closebtn.pack(side="right")
            button("Uygulamayı aç", open_app).pack(side="right", padx=(0, 8))
            button("Kaydı aç", open_log).pack(side="right", padx=(0, 8))
            if not st["details"]:
                toggle_details()
        elif rc == 2:
            root.deiconify()
            root.lift()
            head.configure(text="Güncelleme tamamlandı", fg=WARN)
            note.configure(text="Yeni sürüm kuruldu ve açıldı, ancak %d uyarı var." % len(st["warns"]), fg=WARN)
            foot.configure(text="Uyarılar ayrıntılarda sarı satırlarla gösterilir.", fg=TEXT2)
            closebtn.pack(side="right")
            button("Kaydı aç", open_log).pack(side="right", padx=(0, 8))
            if not st["details"]:
                toggle_details()
        else:
            head.configure(text="Güncelleme tamamlandı", fg=GOOD)
            note.configure(text=("Sürüm %s kuruldu ve uygulama açıldı." % new) if new else
                           "Yeni sürüm kuruldu ve uygulama açıldı.", fg=GOOD)
            closebtn.pack(side="right")
            st["left"] = 6
            countdown()

    def work():
        try:
            rc = run_script("Install", lambda k, m: q.put(("line", k, m)))
        except Exception as e:  # powershell bulunamadı vb.
            q.put(("line", "HATA", str(e)))
            rc = 1
        if rc != 1:  # pencereyi tepsi açtırır (tepsi yoksa uygulama kendisi başlatılır)
            try:
                open_app()
            except Exception:
                pass
        q.put(("call", lambda: finished(rc)))

    more = button("Ayrıntılar", toggle_details)
    more.pack(side="left")
    root.protocol("WM_DELETE_WINDOW", close)
    paint()
    set_note()
    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)  # öne gelsin; kullanıcı başka pencerede kalıp güncellemeyi kaçırmasın
    root.after(900, lambda: root.attributes("-topmost", False))
    threading.Thread(target=work, daemon=True).start()
    pump()
    tick()
    root.mainloop()
    return st["rc"] if st["rc"] is not None else 1


def main():
    args = [a.lower() for a in sys.argv[1:]]
    silent_flag = "/s" in args or "--sessiz" in args or "/silent" in args
    # /guncelle: uygulama içi güncelleme (kendi penceresi var). Eski sürümlerin güncelleyicisi "/S /open" çağırır;
    # /open yalnızca uygulama içi güncellemeden geldiği için o da aynı pencereyi açar.
    if "/guncelle" in args or (silent_flag and "/open" in args):
        rc = update_gui()
        sys.exit(rc if rc is not None else silent(open_after=True))  # pencere açılamadı: eski davranış (sessiz)
    if silent_flag:
        guard = True if "/ccengel" in args else False if "/ccengelyok" in args else None
        sys.exit(silent(restore="/restore" in args, reboot="/reboot" in args, guard=guard))
    gui()


if __name__ == "__main__":
    main()
