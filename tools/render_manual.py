# -*- coding: utf-8 -*-
"""把说明书 PDF 渲染成分页 PNG，供人工/模型阅读核对规则。"""
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "docs" / "现金流游戏说明书.pdf"
OUT = ROOT / "build" / "manual"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    for i, page in enumerate(doc, 1):
        # 扫描件字号偏小，放大到 ~2000px 宽保证可读
        zoom = 2000 / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(OUT / f"p{i:02d}.png")
    print(f"已渲染 {doc.page_count} 页 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
