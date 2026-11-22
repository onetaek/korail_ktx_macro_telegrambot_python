"""Optional local persistence for non-secret GUI preferences."""

import json
import base64
import ctypes
import sys
from pathlib import Path


class GuiPreferences:
    """Read and write optional preferences beside the user's application data."""

    def __init__(self, path: Path | None = None):
        self.path = path or (Path.home() / "AppData" / "Local" / "KorailReservationGui" / "preferences.json")

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        return self._decode(data) if isinstance(data, dict) else {}

    def save_section(self, section: str, values: dict) -> None:
        data = self.load()
        data[section] = self._encode(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @classmethod
    def _encode(cls, value):
        if isinstance(value, dict):
            return {key: cls._encode(item) for key, item in value.items()}
        if isinstance(value, str) and value.startswith("secret:"):
            return {"__protected__": base64.b64encode(cls._protect(value[7:].encode("utf-8"))).decode("ascii")}
        return value

    @classmethod
    def _decode(cls, value):
        if isinstance(value, dict) and set(value) == {"__protected__"}:
            try:
                encrypted = base64.b64decode(value["__protected__"], validate=True)
                return cls._unprotect(encrypted).decode("utf-8")
            except (ValueError, OSError, UnicodeDecodeError):
                return ""
        if isinstance(value, dict):
            return {key: cls._decode(item) for key, item in value.items()}
        return value

    @staticmethod
    def _crypt(data: bytes, *, decrypt: bool) -> bytes:
        if sys.platform != "win32":
            raise OSError("민감한 GUI 설정 보호는 Windows에서만 지원됩니다.")

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        source_buffer = ctypes.create_string_buffer(data)
        source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        destination = DataBlob()
        crypt = ctypes.windll.crypt32
        kernel = ctypes.windll.kernel32
        crypt.CryptProtectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_wchar_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.POINTER(DataBlob)]
        crypt.CryptProtectData.restype = ctypes.c_int
        crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
                                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_uint32, ctypes.POINTER(DataBlob)]
        crypt.CryptUnprotectData.restype = ctypes.c_int
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if decrypt:
            ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination))
        else:
            ok = crypt.CryptProtectData(ctypes.byref(source), "Korail Reservation GUI", None, None, None, 1, ctypes.byref(destination))
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel.LocalFree(destination.pbData)

    @classmethod
    def _protect(cls, data: bytes) -> bytes:
        return cls._crypt(data, decrypt=False)

    @classmethod
    def _unprotect(cls, data: bytes) -> bytes:
        return cls._crypt(data, decrypt=True)
