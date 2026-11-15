"""游戏库页：扫描本机游戏、一键后台启动；手游走 MuMu 模拟器."""
from __future__ import annotations

import pygame

from .. import theme

FILTERS = ("全部", "桌面游戏", "模拟器手游")
FILTER_KINDS = ("", "desktop", "emulator")


class LibraryScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.query = ""
        self.filter_index = 0

    def handle_event(self, event) -> None:
        return

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        lib = self.app.library
        gap = 12
        top = pygame.Rect(rect.x, rect.y, rect.width, 96)
        self._draw_toolbar(ui, top)
        body = pygame.Rect(rect.x, top.bottom + gap, rect.width, max(160, rect.bottom - top.bottom - gap))
        self._draw_list(ui, body)

    # ---------------------------------------------------------------- 工具条
    def _draw_toolbar(self, ui, rect: pygame.Rect) -> None:
        lib = self.app.library
        surface = ui.surface
        inner = ui.card(rect, "游戏库", "扫描本机已安装的游戏，点「启动」即在后台拉起；手游通过 MuMu 模拟器打开")

        self.query = ui.text_input("lib_search", pygame.Rect(inner.x, inner.y + 6, 236, 32),
                                   self.query, "搜索游戏名…", max_len=32)
        scanning = lib.scanning
        if ui.button("lib_scan", pygame.Rect(inner.x + 246, inner.y + 6, 136, 32),
                     "扫描中…" if scanning else "扫描本机游戏",
                     kind="primary", enabled=not scanning, font_size=13):
            self.app.scan_games()
        if ui.button("lib_refresh", pygame.Rect(inner.x + 390, inner.y + 6, 108, 32),
                     "重扫手游", kind="default", font_size=13,
                     enabled=lib.mumu is not None and not scanning):
            self.app.refresh_android_games()

        # 筛选按钮
        x = inner.x + 510
        for index, label in enumerate(FILTERS):
            active = self.filter_index == index
            rect_btn = pygame.Rect(x, inner.y + 6, 92, 32)
            if ui.button(f"lib_filter_{index}", rect_btn, label,
                         kind="primary" if active else "ghost", font_size=12):
                self.filter_index = index
            x += 98

        # MuMu 状态行
        status_color = theme.ACCENT if (lib.mumu and lib.mumu.android_started) else theme.TEXT_MUTED
        theme.draw_text(surface, ui.fonts.get(12), lib.mumu_summary,
                        (inner.x, inner.y + 50), status_color)
        if lib.mumu is not None and not lib.mumu.android_started:
            if ui.button("lib_start_mumu", pygame.Rect(inner.x + 226, inner.y + 44, 116, 26),
                         "启动 MuMu", kind="warning", font_size=12):
                self.app.start_mumu()
        total = len(lib.games)
        phone = len([entry for entry in lib.games if entry.kind == "emulator"])
        theme.draw_text(surface, ui.fonts.get(11),
                        f"共 {total} 条 · 手游 {phone} 个 · 数据缓存于 %APPDATA%\\GamepadStudio",
                        (inner.right, inner.y + 50), theme.TEXT_MUTED, align="topright")

    # ---------------------------------------------------------------- 列表
    def _visible_games(self):
        lib = self.app.library
        keyword = self.query.strip().lower()
        kind = FILTER_KINDS[self.filter_index]
        result = []
        for entry in lib.games:
            if kind == "desktop" and entry.kind == "emulator":
                continue
            if kind == "emulator" and entry.kind != "emulator":
                continue
            if keyword and keyword not in entry.name.lower() and keyword not in (entry.target or "").lower():
                continue
            result.append(entry)
        return result

    def _draw_list(self, ui, rect: pygame.Rect) -> None:
        lib = self.app.library
        surface = ui.surface
        inner = ui.card(rect, "已安装游戏",
                        "注册表 / Steam 自动识别；模拟器手游需要在 MuMu 运行时才列得出来")

        entries = self._visible_games()
        row_height = 60
        viewport = pygame.Rect(inner.x, inner.y + 4, inner.width, max(60, inner.height - 46))
        if not entries:
            hint = "正在扫描…" if lib.scanning else (
                "没有匹配的条目：点「扫描本机游戏」重新识别" if not lib.games else "换个关键词试试")
            theme.draw_text(surface, ui.fonts.get(13), hint, viewport.center, theme.TEXT_MUTED, align="center")
            theme.draw_text(surface, ui.fonts.get(11),
                            "手游请先点「启动 MuMu」，进入安卓桌面后再点「重扫手游」",
                            (viewport.centerx, viewport.centery + 22), theme.TEXT_MUTED, align="center")
            return

        offset = ui.scroll("lib_list", viewport, len(entries) * row_height, row_height)
        surface.set_clip(viewport)
        launched = self.app.game_launching
        for index, entry in enumerate(entries):
            y = viewport.y + 4 + index * row_height - offset
            if y > viewport.bottom or y + row_height < viewport.y:
                continue
            row = pygame.Rect(viewport.x, y, viewport.width, row_height - 8)
            hover = row.collidepoint(ui.mouse)
            if hover:
                theme.rounded_rect(surface, row, (22, 27, 35), radius=9)

            # 左侧色条区分类型
            kind_color = {"steam": (94, 138, 214), "emulator": theme.WARN, "exe": theme.ACCENT}.get(entry.kind, theme.ACCENT)
            pygame.draw.rect(surface, kind_color, pygame.Rect(row.x + 2, row.y + 12, 3, row.height - 24), border_radius=2)

            name_font = ui.fonts.get(15, bold=True)
            theme.draw_text(surface, name_font, theme.ellipsize(name_font, entry.name, row.width - 220),
                            (row.x + 16, row.y + 12), theme.TEXT)
            small = ui.fonts.get(11)
            detail = entry.source
            if entry.kind == "emulator":
                detail += f" · {entry.target}"
            elif entry.kind == "steam":
                detail += f" · AppID {entry.app_id}"
            elif entry.target:
                detail += " · " + entry.target
            theme.draw_text(surface, small, theme.ellipsize(small, detail, row.width - 240),
                            (row.x + 16, row.y + 34), theme.TEXT_MUTED)

            busy = launched == entry.name
            if ui.button(f"lib_launch_{index}", pygame.Rect(row.right - 108, row.y + 12, 92, 30),
                         "启动中…" if busy else "启动",
                         kind="primary", enabled=not busy and not lib.scanning, font_size=13):
                self.app.launch_game(entry)
        surface.set_clip(None)

        # 底部提示
        theme.draw_text(surface, ui.fonts.get(11),
                        f"{len(entries)} 条 · 滚轮可上下翻动 · 双击列表左侧区域可复制路径",
                        (inner.x, inner.bottom - 2), theme.TEXT_MUTED, align="bottomleft")
