"""生成程序图标（assets/icon.png + assets/icon.ico）。

用 Pillow 绘制，避免仓库里放二进制美术资源。
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "assets"
COLOR_BG = (16, 20, 26)
COLOR_BODY = (64, 220, 160)
COLOR_DARK = (16, 20, 26)


def draw_icon(size: int = 256) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(56 * scale)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=COLOR_BG)

    # 手柄机身
    body = [int(28 * scale), int(84 * scale), int(228 * scale), int(156 * scale)]
    draw.rounded_rectangle(body, radius=int(34 * scale), fill=COLOR_BODY)

    # 两侧握把
    grip_w, grip_h = int(44 * scale), int(70 * scale)
    for x in (int(30 * scale), int(182 * scale)):
        draw.rounded_rectangle([x, int(120 * scale), x + grip_w, int(120 * scale) + grip_h],
                               radius=int(22 * scale), fill=COLOR_BODY)

    # 左摇杆
    draw.ellipse([int(58 * scale), int(101 * scale), int(102 * scale), int(145 * scale)], fill=COLOR_DARK)
    draw.ellipse([int(70 * scale), int(113 * scale), int(90 * scale), int(133 * scale)], fill=COLOR_BODY)

    # 右侧按键
    for cx, cy in ((168, 106), (190, 118), (152, 118), (168, 130)):
        r = int(9 * scale)
        draw.ellipse([cx * scale - r, cy * scale - r, cx * scale + r, cy * scale + r], fill=COLOR_DARK)

    # 中央十字键
    cx, cy, arm = 128, 120, int(7 * scale)
    draw.rectangle([(cx - arm) * scale, (cy - arm * 3) * scale, (cx + arm) * scale, (cy + arm * 3) * scale],
                   fill=COLOR_DARK)
    draw.rectangle([(cx - arm * 3) * scale, (cy - arm) * scale, (cx + arm * 3) * scale, (cy + arm) * scale],
                   fill=COLOR_DARK)
    return image


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = draw_icon(256)
    icon.save(OUT_DIR / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(OUT_DIR / "icon.ico", sizes=sizes)
    print("已生成", OUT_DIR / "icon.png", "与", OUT_DIR / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
