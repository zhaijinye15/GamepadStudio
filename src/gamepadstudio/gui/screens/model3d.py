"""3D 模型页：用纯软件投影渲染手柄模型，按键按下时实时高亮.

没有引入 OpenGL / moderngl —— 模型面数很少（约 700 面），
自己做旋转、透视投影和画家算法排序，在 60 FPS 下完全够用。
"""
from __future__ import annotations

import math
from typing import List, Tuple

import pygame

from .. import theme
from ...core.gamepad_mesh import build_gamepad, face_normal

LIGHT_DIR = (0.42, -0.55, 0.72)
DISTANCE = 7.2


class Model3DScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.faces = build_gamepad()
        self.yaw = -0.45
        self.pitch = 0.32
        self.auto_rotate = True
        self._drag_last: Tuple[int, int] = (0, 0)
        self._dragging = False

    def handle_event(self, event) -> None:
        return

    # ------------------------------------------------------------------ 交互
    def _handle_drag(self, ui, rect: pygame.Rect) -> None:
        mouse = ui.mouse
        inside = rect.collidepoint(mouse)
        if ui.mouse_down and inside:
            if not self._dragging:
                self._dragging = True
                self._drag_last = mouse
            else:
                dx = mouse[0] - self._drag_last[0]
                dy = mouse[1] - self._drag_last[1]
                self.yaw += dx * 0.012
                self.pitch = max(-1.2, min(1.2, self.pitch + dy * 0.010))
                self._drag_last = mouse
                self.auto_rotate = False
        elif not ui.mouse_down:
            self._dragging = False

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        surface = ui.surface
        inner = ui.card(rect, "3D 模型", "拖动机身可旋转 · 按下手柄按键会实时高亮")
        self._handle_drag(ui, inner)

        top_bar = pygame.Rect(inner.x, inner.y, inner.width, 30)
        if ui.button("m3d_auto", pygame.Rect(top_bar.x, top_bar.y, 108, 28),
                     "自动旋转：开" if self.auto_rotate else "自动旋转：关",
                     kind="ghost", font_size=12):
            self.auto_rotate = not self.auto_rotate
        if ui.button("m3d_reset", pygame.Rect(top_bar.x + 118, top_bar.y, 88, 28),
                     "复位视角", kind="ghost", font_size=12):
            self.yaw, self.pitch = -0.45, 0.32
            self.auto_rotate = True

        view = pygame.Rect(inner.x, top_bar.bottom + 8, inner.width, inner.height - 42)
        theme.rounded_rect(surface, view, (16, 19, 24), radius=12, border=theme.BORDER_SOFT)
        if self.auto_rotate:
            self.yaw += 0.006

        pressed = self._pressed_tags()
        focal = min(view.width, view.height) * 0.62
        center = (view.centerx, view.centery + int(view.height * 0.04))

        projected: List[Tuple[float, List[Tuple[int, int]], Tuple[int, int, int]]] = []
        for points, color, tag in self.faces:
            rotated = [_rotate(p, self.yaw, self.pitch) for p in points]
            depth = sum(p[2] for p in rotated) / len(rotated) + DISTANCE
            if depth <= 0.4:
                continue
            shade = self._light(rotated, color)
            if tag in pressed:
                shade = (min(255, shade[0] + 90), min(255, shade[1] + 120), min(255, shade[2] + 90))
            screen_points = []
            for point in rotated:
                scale = focal / (point[2] + DISTANCE)
                screen_points.append((int(center[0] + point[0] * scale),
                                      int(center[1] - point[1] * scale)))
            projected.append((depth, screen_points, shade))

        projected.sort(key=lambda item: item[0], reverse=True)
        for _, screen_points, shade in projected:
            if len(screen_points) < 3:
                continue
            pygame.draw.polygon(surface, shade, screen_points)

        # 底部读数
        state = self.app.pad_state
        font = ui.fonts.get(11)
        if state is not None:
            text = (f"左摇杆 {state.axis('lx'):+.2f}/{state.axis('ly'):+.2f}   "
                    f"右摇杆 {state.axis('rx'):+.2f}/{state.axis('ry'):+.2f}   "
                    f"LT {state.axis('lt'):.2f}  RT {state.axis('rt'):.2f}")
        else:
            text = "等待手柄数据…"
        theme.draw_text(surface, font, text, (view.x + 14, view.bottom - 22), theme.TEXT_DIM)

    # ------------------------------------------------------------------ 工具
    def _pressed_tags(self) -> set:
        state = self.app.pad_state
        tags = set()
        if state is None:
            return tags
        for name, active in state.semantic_buttons.items():
            if active:
                tags.add(name)
        axes = state.semantic_axes
        if (axes.get("lx", 0.0) ** 2 + axes.get("ly", 0.0) ** 2) ** 0.5 > 0.25:
            tags.add("stickbase_left")
        if (axes.get("rx", 0.0) ** 2 + axes.get("ry", 0.0) ** 2) ** 0.5 > 0.25:
            tags.add("stickbase_right")
        if axes.get("lt", 0.0) > 0.15:
            tags.add("lb")
        if axes.get("rt", 0.0) > 0.15:
            tags.add("rb")
        return tags

    @staticmethod
    def _light(rotated: List[Tuple[float, float, float]], color) -> Tuple[int, int, int]:
        normal = face_normal(rotated)
        length = (normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) ** 0.5
        if length == 0.0:
            return color
        nx, ny, nz = normal[0] / length, normal[1] / length, normal[2] / length
        dot = nx * LIGHT_DIR[0] + ny * LIGHT_DIR[1] + nz * LIGHT_DIR[2]
        brightness = 0.42 + 0.58 * abs(dot)
        return (max(0, min(255, int(color[0] * brightness))),
                max(0, min(255, int(color[1] * brightness))),
                max(0, min(255, int(color[2] * brightness))))


def _rotate(point: Tuple[float, float, float], yaw: float, pitch: float) -> Tuple[float, float, float]:
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    x, y, z = point
    x1 = x * cy + z * sy
    z1 = -x * sy + z * cy
    y2 = y * cp - z1 * sp
    z2 = y * sp + z1 * cp
    return x1, y2, z2
