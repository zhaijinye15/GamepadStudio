"""震动引擎：统一调度 SDL / HID / 虚拟手柄的震动输出，并支持波形测试."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .device_manager import DeviceManager
from .model import DeviceInfo

log = logging.getLogger(__name__)

#: 预设波形 (名称 -> 说明)
PATTERNS = {
    "constant": "持续震动",
    "pulse": "断续脉冲（0.45s 通 / 0.45s 断）",
    "ramp": "渐强渐弱（1.4s 循环）",
    "heartbeat": "心跳（双短脉冲）",
}


@dataclass
class RumbleTest:
    pattern: str = "constant"
    low: float = 0.6
    high: float = 0.9
    duration: float = 2.5      # 秒
    started_at: float = 0.0
    active: bool = False


class RumbleEngine:
    """把"震动测试"抽象成随时间变化的振幅曲线."""

    def __init__(self, manager: DeviceManager) -> None:
        self.manager = manager
        self.device: Optional[DeviceInfo] = None
        self.test = RumbleTest()
        self._last_send = 0.0
        self.last_backend = ""

    # ------------------------------------------------------------------ 控制
    def set_device(self, info: Optional[DeviceInfo]) -> None:
        if self.device is not None and self.device.key != (info.key if info else None):
            try:
                self.manager.stop_rumble(self.device)
            except Exception:
                pass
        self.device = info

    def describe_device(self) -> str:
        if self.device is None:
            return "未选择手柄"
        if self.device.backend == "hid":
            return "HD 震动（HID 直接驱动音圈）"
        if "sdl" in self.device.rumble:
            return "SD 震动（SDL 触觉反馈）"
        return "该设备未声明震动能力"

    def supported(self) -> bool:
        if self.device is None:
            return False
        if self.device.backend == "hid":
            return True
        return "sdl" in self.device.rumble

    def start(self, pattern: str = "constant", low: float = 0.6, high: float = 0.9,
              duration: float = 2.5) -> bool:
        if self.device is None or not self.supported():
            return False
        self.test = RumbleTest(pattern=pattern, low=low, high=high,
                               duration=duration, started_at=time.monotonic(), active=True)
        self._last_send = 0.0
        self.tick()
        return True

    def stop(self) -> None:
        self.test.active = False
        if self.device is not None:
            try:
                self.manager.stop_rumble(self.device)
            except Exception:
                pass
            self.last_backend = "已停止"

    def pulse(self, low: float, high: float, milliseconds: int = 120) -> bool:
        """一次性脉冲，用于按键触发反馈."""
        if self.device is None:
            return False
        ok = self.manager.rumble(self.device, low, high, milliseconds)
        self.last_backend = "SDL" if self.device.backend == "sdl" else "HID"
        return ok

    # ------------------------------------------------------------------ 每帧
    def tick(self) -> None:
        test = self.test
        if not test.active:
            return
        now = time.monotonic()
        elapsed = now - test.started_at
        if elapsed >= test.duration:
            self.stop()
            return
        if now - self._last_send < 0.06:
            return

        low, high = self._envelope(test, elapsed)
        self.manager.rumble(self.device, low, high, 90)
        self.last_backend = "SDL" if self.device.backend == "sdl" else "HID"
        self._last_send = now

    @staticmethod
    def _envelope(test: RumbleTest, elapsed: float) -> tuple[float, float]:
        if test.pattern == "pulse":
            factor = 1.0 if (elapsed % 0.9) < 0.45 else 0.0
        elif test.pattern == "ramp":
            phase = (elapsed % 1.4) / 1.4
            factor = phase * 2 if phase < 0.5 else (1.0 - phase) * 2
        elif test.pattern == "heartbeat":
            cycle = elapsed % 1.1
            factor = 1.0 if (cycle < 0.16 or 0.32 <= cycle < 0.48) else 0.0
        else:
            factor = 1.0
        return test.low * factor, test.high * factor
