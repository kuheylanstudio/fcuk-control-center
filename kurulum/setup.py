# -*- coding: utf-8 -*-
# FCUK Control Center - kurulum programı (setup.exe)
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
"""setup.exe: yönetici olarak açılır (PyInstaller --uac-admin), derlenmiş uygulamayı içinde taşır.

İşin kendisini kurulum.ps1 yapar; bu dosya yalnızca pencere ve satır satır ilerleme gösterir.
  setup.exe              pencereli kurulum (önce eski Control Center taraması gösterilir)
  setup.exe /S           sessiz kurulum, çıkış kodu: 0 tamam, 2 uyarılı tamam, 1 hata
  setup.exe /S /restore  sessiz kurulum, önce sistem geri yükleme noktası oluşturur
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


def run_script(mode, on_line, launch=True, restore=False):
    """kurulum.ps1'i çalıştırır, her çıktı satırını (tür, metin) olarak on_line'a verir. Çıkış kodunu döndürür."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SCRIPT,
           "-Mode", mode, "-Version", version()]
    if mode == "Install":
        cmd += ["-Payload", PAYLOAD]
        if not launch:
            cmd.append("-NoLaunch")
        if restore:
            cmd.append("-RestorePoint")
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
        if sep and kind in ("ADIM", "BILGI", "OK", "UYARI", "HATA"):
            on_line(kind, msg)
        else:
            on_line("HAM", line)
    return p.wait()


def open_app():
    """Arayüzü NORMAL kullanıcı yetkisiyle açar: kurulum yönetici olarak çalışıyor; explorer aracılığıyla
    başlatılan süreç kullanıcının kendi (yükseltilmemiş) yetkisini alır."""
    if os.path.exists(EXE):
        subprocess.Popen(["explorer.exe", EXE], creationflags=NO_WINDOW)


def silent(restore=False):
    return run_script("Install", lambda k, m: None, restore=restore)


