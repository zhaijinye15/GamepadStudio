"""震动测试页：波形选择、强度调整与实时包络可视化."""
from __future__ import annotations

import math
import time

import pygame

from .. import theme
from ...core.rumble import PATTERNS, RumbleTest


class RumbleScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.pattern_keys = list(PATTERNS.keys())
        self.pattern_index = self.pattern_keys.index(app.settings.get("rumble_pattern", "constant")) \
            if app.settings.get("rumble_pattern") in PATTERNS else 0
        self.last_result = ""

    def handle_event(self, event) -> None:
        return

    def update(self, dt: float) -> None:
        return

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        gap = 12
        left_w = int(rect.width * 0.52)
        left = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right = pygame.Rect(left.right + gap, rect.y, rect.width - left_w - gap, rect.height)
        self._draw_visual(ui, left)
        self._draw_controls(ui, right)

    def _draw_visual(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        theme.draw_text(surface, ui.fonts.get(14, bold=True), "震动波形", (rect.x + 18, rect.y + 16), theme.TEXT)

        device = app.device
        engine = app.rumble
        status_color = theme.ACCENT if engine.supported() else theme.WARN
        status_text = engine.describe_device() if device else "未选择手柄"
        theme.draw_text(surface, ui.fonts.get(12), status_text, (rect.x + 18, rect.y + 38), status_color)

        # 波形区域
        wave = pygame.Rect(rect.x + 18, rect.y + 66, rect.width - 36, int(rect.height * 0.34))
        theme.rounded_rect(surface, wave, theme.PANEL_ALT, radius=10, border=theme.BORDER_SOFT)
        test: RumbleTest = engine.test
        bars = 56
        width_per_bar = (wave.width - 16) / bars
        elapsed = time.monotonic() - test.started_at if test.active else 0.0
        duration = max(0.1, test.duration)
        pattern = test.pattern if test.active else self.pattern_keys[self.pattern_index]
        preview = RumbleTest(pattern=pattern,
                             low=float(app.settings.get("rumble_low", 0.6)),
                             high=float(app.settings.get("rumble_high", 0.9)))
        # 网格线
        for line_index in range(1, 4):
            y_line = wave.y + int(wave.height * line_index / 4)
            pygame.draw.line(surface, theme.BORDER_SOFT, (wave.x + 8, y_line), (wave.right - 8, y_line), 1)
        for index in range(bars):
            fraction = index / bars
            low, high = engine._envelope(preview, fraction * duration)
            height = int((wave.height - 22) * min(1.0, max(low, high)))
            x = wave.x + 8 + int(index * width_per_bar)
            bar = pygame.Rect(x, wave.bottom - 11 - height, max(2, int(width_per_bar) - 3), height)
            played = test.active and fraction * duration <= elapsed
            if height <= 2:
                pygame.draw.line(surface, theme.BORDER, (bar.x, bar.y), (bar.right, bar.y), 2)
            else:
                color = theme.lerp_color(theme.ACCENT_DIM, theme.ACCENT, 0.9 if played else 0.35)
                theme.rounded_rect(surface, bar, color, radius=2)

        if test.active:
            cursor_x = wave.x + int(wave.width * min(1.0, elapsed / duration))
            pygame.draw.line(surface, theme.TEXT, (cursor_x, wave.y + 6), (cursor_x, wave.bottom - 4), 2)
            theme.draw_text(surface, ui.fonts.get(11), f"{elapsed:.1f}s / {duration:.1f}s",
                            (wave.right - 8, wave.y + 6), theme.TEXT_DIM, align="topright")

        # 后端链路说明
        y = wave.bottom + 22
        rows = [
            ("设备", device.name if device else "—"),
            ("震动通道", "HID 音圈驱动（0x10 报文）" if device and device.backend == "hid" else "SDL 触觉反馈"),
            ("当前状态", "正在震动" if test.active else "空闲"),
            ("最近指令", engine.last_backend or "—"),
        ]
        for label, value in rows:
            theme.draw_text(surface, ui.fonts.get(11), label, (rect.x + 18, y), theme.TEXT_MUTED)
            theme.draw_text(surface, ui.fonts.get(12), theme.ellipsize(ui.fonts.get(12), str(value), rect.width - 130),
                            (rect.x + 92, y), theme.TEXT_DIM)
            y += 24

        # 输出电平（实时显示当前两路通道的目标振幅）
        y += 8
        pygame.draw.line(surface, theme.BORDER_SOFT, (rect.x + 18, y), (rect.right - 18, y))
        y += 12
        theme.draw_text(surface, ui.fonts.get(12, bold=True), "输出电平", (rect.x + 18, y), theme.TEXT)
        y += 22
        current_low = current_high = 0.0
        if test.active:
            current_low, current_high = engine._envelope(test, elapsed)
        for label, value, color in (("低频通道", current_low, theme.BLUE),
                                    ("高频通道", current_high, theme.PURPLE)):
            theme.draw_text(surface, ui.fonts.get(11), label, (rect.x + 18, y), theme.TEXT_MUTED)
            bar = pygame.Rect(rect.x + 82, y + 2, rect.width - 150, 8)
            ui.progress_bar(bar, value, color=color, show_value=False, height=8)
            theme.draw_text(surface, ui.fonts.get(11), f"{value:.2f}", (rect.right - 22, y),
                            theme.TEXT_DIM, align="topright")
            y += 24

        note = ("Joy-Con / Pro Controller 使用 HD 震动协议，振幅与频率独立编码；\n"
                "Xbox 手柄走 SDL 触觉反馈，力度按左右马达拆分。")
        for index, line in enumerate(note.split("\n")):
            theme.draw_text(surface, ui.fonts.get(11), line, (rect.x + 18, rect.bottom - 46 + index * 18),
                            theme.TEXT_MUTED)

        # 测试流程
        steps = [
            "① 在左侧设备列表选择要测试的手柄",
            "② 选择波形，调整低频 / 高频强度与时长",
            "③ 点击「开始震动」，观察手柄反应",
            "④ 无反应时先看「关于」页的通道自检结果",
        ]
        sy = y + 16
        theme.draw_text(surface, ui.fonts.get(12, bold=True), "测试流程", (rect.x + 18, sy), theme.TEXT)
        sy += 22
        for step in steps:
            theme.draw_text(surface, ui.fonts.get(11), step, (rect.x + 18, sy), theme.TEXT_MUTED)
            sy += 19

    def _draw_controls(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        theme.draw_text(surface, ui.fonts.get(14, bold=True), "参数", (rect.x + 18, rect.y + 16), theme.TEXT)
        theme.draw_text(surface, ui.fonts.get(11), "先选波形，再调强度与时长",
                        (rect.x + 18, rect.y + 37), theme.TEXT_MUTED)

        x = rect.x + 18
        width = rect.width - 36
        y = rect.y + 66
        theme.draw_text(surface, ui.fonts.get(11), "预设波形", (x, y), theme.TEXT_MUTED)
        options = [PATTERNS[key] for key in self.pattern_keys]
        chosen = ui.dropdown("rumble_pattern", pygame.Rect(x, y + 18, width, 34), options, self.pattern_index)
        if chosen != self.pattern_index:
            self.pattern_index = chosen
            app.settings["rumble_pattern"] = self.pattern_keys[chosen]

        y += 66
        theme.draw_text(surface, ui.fonts.get(11), "低频（左马达 / 低频音圈）", (x, y), theme.TEXT_MUTED)
        low = ui.slider("rumble_low", pygame.Rect(x, y + 18, width, 30),
                        float(app.settings.get("rumble_low", 0.6)), 0.0, 1.0, 0.02,
                        fmt=lambda v: f"{v:.2f}")
        app.settings["rumble_low"] = low

        y += 58
        theme.draw_text(surface, ui.fonts.get(11), "高频（右马达 / 高频音圈）", (x, y), theme.TEXT_MUTED)
        high = ui.slider("rumble_high", pygame.Rect(x, y + 18, width, 30),
                         float(app.settings.get("rumble_high", 0.9)), 0.0, 1.0, 0.02,
                         fmt=lambda v: f"{v:.2f}")
        app.settings["rumble_high"] = high

        y += 58
        theme.draw_text(surface, ui.fonts.get(11), "持续时间", (x, y), theme.TEXT_MUTED)
        duration = ui.slider("rumble_duration", pygame.Rect(x, y + 18, width, 30),
                             float(app.settings.get("rumble_duration", 2.5)), 0.3, 10.0, 0.1,
                             fmt=lambda v: f"{v:.1f}s")
        app.settings["rumble_duration"] = duration

        y += 66
        active = app.rumble.test.active
        if ui.button("rumble_start", pygame.Rect(x, y, (width - 10) // 2, 40),
                     "停止震动" if active else "开始震动",
                     kind="danger" if active else "primary",
                     enabled=app.rumble.supported()):
            if active:
                app.rumble.stop()
                self.last_result = "已停止"
            else:
                ok = app.rumble.start(self.pattern_keys[self.pattern_index], low, high, duration)
                self.last_result = "已开始震动测试" if ok else "该手柄不支持震动"
                app.set_status(self.last_result)
        if ui.button("rumble_once", pygame.Rect(x + (width - 10) // 2 + 10, y, (width - 10) // 2, 40),
                     "单次脉冲 150ms", enabled=app.rumble.supported()):
            ok = app.rumble.pulse(low, high, 150)
            self.last_result = "脉冲已发送" if ok else "脉冲发送失败"
            app.set_status(self.last_result)

        y += 54
        # 单通道分测：分别验证左右马达 / 高低频音圈
        half = (width - 10) // 2
        if ui.button("rumble_low_only", pygame.Rect(x, y, half, 34), "仅低频 300ms",
                     kind="ghost", font_size=13, enabled=app.rumble.supported()):
            ok = app.rumble.pulse(low, 0.0, 300)
            self.last_result = "低频通道已触发" if ok else "低频触发失败"
            app.set_status(self.last_result)
        if ui.button("rumble_high_only", pygame.Rect(x + half + 10, y, half, 34), "仅高频 300ms",
                     kind="ghost", font_size=13, enabled=app.rumble.supported()):
            ok = app.rumble.pulse(0.0, high, 300)
            self.last_result = "高频通道已触发" if ok else "高频触发失败"
            app.set_status(self.last_result)

        y += 46
        if not app.rumble.supported():
            theme.draw_text(surface, ui.fonts.get(12), "当前手柄没有可用的震动通道",
                            (x, y), theme.WARN)
        elif self.last_result:
            theme.draw_text(surface, ui.fonts.get(12), self.last_result, (x, y), theme.TEXT_DIM)

        # 通道说明
        info_y = y + 48
        pygame.draw.line(surface, theme.BORDER_SOFT, (x, info_y), (x + width, info_y))
        info_y += 14
        theme.draw_text(surface, ui.fonts.get(12, bold=True), "各通道说明", (x, info_y), theme.TEXT)
        info_y += 24
        for title, desc in (
            ("Xbox / 通用 HID", "SDL 经 XInput 触觉接口下发，力度 0-100%"),
            ("Switch Joy-Con", "0x10 报文持续驱动音圈，振幅与频率分档编码"),
            ("虚拟手柄", "ViGEmBus 只转发游戏震动，不参与本页手动测试"),
        ):
            theme.draw_text(surface, ui.fonts.get(11, bold=True), title, (x, info_y), theme.TEXT_DIM)
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(ui.fonts.get(11), desc, width - 108),
                            (x + 104, info_y), theme.TEXT_MUTED)
            info_y += 22

        # 提示
        tips = [
            "· Joy-Con 单只使用时只有一枚音圈，左右马达合成为单通道。",
            "· 蓝牙连接时震动强度通常弱于 USB 直连，属正常现象。",
            "· 若完全无震动，先在「关于」页确认 hidapi / SDL 状态。",
        ]
        ty = info_y + 14
        pygame.draw.line(surface, theme.BORDER_SOFT, (x, ty - 8), (x + width, ty - 8))
        for index, tip in enumerate(tips):
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(ui.fonts.get(11), tip, width),
                            (x, ty + index * 19), theme.TEXT_MUTED)
