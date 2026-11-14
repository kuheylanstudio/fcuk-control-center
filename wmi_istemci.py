# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Kucuk bir WMI istemcisi (yalnizca ctypes + COM; pywin32/comtypes gerekmez).

Ureticilerin oyun dizustu arayuzleri (ornek: Acer 'AcerGamingFunction', root\\wmi) WMI yontemi olarak
sunulur. PowerShell ile her cagri bir surec demek (klavye isigi saniyede birkac kez cagirir); bu yuzden
WMI'ya surec icinden baglanilir.

Tum COM nesneleri TEK bir is parcaciginda yasar (WmiClient._worker); diger is parcaciklari istegi kuyruga
koyar ve sonucu bekler. Boylece COM daire (apartment) kurallari, uygulamanin baska yerlerinde COM'u farkli
kipte acmis is parcaciklarindan etkilenmez ve cagrilar kendiliginden sirayla gider.

Yontem parametrelerinin CIM tipleri sinifin imzasindan okunur; boylece uint8 / uint32 / uint64 (WMI'da
metin olarak tasinir) ve uint8[] dizileri dogru VARIANT tipine cevrilir.
"""
import ctypes
import queue
import threading
from ctypes import wintypes as wt

c_void_p = ctypes.c_void_p
HRESULT = ctypes.c_long

# VARIANT tipleri
VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_BSTR, VT_BOOL, VT_UI1, VT_I1, VT_UI2, VT_UI4, VT_I8, VT_UI8 = \
    0, 1, 2, 3, 8, 11, 17, 16, 18, 19, 20, 21
VT_ARRAY = 0x2000
# CIM tipleri
CIM_SINT8, CIM_UINT8, CIM_SINT16, CIM_UINT16, CIM_SINT32, CIM_UINT32, CIM_SINT64, CIM_UINT64 = \
    16, 17, 2, 18, 3, 19, 20, 21
CIM_BOOLEAN, CIM_STRING = 11, 8
CIM_FLAG_ARRAY = 0x2000

WBEM_FLAG_RETURN_IMMEDIATELY = 0x10
WBEM_FLAG_FORWARD_ONLY = 0x20
WBEM_FLAG_NONSYSTEM_ONLY = 0x40
WBEM_S_FALSE = 1
WBEM_S_NO_MORE_DATA = 0x40005
WBEM_E_NOT_FOUND = -2147217406          # 0x80041002
WBEM_E_INVALID_CLASS = -2147217392      # 0x80041010

CLSID_WBEM_LOCATOR = "4590f811-1d3a-11d0-891f-00aa004b2e24"
IID_IWBEM_LOCATOR = "dc12a687-737f-11cf-884d-00aa004b2e24"


class WmiError(RuntimeError):
    def __init__(self, msg, hr=None):
        super().__init__(msg if hr is None else "%s (0x%08X)" % (msg, hr & 0xFFFFFFFF))
        self.hr = hr


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % s), ctypes.byref(g))
    return g


class _VarUnion(ctypes.Union):
    _fields_ = [("llVal", ctypes.c_longlong), ("lVal", ctypes.c_long), ("iVal", ctypes.c_short),
                ("bVal", ctypes.c_ubyte), ("boolVal", ctypes.c_short), ("ptr", c_void_p),
                ("pad", ctypes.c_byte * 16)]


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("u", _VarUnion)]


_oleaut = []


def _oa():
    if not _oleaut:
        o = ctypes.WinDLL("oleaut32")
        o.SysAllocString.argtypes = [wt.LPCWSTR]
        o.SysAllocString.restype = c_void_p
        o.SysFreeString.argtypes = [c_void_p]
        o.SysStringLen.argtypes = [c_void_p]
        o.SysStringLen.restype = ctypes.c_uint
        o.VariantClear.argtypes = [c_void_p]
        o.SafeArrayCreateVector.argtypes = [ctypes.c_ushort, ctypes.c_long, ctypes.c_ulong]
        o.SafeArrayCreateVector.restype = c_void_p
        o.SafeArrayAccessData.argtypes = [c_void_p, ctypes.POINTER(c_void_p)]
        o.SafeArrayUnaccessData.argtypes = [c_void_p]
        o.SafeArrayGetLBound.argtypes = [c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
        o.SafeArrayGetUBound.argtypes = [c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
        _oleaut.append(o)
    return _oleaut[0]


class _Bstr:
    """Kapsam boyunca yasayan BSTR (WMI bazi parametrelerde gercek BSTR uzunluk onekini okur)."""

    def __init__(self, s):
        self.p = _oa().SysAllocString(s) if s is not None else None

    def __enter__(self):
        return self.p

    def __exit__(self, *a):
        if self.p:
            _oa().SysFreeString(self.p)


def _call(ptr, index, *args):
    """COM arayuz yontemi: args = ((ctypes tipi, deger), ...). HRESULT dondurur."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(HRESULT, c_void_p, *[a[0] for a in args])(vtbl[index])
    return fn(ptr, *[a[1] for a in args])


