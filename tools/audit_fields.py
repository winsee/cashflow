# -*- coding: utf-8 -*-
"""字段使用审计：统计每个 subtype 下各字段的出现率与取值分布，暴露设计问题。"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
FILES = ["small_deal.json", "big_deal.json", "market.json", "doodad.json", "professions.json"]

all_cards = []
for f in FILES:
    all_cards += json.loads((CARDS / f).read_text(encoding="utf-8"))

# ---- 1. 顶层字段出现率 ----
top = Counter()
for c in all_cards:
    top.update(c.keys())
print("=" * 70)
print(f"顶层字段（共 {len(all_cards)} 张）")
print("=" * 70)
for k, n in top.most_common():
    print(f"  {k:16} {n:4}/{len(all_cards)}  {'必填' if n == len(all_cards) else '可选'}")

# ---- 2. 各 subtype 的 data 字段矩阵 ----
by_sub = defaultdict(list)
for c in all_cards:
    by_sub[c["subtype"]].append(c)

print("\n" + "=" * 70)
print("各 subtype 的 data 字段出现率")
print("=" * 70)
for sub in sorted(by_sub, key=lambda s: -len(by_sub[s])):
    cs = by_sub[sub]
    fc = Counter()
    for c in cs:
        fc.update(c["data"].keys())
    print(f"\n【{sub}】 {len(cs)} 张")
    for k, n in fc.most_common():
        mark = "" if n == len(cs) else f"  ← 仅 {n} 张"
        print(f"    {k:22} {n:3}/{len(cs)}{mark}")

# ---- 3. 枚举型字段的取值分布 ----
print("\n" + "=" * 70)
print("枚举型字段取值分布")
print("=" * 70)
enums = ["priceBasis", "buyerScope", "incomeCategory", "appliesTo", "condition",
         "assetType", "businessKind", "targetAssetType", "targetBusinessKind", "kind"]
for e in enums:
    vals = Counter()
    for c in all_cards:
        v = c["data"].get(e)
        if v is not None:
            vals[str(v)] += 1
    if vals:
        print(f"\n{e}:")
        for v, n in vals.most_common():
            print(f"    {v:28} × {n}")

# ---- 4. raw 子字段使用率 ----
print("\n" + "=" * 70)
print("raw 子字段使用率（空数组/空串算未使用）")
print("=" * 70)
rc = Counter()
for c in all_cards:
    for k, v in c["raw"].items():
        if v:
            rc[k] += 1
for k, n in rc.most_common():
    print(f"  raw.{k:12} {n:4}/{len(all_cards)}")

# ---- 5. 布尔标志字段：是否只存在 true（可疑设计） ----
print("\n" + "=" * 70)
print("布尔/常量标志字段（只在 true 时出现 = 三态陷阱）")
print("=" * 70)
flags = ["chargeOnce", "loanAllowed", "costUnchanged", "tradingLocked",
         "priceIndeterminate"]
for f in flags:
    vals = Counter()
    for c in all_cards:
        if f in c["data"]:
            vals[str(c["data"][f])] += 1
    if vals:
        n_absent = len(all_cards) - sum(vals.values())
        print(f"  {f:20} {dict(vals)}  缺失 {n_absent} 张")
