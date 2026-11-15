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
    def toolbar_height(self, width: int) -> int:
        """工具条高度随窗口宽度变化（按行数算），避免按钮被卡片底边裁掉."""
        rows = self._layout_rows(max(240, width - 36))
        return 54 + len(rows) * 38 + 14

    def _layout_rows(self, inner_w: int):
        """按可用宽度贪心排布：放不下就换行，返回每行 [(key, x, w)]."""
        rows = []
        row = []
        cursor = 0

        def push(key: str, width: int) -> None:
            nonlocal row, cursor
            gap = 0 if not row else 10
            if row and cursor + gap + width > inner_w:
                rows.append(row)
                row = []
                cursor = 0
                gap = 0
            row.append((key, cursor + gap, width))
            cursor = cursor + gap + width

        search_w = min(236, max(150, inner_w - 264))
        push("search", search_w)
        push("scan", 136)
        push("refresh", 108)
        # 三个筛选按钮作为一组整体换行，避免"全部"留在上一行
        group_w = len(FILTERS) * 92 + (len(FILTERS) - 1) * 10
        gap = 0 if not row else 10
        if row and cursor + gap + group_w > inner_w:
            rows.append(row)
            row = []
            cursor = 0
        for index in range(len(FILTERS)):
            push(f"filter{index}", 92)
        if row:
            rows.append(row)
        rows.append([("status", 0, 0)])
        return rows

    def draw(self, ui, rect: pygame.Rect) -> None:
        height = self.toolbar_height(rect.width)
        top = pygame.Rect(rect.x, rect.y, rect.width, height)
        self._draw_toolbar(ui, top)
        body = pygame.Rect(rect.x, top.bottom + 12, rect.width, max(120, rect.bottom - top.bottom - 12))
        self._draw_list(ui, body)

    # ---------------------------------------------------------------- 工具条
    def _draw_toolbar(self, ui, rect: pygame.Rect) -> None:
        lib = self.app.library
        surface = ui.surface
        inner = ui.card(rect, "游戏库", "扫描本机已安装的游戏，点「启动」即在后台拉起；手游通过 MuMu 模拟器打开")
        rows = self._layout_rows(max(240, rect.width - 36))
        scanning = lib.scanning

        for row_index, items in enumerate(rows):
            base_y = inner.y + row_index * 38
            for key, x, width in items:
                if key == "search":
                    self.query = ui.text_input("lib_search", pygame.Rect(inner.x + x, base_y + 4, width, 32),
                                               self.query, "搜索游戏名…", max_len=32)
                elif key == "scan":
                    if ui.button("lib_scan", pygame.Rect(inner.x + x, base_y + 4, width, 32),
                                 "扫描中…" if scanning else "扫描本机游戏",
                                 kind="primary", enabled=not scanning, font_size=13):
                        self.app.scan_games()
                elif key == "refresh":
                    if ui.button("lib_refresh", pygame.Rect(inner.x + x, base_y + 4, width, 32),
                                 "重扫手游", kind="default", font_size=13,
                                 enabled=lib.mumu is not None and not scanning):
                        self.app.refresh_android_games()
                elif key.startswith("filter"):
                    index = int(key[6:])
                    active = self.filter_index == index
                    if ui.button(f"lib_filter_{index}", pygame.Rect(inner.x + x, base_y + 4, width, 32),
                                 FILTERS[index], kind="primary" if active else "ghost", font_size=12):
                        self.filter_index = index
                elif key == "status":
                    status_color = theme.ACCENT if (lib.mumu and lib.mumu.android_started) else theme.TEXT_MUTED
                    summary = lib.mumu_summary or "未检测到 MuMu 模拟器"
                    theme.draw_text(surface, ui.fonts.get(12), summary, (inner.x, base_y + 8), status_color)
                    if lib.mumu is not None and not lib.mumu.android_started:
                        if ui.button("lib_start_mumu", pygame.Rect(inner.right - 116, base_y + 4, 116, 26),
                                     "启动 MuMu", kind="warning", font_size=12):
                            self.app.start_mumu()


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
