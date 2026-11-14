"""Windows 原生文件对话框（ctypes + comdlg32），无依赖、无需 tkinter."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":  # pragma: no cover - 仅 Windows
    from ctypes import wintypes
else:  # 供非 Windows 环境导入时不报错
    wintypes = None


class _OpenFileName(ctypes.Structure):
    _fields_ = [
        ("lStructSize", ctypes.c_uint),
        ("hwndOwner", ctypes.c_void_p),
        ("hInstance", ctypes.c_void_p),
        ("lpstrFilter", ctypes.c_wchar_p),
        ("lpstrCustomFilter", ctypes.c_wchar_p),
        ("nMaxCustFilter", ctypes.c_uint),
        ("nFilterIndex", ctypes.c_uint),
        ("lpstrFile", ctypes.c_wchar_p),
        ("nMaxFile", ctypes.c_uint),
        ("lpstrFileTitle", ctypes.c_wchar_p),
        ("nMaxFileTitle", ctypes.c_uint),
        ("lpstrInitialDir", ctypes.c_wchar_p),
        ("lpstrTitle", ctypes.c_wchar_p),
        ("Flags", ctypes.c_uint),
        ("nFileOffset", ctypes.c_short),
        ("nFileExtension", ctypes.c_short),
        ("lpstrDefExt", ctypes.c_wchar_p),
        ("lCustData", ctypes.c_void_p),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", ctypes.c_wchar_p),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", ctypes.c_uint),
        ("FlagsEx", ctypes.c_uint),
    ]


OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_OVERWRITEPROMPT = 0x00000002
OFN_NOCHANGEDIR = 0x00000008

FILTER_JSON = "JSON 映射方案 (*.json)\0*.json\0所有文件 (*.*)\0*.*\0\0"
FILTER_CSV = "CSV 表格 (*.csv)\0*.csv\0所有文件 (*.*)\0*.*\0\0"


def _parse_filter(filter_string: str, title: str, default_name: str = "",
                  flags: int = 0, default_ext: str = "json") -> Optional[str]:
    if sys.platform != "win32":
        return None
    buffer = ctypes.create_unicode_buffer(1024)
    if default_name:
        buffer.value = default_name
    info = _OpenFileName()
    info.lStructSize = ctypes.sizeof(_OpenFileName)
    info.hwndOwner = ctypes.windll.user32.GetActiveWindow()
    info.lpstrFilter = filter_string
    info.lpstrFile = ctypes.cast(buffer, ctypes.c_wchar_p)
    info.nMaxFile = 1024
    info.lpstrTitle = title
    info.Flags = OFN_NOCHANGEDIR | flags
    info.lpstrDefExt = default_ext
    ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(info))
    if not ok:
        return None
    return buffer.value or None


def open_json(title: str = "选择映射方案", initial_dir: Optional[Path] = None) -> Optional[Path]:
    path = _parse_filter(FILTER_JSON, title, "", OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST)
    return Path(path) if path else None


def save_json(default_name: str, title: str = "保存映射方案") -> Optional[Path]:
    path = _parse_filter(FILTER_JSON, title, default_name, OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST)
    if not path:
        return None
    result = Path(path)
    if result.suffix.lower() != ".json":
        result = result.with_suffix(".json")
    return result


def save_csv(default_name: str, title: str = "导出 CSV") -> Optional[Path]:
    path = _parse_filter(FILTER_CSV, title, default_name,
                         OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST, "csv")
    if not path:
        return None
    result = Path(path)
    if result.suffix.lower() != ".csv":
        result = result.with_suffix(".csv")
    return result
