"""Nintendo Switch 手柄（Joy-Con / Pro Controller）HID 协议实现.

参考来源（仅用于协议字段对照，本文件为独立实现）:

* Nintendo_Switch_Reverse_Engineering —— ``rumble_data_table.md`` 中给出的
  频率/振幅编码公式，以及标准输入报文 0x30 的字节布局。
* joycon-python (ytai/pyjoycon) —— 输出报文 0x01 的子命令握手流程。

协议要点
--------
输入报文 0x21（simple HID）/ 0x30（standard full）共用同一段前置布局::

    0        报告 ID
    1        计数器
    2        电量(bit5-7) / 充电(bit4) / 连接状态(bit0-3)
    3        按键组 1：Y X B A SR SL R ZR          (右 Joy-Con 面键)
    4        按键组 2：Minus Plus R-Stick L-Stick Home Capture _ ChargingGrip
    5        按键组 3：Down Up Right Left SR SL L ZL
    6..8     左摇杆（X 低 8 位 + X 高 4 位 / Y 低 4 位 + Y 高 8 位）
    9..11    右摇杆（同上）

输出报文 0x10（仅震动）::

    0        0x10
    1..8     震动数据：4 字节 × 2 组（两组交替发送，音圈需要交替驱动）
    9..63    0
"""
from __future__ import annotations

import math
from typing import Dict, Tuple

VENDOR_ID = 0x057E

PRODUCT_NAMES: Dict[int, str] = {
    0x2006: "Joy-Con (L)",
    0x2007: "Joy-Con (R)",
    0x2009: "Switch Pro Controller",
    0x200E: "Joy-Con Charging Grip",
    0x2017: "Nintendo Switch 2 Pro Controller",
}

JOYCON_L = 0x2006
JOYCON_R = 0x2007
PRO_CONTROLLER = 0x2009

INPUT_REPORT_IDS = (0x21, 0x30, 0x31, 0x3F)
NEUTRAL_RUMBLE = b"\x00\x01\x40\x40"
_REPORT_SIZE = 64

#: 语义按键名 -> 报告中的 (字节偏移, 位序号)
BUTTON_BITS: Dict[str, Tuple[int, int]] = {
    # 面键
    "y": (3, 0), "x": (3, 1), "b": (3, 2), "a": (3, 3),
    "rb": (3, 6), "rt": (3, 7),
    # 系统键
    "start": (4, 1), "back": (4, 0),
    "r3": (4, 2), "l3": (4, 3),
    "guide": (4, 4),
    # 十字键与肩键
    "down": (5, 0), "up": (5, 1), "right": (5, 2), "left": (5, 3),
    "lb": (5, 6), "lt": (5, 7),
}


def is_nintendo(vendor_id: int, product_id: int) -> bool:
    return vendor_id == VENDOR_ID and product_id in PRODUCT_NAMES


def device_name(product_id: int) -> str:
    return PRODUCT_NAMES.get(product_id, f"Nintendo 设备 0x{product_id:04X}")


def parse_report(report: bytes, product_id: int) -> Dict[str, object]:
    """解析一帧输入报文，返回原始与语义两套数据."""
    if len(report) < 12:
        return {}
    sticky = report[2]
    battery_level = (sticky >> 5) & 0x07
    charging = (sticky >> 4) & 0x01
    # 0=空 1=低 2=中低 3=中 4=中高 5=高 6=满 7=未知(充电中)
    battery_pct = {0: 0.0, 1: 0.16, 2: 0.33, 3: 0.5, 4: 0.66, 5: 0.83, 6: 1.0}.get(battery_level, 1.0)

    semantic_buttons: Dict[str, bool] = {}
    for name, (offset, bit) in BUTTON_BITS.items():
        if offset < len(report):
            semantic_buttons[name] = bool((report[offset] >> bit) & 0x01)
        else:
            semantic_buttons[name] = False

    left = _parse_stick(report[6], report[7], report[8])
    right = _parse_stick(report[9], report[10], report[11])
    if product_id in (JOYCON_L, JOYCON_R):
        # 单只 Joy-Con 只有一个摇杆
        if product_id == JOYCON_L:
            right = (0.0, 0.0)
        else:
            left = (0.0, 0.0)

    semantic_axes = {
        "lx": left[0], "ly": left[1],
        "rx": right[0], "ry": right[1],
        "lt": 1.0 if semantic_buttons.get("lt") else 0.0,
        "rt": 1.0 if semantic_buttons.get("rt") else 0.0,
    }

    raw_buttons = {f"b{i}": False for i in range(16)}
    for index, name in enumerate(("up", "down", "left", "right", "lb", "rb", "lt", "rt",
                                 "back", "start", "l3", "r3", "a", "b", "x", "y")):
        raw_buttons[f"b{index}"] = bool(semantic_buttons.get(name, False))
    raw_axes = {
        "a0": left[0], "a1": left[1], "a2": right[0], "a3": right[1],
        "a4": semantic_axes["lt"] * 2 - 1, "a5": semantic_axes["rt"] * 2 - 1,
    }
    return {
        "buttons": raw_buttons,
        "axes": raw_axes,
        "semantic_buttons": semantic_buttons,
        "semantic_axes": semantic_axes,
        "battery": battery_pct,
        "charging": bool(charging),
    }


