"""关于页：版本、运行环境自检、数据目录与快捷键."""
from __future__ import annotations

import os
import platform
import sys

import pygame

from .. import theme
from ... import __version__
from ...paths import bundled_profiles_dir, logs_dir, profiles_dir


class AboutScreen:
    def __init__(self, app) -> None:
        self.app = app

    def handle_event(self, event) -> None:
        return

    def update(self, dt: float) -> None:
        return

    def draw(self, ui, rect: pygame.Rect) -> None:
        gap = 12
        left_w = int(rect.width * 0.44)
        left = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right = pygame.Rect(left.right + gap, rect.y, rect.width - left_w - gap, rect.height)
        self._draw_about(ui, left)
        self._draw_environment(ui, right)

    def _draw_about(self, ui, rect: pygame.Rect) -> None:
        surface = ui.surface
        app = self.app
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)

        logo = pygame.Rect(rect.x + 18, rect.y + 18, 56, 56)
        theme.rounded_rect(surface, logo, theme.ACCENT, radius=16)
        pygame.draw.circle(surface, theme.PANEL, (logo.centerx - 9, logo.centery), 8)
        pygame.draw.circle(surface, theme.PANEL, (logo.centerx + 9, logo.centery), 8)
        pygame.draw.line(surface, theme.PANEL, (logo.centerx - 9, logo.centery),
                         (logo.centerx + 9, logo.centery), 2)

        theme.draw_text(surface, ui.fonts.get(20, bold=True), "Gamepad Studio", (rect.x + 88, rect.y + 26), theme.TEXT)
        theme.draw_text(surface, ui.fonts.get(12), f"版本 {__version__} · Windows 手柄测试与映射", 
                        (rect.x + 90, rect.y + 54), theme.TEXT_MUTED)

        y = rect.y + 96
        theme.draw_text(surface, ui.fonts.get(13), "功能一览", (rect.x + 18, y), theme.TEXT)
        features = [
            "实时读取 USB / 蓝牙手柄：按键、摇杆、扳机、十字键",
            "自定义按键映射，方案保存为 JSON，可加载与分享",
            "震动测试：Switch Joy-Con（HD 震动）与 Xbox（SDL 触觉）",
            "输出模式：键盘模拟 / 虚拟 Xbox 360 / 虚拟 DualShock 4",
        ]
        y += 24
        for item in features:
            pygame.draw.circle(surface, theme.ACCENT, (rect.x + 24, y + 8), 3)
            theme.draw_text(surface, ui.fonts.get(12), theme.ellipsize(ui.fonts.get(12), item, rect.width - 60),
                            (rect.x + 36, y), theme.TEXT_DIM)
            y += 24

        y += 18
        theme.draw_text(surface, ui.fonts.get(13), "快捷键", (rect.x + 18, y), theme.TEXT)
        y += 24
        shortcuts = [
            ("F5", "重新扫描手柄"),
            ("ESC", "取消输入 / 退出捕获"),
            ("鼠标滚轮", "映射列表滚动"),
        ]
        for key, desc in shortcuts:
            ui.badge((rect.x + 20, y), key, theme.TEXT, theme.PANEL_ALT)
            theme.draw_text(surface, ui.fonts.get(12), desc, (rect.x + 96, y + 11), theme.TEXT_DIM, align="midleft")
            y += 30

        y += 10
        theme.draw_text(surface, ui.fonts.get(13), "目录", (rect.x + 18, y), theme.TEXT)
        y += 26
        paths = [
            ("用户方案", str(profiles_dir())),
            ("日志", str(logs_dir())),
            ("示例方案", str(bundled_profiles_dir())),
        ]
        small = ui.fonts.get(11)
        for label, path in paths:
            theme.draw_text(surface, small, f"{label}：{theme.ellipsize(small, path, rect.width - 60)}",
                            (rect.x + 18, y), theme.TEXT_MUTED)
            y += 18

        button_y = rect.bottom - 52
        if ui.button("open_profiles", pygame.Rect(rect.x + 18, button_y, 150, 36), "打开方案目录", kind="ghost"):
            _open_path(profiles_dir())
            app.set_status("已在资源管理器中打开方案目录")
        if ui.button("open_logs", pygame.Rect(rect.x + 178, button_y, 130, 36), "打开日志目录", kind="ghost"):
            _open_path(logs_dir())
            app.set_status("已在资源管理器中打开日志目录")

    def _draw_environment(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        surface = ui.surface
        theme.rounded_rect(surface, rect, theme.PANEL, radius=14, border=theme.BORDER_SOFT)
        theme.draw_text(surface, ui.fonts.get(14, bold=True), "运行环境自检", (rect.x + 18, rect.y + 16), theme.TEXT)
        theme.draw_text(surface, ui.fonts.get(11), "安装程序会部署下列组件；缺失项会影响对应功能",
                        (rect.x + 18, rect.y + 37), theme.TEXT_MUTED)

        try:
            import pygame as _pygame
            sdl_version = ".".join(str(part) for part in _pygame.version.SDL)
            pygame_version = _pygame.version.ver
        except Exception:
            sdl_version, pygame_version = "未知", "未知"

        hid_version = "未安装"
        try:
            import hid  # noqa: F401
            hid_version = getattr(hid, "__version__", "已安装")
        except Exception:
            pass

        vgamepad_version = "未安装"
        vgamepad_ok = False
        try:
            import vgamepad
            vgamepad_version = getattr(vgamepad, "__version__", "已安装")
            vgamepad_ok = True
        except ImportError:
            pass
        except Exception:
            vgamepad_version = "已安装（需要 ViGEmBus 驱动）"
            vgamepad_ok = True

        rows = [
            ("Python 运行时", f"{platform.python_version()} ({'64' if sys.maxsize > 2 ** 32 else '32'} 位)", True),
            ("pygame / SDL", f"{pygame_version} / {sdl_version}", app.manager.sdl.available),
            ("hidapi", hid_version, app.manager.hid.available),
            ("viGEmBus 驱动", app.vigem_message, app.vigem_ok),
            ("vgamepad", vgamepad_version, vgamepad_ok),
            ("键盘注入（SendInput）", "可用" if app.injector.supported else "不可用", app.injector.supported),
        ]

        y = rect.y + 66
        for label, value, ok in rows:
            row = pygame.Rect(rect.x + 18, y, rect.width - 36, 42)
            theme.rounded_rect(surface, row, theme.PANEL_ALT, radius=9, border=theme.BORDER_SOFT)
            pygame.draw.circle(surface, theme.ACCENT if ok else theme.WARN, (row.x + 18, row.centery), 5)
            theme.draw_text(surface, ui.fonts.get(12, bold=True), label, (row.x + 34, row.y + 7), theme.TEXT)
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(ui.fonts.get(11), str(value), row.width - 56),
                            (row.x + 34, row.y + 24), theme.TEXT_MUTED)
            y += 48

        y += 6
        theme.draw_text(surface, ui.fonts.get(11), "开源组件：pygame / SDL2、hidapi、vgamepad、ViGEmBus",
                        (rect.x + 18, y), theme.TEXT_MUTED)
        theme.draw_text(surface, ui.fonts.get(11), "协议参考：Nintendo Switch Reverse Engineering（震动编码 / 报文布局）",
                        (rect.x + 18, y + 18), theme.TEXT_MUTED)

        if not app.manager.sdl.available and app.manager.sdl.error:
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(
                ui.fonts.get(11), app.manager.sdl.error, rect.width - 36), (rect.x + 18, y + 44), theme.DANGER)


def _open_path(path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        try:
            import subprocess
            subprocess.Popen(["explorer", str(path)])
        except Exception:
            pass
