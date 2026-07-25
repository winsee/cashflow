"""封闭集匹配器（design/04 §4）：OCR 文本 → 卡库候选打分，纯函数、不依赖 paddle。

评分 = 0.6×标题相似度 + 0.3×显著数字命中 + 0.1×代码命中；
卡面没有某类关键词时该项权重按比例摊给其余项，避免无代码/无数字的卡吃亏。
置信度 < 0.55 视为不可信，不进候选。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..data_loader import Card

try:  # rapidfuzz 在 [ocr] 可选组里；没装时用 difflib 近似，保证测试环境可跑
    from rapidfuzz import fuzz

    def _token_set_ratio(a: str, b: str) -> float:
        return fuzz.token_set_ratio(a, b)
except ImportError:  # pragma: no cover - 取决于环境
    from difflib import SequenceMatcher

    def _token_set_ratio(a: str, b: str) -> float:
        ta, tb = set(a.split()), set(b.split())
        inter = " ".join(sorted(ta & tb))
        sa, sb = " ".join(sorted(ta)), " ".join(sorted(tb))
        base = SequenceMatcher(None, sa, sb).ratio()
        if inter:
            base = max(base,
                       SequenceMatcher(None, inter, sa).ratio(),
                       SequenceMatcher(None, inter, sb).ratio())
        return base * 100

CONFIDENCE_FLOOR = 0.55
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}$")


@dataclass(frozen=True)
class Match:
    card_id: str
    title: str
    score: float


_THOUSANDS_SEP = re.compile(r"(?<=\d)[,，.。、\s]{1,4}(?=\d{3}(?!\d))")


def normalize(text: str) -> str:
    """全角→半角、去千分位分隔符、统一小写；中文字符之间补空格便于分词比对。

    千分位不能只认逗号：实拍卡面 OCR 出来的 `220,000` 有 `220, 000`（逗号后带空格，
    最常见）、`220 000`、`220.000` 等七八种形态，只认 `,` 会让"成本/首付/贷款"这类
    关键数字**一个都对不上**，同标题不同价的卡（大买卖里成堆）就只能靠标题瞎猜。
    """
    text = unicodedata.normalize("NFKC", text)
    text = _THOUSANDS_SEP.sub("", text)
    text = text.lower()
    # 中日韩字符逐字断开，token_set 比对时按字命中
    text = re.sub(r"([一-鿿])", r" \1 ", text)
    return re.sub(r"\s+", " ", text).strip()


def _num_in(num: str, compact: str) -> bool:
    """卡上的数字是否**作为一个独立数字**出现在 OCR 文本里。

    不能用子串判断：`2,000` 是 `220,000` 的子串，这会让一张写着 $2,000 的卡在
    一段全是 $220,000 的文本上拿满分（实测 bd-003「下水管破裂」就这么盖过了
    bd-027「8室公寓待售」）。前后不许再挨着数字。
    """
    return re.search(rf"(?<!\d){re.escape(num)}(?!\d)", compact) is not None


def _split_keywords(card: Card) -> tuple[list[str], list[str], list[str]]:
    """把 ocr_keywords 分为 数字 / 代码(如 ON2U) / 文本 三类。"""
    nums, codes, words = [], [], []
    for kw in card.ocr_keywords:
        plain = normalize(kw).replace(" ", "")
        if plain.isdigit():
            nums.append(plain)
        elif _CODE_RE.match(plain):
            codes.append(plain)
        else:
            words.append(kw)
    return nums, codes, words


def score_card(ocr_text: str, card: Card) -> float:
    norm = normalize(ocr_text)
    compact = norm.replace(" ", "")
    nums, codes, words = _split_keywords(card)

    title_score = _token_set_ratio(norm, normalize(card.title)) / 100
    for w in words:
        title_score = max(title_score, _token_set_ratio(norm, normalize(w)) / 100)

    parts: list[tuple[float, float]] = [(0.6, title_score)]  # (权重, 得分)
    if nums:
        hit = sum(1 for n in nums if _num_in(n, compact))
        parts.append((0.3, hit / len(nums)))
    if codes:
        hit = sum(1 for c in codes if c in compact)
        parts.append((0.1, hit / len(codes)))
    total_w = sum(w for w, _ in parts)
    return sum(w * s for w, s in parts) / total_w


def match_cards(ocr_text: str, cards: list[Card], top: int = 3,
                floor: float = CONFIDENCE_FLOOR) -> list[Match]:
    if not ocr_text.strip():
        return []
    scored = [Match(c.id, c.title, round(score_card(ocr_text, c), 4)) for c in cards]
    scored = [m for m in scored if m.score >= floor]
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top]