def _release(ptr):
    if ptr:
        try:
            vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])(ptr)
        except OSError:
            pass


def _ok(hr, what):
    if hr < 0:
        raise WmiError(what, hr)
    return hr


# ----------------------------------------------------------------------------- VARIANT donusumleri
_ELEM = {VT_UI1: ctypes.c_ubyte, VT_I1: ctypes.c_byte, VT_I2: ctypes.c_short, VT_UI2: ctypes.c_ushort,
         VT_I4: ctypes.c_long, VT_UI4: ctypes.c_ulong, VT_I8: ctypes.c_longlong, VT_UI8: ctypes.c_ulonglong,
         VT_BOOL: ctypes.c_short}


def _bstr_text(p):
    if not p:
        return ""
    return ctypes.wstring_at(p, _oa().SysStringLen(p))


def _unsigned(x, base):
    if base == CIM_UINT32:
        return x & 0xFFFFFFFF
    if base == CIM_UINT16:
        return x & 0xFFFF
    return x


def _from_variant(v, cimtype=0):
    vt = v.vt
    base = cimtype & ~CIM_FLAG_ARRAY
    if vt in (VT_EMPTY, VT_NULL):
        return None
    if vt & VT_ARRAY:
        et = vt & ~VT_ARRAY
        psa = v.u.ptr
        if not psa:
            return []
        lo, hi = ctypes.c_long(), ctypes.c_long()
        _oa().SafeArrayGetLBound(psa, 1, ctypes.byref(lo))
        _oa().SafeArrayGetUBound(psa, 1, ctypes.byref(hi))
        n = max(0, hi.value - lo.value + 1)
        data = c_void_p()
        _ok(_oa().SafeArrayAccessData(psa, ctypes.byref(data)), "SafeArrayAccessData")
        try:
            if et == VT_BSTR:
                arr = ctypes.cast(data, ctypes.POINTER(c_void_p))
                out = [_bstr_text(arr[i]) for i in range(n)]
                return [int(x) for x in out] if base in (CIM_UINT64, CIM_SINT64) else out
            if et not in _ELEM:
                raise WmiError("desteklenmeyen dizi tipi %d" % et)
            arr = ctypes.cast(data, ctypes.POINTER(_ELEM[et]))
            out = [arr[i] for i in range(n)]
        finally:
            _oa().SafeArrayUnaccessData(psa)
        if et == VT_UI1:
            return bytes(out)
        return [_unsigned(x, base) for x in out]
    if vt == VT_BSTR:
        s = _bstr_text(v.u.ptr)
        return int(s) if base in (CIM_UINT64, CIM_SINT64) else s
    if vt == VT_BOOL:
        return v.u.boolVal != 0
    if vt == VT_UI1:
        return v.u.bVal
    if vt == VT_I2:
        return _unsigned(v.u.iVal, base)
    if vt == VT_I4:
        return _unsigned(v.u.lVal, base)
    if vt in (VT_I1, VT_UI2, VT_UI4, VT_I8, VT_UI8):
        return ctypes.cast(ctypes.byref(v.u), ctypes.POINTER(_ELEM[vt])).contents.value
    raise WmiError("desteklenmeyen VARIANT tipi %d" % vt)


