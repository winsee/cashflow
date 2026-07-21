# -*- coding: utf-8 -*-
"""把录入库（server/data/entry/cards/）同步为运行时库那 194 张卡。

背景：录入库的定位是「编辑区」，运行时库是「发布结果」，POST /api/entry/publish
把前者整体覆盖到后者。全量卡已直接录入运行时库，录入库却还留着 14 张旧 schema
种子卡——既让录入工具整体报错（缺 key/source/raw），又埋着「点发布就冲掉 194 张」
的隐患，进度统计也失真。同步后两库一致，发布即空操作。

用法：python tools/sync_entry_library.py [--dry-run]
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "server" / "data" / "cards"
ENTRY = ROOT / "server" / "data" / "entry" / "cards"
FILES = ["small_deal.json", "big_deal.json", "market.json", "doodad.json", "professions.json"]

dry = "--dry-run" in sys.argv


def main() -> int:
    if not ENTRY.is_dir():
        print(f"录入库目录不存在：{ENTRY}")
        return 1

    print(f"{'预演' if dry else '执行'}：运行时库 → 录入库\n")
    total_old = total_new = 0
    for f in FILES:
        src, dst = RUNTIME / f, ENTRY / f
        new = json.loads(src.read_text(encoding="utf-8"))
        old = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else []
        total_old += len(old)
        total_new += len(new)
        print(f"  {f:20} {len(old):3} 张（旧 schema）→ {len(new):3} 张")
        if not dry:
            shutil.copyfile(src, dst)

    print(f"\n合计 {total_old} → {total_new} 张")
    if dry:
        print("（预演，未写入。去掉 --dry-run 执行）")
        return 0

    # 校验两库完全一致——一致才说明「发布」是安全的空操作
    diff = [f for f in FILES
            if json.loads((RUNTIME / f).read_text(encoding="utf-8"))
            != json.loads((ENTRY / f).read_text(encoding="utf-8"))]
    if diff:
        print(f"✗ 同步后仍有差异：{diff}")
        return 1
    print("✓ 两库内容完全一致，发布将是空操作")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
