"""HID 后端：负责 Nintendo 手柄（Joy-Con / Pro Controller）的读取与震动.

SDL 对单只 Joy-Con 的支持有限（左右手会各自暴露为半个手柄，且蓝牙模式下
常常无法输出震动），因此这里用 hidapi 直接读写，保证：
* 能识别 0x21 / 0x30 两种输入报文；
* 能用 0x10 报文驱动 HD 震动。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from .hid import joycon

log = logging.getLogger(__name__)


class HidWorker(threading.Thread):
    """单设备读取线程：持续读报文，缓存最新状态."""

    daemon = True

    def __init__(self, info) -> None:
        super().__init__(name=f"hid-{info.name}")
        self.info = info
        self._device = None
        self._stop_event = threading.Event()
        self._state: Dict[str, object] = {}
        self._lock = threading.Lock()
        self._rumble_until = 0.0
        self._rumble_amp = 0.0
        self._rumble_freq = 160.0
        self.last_error = ""
        self.alive = False

    # ------------------------------------------------------------------ 生命周期
    def run(self) -> None:  # pragma: no cover - 需要真实硬件
        try:
            import hid
        except Exception as exc:
            self.last_error = f"未安装 hidapi：{exc}"
            log.warning(self.last_error)
            return

        try:
            self._device = hid.device()
            self._device.open_path(self.info.path)
            self._device.set_nonblocking(1)
        except Exception as exc:
            self.last_error = f"打开设备失败：{exc}"
            log.warning(self.last_error)
            return

        self.alive = True
        self._handshake()
        last_packet = 0.0
        while not self._stop_event.is_set():
            try:
                report = self._device.read(64)
            except Exception as exc:
                self.last_error = f"读取中断：{exc}"
                break
            now = time.monotonic()
            if report:
                self._ingest(bytes(report), now)
            # 震动需要持续发送报文，音圈才会维持振动
            if self._rumble_amp > 0.0 and now < self._rumble_until and now - last_packet > 0.02:
                try:
                    self._device.write(joycon.build_rumble_report(self._rumble_amp, self._rumble_freq))
                except Exception:
                    pass
                last_packet = now
            elif self._rumble_amp > 0.0 and now >= self._rumble_until:
                self._send_neutral()
                self._rumble_amp = 0.0
            else:
                time.sleep(0.002)
        self.alive = False
        try:
            self._device.close()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------ 协议
    def _handshake(self) -> None:
        """请求 standard full 输入报文（0x30），失败时仍可用 0x21."""
        try:
            packet = 0
            for subcommand, argument in (
                (joycon.ENABLE_IMU, b"\x01"),
                (joycon.SET_INPUT_REPORT_MODE, b"\x30"),
            ):
                self._device.write(joycon.build_subcommand(packet, subcommand, argument))
                packet = (packet + 1) & 0x0F
                time.sleep(0.02)
            self._device.write(joycon.build_rumble_report(0.0, self._rumble_freq))
        except Exception:
            log.debug("Joy-Con 握手失败，继续使用 simple HID 模式", exc_info=True)

    def _ingest(self, report: bytes, now: float) -> None:
        if report[0] not in joycon.INPUT_REPORT_IDS:
            return
        parsed = joycon.parse_report(report, self.info.product_id)
        if not parsed:
            return
        with self._lock:
            self._state = parsed
            self._state["timestamp"] = now

    def _send_neutral(self) -> None:
        try:
            self._device.write(joycon.build_rumble_report(0.0, self._rumble_freq))
        except Exception:
            pass

    # ------------------------------------------------------------------ 对外
    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return dict(self._state)

    def rumble(self, low: float, high: float, duration_ms: int) -> bool:
        """Joy-Con 只有一路音圈，取低频/高频的较大值按能量合成为单通道振幅."""
        if not self.alive:
            return False
        amp = max(0.0, min(1.0, 0.65 * max(low, high) + 0.35 * ((low + high) / 2.0)))
        if amp <= 0.02:
            self._rumble_amp = 0.0
            self._send_neutral()
            return True
        self._rumble_amp = amp
        self._rumble_freq = 80.0 + 240.0 * min(1.0, max(low, high))
        self._rumble_until = time.monotonic() + max(0.05, duration_ms / 1000.0)
        return True

    def stop_rumble(self) -> None:
        self._rumble_amp = 0.0
        self._send_neutral()


class HidBackend:
    name = "hid"
    label = "hidapi（Nintendo HID）"

    def __init__(self) -> None:
        self._available = False
        self._workers: Dict[str, HidWorker] = {}
        self._devices: Dict[str, object] = {}
        self._error = ""

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> bool:
        try:
            import hid  # noqa: F401
        except Exception as exc:
            self._error = f"未安装 hidapi：{exc}"
            return False
        self._available = True
        return True

    def stop(self) -> None:
        for worker in self._workers.values():
            worker.stop()
        self._workers.clear()
        self._devices.clear()

    def enumerate(self) -> List[object]:
        if not self._available:
            return []
        try:
            import hid
            raw = hid.enumerate()
        except Exception as exc:
            log.warning("HID 枚举失败：%s", exc)
            self._error = str(exc)
            return []

        devices = []
        for item in raw:
            vendor = int(item.get("vendor_id") or 0)
            product = int(item.get("product_id") or 0)
            if not joycon.is_nintendo(vendor, product):
                continue
            path = item.get("path") or ""
            usage_page = int(item.get("usage_page") or 0)
            # Joy-Con 会暴露多个接口，只取使用页 0x01 的输入接口
            if usage_page not in (0, 1):
                continue
            key = f"hid:{path}"
            devices.append(_HidDeviceInfo(
                key=key,
                name=joycon.device_name(product),
                path=path,
                vendor_id=vendor,
                product_id=product,
                serial=(item.get("serial_number") or ""),
                transport="bluetooth" if not item.get("bus_type") == 1 else "usb",
            ))
        return devices

    def poll(self, info) -> Optional[Dict[str, object]]:
        worker = self._worker_for(info)
        if worker is None:
            return None
        return worker.snapshot()

    def _worker_for(self, info) -> Optional[HidWorker]:
        worker = self._workers.get(info.key)
        if worker is not None and worker.alive:
            return worker
        worker = HidWorker(info)
        worker.start()
        self._workers[info.key] = worker
        # 给线程一点时间完成握手
        time.sleep(0.05)
        return worker

    def rumble(self, info, low: float, high: float, duration_ms: int) -> bool:
        worker = self._workers.get(info.key)
        if worker is None:
            return False
        return worker.rumble(low, high, duration_ms)

    def stop_rumble(self, info) -> None:
        worker = self._workers.get(info.key)
        if worker is not None:
            worker.stop_rumble()

    def forget(self, key: str) -> None:
        worker = self._workers.pop(key, None)
        if worker is not None:
            worker.stop()


class _HidDeviceInfo:
    """HID 设备的内部描述（在 DeviceManager 中转成 DeviceInfo）."""

    def __init__(self, key, name, path, vendor_id, product_id, serial, transport):
        self.key = key
        self.name = name
        self.path = path
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.serial = serial
        self.transport = transport