def _to_variant(value, cimtype):
    """Python degeri -> VARIANT (WMI'nin CIM -> VARIANT eslemesine gore). Cagiran VariantClear yapar."""
    v = VARIANT()
    base = cimtype & ~CIM_FLAG_ARRAY
    if value is None:
        v.vt = VT_NULL
        return v
    if cimtype & CIM_FLAG_ARRAY:
        vals = [int(x) for x in value]
        if base == CIM_UINT8:
            et = VT_UI1
        elif base in (CIM_SINT8, CIM_SINT16):
            et = VT_I2
        elif base in (CIM_UINT16, CIM_UINT32, CIM_SINT32):
            et = VT_I4
        else:
            raise WmiError("desteklenmeyen dizi CIM tipi %d" % cimtype)
        psa = _oa().SafeArrayCreateVector(et, 0, len(vals))
        if not psa:
            raise WmiError("SafeArrayCreateVector")
        data = c_void_p()
        _ok(_oa().SafeArrayAccessData(psa, ctypes.byref(data)), "SafeArrayAccessData")
        try:
            arr = ctypes.cast(data, ctypes.POINTER(_ELEM[et]))
            for i, x in enumerate(vals):
                arr[i] = x - (1 << 32) if et == VT_I4 and x >= 1 << 31 else x
        finally:
            _oa().SafeArrayUnaccessData(psa)
        v.vt = VT_ARRAY | et
        v.u.ptr = psa
        return v
    if base in (CIM_UINT64, CIM_SINT64):
        v.vt, v.u.ptr = VT_BSTR, _oa().SysAllocString(str(int(value)))
    elif base == CIM_STRING:
        v.vt, v.u.ptr = VT_BSTR, _oa().SysAllocString(str(value))
    elif base == CIM_UINT8:
        v.vt, v.u.bVal = VT_UI1, int(value) & 0xFF
    elif base in (CIM_SINT8, CIM_SINT16):
        v.vt, v.u.iVal = VT_I2, int(value)
    elif base in (CIM_UINT16, CIM_UINT32, CIM_SINT32):
        x = int(value) & 0xFFFFFFFF
        v.vt, v.u.lVal = VT_I4, x - (1 << 32) if x >= 1 << 31 else x
    elif base == CIM_BOOLEAN:
        v.vt, v.u.boolVal = VT_BOOL, -1 if value else 0
    else:
        raise WmiError("desteklenmeyen CIM tipi %d" % cimtype)
    return v


# ----------------------------------------------------------------------------- IWbemClassObject
# vtable sirasi (wbemcli.h): 4 Get, 5 Put, 8 BeginEnumeration, 9 Next, 10 EndEnumeration, 15 SpawnInstance,
# 19 GetMethod
def _obj_props(obj):
    """Nesnenin (ya da yontem imzasinin) sistem disi ozellikleri: {ad: (deger, cimtipi)}."""
    out = {}
    _ok(_call(obj, 8, (ctypes.c_long, WBEM_FLAG_NONSYSTEM_ONLY)), "BeginEnumeration")
    try:
        while True:
            name, var, ctype = c_void_p(), VARIANT(), ctypes.c_long()
            hr = _call(obj, 9, (ctypes.c_long, 0), (c_void_p, ctypes.addressof(name)),
                       (c_void_p, ctypes.addressof(var)), (c_void_p, ctypes.addressof(ctype)), (c_void_p, None))
            if hr in (WBEM_S_NO_MORE_DATA, WBEM_S_FALSE):
                break
            _ok(hr, "IWbemClassObject.Next")
            try:
                out[_bstr_text(name.value)] = (_from_variant(var, ctype.value), ctype.value)
            finally:
                _oa().SysFreeString(name.value)
                _oa().VariantClear(ctypes.byref(var))
    finally:
        _call(obj, 10)
    return out


def _obj_get(obj, name):
    var, ctype = VARIANT(), ctypes.c_long()
    _ok(_call(obj, 4, (wt.LPCWSTR, name), (ctypes.c_long, 0), (c_void_p, ctypes.addressof(var)),
              (c_void_p, ctypes.addressof(ctype)), (c_void_p, None)), "Get " + name)
    try:
        return _from_variant(var, ctype.value)
    finally:
        _oa().VariantClear(ctypes.byref(var))


