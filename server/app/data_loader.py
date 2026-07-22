"""权威数据源加载：server/data 下的 JSON 文件（design/04 §2.5）。

启动时执行 JSON Schema 校验 + 业务校验（如 cost = downPayment + mortgage），
校验失败抛 DataValidationError 并指出文件与卡牌 id。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CARD_FILES = {
    "SMALL_DEAL": "cards/small_deal.json",
    "BIG_DEAL": "cards/big_deal.json",
    "MARKET": "cards/market.json",
    "DOODAD": "cards/doodad.json",
    "PROFESSION": "cards/professions.json",
}


class DataValidationError(Exception):
    pass


@dataclass(frozen=True)
class Card:
    id: str
    deck: str
    subtype: str
    title: str
    data: dict[str, Any]
    ocr_keywords: tuple[str, ...] = ()
    key: str = ""                      # 同内容重复卡共用；识别去重按它归组
    duplicate_of: str | None = None    # 指向组内首张（牌堆构成，非录入错误）
    raw: dict[str, Any] = field(default_factory=dict)   # 卡面原文，纯线上版据此渲染


@dataclass(frozen=True)
class FastTrackBusiness:
    id: str
    name: str
    down_payment: int
    cashflow: int = 0
    dice_rule: dict[str, Any] | None = None


@dataclass(frozen=True)
class FastTrackDream:
    id: str
    name: str
    price: int


@dataclass
class CardLibrary:
    cards: dict[str, Card] = field(default_factory=dict)
    ft_businesses: dict[str, FastTrackBusiness] = field(default_factory=dict)
    ft_dreams: dict[str, FastTrackDream] = field(default_factory=dict)
    ft_charity_cost: int = 100000
    rat_race_squares: list[str] = field(default_factory=list)

    def get(self, card_id: str) -> Card:
        try:
            return self.cards[card_id]
        except KeyError:
            raise DataValidationError(f"卡牌不存在: {card_id}") from None

    def by_deck(self, deck: str) -> list[Card]:
        return [c for c in self.cards.values() if c.deck == deck]

    def get_ft_business(self, square_id: str) -> FastTrackBusiness:
        try:
            return self.ft_businesses[square_id]
        except KeyError:
            raise DataValidationError(f"快车道企业格不存在: {square_id}") from None

    def get_ft_dream(self, square_id: str) -> FastTrackDream:
        try:
            return self.ft_dreams[square_id]
        except KeyError:
            raise DataValidationError(f"快车道梦想格不存在: {square_id}") from None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataValidationError(f"{path.name} 不是合法 JSON：第{e.lineno}行 {e.msg}") from e


def _validate_schema(instance: Any, schema_name: str, source: str) -> None:
    schema = _load_json(DATA_DIR / "schema" / schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        e = errors[0]
        loc = "/".join(str(p) for p in e.absolute_path) or "(根)"
        raise DataValidationError(f"{source} 校验失败 @ {loc}: {e.message}")


def _business_validate_card(card: Card, source: str) -> None:
    d = card.data
    if card.subtype in ("REALESTATE", "BUSINESS"):
        mortgage = d.get("mortgage", 0)
        if d["cost"] != d["downPayment"] + mortgage:
            raise DataValidationError(
                f"{source} 卡 {card.id}: cost({d['cost']}) != downPayment({d['downPayment']}) + mortgage({mortgage})"
            )
    pr = d.get("priceRange")
    if isinstance(pr, (list, tuple)) and len(pr) == 2 and pr[0] > pr[1]:
        raise DataValidationError(
            f"{source} 卡 {card.id}: 价格区间下限({pr[0]})大于上限({pr[1]})")


def _content_key(item: dict) -> str:
    """卡牌内容签名：子类型 + 全部数值。"""
    return item["subtype"] + "|" + json.dumps(item["data"], sort_keys=True, ensure_ascii=False)


def _check_deck_duplicates(items: list[dict], source: str) -> None:
    """重复卡判定（design/06 §5、design/07 §2.1）。

    实体牌堆里本来就有 9 组共 20 张完全相同的卡，它们直接决定抽牌概率，
    **必须按实际张数入库**，洗牌时不得按 key 去重。因此「重复」不是错误，
    但必须显式标注：同 key + 第 2 张起 duplicateOf 指向首张。缺标注才报错。

    归组依据是 key 而非数值签名：sd-003/sd-040 是两张不同的实体卡（「市场强劲」/
    「低利率」两种剧情），数值恰好相同但各自独立，不构成重复卡。
    """
    by_key: dict[str, list[dict]] = {}
    for it in items:
        by_key.setdefault(it["key"], []).append(it)
    for key, group in by_key.items():
        if len(group) == 1:
            continue
        first, rest = group[0], group[1:]
        sigs = {_content_key(it) for it in group}
        if len(sigs) > 1:
            ids = " / ".join(it["id"] for it in group)
            raise DataValidationError(
                f"{source} 同 key「{key}」的卡（{ids}）数值不一致："
                f"共用 key 表示是同内容重复卡，数值不同请改用不同的 key")
        for it in rest:
            dup = it.get("duplicateOf")
            if not dup:
                raise DataValidationError(
                    f"{source} 卡「{it['title']}」({it['id']}) 与 {first['id']} 同 key 同数值："
                    f"若确为牌堆重复卡请标注 duplicateOf: {first['id']}，否则是录入重复，请删除")
            if dup != first["id"]:
                raise DataValidationError(
                    f"{source} 卡 {it['id']} 的 duplicateOf 指向 {dup}，应指向组内首张 {first['id']}")

    # 同名不同值 = 多版本卡（如 MYT4U 的 6 种价位），须每张有区分关键词供识别打分
    by_title: dict[str, list[dict]] = {}
    for it in items:
        by_title.setdefault(it["title"], []).append(it)
    for title, group in by_title.items():
        if len(group) == 1:
            continue
        for it in group:
            if not it.get("ocr_keywords"):
                raise DataValidationError(
                    f"{source} 同名卡「{title}」({it['id']})：同名多版本卡须每张都填区分关键词（ocr_keywords）")


def load_library(data_dir: Path | None = None) -> CardLibrary:
    global DATA_DIR
    if data_dir is not None:
        DATA_DIR = data_dir
    lib = CardLibrary()
    for deck, rel in CARD_FILES.items():
        path = DATA_DIR / rel
        raw = _load_json(path)
        _validate_schema(raw, "card.schema.json", rel)
        _check_deck_duplicates(raw, rel)
        for item in raw:
            card = Card(
                id=item["id"],
                deck=item["deck"],
                subtype=item["subtype"],
                title=item["title"],
                data=item["data"],
                ocr_keywords=tuple(item.get("ocr_keywords", ())),
                key=item.get("key", ""),
                duplicate_of=item.get("duplicateOf"),
                raw=item.get("raw", {}),
            )
            if card.deck != deck:
                raise DataValidationError(f"{rel} 卡 {card.id}: deck 字段 {card.deck} 与文件不符（应为 {deck}）")
            if card.id in lib.cards:
                raise DataValidationError(f"{rel} 卡 id 重复: {card.id}")
            _business_validate_card(card, rel)
            lib.cards[card.id] = card

    ft_raw = _load_json(DATA_DIR / "board" / "fast_track.json")
    _validate_schema(ft_raw, "fast_track.schema.json", "board/fast_track.json")
    for b in ft_raw["businesses"]:
        if not b.get("cashflow") and not b.get("diceRule"):
            raise DataValidationError(f"fast_track.json 企业格 {b['id']}: cashflow 与 diceRule 至少一项")
        lib.ft_businesses[b["id"]] = FastTrackBusiness(
            id=b["id"], name=b["name"], down_payment=b["downPayment"],
            cashflow=b.get("cashflow", 0), dice_rule=b.get("diceRule"),
        )
    for d in ft_raw["dreams"]:
        lib.ft_dreams[d["id"]] = FastTrackDream(id=d["id"], name=d["name"], price=d["price"])
    lib.ft_charity_cost = ft_raw["specials"]["charityCost"]

    rr_raw = _load_json(DATA_DIR / "board" / "rat_race.json")
    lib.rat_race_squares = rr_raw["squares"]
    return lib
