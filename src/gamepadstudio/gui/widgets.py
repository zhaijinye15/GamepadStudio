"""即时模式控件库（immediate-mode GUI）.

用法：每帧先 ``begin()``，再调用各控件函数拿到交互结果，最后 ``draw_overlays()``。
控件状态按 id 保存在内部字典里，界面代码不需要维护任何控件对象。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pygame

from . import theme
from .theme import Fonts


class UI:
    def __init__(self, size: Tuple[int, int], fonts: Fonts) -> None:
        self.size = size
        self.fonts = fonts
        self.surface = pygame.Surface(size)
        self.mouse = (0, 0)
        self.mouse_down = False
        self._pressed = False
        self._released = False
        self._wheel = 0
        self._consumed = False
        self._chars: List[str] = []
        self._keys: List[int] = []
        self.focus_id: Optional[str] = None
        self.enter_id: Optional[str] = None
        self._dropdown: Optional[dict] = None
        self._dropdown_choice: Optional[Tuple[str, int]] = None
        self._scroll_offsets: Dict[str, int] = {}
        self._slider_active: Optional[str] = None
        self.tooltip: Optional[Tuple[str, Tuple[int, int]]] = None
        self._last_rects: Dict[str, pygame.Rect] = {}
        self.hover_id: Optional[str] = None

    # ------------------------------------------------------------------ 帧控制
    def begin(self, surface: pygame.Surface, mouse: Tuple[int, int], mouse_down: bool,
              pressed: bool, released: bool, wheel: int) -> None:
        self.surface = surface
        self.mouse = mouse
        self.mouse_down = mouse_down
        self._pressed = pressed
        self._released = released
        self._wheel = wheel
        self._consumed = False
        self._dropdown_choice = None
        self._chars = []
        self._keys = []
        self.hover_id = None
        self.tooltip = None
        # 下拉弹层：点击弹层外部则关闭，并吞掉这次点击
        if self._dropdown is not None:
            popup = self._dropdown["popup"]
            if pressed and not popup.collidepoint(mouse):
                self._dropdown = None
                self._consumed = True

    def end(self) -> None:
        if self._released:
            self._slider_active = None

    # ------------------------------------------------------------------ 事件
    def feed_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.TEXTINPUT and self.focus_id:
            for char in event.text:
                if char.isprintable():
                    self._chars.append(char)
        elif event.type == pygame.KEYDOWN:
            self._keys.append(event.key)
            if event.key == pygame.K_RETURN and self.focus_id:
                self.enter_id = self.focus_id
            elif event.key == pygame.K_ESCAPE:
                self.focus_id = None

    def clear_enter(self) -> None:
        self.enter_id = None

    # ------------------------------------------------------------------ 命中
    def _hit(self, widget_id: str, rect: pygame.Rect, enabled: bool = True) -> Tuple[bool, bool]:
        """返回 (hover, clicked)；点击会被消费，保证只触发一个控件."""
        self._last_rects[widget_id] = rect
        hover = rect.collidepoint(self.mouse) and not self._consumed
        clicked = hover and self._pressed and enabled
        if hover:
            self.hover_id = widget_id
        if clicked:
            self._consumed = True
        return hover, clicked

    def consumed(self) -> bool:
        return self._consumed

    # ------------------------------------------------------------------ 控件
    def button(self, widget_id: str, rect, label: str, kind: str = "default",
               enabled: bool = True, font_size: int = 15) -> bool:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect, enabled)
        colors = {
            "primary": (theme.ACCENT, theme.ACCENT_DIM, (20, 30, 26)),
            "default": (theme.PANEL_ALT, theme.BORDER, theme.TEXT),
            "ghost": (theme.PANEL, theme.BORDER_SOFT, theme.TEXT_DIM),
            "danger": ((66, 30, 36), (120, 50, 58), theme.DANGER),
            "warning": ((62, 48, 26), (120, 92, 44), theme.WARN),
        }
        bg, border, fg = colors.get(kind, colors["default"])
        if not enabled:
            bg, border, fg = theme.PANEL, theme.BORDER_SOFT, theme.TEXT_MUTED
        elif hover:
            bg = theme.lerp_color(bg, (255, 255, 255), 0.10)
            border = theme.lerp_color(border, theme.ACCENT, 0.35)
        if clicked and enabled:
            bg = theme.lerp_color(bg, (0, 0, 0), 0.12)

        theme.rounded_rect(self.surface, rect, bg, radius=9, border=border)
        if kind == "primary" and enabled:
            theme.rounded_rect(self.surface, rect.inflate(-2, -2), bg, radius=8)
        font = self.fonts.get(font_size, bold=(kind == "primary"))
        theme.draw_text(self.surface, font, theme.ellipsize(font, label, rect.width - 16),
                        rect.center, fg, align="center")
        return clicked

    def toggle(self, widget_id: str, rect, value: bool, label: str = "") -> bool:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect)
        track_rect = pygame.Rect(rect.x, rect.y + (rect.height - 22) // 2, 42, 22)
        fill = theme.ACCENT_DIM if value else theme.PANEL_ALT
        border = theme.ACCENT if value else theme.BORDER
        theme.rounded_rect(self.surface, track_rect, fill, radius=11, border=border)
        knob_x = track_rect.right - 11 if value else track_rect.x + 11
        pygame.draw.circle(self.surface, theme.TEXT if value else theme.TEXT_DIM,
                           (knob_x, track_rect.centery), 8)
        if label:
            font = self.fonts.get(14)
            theme.draw_text(self.surface, font, label, (rect.x + 54, rect.centery), theme.TEXT, align="midleft")
        return (not value) if clicked else value

    def slider(self, widget_id: str, rect, value: float, low: float = 0.0, high: float = 1.0,
               step: float = 0.0, fmt: Optional[Callable[[float], str]] = None,
               track_height: int = 6) -> float:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect)
        if clicked:
            self._slider_active = widget_id
            self.focus_id = None
        dragging = self._slider_active == widget_id and (self.mouse_down or self._pressed)

        if dragging:
            ratio = (self.mouse[0] - rect.x - 8) / max(1, rect.width - 16)
            ratio = max(0.0, min(1.0, ratio))
            value = low + ratio * (high - low)
            if step > 0:
                value = round(value / step) * step
            self._consumed = True

        ratio = 0.0 if high == low else (value - low) / (high - low)
        track = pygame.Rect(rect.x + 8, rect.centery - track_height // 2, rect.width - 16, track_height)
        theme.rounded_rect(self.surface, track, theme.PANEL_ALT, radius=3, border=theme.BORDER_SOFT)
        filled = pygame.Rect(track.x, track.y, int(track.width * ratio), track.height)
        accent = theme.ACCENT if dragging or hover else theme.ACCENT_DIM
        if filled.width > 0:
            theme.rounded_rect(self.surface, filled, accent, radius=3)
        knob_x = track.x + int(track.width * ratio)
        pygame.draw.circle(self.surface, theme.ACCENT if dragging else theme.TEXT, (knob_x, track.centery), 8)
        if fmt is not None:
            font = self.fonts.get(13)
            theme.draw_text(self.surface, font, fmt(value), (rect.right - 4, rect.centery - 18),
                            theme.TEXT_DIM, align="bottomright")
        return value

    def text_input(self, widget_id: str, rect, text: str, hint: str = "", max_len: int = 64) -> str:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect)
        if clicked:
            self.focus_id = widget_id
        focused = self.focus_id == widget_id

        border = theme.ACCENT if focused else (theme.BORDER if hover else theme.BORDER_SOFT)
        theme.rounded_rect(self.surface, rect, theme.PANEL_ALT, radius=8, border=border)
        font = self.fonts.get(14)
        if focused:
            new_chars = "".join(self._chars)
            for key in self._keys:
                if key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif key == pygame.K_RETURN:
                    self.enter_id = widget_id
            if new_chars:
                text = (text + new_chars)[:max_len]
        display = text if text else hint
        color = theme.TEXT if text else theme.TEXT_MUTED
        shown = theme.ellipsize(font, display, rect.width - 20)
        theme.draw_text(self.surface, font, shown, (rect.x + 10, rect.centery), color, align="midleft")
        if focused and text:
            caret_x = rect.x + 10 + font.size(shown)[0] + 1
            pygame.draw.line(self.surface, theme.ACCENT, (caret_x, rect.centery - 8), (caret_x, rect.centery + 8))
        return text

    def dropdown(self, widget_id: str, rect, options: Sequence[str], index: int,
                 placeholder: str = "请选择") -> int:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect)
        is_open = self._dropdown is not None and self._dropdown.get("id") == widget_id

        border = theme.ACCENT if is_open else (theme.BORDER if hover else theme.BORDER_SOFT)
        theme.rounded_rect(self.surface, rect, theme.PANEL_ALT, radius=8, border=border)
        font = self.fonts.get(14)
        label = options[index] if 0 <= index < len(options) else placeholder
        theme.draw_text(self.surface, font, theme.ellipsize(font, label, rect.width - 34),
                        (rect.x + 10, rect.centery), theme.TEXT, align="midleft")
        arrow = (rect.right - 14, rect.centery - 2)
        pygame.draw.polygon(self.surface, theme.TEXT_DIM,
                            [(arrow[0] - 5, arrow[1] - 3), (arrow[0] + 5, arrow[1] - 3), (arrow[0], arrow[1] + 4)])

        if clicked and not is_open:
            self._dropdown = {
                "id": widget_id,
                "index": index,
                "options": list(options),
                "rect": rect,
                "popup": pygame.Rect(rect.x, rect.bottom + 4, rect.width, min(240, 34 * len(options))),
            }
            self._consumed = True
        if self._dropdown is not None and self._dropdown.get("id") == widget_id and self._dropdown_choice is None:
            hit_index = self._popup_hit_test()
            if hit_index is not None:
                index = hit_index
                self._dropdown_choice = (widget_id, index)
                self._dropdown = None
        return index

    def _popup_hit_test(self) -> Optional[int]:
        if self._dropdown is None or not self._pressed:
            return None
        popup: pygame.Rect = self._dropdown["popup"]
        if not popup.collidepoint(self.mouse):
            return None
        row = (self.mouse[1] - popup.y) // 34
        if 0 <= row < len(self._dropdown["options"]):
            self._consumed = True
            return int(row)
        return None

    def list_row(self, widget_id: str, rect, label: str, selected: bool, sub: str = "") -> bool:
        rect = pygame.Rect(rect)
        hover, clicked = self._hit(widget_id, rect)
        bg = theme.PANEL_ALT if selected else (theme.PANEL if hover else None)
        if bg is not None:
            theme.rounded_rect(self.surface, rect, bg, radius=8,
                               border=theme.ACCENT_DIM if selected else None)
        if selected:
            pygame.draw.rect(self.surface, theme.ACCENT,
                             pygame.Rect(rect.x, rect.y + 8, 3, rect.height - 16), border_radius=2)
        font = self.fonts.get(14, bold=selected)
        color = theme.TEXT if selected or hover else theme.TEXT_DIM
        theme.draw_text(self.surface, font, theme.ellipsize(font, label, rect.width - 20),
                        (rect.x + 12, rect.y + 9), color, align="topleft")
        if sub:
            small = self.fonts.get(11)
            theme.draw_text(self.surface, small, theme.ellipsize(small, sub, rect.width - 20),
                            (rect.x + 12, rect.y + 27), theme.TEXT_MUTED, align="topleft")
        return clicked

    def card(self, rect, title: str = "", subtitle: str = "") -> pygame.Rect:
        rect = pygame.Rect(rect)
        theme.rounded_rect(self.surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        if title:
            font = self.fonts.get(14, bold=True)
            theme.draw_text(self.surface, font, title, (rect.x + 18, rect.y + 14), theme.TEXT)
        if subtitle:
            small = self.fonts.get(11)
            theme.draw_text(self.surface, small, subtitle, (rect.x + 18, rect.y + 36), theme.TEXT_MUTED)
        top = 54 if (title or subtitle) else 14
        return pygame.Rect(rect.x + 18, rect.y + top, rect.width - 36, max(0, rect.height - top - 16))

    def badge(self, pos, text: str, color=theme.TEXT_DIM, bg=None) -> pygame.Rect:
        font = self.fonts.get(11)
        size = font.size(text)
        rect = pygame.Rect(pos[0], pos[1], size[0] + 16, 22)
        theme.rounded_rect(self.surface, rect, bg or (30, 37, 48), radius=11, border=theme.BORDER_SOFT)
        theme.draw_text(self.surface, font, text, rect.center, color, align="center")
        return rect

    def progress_bar(self, rect, value: float, color=theme.ACCENT, bg=theme.PANEL_ALT, height: int = 8,
                     show_value: bool = True, fmt: Optional[Callable[[float], str]] = None) -> None:
        rect = pygame.Rect(rect)
        rect.height = height
        theme.rounded_rect(self.surface, rect, bg, radius=height // 2, border=theme.BORDER_SOFT)
        width = int(rect.width * max(0.0, min(1.0, value)))
        if width > 2:
            theme.rounded_rect(self.surface, pygame.Rect(rect.x, rect.y, width, height), color,
                               radius=height // 2)
        if show_value:
            font = self.fonts.get(12)
            text = fmt(value) if fmt else f"{value:.2f}"
            theme.draw_text(self.surface, font, text, (rect.right, rect.y - 2), theme.TEXT_DIM, align="bottomright")

    def scroll(self, widget_id: str, viewport: pygame.Rect, content_height: int, row_height: int) -> int:
        """返回滚动偏移；滚轮只在鼠标位于视口内时生效."""
        offset = self._scroll_offsets.get(widget_id, 0)
        max_offset = max(0, content_height - viewport.height)
        if self._wheel and viewport.collidepoint(self.mouse):
            offset -= self._wheel * row_height
            self._wheel = 0
        offset = max(0, min(max_offset, offset))
        self._scroll_offsets[widget_id] = offset
        return offset

    def draw_overlays(self) -> None:
        if self._dropdown is None:
            return
        popup: pygame.Rect = self._dropdown["popup"]
        theme.shadow(self.surface, popup, radius=10, alpha=90, offset=(0, 6))
        theme.rounded_rect(self.surface, popup, theme.PANEL_ALT, radius=10, border=theme.BORDER)
        font = self.fonts.get(14)
        for row, option in enumerate(self._dropdown["options"]):
            row_rect = pygame.Rect(popup.x + 4, popup.y + 4 + row * 34, popup.width - 8, 32)
            if row_rect.collidepoint(self.mouse):
                theme.rounded_rect(self.surface, row_rect, theme.lerp_color(theme.PANEL_ALT, theme.ACCENT, 0.12),
                                   radius=7)
            theme.draw_text(self.surface, font, theme.ellipsize(font, option, row_rect.width - 16),
                            (row_rect.x + 10, row_rect.centery), theme.TEXT, align="midleft")

    def tooltip_at(self, text: str, pos: Tuple[int, int]) -> None:
        self.tooltip = (text, pos)

    def draw_tooltip(self) -> None:
        if self.tooltip is None:
            return
        text, pos = self.tooltip
        font = self.fonts.get(12)
        size = font.size(text)
        rect = pygame.Rect(pos[0], pos[1], size[0] + 16, size[1] + 10)
        rect.right = min(rect.right, self.size[0] - 8)
        theme.rounded_rect(self.surface, rect, (12, 15, 20), radius=6, border=theme.BORDER)
        theme.draw_text(self.surface, font, text, rect.center, theme.TEXT, align="center")
