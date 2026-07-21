# -*- coding: utf-8 -*-
"""卡库 v2 → v3 字段精简与规整。

目标：合理、不冗余、可扩展、符合说明书规则。每项改动都对应一条依据：

删冗余（信息可由别处推出，留着只会不一致）
  1. effects        —— 194 张全部与 subtype 一一对应，无一张覆写过 → 删，引擎按 subtype 查表
  2. costUnchanged  —— STOCK_EVENT 4/4 恒 true，是规则不是卡属性 → 删
     tradingLocked  —— 同上
  3. loanAllowed    —— 说明书 p6「您可以向银行贷款，除非您被宣布破产」，贷款是通用规则，
                       卡面那句只是提醒；且 App 无法约束"专款专用" → 删
  4. unitCost       —— COLLECTIBLE 可由 cost ÷ quantity 推出 → 删

消歧义（一名多义是最容易埋 bug 的形态）
  5. priceBasis(资产侧) → resaleBasis  —— 与求购侧的 priceBasis（怎么算价）角色不同
  6. condition → payerCondition / assetCondition —— 前者判定玩家，后者判定资产
  7. appliesTo: ALL_OWNERS → ALL      —— 与 buyerScope 的值域统一

补完整
  8. roiPct 统一必填：股票卡卡面印「投资收益率＝0%」的补 0
  9. LOSS_EVENT 并入 EXPENSE_EVENT   —— 字段形状相同，schema 本就同分支处理
 10. incomeCategory 值域按说明书 p7 记录卡收入栏扩为四类，并补全所有产生现金流的资产
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
FILES = ["small_deal.json", "big_deal.json", "market.json", "doodad.json", "professions.json"]

# 判定玩家资格 vs 判定资产状态
PAYER_CONDITIONS = {"hasChildren", "hasRentalProperty", "hasRealEstate"}

# 说明书 p7 记录卡收入栏：工资 / 利息 / 股利 / 房地产 / 企业投资
INCOME_BY_SUBTYPE = {
    "REALESTATE": "REAL_ESTATE",
    "BUSINESS": "BUSINESS",
    "DICE_GAMBLE": "BUSINESS",
}

stats = {k: 0 for k in (
    "effects", "costUnchanged", "tradingLocked", "loanAllowed", "unitCost",
    "resaleBasis", "payerCondition", "assetCondition", "appliesTo",
    "roiPct", "subtype", "incomeCategory",
)}

for fname in FILES:
    p = CARDS / fname
    cards = json.loads(p.read_text(encoding="utf-8"))
    for c in cards:
        d = c["data"]

        # 1. effects 全冗余
        if c.pop("effects", None) is not None:
            stats["effects"] += 1

        # 2. STOCK_EVENT 的两个恒真标志
        for f in ("costUnchanged", "tradingLocked"):
            if d.pop(f, None) is not None:
                stats[f] += 1

        # 3. 贷款是通用规则
        if d.pop("loanAllowed", None) is not None:
            stats["loanAllowed"] += 1

        # 4. unitCost 可推导
        if d.pop("unitCost", None) is not None:
            stats["unitCost"] += 1

        # 5. 资产侧 priceBasis 改名，避免与求购侧同名不同义
        if c["subtype"] in ("REALESTATE", "BUSINESS", "COLLECTIBLE") and "priceBasis" in d:
            d["resaleBasis"] = d.pop("priceBasis")
            stats["resaleBasis"] += 1

        # 6. condition 按判定对象拆分
        if "condition" in d:
            v = d.pop("condition")
            key = "payerCondition" if v in PAYER_CONDITIONS else "assetCondition"
            d[key] = v
            stats[key] += 1

        # 7. 值域统一
        if d.get("appliesTo") == "ALL_OWNERS":
            d["appliesTo"] = "ALL"
            stats["appliesTo"] += 1

        # 8. 股票卡 roiPct 补 0（卡面印「投资收益率＝0%」）
        if c["subtype"] == "STOCK_OFFER" and "roiPct" not in d:
            d["roiPct"] = 0
            stats["roiPct"] += 1

        # 9. LOSS_EVENT 并入 EXPENSE_EVENT
        if c["subtype"] == "LOSS_EVENT":
            c["subtype"] = "EXPENSE_EVENT"
            stats["subtype"] += 1

        # 10. 现金流资产补 incomeCategory（记录卡收入栏归属）
        sec = INCOME_BY_SUBTYPE.get(c["subtype"])
        if sec and d.get("cashflow"):
            if d.get("incomeCategory") != sec:
                d["incomeCategory"] = sec
                stats["incomeCategory"] += 1

    p.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("v2 → v3 迁移完成：")
for k, v in stats.items():
    if v:
        print(f"  {k:16} {v:3} 处")
