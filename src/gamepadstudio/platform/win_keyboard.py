"""Windows 键盘/鼠标注入（SendInput）。

只在用户显式开启"键盘映射输出"时使用；测试台默认仅监视，不会向系统注入输入。
"""
from __future__ import annotations

import logging
import sys
from typing import Dict, Iterable, Optional, Set

log = logging.getLogger(__name__)

VK_CODES: Dict[str, int] = {
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},  # VK_A..VK_Z = 0x41..
    **{str(digit): 0x30 + digit for digit in range(10)},
    "SPACE": 0x20, "ENTER": 0x0D, "ESC": 0x1B, "TAB": 0x09,
    "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    **{f"F{index}": 0x6F + index for index in range(1, 13)},
}

MOUSE_CODES: Dict[str, int] = {
    "mouse_left": 0x0002,
    "mouse_right": 0x0008,
    "mouse_middle": 0x0020,
}

KEYEVENTF_KEYUP = 0x0002
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1


class KeyboardInjector:
    """把动作集合差分成按下/抬起事件，避免每帧重复注入."""

    def __init__(self) -> None:
        self._pressed: Set[str] = set()
        self._supported = sys.platform == "win32"
        self.error = "" if self._supported else "当前系统不支持键盘注入（仅 Windows）"
        if self._supported:
            try:
                import ctypes
                from ctypes import wintypes

                self._ctypes = ctypes
                self._wintypes = wintypes
                self._user32 = ctypes.WinDLL("user32", use_last_error=True)
                self._build_structures()
            except Exception as exc:  # pragma: no cover
                self._supported = False
                self.error = f"初始化 SendInput 失败：{exc}"
                log.warning(self.error)

    def _build_structures(self) -> None:  # pragma: no cover - 依赖 Windows
        ctypes = self._ctypes
        wintypes = self._wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

        self._KEYBDINPUT = KEYBDINPUT
        self._MOUSEINPUT = MOUSEINPUT
        self._INPUT = INPUT
        self._INPUTUNION = _INPUTUNION

    @property
    def supported(self) -> bool:
        return self._supported

    # ------------------------------------------------------------------ 注入
    def update(self, actions: Iterable[str]) -> None:
        """actions 形如 {"keyboard:W", "keyboard:mouse_left"}。"""
        if not self._supported:
            return
        wanted: Set[str] = set()
        for action in actions:
            if action.startswith("keyboard:"):
                wanted.add(action[len("keyboard:"):])

        for combo in wanted - self._pressed:
            self._send_combo(combo, down=True)
        for combo in self._pressed - wanted:
            self._send_combo(combo, down=False)
        self._pressed = wanted

    def release_all(self) -> None:
        for combo in list(self._pressed):
            self._send_combo(combo, down=False)
        self._pressed.clear()

    def _send_combo(self, combo: str, down: bool) -> None:
        parts = [part.strip() for part in combo.split("+") if part.strip()]
        if not parts:
            return
        if len(parts) == 1 and parts[0] in MOUSE_CODES:
            self._send_mouse(MOUSE_CODES[parts[0]], down)
            return
        # 组合键：按下时按顺序发，抬起时反序
        ordered = parts if down else list(reversed(parts))
        for part in ordered:
            vk = VK_CODES.get(part.upper())
            if vk is not None:
                self._send_key(vk, down)

    def _send_key(self, vk: int, down: bool) -> None:  # pragma: no cover - 依赖 Windows
        ctypes = self._ctypes
        inp = self._INPUT(type=INPUT_KEYBOARD)
        inp.union.ki = self._KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0 if down else KEYEVENTF_KEYUP,
                                        time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(self._INPUT))

    def _send_mouse(self, flag: int, down: bool) -> None:  # pragma: no cover - 依赖 Windows
        ctypes = self._ctypes
        inp = self._INPUT(type=INPUT_MOUSE)
        flags = flag if down else flag << 1  # MOUSEEVENTF_*UP = 对应 DOWN 左移一位
        inp.union.mi = self._MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(self._INPUT))
