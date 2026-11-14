"""手柄 3D 模型的程序化几何（无外部依赖，纯 Python）.

模型很轻：一个超椭圆挤出的机身 + 若干圆柱体按键 + 两根摇杆 + 扳机。
所有面都是凸多边形，渲染端用画家算法按深度排序即可，不需要 z-buffer。

坐标约定（右手系）：x 向右、y 向上、z 指向观察者；机身中心在原点。
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

Point = Tuple[float, float, float]
Face = Tuple[List[Point], Tuple[int, int, int], str]   # 顶点、颜色、语义标签

BODY_HALF_W = 2.15
BODY_HALF_H = 0.95
BODY_HALF_Z = 0.26
BODY_SUPERNESS = 3.4

#: 语义按键 -> 机身平面上的位置（x, y）与半径
BUTTON_LAYOUT: Dict[str, Tuple[float, float, float, str]] = {
    "y":  (1.02, 0.44, 0.20, "#f2c14e"),
    "x":  (0.62, 0.06, 0.20, "#4f9cf9"),
    "b":  (1.42, 0.06, 0.20, "#e2574c"),
    "a":  (1.02, -0.32, 0.20, "#57c785"),
    "back": (-0.42, 0.34, 0.13, "#9aa4b2"),
    "start": (0.36, 0.34, 0.13, "#9aa4b2"),
    "guide": (0.0, 0.62, 0.14, "#63d0c4"),
    "l3": (-1.52, 0.0, 0.16, "#5b6472"),
    "r3": (1.86, 0.16, 0.16, "#5b6472"),
}

#: 左右摇杆中心（左摇杆在机身左侧，右摇杆在右下）
STICK_LAYOUT: Dict[str, Tuple[float, float]] = {
    "left": (-1.28, -0.06),
    "right": (1.86, -0.34),
}

BODY_COLOR = (42, 48, 58)
FACE_COLOR = (54, 62, 74)
GRIP_COLOR = (34, 39, 48)
STICK_COLOR = (26, 30, 38)


def superellipse(a: float, b: float, n: float, count: int) -> List[Tuple[float, float]]:
    """超椭圆（圆角矩形近似），返回闭合轮廓."""
    points: List[Tuple[float, float]] = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        cos_t, sin_t = math.cos(angle), math.sin(angle)
        x = a * _signed_pow(cos_t, 2.0 / n)
        y = b * _signed_pow(sin_t, 2.0 / n)
        points.append((x, y))
    return points


def _signed_pow(value: float, exponent: float) -> float:
    if value == 0.0:
        return 0.0
    return math.copysign(abs(value) ** exponent, value)


def _vec(a: Point, b: Point) -> Point:
    return (b[0] - a[0], b[1] - a[1], b[2] - a[2])


def _cross(u: Point, v: Point) -> Point:
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def build_gamepad(segments: int = 40, detail: int = 14) -> List[Face]:
    """生成整台手柄的面列表."""
    faces: List[Face] = []

    outline = superellipse(BODY_HALF_W, BODY_HALF_H, BODY_SUPERNESS, segments)
    bevel_outline = superellipse(BODY_HALF_W * 0.985, BODY_HALF_H * 0.975,
                                 BODY_SUPERNESS, segments)

    top_center: Point = (0.0, 0.0, BODY_HALF_Z)
    bottom_center: Point = (0.0, 0.0, -BODY_HALF_Z)

    # 顶面扇形三角
    for index in range(segments):
        p1 = (bevel_outline[index][0], bevel_outline[index][1], BODY_HALF_Z * 0.86)
        p2 = (bevel_outline[(index + 1) % segments][0],
              bevel_outline[(index + 1) % segments][1], BODY_HALF_Z * 0.86)
        faces.append(([top_center, p1, p2], FACE_COLOR, "body"))

    # 底面扇形三角
    for index in range(segments):
        p1 = (outline[index][0], outline[index][1], -BODY_HALF_Z)
        p2 = (outline[(index + 1) % segments][0], outline[(index + 1) % segments][1], -BODY_HALF_Z)
        faces.append(([bottom_center, p2, p1], GRIP_COLOR, "body"))

    # 侧壁：上沿倒角 + 竖直侧壁
    for index in range(segments):
        nxt = (index + 1) % segments
        t1 = (bevel_outline[index][0], bevel_outline[index][1], BODY_HALF_Z * 0.86)
        t2 = (bevel_outline[nxt][0], bevel_outline[nxt][1], BODY_HALF_Z * 0.86)
        m1 = (outline[index][0], outline[index][1], BODY_HALF_Z * 0.42)
        m2 = (outline[nxt][0], outline[nxt][1], BODY_HALF_Z * 0.42)
        b1 = (outline[index][0], outline[index][1], -BODY_HALF_Z)
        b2 = (outline[nxt][0], outline[nxt][1], -BODY_HALF_Z)
        faces.append(([t1, t2, m2, m1], BODY_COLOR, "body"))
        faces.append(([m1, m2, b2, b1], GRIP_COLOR, "body"))

    # 按键
    for name, (x, y, radius, color) in BUTTON_LAYOUT.items():
        faces.extend(_cylinder(x, y, BODY_HALF_Z * 0.92, radius, 0.09,
                               _hex_to_rgb(color), tag=name, detail=detail))

    # 摇杆：底座 + 杆 + 顶帽
    for which, (x, y) in STICK_LAYOUT.items():
        faces.extend(_cylinder(x, y, BODY_HALF_Z * 0.92, 0.34, 0.05,
                               (30, 34, 42), tag=f"stickbase_{which}", detail=detail))
        faces.extend(_cylinder(x, y, BODY_HALF_Z * 0.92 + 0.05, 0.14, 0.26,
                               STICK_COLOR, tag=f"stick_{which}", detail=detail))
        faces.extend(_cylinder(x, y + 0.12, BODY_HALF_Z * 0.92 + 0.30, 0.24, 0.07,
                               (70, 78, 92), tag=f"stickcap_{which}", detail=detail))

    # 肩键（机身顶部左右两侧的小凸台）
    for which, x, color in (("lb", -1.72, (92, 100, 114)), ("rb", 1.72, (92, 100, 114))):
        faces.extend(_box(x, 0.0, BODY_HALF_Z * 0.5, 0.55, 0.28, 0.16,
                          color, tag=which))
    return faces


def _cylinder(cx: float, cy: float, base_z: float, radius: float, height: float,
              color: Tuple[int, int, int], tag: str, detail: int = 14) -> List[Face]:
    faces: List[Face] = []
    ring_top: List[Point] = []
    ring_bottom: List[Point] = []
    for index in range(detail):
        angle = 2.0 * math.pi * index / detail
        dx, dy = math.cos(angle) * radius, math.sin(angle) * radius
        ring_bottom.append((cx + dx, cy + dy, base_z))
        ring_top.append((cx + dx, cy + dy, base_z + height))
    top_center = (cx, cy, base_z + height)
    for index in range(detail):
        nxt = (index + 1) % detail
        faces.append(([top_center, ring_top[index], ring_top[nxt], ], color, tag))
        faces.append(([ring_bottom[index], ring_bottom[nxt], ring_top[nxt], ring_top[index]],
                      _shade(color, 0.82), tag))
    return faces


def _box(cx: float, cy: float, cz: float, half_x: float, half_y: float, half_z: float,
         color: Tuple[int, int, int], tag: str) -> List[Face]:
    corners = [
        (cx - half_x, cy - half_y, cz - half_z), (cx + half_x, cy - half_y, cz - half_z),
        (cx + half_x, cy + half_y, cz - half_z), (cx - half_x, cy + half_y, cz - half_z),
        (cx - half_x, cy - half_y, cz + half_z), (cx + half_x, cy - half_y, cz + half_z),
        (cx + half_x, cy + half_y, cz + half_z), (cx - half_x, cy + half_y, cz + half_z),
    ]
    quads = [
        [4, 5, 6, 7], [1, 0, 3, 2], [0, 1, 5, 4],
        [2, 3, 7, 6], [0, 4, 7, 3], [1, 2, 6, 5],
    ]
    return [([corners[i] for i in quad], color, tag) for quad in quads]


def _shade(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return (max(0, min(255, int(color[0] * factor))),
            max(0, min(255, int(color[1] * factor))),
            max(0, min(255, int(color[2] * factor))))


def _hex_to_rgb(text: str) -> Tuple[int, int, int]:
    text = text.lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def face_normal(face: Sequence[Point]) -> Point:
    """用前三个顶点求法向量（凸多边形足够）."""
    u = _vec(face[0], face[1])
    v = _vec(face[0], face[2])
    return _cross(u, v)
