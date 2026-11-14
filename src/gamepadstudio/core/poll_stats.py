"""轮询稳定性统计：间隔、抖动、最坏帧与卡顿计数.

用途：排查"手柄偶尔卡一下 / 掉帧 / 断连"——单纯看 Hz 平均值看不出问题，
需要看 P99 间隔、抖动（标准差）和超长间隔（卡顿）次数。
"""
from __future__ import annotations

import csv
import statistics
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List


class PollStats:
    """滚动窗口的轮询间隔统计.

    ``window`` 为参与统计的样本数（默认 600 ≈ 10 秒@60Hz），
    ``gap_factor`` 为卡顿判定倍数：某次间隔超过窗口均值的这么多倍即记一次卡顿。
    """

    def __init__(self, window: int = 600, gap_factor: float = 2.0) -> None:
        self.window = max(60, int(window))
        self.gap_factor = max(1.2, float(gap_factor))
        self._samples: Deque[float] = deque(maxlen=self.window)
        self._all: List[float] = []
        self.samples = 0
        self.stalls = 0
        self.total_ms = 0.0
        self.last_ms = 0.0
        self.started_at = time.monotonic()

    # ------------------------------------------------------------------ 记录
    def record(self, interval_ms: float) -> None:
        """记录一次轮询间隔（毫秒）."""
        if interval_ms <= 0.0 or interval_ms > 5000.0:
            return
        self.samples += 1
        self.last_ms = interval_ms
        self.total_ms += interval_ms
        self._samples.append(interval_ms)
        if len(self._all) < 5000:
            self._all.append(interval_ms)
        if interval_ms > 250.0:
            self.stalls += 1

    def reset(self) -> None:
        self._samples.clear()
        self._all.clear()
        self.samples = 0
        self.stalls = 0
        self.total_ms = 0.0
        self.last_ms = 0.0
        self.started_at = time.monotonic()

    # ------------------------------------------------------------------ 统计
    def mean_ms(self) -> float:
        if not self._samples:
            return 0.0
        return sum(self._samples) / len(self._samples)

    def hz(self) -> float:
        mean = self.mean_ms()
        return 1000.0 / mean if mean > 0 else 0.0

    def jitter_ms(self) -> float:
        """间隔标准差；样本不足 2 个返回 0."""
        if len(self._samples) < 2:
            return 0.0
        return statistics.pstdev(self._samples)

    def percentile(self, ratio: float) -> float:
        """窗口内间隔分位数（0..1），例如 0.99 得到 P99."""
        if not self._samples:
            return 0.0
        ordered = sorted(self._samples)
        index = max(0, min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1)))))
        return ordered[index]

    def worst_ms(self) -> float:
        return max(self._samples) if self._samples else 0.0

    def gap_count(self) -> int:
        """窗口内超过均值 gap_factor 倍的间隔个数（真实卡顿，不含首帧）."""
        mean = self.mean_ms()
        if mean <= 0 or len(self._samples) < 8:
            return 0
        return sum(1 for value in self._samples if value > mean * self.gap_factor)

    def uptime_s(self) -> float:
        return time.monotonic() - self.started_at

    def summary(self) -> Dict[str, float]:
        return {
            "samples": float(self.samples),
            "window": float(len(self._samples)),
            "hz": self.hz(),
            "mean_ms": self.mean_ms(),
            "jitter_ms": self.jitter_ms(),
            "p50_ms": self.percentile(0.50),
            "p99_ms": self.percentile(0.99),
            "worst_ms": self.worst_ms(),
            "stalls": float(self.stalls),
            "gaps": float(self.gap_count()),
            "last_ms": self.last_ms,
            "uptime_s": self.uptime_s(),
        }

    def series(self) -> List[float]:
        """用于绘制折线的窗口数据."""
        return list(self._samples)

    def verdict(self) -> str:
        """一句话结论，给界面直接显示."""
        mean = self.mean_ms()
        if mean <= 0:
            return "暂无数据：连接手柄并保持窗口在前台"
        gaps = self.gap_count()
        jitter = self.jitter_ms()
        p99 = self.percentile(0.99)
        if mean * self.gap_factor and p99 > mean * self.gap_factor and gaps >= 3:
            return "存在明显卡顿：P99 远高于平均值，检查 USB 线材 / 蓝牙干扰 / 后台占用"
        if jitter > mean * 0.35:
            return "抖动偏大：平均间隔波动超过 35%，建议换端口或改用有线连接"
        return "轮询稳定：间隔波动在正常范围"

    # ------------------------------------------------------------------ 导出
    def export_csv(self, path) -> bool:
        """导出全部样本（本次会话累计，最多 5000 条）."""
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["index", "interval_ms"])
                for index, value in enumerate(self._all, start=1):
                    writer.writerow([index, f"{value:.2f}"])
                summary = self.summary()
                writer.writerow([])
                writer.writerow(["metric", "value"])
                for key in ("samples", "hz", "mean_ms", "jitter_ms", "p50_ms", "p99_ms",
                            "worst_ms", "stalls", "gaps"):
                    writer.writerow([key, f"{summary[key]:.3f}"])
            return True
        except Exception:
            return False
