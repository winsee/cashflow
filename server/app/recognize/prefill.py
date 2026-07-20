"""录入 OCR 预填解析（design/04 §6）：带坐标的 OCR 碎块 → 物理行 → 表单字段。

卡面是"左标签右数值"两栏布局，PaddleOCR 按检测框逐块输出，标签与数值天然
分离；merge_rows 按 y 中心把碎块聚回物理行，parse_fields 再用各 subtype 的
标签别名表抽出「字段键→数值」。字段键与前端 entry-fields.ts 的 FIELDS 一致，
前端拿到直接填表。纯函数、不依赖 paddle；别名没覆盖到的内容前端仍有点选
芯片兜底，因此宁可漏解析、不做激进猜测（标题除外，标题明确标注是猜测）。
"""
from __future__ import annotations

import re
import unicodedata

Box = tuple[float, float, float, float]  # x0, y0, x1, y1

_NUM_RE = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)")
_SYMBOL_RE = re.compile(r"\b(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,8}\b")
_RATIO_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
_HAN_RE = re.compile(r"[一-鿿]")
# 收益率：卡面写法是"42%的投资收益率"，数字在标签前，只认「数字%」模式
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# 价格区间：卡面写法是"可以卖$45,000~$65,000"，认「$X~$Y」区间模式（可跨行）
_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[~〜\-–—]+\s*\$?\s*(\d[\d,]*)")
# 资产类型：与卡库取值约定一致（3室2厅 / 4室公寓）
_ASSET_RE = re.compile(r"\d+\s*室\s*\d+\s*厅|\d+\s*[室套]\s*公寓")


