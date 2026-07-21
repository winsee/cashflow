# -*- coding: utf-8 -*-
"""按用户 2026-07-21 的裁定修正资产类型与 mk-029 机制。

1. sd-017「10亩荒地」与 mk-026「10英亩土地（带河流）」判定为同一标的，统一类型；
2. sd-018/sd-049 加 businessKind，mk-025/mk-033 改为按 businessKind 匹配；
3. 2室/4室/8室公寓统一 assetType 为「公寓」（房间数在 rooms 里），
   否则与 mk-020 等 10 张「求购公寓·每间房」的标的字符串对不上；
4. mk-029 分期收款：200 个月（100,000÷500），到期现金流恢复并入账，无需房主裁定。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"

LAND = "10英亩土地（带河流）"
BIZ_KIND = {"sd-018": "小型机械公司", "sd-049": "软件公司"}
APT_ROOMS = {"2室公寓", "4室公寓", "8室公寓"}

changes: list[str] = []


def load(n):
    return json.loads((CARDS / n).read_text(encoding="utf-8"))


def save(n, d):
    (CARDS / n).write_text(
        json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ---- 小生意 ----
sd = load("small_deal.json")
for c in sd:
    d = c["data"]
    if c["id"] == "sd-017":
        d["assetType"] = LAND
        changes.append(f"sd-017 assetType → {LAND}（与 mk-026 同一标的）")
    if c["id"] in BIZ_KIND:
        d["businessKind"] = BIZ_KIND[c["id"]]
        changes.append(f"{c['id']} + businessKind={BIZ_KIND[c['id']]}")
save("small_deal.json", sd)

# ---- 大买卖 ----
bd = load("big_deal.json")
for c in bd:
    d = c["data"]
    if d.get("assetType") in APT_ROOMS:
        old = d["assetType"]
        d["assetType"] = "公寓"
        changes.append(f"{c['id']} assetType {old} → 公寓（rooms={d.get('rooms')}）")
save("big_deal.json", bd)

# ---- 市场风云 ----
mk = load("market.json")
for c in mk:
    d = c["data"]
    if c["id"] == "mk-026":
        d["targetAssetType"] = LAND
        changes.append(f"mk-026 targetAssetType → {LAND}")
    if c["id"] == "mk-025":
        d["targetAssetType"] = "自建企业"
        d["targetBusinessKind"] = "小型机械公司"
        changes.append("mk-025 → 自建企业/小型机械公司（匹配 sd-018）")
    if c["id"] == "mk-033":
        d["targetAssetType"] = "自建企业"
        d["targetBusinessKind"] = "软件公司"
        changes.append("mk-033 → 自建企业/软件公司（匹配 sd-049）")
    if c["id"] == "mk-029":
        d.pop("needsHostAdjudication", None)
        d.pop("termYears", None)
        d["durationMonths"] = d["totalPrice"] // abs(d["monthlyCashflowDelta"])
        d["onCompletion"] = "RESTORE_CASHFLOW_AND_PAY"
        c["effects"] = [{"op": "MARKET_SELL_OFFER"}, {"op": "SCHEDULE_INSTALLMENT"}]
        c["raw"]["notes"] = [
            "卡面「四年内」为剧情文案；按数值结算为 $100,000 ÷ $500 = 200 个月，"
            "期满月现金流恢复 +$500 并一次性入账 $100,000（房主 2026-07-21 裁定）"
        ]
        changes.append(f"mk-029 → 分期 {d['durationMonths']} 个月，自动结算")
save("market.json", mk)

print(f"共 {len(changes)} 处修改：")
for c in changes:
    print(f"  · {c}")
