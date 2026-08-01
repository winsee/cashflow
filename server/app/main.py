"""FastAPI 入口：REST + WebSocket + 静态资源（design/03 §4、§5）。"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import diag
from .api.entry import router as entry_router
from .data_loader import DataValidationError, load_library
from .engine.errors import EngineError
from .recognize.base import Candidate, default_chain
from .recognize.matcher import match_cards
from .rooms import RoomManager
from .store.db import Database

DB_PATH = os.environ.get("CASHFLOW_DB", str(Path(__file__).resolve().parent.parent / "cashflow.db"))
WEB_DIST = Path(os.environ.get("CASHFLOW_WEB_DIST",
                               Path(__file__).resolve().parent.parent.parent / "web" / "dist"))
MANUAL_DIR = Path(os.environ.get("CASHFLOW_MANUAL_DIR",
                                 Path(__file__).resolve().parent.parent / "manual_pages"))


def cert_dir() -> Path:
    return Path(os.environ.get("CASHFLOW_CERT_DIR",
                               str(Path(DB_PATH).parent / "certs")))


async def _archive_loop(manager: RoomManager) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await manager.archive_idle()
        except Exception:
            pass   # 归档失败不影响服务，下个整点重试


def _warm_engine(eng, state) -> None:
    """预热跑在线程池里，异常必须自己接住写进 state：早期版本这个 future
    无人 await，模型加载失败（如云端内存不足）完全不留痕迹，只表现为
    「扫描永远识别不到」。"""
    t0 = time.monotonic()
    try:
        eng.warm()
        state.ocr_warm = {"state": "ok", "ms": int((time.monotonic() - t0) * 1000),
                          "error": None}
    except Exception as exc:
        state.ocr_warm = {"state": "failed", "ms": int((time.monotonic() - t0) * 1000),
                          "error": f"{type(exc).__name__}: {exc}"[:300]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # serve.py 会在同一进程/同一事件循环起 HTTP+HTTPS 两个 server，
    # lifespan 因此会进入两次——初始化必须幂等，否则会出现两套 RoomManager。
    if getattr(app.state, "manager", None) is None:
        lib = load_library()
        db = Database(DB_PATH)
        manager = RoomManager(db, lib)
        manager.restore_all()
        app.state.lib = lib
        app.state.manager = manager
        app.state.recognizer = default_chain()
        app.state.started_at = time.time()
        app.state.ocr_warm = {"state": "n/a", "ms": 0, "error": None}
        for eng in app.state.recognizer.engines:
            if getattr(eng, "name", "") == "local":
                if os.environ.get("CASHFLOW_OCR_WARMUP", "on") == "off":
                    # 小内存实例上"启动即加载三个模型"本身就可能触发 OOM，
                    # 关掉预热可单独验证服务能否活着（首帧扫描会慢一次）
                    app.state.ocr_warm = {"state": "skipped", "ms": 0, "error": None}
                    continue
                # 后台预热模型：首帧扫描不至于撞上加载耗时而超时降级
                app.state.ocr_warm = {"state": "pending", "ms": 0, "error": None}
                asyncio.get_running_loop().run_in_executor(
                    None, _warm_engine, eng, app.state)
        app.state.archive_task = asyncio.create_task(_archive_loop(manager))
    yield
    task = getattr(app.state, "archive_task", None)
    if task is not None:
        task.cancel()
        app.state.archive_task = None


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
    password: str | None = Field(default=None, max_length=32)


@app.post("/api/rooms")
async def create_room(body: CreateRoomBody):
    return await app.state.manager.create_room(
        body.name, body.nickname, body.maxPlayers, body.password or None)


@app.get("/api/rooms")
async def list_rooms():
    return app.state.manager.list_rooms()


class JoinBody(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    password: str | None = Field(default=None, max_length=32)


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: JoinBody):
    return await app.state.manager.join_room(code.upper(), body.nickname, body.password)


@app.get("/api/rooms/{code}/seats")
async def room_seats(code: str):
    return app.state.manager.seats(code.upper())


class TakeoverBody(BaseModel):
    playerId: str
    password: str | None = Field(default=None, max_length=32)


@app.post("/api/rooms/{code}/takeover")
async def takeover(code: str, body: TakeoverBody):
    return await app.state.manager.takeover(code.upper(), body.playerId, body.password)


class DeleteRoomBody(BaseModel):
    token: str | None = None
    password: str | None = Field(default=None, max_length=32)


@app.delete("/api/rooms/{code}")
async def delete_room(code: str, body: DeleteRoomBody | None = None):
    body = body or DeleteRoomBody()
    await app.state.manager.delete_room(code.upper(), body.token, body.password)
    return {"ok": True}


@app.get("/api/cards")
async def list_cards(deck: str | None = Query(None), q: str = Query("")):
    lib = app.state.lib
    cards = lib.by_deck(deck) if deck else list(lib.cards.values())
    if q:
        needle = q.lower()
        cards = [c for c in cards
                 if needle in c.title.lower()
                 or any(needle in k.lower() for k in c.ocr_keywords)]
    # raw = 卡面原文（标题/正文/数值栏/脚注），前端据此逐字渲染卡面；
    # data 仍是引擎唯一取数来源，两者不可互换（design/04 §2.5 卡库双轨）
    return [{"id": c.id, "deck": c.deck, "subtype": c.subtype,
             "title": c.title, "data": c.data, "raw": c.raw} for c in cards]


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
    """识别接口（FR-26/27）：返回 Top-3 候选；空候选 = 转手动选卡。

    `reason` 让前端能分清「超时/没装 OCR/没认出字/认出了没匹配上」，
    别再一律显示「未识别到，调整角度试试」（见 RecognizeOutcome）。
    """
    sess = app.state.manager.get(code.upper())
    data = await image.read()
    t0 = time.monotonic()
    out = await app.state.recognizer.recognize(data, deckHint, app.state.lib)
    duration_ms = int((time.monotonic() - t0) * 1000)
    top = out.candidates[:3]
    stat_id = app.state.manager.db.add_recog_stat(
        sess.room_id, deckHint, out.engine, duration_ms, [c.card_id for c in top])
    return {"candidates": [vars(c) for c in top], "engine": out.engine,
            "reason": out.reason, "textLen": out.text_len,
            "recognitionId": stat_id, "durationMs": duration_ms}


class RecognizeTextBody(BaseModel):
    # 限长：公网端点，别让人塞大文本进来空耗 CPU（正常一张卡 OCR 出来 100~300 字）
    text: str = Field(max_length=4000)
    deckHint: str | None = Field(default=None, max_length=20)
    clientMs: int = Field(default=0, ge=0, le=600_000)   # 手机端 OCR 耗时，进统计


@app.post("/api/rooms/{code}/recognize-text")
async def recognize_text(code: str, body: RecognizeTextBody):
    """浏览器端 OCR 的匹配接口（design/08）：手机跑识别，服务端只做封闭集打分。

    与 `/recognize` 的唯一区别是 OCR 在哪跑——候选、reason、统计口径完全一致，
    前端两条路可以共用一套渲染。服务端这里是纯字符串计算，不加载任何模型，
    512MB 的云主机也扛得住（服务端 PaddleOCR 在那种机器上必被 OOM 杀掉）。
    """
    sess = app.state.manager.get(code.upper())
    lib = app.state.lib
    cards = lib.by_deck(body.deckHint) if body.deckHint else list(lib.cards.values())
    t0 = time.monotonic()
    top = [Candidate(m.card_id, m.title, m.score, "browser")
           for m in match_cards(body.text, cards)]
    match_ms = int((time.monotonic() - t0) * 1000)
    # 这条路不会有 timeout / unavailable：识别已经在手机上跑完了
    reason = "ok" if top else ("no_match" if body.text.strip() else "no_text")
    # 耗时按手机端 OCR 计，/api/stats/recognition 上才能和服务端引擎横向比
    stat_id = app.state.manager.db.add_recog_stat(
        sess.room_id, body.deckHint, "browser", body.clientMs or match_ms,
        [c.card_id for c in top])
    return {"candidates": [vars(c) for c in top], "engine": "browser",
            "reason": reason, "textLen": len(body.text),
            "recognitionId": stat_id, "durationMs": body.clientMs,
            "matchMs": match_ms}


class ChosenBody(BaseModel):
    cardId: str


@app.post("/api/recognize/{stat_id}/chosen")
async def recognize_chosen(stat_id: int, body: ChosenBody):
    """FR-28：玩家确认选卡后回填命中情况（fire-and-forget，不影响入账）。"""
    app.state.manager.db.set_recog_chosen(stat_id, body.cardId)
    return {"ok": True}


@app.get("/api/stats/recognition")
async def recognition_stats():
    """FR-28：按引擎聚合的识别统计（次数 / Top-3 命中率 / 平均耗时）。"""
    return app.state.manager.db.recog_summary()


# ---------------- 诊断（部署排障用） ----------------

def _local_engine():
    chain = getattr(app.state, "recognizer", None)
    if chain is None:
        return None
    return next((e for e in chain.engines if getattr(e, "name", "") == "local"), None)


@app.get("/api/health")
async def health():
    """部署自检：OCR 到底有没有、预热成功没有、内存离上限还有多远。

    云端小实例上「扫描永远识别不到」有好几种成因（依赖缺失 / 内存被 OOM 杀
    / CPU 太慢超时 / 匹配不上），靠这个端点一次分清：
    - `memory.limitMb` 512 且 `rssMb` 逼近它 → 内存不够
    - `uptimeS` 每次刷新都归零 → 实例在重启循环
    - `ocr.warm.state=failed` → 模型压根没加载起来
    """
    from .recognize import local_ocr
    chain = getattr(app.state, "recognizer", None)
    local = _local_engine()
    db = app.state.manager.db
    rooms = db.conn.execute("SELECT COUNT(*) AS n FROM room").fetchone()["n"]
    stats = db.conn.execute("SELECT COUNT(*) AS n FROM recog_stat").fetchone()["n"]
    return {
        "uptimeS": int(time.time() - getattr(app.state, "started_at", time.time())),
        "ocr": {
            "configured": os.environ.get("CASHFLOW_OCR", "auto"),
            "available": local_ocr.available(),
            "engines": [getattr(e, "name", "?") for e in (chain.engines if chain else [])],
            "warm": getattr(app.state, "ocr_warm", None),
            "timeoutS": local_ocr.timeout_s(),
            "engineLoaded": bool(local and local.engine_loaded),
            "lastMs": getattr(local, "last_ms", None),
        },
        "memory": diag.memory_report(),
        "db": {"path": DB_PATH, "rooms": rooms, "recogStats": stats},
        "diagEnabled": os.environ.get("CASHFLOW_DIAG", "on") != "off",
    }


@app.post("/api/health/ocr-probe")
async def ocr_probe(image: UploadFile | None = File(None),
                    deckHint: str | None = Form(None),
                    timeout: float | None = Form(None)):
    """实测一次云端 OCR：不建房间、不写库，返回耗时 / OCR 出的文本 / 候选。

    不传图片就用一张空白图，只测「模型跑不跑得通 + 冷启动要多久」。
    `timeout` 可临时放宽（上限 120s），用来区分「跑不动」和「只是慢」。
    识别本身走引擎的 Semaphore(1)，公网上也不至于被并发打爆。
    `CASHFLOW_DIAG=off` 可整体关闭本端点。
    """
    if os.environ.get("CASHFLOW_DIAG", "on") == "off":
        raise HTTPException(status_code=404, detail="diagnostics disabled")
    from .recognize import local_ocr
    local = _local_engine()
    if local is None:
        return {"ok": False, "reason": "unavailable", "ms": 0,
                "installed": local_ocr.available(),
                "configured": os.environ.get("CASHFLOW_OCR", "auto")}
    data = await image.read() if image is not None else local_ocr.blank_jpeg()
    t0 = time.monotonic()
    try:
        out = await local.probe(data, deckHint, app.state.lib,
                                min(timeout, 120.0) if timeout else None)
    except asyncio.TimeoutError:
        return {"ok": False, "reason": "timeout", "imageBytes": len(data),
                "ms": int((time.monotonic() - t0) * 1000),
                "timeoutS": min(timeout, 120.0) if timeout else local_ocr.timeout_s()}
    except Exception as exc:
        return {"ok": False, "reason": f"error:{type(exc).__name__}",
                "imageBytes": len(data), "ms": int((time.monotonic() - t0) * 1000),
                "error": f"{exc}"[:300]}
    return {"ok": True, "reason": "ok" if out["candidates"] else
            ("no_match" if out["textLen"] else "no_text"),
            "imageBytes": len(data), "totalMs": int((time.monotonic() - t0) * 1000),
            **out}


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
    # Windows 的 mimetypes 没注册 .webp，猜成 octet-stream 会让 <img> 拿不准，显式给
    media = {".webp": "image/webp", ".png": "image/png",
             ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(path.suffix.lower())
    # 扫描页是不变的静态内容，长缓存让重复翻阅走本地缓存（弱网/离线更稳）
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------- 自签证书信任引导（design/03 §7.1，扫描框需 HTTPS） ----------------

@app.get("/ca.crt")
async def download_ca():
    path = cert_dir() / "ca.crt"
    if not path.exists():
        raise HTTPException(404, "证书未生成（请用 serve.py / Docker 方式启动）")
    return FileResponse(path, media_type="application/x-x509-ca-cert",
                        filename="cashflow-ca.crt")


_TRUST_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>开启扫描识别（信任证书）</title>
<style>
 body{font-family:system-ui,-apple-system,sans-serif;max-width:560px;margin:24px auto;
      padding:0 16px;line-height:1.7;color:#222}
 h1{font-size:20px} h2{font-size:16px;margin-top:24px}
 .btn{display:inline-block;background:#2f855a;color:#fff;padding:10px 18px;
      border-radius:8px;text-decoration:none;margin:8px 0}
 li{margin:6px 0} .muted{color:#777;font-size:13px}
</style></head><body>
<h1>📷 开启扫描识别（一次性设置）</h1>
<p>扫描框需要浏览器调起摄像头，而浏览器要求 HTTPS。本工具使用房主电脑
自动生成的<b>本地根证书</b>，每台手机信任一次即可，之后一直有效。</p>
<a class="btn" href="/ca.crt">① 下载根证书 cashflow-ca.crt</a>
<h2>② iPhone / iPad（Safari）</h2>
<ol>
<li>下载后弹出「已下载描述文件」→ 打开「设置」，顶部点「已下载描述文件」→ 安装；</li>
<li>再进「设置 → 通用 → 关于本机 → 证书信任设置」，打开对
「Cashflow Companion 本地根证书」的完全信任开关。</li>
</ol>
<h2>② 安卓（Chrome）</h2>
<ol>
<li>下载后进「设置 → 安全 → 更多安全设置 → 加密与凭据 → 安装证书 → CA 证书」，
选择下载的 cashflow-ca.crt（各品牌路径略有差异，可在设置里搜「证书」）。</li>
</ol>
<h2>③ 用 HTTPS 地址重新进入房间</h2>
<p>把地址栏里的 <b>http://…:8000</b> 换成 <b>https://…:8443</b>（IP 不变）打开，
选卡时就会出现扫描框。</p>
<p class="muted">不想装证书也没关系：继续用 http 地址，选卡时点「📷 拍照」走系统相机，
功能完全一样，只是少了实时取景。本证书仅本工具局域网使用，不影响其他网站。</p>
</body></html>"""


@app.get("/trust")
async def trust_guide():
    return HTMLResponse(_TRUST_HTML)


# ---------------- WebSocket ----------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query(...)):
    try:
        sess, player_id = app.state.manager.auth(token)
    except EngineError:
        # 必须先 accept 再 close(4001)：握手前 close 会被 uvicorn 降级成 HTTP 403，
        # 浏览器只能拿到 CloseEvent.code === 1006，分不清「房间没了/令牌失效」和
        # 「服务器暂时连不上」，前端就只能无限重连、永远卡在「连接中…」。
        await ws.accept()
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
        pass
    finally:
        # 必须 finally：删除房间与空房清理都以「有没有活连接」为准，
        # 任何一条异常路径漏掉 detach，都会留下僵尸连接让房间永远删不掉。
        sess.detach(player_id, ws)


# ---------------- 前端静态资源（构建后） ----------------

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
