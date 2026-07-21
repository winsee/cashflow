# -*- coding: utf-8 -*-
"""把 docs/实体卡片/ 下的原始照片裁出卡面区域，输出到 build/cards_cropped/。

背景是深色桌面，卡片是浅色矩形：按亮度阈值找最大连通亮区的外接框即可。
裁剪只为降低人工/模型读图成本，原图始终保留为权威档案。
"""
import sys
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "实体卡片"
OUT = ROOT / "build" / "cards_cropped"
TARGET_W = 1100  # 裁剪后统一宽度，够看清最小号字


def card_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    g = ImageOps.grayscale(im).resize((200, 200))
    px = g.load()
    # 用图像中心区域的亮度做阈值参考：卡片一般居中且明显亮于背景
    vals = sorted(px[x, y] for x in range(200) for y in range(200))
    lo, hi = vals[len(vals) // 10], vals[-len(vals) // 10]
    thr = (lo + hi) / 2
    xs = [x for x in range(200) for y in range(200) if px[x, y] > thr]
    ys = [y for y in range(200) for x in range(200) if px[x, y] > thr]
    if not xs or not ys:
        return (0, 0, im.width, im.height)
    sx, sy = im.width / 200, im.height / 200
    pad = 6
    return (
        max(0, int((min(xs) - pad) * sx)),
        max(0, int((min(ys) - pad) * sy)),
        min(im.width, int((max(xs) + pad) * sx)),
        min(im.height, int((max(ys) + pad) * sy)),
    )


def main() -> int:
    if not SRC.is_dir():
        print(f"找不到源目录 {SRC}", file=sys.stderr)
        return 1
    n = 0
    for deck_dir in sorted(SRC.iterdir()):
        if not deck_dir.is_dir():
            continue
        dst_dir = OUT / deck_dir.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(deck_dir.glob("*.jpg"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
            im = Image.open(f)
            box = card_bbox(im)
            c = im.crop(box)
            if c.width > TARGET_W:
                c = c.resize((TARGET_W, round(c.height * TARGET_W / c.width)), Image.LANCZOS)
            c.save(dst_dir / f.name, quality=92)
            n += 1
    print(f"已裁剪 {n} 张 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
