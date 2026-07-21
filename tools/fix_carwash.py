# -*- coding: utf-8 -*-
"""房主 2026-07-21 第二次裁定：mk-035 的买家关系。

全库仅 3 张洗车相关卡（mk-035 / bd-023 / bd-037），无转录遗漏。
- mk-035「求购汽车清洗公司 $25,000」→ 匹配 bd-037「洗车店」。
  佐证：bd-037 卡面「售价可能为年月现金流量的12~25倍」，月现金流 $1,500
  → 区间 $18,000~$37,500，报价 $25,000 正落其中。
- bd-023「4家投币式洗车店」卡面写明「目前没有其他买主」，不参与本次求购；
  其 $125,000 是 4 家作为一个整体的成本，不拆分为 4 个资产单位。
- 出售始终是可选的：报价低于账面时玩家可以不卖，这不构成匹配矛盾。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"


def load(n):
    return json.loads((CARDS / n).read_text(encoding="utf-8"))


def save(n, d):
    (CARDS / n).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


changes = []

bd = load("big_deal.json")
for c in bd:
    if c["id"] == "bd-037":
        c["data"]["businessKind"] = "汽车清洗公司"
        changes.append("bd-037 + businessKind=汽车清洗公司（供 mk-035 匹配）")
    if c["id"] == "bd-023":
        c["raw"]["notes"] = [
            "$125,000 为 4 家洗车店作为一个整体的成本，不拆分为 4 个资产单位；"
            "卡面写明「目前没有其他买主」，不参与 mk-035 求购"
        ]
        changes.append("bd-023 + 整体性与无买家的说明")
save("big_deal.json", bd)

mk = load("market.json")
for c in mk:
    if c["id"] == "mk-035":
        c["data"]["targetAssetType"] = "洗车店"
        c["data"]["targetBusinessKind"] = "汽车清洗公司"
        c["raw"]["notes"] = [
            "标的即 bd-037「洗车店」：其卡面售价区间为月现金流 $1,500 的 12~25 倍"
            "（$18,000~$37,500），本卡报价 $25,000 落在区间内。出售可选，玩家可拒绝。"
        ]
        changes.append("mk-035 → 洗车店/汽车清洗公司（匹配 bd-037）")
save("market.json", mk)

print(f"共 {len(changes)} 处修改：")
for c in changes:
    print(f"  · {c}")