# ----------------------------------------------------------------------------- istemci
class WmiClient:
    """Bir WMI ad alanina bagli istemci. Tum cagrilar ozel is parcaciginda sirayla calisir."""
    TIMEOUT = 15.0

    def __init__(self, namespace):
        self.namespace = namespace
        self._q = queue.Queue()
        self._svc = None
        self._err = None
        self._methods = {}  # (sinif, yontem) -> giris imzasi (IWbemClassObject) ya da None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="wmi-" + namespace, daemon=True)
        self._thread.start()
        self._ready.wait(self.TIMEOUT)
        if self._err:
            raise self._err
        if self._svc is None:
            raise WmiError("WMI baglantisi zaman asimina ugradi: " + namespace)

    # ------------------------------------------------------------------ is parcacigi
    def _worker(self):
        ole = ctypes.windll.ole32
        ole.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        try:
            self._connect()
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
                box.append((True, fn(*args)))
            except Exception as exc:  # sonuc cagirana tasinir
                box.append((False, exc))
            done.set()
        for sig in self._methods.values():
            _release(sig)
        _release(self._svc)
        ole.CoUninitialize()

    def _connect(self):
        ole = ctypes.windll.ole32
        ole.CoCreateInstance.argtypes = [c_void_p, c_void_p, ctypes.c_ulong, c_void_p, c_void_p]
        loc = c_void_p()
        clsid, iid = _guid(CLSID_WBEM_LOCATOR), _guid(IID_IWBEM_LOCATOR)
        _ok(ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(loc)),
            "CoCreateInstance(WbemLocator)")
        try:
            svc = c_void_p()
            with _Bstr(self.namespace) as ns:
                # IWbemLocator::ConnectServer (3)
                _ok(_call(loc.value, 3, (c_void_p, ns), (c_void_p, None), (c_void_p, None), (c_void_p, None),
                          (ctypes.c_long, 0), (c_void_p, None), (c_void_p, None), (c_void_p, ctypes.addressof(svc))),
                    "ConnectServer " + self.namespace)
        finally:
            _release(loc.value)
        self._blanket(svc.value)
        self._svc = svc.value

    @staticmethod
    def _blanket(ptr):
        """Yerel WMI icin kimlik taklidi (impersonate) duzeyi: aksi halde yontem cagrilari erisim hatasi verir."""
        ole = ctypes.windll.ole32
        ole.CoSetProxyBlanket.argtypes = [c_void_p, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p,
                                          wt.DWORD]
        ole.CoSetProxyBlanket(ptr, 10, 0, None, 3, 3, None, 0)  # WINNT, NONE, CALL, IMPERSONATE

    def _run(self, fn, *args):
        if threading.current_thread() is self._thread:
            return fn(*args)
        if not self._thread.is_alive():
            raise WmiError("WMI istemcisi kapali")
        box, done = [], threading.Event()
        self._q.put((fn, args, box, done))
        if not done.wait(self.TIMEOUT):
            raise WmiError("WMI cagrisi zaman asimina ugradi")
        ok, val = box[0]
        if not ok:
            raise val
        return val

    def close(self):
        self._q.put(None)

    # ------------------------------------------------------------------ islemler (is parcaciginda)
    def _query(self, wql, props):
        enum = c_void_p()
        with _Bstr("WQL") as lang, _Bstr(wql) as q:
            # IWbemServices::ExecQuery (20)
            _ok(_call(self._svc, 20, (c_void_p, lang), (c_void_p, q),
                      (ctypes.c_long, WBEM_FLAG_FORWARD_ONLY | WBEM_FLAG_RETURN_IMMEDIATELY), (c_void_p, None),
                      (c_void_p, ctypes.addressof(enum))), "ExecQuery")
        rows = []
        try:
            self._blanket(enum.value)
            while True:
                obj, n = c_void_p(), ctypes.c_ulong()
                # IEnumWbemClassObject::Next (4)
                hr = _call(enum.value, 4, (ctypes.c_long, 10000), (ctypes.c_ulong, 1),
                           (c_void_p, ctypes.addressof(obj)), (c_void_p, ctypes.addressof(n)))
                if hr < 0:
                    raise WmiError("ExecQuery.Next", hr)
                if n.value == 0:
                    break
                try:
                    if props is None:
                        rows.append({k: v[0] for k, v in _obj_props(obj.value).items()})
                    else:
                        row = {}
                        for p in props:
                            try:
                                row[p] = _obj_get(obj.value, p)
                            except WmiError:
                                row[p] = None
                        rows.append(row)
                finally:
                    _release(obj.value)
        finally:
            _release(enum.value)
        return rows

    def _get_object(self, path):
        obj = c_void_p()
        with _Bstr(path) as p:
            hr = _call(self._svc, 6, (c_void_p, p), (ctypes.c_long, 0), (c_void_p, None),
                       (c_void_p, ctypes.addressof(obj)), (c_void_p, None))  # IWbemServices::GetObject (6)
        return hr, obj.value

    def _class_exists(self, cls):
        hr, obj = self._get_object(cls)
        _release(obj)
        if hr >= 0:
            return True
        if hr in (WBEM_E_NOT_FOUND, WBEM_E_INVALID_CLASS):
            return False
        raise WmiError("GetObject " + cls, hr)

    def _method_sig(self, cls, method):
        """Yontemin giris imzasi (IWbemClassObject) ya da None (parametresiz). Yontem yoksa WmiError."""
        key = (cls, method)
        if key in self._methods:
            return self._methods[key]
        hr, cobj = self._get_object(cls)
        _ok(hr, "GetObject " + cls)
        try:
            ins, outs = c_void_p(), c_void_p()
            hr = _call(cobj, 19, (wt.LPCWSTR, method), (ctypes.c_long, 0), (c_void_p, ctypes.addressof(ins)),
                       (c_void_p, ctypes.addressof(outs)))  # GetMethod (19)
            _ok(hr, "GetMethod %s.%s" % (cls, method))
            _release(outs.value)
        finally:
            _release(cobj)
        self._methods[key] = ins.value
        return ins.value

    def _has_method(self, cls, method):
        try:
            self._method_sig(cls, method)
            return True
        except WmiError:
            return False

    def _in_params(self, cls, method):
        sig = self._method_sig(cls, method)
        return {k: v[1] for k, v in _obj_props(sig).items()} if sig else {}

    def _exec(self, path, cls, method, args):
        sig = self._method_sig(cls, method)
        inst = c_void_p()
        if sig:
            _ok(_call(sig, 15, (ctypes.c_long, 0), (c_void_p, ctypes.addressof(inst))), "SpawnInstance")
        try:
            if inst.value:
                types = {k: v[1] for k, v in _obj_props(sig).items()}
                if not isinstance(args, dict):  # tek parametreli yontem: deger dogrudan verilebilir
                    if len(types) != 1:
                        raise WmiError("%s.%s %d parametre bekliyor" % (cls, method, len(types)))
                    args = {next(iter(types)): args}
                for name, val in args.items():
                    if name not in types:
                        raise WmiError("%s.%s: bilinmeyen parametre %s" % (cls, method, name))
                    var = _to_variant(val, types[name])
                    try:
                        _ok(_call(inst.value, 5, (wt.LPCWSTR, name), (ctypes.c_long, 0),
                                  (c_void_p, ctypes.addressof(var)), (ctypes.c_long, 0)), "Put " + name)
                    finally:
                        _oa().VariantClear(ctypes.byref(var))
            elif args:
                raise WmiError("%s.%s parametre almaz" % (cls, method))
            out = c_void_p()
            with _Bstr(path) as p, _Bstr(method) as m:
                # IWbemServices::ExecMethod (24)
                _ok(_call(self._svc, 24, (c_void_p, p), (c_void_p, m), (ctypes.c_long, 0), (c_void_p, None),
                          (c_void_p, inst.value), (c_void_p, ctypes.addressof(out)), (c_void_p, None)),
                    "ExecMethod %s.%s" % (cls, method))
            try:
                return {k: v[0] for k, v in _obj_props(out.value).items()} if out.value else {}
            finally:
                _release(out.value)
        finally:
            _release(inst.value)

    # ------------------------------------------------------------------ genel arayuz
    def query(self, wql, props=None):
        """[{ozellik: deger}]. props verilirse yalnizca onlar okunur (__PATH gibi sistem ozellikleri dahil)."""
        return self._run(self._query, wql, props)

    def class_exists(self, cls):
        return self._run(self._class_exists, cls)

    def has_method(self, cls, method):
        return self._run(self._has_method, cls, method)

    def in_params(self, cls, method):
        """Yontemin giris parametreleri: {ad: CIM tipi}."""
        return self._run(self._in_params, cls, method)

    def call(self, path, cls, method, args=None):
        """Yontemi cagirir. path: nesne yolu (ornegin __PATH ya da statik yontemde sinif adi).
        args: {parametre: deger} ya da tek parametreli yontemde yalnizca deger. Cikti: {ad: deger}."""
        return self._run(self._exec, path, cls, method, {} if args is None else args)
