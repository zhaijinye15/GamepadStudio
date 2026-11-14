"""向 SDL 查询每台手柄自己的按键/轴绑定.

pygame 只提供原始通道号（b0、a0…），而不同手柄——尤其是打着 Xbox 名号的
兼容手柄——原始序号排布并不一致。若按固定表翻译，就会出现"按 RB 却亮起
Xbox 键"这类错位。这里直接调用 SDL2 的 GameController 绑定接口，让 SDL
自己告诉我们：语义按键/轴 对应 哪个原始序号。
"""
from __future__ import annotations

import ctypes
import os
from typing import Dict, Optional, Tuple

#: SDL 语义按键顺序（SDL_GameControllerButton 枚举）
BUTTON_ORDER: Tuple[str, ...] = (
    "a", "b", "x", "y", "back", "guide", "start", "l3", "r3", "lb", "rb",
    "up", "down", "left", "right", "misc1", "paddle1", "paddle2", "paddle3",
    "paddle4", "touchpad",
)

#: SDL 语义轴顺序（SDL_GameControllerAxis 枚举）
AXIS_ORDER: Tuple[str, ...] = ("lx", "ly", "rx", "ry", "lt", "rt")

_SDL_INIT_JOYSTICK = 0x00000200
_SDL_INIT_GAMECONTROLLER = 0x00002000
_BIND_NONE = 0
_BIND_BUTTON = 1
_BIND_AXIS = 2
_BIND_HAT = 3


class _AxisStruct(ctypes.Structure):
    _fields_ = [("axis", ctypes.c_int), ("axis_min", ctypes.c_int), ("axis_max", ctypes.c_int)]


class _HatStruct(ctypes.Structure):
    _fields_ = [("hat", ctypes.c_int), ("hat_mask", ctypes.c_int)]


class _ValueStruct(ctypes.Union):
    _fields_ = [("button", ctypes.c_int), ("axis", _AxisStruct), ("hat", _HatStruct)]


class _BindStruct(ctypes.Structure):
    _fields_ = [("bind_type", ctypes.c_int), ("value", _ValueStruct)]


_lib = None
_lib_ready = False
_cache: Dict[Tuple[int, str], Tuple[Dict[str, int], Dict[str, int]]] = {}


def _candidate_paths() -> Tuple[str, ...]:
    paths = []
    try:
        import pygame

        base = os.path.dirname(pygame.__file__)
        for name in ("SDL2.dll", "libSDL2.so", "libSDL2-2.0.so.0", "SDL2.framework/SDL2"):
            paths.append(os.path.join(base, name))
    except Exception:
        pass
    paths.append("SDL2.dll")
    return tuple(paths)


def _load_lib():
    """加载 SDL2 动态库；做不到就返回 None（后端会退回固定表）."""
    global _lib, _lib_ready
    if _lib_ready:
        return _lib
    _lib_ready = True
    for path in _candidate_paths():
        if path != "SDL2.dll" and not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path)
        except Exception:
            continue
        try:
            lib.SDL_Init.argtypes = [ctypes.c_uint32]
            lib.SDL_Init.restype = ctypes.c_int
            lib.SDL_NumJoysticks.restype = ctypes.c_int
            lib.SDL_IsGameController.argtypes = [ctypes.c_int]
            lib.SDL_IsGameController.restype = ctypes.c_int
            lib.SDL_GameControllerOpen.argtypes = [ctypes.c_int]
            lib.SDL_GameControllerOpen.restype = ctypes.c_void_p
            lib.SDL_GameControllerClose.argtypes = [ctypes.c_void_p]
            lib.SDL_GameControllerGetBindForButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.SDL_GameControllerGetBindForButton.restype = _BindStruct
            lib.SDL_GameControllerGetBindForAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.SDL_GameControllerGetBindForAxis.restype = _BindStruct
        except Exception:
            continue
        _lib = lib
        return lib
    _lib = None
    return None


def _query(index: int, guid: str) -> Optional[Tuple[Dict[str, int], Dict[str, int]]]:
    lib = _load_lib()
    if lib is None:
        return None
    try:
        lib.SDL_Init(_SDL_INIT_JOYSTICK | _SDL_INIT_GAMECONTROLLER)
        if not lib.SDL_IsGameController(index):
            return None
        handle = lib.SDL_GameControllerOpen(index)
        if not handle:
            return None
        try:
            buttons: Dict[str, int] = {}
            for enum, name in enumerate(BUTTON_ORDER):
                bind = lib.SDL_GameControllerGetBindForButton(handle, enum)
                if bind.bind_type == _BIND_BUTTON:
                    buttons[name] = int(bind.value.button)
            axes: Dict[str, int] = {}
            for enum, name in enumerate(AXIS_ORDER):
                bind = lib.SDL_GameControllerGetBindForAxis(handle, enum)
                if bind.bind_type == _BIND_AXIS:
                    axes[name] = int(bind.value.axis.axis)
            if not buttons and not axes:
                return None
            return buttons, axes
        finally:
            try:
                lib.SDL_GameControllerClose(handle)
            except Exception:
                pass
    except Exception:
        return None


def device_bindings(index: int, guid: str = "") -> Tuple[Dict[str, int], Dict[str, int]]:
    """返回 (语义按键 -> 原始序号, 语义轴 -> 原始序号).

    拿不到 SDL 绑定时返回空字典，调用方回退到固定标准表。
    """
    key = (int(index), (guid or "").lower())
    if key in _cache:
        return _cache[key]
    result = _query(int(index), key[1]) or ({}, {})
    _cache[key] = result
    return result


def forget(index: Optional[int] = None) -> None:
    """设备热插拔后清缓存."""
    if index is None:
        _cache.clear()
        return
    for key in list(_cache):
        if key[0] == int(index):
            _cache.pop(key, None)
