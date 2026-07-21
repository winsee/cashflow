# -*- coding: utf-8 -*-
"""把代码/测试里引用的旧种子卡 id，按数值匹配到 v3 全量库的新 id。

旧种子库（server/data/entry/cards/）是 14 张手工样例，用的是语义 id（如 sd-house-3b2b-01）；
v3 全量库改用 <叠前缀>-<实体牌序号> 编号，旧 id 全部不存在。
本脚本按 subtype + data 数值做匹配，输出替换对照表。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
ENTRY = ROOT / "server" / "data" / "entry" / "cards"
FILES = ["small_deal.json", "big_deal.json", "market.json", "doodad.json", "professions.json"]

# 旧库的 data 用的是 v2 字段名，比对前先归一
RENAMED = {"pricePerUnit": "price", "condition": "payerCondition"}
DROPPED = {"loanAllowed", "costUnchanged", "tradingLocked", "unitCost", "noBuyer",
           "roiPct", "incomeCategory", "priceBasis", "buyerScope", "rooms", "units",
           "priceRange", "assetType", "priceIndeterminate"}


def norm(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        k = RENAMED.get(k, k)
        if k in DROPPED:
            continue
        out[k] = v
    return out


def main() -> int:
    new = []
    for f in FILES:
        new += json.loads((CARDS / f).read_text(encoding="utf-8"))

    old = []
    for f in FILES:
        p = ENTRY / f
        if p.exists():
            old += json.loads(p.read_text(encoding="utf-8"))

    # 收集代码/测试里真正被引用的旧 id
    referenced: set[str] = set()
    for pat in ("server/app/engine/tests/*.py", "server/tests/*.py"):
        for p in ROOT.glob(pat):
            txt = p.read_text(encoding="utf-8")
            for m in re.finditer(r'"((?:sd|bd|mk|dd|prof)-[a-z0-9][a-z0-9-]*)"', txt):
                referenced.add(m.group(1))
    # 排除已经是新格式的（三位数字）
    referenced = {r for r in referenced if not re.fullmatch(r"(sd|bd|mk|dd|prof)-\d{3}", r)}

    print("=" * 74)
    print("旧种子卡 id → v3 全量库 id")
    print("=" * 74)
    unmatched = []
    for oid in sorted(referenced):
        src = next((c for c in old if c["id"] == oid), None)
        if src is None:
            unmatched.append((oid, "旧种子库里也找不到"))
            continue
        want = norm(src["data"])
        hits = [c for c in new
                if c["subtype"] == src["subtype"] and
                all(norm(c["data"]).get(k) == v for k, v in want.items())]
        if not hits:
            # 放宽：职业卡按标题匹配
            hits = [c for c in new if c["title"] == src["title"]]
        if hits:
            # 数值相同但卡名不同 = 巧合，不是同一张卡；优先按卡面标题收敛
            exact = [h for h in hits if h["raw"]["title"] == src["title"]]
            if exact:
                hits = exact
            note = ""
            if len(hits) > 1:
                keys = {h["key"] for h in hits}
                note = "（真·重复卡，任选一张）" if len(keys) == 1 else "（⚠ 数值巧合，需人工确认）"
            ids = " / ".join(h["id"] for h in hits)
            print(f"  {oid:22} → {ids:16} {hits[0]['title']} {note}")
        else:
            unmatched.append((oid, f"{src['subtype']} {src['title']}"))

    if unmatched:
        print("\n未能自动匹配（需人工指定）：")
        for oid, why in unmatched:
            print(f"  {oid:22} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
