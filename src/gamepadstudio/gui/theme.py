"""视觉主题：配色、字体加载、绘制辅助（圆角矩形 / 文本对齐）."""
from __future__ import annotations

import pygame

from ..paths import asset_path

# ---------------------------------------------------------------- 配色（深色）
BG = (14, 17, 22)
SIDEBAR = (18, 22, 29)
PANEL = (24, 30, 39)
PANEL_ALT = (30, 37, 48)
BORDER = (44, 55, 70)
BORDER_SOFT = (36, 45, 58)
TEXT = (230, 237, 243)
TEXT_DIM = (148, 163, 179)
TEXT_MUTED = (104, 118, 134)
ACCENT = (64, 220, 160)
ACCENT_DIM = (32, 120, 92)
BLUE = (86, 148, 255)
PURPLE = (150, 128, 255)
WARN = (255, 176, 64)
DANGER = (255, 96, 108)
ACTIVE_GLOW = (64, 220, 160)


class Fonts:
    """统一字体：优先加载随程序分发的中文字体，缺失时回退系统字体."""

    _FONT_FILE = ("fonts", "NotoSansSC.otf")

    def __init__(self) -> None:
        self._path = asset_path(*self._FONT_FILE)
        self._cache = {}
        self._fallback = None

    def get(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key in self._cache:
            return self._cache[key]
        font = None
        if self._path.exists():
            try:
                font = pygame.font.Font(str(self._path), size)
            except Exception:
                font = None
        if font is None:
            font = pygame.font.SysFont("microsoftyahei,simhei,notosanscjksc,arial", size, bold=bold)
        if bold and font is not None:
            try:
                font.set_bold(True)
            except Exception:
                pass
        self._cache[key] = font
        return font

    def measure(self, text: str, size: int, bold: bool = False) -> tuple[int, int]:
        return self.get(size, bold).size(text)


# ---------------------------------------------------------------- 绘制辅助
def rounded_rect(surface, rect, color, radius=10, border=None, border_width=1):
    """填充圆角矩形并可选描边（无抗锯齿以保持边缘锐利，缩放时更稳）."""
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    if border is not None:
        pygame.draw.rect(surface, border, rect, border_radius=radius)
        inner = rect.inflate(-2 * border_width, -2 * border_width)
        pygame.draw.rect(surface, color, inner, border_radius=max(0, radius - border_width))
    else:
        pygame.draw.rect(surface, color, rect, border_radius=radius)


def shadow(surface, rect, radius=12, alpha=60, offset=(0, 4)):
    rect = pygame.Rect(rect).move(offset)
    layer = pygame.Surface((rect.width + 8, rect.height + 8), pygame.SRCALPHA)
    pygame.draw.rect(layer, (0, 0, 0, alpha), layer.get_rect(), border_radius=radius)
    surface.blit(layer, (rect.x - 4, rect.y - 4))


def draw_text(surface, font, text, pos, color=TEXT, align="topleft", shadow_color=None, shadow_offset=(0, 1)):
    """带可选阴影的文本绘制，返回实际占用的矩形."""
    if shadow_color is not None:
        shadow_surface = font.render(text, True, shadow_color)
        shadow_rect = shadow_surface.get_rect(**{align: (pos[0] + shadow_offset[0], pos[1] + shadow_offset[1])})
        surface.blit(shadow_surface, shadow_rect)
    text_surface = font.render(text, True, color)
    rect = text_surface.get_rect(**{align: pos})
    surface.blit(text_surface, rect)
    return rect


def ellipsize(font, text: str, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and font.size(trimmed + ellipsis)[0] > max_width:
        trimmed = trimmed[:-1]
    return trimmed + ellipsis if trimmed else ellipsis


def lerp_color(color_a, color_b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(color_a, color_b))


def with_alpha(color, alpha: int):
    return (color[0], color[1], color[2], alpha)
