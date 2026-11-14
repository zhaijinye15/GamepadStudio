"""摇杆/扳机校准、响应曲线与漂移过滤.

设计目标
--------
* **不改动后端**：后端仍只负责吐原始轴值，本模块在语义层做一次"校准 -> 曲线"
  的变换，界面看到的、映射拿去用的都是校准后的值。
* **可持久化**：所有参数都是纯 JSON（``to_dict`` / ``from_dict``），能整体写进
  配置文件、能导出给别人。
* **失败安全**：任何非法参数（span 为 0、NaN 等）都会被夹回安全范围，
  最坏情况等价于"没校准"，不会把摇杆彻底锁死。

术语
----
* 中心（center）：摇杆静止时两个轴的原始读数，Xbox 手柄常年在 ±0.02 附近飘。
* 行程（span）：从中心推到极限的最大偏移量，左右/上下可能不对称，按轴分别记。
* 死区（deadzone）：径向阈值，小于它的输入直接视为 0，其余重新缩放到 0..1。
* 漂移过滤（drift）：比死区更细的一道闸，只过滤"低速抖动"，不做缩放。
* 曲线（curve）：把 0..1 的行程映射成输出力度，用于手感调节。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import AXIS_LT, AXIS_LX, AXIS_LY, AXIS_RT, AXIS_RX, AXIS_RY, clamp

# ------------------------------------------------------------------ 曲线
CURVE_KEYS: Tuple[str, ...] = ("linear", "ease_in", "ease_out", "expo", "s_curve")
CURVE_OPTIONS: Tuple[str, ...] = ("线性", "缓入（起手更细腻）", "缓出（起手更灵敏）", "指数", "S 曲线")

CURVE_LABELS: Dict[str, str] = dict(zip(CURVE_KEYS, CURVE_OPTIONS))


def apply_curve(value: float, kind: str = "linear", power: float = 1.6) -> float:
    """把 -1..1 的行程值按曲线重映射，保留符号，输出仍在 -1..1."""
    value = clamp(value)
    if value == 0.0 or kind in ("", "linear"):
        return value
    sign = 1.0 if value > 0 else -1.0
    magnitude = min(1.0, abs(value))
    power = max(1.0, min(4.0, float(power)))
    if kind == "ease_in":          # 前段平缓：小位移更精细
        out = magnitude ** power
    elif kind == "ease_out":       # 前段陡：小位移更容易推动
        out = 1.0 - (1.0 - magnitude) ** power
    elif kind == "expo":
        out = magnitude ** (power * 1.8)
    elif kind == "s_curve":
        out = magnitude * magnitude * (3.0 - 2.0 * magnitude)
    else:
        out = magnitude
    return clamp(sign * out)


# ------------------------------------------------------------------ 摇杆
@dataclass
class StickSettings:
    """单个摇杆的校准参数."""

    deadzone: float = 0.15
    drift: float = 0.02
    curve: str = "linear"
    power: float = 1.6
    invert_x: bool = False
    invert_y: bool = True
    center_x: float = 0.0
    center_y: float = 0.0
    span_x: float = 1.0
    span_y: float = 1.0
    calibrated: bool = False

    # -------------------------------------------------------------- 序列化
    def to_dict(self) -> Dict[str, object]:
        return {
            "deadzone": round(float(self.deadzone), 4),
            "drift": round(float(self.drift), 4),
            "curve": self.curve if self.curve in CURVE_KEYS else "linear",
            "power": round(float(self.power), 3),
            "invert_x": bool(self.invert_x),
            "invert_y": bool(self.invert_y),
            "center_x": round(float(self.center_x), 4),
            "center_y": round(float(self.center_y), 4),
            "span_x": round(float(self.span_x), 4),
            "span_y": round(float(self.span_y), 4),
            "calibrated": bool(self.calibrated),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "StickSettings":
        settings = cls()
        if not isinstance(data, dict):
            return settings
        settings.deadzone = _safe_float(data.get("deadzone"), 0.15, 0.0, 0.95)
        settings.drift = _safe_float(data.get("drift"), 0.02, 0.0, 0.5)
        curve = str(data.get("curve") or "linear")
        settings.curve = curve if curve in CURVE_KEYS else "linear"
        settings.power = _safe_float(data.get("power"), 1.6, 1.0, 4.0)
        settings.invert_x = bool(data.get("invert_x", False))
        settings.invert_y = bool(data.get("invert_y", True))
        settings.center_x = _safe_float(data.get("center_x"), 0.0, -1.0, 1.0)
        settings.center_y = _safe_float(data.get("center_y"), 0.0, -1.0, 1.0)
        settings.span_x = _safe_float(data.get("span_x"), 1.0, 0.15, 1.0)
        settings.span_y = _safe_float(data.get("span_y"), 1.0, 0.15, 1.0)
        settings.calibrated = bool(data.get("calibrated", False))
        return settings

    def reset_calibration(self) -> None:
        self.center_x = 0.0
        self.center_y = 0.0
        self.span_x = 1.0
        self.span_y = 1.0
        self.calibrated = False

    # -------------------------------------------------------------- 变换
    def normalize(self, x: float, y: float) -> Tuple[float, float]:
        """原始 -> 去中心、按行程缩放后的 -1..1 值（未做死区与曲线）."""
        nx = clamp((float(x) - self.center_x) / max(0.15, self.span_x))
        ny = clamp((float(y) - self.center_y) / max(0.15, self.span_y))
        if self.invert_x:
            nx = -nx
        if self.invert_y:
            ny = -ny
        return nx, ny

    def process(self, x: float, y: float) -> Tuple[float, float]:
        """完整流水线：校准 -> 漂移过滤 -> 径向死区 -> 曲线."""
        nx, ny = self.normalize(x, y)

        # 漂移过滤：每个轴独立，小抖动直接归零
        if self.drift > 0.0:
            if abs(nx) < self.drift:
                nx = 0.0
            if abs(ny) < self.drift:
                ny = 0.0

        nx, ny = _radial_deadzone(nx, ny, self.deadzone)
        nx = apply_curve(nx, self.curve, self.power)
        ny = apply_curve(ny, self.curve, self.power)
        return nx, ny


def _radial_deadzone(x: float, y: float, deadzone: float) -> Tuple[float, float]:
    """径向死区：按向量长度判断，避免斜向推杆时的"方框"死角."""
    magnitude = math.hypot(x, y)
    if magnitude <= 0.0:
        return 0.0, 0.0
    if deadzone <= 0.0:
        return x, y
    if magnitude <= deadzone:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - deadzone) / (1.0 - deadzone)) / magnitude
    return x * scale, y * scale


# ------------------------------------------------------------------ 扳机
@dataclass
class TriggerSettings:
    """单个扳机的校准参数；输入统一按 0..1 行程处理."""

    deadzone: float = 0.05
    invert: bool = False
    min_raw: float = 0.0
    max_raw: float = 1.0
    calibrated: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "deadzone": round(float(self.deadzone), 4),
            "invert": bool(self.invert),
            "min_raw": round(float(self.min_raw), 4),
            "max_raw": round(float(self.max_raw), 4),
            "calibrated": bool(self.calibrated),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "TriggerSettings":
        settings = cls()
        if not isinstance(data, dict):
            return settings
        settings.deadzone = _safe_float(data.get("deadzone"), 0.05, 0.0, 0.9)
        settings.invert = bool(data.get("invert", False))
        settings.min_raw = _safe_float(data.get("min_raw"), 0.0, 0.0, 1.0)
        settings.max_raw = _safe_float(data.get("max_raw"), 1.0, 0.0, 1.0)
        if settings.max_raw - settings.min_raw < 0.2:
            settings.min_raw, settings.max_raw = 0.0, 1.0
        settings.calibrated = bool(data.get("calibrated", False))
        return settings

    def reset_calibration(self) -> None:
        self.min_raw = 0.0
        self.max_raw = 1.0
        self.calibrated = False

    def process(self, value: float) -> float:
        raw = clamp(float(value), 0.0, 1.0)
        span = max(0.2, self.max_raw - self.min_raw)
        out = clamp((raw - self.min_raw) / span, 0.0, 1.0)
        if self.invert:
            out = 1.0 - out
        if out < self.deadzone:
            return 0.0
        return clamp((out - self.deadzone) / (1.0 - self.deadzone))


# ------------------------------------------------------------------ 整机
@dataclass
class DeviceCalibration:
    """一台手柄的完整校准集合."""

    left: StickSettings = field(default_factory=StickSettings)
    right: StickSettings = field(default_factory=StickSettings)
    lt: TriggerSettings = field(default_factory=TriggerSettings)
    rt: TriggerSettings = field(default_factory=TriggerSettings)

    def to_dict(self) -> Dict[str, object]:
        return {
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "lt": self.lt.to_dict(),
            "rt": self.rt.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "DeviceCalibration":
        if not isinstance(data, dict):
            return cls()
        return cls(
            left=StickSettings.from_dict(data.get("left")),
            right=StickSettings.from_dict(data.get("right")),
            lt=TriggerSettings.from_dict(data.get("lt")),
            rt=TriggerSettings.from_dict(data.get("rt")),
        )

    def reset(self) -> None:
        self.left = StickSettings()
        self.right = StickSettings()
        self.lt = TriggerSettings()
        self.rt = TriggerSettings()
        # 保持默认的 Y 轴反向（Windows 摇杆向下为正，界面习惯向上为正）
        self.left.invert_y = True
        self.right.invert_y = True

    def stick(self, which: str) -> StickSettings:
        return self.right if which == "right" else self.left

    def trigger(self, which: str) -> TriggerSettings:
        return self.rt if which == "rt" else self.lt

    def apply_axes(self, axes: Dict[str, float]) -> Dict[str, float]:
        """返回校准后的语义轴字典；未提供的轴原样返回."""
        result = dict(axes)
        if AXIS_LX in axes and AXIS_LY in axes:
            lx, ly = self.left.process(axes[AXIS_LX], axes[AXIS_LY])
            result[AXIS_LX], result[AXIS_LY] = lx, ly
        if AXIS_RX in axes and AXIS_RY in axes:
            rx, ry = self.right.process(axes[AXIS_RX], axes[AXIS_RY])
            result[AXIS_RX], result[AXIS_RY] = rx, ry
        if AXIS_LT in axes:
            result[AXIS_LT] = self.lt.process(axes[AXIS_LT])
        if AXIS_RT in axes:
            result[AXIS_RT] = self.rt.process(axes[AXIS_RT])
        return result


# ------------------------------------------------------------------ 采样器
class StickSampler:
    """自动校准采样：先采中心，再采行程."""

    def __init__(self, axis_x: str, axis_y: str) -> None:
        self.axis_x = axis_x
        self.axis_y = axis_y
        self.center: Optional[Tuple[float, float]] = None
        self.samples: List[Tuple[float, float]] = []
        self.span: Tuple[float, float] = (1.0, 1.0)

    def start_center(self) -> None:
        self.center = None
        self.samples = []
        self.span = (1.0, 1.0)

    def start_span(self) -> None:
        self.samples = []

    def feed_center(self, x: float, y: float) -> None:
        self.samples.append((float(x), float(y)))

    def feed_span(self, x: float, y: float) -> None:
        self.samples.append((float(x), float(y)))

    def finish_center(self) -> Tuple[float, float]:
        if not self.samples:
            return (0.0, 0.0)
        xs = sorted(s[0] for s in self.samples)
        ys = sorted(s[1] for s in self.samples)
        # 取中位数，比均值更能抵抗采集期间的误碰
        self.center = (_median(xs), _median(ys))
        return self.center

    def finish_span(self) -> Tuple[float, float]:
        cx, cy = self.center or (0.0, 0.0)
        if not self.samples:
            return (1.0, 1.0)
        span_x = max(abs(s[0] - cx) for s in self.samples)
        span_y = max(abs(s[1] - cy) for s in self.samples)
        self.span = (max(0.15, span_x), max(0.15, span_y))
        return self.span


class TriggerSampler:
    """扳机采样：同时记录最小与最大原始值."""

    def __init__(self) -> None:
        self.min_raw = 1.0
        self.max_raw = 0.0
        self.count = 0

    def reset(self) -> None:
        self.min_raw = 1.0
        self.max_raw = 0.0
        self.count = 0

    def feed(self, value: float) -> None:
        value = clamp(float(value), 0.0, 1.0)
        self.min_raw = min(self.min_raw, value)
        self.max_raw = max(self.max_raw, value)
        self.count += 1

    def result(self) -> Tuple[float, float]:
        if self.count == 0:
            return (0.0, 1.0)
        # 两端各留 2% 余量，避免恰好卡在边界读数上取不到满行程
        low = min(self.min_raw, 0.04)
        high = max(self.max_raw, 0.96)
        return (low, high)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def _safe_float(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))
