"""设备布局与原始通道到语义按键的换算.

SDL 在 Windows 上对所有手柄使用统一的 "Game Controller" 通道顺序，
因此默认映射可以直接复用；不同品牌只影响界面标签与提示文案。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# SDL Game Controller 标准按钮顺序（pygame 沿用该顺序）
SDL_BUTTON_SEMANTIC: Dict[int, str] = {
    0: "a",
    1: "b",
    2: "x",
    3: "y",
    4: "back",
    5: "guide",
    6: "start",
    7: "l3",
    8: "r3",
    9: "lb",
    10: "rb",
    11: "up",
    12: "down",
    13: "left",
    14: "right",
    15: "misc1",
    16: "paddle1",
    17: "paddle2",
    18: "paddle3",
    19: "paddle4",
    20: "touchpad",
}

SDL_AXIS_SEMANTIC: Dict[int, str] = {
    0: "lx",
    1: "ly",
    2: "rx",
    3: "ry",
    4: "lt",
    5: "rt",
}

LAYOUT_LABELS: Dict[str, Dict[str, str]] = {
    "xbox": {
        "a": "A", "b": "B", "x": "X", "y": "Y",
        "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
        "back": "View", "start": "Menu", "guide": "Xbox",
        "l3": "LS", "r3": "RS",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
    },
    "playstation": {
        "a": "✕", "b": "○", "x": "□", "y": "△",
        "lb": "L1", "rb": "R1", "lt": "L2", "rt": "R2",
        "back": "Share", "start": "Options", "guide": "PS",
        "l3": "L3", "r3": "R3",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
    },
    "switch": {
        "a": "A", "b": "B", "x": "X", "y": "Y",
        "lb": "L", "rb": "R", "lt": "ZL", "rt": "ZR",
        "back": "Minus", "start": "Plus", "guide": "Home",
        "l3": "L Stick", "r3": "R Stick",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
    },
    "generic": {
        "a": "A", "b": "B", "x": "X", "y": "Y",
        "lb": "L1", "rb": "R1", "lt": "L2", "rt": "R2",
        "back": "Back", "start": "Start", "guide": "Guide",
        "l3": "L3", "r3": "R3",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
    },
}


def labels_for(layout: str) -> Dict[str, str]:
    return LAYOUT_LABELS.get(layout, LAYOUT_LABELS["generic"])


def detect_layout(name: str) -> str:
    """根据设备名猜布局（尽力而为，识别不了就用通用布局）。"""
    lowered = (name or "").lower()
    if any(token in lowered for token in ("joy-con", "joycon", "pro controller", "nintendo", "switch")):
        return "switch"
    if any(token in lowered for token in ("xbox", "xinput", "360")):
        return "xbox"
    if any(token in lowered for token in ("dualsense", "dualshock", "playstation", "wireless controller", "ps4", "ps5")):
        return "playstation"
    return "generic"


def sdl_state(
    raw_buttons: Dict[str, bool],
    raw_axes: Dict[str, float],
    hat: Tuple[int, int],
    button_map: Optional[Dict[str, int]] = None,
    axis_map: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, bool], Dict[str, float]]:
    """把 SDL 原始通道换算成语义按键/轴.

    button_map / axis_map 来自设备自身的 SDL 绑定（见 core.sdl_bindings）：
    不同手柄的原始序号排布并不统一，传入真实绑定才能避免错位；
    拿不到绑定时退回 SDL 标准表。
    """
    semantic_buttons: Dict[str, bool] = {}
    if button_map:
        for name, index in button_map.items():
            semantic_buttons[name] = bool(raw_buttons.get(f"b{index}", False))
        for name in SDL_BUTTON_SEMANTIC.values():
            semantic_buttons.setdefault(name, False)
    else:
        for index, name in SDL_BUTTON_SEMANTIC.items():
            semantic_buttons[name] = bool(raw_buttons.get(f"b{index}", False))

    # 十字键：既可能出现在按钮位，也可能是 hat
    hx, hy = hat
    if hy > 0:
        semantic_buttons["up"] = True
    elif hy < 0:
        semantic_buttons["down"] = True
    if hx < 0:
        semantic_buttons["left"] = True
    elif hx > 0:
        semantic_buttons["right"] = True

    semantic_axes: Dict[str, float] = {}
    if axis_map:
        pairs = [(raw_index, name) for name, raw_index in axis_map.items()]
    else:
        pairs = list(SDL_AXIS_SEMANTIC.items())
    for raw_index, name in pairs:
        value = float(raw_axes.get(f"a{raw_index}", 0.0))
        if name in ("lt", "rt"):
            semantic_axes[name] = max(0.0, (value + 1.0) / 2.0)
        else:
            semantic_axes[name] = value
    return semantic_buttons, semantic_axes


def transport_from_name(name: str, guid: str) -> str:
    lowered = ((name or "") + " " + (guid or "")).lower()
    if "bluetooth" in lowered or "bt" in lowered:
        return "bluetooth"
    return "usb"


def short_guid(guid: str) -> Optional[str]:
    if not guid:
        return None
    cleaned = guid.replace("-", "")
    if len(cleaned) >= 8:
        return f"{cleaned[:8]}…{cleaned[-4:]}"
    return guid
