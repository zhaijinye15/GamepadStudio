"""摇杆校准页：自动采集零点/行程、死区与曲线、漂移过滤、扳机校准、方案存取."""
from __future__ import annotations

import time
from typing import Optional

import pygame

from .. import theme
from ...core.calibration import (
    CURVE_KEYS,
    CURVE_OPTIONS,
    StickSampler,
    TriggerSampler,
)


class CalibrationScreen:
    """即时模式页面：所有参数直接读写 app.calibration."""

    def __init__(self, app) -> None:
        self.app = app
        self.target: Optional[str] = None      # left / right / lt / rt
        self.stage: str = ""                   # center / span / trigger
        self.stage_started = 0.0
        self.stage_length = 0.0
        self.stick_sampler: Optional[StickSampler] = None
        self.trigger_sampler: Optional[TriggerSampler] = None
        self.label_text = ""
        self.selected_profile = 0
        self.tick = 0

    # ------------------------------------------------------------------ 采样
    def handle_event(self, event) -> None:
        return

    def update(self, dt: float) -> None:
        if not self.target:
            return
        self.tick += 1
        elapsed = time.monotonic() - self.stage_started
        raw = getattr(self.app, "raw_semantic", None) or {}
        if self.stage == "center" and self.stick_sampler is not None:
            if "lx" in raw:
                if self.target == "left":
                    self.stick_sampler.feed_center(raw.get("lx", 0.0), raw.get("ly", 0.0))
                else:
                    self.stick_sampler.feed_center(raw.get("rx", 0.0), raw.get("ry", 0.0))
            if elapsed >= self.stage_length:
                self.stick_sampler.finish_center()
                self.stage = "span"
                self.stage_started = time.monotonic()
                self.stage_length = 4.0
        elif self.stage == "span" and self.stick_sampler is not None:
            if "lx" in raw:
                if self.target == "left":
                    self.stick_sampler.feed_span(raw.get("lx", 0.0), raw.get("ly", 0.0))
                else:
                    self.stick_sampler.feed_span(raw.get("rx", 0.0), raw.get("ry", 0.0))
            if elapsed >= self.stage_length:
                center = self.stick_sampler.center or (0.0, 0.0)
                span = self.stick_sampler.finish_span()
                stick = self.app.calibration.stick(self.target)
                stick.center_x, stick.center_y = center
                stick.span_x, stick.span_y = span
                stick.calibrated = True
                self.app.mark_calibration_dirty()
                self.app.set_status(f"{self._target_label()} 校准完成")
                self._finish_stage()
        elif self.stage == "trigger" and self.trigger_sampler is not None:
            key = "lt" if self.target == "lt" else "rt"
            if key in raw:
                self.trigger_sampler.feed(raw.get(key, 0.0))
            if elapsed >= self.stage_length:
                low, high = self.trigger_sampler.result()
                trigger = self.app.calibration.trigger(self.target)
                trigger.min_raw, trigger.max_raw = low, high
                trigger.calibrated = True
                self.app.mark_calibration_dirty()
                self.app.set_status(f"{self._target_label()} 校准完成")
                self._finish_stage()

    def _finish_stage(self) -> None:
        self.target = None
        self.stage = ""
        self.stick_sampler = None
        self.trigger_sampler = None

    def _target_label(self) -> str:
        return {"left": "左摇杆", "right": "右摇杆", "lt": "LT 扳机", "rt": "RT 扳机"}.get(
            self.target or "", "摇杆")

    def _start_stick(self, which: str) -> None:
        if self.app.device is None:
            self.app.set_status("先连接手柄再校准")
            return
        self.target = which
        self.stage = "center"
        self.stage_started = time.monotonic()
        self.stage_length = 2.0
        self.stick_sampler = StickSampler("lx" if which == "left" else "rx",
                                          "ly" if which == "left" else "ry")
        self.stick_sampler.start_center()
        self.app.set_status(f"松开{self._target_label()}，保持静止 2 秒")

    def _start_trigger(self, which: str) -> None:
        if self.app.device is None:
            self.app.set_status("先连接手柄再校准")
            return
        self.target = which
        self.stage = "trigger"
        self.stage_started = time.monotonic()
        self.stage_length = 4.0
        self.trigger_sampler = TriggerSampler()
        self.app.set_status(f"把{self._target_label()}松开再踩到底，重复几次")

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        gap = 12
        top_h = int((rect.height - gap) * 0.62)
        left_w = int((rect.width - gap) * 0.5)
        left_card = pygame.Rect(rect.x, rect.y, left_w, top_h)
        right_card = pygame.Rect(left_card.right + gap, rect.y, rect.width - left_w - gap, top_h)
        trigger_card = pygame.Rect(rect.x, left_card.bottom + gap, left_w,
                                   rect.height - top_h - gap)
        profile_card = pygame.Rect(trigger_card.right + gap, left_card.bottom + gap,
                                   rect.width - left_w - gap, rect.height - top_h - gap)

        self._draw_stick(ui, left_card, "left")
        self._draw_stick(ui, right_card, "right")
        self._draw_triggers(ui, trigger_card)
        self._draw_profiles(ui, profile_card)

    # ---------------------------------------------------------------- 摇杆卡
    def _draw_stick(self, ui, rect: pygame.Rect, which: str) -> None:
        app = self.app
        surface = ui.surface
        stick = app.calibration.stick(which)
        title = "左摇杆" if which == "left" else "右摇杆"
        state_note = "已校准" if stick.calibrated else "未校准"
        inner = ui.card(rect, title, f"{state_note} · 死区 {stick.deadzone:.2f} · 曲线 {CURVE_OPTIONS[CURVE_KEYS.index(stick.curve)]}")

        # 实时读数
        raw = getattr(app, "raw_semantic", None) or {}
        x_raw = raw.get("lx" if which == "left" else "rx", 0.0)
        y_raw = raw.get("ly" if which == "left" else "ry", 0.0)
        out = app.pad_state.semantic_axes if app.pad_state else {}
        x_out = out.get("lx" if which == "left" else "rx", 0.0)
        y_out = out.get("ly" if which == "left" else "ry", 0.0)

        font = ui.fonts.get(12)
        theme.draw_text(surface, font, f"原始  X {x_raw:+.2f}  Y {y_raw:+.2f}",
                        (inner.x, inner.y), theme.TEXT_MUTED)
        theme.draw_text(surface, ui.fonts.get(12, bold=True), f"校准后  X {x_out:+.2f}  Y {y_out:+.2f}",
                        (inner.x, inner.y + 18), theme.ACCENT)

        # 视觉小球
        radius = 44
        cx = inner.x + radius + 6
        cy = inner.y + 42 + radius
        pygame.draw.circle(surface, theme.PANEL_ALT, (cx, cy), radius)
        pygame.draw.circle(surface, theme.BORDER, (cx, cy), radius, 1)
        pygame.draw.circle(surface, theme.BORDER_SOFT, (cx, cy), int(radius * (1 - stick.deadzone)), 1)
        px = cx + int(x_out * (radius - 8))
        py = cy + int(y_out * (radius - 8))
        pygame.draw.circle(surface, theme.ACCENT, (px, py), 7)
        theme.draw_text(surface, ui.fonts.get(11), "虚线=死区", (cx, cy + radius + 12),
                        theme.TEXT_MUTED, align="center")

        # 控件
        x0 = cx + radius + 20
        width = rect.right - 18 - x0
        y = inner.y + 40
        stick.deadzone = ui.slider(f"cal_dz_{which}", pygame.Rect(x0, y, width, 22),
                                   stick.deadzone, 0.0, 0.6, 0.01, lambda v: f"死区 {v:.2f}")
        y += 26
        stick.drift = ui.slider(f"cal_drift_{which}", pygame.Rect(x0, y, width, 22),
                                stick.drift, 0.0, 0.20, 0.005, lambda v: f"漂移过滤 {v:.3f}")
        y += 26
        index = CURVE_KEYS.index(stick.curve) if stick.curve in CURVE_KEYS else 0
        new_index = ui.dropdown(f"cal_curve_{which}", pygame.Rect(x0, y, width, 30),
                                CURVE_OPTIONS, index)
        if new_index != index:
            stick.curve = CURVE_KEYS[new_index]
            app.mark_calibration_dirty()
        y += 36
        if stick.curve != "linear":
            stick.power = ui.slider(f"cal_power_{which}", pygame.Rect(x0, y, width, 22),
                                    stick.power, 1.0, 4.0, 0.05, lambda v: f"强度 {v:.1f}")
            y += 26

        toggles_y = inner.bottom - 66
        if ui.toggle(f"cal_invx_{which}", pygame.Rect(x0, toggles_y, 130, 24), stick.invert_x, "X 反向"):
            stick.invert_x = not stick.invert_x
            app.mark_calibration_dirty()
        if ui.toggle(f"cal_invy_{which}", pygame.Rect(x0 + 140, toggles_y, 130, 24), stick.invert_y, "Y 反向"):
            stick.invert_y = not stick.invert_y
            app.mark_calibration_dirty()

        buttons_y = inner.bottom - 34
        busy = self.target == which
        if ui.button(f"cal_auto_{which}", pygame.Rect(x0, buttons_y, width - 96, 32),
                     "校准中…" if busy else "自动校准", kind="primary", enabled=not busy,
                     font_size=13):
            self._start_stick(which)
        if ui.button(f"cal_reset_{which}", pygame.Rect(x0 + width - 88, buttons_y, 88, 32),
                     "重置", kind="ghost", font_size=12):
            stick.reset_calibration()
            app.mark_calibration_dirty()
            app.set_status(f"{title} 已恢复默认校准")

    # ---------------------------------------------------------------- 扳机卡
    def _draw_triggers(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "扳机校准", "单独校准行程端点 · 可反向（适合赛车油门/刹车互换）")
        raw = getattr(app, "raw_semantic", None) or {}
        out = app.pad_state.semantic_axes if app.pad_state else {}
        y = inner.y
        for key, title in (("lt", "LT 左扳机"), ("rt", "RT 右扳机")):
            trigger = app.calibration.trigger(key)
            value_out = out.get(key, 0.0)
            value_raw = raw.get(key, 0.0)
            theme.draw_text(surface, ui.fonts.get(13, bold=True), title, (inner.x, y), theme.TEXT)
            theme.draw_text(surface, ui.fonts.get(11),
                            f"原始 {value_raw:.2f} → 校准 {value_out:.2f}"
                            + (f" · 行程 {trigger.min_raw:.2f}~{trigger.max_raw:.2f}" if trigger.calibrated else ""),
                            (inner.x + 102, y + 2), theme.TEXT_MUTED)
            y += 22
            ui.progress_bar(pygame.Rect(inner.x, y, inner.width - 210, 8), value_out)
            y += 14
            busy = self.target == key
            if ui.button(f"cal_trig_{key}", pygame.Rect(inner.x, y, 92, 28),
                         "校准中…" if busy else "校准行程", kind="default", enabled=not busy,
                         font_size=12):
                self._start_trigger(key)
            if ui.toggle(f"cal_trig_inv_{key}", pygame.Rect(inner.x + 100, y, 118, 24),
                         trigger.invert, "反向"):
                trigger.invert = not trigger.invert
                app.mark_calibration_dirty()
            trigger.deadzone = ui.slider(f"cal_trig_dz_{key}", pygame.Rect(inner.x + 226, y, inner.width - 226, 20),
                                         trigger.deadzone, 0.0, 0.3, 0.01, lambda v: f"{v:.2f}")
            y += 40

        if self.target:
            remain = max(0.0, self.stage_length - (time.monotonic() - self.stage_started))
            note = {"center": "保持摇杆静止", "span": "把摇杆推到最大并转圈",
                    "trigger": "反复松开/踩到底"}.get(self.stage, "")
            theme.draw_text(surface, ui.fonts.get(12, bold=True),
                            f"正在采集{self._target_label()}：{note}（剩 {remain:.1f}s）",
                            (inner.x, inner.bottom - 16), theme.ACCENT)

    # ---------------------------------------------------------------- 方案卡
    def _draw_profiles(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        store = app.cal_store
        profiles = store.profiles
        matched = store.match(app.device)
        note = f"当前手柄匹配：{matched.label or matched.device_name}" if matched else "当前手柄还没有已保存方案"
        inner = ui.card(rect, "配置方案", note)

        labels = [p.label or p.device_name or p.id for p in profiles]
        if not labels:
            labels = ["（暂无已保存方案）"]
        self.selected_profile = max(0, min(self.selected_profile, len(labels) - 1))
        new_index = ui.dropdown("cal_prof_list", pygame.Rect(inner.x, inner.y, inner.width - 96, 32),
                                labels, self.selected_profile)
        if new_index != self.selected_profile:
            self.selected_profile = new_index
        load_clicked = ui.button("cal_prof_load", pygame.Rect(inner.right - 88, inner.y, 88, 32),
                                 "载入", kind="default", enabled=bool(profiles), font_size=13)
        y = inner.y + 42

        self.label_text = ui.text_input("cal_prof_name", pygame.Rect(inner.x, y, inner.width - 96, 30),
                                        self.label_text, "方案名（留空则用手柄型号）", 32)
        save_clicked = ui.button("cal_prof_save", pygame.Rect(inner.right - 88, y, 88, 30),
                                 "保存", kind="primary", font_size=13, enabled=app.device is not None)
        y += 40

        if load_clicked and profiles:
            profile = profiles[self.selected_profile]
            app.calibration = profile.calibration
            app.set_status(f"已载入方案：{profile.label or profile.device_name}")
        if save_clicked:
            app.save_calibration_profile(self.label_text.strip())
            self.label_text = ""

        dirty = app.calibration_dirty
        theme.draw_text(surface, ui.fonts.get(11),
                        "未保存的改动" if dirty else "已与方案同步",
                        (inner.x, y), theme.WARN if dirty else theme.TEXT_MUTED)
        y += 20
        if ui.button("cal_prof_export", pygame.Rect(inner.x, y, (inner.width - 8) // 2, 30),
                     "导出 JSON", kind="ghost", font_size=12):
            app.export_calibration()
        if ui.button("cal_prof_import", pygame.Rect(inner.x + (inner.width - 8) // 2 + 8, y,
                                                    (inner.width - 8) // 2, 30),
                     "导入 JSON", kind="ghost", font_size=12):
            app.import_calibration()

        y += 38
        if ui.button("cal_prof_reset_all", pygame.Rect(inner.x, y, (inner.width - 8) // 2, 28),
                     "全部恢复默认", kind="danger", font_size=12):
            app.calibration.reset()
            app.mark_calibration_dirty()
            app.set_status("已恢复默认校准参数")
        if ui.button("cal_prof_delete", pygame.Rect(inner.x + (inner.width - 8) // 2 + 8, y,
                                                    (inner.width - 8) // 2, 28),
                     "删除当前方案", kind="danger", font_size=12, enabled=bool(profiles)):
            profile = profiles[self.selected_profile] if profiles else None
            if profile is not None and app.cal_store.delete(profile.id):
                self.selected_profile = 0
                app.set_status(f"已删除方案：{profile.label or profile.device_name}")
