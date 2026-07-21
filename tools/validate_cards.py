# -*- coding: utf-8 -*-
"""卡库校验：结构完整性 + 业务恒等式 + 与实体张数对账。

用法：python tools/validate_cards.py
退出码 0 = 全部通过。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
SCHEMA = ROOT / "server" / "data" / "schema" / "card.schema.json"
IMAGES = ROOT / "docs" / "实体卡片"

# 实体清点结果（开局前对账用）
EXPECTED = {
    "small_deal.json": ("小生意", 56),
    "big_deal.json": ("大买卖", 42),
    "market.json": ("市场风云", 42),
    "doodad.json": ("额外支出", 42),
    "professions.json": ("职业卡", 12),
}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# v3 已删除的字段：任何一个重新出现都说明有人在回退设计
REMOVED_FIELDS = {
    "effects": "已由 subtype 查表推出（design/06 §4.0），不再逐卡存储",
    "loanAllowed": "说明书 p6 规定贷款是通用规则，非卡片属性",
    "costUnchanged": "并股/拆股的固有规则，非卡片属性",
    "tradingLocked": "同上",
    "unitCost": "可由 cost ÷ quantity 推出",
    "noBuyer": "「目前没有其他买主」是卡面剧情，已并入 priceIndeterminate",
    "condition": "已按判定对象拆为 payerCondition / assetCondition",
}


def check_removed(c: dict, fname: str) -> None:
    for f, why in REMOVED_FIELDS.items():
        if f in c or f in c.get("data", {}):
            err(f"{fname} {c.get('id')}: 字段「{f}」已在 v3 删除——{why}")


def check_common(c: dict, fname: str) -> None:
    cid = c.get("id", "<无id>")
    for f in ("id", "key", "deck", "subtype", "title", "source", "raw", "data"):
        if f not in c:
            err(f"{fname} {cid}: 缺字段 {f}")
    src = c.get("source", {})
    img = ROOT / src.get("image", "")
    if not img.is_file():
        err(f"{fname} {cid}: 原图不存在 {src.get('image')}")
    raw = c.get("raw", {})
    if not raw.get("title"):
        err(f"{fname} {cid}: raw.title 为空——原文未保留")
    if not raw.get("body") and not raw.get("groups"):
        err(f"{fname} {cid}: raw 正文为空——原文未保留")


def check_asset(c: dict, fname: str) -> None:
    """成本 = 首期支付 + 抵押/负债。"""
    d = c["data"]
    if "cost" not in d:
        return
    if d["cost"] != d.get("downPayment", 0) + d.get("mortgage", 0):
        err(
            f"{fname} {c['id']}『{c['title']}』: 成本恒等式不成立 "
            f"{d['cost']} ≠ {d.get('downPayment')} + {d.get('mortgage')}"
        )


def check_profession(c: dict, fname: str) -> None:
    d = c["data"]
    s = (
        d["taxes"] + d["mortgagePayment"] + d["schoolLoanPayment"] + d["carLoanPayment"]
        + d["creditCardPayment"] + d["extraExpenses"] + d["otherExpenses"]
    )
    if s != d["totalExpenses"]:
        err(f"{fname} {c['id']}『{c['title']}』: 各项支出合计 {s} ≠ 总支出 {d['totalExpenses']}")
    if d["salary"] - d["totalExpenses"] != d["monthlyCashflow"]:
        err(f"{fname} {c['id']}『{c['title']}』: 总收入-总支出 ≠ 月现金流")


def check_stock(c: dict, fname: str) -> None:
    d = c["data"]
    lo, hi = d.get("priceRange", [None, None])
    if lo is None:
        return
    if not (lo <= d["price"] <= hi):
        # 实体卡本身就有超出区间的（股灾/暴涨），只提示不报错
        warn(f"{fname} {c['id']}『{c['title']}』: 今日价 {d['price']} 不在区间 [{lo}, {hi}] 内（卡面如此）")


# 全套市场卡确实不求购的资产类型（属牌组构成，非规则限制）
# 注意：卡面「目前没有其他买主」只是剧情，不代表不可转售，不作为本集合的依据
NO_BUYER_OK = {"自动化企业", "特许专卖店"}

# 待房主裁定的悬空标的：降级为提示，定案后从此处移除
PENDING_DECISION: dict[str, str] = {}


def check_liquidity() -> None:
    """求购卡标的必须能在买入卡里找到，反之亦然——字符串对不上就永远卖不掉。"""
    buyable: dict[str, set[str]] = {}
    assets: dict[str, list[dict]] = {}  # assetType -> 买入卡
    for f in ("small_deal.json", "big_deal.json"):
        for c in json.loads((CARDS / f).read_text(encoding="utf-8")):
            if c["subtype"] in ("REALESTATE", "BUSINESS", "COLLECTIBLE"):
                d = c["data"]
                at = d.get("assetType", "?")
                buyable.setdefault(at, set())
                assets.setdefault(at, []).append(c)
                if d.get("businessKind"):
                    buyable[at].add(d["businessKind"])

    kind_owner: dict[str, list[dict]] = {}  # businessKind -> 买入卡（跨 assetType）
    for at, cs in assets.items():
        for c in cs:
            if c["data"].get("businessKind"):
                kind_owner.setdefault(c["data"]["businessKind"], []).append(c)

    # 全库扫描：任何文件里的 targetAssetType / targetRooms 都必须指向真实存在的资产
    # （曾只扫 market.json，导致 big_deal.json 的 bd-003 改名后永久失效未被发现）
    for f in ("small_deal.json", "big_deal.json", "market.json", "doodad.json"):
        for c in json.loads((CARDS / f).read_text(encoding="utf-8")):
            t = c["data"].get("targetAssetType")
            if t and t not in buyable and t not in PENDING_DECISION:
                err(f"{f} {c['id']}『{c['title']}』: targetAssetType「{t}」无对应资产类型，此卡永不生效")
            r = c["data"].get("targetRooms")
            if r is not None and not [a for a in assets.get(t, []) if a["data"].get("rooms") == r]:
                err(f"{f} {c['id']}『{c['title']}』: 无 rooms={r} 的「{t}」资产，此卡永不生效")

    for c in json.loads((CARDS / "market.json").read_text(encoding="utf-8")):
        t = c["data"].get("targetAssetType")
        bk = c["data"].get("targetBusinessKind")

        # 只给 businessKind 的求购卡：跨 assetType 匹配
        if not t:
            if bk and bk not in kind_owner:
                err(f"market.json {c['id']}『{c['title']}』: 企业类型「{bk}」没有任何买入卡")
            targets = kind_owner.get(bk, [])
        else:
            if t not in buyable:
                if t in PENDING_DECISION:
                    warn(f"【待裁定】{c['id']}『{c['title']}』: {PENDING_DECISION[t]}")
                else:
                    err(f"market.json {c['id']}『{c['title']}』: 标的「{t}」没有任何买入卡，永远无法成交")
                continue
            if bk and bk not in buyable[t]:
                err(f"market.json {c['id']}『{c['title']}』: 「{t}」名下无 businessKind=「{bk}」的买入卡")
            targets = assets.get(t, [])

        # 定价求购的报价，应落在标的卡面标注的售价区间内（卡面自洽性交叉验证）
        price = c["data"].get("price")
        if price is None or c["data"].get("priceBasis") != "PER_UNIT":
            continue
        for a in targets:
            ad = a["data"]
            if ad.get("priceBasis") == "CASHFLOW_MULTIPLE":
                lo_m, hi_m = ad["priceMultipleRange"]
                lo, hi = ad["cashflow"] * lo_m, ad["cashflow"] * hi_m
                if not (lo <= price <= hi):
                    warn(
                        f"{c['id']}『{c['title']}』报价 {price} 不在 {a['id']} 卡面售价区间 "
                        f"[{lo:.0f}, {hi:.0f}]（月现金流 {ad['cashflow']} × {lo_m}~{hi_m} 倍）内"
                    )

    # 反向：每种买入资产都该有求购卡。targetAssetType 直接命中，
    # 或 targetBusinessKind 命中该 assetType 名下任一 businessKind，均算已连通。
    demanded: set[str] = set()
    for c in json.loads((CARDS / "market.json").read_text(encoding="utf-8")):
        d = c["data"]
        if d.get("targetAssetType"):
            demanded.add(d["targetAssetType"])
        if d.get("targetBusinessKind"):
            demanded |= {at for at, ks in buyable.items() if d["targetBusinessKind"] in ks}

    for at in sorted(buyable):
        if at not in demanded and at not in NO_BUYER_OK:
            warn(f"资产「{at}」没有任何市场求购卡，买入后无法变现——确认是否规则原意")


def main() -> int:
    all_ids: dict[str, str] = {}
    all_keys: dict[str, list[str]] = {}
    total = 0

    validator = None
    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(
            json.loads(SCHEMA.read_text(encoding="utf-8"))["items"]
        )
    except ImportError:
        warn("未安装 jsonschema，跳过 schema 校验（pip install jsonschema）")

    for fname, (deck_dir, expected_n) in EXPECTED.items():
        p = CARDS / fname
        if not p.is_file():
            err(f"缺文件 {fname}")
            continue
        cards = json.loads(p.read_text(encoding="utf-8"))
        total += len(cards)

        if validator is not None:
            for c in cards:
                for e in validator.iter_errors(c):
                    loc = "/".join(str(x) for x in e.absolute_path) or "<根>"
                    err(f"{fname} {c.get('id')}: schema 违规 @{loc}: {e.message}")

        if len(cards) != expected_n:
            err(f"{fname}: 录入 {len(cards)} 张，实体清点 {expected_n} 张")

        n_photos = len(list((IMAGES / deck_dir).glob("*.jpg")))
        if len(cards) != n_photos:
            err(f"{fname}: 录入 {len(cards)} 张，照片 {n_photos} 张")

        seen_sheets = set()
        for c in cards:
            check_common(c, fname)
            check_removed(c, fname)
            cid = c.get("id")
            if cid in all_ids:
                err(f"id 重复: {cid}（{fname} 与 {all_ids[cid]}）")
            all_ids[cid] = fname
            all_keys.setdefault(c.get("key", ""), []).append(cid)

            sheet = c.get("source", {}).get("sheetNo")
            if sheet in seen_sheets:
                err(f"{fname}: sheetNo {sheet} 重复")
            seen_sheets.add(sheet)

            st = c.get("subtype")
            if st in ("REALESTATE", "BUSINESS", "COLLECTIBLE", "DICE_GAMBLE"):
                check_asset(c, fname)
            elif st == "PROFESSION":
                check_profession(c, fname)
            elif st == "STOCK_OFFER":
                check_stock(c, fname)

        missing = set(range(1, expected_n + 1)) - seen_sheets
        if missing:
            err(f"{fname}: 缺 sheetNo {sorted(missing)}")

    # duplicateOf 指向必须存在
    for fname in EXPECTED:
        p = CARDS / fname
        if not p.is_file():
            continue
        for c in json.loads(p.read_text(encoding="utf-8")):
            dup = c.get("duplicateOf")
            if dup and dup not in all_ids:
                err(f"{fname} {c['id']}: duplicateOf 指向不存在的 {dup}")

    check_liquidity()

    print(f"共 {total} 张卡")
    dup_keys = {k: v for k, v in all_keys.items() if len(v) > 1}
    if dup_keys:
        print(f"同内容重复卡组 {len(dup_keys)} 组：")
        for k, v in sorted(dup_keys.items()):
            print(f"  {k}: {' '.join(v)}")

    for w in warnings:
        print(f"[提示] {w}")
    for e in errors:
        print(f"[错误] {e}", file=sys.stderr)

    if errors:
        print(f"\n校验失败：{len(errors)} 个错误", file=sys.stderr)
        return 1
    print(f"\n校验通过（{len(warnings)} 条提示）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
