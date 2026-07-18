"""录入工具后端（M0 / FR-24）：录卡即写回 server/data/cards/*.json（权威数据源）。

- 保存前执行与启动加载相同的校验（JSON Schema + 业务校验，如 cost=downPayment+mortgage）；
- 保存成功后热重载卡库（进行中的对局不受影响，新决策用新数据，design/04 §2.5）。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import data_loader
from ..data_loader import CARD_FILES, Card, DataValidationError, _business_validate_card, _validate_schema

router = APIRouter(prefix="/api/entry")


def _file_for_deck(deck: str) -> Path:
    if deck not in CARD_FILES:
        raise DataValidationError(f"未知牌叠: {deck}")
    return data_loader.DATA_DIR / CARD_FILES[deck]


def _load_file(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_file(path: Path, cards: list[dict]) -> None:
    path.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@router.get("/stats")
async def stats(request: Request):
    lib = request.app.state.lib
    out = {}
    for deck in CARD_FILES:
        out[deck] = sum(1 for c in lib.cards.values() if c.deck == deck)
    return out


class CardBody(BaseModel):
    id: str
    deck: str
    subtype: str
    title: str
    data: dict
    ocr_keywords: list[str] = []


@router.post("/cards")
async def upsert_card(body: CardBody, request: Request):
    item = body.model_dump()
    _validate_schema([item], "card.schema.json", "录入卡牌")
    _business_validate_card(
        Card(id=body.id, deck=body.deck, subtype=body.subtype,
             title=body.title, data=body.data), "录入卡牌")
    path = _file_for_deck(body.deck)
    cards = _load_file(path)
    # 重复标题告警（不同 id 同标题须补充区分关键词，design/04 §6）
    dup = [c for c in cards if c["title"] == body.title and c["id"] != body.id]
    if dup and not body.ocr_keywords:
        raise DataValidationError(
            f"标题「{body.title}」与 {dup[0]['id']} 重复：请补充区分关键词（ocr_keywords）")
    replaced = False
    for i, c in enumerate(cards):
        if c["id"] == body.id:
            cards[i] = item
            replaced = True
            break
    if not replaced:
        cards.append(item)
    _save_file(path, cards)
    request.app.state.lib = data_loader.load_library()
    return {"ok": True, "replaced": replaced}


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, request: Request):
    lib = request.app.state.lib
    card = lib.cards.get(card_id)
    if card is None:
        raise DataValidationError(f"卡牌不存在: {card_id}")
    path = _file_for_deck(card.deck)
    cards = [c for c in _load_file(path) if c["id"] != card_id]
    _save_file(path, cards)
    request.app.state.lib = data_loader.load_library()
    return {"ok": True}
