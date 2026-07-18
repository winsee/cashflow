"""FastAPI 入口：REST + WebSocket + 静态资源（design/03 §4、§5）。"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .api.entry import router as entry_router
from .data_loader import DataValidationError, load_library
from .engine.errors import EngineError
from .recognize.base import default_chain
from .rooms import RoomManager
from .store.db import Database

DB_PATH = os.environ.get("CASHFLOW_DB", str(Path(__file__).resolve().parent.parent / "cashflow.db"))
WEB_DIST = Path(os.environ.get("CASHFLOW_WEB_DIST",
                               Path(__file__).resolve().parent.parent.parent / "web" / "dist"))
MANUAL_DIR = Path(os.environ.get("CASHFLOW_MANUAL_DIR",
                                 Path(__file__).resolve().parent.parent / "manual_pages"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    lib = load_library()
    db = Database(DB_PATH)
    manager = RoomManager(db, lib)
    manager.restore_all()
    app.state.lib = lib
    app.state.manager = manager
    app.state.recognizer = default_chain()
    yield


app = FastAPI(title="现金流游戏辅助工具", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.exception_handler(EngineError)
async def engine_error_handler(request, exc: EngineError):
    return JSONResponse(status_code=400, content={
        "code": exc.code, "message": exc.message, **exc.extra})


@app.exception_handler(DataValidationError)
async def data_error_handler(request, exc: DataValidationError):
    return JSONResponse(status_code=400, content={
        "code": "DATA_INVALID", "message": str(exc)})


app.include_router(entry_router)


# ---------------- REST ----------------

class CreateRoomBody(BaseModel):
    name: str = "现金流对局"
    nickname: str = Field(min_length=1, max_length=20)
    maxPlayers: int = Field(default=6, ge=2, le=6)


@app.post("/api/rooms")
async def create_room(body: CreateRoomBody):
    return await app.state.manager.create_room(body.name, body.nickname, body.maxPlayers)


class JoinBody(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: JoinBody):
    return await app.state.manager.join_room(code.upper(), body.nickname)


@app.get("/api/cards")
async def list_cards(deck: str | None = Query(None), q: str = Query("")):
    lib = app.state.lib
    cards = lib.by_deck(deck) if deck else list(lib.cards.values())
    if q:
        needle = q.lower()
        cards = [c for c in cards
                 if needle in c.title.lower()
                 or any(needle in k.lower() for k in c.ocr_keywords)]
    return [{"id": c.id, "deck": c.deck, "subtype": c.subtype,
             "title": c.title, "data": c.data} for c in cards]


@app.get("/api/board/fasttrack")
async def fasttrack_board():
    lib = app.state.lib
    return {
        "businesses": [vars(b) for b in lib.ft_businesses.values()],
        "dreams": [vars(d) for d in lib.ft_dreams.values()],
        "charityCost": lib.ft_charity_cost,
    }


@app.get("/api/rooms/{code}/export")
async def export_room(code: str):
    sess = app.state.manager.get(code.upper())
    return {"roomCode": code.upper(), "events": sess.log_rows()}


@app.get("/api/rooms/{code}/log")
async def room_log(code: str):
    sess = app.state.manager.get(code.upper())
    return sess.log_rows()


@app.post("/api/rooms/{code}/recognize")
async def recognize(code: str, image: UploadFile = File(...),
                    deckHint: str | None = Form(None)):
    """识别接口（FR-26/27）：返回 Top-3 候选；空候选 = 转手动选卡。"""
    sess = app.state.manager.get(code.upper())
    data = await image.read()
    cands, engine = await app.state.recognizer.recognize(data, deckHint, app.state.lib)
    return {"candidates": [vars(c) for c in cands[:3]], "engine": engine}


# ---------------- 说明书（FR-31） ----------------

@app.get("/api/manual/pages")
async def manual_pages():
    if not MANUAL_DIR.exists():
        return {"pages": []}
    pages = sorted(p.name for p in MANUAL_DIR.iterdir()
                   if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    return {"pages": pages}


@app.get("/api/manual/pages/{name}")
async def manual_page(name: str):
    path = MANUAL_DIR / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


# ---------------- WebSocket ----------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query(...)):
    try:
        sess, player_id = app.state.manager.auth(token)
    except EngineError:
        await ws.close(code=4001)
        return
    await ws.accept()
    await sess.attach(player_id, ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                await sess.handle_action(player_id, msg.get("actionId"),
                                         msg["type"], msg.get("payload") or {})
                await ws.send_text(json.dumps(
                    {"type": "ack", "actionId": msg.get("actionId")}, ensure_ascii=False))
            except EngineError as e:
                await ws.send_text(json.dumps({
                    "type": "error", "actionId": msg.get("actionId"),
                    "code": e.code, "message": e.message, **e.extra,
                }, ensure_ascii=False))
            except (KeyError, json.JSONDecodeError):
                await ws.send_text(json.dumps({
                    "type": "error", "code": "BAD_MESSAGE", "message": "消息格式错误"},
                    ensure_ascii=False))
    except WebSocketDisconnect:
        sess.detach(player_id, ws)


# ---------------- 前端静态资源（构建后） ----------------

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
