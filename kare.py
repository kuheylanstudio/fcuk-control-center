# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Kare hizi (FPS): oyuna DOKUNMADAN, Windows'un olay izleme (ETW) akisindan.

DirectX 10/11/12 (DXGI) ve DirectX 9 katmani her kare sunumunda (Present) bir olay yayar. Bu modul gercek
zamanli bir ETW oturumu acar, yalnizca bu olaylari (olay kimligi suzgeciyle) alir ve surec basina zaman
damgalarini tutar. FPS = on plandaki pencerenin surecinin son 1 saniyedeki sunum sayisi; olaylarin kendi zaman
damgalariyla hesaplanir, ETW tamponlari toplu teslim etse de sonuc titremez.

- Oyuna hicbir sey enjekte edilmez, oyunun bellegi okunmaz (hile korumalariyla sorun cikmaz).
- ETW oturumu acmak yonetici yetkisi ister: motor yonetici modunda degilse durum "admin" olur.
- Vulkan / OpenGL oyunlar DXGI uzerinden sunmuyorsa olcum cikmaz (durum "none").
- Yalnizca gostergede FPS secili ve gosterge acikken calisir; kapaninca oturum hemen durdurulur.
"""
import ctypes
import threading
import time
from collections import deque
from ctypes import wintypes as wt

SESSION = "FCUKControlCenterFPS"
WINDOW = 1.0         # FPS penceresi (sn)
STALE = 2.0          # bu kadar suredir sunum yoksa o surec icin olcum yok
DXGI = "{CA11C036-0102-4A2D-A6AD-F03CFED5D3C9}"  # Microsoft-Windows-DXGI
D3D9 = "{783ACA0A-790E-4D7F-8451-AA850511C6B9}"  # Microsoft-Windows-Direct3D9
DXGI_PRESENT = (42, 55)  # Present_Start, PresentMultiplaneOverlay_Start
D3D9_PRESENT = (1,)      # Present_Start

ULONG, USHORT, UCHAR, ULONG64 = wt.ULONG, wt.USHORT, ctypes.c_ubyte, ctypes.c_uint64
TRACEHANDLE = ctypes.c_uint64
INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF
WNODE_FLAG_TRACED_GUID = 0x00020000
EVENT_TRACE_REAL_TIME_MODE = 0x00000100
EVENT_TRACE_CONTROL_STOP = 1
EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1
EVENT_FILTER_TYPE_EVENT_ID = 0x80000200
ENABLE_TRACE_PARAMETERS_VERSION_2 = 2
PROCESS_TRACE_MODE_REAL_TIME = 0x00000100
PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000
ERROR_ALREADY_EXISTS, ERROR_ACCESS_DENIED = 183, 5


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        g = cls()
        ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(g))
        return g


class WNODE_HEADER(ctypes.Structure):
    _fields_ = [("BufferSize", ULONG), ("ProviderId", ULONG), ("HistoricalContext", ULONG64),
                ("TimeStamp", ctypes.c_int64), ("Guid", GUID), ("ClientContext", ULONG), ("Flags", ULONG)]


class EVENT_TRACE_PROPERTIES(ctypes.Structure):
    _fields_ = [("Wnode", WNODE_HEADER), ("BufferSize", ULONG), ("MinimumBuffers", ULONG),
                ("MaximumBuffers", ULONG), ("MaximumFileSize", ULONG), ("LogFileMode", ULONG),
                ("FlushTimer", ULONG), ("EnableFlags", ULONG), ("AgeLimit", ctypes.c_long),
                ("NumberOfBuffers", ULONG), ("FreeBuffers", ULONG), ("EventsLost", ULONG),
                ("BuffersWritten", ULONG), ("LogBuffersLost", ULONG), ("RealTimeBuffersLost", ULONG),
                ("LoggerThreadId", wt.HANDLE), ("LogFileNameOffset", ULONG), ("LoggerNameOffset", ULONG)]


class _Props(ctypes.Structure):
    """EVENT_TRACE_PROPERTIES + oturum adi icin yer (StartTrace adi oraya kopyalar)."""
    _fields_ = [("p", EVENT_TRACE_PROPERTIES), ("name", ctypes.c_wchar * 1024)]


class EVENT_FILTER_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Ptr", ULONG64), ("Size", ULONG), ("Type", ULONG)]


class ENABLE_TRACE_PARAMETERS(ctypes.Structure):
    _fields_ = [("Version", ULONG), ("EnableProperty", ULONG), ("ControlFlags", ULONG), ("SourceId", GUID),
                ("EnableFilterDesc", ctypes.POINTER(EVENT_FILTER_DESCRIPTOR)), ("FilterDescCount", ULONG)]


class EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Id", USHORT), ("Version", UCHAR), ("Channel", UCHAR), ("Level", UCHAR), ("Opcode", UCHAR),
                ("Task", USHORT), ("Keyword", ULONG64)]


class EVENT_HEADER(ctypes.Structure):
    _fields_ = [("Size", USHORT), ("HeaderType", USHORT), ("Flags", USHORT), ("EventProperty", USHORT),
                ("ThreadId", ULONG), ("ProcessId", ULONG), ("TimeStamp", ctypes.c_int64), ("ProviderId", GUID),
                ("EventDescriptor", EVENT_DESCRIPTOR), ("ProcessorTime", ULONG64), ("ActivityId", GUID)]


class EVENT_RECORD(ctypes.Structure):
    _fields_ = [("EventHeader", EVENT_HEADER), ("BufferContext", ULONG), ("ExtendedDataCount", USHORT),
                ("UserDataLength", USHORT), ("ExtendedData", ctypes.c_void_p), ("UserData", ctypes.c_void_p),
                ("UserContext", ctypes.c_void_p)]


class EVENT_TRACE_HEADER(ctypes.Structure):
    _fields_ = [("Size", USHORT), ("FieldTypeFlags", USHORT), ("Version", ULONG), ("ThreadId", ULONG),
                ("ProcessId", ULONG), ("TimeStamp", ctypes.c_int64), ("Guid", GUID), ("ProcessorTime", ULONG64)]


class EVENT_TRACE(ctypes.Structure):
    _fields_ = [("Header", EVENT_TRACE_HEADER), ("InstanceId", ULONG), ("ParentInstanceId", ULONG),
                ("ParentGuid", GUID), ("MofData", ctypes.c_void_p), ("MofLength", ULONG), ("ClientContext", ULONG)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wt.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond",
                                       "wMilliseconds")]


class TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [("Bias", ctypes.c_long), ("StandardName", ctypes.c_wchar * 32), ("StandardDate", SYSTEMTIME),
                ("StandardBias", ctypes.c_long), ("DaylightName", ctypes.c_wchar * 32),
                ("DaylightDate", SYSTEMTIME), ("DaylightBias", ctypes.c_long)]


class TRACE_LOGFILE_HEADER(ctypes.Structure):
    _fields_ = [("BufferSize", ULONG), ("Version", ULONG), ("ProviderVersion", ULONG),
                ("NumberOfProcessors", ULONG), ("EndTime", ctypes.c_int64), ("TimerResolution", ULONG),
                ("MaximumFileSize", ULONG), ("LogFileMode", ULONG), ("BuffersWritten", ULONG),
                ("LogInstanceGuid", GUID), ("LoggerName", ctypes.c_void_p), ("LogFileName", ctypes.c_void_p),
                ("TimeZone", TIME_ZONE_INFORMATION), ("BootTime", ctypes.c_int64), ("PerfFreq", ctypes.c_int64),
                ("StartTime", ctypes.c_int64), ("ReservedFlags", ULONG), ("BuffersLost", ULONG)]


EVENT_RECORD_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(EVENT_RECORD))


class EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [("LogFileName", wt.LPWSTR), ("LoggerName", wt.LPWSTR), ("CurrentTime", ctypes.c_int64),
                ("BuffersRead", ULONG), ("ProcessTraceMode", ULONG), ("CurrentEvent", EVENT_TRACE),
                ("LogfileHeader", TRACE_LOGFILE_HEADER), ("BufferCallback", ctypes.c_void_p),
                ("BufferSize", ULONG), ("Filled", ULONG), ("EventsLost", ULONG),
                ("EventRecordCallback", EVENT_RECORD_CALLBACK), ("IsKernelTrace", ULONG),
                ("Context", ctypes.c_void_p)]


_adv = None


def _api():
    global _adv
    if _adv is None:
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        a.StartTraceW.argtypes = [ctypes.POINTER(TRACEHANDLE), wt.LPCWSTR, ctypes.c_void_p]
        a.StartTraceW.restype = ULONG
        a.ControlTraceW.argtypes = [TRACEHANDLE, wt.LPCWSTR, ctypes.c_void_p, ULONG]
        a.ControlTraceW.restype = ULONG
        a.EnableTraceEx2.argtypes = [TRACEHANDLE, ctypes.POINTER(GUID), ULONG, UCHAR, ULONG64, ULONG64, ULONG,
                                     ctypes.POINTER(ENABLE_TRACE_PARAMETERS)]
        a.EnableTraceEx2.restype = ULONG
        a.OpenTraceW.argtypes = [ctypes.POINTER(EVENT_TRACE_LOGFILEW)]
        a.OpenTraceW.restype = TRACEHANDLE
        a.ProcessTrace.argtypes = [ctypes.POINTER(TRACEHANDLE), ULONG, ctypes.c_void_p, ctypes.c_void_p]
        a.ProcessTrace.restype = ULONG
        a.CloseTrace.argtypes = [TRACEHANDLE]
        a.CloseTrace.restype = ULONG
        _adv = a
    return _adv


def _props():
    pr = _Props()
    p = pr.p
    p.Wnode.BufferSize = ctypes.sizeof(_Props)
    p.Wnode.Flags = WNODE_FLAG_TRACED_GUID
    p.Wnode.ClientContext = 1  # zaman damgasi: QueryPerformanceCounter
    p.BufferSize = 32            # KB
    p.MinimumBuffers = 4
    p.MaximumBuffers = 16
    p.LogFileMode = EVENT_TRACE_REAL_TIME_MODE
    p.FlushTimer = 1             # sn: tampon dolmasa da saniyede bir teslim
    p.LoggerNameOffset = _Props.name.offset
    return pr


def stop_session():
    """Ayni adli (onceki cokmus surecten kalmis olabilir) oturumu durdurur."""
    try:
        pr = _props()
        _api().ControlTraceW(0, SESSION, ctypes.byref(pr), EVENT_TRACE_CONTROL_STOP)
    except OSError:
        pass


def fps_from(stamps, freq, now_qpc):
    """Zaman damgalarindan (QPC) FPS: en son sunumdan geriye WINDOW saniyedeki aralik sayisi / sure.
    Son sunum STALE saniyeden eskiyse None (uygulama artik cizmiyor)."""
    if len(stamps) < 2 or freq <= 0:
        return None
    last = stamps[-1]
    if (now_qpc - last) / freq > STALE:
        return None
    lo = last - WINDOW * freq
    first, n = last, 0
    for ts in reversed(stamps):
        if ts < lo:
            break
        first, n = ts, n + 1
    if n < 2 or last <= first:
        return None
    return (n - 1) * freq / (last - first)


def _event_filter(ids):
    """EVENT_FILTER_EVENT_ID { BOOLEAN FilterIn; UCHAR Reserved; USHORT Count; USHORT Events[] }"""
    buf = ctypes.create_string_buffer(4 + 2 * len(ids))
    buf[0] = 1  # FilterIn: yalnizca bu kimlikler
    ctypes.c_uint16.from_buffer(buf, 2).value = len(ids)
    for i, v in enumerate(ids):
        ctypes.c_uint16.from_buffer(buf, 4 + 2 * i).value = v
    return buf


class FpsCounter:
    """ensure(True) oturumu acar, ensure(False) kapatir. read() -> (fps veya None, durum)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.handle = TRACEHANDLE(0)
        self.consumer = INVALID_PROCESSTRACE_HANDLE
        self.state = "off"          # off | ok | admin | error
        self.error = ""
        self.dxgi, self.d3d9 = {}, {}  # pid -> deque(QPC)
        self.freq = ctypes.c_int64()
        ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(self.freq))
        self._cb = EVENT_RECORD_CALLBACK(self._on_event)  # referans canli kalmali
        self._dxgi1 = GUID.parse(DXGI).Data1
        self._d3d91 = GUID.parse(D3D9).Data1
        self._retry_at = 0.0
        self._keep = []

    # -- ETW geri cagrisi (ProcessTrace is parcacigi): olabildigince kisa
    def _on_event(self, rec):
        try:
            h = rec.contents.EventHeader
            d1, eid = h.ProviderId.Data1, h.EventDescriptor.Id
            if d1 == self._dxgi1 and eid in DXGI_PRESENT:
                book = self.dxgi
            elif d1 == self._d3d91 and eid in D3D9_PRESENT:
                book = self.d3d9
            else:
                return
            q = book.get(h.ProcessId)
            if q is None:
                q = book[h.ProcessId] = deque(maxlen=2000)
            q.append(h.TimeStamp)
        except Exception:
            pass

    # -- yasam dongusu
    def ensure(self, want):
        with self.lock:
            running = self.thread is not None and self.thread.is_alive()
            if want and not running:
                if self.state in ("admin", "error") and time.monotonic() < self._retry_at:
                    return
                if self.thread is not None:  # pompa beklenmedik durduysa artiklari temizle
                    self._stop()
                self._start()
            elif not want and (running or self.handle.value):
                self._stop()
                self.state = "off"

    def _enable(self, api, guid, ids):
        g = GUID.parse(guid)
        buf = _event_filter(ids)
        desc = EVENT_FILTER_DESCRIPTOR(ctypes.addressof(buf), len(buf), EVENT_FILTER_TYPE_EVENT_ID)
        par = ENABLE_TRACE_PARAMETERS(Version=ENABLE_TRACE_PARAMETERS_VERSION_2,
                                      EnableFilterDesc=ctypes.pointer(desc), FilterDescCount=1)
        rc = api.EnableTraceEx2(self.handle, ctypes.byref(g), EVENT_CONTROL_CODE_ENABLE_PROVIDER, 5,
                                0xFFFFFFFFFFFFFFFF, 0, 0, ctypes.byref(par))
        if rc not in (0, ERROR_ACCESS_DENIED):  # suzgec desteklenmezse suzgecsiz (geri cagri yine bakar)
            rc = api.EnableTraceEx2(self.handle, ctypes.byref(g), EVENT_CONTROL_CODE_ENABLE_PROVIDER, 5,
                                    0xFFFFFFFFFFFFFFFF, 0, 0, None)
        return rc

    def _start(self):
        self.dxgi, self.d3d9 = {}, {}
        try:
            api = _api()
            pr = _props()
            rc = api.StartTraceW(ctypes.byref(self.handle), SESSION, ctypes.byref(pr))
            if rc == ERROR_ALREADY_EXISTS:  # onceki (cokmus) surecten kalan oturum
                stop_session()
                pr = _props()
                rc = api.StartTraceW(ctypes.byref(self.handle), SESSION, ctypes.byref(pr))
            if rc != 0:
                self.handle = TRACEHANDLE(0)
                self._fail("admin" if rc == ERROR_ACCESS_DENIED else "error", "StartTrace %d" % rc)
                return
            rc = self._enable(api, DXGI, DXGI_PRESENT)
            self._enable(api, D3D9, D3D9_PRESENT)
            if rc != 0:
                self._stop()
                self._fail("admin" if rc == ERROR_ACCESS_DENIED else "error", "EnableTraceEx2 %d" % rc)
                return
            lf = EVENT_TRACE_LOGFILEW()
            lf.LoggerName = SESSION
            lf.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD
            lf.EventRecordCallback = self._cb
            self._keep = [lf]  # ProcessTrace suresince canli kalmali
            consumer = api.OpenTraceW(ctypes.byref(lf))
            if consumer == INVALID_PROCESSTRACE_HANDLE:
                err = ctypes.get_last_error()
                self._stop()
                self._fail("error", "OpenTrace %d" % err)
                return
            self.consumer = consumer
            h = TRACEHANDLE(consumer)

            def pump():
                try:
                    api.ProcessTrace(ctypes.byref(h), 1, None, None)  # oturum durana dek doner
                except Exception:
                    pass
            self.thread = threading.Thread(target=pump, name="fps-etw", daemon=True)
            self.thread.start()
            self.state, self.error = "ok", ""
        except Exception as exc:
            self._fail("error", "%s: %s" % (type(exc).__name__, exc))

    def _fail(self, state, err):
        self.state, self.error = state, err
        self._retry_at = time.monotonic() + 30  # her yoklamada yeniden denenmesin

    def _stop(self):
        try:
            api = _api()
            if self.handle.value:
                pr = _props()
                api.ControlTraceW(self.handle, None, ctypes.byref(pr), EVENT_TRACE_CONTROL_STOP)
                self.handle = TRACEHANDLE(0)
            if self.consumer != INVALID_PROCESSTRACE_HANDLE:
                api.CloseTrace(self.consumer)
                self.consumer = INVALID_PROCESSTRACE_HANDLE
        except Exception:
            pass
        if self.thread is not None:
            self.thread.join(1.5)
        self.thread = None
        self.dxgi, self.d3d9 = {}, {}

    def shutdown(self):
        with self.lock:
            self._stop()
            self.state = "off"

    # -- okuma
    def read(self, pid=None):
        """On plandaki (ya da verilen) surecin FPS'i: (fps veya None, durum: ok|none|off|admin|error)."""
        if self.state != "ok":
            return None, self.state
        if pid is None:
            pid = foreground_pid()
        now = ctypes.c_int64()
        ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(now))
        f = self.freq.value
        val = None
        for book in (self.dxgi, self.d3d9):  # D3D9 olaylari yalnizca DXGI olayi yoksa (cift sayim olmasin)
            q = book.get(pid)
            if q:
                val = fps_from(_copy(q), f, now.value)
                if val:
                    break
        for book in (self.dxgi, self.d3d9):  # kapanmis sureclerin kuyruklari: bellek sinirli kalsin
            try:
                old = [k for k, q in list(book.items()) if not q or (now.value - q[-1]) / f > 10]
            except (RuntimeError, IndexError):  # ETW is parcacigi o an yaziyordu: bir sonraki okumada
                old = []
            for k in old:
                book.pop(k, None)
        return val, ("ok" if val else "none")


def _copy(q):
    """ETW is parcacigi eklerken kopya alinabilir; nadiren 'deque mutated' olursa yeniden dene."""
    for _ in range(3):
        try:
            return list(q)
        except RuntimeError:
            continue
    return []


def foreground_pid():
    u32 = ctypes.windll.user32
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value
