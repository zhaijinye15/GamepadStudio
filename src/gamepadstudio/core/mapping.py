"""按键映射方案：JSON 结构、校验、运行时换算.

方案文件示例（profiles/*.json）::

    {
      "schema": "gamepadstudio.mapping/1",
      "name": "赛车 · 键盘模拟",
      "target": "keyboard",
      "deadzone": 0.18,
      "invert_axes": ["ly", "ry"],
      "bindings": [
        {"source": "button:rt", "action": "keyboard:W"},
        {"source": "axis:lx+", "action": "keyboard:D"},
        {"source": "axis:lx-", "action": "keyboard:A"}
      ]
    }

source 语法：
    button:<语义键名>     例如 button:a、button:rb、button:up
    axis:<轴名>:<符号>    例如 axis:lx:+（推到右）、axis:rt:+（扳机按下）
action 语法：
    keyboard:<按键或组合> 例如 keyboard:W、keyboard:CTRL+SHIFT+S、keyboard:mouse_left
    virtual:<手柄按键>    例如 virtual:a、virtual:lt
    none                  仅记录，不输出
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .model import SEMANTIC_AXES, SEMANTIC_BUTTONS, PadState, radial_deadzone

SCHEMA = "gamepadstudio.mapping/1"
TARGETS = ("monitor", "keyboard", "virtual_xbox360", "virtual_dualshock4")
TARGET_LABELS = {
    "monitor": "仅监视（不输出）",
    "keyboard": "键盘 / 鼠标映射",
    "virtual_xbox360": "虚拟 Xbox 360 手柄",
    "virtual_dualshock4": "虚拟 DualShock 4 手柄",
}

SOURCE_PREFIX_BUTTON = "button:"
SOURCE_PREFIX_AXIS = "axis:"

#: 键盘可用按键名（SendInput 虚拟键码，见 platform/win_keyboard.py）
KEYBOARD_KEYS = (
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "SPACE", "ENTER", "ESC", "TAB", "SHIFT", "CTRL", "ALT",
    "UP", "DOWN", "LEFT", "RIGHT",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "mouse_left", "mouse_right", "mouse_middle",
)


def all_sources() -> List[str]:
    """界面可选的全部源事件（按钮 + 摇杆正负方向 + 扳机）."""
    sources: List[str] = [f"button:{name}" for name in SEMANTIC_BUTTONS]
    for axis in ("lx", "ly", "rx", "ry", "rt", "lt"):
        if axis in SEMANTIC_AXES:
            sources.append(f"axis:{axis}:+")
            if axis in ("lx", "ly", "rx", "ry"):
                sources.append(f"axis:{axis}:-")
    return sources


def describe_source(source: str) -> str:
    if source.startswith(SOURCE_PREFIX_BUTTON):
        name = source[len(SOURCE_PREFIX_BUTTON):]
        labels = {
            "a": "A 键", "b": "B 键", "x": "X 键", "y": "Y 键",
            "lb": "左肩键", "rb": "右肩键", "lt": "左扳机", "rt": "右扳机",
            "up": "十字键 ↑", "down": "十字键 ↓", "left": "十字键 ←", "right": "十字键 →",
            "back": "Back / 视图", "start": "Start / 菜单", "guide": "Guide / Home",
            "l3": "左摇杆按下", "r3": "右摇杆按下",
        }
        return labels.get(name, name.upper())
    if source.startswith(SOURCE_PREFIX_AXIS):
        parts = source.split(":")
        axis = parts[1] if len(parts) > 1 else ""
        sign = parts[2] if len(parts) > 2 else "+"
        axis_labels = {"lx": "左摇杆 X", "ly": "左摇杆 Y", "rx": "右摇杆 X",
                       "ry": "右摇杆 Y", "lt": "左扳机", "rt": "右扳机"}
        arrow = "+" if axis in ("lx", "rx", "rt", "lt") else "-"
        arrow = sign
        direction = {"+": "正向", "-": "反向"}[arrow]
        return f"{axis_labels.get(axis, axis)}（{direction}）"
    return source


def describe_action(action: str) -> str:
    if not action or action == "none":
        return "不输出"
    if action.startswith("keyboard:"):
        return "按键 " + action[len("keyboard:"):]
    if action.startswith("virtual:"):
        return "虚拟手柄 " + action[len("virtual:"):]
    return action


@dataclass
class Binding:
    source: str
    action: str = "none"
    threshold: float = 0.55

    def to_dict(self) -> dict:
        data = {"source": self.source, "action": self.action}
        if self.action.startswith("axis") or ":" in self.source:
            data["threshold"] = round(self.threshold, 3)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Binding":
        return cls(
            source=str(data.get("source", "")),
            action=str(data.get("action", "none")),
            threshold=float(data.get("threshold", 0.55)),
        )


@dataclass
class MappingProfile:
    name: str = "新建映射方案"
    target: str = "monitor"
    deadzone: float = 0.18
    invert_axes: List[str] = field(default_factory=lambda: ["ly", "ry"])
    bindings: List[Binding] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list, compare=False)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "name": self.name,
            "target": self.target,
            "deadzone": round(self.deadzone, 3),
            "invert_axes": list(self.invert_axes),
            "bindings": [b.to_dict() for b in self.bindings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MappingProfile":
        if not isinstance(data, dict):
            raise ValueError("映射方案必须是 JSON 对象")
        schema = data.get("schema")
        if schema and schema != SCHEMA:
            raise ValueError(f"不支持的方案版本：{schema}")
        target = str(data.get("target", "monitor"))
        if target not in TARGETS:
            target = "monitor"
        profile = cls(
            name=str(data.get("name", "未命名方案")),
            target=target,
            deadzone=max(0.0, min(0.8, float(data.get("deadzone", 0.18)))),
            invert_axes=[a for a in data.get("invert_axes", ["ly", "ry"]) if a in SEMANTIC_AXES],
            bindings=[Binding.from_dict(b) for b in data.get("bindings", []) if isinstance(b, dict)],
        )
        profile.validate()
        return profile
    def validate(self) -> List[str]:
        """返回警告列表；无法修复的字段会被就地修正."""
        warnings: List[str] = []
        valid_sources = set(all_sources())
        cleaned: List[Binding] = []
        for binding in self.bindings:
            if binding.source not in valid_sources:
                warnings.append(f"未知来源 {binding.source}，已忽略")
                continue
            if binding.action.startswith("keyboard:"):
                key = binding.action[len("keyboard:"):]
                if not _valid_key_combo(key):
                    warnings.append(f"未知按键 {key}，已改为不输出")
                    binding.action = "none"
            cleaned.append(binding)
        self.bindings = cleaned
        self.warnings = warnings
        return warnings

    # ---------------------------------------------------------------- 文件
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "MappingProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    # ---------------------------------------------------------------- 换算
    def resolved_axes(self, state: PadState) -> Dict[str, float]:
        """应用死区与反转后的摇杆/扳机值."""
        axes = {}
        for name in ("lx", "ly", "rx", "ry"):
            value = state.axis(name)
            if name in self.invert_axes:
                value = -value
            axes[name] = value
        left_x, left_y = radial_deadzone(axes["lx"], axes["ly"], self.deadzone)
        right_x, right_y = radial_deadzone(axes["rx"], axes["ry"], self.deadzone)
        axes["lx"], axes["ly"] = left_x, left_y
        axes["rx"], axes["ry"] = right_x, right_y
        axes["lt"] = state.axis("lt")
        axes["rt"] = state.axis("rt")
        return axes

    def active_sources(self, state: PadState) -> Dict[str, float]:
        """当前被触发的源事件 -> 强度（0..1）。按钮为 1.0."""
        axes = self.resolved_axes(state)
        active: Dict[str, float] = {}
        for name in SEMANTIC_BUTTONS:
            if state.button(name):
                active[f"button:{name}"] = 1.0
        for name in ("lx", "ly", "rx", "ry"):
            if axes[name] > 0:
                active[f"axis:{name}:+"] = abs(axes[name])
            elif axes[name] < 0 and name in ("lx", "ly", "rx", "ry"):
                active[f"axis:{name}:-"] = abs(axes[name])
        for name in ("lt", "rt"):
            if axes[name] > 0.01:
                active[f"axis:{name}:+"] = axes[name]
        return active

    def evaluate(self, state: PadState) -> Dict[str, float]:
        """返回本次帧应当生效的输出动作 -> 强度."""
        active = self.active_sources(state)
        outputs: Dict[str, float] = {}
        for binding in self.bindings:
            if binding.action == "none":
                continue
            strength = active.get(binding.source, 0.0)
            if binding.source.startswith(SOURCE_PREFIX_AXIS):
                strength = strength if strength >= binding.threshold else 0.0
            if strength <= 0.0:
                continue
            outputs[binding.action] = max(outputs.get(binding.action, 0.0), strength)
        return outputs


def _valid_key_combo(combo: str) -> bool:
    if not combo:
        return False
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    return all(p.upper() in KEYBOARD_KEYS or p in KEYBOARD_KEYS for p in parts)


def detect_capture(previous: Optional[PadState], current: PadState, deadzone: float) -> Optional[str]:
    """在"捕获按键"模式下，返回刚刚触发/越过阈值的源事件."""
    if previous is None:
        return None
    for name in SEMANTIC_BUTTONS:
        if current.button(name) and not previous.button(name):
            return f"button:{name}"
    for axis in ("lx", "ly", "rx", "ry"):
        before = previous.axis(axis)
        after = current.axis(axis)
        if abs(after) > deadzone and abs(after) - abs(before) > 0.25:
            return f"axis:{axis}:{'+' if after > 0 else '-'}"
    for axis in ("lt", "rt"):
        before = previous.axis(axis)
        after = current.axis(axis)
        if after > 0.35 > before:
            return f"axis:{axis}:+"
    return None


def load_builtin_profiles(directory: Path) -> List[MappingProfile]:
    """读取随程序分发的示例方案，出错时跳过."""
    profiles: List[MappingProfile] = []
    if not Path(directory).is_dir():
        return profiles
    for path in sorted(Path(directory).glob("*.json")):
        try:
            profiles.append(MappingProfile.load(path))
        except Exception:
            continue
    return profiles