def _parse_stick(low_byte: int, mid_byte: int, high_byte: int) -> Tuple[float, float]:
    """12 位摇杆值 -> -1..1（Y 轴硬件方向向下为正，这里翻转）."""
    x_raw = low_byte | ((mid_byte & 0x0F) << 8)
    y_raw = (mid_byte >> 4) | (high_byte << 4)
    x = (x_raw - 2048) / 2048.0
    y = (y_raw - 2048) / 2048.0
    return _clamp(x), _clamp(-y)


def _clamp(value: float) -> float:
    return -1.0 if value < -1.0 else 1.0 if value > 1.0 else value


# ----------------------------------------------------------------- 震动编码
def encode_amp(amp: float) -> int:
    """振幅 0..1 -> 编码值 0..0xFF（0 表示静默）."""
    amp = max(0.0, min(1.0, amp))
    if amp <= 0.02:
        return 0
    if amp > 0.23:
        return int(round(math.log2(amp * 8.7) * 32.0)) & 0xFF
    if amp > 0.12:
        return int(round(math.log2(amp * 17.0) * 16.0)) & 0xFF
    return int(round(math.log2(max(amp, 0.021) * 17.0) * 16.0)) & 0xFF


def encode_freq(freq_hz: float) -> Tuple[int, int]:
    """频率 -> (hf 16bit, lf 8bit)。hf 步进 4，范围 0x0004-0x01FC；lf 范围 0x01-0x7F."""
    freq = max(1.0, min(1252.0, float(freq_hz)))
    encoded = int(round(math.log2(freq / 10.0) * 32.0))
    hf = max(0x0004, min(0x01FC, (encoded - 0x60) * 4))
    lf = max(0x00, min(0x7F, encoded - 0x40))
    return hf, lf


def encode_channel(amp: float, freq_hz: float) -> bytes:
    """单个通道 4 字节震动数据（与硬件字节序一致）."""
    if amp <= 0.02:
        return NEUTRAL_RUMBLE
    encoded_amp = encode_amp(amp)
    hf, lf = encode_freq(freq_hz)
    hf_amp = (encoded_amp << 1) & 0xFFFF
    lf_amp = ((encoded_amp >> 1) + 0x40) & 0xFFFF
    byte0 = hf & 0xFF
    byte1 = ((hf_amp & 0xFF) + ((hf >> 8) & 0xFF)) & 0xFF
    byte2 = (lf + ((lf_amp >> 8) & 0xFF)) & 0xFF
    byte3 = lf_amp & 0xFF
    return bytes((byte0, byte1, byte2, byte3))


def build_rumble_report(amp: float, freq_hz: float = 160.0) -> bytes:
    """构造 64 字节的 0x10 输出报文（低频 + 高频双通道同时驱动）."""
    if amp <= 0.02:
        payload = NEUTRAL_RUMBLE + NEUTRAL_RUMBLE
    else:
        low_channel = encode_channel(amp, freq_hz)
        high_channel = encode_channel(amp * 0.85, freq_hz * 1.6)
        payload = low_channel + high_channel
    return bytes([0x10]) + payload + bytes(_REPORT_SIZE - 9)


def build_subcommand(packet_number: int, subcommand: int, argument: bytes = b"") -> bytes:
    """输出报文 0x01：震动占位 + 子命令，用于设置输入报文模式等."""
    body = NEUTRAL_RUMBLE + NEUTRAL_RUMBLE + bytes([subcommand]) + argument
    packet = bytes([0x01, packet_number & 0x0F]) + body
    return packet + bytes(_REPORT_SIZE - len(packet))


SET_INPUT_REPORT_MODE = 0x03
ENABLE_IMU = 0x40
SET_PLAYER_LIGHTS = 0x30