def merge_rows(items: list[tuple[str, Box]]) -> list[str]:
    """按 y 中心把 OCR 碎块聚成物理行，行内按 x 排序空格拼接。"""
    if not items:
        return []
    heights = sorted(b[3] - b[1] for _, b in items)
    med_h = heights[len(heights) // 2] or 1.0
    rows: list[list[tuple[str, Box]]] = []
    for text, box in sorted(items, key=lambda it: (it[1][1] + it[1][3]) / 2):
        cy = (box[1] + box[3]) / 2
        if rows:
            last = rows[-1]
            last_cy = sum((b[1] + b[3]) / 2 for _, b in last) / len(last)
            if abs(cy - last_cy) < 0.6 * med_h:
                last.append((text, box))
                continue
        rows.append([(text, box)])
    out = []
    for row in rows:
        row.sort(key=lambda it: it[1][0])
        out.append(" ".join(t for t, _ in row))
    return out


# ---------------- 别名表 ----------------
# 每 subtype：[(标签别名列表, 候选字段键列表)]。候选键按「支出/普通键在前、
# liabilities.* 在后」排列，_pick_key 依区段（收入/支出/资产/负债）选择归属。

_ALIASES: dict[str, list[tuple[list[str], list[str]]]] = {
    "PROFESSION": [
        (["工资"], ["salary"]),
        (["税金", "税收"], ["taxes"]),
        (["住房抵押", "住房贷款", "房租"], ["mortgagePayment", "liabilities.mortgage"]),
        (["教育贷款", "助学贷款"], ["schoolLoanPayment", "liabilities.schoolLoan"]),
        (["购车贷款", "汽车贷款"], ["carLoanPayment", "liabilities.carLoan"]),
        (["信用卡"], ["creditCardPayment", "liabilities.creditCard"]),
        (["其他支出"], ["otherExpenses"]),
        # "外负债"：实拍中"额外负债"的"额"常被 OCR 吞掉
        (["额外支出", "额外负债", "外负债", "零售债务"], ["extraExpenses", "liabilities.extra"]),
        (["每个孩子", "每孩", "孩子支出"], ["perChildExpense"]),
        (["储蓄", "存款"], ["savings"]),
    ],
    "REALESTATE": [
        (["成本"], ["cost"]),
        (["首期支付", "首付"], ["downPayment"]),
        (["抵押贷款", "贷款"], ["mortgage"]),
        (["现金流"], ["cashflow"]),
        # roiPct/priceRange/assetType 不走标签取数，见 _subtype_extras 的模式匹配
        (["交易范围", "价格区间", "价格范围"], ["priceRange"]),
    ],
    "BUSINESS": [
        (["成本"], ["cost"]),
        (["首期支付", "首付"], ["downPayment"]),
        (["抵押贷款", "负债", "贷款"], ["mortgage"]),
        (["现金流"], ["cashflow"]),
    ],
    "STOCK_OFFER": [
        (["今日价格", "今日价", "价格"], ["price"]),
        (["每股红利", "每股股利", "分红", "股息", "股利", "红利"], ["dividendPerShare"]),
        (["交易范围", "价格区间", "价格范围"], ["priceRange"]),
    ],
    "STOCK_EVENT": [],
    "LOSS_EVENT": [
        (["金额", "损失", "支付"], ["amount"]),
    ],
    "EXPENSE_EVENT": [
        (["每套", "每所", "每栋", "每间", "每处"], ["amountPerUnit"]),
    ],
    "BUYER_OFFER": [
        (["每套价格", "每套", "每所", "每处", "价格"], ["pricePerUnit"]),
    ],
    "MULTIPLE_OFFER": [
        (["倍数", "倍"], ["multiple"]),
    ],
    "ECONOMY_EVENT": [],
    "CASH": [
        (["金额", "支付", "花费", "费用"], ["amount"]),
    ],
    "CREDIT_OPTION": [
        (["月供", "每月", "月支出"], ["creditMonthly"]),
        (["金额", "支付", "花费", "费用"], ["amount"]),
    ],
    "INSTALLMENT": [
        (["首付", "首期支付"], ["downPayment"]),
        (["月供", "每月", "月付"], ["monthly"]),
        (["负债", "贷款", "分期"], ["liability"]),
    ],
}

# 与前端 entry-fields.ts SUBTYPES 保持一致，用于同叠内 subtype 自动探测
DECK_SUBTYPES: dict[str, list[str]] = {
    "SMALL_DEAL": ["REALESTATE", "STOCK_OFFER", "STOCK_EVENT", "LOSS_EVENT"],
    "BIG_DEAL": ["REALESTATE", "BUSINESS", "EXPENSE_EVENT"],
    "MARKET": ["BUYER_OFFER", "MULTIPLE_OFFER", "ECONOMY_EVENT"],
    "DOODAD": ["CASH", "CREDIT_OPTION", "INSTALLMENT"],
    "PROFESSION": ["PROFESSION"],
}

_SECTIONS = {"收入": "income", "支出": "expense", "资产": "asset", "负债": "liability"}

# 职业卡模板废话：不做标题候选（"您的职业"单独处理）
_TITLE_SKIP = ("请将所有数据", "游戏卡", "目标", "非工资收入", "总收入", "总支出",
               "利息", "股利", "您的职业", "房地产/企业")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _first_number(seg: str) -> int | float | None:
    seg = _ASSET_RE.sub("", seg)  # "每套3室2厅房产…"里的 3/2 不是金额
    m = _NUM_RE.search(seg)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return int(v) if v.is_integer() else v


def _all_numbers(seg: str) -> list[int | float]:
    seg = _ASSET_RE.sub("", seg)
    out = []
    for m in _NUM_RE.finditer(seg):
        v = float(m.group(1).replace(",", ""))
        out.append(int(v) if v.is_integer() else v)
    return out


def _pick_key(keys: list[str], section: str | None, fields: dict) -> str | None:
    """按区段选择字段归属，已填的键不覆盖（首见为准）。

    实体职业卡底部"资产/负债"是左右两栏并排，区段头会并成一行（"资产 负债"）
    导致区段追踪失效；因此负债区外一律"普通键优先、已填则兜底负债键"——
    同名标签（住房抵押/教育贷款/购车贷款/信用卡）第一次归支出、第二次归负债。
    """
    liab = [k for k in keys if k.startswith("liabilities.")]
    plain = [k for k in keys if not k.startswith("liabilities.")]
    cands = liab if section == "liability" else plain + liab
    for k in cands:
        if k not in fields:
            return k
    return None


def _parse_one(rows: list[str], subtype: str) -> dict:
    table = _ALIASES.get(subtype, [])
    fields: dict[str, int | float | str] = {}
    section: str | None = None
    for row in rows:
        text = _norm(row)
        bare = re.sub(r"[\s:：]", "", text)
        if bare in _SECTIONS:
            section = _SECTIONS[bare]
            continue
        # 收集本行全部别名命中：按位置排序，重叠时长别名优先（抵押贷款 vs 贷款）
        hits: list[tuple[int, int, list[str]]] = []  # (pos, len, keys)
        for aliases, keys in table:
            first: tuple[int, int] | None = None
            for a in aliases:
                pos = text.find(a)
                # "非工资收入"里的"工资"不算命中
                while pos > 0 and text[pos - 1] == "非":
                    pos = text.find(a, pos + 1)
                if pos != -1 and (first is None or pos < first[0]):
                    first = (pos, len(a))
            if first is not None:
                hits.append((first[0], first[1], keys))
        hits.sort(key=lambda h: (h[0], -h[1]))
        kept: list[tuple[int, int, list[str]]] = []
        covered = -1
        for pos, alen, keys in hits:
            if pos < covered:
                continue
            kept.append((pos, alen, keys))
            covered = pos + alen
        for i, (pos, alen, keys) in enumerate(kept):
            seg_end = kept[i + 1][0] if i + 1 < len(kept) else len(text)
            seg = text[pos + alen:seg_end]
            if keys == ["priceRange"]:
                nums = _all_numbers(seg)
                if len(nums) < 2:
                    break
                fields.setdefault("priceRange.0", nums[0])
                fields.setdefault("priceRange.1", nums[1])
                continue
            v = _first_number(seg)
            if v is None:
                # 标签后无数值：斜拍/两栏错位时本行后续的标签→数值配对已不可信，
                # 宁可漏填也不错配（实拍验证：错值比漏值更难被人工核对发现）
                break
            key = _pick_key(keys, section, fields)
            if key is not None:
                fields[key] = v
    if subtype in ("REALESTATE", "BUSINESS"):
        # 收益率/价格区间/资产类型不是"左标签右数值"结构（数字在标签前、行内区间、
        # 或藏在标题里），按整卡文本模式匹配，别走别名取数（否则收益率会误抓卖价）
        joined = " ".join(_norm(r) for r in rows)
        m = _ASSET_RE.search(joined)
        if m:
            fields.setdefault("assetType", re.sub(r"\s+", "", m.group()))
        m = _PCT_RE.search(joined)
        if m:
            v = float(m.group(1))
            fields.setdefault("roiPct", int(v) if v.is_integer() else v)
        if "priceRange.0" not in fields:
            m = _RANGE_RE.search(joined)
            if m:
                lo = int(m.group(1).replace(",", ""))
                hi = int(m.group(2).replace(",", ""))
                if lo > hi:
                    lo, hi = hi, lo
                fields["priceRange.0"] = lo
                fields["priceRange.1"] = hi
    if subtype in ("STOCK_OFFER", "STOCK_EVENT"):
        for row in rows:
            m = _SYMBOL_RE.search(_norm(row))
            if m:
                fields.setdefault("symbol", m.group())
                break
    if subtype == "STOCK_EVENT":
        for row in rows:
            m = _RATIO_RE.search(_norm(row))
            if m:
                fields.setdefault("ratio", f"{m.group(1)}:{m.group(2)}")
                break
    return fields


def _guess_title(rows: list[str], subtype: str) -> str | None:
    if subtype == "PROFESSION":
        for i, row in enumerate(rows):
            t = _norm(row)
            if "您的职业" not in t:
                continue
            rest = t.split("您的职业", 1)[1].strip(" :：")
            if len(rest) >= 2:
                return rest
            if i + 1 < len(rows):
                nxt = _norm(rows[i + 1]).strip()
                if nxt and not re.search(r"\d", nxt) and len(nxt) <= 12:
                    return nxt
        return None
    table = _ALIASES.get(subtype, [])
    for row in rows:
        t = _norm(row).strip()
        if not t or any(s in t for s in _TITLE_SKIP):
            continue
        if re.sub(r"[\s:：]", "", t) in _SECTIONS:
            continue
        if any(a in t for aliases, _ in table for a in aliases):
            continue
        if len(_HAN_RE.findall(t)) < 2 or len(t) > 16:
            continue
        return t
    return None


def parse_fields(rows: list[str], deck: str, subtype: str) -> dict:
    """物理行 → {title, subtype, fields}。

    对 deck 内所有 subtype 各跑一遍别名表，命中最多者胜出（同叠拍到股票卡自动
    切 STOCK_OFFER）；平手时保持请求带来的 subtype。fields 的键与前端 FIELDS
    一致（嵌套键如 liabilities.mortgage / priceRange.0）。
    """
    cands = DECK_SUBTYPES.get(deck) or ([subtype] if subtype else [])
    if not cands:
        return {"title": None, "subtype": subtype, "fields": {}}
    results = {st: _parse_one(rows, st) for st in cands}
    best = max(len(f) for f in results.values())
    winners = [st for st, f in results.items() if len(f) == best]
    if subtype and (subtype in winners or best == 0):
        chosen = subtype
    else:
        chosen = winners[0]
    if chosen not in results:
        results[chosen] = _parse_one(rows, chosen)
    return {"title": _guess_title(rows, chosen), "subtype": chosen,
            "fields": results[chosen]}
