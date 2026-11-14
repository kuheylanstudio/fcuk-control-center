# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""WMI yontem cagrilari (IWbemServices::ExecMethod), ek paket olmadan ctypes ve COM ile.

Uretici ACPI-WMI arayuzleri (ornegin Gigabyte GB_WMIACPI_Get / GB_WMIACPI_Set) her olcumde cagrilir;
her seferinde PowerShell baslatmak saniyede bir icin cok yavas. Tum COM isi TEK bir is parcaciginda
yapilir (baglanti o parcacigin dairesine aittir); diger parcaciklar istegi kuyruga birakip sonucu bekler.
Bir ACPI yontemi takilirsa cagiran zaman asimiyla doner, motor kilitlenmez.
"""
import ctypes
import queue
import threading
from ctypes import wintypes as wt

c_void_p = ctypes.c_void_p

CLSID_WbemLocator = "4590f811-1d3a-11d0-891f-00aa004b2e24"
IID_IWbemLocator = "dc12a687-737f-11cf-884d-00aa004b2e24"

VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_BSTR, VT_BOOL, VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_I8, VT_UI8, VT_INT, VT_UINT = \
    0, 1, 2, 3, 8, 11, 16, 17, 18, 19, 20, 21, 22, 23
WBEM_E_NOT_FOUND = 0x80041002
WBEM_E_INVALID_CLASS = 0x80041010
WBEM_E_INVALID_METHOD = 0x8004102E
E_NOINTERFACE = 0x80004002


class WmiError(OSError):
    """WMI cagrisi basarisiz (HRESULT ile)."""

    def __init__(self, what, hr):
        self.hr = hr & 0xFFFFFFFF
        super().__init__("%s: HRESULT 0x%08X" % (what, self.hr))


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % s), ctypes.byref(g))
    return g


class _VarUnion(ctypes.Union):
    _fields_ = [("llVal", ctypes.c_longlong), ("lVal", ctypes.c_long), ("bVal", ctypes.c_ubyte),
                ("iVal", ctypes.c_short), ("ptr", c_void_p), ("pad", ctypes.c_ubyte * 16)]


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("u", _VarUnion)]


def _vcall(ptr, index, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtbl[index])


def _release(p):
    if p:
        try:
            vtbl = ctypes.cast(p, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])(p)
        except OSError:
            pass


class _Bstr:
    """SysAllocString ile ayrilan BSTR; with blogundan cikinca serbest."""

    def __init__(self, s):
        o = ctypes.windll.oleaut32
        o.SysAllocString.restype = c_void_p
        o.SysAllocString.argtypes = [wt.LPCWSTR]
        o.SysFreeString.argtypes = [c_void_p]
        self.o = o
        self.p = o.SysAllocString(s)

    def __enter__(self):
        return self.p

    def __exit__(self, *a):
        self.o.SysFreeString(self.p)


def _variant_value(v):
    vt = v.vt
    if vt in (VT_EMPTY, VT_NULL):
        return None
    if vt in (VT_I4, VT_INT):
        return v.u.lVal
    if vt in (VT_UI4, VT_UINT):
        return v.u.lVal & 0xFFFFFFFF
    if vt == VT_I2:
        return v.u.iVal
    if vt == VT_UI2:
        return v.u.iVal & 0xFFFF
    if vt in (VT_UI1, VT_I1):
        return v.u.bVal
    if vt == VT_BOOL:
        return v.u.iVal != 0
    if vt in (VT_I8, VT_UI8):
        return v.u.llVal
    if vt == VT_BSTR:
        return ctypes.wstring_at(v.u.ptr) if v.u.ptr else ""
    return None  # diziler ve nesneler: bu modulde gerekmiyor


# IWbemServices / IWbemClassObject / IEnumWbemClassObject sanal tablo sirasi (wbemcli.h)
_SVC_GETOBJECT, _SVC_CREATEINSTANCEENUM, _SVC_EXECMETHOD = 6, 18, 24
_OBJ_GET, _OBJ_PUT, _OBJ_SPAWNINSTANCE, _OBJ_GETMETHOD = 4, 5, 15, 19
_ENUM_NEXT = 4


class ComWmi:
    """Tek is parcacikli WMI istemcisi. call(), instances() ve has_class() herhangi bir parcaciktan cagrilabilir."""

    def __init__(self, namespace="root\\WMI", timeout=6.0):
        self.namespace = namespace
        self.timeout = timeout
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._error = None
        self._dead = False
        self.svc = c_void_p()
        self._t = threading.Thread(target=self._worker, name="wmi-" + namespace, daemon=True)
        self._t.start()
        if not self._ready.wait(timeout):
            self._dead = True
            raise WmiError("WMI baglantisi zaman asimi", 0x800705B4)
        if self._error is not None:
            self._dead = True
            raise self._error

    # ------------------------------------------------------------------ disaridan
    def _submit(self, fn, *args):
        if self._dead:
            raise WmiError("WMI is parcacigi durdu", 0x8000FFFF)
        box = {}
        done = threading.Event()
        self._q.put((fn, args, box, done))
        if not done.wait(self.timeout):
            # Takilan ACPI yontemi: bu istemci bundan sonra kullanilmaz (sira bozuldu)
            self._dead = True
            raise WmiError("WMI cagrisi zaman asimi", 0x800705B4)
        if "err" in box:
            raise box["err"]
        return box.get("ok")

    def has_class(self, cls):
        return self._submit(self._has_class, cls)

    def has_method(self, cls, method):
        """Sinifin MOF'unda bu yontem var mi? Yontem CALISTIRILMAZ, yalnizca imzasi okunur."""
        return self._submit(self._has_method, cls, method)

    def instances(self, cls):
        """Sinifin ornekleri: [{"InstanceName": ..., "Active": ...}]."""
        return self._submit(self._instances, cls)

    def call(self, path, method, inargs=None, outnames=None):
        """path: 'Sinif.InstanceName="..."' bicimli nesne yolu. inargs: {ad: tamsayi}. Donus {cikis adi: deger}."""
        return self._submit(self._call, path, method, dict(inargs or {}), tuple(outnames or ()))

    def close(self):
        if not self._dead:
            self._dead = True
            self._q.put(None)

    # ------------------------------------------------------------------ is parcacigi
    def _worker(self):
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        try:
            self._connect()
        except Exception as exc:
            self._error = exc if isinstance(exc, OSError) else WmiError(str(exc), 0x80004005)
            self._ready.set()
            return
        self._ready.set()
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, args, box, done = item
            try:
                box["ok"] = fn(*args)
            except Exception as exc:
                box["err"] = exc
            done.set()
        _release(self.svc)

    def _connect(self):
        ole = ctypes.windll.ole32
        ole.CoCreateInstance.argtypes = [c_void_p, c_void_p, ctypes.c_ulong, c_void_p, c_void_p]
        loc = c_void_p()
        hr = ole.CoCreateInstance(ctypes.byref(_guid(CLSID_WbemLocator)), None, 1,  # CLSCTX_INPROC_SERVER
                                  ctypes.byref(_guid(IID_IWbemLocator)), ctypes.byref(loc))
        if hr != 0:
            raise WmiError("WbemLocator", hr)
        try:
            with _Bstr(self.namespace) as ns:
                hr = _vcall(loc, 3, c_void_p, c_void_p, c_void_p, c_void_p, ctypes.c_long, c_void_p, c_void_p,
                            c_void_p)(loc, ns, None, None, None, 0, None, None, ctypes.byref(self.svc))
            if hr != 0:
                raise WmiError("ConnectServer " + self.namespace, hr)
        finally:
            _release(loc)
        ole.CoSetProxyBlanket.argtypes = [c_void_p, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p,
                                          wt.DWORD]
        ole.CoSetProxyBlanket.restype = ctypes.c_long
        # RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE, RPC_C_AUTHN_LEVEL_CALL, RPC_C_IMP_LEVEL_IMPERSONATE, EOAC_NONE
        hr = ole.CoSetProxyBlanket(self.svc, 10, 0, None, 3, 3, None, 0) & 0xFFFFFFFF
        if hr not in (0, E_NOINTERFACE):  # E_NOINTERFACE: vekil yok (ayni surec)
            raise WmiError("CoSetProxyBlanket", hr)

    def _get_object(self, path):
        obj = c_void_p()
        with _Bstr(path) as b:
            hr = _vcall(self.svc, _SVC_GETOBJECT, c_void_p, ctypes.c_long, c_void_p, c_void_p, c_void_p)(
                self.svc, b, 0, None, ctypes.byref(obj), None)
        if hr != 0:
            raise WmiError("GetObject " + path, hr)
        return obj

    def _has_class(self, cls):
        try:
            _release(self._get_object(cls))
            return True
        except WmiError as exc:
            if exc.hr in (WBEM_E_NOT_FOUND, WBEM_E_INVALID_CLASS):
                return False
            raise

    def _has_method(self, cls, method):
        clsobj = self._get_object(cls)
        insig, outsig = c_void_p(), c_void_p()
        try:
            hr = _vcall(clsobj, _OBJ_GETMETHOD, wt.LPCWSTR, ctypes.c_long, c_void_p, c_void_p)(
                clsobj, method, 0, ctypes.byref(insig), ctypes.byref(outsig))
            if hr == 0:
                return True
            if hr & 0xFFFFFFFF == WBEM_E_NOT_FOUND:
                return False
            raise WmiError("GetMethod %s.%s" % (cls, method), hr)
        finally:
            for p in (outsig, insig, clsobj):
                _release(p)

    @staticmethod
    def _prop(obj, name):
        v = VARIANT()
        hr = _vcall(obj, _OBJ_GET, wt.LPCWSTR, ctypes.c_long, c_void_p, c_void_p, c_void_p)(
            obj, name, 0, ctypes.byref(v), None, None)
        if hr != 0:
            raise WmiError("Get " + name, hr)
        try:
            return _variant_value(v)
        finally:
            ctypes.windll.oleaut32.VariantClear(ctypes.byref(v))

    def _instances(self, cls):
        en = c_void_p()
        with _Bstr(cls) as b:
            hr = _vcall(self.svc, _SVC_CREATEINSTANCEENUM, c_void_p, ctypes.c_long, c_void_p, c_void_p)(
                self.svc, b, 0x20 | 0x10, None, ctypes.byref(en))  # FORWARD_ONLY | RETURN_IMMEDIATELY
        if hr != 0:
            raise WmiError("CreateInstanceEnum " + cls, hr)
        out = []
        try:
            for _ in range(64):
                obj, n = c_void_p(), ctypes.c_ulong(0)
                hr = _vcall(en, _ENUM_NEXT, ctypes.c_long, ctypes.c_ulong, c_void_p, c_void_p)(
                    en, 5000, 1, ctypes.byref(obj), ctypes.byref(n))
                if n.value == 0:
                    break
                try:
                    item = {}
                    for name in ("InstanceName", "Active"):
                        try:
                            item[name] = self._prop(obj, name)
                        except WmiError:
                            pass
                    out.append(item)
                finally:
                    _release(obj)
                if hr != 0:
                    break
        finally:
            _release(en)
        return out

    def _call(self, path, method, inargs, outnames):
        cls = path.split(".", 1)[0]
        clsobj = self._get_object(cls)
        insig, inst, outp = c_void_p(), c_void_p(), c_void_p()
        try:
            hr = _vcall(clsobj, _OBJ_GETMETHOD, wt.LPCWSTR, ctypes.c_long, c_void_p, c_void_p)(
                clsobj, method, 0, ctypes.byref(insig), None)
            if hr != 0:
                raise WmiError("GetMethod %s.%s" % (cls, method), hr)
            if inargs:
                if not insig:
                    raise WmiError("%s.%s giris parametresi almiyor" % (cls, method), WBEM_E_INVALID_METHOD)
                hr = _vcall(insig, _OBJ_SPAWNINSTANCE, ctypes.c_long, c_void_p)(insig, 0, ctypes.byref(inst))
                if hr != 0:
                    raise WmiError("SpawnInstance", hr)
                for name, value in inargs.items():
                    v = VARIANT()
                    v.vt = VT_I4
                    v.u.lVal = int(value)
                    hr = _vcall(inst, _OBJ_PUT, wt.LPCWSTR, ctypes.c_long, c_void_p, ctypes.c_long)(
                        inst, name, 0, ctypes.byref(v), 0)
                    if hr != 0:
                        raise WmiError("Put %s" % name, hr)
            with _Bstr(path) as bp, _Bstr(method) as bm:
                hr = _vcall(self.svc, _SVC_EXECMETHOD, c_void_p, c_void_p, ctypes.c_long, c_void_p, c_void_p,
                            c_void_p, c_void_p)(self.svc, bp, bm, 0, None, inst if inst else None,
                                                ctypes.byref(outp), None)
            if hr != 0:
                raise WmiError("ExecMethod %s.%s" % (cls, method), hr)
            out = {}
            if outp:
                for name in outnames:
                    out[name] = self._prop(outp, name)
            return out
        finally:
            for p in (outp, inst, insig, clsobj):
                _release(p)
