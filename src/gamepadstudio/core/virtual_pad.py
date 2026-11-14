"""虚拟手柄输出（基于 ViGEmBus + vgamepad）。

安装程序会部署 ViGEmBus 驱动；本模块在驱动或 vgamepad 缺失时优雅降级，
只影响"输出为虚拟手柄"这一功能，不影响测试台本身。
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

#: 语义按键 -> Xbox 360 常量名
_X360_BUTTONS = {
    "a": "XUSB_GAMEPAD_A",
    "b": "XUSB_GAMEPAD_B",
    "x": "XUSB_GAMEPAD_X",
    "y": "XUSB_GAMEPAD_Y",
    "lb": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "rb": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "back": "XUSB_GAMEPAD_BACK",
    "start": "XUSB_GAMEPAD_START",
    "guide": "XUSB_GAMEPAD_GUIDE",
    "l3": "XUSB_GAMEPAD_LEFT_THUMB",
    "r3": "XUSB_GAMEPAD_RIGHT_THUMB",
    "up": "XUSB_GAMEPAD_DPAD_UP",
    "down": "XUSB_GAMEPAD_DPAD_DOWN",
    "left": "XUSB_GAMEPAD_DPAD_LEFT",
    "right": "XUSB_GAMEPAD_DPAD_RIGHT",
}

#: 语义按键 -> DS4 常量名
_DS4_BUTTONS = {
    "a": "DS4_BUTTON_CROSS",
    "b": "DS4_BUTTON_CIRCLE",
    "x": "DS4_BUTTON_SQUARE",
    "y": "DS4_BUTTON_TRIANGLE",
    "lb": "DS4_BUTTON_SHOULDER_LEFT",
    "rb": "DS4_BUTTON_SHOULDER_RIGHT",
    "back": "DS4_BUTTON_SHARE",
    "start": "DS4_BUTTON_OPTIONS",
    "l3": "DS4_BUTTON_THUMB_LEFT",
    "r3": "DS4_BUTTON_THUMB_RIGHT",
    "up": "DS4_BUTTON_DPAD_NORTH",
    "down": "DS4_BUTTON_DPAD_SOUTH",
    "left": "DS4_BUTTON_DPAD_WEST",
    "right": "DS4_BUTTON_DPAD_EAST",
}


def availability() -> Tuple[bool, str]:
    """返回 (是否可用, 说明)."""
    try:
        import vgamepad  # noqa: F401
    except ImportError as exc:
        return False, f"未安装 vgamepad：{exc}"
    except Exception as exc:
        message = str(exc)
        if "VIGEM_ERROR_BUS_NOT_FOUND" in message:
            return False, "ViGEmBus 驱动未安装，虚拟手柄不可用"
        return False, f"vgamepad 初始化失败：{message}"
    try:
        from vgamepad import VX360Gamepad
        pad = VX360Gamepad()
        del pad
        return True, "ViGEmBus 驱动就绪"
    except Exception as exc:
        message = str(exc)
        if "VIGEM_ERROR_BUS_NOT_FOUND" in message:
            return False, "ViGEmBus 驱动未安装，虚拟手柄不可用"
        return False, f"ViGEmBus 驱动不可用：{message}"


class VirtualPad:
    """把一个真实手柄映射成虚拟 Xbox 360 / DualShock 4 手柄."""

    def __init__(self, kind: str = "virtual_xbox360") -> None:
        self.kind = kind
        self._pad = None
        self._vg = None
        self._pressed: set[str] = set()
        self._last_state: Dict[str, float] = {}
        self.error = ""

    # ------------------------------------------------------------------ 生命周期
    def open(self) -> bool:
        try:
            import vgamepad as vg

            self._vg = vg
            if self.kind == "virtual_dualshock4":
                self._pad = vg.VDS4Gamepad()
            else:
                self._pad = vg.VX360Gamepad()
            self.error = ""
            return True
        except ImportError as exc:
            self.error = f"未安装 vgamepad：{exc}"
            self._pad = None
            return False
        except Exception as exc:
            message = str(exc)
            if "VIGEM_ERROR_BUS_NOT_FOUND" in message:
                self.error = "ViGEmBus 驱动未安装，无法创建虚拟手柄"
            else:
                self.error = f"创建虚拟手柄失败：{message}"
            log.warning(self.error)
            self._pad = None
            return False

    @property
    def is_open(self) -> bool:
        return self._pad is not None

    def close(self) -> None:
        if self._pad is not None:
            try:
                self._pad.reset()
                self._pad.update()
            except Exception:
                pass
            try:
                del self._pad
            except Exception:
                pass
        self._pad = None
        self._pressed.clear()

    # ------------------------------------------------------------------ 输出
    def apply(self, outputs: Dict[str, float], sticks: Dict[str, float], triggers: Dict[str, float]) -> None:
        """outputs 形如 {"virtual:a": 1.0, ...}；sticks/triggers 为模拟量."""
        if self._pad is None:
            return
        wanted = set()
        for action, strength in outputs.items():
            if not action.startswith("virtual:") or strength <= 0.0:
                continue
            wanted.add(action[len("virtual:"):])

        table = _DS4_BUTTONS if self.kind == "virtual_dualshock4" else _X360_BUTTONS
        for name in wanted - self._pressed:
            constant = getattr(self._vg, "DS4_BUTTONS" if self.kind == "virtual_dualshock4" else "XUSB_BUTTON", None)
            attr = table.get(name)
            if constant is not None and attr is not None:
                try:
                    self._pad.press_button(button=getattr(constant, attr))
                except Exception:
                    pass
        for name in self._pressed - wanted:
            constant = getattr(self._vg, "DS4_BUTTONS" if self.kind == "virtual_dualshock4" else "XUSB_BUTTON", None)
            attr = table.get(name)
            if constant is not None and attr is not None:
                try:
                    self._pad.release_button(button=getattr(constant, attr))
                except Exception:
                    pass
        self._pressed = wanted

        state = {
            "lx": sticks.get("lx", 0.0), "ly": sticks.get("ly", 0.0),
            "rx": sticks.get("rx", 0.0), "ry": sticks.get("ry", 0.0),
            "lt": triggers.get("lt", 0.0), "rt": triggers.get("rt", 0.0),
        }
        if state != self._last_state:
            try:
                self._pad.left_joystick_float(x_value_float=state["lx"], y_value_float=state["ly"])
                self._pad.right_joystick_float(x_value_float=state["rx"], y_value_float=state["ry"])
                self._pad.left_trigger_float(value_float=max(0.0, min(1.0, state["lt"])))
                self._pad.right_trigger_float(value_float=max(0.0, min(1.0, state["rt"])))
            except Exception:
                pass
            self._last_state = state
        try:
            self._pad.update()
        except Exception:
            pass

    def reset(self) -> None:
        if self._pad is None:
            return
        try:
            self._pad.reset()
            self._pad.update()
        except Exception:
            pass
        self._pressed.clear()
        self._last_state = {}
