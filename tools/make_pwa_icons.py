"""生成 PWA 图标（web/public/icons/）。

图形语言与 App 一致：桌游暖光的纸底、墨绿圆盘、金色的现金流循环箭头。
主图形收在中心 62% 以内，maskable 被裁成圆形/水滴形也不会切到内容。

产物入 git（随镜像交付），改了配色再跑一次即可：
    python tools/make_pwa_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"

BG = (241, 233, 218)      # #F1E9DA 纸底
GREEN = (21, 128, 61)     # #15803D 墨绿
GOLD = (180, 131, 42)     # #B4832A 金箔


def draw(size: int) -> Image.Image:
    s = size * 4                     # 4x 超采样后缩回，边缘干净
    img = Image.new("RGBA", (s, s), BG + (255,))
    d = ImageDraw.Draw(img)
    c = s / 2
    r = s * 0.31                     # 圆盘半径，落在 maskable 安全区内
    d.ellipse([c - r, c - r, c + r, c + r], fill=GREEN)

    # 金色循环箭头。PIL 的角度自 3 点方向顺时针增长
    rr, w = r * 0.58, r * 0.17
    start, end = 150, 390            # 缺口留在右下，箭头收在那里
    d.arc([c - rr, c - rr, c + rr, c + rr], start=start, end=end, fill=GOLD, width=int(w))

    th = math.radians(end)
    px, py = c + rr * math.cos(th), c + rr * math.sin(th)
    tx, ty = -math.sin(th), math.cos(th)     # 切线（前进方向）
    nx, ny = math.cos(th), math.sin(th)      # 法线（指向外）
    a, b = r * 0.44, r * 0.30
    d.polygon([
        (px + tx * a, py + ty * a),
        (px + nx * b - tx * b * .1, py + ny * b - ty * b * .1),
        (px - nx * b - tx * b * .1, py - ny * b - ty * b * .1),
    ], fill=GOLD)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw(size).save(OUT / f"icon-{size}.png")
    draw(180).save(OUT / "apple-touch-icon.png")   # iOS 主屏图标
    print("已写入", ", ".join(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
