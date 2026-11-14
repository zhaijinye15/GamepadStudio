"""设备管理器：聚合 SDL 与 HID 两个后端，向上层暴露统一接口."""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional

from .backend_hid import HidBackend
from .backend_sdl import SdlBackend
from .layouts import detect_layout
from .model import DeviceInfo, PadState

log = logging.getLogger(__name__)

NINTENDO_NAMES = ("joy-con", "joycon", "pro controller", "nintendo")


class DeviceManager:
    """统一设备枚举 / 轮询 / 震动入口."""

    def __init__(self) -> None:
        self.sdl = SdlBackend()
        self.hid = HidBackend()
        self._devices: List[DeviceInfo] = []
        self._last_refresh = 0.0
        self._refresh_interval = 1.0
        self.errors: Dict[str, str] = {}

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if not self.sdl.start():
            self.errors["sdl"] = self.sdl.error
        if not self.hid.start():
            self.errors["hid"] = self.hid.error
        self.refresh(force=True)

    def stop(self) -> None:
        self.sdl.stop()
        self.hid.stop()

    # ------------------------------------------------------------------ 枚举
    def refresh(self, force: bool = False) -> List[DeviceInfo]:
        now = time.monotonic()
        if not force and now - self._last_refresh < self._refresh_interval:
            return self._devices
        self._last_refresh = now

        devices: List[DeviceInfo] = []
        hid_devices = self.hid.enumerate() if self.hid.available else []
        hid_names = set()
        for raw in hid_devices:
            hid_names.add(raw.product_id)
            devices.append(
                DeviceInfo(
                    key=raw.key,
                    name=raw.name,
                    backend="hid",
                    layout="switch",
                    transport=raw.transport,
                    vendor_id=raw.vendor_id,
                    product_id=raw.product_id,
                    buttons=16,
                    axes=6,
                    hats=0,
                    battery=None,
                    rumble=("hid",),
                    instance_id=-1,
                )
            )

        if self.sdl.available:
            for info in self.sdl.enumerate():
                # Nintendo 设备已由 HID 后端接管，避免重复出现
                if any(token in info.name.lower() for token in NINTENDO_NAMES) and hid_names:
                    continue
                devices.append(info)

        known = {device.key: device for device in self._devices}
        for device in devices:
            previous = known.get(device.key)
            if previous is not None and previous.battery is not None:
                device.battery = previous.battery
        self._devices = devices
        return devices

    @property
    def devices(self) -> List[DeviceInfo]:
        return self._devices

    def find(self, key: str) -> Optional[DeviceInfo]:
        for device in self._devices:
            if device.key == key:
                return device
        return None

    # ------------------------------------------------------------------ 读取
    def poll(self, info: DeviceInfo) -> Optional[PadState]:
        if info.backend == "hid":
            snapshot = self.hid.poll(_HidProxy(info))
            if not snapshot:
                return None
            state = PadState(
                buttons=dict(snapshot.get("buttons", {})),
                axes=dict(snapshot.get("axes", {})),
                semantic_buttons=dict(snapshot.get("semantic_buttons", {})),
                semantic_axes=dict(snapshot.get("semantic_axes", {})),
            )
            battery = snapshot.get("battery")
            if isinstance(battery, float):
                info.battery = battery
            return state
        return self.sdl.poll(info)

    # ------------------------------------------------------------------ 震动
    def rumble(self, info: DeviceInfo, low: float, high: float, duration_ms: int) -> bool:
        if info.backend == "hid":
            return self.hid.rumble(_HidProxy(info), low, high, duration_ms)
        return self.sdl.rumble(info, low, high, duration_ms)

    def stop_rumble(self, info: DeviceInfo) -> None:
        if info.backend == "hid":
            self.hid.stop_rumble(_HidProxy(info))
        else:
            self.sdl.stop_rumble(info)

    def rumble_capability(self, info: DeviceInfo) -> str:
        if info.backend == "hid":
            return "HD 震动（HID 直连）"
        if info.backend == "sdl":
            stick = _sdl_stick(self.sdl, info)
            caps = self.sdl._rumble_caps(stick) if stick is not None else ()
            return "SD 震动（SDL）" if "sdl" in caps else "不支持震动"
        return "未知"

    # ------------------------------------------------------------------ 杂项
    def forget_removed(self, present_keys: List[str]) -> None:
        for device in list(self._devices):
            if device.key not in present_keys:
                if device.backend == "hid":
                    self.hid.forget(device.key)
                else:
                    self.sdl.forget(device.instance_id)
        self._devices = [d for d in self._devices if d.key in present_keys]


def _sdl_stick(backend: SdlBackend, info: DeviceInfo):
    try:
        return backend._ensure(info.instance_id)
    except Exception:
        return None


class _HidProxy:
    """把 DeviceInfo 适配成 HidBackend 需要的对象（带 path）."""

    def __init__(self, info: DeviceInfo) -> None:
        self.key = info.key
        self.name = info.name
        self.product_id = info.product_id
        self.vendor_id = info.vendor_id
        self.path = info.key.split("hid:", 1)[-1]
