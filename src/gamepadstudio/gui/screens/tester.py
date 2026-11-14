"""测试台页：设备信息、摇杆、按键、扳机与原始通道实时显示."""
from __future__ import annotations

from collections import deque
from typing import List, Tuple

import pygame

from .. import theme
from ...core import layouts as layout_defs
from ...core.model import SEMANTIC_BUTTONS, describe_button


class TesterScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.left_trail: deque = deque(maxlen=120)
        self.right_trail: deque = deque(maxlen=120)
        self.trigger_history: dict = {"lt": deque(maxlen=90), "rt": deque(maxlen=90)}

    def handle_event(self, event) -> None:
        return

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        card_gap = 12
        header_h = 96
        device_card = pygame.Rect(rect.x, rect.y, rect.width, header_h)
        self._draw_device_card(ui, device_card)

        top = device_card.bottom + card_gap
        available = rect.bottom - top - card_gap
        row1_h = int(available * 0.56)
        row2_h = available - row1_h - card_gap
        left_w = int(rect.width * 0.46)
        right_w = rect.width - left_w - card_gap

        sticks_rect = pygame.Rect(rect.x, top, left_w, row1_h)
        buttons_rect = pygame.Rect(sticks_rect.right + card_gap, top, right_w, row1_h)
        triggers_rect = pygame.Rect(rect.x, sticks_rect.bottom + card_gap, left_w, row2_h)
        raw_rect = pygame.Rect(triggers_rect.right + card_gap, sticks_rect.bottom + card_gap, right_w, row2_h)

        self._draw_sticks(ui, sticks_rect)
        self._draw_buttons(ui, buttons_rect)
        self._draw_triggers(ui, triggers_rect)
        self._draw_raw(ui, raw_rect)

    # ---------------------------------------------------------------- 设备卡片
    def _draw_device_card(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        device = app.device
        state = app.pad_state

        # 左侧状态指示
        online = device is not None and state is not None
        dot_color = theme.ACCENT if online else theme.TEXT_MUTED
        pulse = 0
        if online and state.any_activity():
            pulse = 4
        halo = theme.lerp_color(theme.PANEL, dot_color, 0.22)
        pygame.draw.circle(surface, halo, (rect.x + 34, rect.y + 36), 16 + pulse)
        pygame.draw.circle(surface, dot_color, (rect.x + 34, rect.y + 36), 9)

        name = device.name if device else "等待手柄连接"
        theme.draw_text(surface, ui.fonts.get(18, bold=True), name, (rect.x + 58, rect.y + 20), theme.TEXT)
        info_font = ui.fonts.get(12)
        if device is not None:
            meta = (f"{device.backend.upper()} · {device.describe_transport()} · "
                    f"{device.describe_layout()} · {device.buttons} 键 / {device.axes} 轴")
        else:
            meta = "USB 直连或蓝牙配对后会自动出现在左侧设备列表"
        theme.draw_text(surface, info_font, meta, (rect.x + 60, rect.y + 44), theme.TEXT_MUTED)

        # 标签
        x = rect.x + 60
        y = rect.y + 64
        if device is not None:
            x = ui.badge((x, y), app.rumble.describe_device(), theme.TEXT_DIM).right + 8
            if device.battery is not None:
                battery_text = f"电量 {int(device.battery * 100)}%"
                x = ui.badge((x, y), battery_text,
                             theme.ACCENT if device.battery > 0.3 else theme.WARN).right + 8
        if state is not None:
            x = ui.badge((x, y), f"轮询 {app.poll_rate:.0f} Hz", theme.TEXT_DIM).right + 8
        if device is not None and state is None:
            ui.badge((x, y), "等待数据…", theme.WARN)

        # 右侧操作
        button_y = rect.y + 26
        if device is not None:
            if ui.button("tester_rumble", pygame.Rect(rect.right - 300, button_y, 132, 38),
                         "震动自检", kind="primary"):
                ok = app.rumble.pulse(0.7, 0.9, 140)
                app.set_status("已发送震动指令" if ok else "该手柄未响应震动指令")
        if ui.button("tester_refresh", pygame.Rect(rect.right - 160, button_y, 132, 38), "重新扫描", kind="default"):
            app.manager.refresh(force=True)
            app._select_first_device()
            app.set_status("已重新扫描设备")

    # ---------------------------------------------------------------- 摇杆
    def _draw_sticks(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "摇杆", "拖动摇杆看圆点是否跟随 · 虚线为死区")
        state = app.pad_state
        axes = app.profile.resolved_axes(state) if state else {k: 0.0 for k in ("lx", "ly", "rx", "ry")}
        self.left_trail.append((axes["lx"], axes["ly"]))
        self.right_trail.append((axes["rx"], axes["ry"]))

        half = inner.width // 2
        radius = min(half - 24, (inner.height - 74) // 2)
        radius = max(46, radius)
        center_left = (inner.x + half // 2, inner.y + 8 + radius)
        center_right = (inner.x + half + half // 2, inner.y + 8 + radius)

        for center, (x, y), trail, axis_x, axis_y in (
            (center_left, (axes["lx"], axes["ly"]), self.left_trail, "LX", "LY"),
            (center_right, (axes["rx"], axes["ry"]), self.right_trail, "RX", "RY"),
        ):
            pygame.draw.circle(surface, theme.PANEL_ALT, center, radius)
            pygame.draw.circle(surface, theme.BORDER_SOFT, center, radius, 1)
            # 十字准线
            pygame.draw.line(surface, theme.BORDER_SOFT, (center[0] - radius, center[1]),
                             (center[0] + radius, center[1]), 1)
            pygame.draw.line(surface, theme.BORDER_SOFT, (center[0], center[1] - radius),
                             (center[0], center[1] + radius), 1)
            # 死区圈
            deadzone_radius = int(radius * app.profile.deadzone)
            if deadzone_radius > 4:
                pygame.draw.circle(surface, theme.BORDER, center, deadzone_radius, 1)
            # 轨迹
            if len(trail) > 2:
                points = [(center[0] + px * radius, center[1] - py * radius) for px, py in trail]
                pygame.draw.lines(surface, (36, 78, 66), False, points, 2)
            dot = (center[0] + x * radius, center[1] - y * radius)
            pygame.draw.circle(surface, (18, 24, 22), dot, 11)
            pygame.draw.circle(surface, theme.ACCENT, dot, 8)

            # 轴名标注在圆内顶部
            small = ui.fonts.get(10)
            theme.draw_text(surface, small, f"{axis_x} / {axis_y}", (center[0], center[1] - radius + 12),
                            theme.TEXT_MUTED, align="midtop")
            theme.draw_text(surface, ui.fonts.get(13, bold=True), f"{x:+.2f} / {y:+.2f}",
                            (center[0], center[1] + radius + 12), theme.TEXT_DIM, align="midtop")

    # ---------------------------------------------------------------- 按键
    def _draw_buttons(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "按键状态", "按下手柄按键，对应方块亮起")
        device = app.device
        state = app.pad_state
        labels = layout_defs.labels_for(device.layout if device else "generic")

        columns = 4
        gap = 8
        chip_w = (inner.width - gap * (columns - 1)) // columns
        rows = (
            ("lt", "rt"),
            ("lb", "rb"),
            ("a", "b", "x", "y"),
            ("up", "left", "down", "right"),
            ("back", "start", "guide"),
            ("l3", "r3"),
        )
        chip_h = (inner.height - gap * (len(rows) - 1)) // len(rows)
        for row_index, row_names in enumerate(rows):
            for column, name in enumerate(row_names):
                chip = pygame.Rect(inner.x + column * (chip_w + gap),
                                   inner.y + row_index * (chip_h + gap), chip_w, chip_h)
                pressed = bool(state and state.button(name))
                self._draw_chip(ui, chip, labels.get(name, describe_button(name)), pressed,
                                sub=self._raw_channel(device, name))

    def _raw_channel(self, device, name: str) -> str:
        if device is None:
            return ""
        if device.backend == "hid":
            return "HID"
        try:
            if device.button_map and name in device.button_map:
                return f"B{device.button_map[name]}"
            from ...core.layouts import SDL_BUTTON_SEMANTIC

            for index, semantic in SDL_BUTTON_SEMANTIC.items():
                if semantic == name:
                    return f"B{index}"
        except Exception:
            return ""
        return ""

    def _draw_chip(self, ui, rect: pygame.Rect, label: str, pressed: bool, sub: str = "") -> None:
        surface = ui.surface
        if pressed:
            bg = (26, 62, 50)
            border = theme.ACCENT
            glow = pygame.Rect(rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4)
            theme.rounded_rect(surface, glow, (34, 92, 74), radius=12)
            theme.rounded_rect(surface, rect, bg, radius=10, border=border)
        else:
            theme.rounded_rect(surface, rect, theme.PANEL_ALT, radius=10, border=theme.BORDER_SOFT)
        font = ui.fonts.get(13, bold=True)
        color = theme.ACCENT if pressed else theme.TEXT
        if sub:
            # 序号贴在右侧小字，避免与上下行挤在一起
            theme.draw_text(surface, font, label, (rect.centerx - 9, rect.centery),
                            color, align="center")
            theme.draw_text(surface, ui.fonts.get(10), sub, (rect.right - 9, rect.centery + 1),
                            theme.ACCENT if pressed else theme.TEXT_MUTED, align="midright")
        else:
            theme.draw_text(surface, font, label, (rect.centerx, rect.centery), color, align="center")

    # ---------------------------------------------------------------- 扳机
    def _draw_triggers(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "扳机行程", "0 → 1 线性行程 · 支持模拟量与开关量")
        state = app.pad_state
        values = {"lt": state.axis("lt") if state else 0.0, "rt": state.axis("rt") if state else 0.0}
        self.trigger_history["lt"].append(values["lt"])
        self.trigger_history["rt"].append(values["rt"])

        row_h = inner.height // 2
        for index, (key, label) in enumerate((("lt", "LT / L2"), ("rt", "RT / R2"))):
            row = pygame.Rect(inner.x, inner.y + index * row_h, inner.width, row_h - 6)
            theme.draw_text(surface, ui.fonts.get(12, bold=True), label, (row.x, row.centery - 8),
                            theme.TEXT_DIM, align="midleft")
            bar = pygame.Rect(row.x + 58, row.centery - 4, row.width - 130, 9)
            ui.progress_bar(bar, values[key], color=theme.BLUE if key == "lt" else theme.PURPLE,
                            show_value=False, height=9)
            theme.draw_text(surface, ui.fonts.get(13, bold=True), f"{values[key]:.2f}",
                            (row.right, row.centery), theme.TEXT, align="midright")
            # 迷你波形
            history = list(self.trigger_history[key])
            if len(history) > 2:
                points = []
                for i, value in enumerate(history):
                    px = bar.x + int(bar.width * i / max(1, len(history) - 1))
                    py = bar.y - 14 - int(value * 10)
                    points.append((px, py))
                pygame.draw.lines(surface, (52, 62, 78), False, points, 1)

    # ---------------------------------------------------------------- 原始通道
    def _draw_raw(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "原始通道", "排查校准 / 死区问题的底层数据")
        device = app.device
        state = app.pad_state
        if state is None:
            theme.draw_text(surface, ui.fonts.get(13), "暂无数据", inner.center, theme.TEXT_MUTED, align="center")
            return
        axes = sorted(state.axes.items(), key=lambda item: item[0])
        max_rows = 5
        columns = 2 if len(axes) > max_rows else 1
        row_h = 22
        for index, (name, value) in enumerate(axes[:max_rows * columns]):
            column = index // max_rows
            row = index % max_rows
            x = inner.x + column * (inner.width // columns)
            y = inner.y + row * row_h
            width = inner.width // columns - 12
            theme.draw_text(surface, ui.fonts.get(11), name.upper(), (x, y + 4), theme.TEXT_MUTED)
            bar = pygame.Rect(x + 34, y + 6, width - 96, 8)
            normalized = (value + 1.0) / 2.0 if name in ("a4", "a5") else (value + 1.0) / 2.0
            ui.progress_bar(bar, normalized, color=theme.BORDER, bg=theme.PANEL_ALT, show_value=False, height=8)
            theme.draw_text(surface, ui.fonts.get(11), f"{value:+.2f}", (x + width, y + 4),
                            theme.TEXT_DIM, align="topright")

        # 底部：hat / 按键 / 事件
        footer_y = inner.bottom - 26
        pygame.draw.line(surface, theme.BORDER_SOFT, (inner.x, footer_y - 8), (inner.right, footer_y - 8))
        hat = state.hats
        theme.draw_text(surface, ui.fonts.get(11), f"HAT ({hat[0]},{hat[1]})",
                        (inner.x, footer_y), theme.TEXT_MUTED)
        pressed = ", ".join(name.upper() for name in state.pressed_semantic()[:4]) or "无"
        theme.draw_text(surface, ui.fonts.get(11), f"按下：{pressed}", (inner.x + 96, footer_y), theme.TEXT_MUTED)

        events = app.recent_events[:3]
        if events:
            text = " · ".join(item[1] for item in reversed(events))
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(ui.fonts.get(11), text, inner.width - 260),
                            (inner.right, footer_y), theme.TEXT_MUTED, align="topright")
