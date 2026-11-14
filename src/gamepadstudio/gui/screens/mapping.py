"""按键映射页：方案设置、来源捕获、动作选择与绑定列表."""
from __future__ import annotations

import pygame

from .. import theme
from ...core import mapping as mapping_mod
from ...core.mapping import Binding, MappingProfile
from ...core.model import SEMANTIC_BUTTONS


class MappingScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.capture_source = False
        self.capture_key = False
        self.captured_source = ""
        self.action_kind = 0
        self.action_value = "W"
        self.mode_index = 0
        self.turbo_hz = 12.0
        self.macro_text = ""
        self.error = ""
        self.list_scroll_offset = 0

    # ------------------------------------------------------------------ 事件
    def handle_event(self, event) -> None:
        if self.capture_key and event.type == pygame.KEYDOWN:
            name = pygame.key.name(event.key).upper()
            if name in ("ESCAPE",):
                self.capture_key = False
                return
            key_name = _key_name(event.key)
            if key_name:
                self.action_value = key_name
                self.action_kind = 0
                self.capture_key = False
                self.app.set_status(f"已捕获键盘按键：{key_name}")

    def update(self, dt: float) -> None:
        if not self.capture_source:
            return
        state = self.app.pad_state
        if state is None:
            return
        captured = mapping_mod.detect_capture(self.app.prev_state, state, self.app.profile.deadzone)
        if captured:
            self.captured_source = captured
            self.capture_source = False
            self.app.set_status(f"已捕获来源：{mapping_mod.describe_source(captured)}")

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        gap = 12
        left_w = min(340, int(rect.width * 0.34))
        left = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right = pygame.Rect(left.right + gap, rect.y, rect.width - left_w - gap, rect.height)
        self._draw_settings(ui, left)
        self._draw_editor(ui, right)

    # ---------------------------------------------------------------- 左：方案
    def _draw_settings(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        theme.draw_text(surface, ui.fonts.get(14, bold=True), "方案设置", (rect.x + 18, rect.y + 16), theme.TEXT)
        theme.draw_text(surface, ui.fonts.get(11), "保存在 JSON，可随时加载 / 分享",
                        (rect.x + 18, rect.y + 37), theme.TEXT_MUTED)

        x = rect.x + 18
        width = rect.width - 36
        y = rect.y + 66
        theme.draw_text(surface, ui.fonts.get(11), "方案名称", (x, y), theme.TEXT_MUTED)
        new_name = ui.text_input("profile_name", pygame.Rect(x, y + 18, width, 34), app.profile.name, "例如：赛车 · 键盘")
        if new_name != app.profile.name:
            app.profile.name = new_name

        y += 66
        theme.draw_text(surface, ui.fonts.get(11), "输出目标", (x, y), theme.TEXT_MUTED)
        target_options = [mapping_mod.TARGET_LABELS[t] for t in mapping_mod.TARGETS]
        target_index = mapping_mod.TARGETS.index(app.profile.target)
        chosen = ui.dropdown("profile_target", pygame.Rect(x, y + 18, width, 34), target_options, target_index)
        if chosen != target_index:
            app.profile.target = mapping_mod.TARGETS[chosen]

        y += 66
        theme.draw_text(surface, ui.fonts.get(11), "摇杆死区", (x, y), theme.TEXT_MUTED)
        deadzone = ui.slider("profile_deadzone", pygame.Rect(x, y + 18, width, 30),
                             app.profile.deadzone, 0.0, 0.6, 0.01,
                             fmt=lambda v: f"{v:.2f}")
        app.profile.deadzone = deadzone

        y += 58
        invert_ly = ui.toggle("invert_ly", pygame.Rect(x, y, width, 26),
                              "ly" in app.profile.invert_axes, "反转左摇杆 Y 轴")
        invert_ry = ui.toggle("invert_ry", pygame.Rect(x, y + 32, width, 26),
                              "ry" in app.profile.invert_axes, "反转右摇杆 Y 轴")
        for axis, enabled in (("ly", invert_ly), ("ry", invert_ry)):
            if enabled and axis not in app.profile.invert_axes:
                app.profile.invert_axes.append(axis)
            elif not enabled and axis in app.profile.invert_axes:
                app.profile.invert_axes.remove(axis)

        y += 78
        pygame.draw.line(surface, theme.BORDER_SOFT, (x, y), (x + width, y))
        y += 14
        output_enabled = ui.toggle("output_enabled", pygame.Rect(x, y, width, 26),
                                   bool(app.settings.get("output_enabled")), "启用输出（会真的按键 / 操作手柄）")
        app.settings["output_enabled"] = bool(output_enabled)
        if output_enabled and app.profile.target == "keyboard" and not app.injector.supported:
            theme.draw_text(surface, ui.fonts.get(11), "当前系统不支持键盘注入", (x, y + 32), theme.WARN)

        y = rect.bottom - 142
        if ui.button("profile_save", pygame.Rect(x, y, width, 36), "保存为 JSON…", kind="primary"):
            path = _save_dialog(app.profile.name)
            if path:
                try:
                    app.profile.save(path)
                    app.profile_path = str(path)
                    app.set_status(f"已保存：{path}")
                except Exception as exc:
                    app.set_status(f"保存失败：{exc}")
        if ui.button("profile_load", pygame.Rect(x, y + 44, width, 36), "从 JSON 加载…"):
            path = _open_dialog()
            if path:
                try:
                    app.profile = MappingProfile.load(path)
                    app.profile_path = str(path)
                    app.set_status(f"已加载：{app.profile.name}")
                except Exception as exc:
                    app.set_status(f"加载失败：{exc}")
        if ui.button("profile_new", pygame.Rect(x, y + 88, width, 34), "新建空白方案", kind="ghost"):
            app.profile = MappingProfile()
            app.set_status("已新建空白方案")

    # ---------------------------------------------------------------- 右：编辑
    def _draw_editor(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        editor_h = 216
        editor = pygame.Rect(rect.x, rect.y, rect.width, editor_h)
        theme.rounded_rect(surface, editor, theme.PANEL, radius=14, border=theme.BORDER_SOFT)

        theme.draw_text(surface, ui.fonts.get(14, bold=True), "添加映射", (editor.x + 18, editor.y + 16), theme.TEXT)
        theme.draw_text(surface, ui.fonts.get(11), "先捕获手柄来源，再指定输出动作与触发模式",
                        (editor.x + 18, editor.y + 37), theme.TEXT_MUTED)

        # ① 来源
        x1 = editor.x + 18
        y1 = editor.y + 66
        capture_label = "① 捕获来源（按手柄按键）"
        if self.capture_source:
            capture_label = "监听中… 请按手柄按键或推摇杆"
        if ui.button("capture_source", pygame.Rect(x1, y1, 210, 36),
                     capture_label, kind="primary" if self.capture_source else "default", font_size=13):
            self.capture_source = not self.capture_source
            self.capture_key = False
        source_text = mapping_mod.describe_source(self.captured_source) if self.captured_source else "尚未捕获"
        theme.draw_text(surface, ui.fonts.get(13), theme.ellipsize(
            ui.fonts.get(13), source_text, rect.width - 260), (x1 + 226, y1 + 18),
            theme.ACCENT if self.captured_source else theme.TEXT_MUTED, align="midleft")

        # ② 动作
        x2 = x1
        y2 = y1 + 48
        kinds = ["键盘 / 鼠标", "虚拟手柄按键", "不输出"]
        self.action_kind = ui.dropdown("action_kind", pygame.Rect(x2, y2, 150, 34), kinds, self.action_kind)

        if self.action_kind == 0:
            self.action_value = ui.text_input("action_value", pygame.Rect(x2 + 162, y2, 120, 34),
                                              self.action_value, "如 W 或 CTRL+S")
            if ui.button("capture_key", pygame.Rect(x2 + 294, y2, 110, 34),
                         "捕获按键" if not self.capture_key else "按任意键…", kind="ghost", font_size=12):
                self.capture_key = not self.capture_key
                self.capture_source = False
        elif self.action_kind == 1:
            pad_options = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "UP", "DOWN", "LEFT", "RIGHT", "START", "BACK"]
            current = pad_options.index(self.action_value.upper()) if self.action_value.upper() in pad_options else 0
            chosen = ui.dropdown("pad_button", pygame.Rect(x2 + 162, y2, 130, 34), pad_options, current)
            self.action_value = pad_options[chosen].lower()

        # ③ 触发模式
        y3 = y2 + 42
        mode_options = [mapping_mod.MODE_LABELS[name] for name in mapping_mod.MODES]
        self.mode_index = ui.dropdown("binding_mode", pygame.Rect(x2, y3, 150, 34), mode_options, self.mode_index)
        mode = mapping_mod.MODES[self.mode_index]
        if mode == "turbo":
            theme.draw_text(surface, ui.fonts.get(11), "频率", (x2 + 166, y3 + 9), theme.TEXT_MUTED)
            self.turbo_hz = ui.slider("binding_turbo", pygame.Rect(x2 + 204, y3, 170, 34),
                                      self.turbo_hz, 2.0, 30.0, 1.0, fmt=lambda v: f"{v:.0f} Hz")
        elif mode == "macro":
            macro_w = max(160, min(320, editor.right - 150 - (x2 + 162)))
            self.macro_text = ui.text_input("binding_macro", pygame.Rect(x2 + 162, y3, macro_w, 34),
                                            self.macro_text, "W:80/200|SPACE:60/150", max_len=220)
            theme.draw_text(surface, ui.fonts.get(10),
                            "格式：按键:按住ms/间隔ms，多步用 | 分隔，组合键写 CTRL+S",
                            (x2 + 162, y3 + 37), theme.TEXT_MUTED)

        # ④ 添加
        macro_steps = mapping_mod.parse_macro(self.macro_text) if mode == "macro" else []
        can_add = bool(self.captured_source) and (self.action_kind == 2 or bool(self.action_value))
        if mode == "macro" and not macro_steps:
            can_add = False
        if ui.button("add_binding", pygame.Rect(editor.right - 132, y3, 114, 34),
                     "添加到列表", kind="primary", enabled=can_add):
            action = "none"
            if self.action_kind == 0:
                action = f"keyboard:{self.action_value.strip().upper()}"
            elif self.action_kind == 1:
                action = f"virtual:{self.action_value.lower()}"
            self._add_binding(self.captured_source, action, mode)
        if mode == "macro" and self.macro_text and not macro_steps:
            self.error = "宏序列里没有合法按键，检查格式或按键名"
        elif self.error and self.captured_source:
            self.error = ""
        if self.error:
            theme.draw_text(surface, ui.fonts.get(11), self.error, (x2, y3 + 40), theme.DANGER)

        # 列表
        list_rect = pygame.Rect(rect.x, editor.bottom + 12, rect.width, rect.bottom - editor.bottom - 12)
        theme.rounded_rect(surface, list_rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        count = len(app.profile.bindings)
        theme.draw_text(surface, ui.fonts.get(14, bold=True), f"映射列表（{count}）",
                        (list_rect.x + 18, list_rect.y + 16), theme.TEXT)
        if ui.button("clear_bindings", pygame.Rect(list_rect.right - 106, list_rect.y + 10, 88, 28),
                     "清空", kind="danger", font_size=12, enabled=count > 0):
            app.profile.bindings.clear()
            app.set_status("已清空映射")

        viewport = pygame.Rect(list_rect.x + 12, list_rect.y + 48, list_rect.width - 24, list_rect.height - 60)
        row_h = 46
        offset = ui.scroll("bindings", viewport, row_h * max(count, 1), row_h)
        self.list_scroll_offset = offset
        if count == 0:
            theme.draw_text(surface, ui.fonts.get(13), "还没有映射，先在上方捕获一个来源",
                            viewport.center, theme.TEXT_MUTED, align="center")
            return

        # 表头
        header = ui.fonts.get(10)
        theme.draw_text(surface, header, "来 源", (viewport.x + 12, viewport.y - 14), theme.TEXT_MUTED)
        theme.draw_text(surface, header, "输 出 动 作", (viewport.x + 274, viewport.y - 14), theme.TEXT_MUTED)

        surface.set_clip(viewport)
        for index, binding in enumerate(app.profile.bindings):
            row = pygame.Rect(viewport.x, viewport.y + index * row_h - offset, viewport.width, row_h - 6)
            if row.bottom < viewport.y - row_h or row.y > viewport.bottom:
                continue
            hover = row.collidepoint(ui.mouse)
            theme.rounded_rect(surface, row, theme.PANEL_ALT if hover else theme.PANEL,
                               radius=8, border=theme.BORDER_SOFT)
            source_label = mapping_mod.describe_source(binding.source)
            theme.draw_text(surface, ui.fonts.get(13, bold=True), theme.ellipsize(
                ui.fonts.get(13), source_label, 200), (row.x + 12, row.centery), theme.TEXT, align="midleft")
            arrow_x = row.x + 226
            pygame.draw.line(surface, theme.TEXT_MUTED, (arrow_x, row.centery), (arrow_x + 22, row.centery), 1)
            pygame.draw.polygon(surface, theme.TEXT_MUTED,
                                [(arrow_x + 22, row.centery - 4), (arrow_x + 28, row.centery), (arrow_x + 22, row.centery + 4)])
            action_label = mapping_mod.describe_action(binding.action)
            theme.draw_text(surface, ui.fonts.get(13), theme.ellipsize(ui.fonts.get(13), action_label, 132),
                            (arrow_x + 38, row.centery), theme.ACCENT if binding.action != "none" else theme.TEXT_MUTED,
                            align="midleft")
            mode_label = mapping_mod.describe_binding(binding)
            theme.draw_text(surface, ui.fonts.get(10), mode_label,
                            (row.right - 74, row.centery),
                            theme.ACCENT_DIM if binding.mode != "hold" else theme.TEXT_MUTED,
                            align="midright")
            if ui.button(f"del_binding_{index}", pygame.Rect(row.right - 66, row.y + 6, 56, 28),
                         "删除", kind="danger", font_size=11):
                app.profile.bindings.pop(index)
                app.set_status("已删除一条映射")
                break
        surface.set_clip(None)
        self._draw_scrollbar(ui, viewport, row_h * count, offset)

    def _draw_scrollbar(self, ui, viewport: pygame.Rect, content_height: int, offset: int) -> None:
        if content_height <= viewport.height:
            return
        surface = ui.surface
        track = pygame.Rect(viewport.right + 4, viewport.y, 5, viewport.height)
        theme.rounded_rect(surface, track, theme.PANEL_ALT, radius=3)
        ratio = viewport.height / content_height
        thumb_h = max(28, int(viewport.height * ratio))
        max_offset = content_height - viewport.height
        position = offset / max_offset if max_offset else 0
        thumb = pygame.Rect(track.x, track.y + int((track.height - thumb_h) * position), track.width, thumb_h)
        theme.rounded_rect(surface, thumb, theme.BORDER, radius=3)

    def _add_binding(self, source: str, action: str, mode: str = "hold") -> None:
        if not source:
            self.error = "请先捕获一个来源"
            return
        macro_text = ""
        if mode == "macro":
            steps = mapping_mod.parse_macro(self.macro_text)
            if not steps:
                self.error = "宏序列为空或格式不对"
                return
            macro_text = mapping_mod.format_macro(steps)
            action = f"keyboard:{steps[0].keys}"
        turbo_hz = round(self.turbo_hz, 1)
        for binding in self.app.profile.bindings:
            if binding.source == source:
                binding.action = action
                binding.mode = mode
                binding.turbo_hz = turbo_hz
                binding.macro = macro_text
                self.error = ""
                self.app.set_status(f"已更新：{mapping_mod.describe_source(source)}")
                return
        self.app.profile.bindings.append(
            Binding(source=source, action=action, mode=mode, turbo_hz=turbo_hz, macro=macro_text))
        self.error = ""
        self.app.set_status(
            f"已添加：{mapping_mod.describe_source(source)} → {mapping_mod.describe_action(action)}"
            f"（{mapping_mod.describe_binding(self.app.profile.bindings[-1])}）")


def _key_name(keycode: int) -> str:
    mapping = {
        pygame.K_SPACE: "SPACE", pygame.K_RETURN: "ENTER", pygame.K_ESCAPE: "ESC",
        pygame.K_TAB: "TAB", pygame.K_LSHIFT: "SHIFT", pygame.K_LCTRL: "CTRL",
        pygame.K_LALT: "ALT", pygame.K_UP: "UP", pygame.K_DOWN: "DOWN",
        pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    }
    if keycode in mapping:
        return mapping[keycode]
    if pygame.K_a <= keycode <= pygame.K_z:
        return chr(keycode).upper()
    if pygame.K_0 <= keycode <= pygame.K_9:
        return chr(keycode)
    if pygame.K_F1 <= keycode <= pygame.K_F12:
        return f"F{keycode - pygame.K_F1 + 1}"
    return ""


def _open_dialog():
    from ...platform.win_dialog import open_json
    return open_json("加载映射方案")


def _save_dialog(default_name: str):
    from ...platform.win_dialog import save_json
    import re
    safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", default_name).strip("_") or "mapping"
    return save_json(f"{safe}.json", "保存映射方案")
