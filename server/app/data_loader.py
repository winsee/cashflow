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


def load_library(data_dir: Path | None = None) -> CardLibrary:
    global DATA_DIR
    if data_dir is not None:
        DATA_DIR = data_dir
    lib = CardLibrary()
    titles: dict[tuple[str, str], str] = {}
    for deck, rel in CARD_FILES.items():
        path = DATA_DIR / rel
        raw = _load_json(path)
        _validate_schema(raw, "card.schema.json", rel)
        for item in raw:
            card = Card(
                id=item["id"],
                deck=item["deck"],
                subtype=item["subtype"],
                title=item["title"],
                data=item["data"],
                ocr_keywords=tuple(item.get("ocr_keywords", ())),
            )
            if card.deck != deck:
                raise DataValidationError(f"{rel} 卡 {card.id}: deck 字段 {card.deck} 与文件不符（应为 {deck}）")
            if card.id in lib.cards:
                raise DataValidationError(f"{rel} 卡 id 重复: {card.id}")
            key = (card.deck, card.title)
            if key in titles:
                raise DataValidationError(
                    f"{rel} 重复标题「{card.title}」({titles[key]} / {card.id})：须补充区分关键词并改标题"
                )
            titles[key] = card.id
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
