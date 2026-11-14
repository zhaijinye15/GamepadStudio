"""规范化输入模型.

所有后端（SDL / HID）都转换成本模块的数据结构，界面与映射逻辑只依赖它，
因此新增后端不会影响上层。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: 语义按键键名（跨布局统一）
SEMANTIC_BUTTONS: Tuple[str, ...] = (
    "a", "b", "x", "y",
    "lb", "rb", "lt", "rt",
    "up", "down", "left", "right",
    "back", "start", "guide", "l3", "r3",
)

#: 语义轴键名
AXIS_LX, AXIS_LY, AXIS_RX, AXIS_RY = "lx", "ly", "rx", "ry"
AXIS_LT, AXIS_RT = "lt", "rt"
SEMANTIC_AXES: Tuple[str, ...] = (AXIS_LX, AXIS_LY, AXIS_RX, AXIS_RY, AXIS_LT, AXIS_RT)


@dataclass
class DeviceInfo:
    """一个可被测试/映射的手柄."""

    key: str                       # 唯一标识（后端:序号）
    name: str
    backend: str                   # "sdl" | "hid"
    layout: str = "generic"        # xbox / playstation / switch / generic
    guid: str = ""
    vendor_id: int = 0
    product_id: int = 0
    transport: str = "unknown"     # usb / bluetooth / unknown
    buttons: int = 0
    axes: int = 0
    hats: int = 0
    battery: Optional[float] = None
    rumble: Tuple[str, ...] = ()
    instance_id: int = -1          # SDL 设备索引 / HID 索引
    #: 语义按键 -> 原始按钮序号（由 SDL 绑定表给出；空则用标准表）
    button_map: Dict[str, int] = field(default_factory=dict)
    #: 语义轴 -> 原始轴序号
    axis_map: Dict[str, int] = field(default_factory=dict)

    def describe_transport(self) -> str:
        return {"usb": "USB", "bluetooth": "蓝牙"}.get(self.transport, "未知连接")

    def describe_layout(self) -> str:
        return {
            "xbox": "Xbox 布局",
            "playstation": "PlayStation 布局",
            "switch": "Switch 布局",
            "generic": "通用布局",
        }.get(self.layout, "通用布局")


@dataclass
class PadState:
    """一帧输入快照。raw 键为 b0..b31 / a0..a7，语义键见 SEMANTIC_*。"""

    buttons: Dict[str, bool] = field(default_factory=dict)
    axes: Dict[str, float] = field(default_factory=dict)
    hats: Tuple[int, int] = (0, 0)
    semantic_buttons: Dict[str, bool] = field(default_factory=dict)
    semantic_axes: Dict[str, float] = field(default_factory=dict)

    def button(self, name: str) -> bool:
        return bool(self.semantic_buttons.get(name, False))

    def axis(self, name: str) -> float:
        return float(self.semantic_axes.get(name, 0.0))

    def pressed_semantic(self) -> List[str]:
        return [k for k, v in self.semantic_buttons.items() if v]

    @property
    def connected(self) -> bool:
        return bool(self.buttons or self.axes)

    def any_activity(self) -> bool:
        return any(self.buttons.values()) or any(abs(v) > 0.02 for v in self.axes.values())


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def normalize_trigger(raw: float) -> float:
    """SDL 扳机轴为 -1..1，统一到 0..1。"""
    return clamp((raw + 1.0) / 2.0, 0.0, 1.0)


def apply_deadzone(value: float, deadzone: float) -> float:
    """径向死区：小于阈值归零，其余重新缩放到 0..1，避免"跳变"。"""
    if deadzone <= 0.0:
        return value
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * min(1.0, (abs(value) - deadzone) / (1.0 - deadzone))


def radial_deadzone(x: float, y: float, deadzone: float) -> Tuple[float, float]:
    magnitude = (x * x + y * y) ** 0.5
    if magnitude <= deadzone or magnitude == 0.0:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - deadzone) / (1.0 - deadzone)) / magnitude
    return x * scale, y * scale


def describe_button(name: str) -> str:
    """语义按键 -> 中文显示名。"""
    return {
        "a": "A", "b": "B", "x": "X", "y": "Y",
        "lb": "LB / L1", "rb": "RB / R1",
        "lt": "LT / L2", "rt": "RT / R2",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
        "back": "Back / View", "start": "Start / Menu",
        "guide": "Guide", "l3": "L3", "r3": "R3",
    }.get(name, name.upper())


def describe_axis(name: str) -> str:
    return {
        "lx": "左摇杆 X", "ly": "左摇杆 Y",
        "rx": "右摇杆 X", "ry": "右摇杆 Y",
        "lt": "左扳机 LT", "rt": "右扳机 RT",
    }.get(name, name.upper())
