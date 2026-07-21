# -*- coding: utf-8 -*-
"""交叉核对：每种可买入资产，市场风云里有没有对应的求购卡（能否变现）。"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"


def load(n):
    return json.loads((CARDS / n).read_text(encoding="utf-8"))


buyable = defaultdict(list)  # assetType -> [(id, title, businessKind)]
kinds = defaultdict(set)  # assetType -> {businessKind}
for f in ("small_deal.json", "big_deal.json"):
    for c in load(f):
        if c["subtype"] in ("REALESTATE", "BUSINESS", "COLLECTIBLE"):
            d = c["data"]
            at = d.get("assetType", "?")
            bk = d.get("businessKind", "")
            buyable[at].append((c["id"], c["title"], bk))
            if bk:
                kinds[at].add(bk)

demanded = defaultdict(list)  # assetType -> [(id, title)]
for c in load("market.json"):
    d = c["data"]
    t = d.get("targetAssetType")
    if t:
        demanded[t].append((c["id"], c["title"]))
    elif d.get("targetBusinessKind"):
        # 只按企业类型求购：命中所有带该 businessKind 的 assetType
        for at, ks in kinds.items():
            if d["targetBusinessKind"] in ks:
                demanded[at].append((c["id"], f"{c['title']}〔按企业类型〕"))

print("=" * 78)
print("可买入资产类型 → 市场风云求购卡")
print("=" * 78)
for at in sorted(buyable):
    ids = " ".join(i for i, _, _ in buyable[at])
    hits = demanded.get(at, [])
    flag = "✅" if hits else "❌ 无任何求购卡"
    print(f"\n{flag}  【{at}】 买入卡 {len(buyable[at])} 张: {ids}")
    if hits:
        for i, t in hits:
            print(f"      ← {i} {t}")
    else:
        for i, t, bk in buyable[at]:
            print(f"      · {i} {t}" + (f"  〔businessKind={bk}〕" if bk else ""))

print("\n" + "=" * 78)
print("求购卡标的 → 有无对应买入卡（反向：求购了但买不到的）")
print("=" * 78)
orphan = False
for at in sorted(demanded):
    if at not in buyable:
        ids = " ".join(i for i, _ in demanded[at])
        print(f"❌ 【{at}】 求购卡 {len(demanded[at])} 张: {ids} —— 没有对应买入卡")
        orphan = True
if not orphan:
    print("（无：每张求购卡都能找到对应的买入卡）")
