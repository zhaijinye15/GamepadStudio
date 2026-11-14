"""轮询统计页：间隔分布、抖动、最差帧与卡顿次数的可视化."""
from __future__ import annotations

import pygame

from .. import theme


class StatsScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.gap_factor = 2.0

    def handle_event(self, event) -> None:
        return

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        stats = app.poll_stats
        summary = stats.summary()
        gap = 12
        top = pygame.Rect(rect.x, rect.y, rect.width, 178)
        self._draw_metrics(ui, top, summary)
        bottom = pygame.Rect(rect.x, top.bottom + gap, rect.width, max(180, rect.bottom - top.bottom - gap))
        self._draw_graph(ui, bottom)

    # ---------------------------------------------------------------- 指标卡
    def _draw_metrics(self, ui, rect: pygame.Rect, summary) -> None:
        app = self.app
        surface = ui.surface
        inner = ui.card(rect, "轮询质量", "每帧采样间隔越均匀越好；P99 与抖动比平均值更能暴露卡顿")

        tiles = [
            ("有效频率", f"{summary['hz']:.0f} Hz", theme.ACCENT),
            ("平均间隔", f"{summary['mean_ms']:.1f} ms", theme.TEXT),
            ("P99 间隔", f"{summary['p99_ms']:.1f} ms", theme.WARN if summary["p99_ms"] > summary["mean_ms"] * 2 else theme.TEXT),
            ("抖动 σ", f"{summary['jitter_ms']:.1f} ms", theme.WARN if summary["jitter_ms"] > summary["mean_ms"] * 0.35 else theme.TEXT),
            ("最差一帧", f"{summary['worst_ms']:.1f} ms", theme.TEXT_DIM),
            ("卡顿 / 断流", f"{int(summary['gaps'])} / {int(summary['stalls'])}", theme.DANGER if summary["stalls"] else theme.TEXT_DIM),
        ]
        columns = 3
        gap_x, gap_y = 10, 8
        tile_h = 56
        tile_w = (inner.width - gap_x * (columns - 1)) // columns
        for index, (label, value, color) in enumerate(tiles):
            column = index % columns
            row = index // columns
            tile = pygame.Rect(inner.x + column * (tile_w + gap_x),
                               inner.y + row * (tile_h + gap_y), tile_w, tile_h)
            theme.rounded_rect(surface, tile, theme.PANEL_ALT, radius=10, border=theme.BORDER_SOFT)
            theme.draw_text(surface, ui.fonts.get(11), label, (tile.x + 12, tile.y + 9), theme.TEXT_MUTED)
            theme.draw_text(surface, ui.fonts.get(15, bold=True), value, (tile.x + 12, tile.y + 28),
                            color, align="topleft")

        # 底部：按钮 + 卡顿阈值
        control_y = inner.bottom - 34
        if ui.button("stats_export", pygame.Rect(inner.x, control_y, 132, 32),
                     "导出 CSV…", kind="primary", font_size=13):
            app.export_poll_csv()
        if ui.button("stats_reset", pygame.Rect(inner.x + 140, control_y, 96, 32),
                     "清零", kind="ghost", font_size=13):
            app.reset_poll_stats()
        label_x = inner.x + 250
        theme.draw_text(surface, ui.fonts.get(11), "卡顿阈值",
                        (label_x, control_y + 10), theme.TEXT_MUTED)
        factor = ui.slider("stats_gap_factor", pygame.Rect(label_x + 56, control_y, 190, 32),
                           self.gap_factor, 1.5, 4.0, 0.1,
                           fmt=lambda value: f"×{value:.1f}")
        self.gap_factor = factor
        app.poll_stats.gap_factor = factor
        theme.draw_text(surface, ui.fonts.get(11),
                        f"采样 {int(summary['samples'])} 帧 · 运行 {int(summary['uptime_s'])} 秒",
                        (inner.right, control_y + 10), theme.TEXT_MUTED, align="topright")

    # ---------------------------------------------------------------- 折线图
    def _draw_graph(self, ui, rect: pygame.Rect) -> None:
        app = self.app
        stats = app.poll_stats
        surface = ui.surface
        inner = ui.card(rect, "间隔走势", "纵轴为每帧间隔（毫秒），虚线是当前平均值")
        series = stats.series()
        verdict = stats.verdict()
        verdict_color = theme.ACCENT if "稳定" in verdict else theme.WARN
        theme.draw_text(surface, ui.fonts.get(13), verdict,
                        (inner.x, inner.bottom - 4), verdict_color, align="bottomleft")

        plot = pygame.Rect(inner.x, inner.y + 6, inner.width, inner.height - 48)
        theme.rounded_rect(surface, plot, theme.PANEL_ALT, radius=10, border=theme.BORDER_SOFT)
        if len(series) < 2:
            theme.draw_text(surface, ui.fonts.get(13), "暂无数据：连接手柄后在本页停留几秒",
                            plot.center, theme.TEXT_MUTED, align="center")
            return

        mean = sum(series) / len(series)
        ceiling = max(max(series) * 1.15, mean * 2.0, 20.0)
        floor = min(min(series) * 0.85, mean * 0.5)
        span = max(1.0, ceiling - floor)
        count = len(series)
        points = []
        for index, value in enumerate(series):
            x = plot.x + 10 + int((plot.width - 20) * index / max(1, count - 1))
            y = plot.bottom - 10 - int((plot.height - 20) * (value - floor) / span)
            points.append((x, y))

        # 平均值参考线与阈值线
        mean_y = plot.bottom - 10 - int((plot.height - 20) * (mean - floor) / span)
        for x in range(plot.x + 10, plot.right - 10, 14):
            pygame.draw.line(surface, theme.BORDER, (x, mean_y), (x + 6, mean_y), 1)
        gap_y = plot.bottom - 10 - int((plot.height - 20) * (mean * stats.gap_factor - floor) / span)
        if plot.y + 4 < gap_y < plot.bottom - 4:
            pygame.draw.line(surface, theme.WARN, (plot.x + 8, gap_y), (plot.right - 8, gap_y), 1)
            theme.draw_text(surface, ui.fonts.get(10), "卡顿线", (plot.right - 10, gap_y - 2),
                            theme.WARN, align="bottomright")

        pygame.draw.lines(surface, theme.ACCENT, False, points, 2)
        # 最新一点高亮
        pygame.draw.circle(surface, theme.ACCENT, points[-1], 4)

        labels = ("实时", f"{mean:.1f} ms 平均", f"上限 {ceiling:.0f} ms")
        theme.draw_text(surface, ui.fonts.get(10), labels[1], (plot.x + 10, plot.y + 6),
                        theme.TEXT_MUTED)
        theme.draw_text(surface, ui.fonts.get(10), labels[2], (plot.x + 10, plot.bottom - 18),
                        theme.TEXT_MUTED)
