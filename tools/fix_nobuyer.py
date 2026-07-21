# -*- coding: utf-8 -*-
"""房主 2026-07-21 第三次裁定：撤销 noBuyer 这个伪机制。

「目前没有其他买主」是卡面剧情文案（解释这笔生意没人跟你抢），
不是"该资产不可转售"的规则。它出现的位置正是其他卡印「售价在$A~$B之间」的那一行，
因此唯一的机制含义是：**卡面未给出转售参考价**，等价于已有的 priceIndeterminate。

连带修正：上一轮曾据此把 bd-023 排除在 mk-035 之外，该理由不成立，现予恢复匹配。
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
    d = c["data"]
    if d.pop("noBuyer", None):
        d["priceIndeterminate"] = True
        changes.append(f"{c['id']} noBuyer → priceIndeterminate（卡面未给转售参考价）")
    if c["id"] == "bd-023":
        d["businessKind"] = "汽车清洗公司"
        c["raw"]["notes"] = [
            "$125,000 为 4 家洗车店作为一个整体的成本，不拆分为 4 个资产单位；"
            "「目前没有其他买主」是卡面剧情（没人跟你抢这笔生意），不影响日后转售"
        ]
        changes.append("bd-023 + businessKind=汽车清洗公司（可被 mk-035 收购）")
save("big_deal.json", bd)

# mk-035 改为按 businessKind 匹配：bd-023(自动化企业) 与 bd-037(洗车店) 分属不同 assetType
mk = load("market.json")
for c in mk:
    if c["id"] == "mk-035":
        c["data"].pop("targetAssetType", None)
        c["data"]["targetBusinessKind"] = "汽车清洗公司"
        c["raw"]["notes"] = [
            "标的为一切「汽车清洗公司」：bd-037 洗车店、bd-023 4家投币式洗车店。"
            "出售可选——报价低于账面时玩家可拒绝，报价不划算不构成匹配矛盾。"
        ]
        changes.append("mk-035 改按 businessKind 匹配（跨 assetType：洗车店 + 自动化企业）")
save("market.json", mk)

print(f"共 {len(changes)} 处修改：")
for c in changes:
    print(f"  · {c}")
