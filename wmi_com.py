# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Ek paket gerektirmeyen WMI istemcisi (COM, ctypes): sorgu ve yontem cagrisi.

Alienware arka ucu (alienware.py) gomulu denetleyiciye ACPI-WMI yontemleriyle (root\\WMI) ulasir. PowerShell
cagirmak her komutta ~0,3 sn ve bir surec demek; fan egrisi saniyede bir komut gonderdigi icin COM dogrudan
kullanilir. COM nesneleri olusturulduklari is parcacigina bagli oldugundan tum cagrilar TEK bir isci is
parcacigindan gecer (kuyruk); cagri takilirsa arayan zaman asimiyla doner, motor donmaz.
"""
import ctypes
import queue
import threading
from ctypes import wintypes as wt

c_void_p = ctypes.c_void_p
HRESULT = ctypes.c_long

VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_BSTR, VT_BOOL, VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_I8, VT_UI8, VT_INT, VT_UINT = \
    0, 1, 2, 3, 8, 11, 16, 17, 18, 19, 20, 21, 22, 23
VT_ARRAY = 0x2000
WBEM_FLAG_FORWARD_ONLY, WBEM_FLAG_RETURN_IMMEDIATELY = 0x20, 0x10


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("v", ctypes.c_ulonglong), ("v2", ctypes.c_ulonglong if ctypes.sizeof(c_void_p) == 8 else ctypes.c_ulong)]


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class WmiError(OSError):
    pass


_ole32 = ctypes.WinDLL("ole32")
_oleaut = ctypes.WinDLL("oleaut32")
_oleaut.SysAllocString.restype = c_void_p
_oleaut.SysAllocString.argtypes = [wt.LPCWSTR]
_oleaut.SysFreeString.argtypes = [c_void_p]
_oleaut.VariantClear.argtypes = [c_void_p]
_oleaut.SafeArrayGetLBound.argtypes = [c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
_oleaut.SafeArrayGetUBound.argtypes = [c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
_oleaut.SafeArrayAccessData.argtypes = [c_void_p, ctypes.POINTER(c_void_p)]
_oleaut.SafeArrayUnaccessData.argtypes = [c_void_p]
_ole32.CoInitializeEx.argtypes = [c_void_p, wt.DWORD]
_ole32.CoCreateInstance.argtypes = [c_void_p, c_void_p, wt.DWORD, c_void_p, c_void_p]
_ole32.CoInitializeSecurity.argtypes = [c_void_p, ctypes.c_long, c_void_p, c_void_p, wt.DWORD, wt.DWORD, c_void_p,
                                        wt.DWORD, c_void_p]
_ole32.CoSetProxyBlanket.argtypes = [c_void_p, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD]


def _guid(s):
    g = GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % s), ctypes.byref(g))
    return g


CLSID_WbemLocator = _guid("4590f811-1d3a-11d0-891f-00aa004b2e24")
IID_IWbemLocator = _guid("dc12a687-737f-11cf-884d-00aa004b2e24")


def _fn(ptr, index, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtbl[index])


def _release(ptr):
    if ptr:
        _fn(ptr, 2)(ptr)


def _check(hr, what):
    if hr < 0:
        raise WmiError("%s: 0x%08X" % (what, hr & 0xFFFFFFFF))


class _Bstr:
    def __init__(self, s):
        self.p = _oleaut.SysAllocString(s)

    def __del__(self):
        if self.p:
            _oleaut.SysFreeString(self.p)
            self.p = None


def _from_variant(v):
    vt = v.vt
    if vt in (VT_EMPTY, VT_NULL):
        return None
    if vt & VT_ARRAY:
        sa = c_void_p(v.v)
        lo, hi = ctypes.c_long(), ctypes.c_long()
        _oleaut.SafeArrayGetLBound(sa, 1, ctypes.byref(lo))
        _oleaut.SafeArrayGetUBound(sa, 1, ctypes.byref(hi))
        n = hi.value - lo.value + 1
        data = c_void_p()
        _oleaut.SafeArrayAccessData(sa, ctypes.byref(data))
        try:
            ct = {VT_UI1: ctypes.c_ubyte, VT_I1: ctypes.c_byte, VT_I2: ctypes.c_short, VT_UI2: ctypes.c_ushort,
                  VT_I4: ctypes.c_long, VT_UI4: ctypes.c_ulong}.get(vt & ~VT_ARRAY)
            return list((ct * n).from_address(data.value)) if ct and n > 0 else []
        finally:
            _oleaut.SafeArrayUnaccessData(sa)
    raw = v.v
    if vt == VT_BSTR:
        return ctypes.wstring_at(raw) if raw else ""
    if vt == VT_BOOL:
        return (raw & 0xFFFF) != 0
    if vt == VT_I1:
        return ctypes.c_byte(raw & 0xFF).value
    if vt == VT_UI1:
        return raw & 0xFF
    if vt == VT_I2:
        return ctypes.c_short(raw & 0xFFFF).value
    if vt == VT_UI2:
        return raw & 0xFFFF
    if vt in (VT_I4, VT_INT):
        return ctypes.c_long(raw & 0xFFFFFFFF).value
    if vt in (VT_UI4, VT_UINT):
        return raw & 0xFFFFFFFF
    if vt == VT_I8:
        return ctypes.c_longlong(raw).value
    if vt == VT_UI8:
        return raw
    raise WmiError("desteklenmeyen VARIANT turu %d" % vt)


def _get(obj, name):
    v = VARIANT()
    _check(_fn(obj, 4, wt.LPCWSTR, ctypes.c_long, c_void_p, c_void_p, c_void_p)(obj, name, 0, ctypes.byref(v),
                                                                              None, None), "Get " + name)
    try:
        return _from_variant(v)
    finally:
        _oleaut.VariantClear(ctypes.byref(v))


def _put(obj, name, value):
    v = VARIANT()
    keep = None
    if isinstance(value, str):
        keep = _Bstr(value)
        v.vt, v.v = VT_BSTR, keep.p
    else:
        v.vt = VT_I4  # WMI uint32 parametreleri VT_I4 ile verilir
        v.v = int(value) & 0xFFFFFFFF
    _check(_fn(obj, 5, wt.LPCWSTR, ctypes.c_long, c_void_p, ctypes.c_long)(obj, name, 0, ctypes.byref(v), 0),
           "Put " + name)
    del keep  # Put degeri kopyalar


class _Connection:
    """Isci is parcaciginda yasayan COM baglantisi."""

    def __init__(self, namespace):
        _ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        # Surec capinda bir kez; baska bir modul once cagirdiysa RPC_E_TOO_LATE doner, CoSetProxyBlanket yeter
        _ole32.CoInitializeSecurity(None, -1, None, None, 0, 3, None, 0, None)
        loc = c_void_p()
        _check(_ole32.CoCreateInstance(ctypes.byref(CLSID_WbemLocator), None, 1, ctypes.byref(IID_IWbemLocator),
                                       ctypes.byref(loc)), "WbemLocator")
        self.svc = c_void_p()
        try:
            ns = _Bstr(namespace)
            hr = _fn(loc, 3, c_void_p, c_void_p, c_void_p, c_void_p, ctypes.c_long, c_void_p, c_void_p, c_void_p)(
                loc, ns.p, None, None, None, 0, None, None, ctypes.byref(self.svc))
            _check(hr, "ConnectServer " + namespace)
        finally:
            _release(loc)
        # RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE, RPC_C_AUTHN_LEVEL_CALL, RPC_C_IMP_LEVEL_IMPERSONATE, EOAC_NONE
        _ole32.CoSetProxyBlanket(self.svc, 10, 0, None, 3, 3, None, 0)
        self._sigs = {}

    def close(self):
        for in_sig in self._sigs.values():
            _release(in_sig)
        self._sigs.clear()
        _release(self.svc)
        self.svc = c_void_p()

    def query(self, wql, props):
        """[{ozellik: deger}] ; props None ise yalnizca __PATH."""
        en = c_void_p()
        lang, q = _Bstr("WQL"), _Bstr(wql)
        _check(_fn(self.svc, 20, c_void_p, c_void_p, ctypes.c_long, c_void_p, c_void_p)(
            self.svc, lang.p, q.p, WBEM_FLAG_FORWARD_ONLY | WBEM_FLAG_RETURN_IMMEDIATELY, None, ctypes.byref(en)),
            "ExecQuery")
        out = []
        try:
            nxt = _fn(en, 4, ctypes.c_long, ctypes.c_ulong, c_void_p, ctypes.POINTER(ctypes.c_ulong))
            while True:
                obj, got = c_void_p(), ctypes.c_ulong()
                hr = nxt(en, 5000, 1, ctypes.byref(obj), ctypes.byref(got))
                _check(hr, "Next")
                if not got.value:
                    break
                try:
                    out.append({p: _get(obj, p) for p in (props or ["__PATH"])})
                finally:
                    _release(obj)
        finally:
            _release(en)
        return out

    def methods(self, cls):
        """Sinifin yontem adlari (tani icin)."""
        klass = c_void_p()
        name = _Bstr(cls)
        _check(_fn(self.svc, 6, c_void_p, ctypes.c_long, c_void_p, c_void_p, c_void_p)(
            self.svc, name.p, 0, None, ctypes.byref(klass), None), "GetObject " + cls)
        out = []
        try:
            _check(_fn(klass, 22, ctypes.c_long)(klass, 0), "BeginMethodEnumeration")
            nxt = _fn(klass, 23, ctypes.c_long, c_void_p, c_void_p, c_void_p)
            while True:
                b, a, o = c_void_p(), c_void_p(), c_void_p()
                if nxt(klass, 0, ctypes.byref(b), ctypes.byref(a), ctypes.byref(o)) != 0:
                    break
                out.append(ctypes.wstring_at(b.value))
                _oleaut.SysFreeString(b)
                _release(a)
                _release(o)
            _fn(klass, 24)(klass)
        finally:
            _release(klass)
        return out

    def _in_sig(self, cls, method):
        key = (cls, method)
        if key not in self._sigs:
            klass = c_void_p()
            name = _Bstr(cls)
            _check(_fn(self.svc, 6, c_void_p, ctypes.c_long, c_void_p, c_void_p, c_void_p)(
                self.svc, name.p, 0, None, ctypes.byref(klass), None), "GetObject " + cls)
            try:
                in_sig, out_sig = c_void_p(), c_void_p()
                _check(_fn(klass, 19, wt.LPCWSTR, ctypes.c_long, c_void_p, c_void_p)(
                    klass, method, 0, ctypes.byref(in_sig), ctypes.byref(out_sig)), "GetMethod " + method)
                _release(out_sig)
            finally:
                _release(klass)
            self._sigs[key] = in_sig
        return self._sigs[key]

    def call(self, path, cls, method, args, out_name):
        """path: ornek yolu (__PATH) ya da statik yontem icin sinif adi; args: {ad: tamsayi}.
        Donus: out_name cikis parametresinin degeri."""
        in_sig = self._in_sig(cls, method)
        inst = c_void_p()
        if in_sig:
            _check(_fn(in_sig, 15, ctypes.c_long, c_void_p)(in_sig, 0, ctypes.byref(inst)), "SpawnInstance")
        try:
            for k, v in args.items():
                _put(inst, k, v)
            out = c_void_p()
            p, m = _Bstr(path), _Bstr(method)
            _check(_fn(self.svc, 24, c_void_p, c_void_p, ctypes.c_long, c_void_p, c_void_p, c_void_p, c_void_p)(
                self.svc, p.p, m.p, 0, None, inst, ctypes.byref(out), None), "ExecMethod " + method)
            try:
                return _get(out, out_name) if out and out_name else None
            finally:
                _release(out)
        finally:
            _release(inst)


class Wmi:
    """Tek isci is parcacikli WMI istemcisi. Tum yontemler is parcacigi guvenlidir."""

    def __init__(self, namespace=r"root\WMI", timeout=6.0):
        self.namespace = namespace
        self.timeout = timeout
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._err = None
        self._t = threading.Thread(target=self._run, name="wmi", daemon=True)
        self._t.start()
        if not self._ready.wait(timeout):
            raise WmiError("WMI baglantisi zaman asimi")
        if self._err:
            raise self._err

    def _run(self):
        try:
            conn = _Connection(self.namespace)
        except Exception as exc:
            self._err = exc if isinstance(exc, WmiError) else WmiError(str(exc))
            self._ready.set()
            return
        self._ready.set()
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, args, box, done = item
            try:
                box.append((True, getattr(conn, fn)(*args)))
            except Exception as exc:
                box.append((False, exc))
            done.set()
        conn.close()

    def _do(self, fn, *args):
        box, done = [], threading.Event()
        self._q.put((fn, args, box, done))
        if not done.wait(self.timeout):
            raise WmiError("WMI cagrisi zaman asimi: %s" % fn)
        ok, val = box[0]
        if not ok:
            raise val
        return val

    def query(self, wql, props=None):
        return self._do("query", wql, props)

    def methods(self, cls):
        return self._do("methods", cls)

    def call(self, path, cls, method, args, out_name):
        return self._do("call", path, cls, method, args, out_name)

    def close(self):
        self._q.put(None)
