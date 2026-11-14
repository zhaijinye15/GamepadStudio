"""SDL / pygame 输入后端.

pygame 2.x 基于 SDL2，Windows 下通过 XInput / HID 枚举手柄，
并且天然支持 USB 与蓝牙热插拔（JOYDEVICEADDED / JOYDEVICEREMOVED）。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .layouts import detect_layout, sdl_state, transport_from_name
from .sdl_bindings import device_bindings, forget as forget_bindings
from .model import DeviceInfo, PadState

log = logging.getLogger(__name__)


class SdlBackend:
    name = "sdl"
    label = "SDL2 / pygame"

    def __init__(self) -> None:
        self._available = False
        self._joysticks: Dict[int, object] = {}
        self._error = ""

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> bool:
        try:
            import pygame
        except Exception as exc:  # pragma: no cover - 环境缺库
            self._error = f"未安装 pygame：{exc}"
            log.warning(self._error)
            return False
        try:
            # pygame.init() 是幂等的；手柄子系统只初始化一次，
            # 重复 init 会让 pygame 重建内部设备表，残留事件随后触发 KeyError。
            pygame.init()
            if not pygame.joystick.get_init():
                pygame.joystick.init()
            self._available = True
        except Exception as exc:
            self._error = f"SDL 初始化失败：{exc}"
            log.exception("SDL 初始化失败")
            return False
        return True

    def stop(self) -> None:
        self._joysticks.clear()
        try:
            import pygame
            pygame.joystick.quit()
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str:
        return self._error

    # ---------------------------------------------------------------- 枚举
    def enumerate(self) -> List[DeviceInfo]:
        import pygame

        devices: List[DeviceInfo] = []
        count = pygame.joystick.get_count()
        for index in range(count):
            try:
                stick = self._ensure(index)
            except Exception:
                log.exception("打开手柄 %s 失败", index)
                continue
            try:
                devices.append(self._describe(index, stick))
            except Exception:
                log.exception("读取手柄 %s 信息失败，已跳过", index)
        return devices

    def _describe(self, index: int, stick) -> "DeviceInfo":
        guid = _call_str(stick, "get_guid")
        name = _call_str(stick, "get_name") or f"手柄 #{index}"
        instances = _call_int(stick, "get_instance_id", index)
        vendor_id, product_id = _vid_pid(stick, guid)
        button_map, axis_map = device_bindings(index, guid)
        return DeviceInfo(
            key=f"sdl:{instances}",
            name=name,
            backend="sdl",
            layout=detect_layout(name),
            guid=guid,
            vendor_id=vendor_id,
            product_id=product_id,
            transport=transport_from_name(name, guid),
            buttons=_call_int(stick, "get_numbuttons", 0),
            axes=_call_int(stick, "get_numaxes", 0),
            hats=_call_int(stick, "get_numhats", 0),
            rumble=self._rumble_caps(stick),
            instance_id=index,
            button_map=button_map,
            axis_map=axis_map,
        )

    def _ensure(self, index: int):
        import pygame

        stick = self._joysticks.get(index)
        if stick is not None and getattr(stick, "get_init", lambda: False)():
            return stick
        stick = pygame.joystick.Joystick(index)
        stick.init()
        self._joysticks[index] = stick
        return stick

    def forget(self, index: int) -> None:
        self._joysticks.pop(index, None)

    # ---------------------------------------------------------------- 读取
    def poll(self, info: DeviceInfo) -> Optional[PadState]:
        if not self._available:
            return None
        try:
            stick = self._ensure(info.instance_id)
        except Exception:
            log.exception("读取手柄失败：%s", info.name)
            return None

        raw_buttons = {f"b{i}": bool(stick.get_button(i)) for i in range(stick.get_numbuttons())}
        raw_axes: Dict[str, float] = {}
        for index in range(stick.get_numaxes()):
            try:
                raw_axes[f"a{index}"] = float(stick.get_axis(index))
            except Exception:
                raw_axes[f"a{index}"] = 0.0
        hat: Tuple[int, int] = (0, 0)
        if info.hats:
            try:
                hat = tuple(stick.get_hat(0))  # type: ignore[assignment]
            except Exception:
                hat = (0, 0)

        semantic_buttons, semantic_axes = sdl_state(
            raw_buttons, raw_axes, hat,
            button_map=info.button_map or None,
            axis_map=info.axis_map or None,
        )
        return PadState(
            buttons=raw_buttons,
            axes=raw_axes,
            hats=(int(hat[0]), int(hat[1])),
            semantic_buttons=semantic_buttons,
            semantic_axes=semantic_axes,
        )

    # ---------------------------------------------------------------- 震动
    @staticmethod
    def _rumble_caps(stick) -> Tuple[str, ...]:
        caps: List[str] = []
        if hasattr(stick, "rumble"):
            caps.append("sdl")
        return tuple(caps)

    def rumble(self, info: DeviceInfo, low: float, high: float, duration_ms: int) -> bool:
        try:
            stick = self._ensure(info.instance_id)
        except Exception:
            return False
        if not hasattr(stick, "rumble"):
            return False
        try:
            stick.rumble(float(low), float(high), int(duration_ms))
            return True
        except Exception:
            log.exception("SDL 震动失败")
            return False

    def stop_rumble(self, info: DeviceInfo) -> None:
        try:
            stick = self._ensure(info.instance_id)
            if hasattr(stick, "stop_rumble"):
                stick.stop_rumble()
            elif hasattr(stick, "rumble"):
                stick.rumble(0.0, 0.0, 0)
        except Exception:
            pass


def _call_int(obj, name: str, default: int = 0) -> int:
    """安全读取 pygame 手柄对象上的整数方法/属性；不存在或出错时回退默认值."""
    try:
        attr = getattr(obj, name, None)
        if attr is None:
            return default
        value = attr() if callable(attr) else attr
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _call_str(obj, name: str, default: str = "") -> str:
    try:
        attr = getattr(obj, name, None)
        if attr is None:
            return default
        value = attr() if callable(attr) else attr
        return str(value) if value else default
    except Exception:
        return default


def _swap16(value: int) -> int:
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


def _vid_pid(stick, guid: str) -> Tuple[int, int]:
    """厂商/产品号：优先读对象上的方法，pygame 不提供时从 SDL GUID 解析.

    SDL 的 GUID 十六进制串里，前 4 字节是总线类型，随后是厂商号、产品号，
    均为小端存放，所以解析出来要交换高低字节。
    """
    vendor = _call_int(stick, "get_vendor_id", 0)
    product = _call_int(stick, "get_product_id", 0)
    text = (guid or "").strip().lower()
    if len(text) >= 24:
        try:
            if not vendor:
                vendor = _swap16(int(text[8:12], 16))
        except ValueError:
            vendor = vendor or 0
    if len(text) >= 20:
        for start in (16, 12):
            try:
                candidate = _swap16(int(text[start:start + 4], 16))
            except ValueError:
                continue
            if not product and candidate:
                product = candidate
                break
    return vendor, product


def _guarded(func, default: int) -> int:
    try:
        return int(func())
    except Exception:
        return default