# ----------------------------------------------------------------------------- pencere
def gui():
    import tkinter as tk
    from tkinter import ttk

    BG, SURFACE, SURFACE2 = "#0a0c0f", "#111419", "#181c23"
    LINE, TEXT, TEXT2, TEXT3 = "#252a33", "#eceff4", "#a9b1be", "#818a99"
    GOOD, WARN, BAD = "#5fd38d", "#ffc861", "#ff6b6b"
    COLORS = {"ADIM": "#ffffff", "BILGI": TEXT2, "OK": GOOD, "UYARI": WARN, "HATA": BAD, "HAM": TEXT3}
    PREFIX = {"ADIM": "\n▸ ", "OK": "  ✓ ", "UYARI": "  ! ", "HATA": "  ✗ ", "BILGI": "  · ", "HAM": "    "}
    FONT = "Bahnschrift"

    root = tk.Tk()
    root.title("%s %s Kurulumu" % (TITLE, version()))
    root.configure(bg=BG)
    root.geometry("780x620")
    root.minsize(620, 480)
    try:
        root.iconbitmap(os.path.join(BUNDLE, "uygulama.ico"))
    except tk.TclError:
        pass

    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=24, pady=(20, 8))
    tk.Label(head, text=TITLE, bg=BG, fg="#ffffff", font=(FONT, 20, "bold"), anchor="w").pack(fill="x")
    tk.Label(head, text="Sürüm %s  ·  Monster / Clevo Control Center'ın yerine geçer" % version(), bg=BG, fg=TEXT3,
             font=(FONT, 10), anchor="w").pack(fill="x")
    tk.Label(head, bg=BG, fg=TEXT2, font=(FONT, 10), justify="left", anchor="w", wraplength=720, text=(
        "Kurulum eski Control Center'ı yedek alarak kaldırır ve FCUK Control Center'ı kurar. Üreticinin kaldırıcısı "
        "çalıştırılmaz, çünkü o kaldırıcı AcpiBridge sürücülerini de siler. Sürücüler ve CCDCHUService korunur: önce "
        "sürücüler dışa aktarılır, sonunda her şey doğrulanır. İsterseniz önce sistem geri yükleme noktası da "
        "oluşturulur (aşağıdaki kutu; birkaç dakika sürebilir).")).pack(fill="x", pady=(10, 0))

    box = tk.Frame(root, bg=LINE, padx=1, pady=1)
    box.pack(fill="both", expand=True, padx=24, pady=8)
    txt = tk.Text(box, bg=SURFACE, fg=TEXT2, insertbackground=TEXT, relief="flat", font=("Consolas", 9),
                  wrap="word", padx=10, pady=8, highlightthickness=0)
    sb = tk.Scrollbar(box, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    for k, c in COLORS.items():
        txt.tag_configure(k, foreground=c)
    txt.tag_configure("ADIM", font=("Consolas", 9, "bold"))
    txt.configure(state="disabled")

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("C.Horizontal.TProgressbar", troughcolor=SURFACE, background=GOOD, bordercolor=LINE,
                    lightcolor=GOOD, darkcolor=GOOD)
    bar = ttk.Progressbar(root, mode="indeterminate", style="C.Horizontal.TProgressbar")
    bar.pack(fill="x", padx=24)

    foot = tk.Frame(root, bg=BG)
    foot.pack(fill="x", padx=24, pady=(10, 18))
    status = tk.Label(foot, text="Eski Control Center taranıyor...", bg=BG, fg=TEXT2, font=(FONT, 10), anchor="w")
    status.pack(side="left", fill="x", expand=True)
    launch = tk.BooleanVar(value=True)
    chk = tk.Checkbutton(foot, text="Bitince aç", variable=launch, bg=BG, fg=TEXT2, selectcolor=SURFACE2,
                         activebackground=BG, activeforeground=TEXT, font=(FONT, 10), highlightthickness=0, bd=0)
    restore = tk.BooleanVar(value=False)
    chk_rp = tk.Checkbutton(foot, text="Geri yükleme noktası oluştur", variable=restore, bg=BG, fg=TEXT2,
                            selectcolor=SURFACE2, activebackground=BG, activeforeground=TEXT, font=(FONT, 10),
                            highlightthickness=0, bd=0)

    def button(text, cmd, primary=False):
        return tk.Button(foot, text=text, command=cmd, font=(FONT, 10, "bold" if primary else "normal"), relief="flat",
                         bd=0, padx=18, pady=6, cursor="hand2", bg=TEXT if primary else SURFACE2,
                         fg=BG if primary else TEXT, activebackground="#ffffff" if primary else LINE,
                         activeforeground=BG if primary else "#ffffff", disabledforeground=TEXT3)

    q = queue.Queue()
    st = {"busy": False, "rc": 1, "errors": []}

    def put(kind, msg):
        q.put(("line", kind, msg))

    def pump():
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "line":
                    _, kind, msg = item
                    if kind == "HATA":
                        st["errors"].append(msg)
                    txt.configure(state="normal")
                    txt.insert("end", PREFIX[kind] + msg + "\n", kind)
                    txt.see("end")
                    txt.configure(state="disabled")
                    if kind == "ADIM":
                        status.configure(text=msg + "...", fg=TEXT2)
                else:
                    item[1]()
        except queue.Empty:
            pass
        root.after(60, pump)

    def report_done(rc):
        bar.stop()
        st["busy"] = False
        status.configure(text="Hazır. Kurmak için 'Kur'a basın." if rc == 0 else "Tarama tamamlanamadı; yine de kurabilirsiniz.",
                         fg=TEXT)
        go.configure(state="normal")

    def install_done(rc):
        bar.stop()
        bar.configure(mode="determinate", value=100)
        st["busy"] = False
        st["rc"] = rc
        if rc == 0:
            status.configure(text="Kurulum tamamlandı. FCUK Control Center eski Control Center'ın yerini aldı.", fg=GOOD)
        elif rc == 2:
            status.configure(text="Kurulum tamamlandı, uyarılar var (sarı satırlar).", fg=WARN)
        else:
            why = st["errors"][-1] if st["errors"] else "ayrıntı kayıt dosyasında"
            status.configure(text="Kurulum tamamlanamadı: %s" % why, fg=BAD, wraplength=420, justify="left")
            logbtn.pack(side="right", padx=(0, 8))
        go.configure(text="Kapat", state="normal", command=finish)
        cancel.pack_forget()
        chk_rp.pack_forget()
        if rc == 1:
            chk.pack_forget()

    def finish():
        if st["rc"] != 1 and launch.get():
            open_app()
        root.destroy()

    def start_install():
        if st["busy"]:
            return
        st["busy"] = True
        go.configure(state="disabled")
        cancel.configure(state="disabled")
        chk_rp.configure(state="disabled")
        st["errors"] = []
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disabled")
        bar.configure(mode="indeterminate")
        bar.start(12)
        status.configure(text="Kuruluyor...", fg=TEXT2)

        def work():
            try:
                rc = run_script("Install", put, restore=restore.get())
            except Exception as e:  # powershell bulunamadı vb.
                put("HATA", str(e))
                rc = 1
            q.put(("call", lambda: install_done(rc)))
        threading.Thread(target=work, daemon=True).start()

    def on_close():
        if st["busy"]:
            return  # kurulum yarıda kesilmez
        root.destroy()

    def open_log():
        if os.path.exists(LOG):
            subprocess.Popen(["notepad.exe", LOG], creationflags=NO_WINDOW)

    cancel = button("İptal", on_close)
    logbtn = button("Kaydı aç", open_log)
    go = button("Kur", start_install, primary=True)
    go.configure(state="disabled")
    go.pack(side="right")
    cancel.pack(side="right", padx=(0, 8))
    chk.pack(side="right", padx=(0, 16))
    chk_rp.pack(side="right", padx=(0, 12))
    root.protocol("WM_DELETE_WINDOW", on_close)

    put("ADIM", "Bu bilgisayarda bulunanlar")
    st["busy"] = True
    bar.start(12)

    def scan():
        try:
            rc = run_script("Report", put)
        except Exception as e:
            put("HATA", str(e))
            rc = 1
        q.put(("call", lambda: report_done(rc)))
    threading.Thread(target=scan, daemon=True).start()
    pump()
    root.mainloop()


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "/s" in args or "--sessiz" in args or "/silent" in args:
        sys.exit(silent(restore="/restore" in args))
    gui()


if __name__ == "__main__":
    main()
