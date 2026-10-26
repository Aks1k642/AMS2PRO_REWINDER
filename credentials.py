"""Windows-only DPAPI vault: local LAN access codes keyed by Bambu printer serial.

Never put credentials into browser storage, logs, or API responses. On Linux/macOS,
no persistent vault is offered rather than falling back to plaintext encryption.
"""
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import tempfile

SERIAL = re.compile(r"[A-Za-z0-9]{6,40}\Z")


def _validate(serial):
    if not isinstance(serial, str) or not SERIAL.fullmatch(serial):
        raise ValueError("Некорректный серийный номер принтера")
    return serial


def vault_path():
    if os.name != "nt":
        return None
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        return None
    return Path(root) / "AMS2ProRewinder" / "credentials.json"


def _protect(data, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("Шифрованное хранение кодов доступно только на Windows")
    from ctypes import wintypes
    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    src_buffer = ctypes.create_string_buffer(data)
    src = BLOB(len(data), ctypes.cast(src_buffer, ctypes.POINTER(ctypes.c_byte)))
    dst = BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if decrypt:
        operation = crypt32.CryptUnprotectData
    else:
        operation = crypt32.CryptProtectData
    operation.restype = wintypes.BOOL
    if decrypt:
        operation.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        success = operation(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst))
    else:
        operation.argtypes = [ctypes.POINTER(BLOB), ctypes.c_wchar_p, ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        success = operation(ctypes.byref(src), "AMS2ProRewinder", None, None, None, 1, ctypes.byref(dst))
    if not success:
        raise RuntimeError("Windows не разрешила доступ к защищённому коду")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(dst.pbData, ctypes.c_void_p))


class CredentialVault:
    def __init__(self, path=None):
        self.path = vault_path() if path is None else Path(path)

    @property
    def available(self):
        return self.path is not None and os.name == "nt"

    def _read(self):
        if self.path is None or not self.path.exists():
            return {}
        try:
            contents = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(contents, dict):
                return {}
            return {k: v for k, v in contents.items() if isinstance(k, str) and isinstance(v, str)}
        except (ValueError, OSError):
            return {}

    def saved(self, serial):
        return bool(self.available and _validate(serial) in self._read())

    def get(self, serial):
        _validate(serial)
        if not self.available:
            return None
        blob = self._read().get(serial)
        if not blob:
            return None
        try:
            return _protect(base64.b64decode(blob, validate=True), decrypt=True).decode("utf-8")
        except (ValueError, UnicodeError, RuntimeError):
            return None

    def put(self, serial, code):
        _validate(serial)
        if not self.available:
            raise RuntimeError("Сохранение кода доступно только в Windows-сборке")
        if not isinstance(code, str) or not (4 <= len(code) <= 64):
            raise ValueError("Некорректный LAN Access Code")
        records = self._read()
        records[serial] = base64.b64encode(_protect(code.encode("utf-8"))).decode("ascii")
        self._write(records)

    def delete(self, serial):
        _validate(serial)
        records = self._read()
        if serial in records:
            del records[serial]
            self._write(records)

    def _write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="credentials-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=True, sort_keys=True)
            os.replace(name, self.path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
