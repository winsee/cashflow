"""录入工具后端（M0 / FR-24）：录入库与游戏运行时库分离。

- 录入工具读写 server/data/entry/cards/*.json（录入库，纯数据记录，进 git，
  首次使用时自动从运行时库播种）；游戏引擎/识别只读 server/data/cards/*.json
  （运行时库）。录入侧任何操作都不影响进行中的对局。
- 点「发布」（POST /publish）才把录入库整体校验后拷入运行时库并热重载；
  也可手动把 entry/cards 下文件拷到 cards 下重启服务（手动导入）。
- id 由服务端自动生成（前缀+递增序号）；校验与启动加载同一套规则（JSON
  Schema + 业务校验 + 去重：标题+数值全同 = 重复卡拒绝；同名多版本须每张有
  ocr_keywords，design/04 §4/§6）。
- 并发约束：本模块 handler 全同步无 await，单进程单 worker（deploy 现状）下在
  事件循环上原子执行，多人同时录入不会产生读改写竞争。部署勿开多 worker。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .. import data_loader
from ..data_loader import (
    CARD_FILES, Card, DataValidationError,
    _business_validate_card, _check_deck_duplicates, _validate_schema,
)

router = APIRouter(prefix="/api/entry")

ID_PREFIX = {
    "SMALL_DEAL": "sd", "BIG_DEAL": "bd", "MARKET": "mk",
    "DOODAD": "dd", "PROFESSION": "prof",
}


def _check_deck(deck: str) -> None:
    if deck not in CARD_FILES:
        raise DataValidationError(f"未知牌叠: {deck}")


def _runtime_file(deck: str) -> Path:
    return data_loader.DATA_DIR / CARD_FILES[deck]


def _entry_file(deck: str) -> Path:
    """录入库文件；不存在时从运行时库播种（运行时也没有则建空叠）。"""
    path = data_loader.DATA_DIR / "entry" / CARD_FILES[deck]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        rt = _runtime_file(deck)
        path.write_text(rt.read_text(encoding="utf-8") if rt.exists() else "[]\n",
                        encoding="utf-8")
    return path


def _load_file(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_file(path: Path, cards: list[dict]) -> None:
    path.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _entry_cards(deck: str) -> list[dict]:
    return _load_file(_entry_file(deck))


def _entry_deck_of_id(card_id: str) -> str | None:
    for deck in CARD_FILES:
        if any(c["id"] == card_id for c in _entry_cards(deck)):
            return deck
    return None


def _gen_id(deck: str, used: set[str]) -> str:
    prefix = ID_PREFIX[deck]
    n = 1
    for cid in used:
        head, _, tail = cid.rpartition("-")
        if head == prefix and tail.isdigit():
            n = max(n, int(tail) + 1)
    while f"{prefix}-{n:03d}" in used:
        n += 1
    return f"{prefix}-{n:03d}"


def _all_used_ids(lib) -> set[str]:
    used = set(lib.cards)
    for deck in CARD_FILES:
        used.update(c["id"] for c in _entry_cards(deck))
    return used


# ---------------- 录入库读写 ----------------

@router.get("/stats")
async def stats(request: Request):
    lib = request.app.state.lib
    out = {}
    for deck in CARD_FILES:
        out[deck] = {
            "entry": len(_entry_cards(deck)),
            "runtime": sum(1 for c in lib.cards.values() if c.deck == deck),
        }
    return out


@router.get("/cards")
async def list_entry_cards(deck: str = Query(...)):
    _check_deck(deck)
    return _entry_cards(deck)


class CardBody(BaseModel):
    id: str = ""
    deck: str
    subtype: str
    title: str
    data: dict
    ocr_keywords: list[str] = []


@router.post("/cards")
async def upsert_card(body: CardBody, request: Request):
    _check_deck(body.deck)
    card_id = body.id.strip()
    if not card_id:
        card_id = _gen_id(body.deck, _all_used_ids(request.app.state.lib))
    else:
        owner = _entry_deck_of_id(card_id)
        if owner is not None and owner != body.deck:
            raise DataValidationError(f"id {card_id} 已被牌叠 {owner} 占用")
        rt = request.app.state.lib.cards.get(card_id)
        if rt is not None and rt.deck != body.deck:
            raise DataValidationError(f"id {card_id} 已被运行时库牌叠 {rt.deck} 占用")

    item = body.model_dump()
    item["id"] = card_id
    _validate_schema([item], "card.schema.json", "录入卡牌")
    _business_validate_card(
        Card(id=card_id, deck=body.deck, subtype=body.subtype,
             title=body.title, data=body.data), "录入卡牌")

    path = _entry_file(body.deck)
    cards = _load_file(path)
    replaced = False
    for i, c in enumerate(cards):
        if c["id"] == card_id:
            cards[i] = item
            replaced = True
            break
    if not replaced:
        cards.append(item)
    _check_deck_duplicates(cards, "录入卡牌")
    _save_file(path, cards)
    return {"ok": True, "replaced": replaced, "id": card_id}


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str):
    deck = _entry_deck_of_id(card_id)
    if deck is None:
        raise DataValidationError(f"录入库中卡牌不存在: {card_id}")
    path = _entry_file(deck)
    _save_file(path, [c for c in _load_file(path) if c["id"] != card_id])
    return {"ok": True}


@router.delete("/decks/{deck}")
async def clear_deck(deck: str):
    """整叠清空录入库（不影响运行时库与进行中的对局）。"""
    _check_deck(deck)
    _save_file(_entry_file(deck), [])
    return {"ok": True}


# ---------------- 发布到运行时库 ----------------

def _validate_staging() -> dict[str, list[dict]]:
    """整库校验录入库（与启动加载同一套规则），返回各叠卡列表。"""
    staged: dict[str, list[dict]] = {}
    seen_ids: dict[str, str] = {}
    for deck in CARD_FILES:
        rel = f"entry/{CARD_FILES[deck]}"
        items = _entry_cards(deck)
        _validate_schema(items, "card.schema.json", rel)
        _check_deck_duplicates(items, rel)
        for it in items:
            if it["deck"] != deck:
                raise DataValidationError(
                    f"{rel} 卡 {it['id']}: deck 字段 {it['deck']} 与文件不符（应为 {deck}）")
            if it["id"] in seen_ids:
                raise DataValidationError(
                    f"{rel} 卡 id 与 {seen_ids[it['id']]} 重复: {it['id']}")
            seen_ids[it["id"]] = deck
            _business_validate_card(
                Card(id=it["id"], deck=it["deck"], subtype=it["subtype"],
                     title=it["title"], data=it["data"]), rel)
        staged[deck] = items
    return staged


def _diff_summary(staged: dict[str, list[dict]]) -> dict:
    out = {}
    for deck, items in staged.items():
        rt_path = _runtime_file(deck)
        old = {c["id"]: c for c in (_load_file(rt_path) if rt_path.exists() else [])}
        new = {c["id"]: c for c in items}
        out[deck] = {
            "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)),
            "changed": sorted(i for i in set(new) & set(old) if new[i] != old[i]),
        }
    return out


@router.get("/publish/preview")
async def publish_preview():
    """发布预览：整库校验 + 与运行时库的差异摘要。"""
    staged = _validate_staging()
    return {"ok": True, "diff": _diff_summary(staged)}


@router.post("/publish")
async def publish(request: Request):
    staged = _validate_staging()
    diff = _diff_summary(staged)
    old_texts: dict[str, str | None] = {}
    for deck in CARD_FILES:
        rt = _runtime_file(deck)
        old_texts[deck] = rt.read_text(encoding="utf-8") if rt.exists() else None
    try:
        for deck, items in staged.items():
            _save_file(_runtime_file(deck), items)
        request.app.state.lib = data_loader.load_library()
    except Exception:
        for deck, text in old_texts.items():
            rt = _runtime_file(deck)
            if text is None:
                rt.unlink(missing_ok=True)
            else:
                rt.write_text(text, encoding="utf-8")
        raise
    return {"ok": True, "diff": diff}
