# -*- coding: utf-8 -*-
"""把说明书 PDF 渲染成上线用的压缩分页图，供 App 的 /manual 页面翻阅。

与 render_manual.py 的区别：那个产出 build/manual/*.png（约 74MB），只给人/模型
核对规则用；这个产出 server/manual_pages/pNN.webp（约 3.5MB），要入 git、随 Docker
镜像交付、由手机按页拉取。

用法：
    python tools/build_manual_pages.py                 # 默认 1400px 宽
    python tools/build_manual_pages.py --width 1800    # 嫌小字糊就调大重跑
"""
import argparse
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "docs" / "现金流游戏说明书.pdf"
OUT = ROOT / "server" / "manual_pages"

# 服务端 /api/manual/pages 认这几种后缀，清理旧产物时一并扫掉
SUFFIXES = (".webp", ".png", ".jpg", ".jpeg")


def main() -> int:
    ap = argparse.ArgumentParser(description="说明书 PDF → 分页 WebP")
    ap.add_argument("--pdf", type=Path, default=PDF, help="源 PDF")
    ap.add_argument("--out", type=Path, default=OUT, help="输出目录")
    ap.add_argument("--width", type=int, default=1400,
                    help="每页目标像素宽（默认 1400，约 170dpi）")
    ap.add_argument("--quality", type=int, default=82, help="WebP 质量（默认 82）")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"找不到 PDF：{args.pdf}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    # 先清旧产物：换 --width 或换 PDF 后，残留的旧页会按文件名混进序列里
    for old in args.out.iterdir():
        if old.is_file() and old.suffix.lower() in SUFFIXES:
            old.unlink()

    doc = fitz.open(args.pdf)
    total = 0
    for i, page in enumerate(doc, 1):
        zoom = args.width / page.rect.width
        pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        buf = BytesIO()
        img.save(buf, "WEBP", quality=args.quality, method=4)
        data = buf.getvalue()
        # 零填充两位：服务端按文件名字典序排页，p1/p10 会乱序
        (args.out / f"p{i:02d}.webp").write_bytes(data)
        total += len(data)
        print(f"  p{i:02d}.webp  {pm.width}×{pm.height}  {len(data) / 1024:.0f} KB")

    print(f"已生成 {doc.page_count} 页 → {args.out}（共 {total / 1048576:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
