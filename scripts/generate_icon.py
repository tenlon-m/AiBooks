"""AiBooks 应用图标生成脚本.

使用 Pillow 绘制 AI + 书本双主题多尺寸图标，输出 .ico 文件到 src/resources/app.ico。
视觉设计：书本主体（深蓝 #1565c0）+ 神经网络节点连线（亮蓝 #42a5f5）+ 中心发光核心（金色 #ffd54f）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

MAIN_COLOR = (21, 101, 192, 255)
ACCENT_COLOR = (66, 165, 245, 255)
GLOW_COLOR = (255, 213, 79, 255)
PAGE_COLOR = (255, 255, 255, 220)
PEN_COLOR = (33, 33, 33, 255)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "src" / "resources" / "app.ico"
ALL_SIZES = [16, 32, 48, 64, 128, 256]


def _draw_book(draw: ImageDraw.ImageDraw, size: int) -> None:
    """绘制书本主体轮廓与书页."""
    margin = size * 0.15
    left = margin
    right = size - margin
    top = size * 0.20
    bottom = size * 0.80
    spine_x = left + (right - left) * 0.18

    draw.rounded_rectangle(
        [left, top, right, bottom],
        radius=size * 0.06,
        fill=MAIN_COLOR,
    )
    draw.rounded_rectangle(
        [left + size * 0.02, top + size * 0.02, spine_x, bottom - size * 0.02],
        radius=size * 0.03,
        fill=(13, 71, 161, 255),
    )
    if size >= 32:
        page_left = spine_x + size * 0.03
        page_right = right - size * 0.04
        page_top = top + size * 0.08
        page_bottom = bottom - size * 0.08
        draw.rounded_rectangle(
            [page_left, page_top, page_right, page_bottom],
            radius=size * 0.02,
            fill=PAGE_COLOR,
        )
        if size >= 64:
            for i in range(3):
                ly = page_top + (page_bottom - page_top) * (0.25 + i * 0.22)
                draw.line(
                    [page_left + size * 0.04, ly, page_right - size * 0.04, ly],
                    fill=(180, 180, 180, 160),
                    width=max(1, size // 64),
                )


def _draw_neural_net(img: Image.Image, draw: ImageDraw.ImageDraw, size: int) -> None:
    """绘制神经网络节点与连线."""
    if size < 32:
        return

    cx, cy = size / 2, size / 2
    node_radius = max(1, size * 0.04)

    if size >= 48:
        nodes = [
            (size * 0.28, size * 0.35),
            (size * 0.72, size * 0.35),
            (size * 0.28, size * 0.65),
            (size * 0.72, size * 0.65),
        ]
        for n in nodes:
            draw.line(
                [cx, cy, n[0], n[1]],
                fill=ACCENT_COLOR,
                width=max(1, size // 80),
            )
        for n in nodes:
            draw.ellipse(
                [n[0] - node_radius, n[1] - node_radius, n[0] + node_radius, n[1] + node_radius],
                fill=ACCENT_COLOR,
            )

    if size >= 128:
        outer_nodes = [
            (size * 0.18, size * 0.50),
            (size * 0.82, size * 0.50),
            (size * 0.50, size * 0.18),
            (size * 0.50, size * 0.82),
        ]
        for n in outer_nodes:
            draw.line(
                [cx, cy, n[0], n[1]],
                fill=(66, 165, 245, 120),
                width=max(1, size // 128),
            )
            draw.ellipse(
                [n[0] - node_radius * 0.7, n[1] - node_radius * 0.7,
                 n[0] + node_radius * 0.7, n[1] + node_radius * 0.7],
                fill=(66, 165, 245, 180),
            )


def _draw_glow_core(img: Image.Image, draw: ImageDraw.ImageDraw, size: int) -> None:
    """绘制中心发光核心."""
    cx, cy = size / 2, size / 2
    core_radius = max(1, size * 0.08)

    if size >= 48:
        glow_radius = core_radius * 2.5
        glow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_img)
        glow_draw.ellipse(
            [cx - glow_radius, cy - glow_radius, cx + glow_radius, cy + glow_radius],
            fill=(*GLOW_COLOR[:3], 80),
        )
        glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=size * 0.04))
        img.alpha_composite(glow_img)

    draw.ellipse(
        [cx - core_radius, cy - core_radius, cx + core_radius, cy + core_radius],
        fill=GLOW_COLOR,
    )

    if size >= 64:
        inner_radius = core_radius * 0.5
        draw.ellipse(
            [cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius],
            fill=(255, 255, 255, 220),
        )


def _draw_pen(draw: ImageDraw.ImageDraw, size: int) -> None:
    """绘制笔尖细节（仅大尺寸）."""
    if size < 128:
        return

    pen_w = size * 0.03
    pen_x = size * 0.82
    pen_top = size * 0.12
    pen_bottom = size * 0.30

    draw.rounded_rectangle(
        [pen_x - pen_w / 2, pen_top, pen_x + pen_w / 2, pen_bottom],
        radius=pen_w / 2,
        fill=PEN_COLOR,
    )
    draw.polygon(
        [
            (pen_x - pen_w * 0.8, pen_bottom),
            (pen_x + pen_w * 0.8, pen_bottom),
            (pen_x, pen_bottom + size * 0.06),
        ],
        fill=PEN_COLOR,
    )


def draw_16() -> Image.Image:
    return _build(16)


def draw_32() -> Image.Image:
    return _build(32)


def draw_48() -> Image.Image:
    return _build(48)


def draw_64() -> Image.Image:
    return _build(64)


def draw_128() -> Image.Image:
    return _build(128)


def draw_256() -> Image.Image:
    return _build(256)


def _build_16() -> Image.Image:
    """16x16 专用简化设计：蓝色书本 + 金色中心点."""
    size = 16
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [2, 3, 14, 13],
        radius=2,
        fill=MAIN_COLOR,
    )
    draw.rectangle(
        [4, 5, 12, 11],
        fill=PAGE_COLOR,
    )
    draw.ellipse(
        [6, 6, 10, 10],
        fill=GLOW_COLOR,
    )
    return img


def _build(size: int) -> Image.Image:
    if size <= 16:
        return _build_16()
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _draw_book(draw, size)
    _draw_neural_net(img, draw, size)
    _draw_glow_core(img, draw, size)
    _draw_pen(draw, size)
    return img


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    images = [_build(s) for s in ALL_SIZES]
    base = images[-1]
    base.save(
        OUTPUT_PATH,
        format="ICO",
        sizes=[(s, s) for s in ALL_SIZES],
    )
    file_size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"图标已生成: {OUTPUT_PATH}")
    print(f"文件大小: {file_size_kb:.1f} KB")
    print(f"尺寸图层: {ALL_SIZES}")


if __name__ == "__main__":
    main()