"""服务端冒烟：REST 建房/加入 + WS 行动 + 断线重连快照 + 日志导出。"""
import os
import uuid

os.environ["CASHFLOW_DB"] = os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db")

import pytest                               # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.main import app                    # noqa: E402


def _act(ws, atype, **payload):
    aid = uuid.uuid4().hex
    ws.send_json({"actionId": aid, "type": atype, "payload": payload})
    state = None
    while True:
        msg = ws.receive_json()
        if msg["type"] == "error" and msg.get("actionId") == aid:
            raise AssertionError(f"{atype}: {msg['code']} {msg['message']}")
        if msg["type"] == "state":
            state = msg
        if msg["type"] == "ack" and msg.get("actionId") == aid:
            return state


def test_full_room_flow():
    with TestClient(app) as client:
        r = client.post("/api/rooms", json={"nickname": "房主", "name": "测试局"})
        assert r.status_code == 200
        host = r.json()
        code = host["roomCode"]

        r = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"})
        guest = r.json()

        r = client.get("/api/cards", params={"deck": "PROFESSION"})
        profs = r.json()
        assert {p["id"] for p in profs} >= {"prof-006", "prof-010"}

        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            snap = wa.receive_json()
            assert snap["type"] == "snapshot" and snap["you"] == host["playerId"]
            wb.receive_json()

            _act(wa, "SELECT_PROFESSION", professionId="prof-006")
            wb.receive_json()   # 广播同步
            _act(wb, "SELECT_PROFESSION", professionId="prof-010")
            wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari")
            wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet")
            wa.receive_json()
            _act(wa, "SET_TURN_ORDER", order=[host["playerId"], guest["playerId"]])
            wb.receive_json()
            st = _act(wa, "START_GAME")
            players = {p["id"]: p for p in st["state"]["players"]}
            assert players[host["playerId"]]["cash"] == 3950
            assert players[guest["playerId"]]["cash"] == 2070
            wb.receive_json()

            # 房主回合：抽小生意买房 → 结算 → 结束回合
            _act(wa, "DRAW_CARD", cardId="sd-006")
            wb.receive_json()
            st = _act(wa, "CARD_DECISION", decision="buy")
            me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
            assert me["cash"] == 950
            assert me["derived"]["passiveIncome"] == 100
            wb.receive_json()
            _act(wa, "PAYDAY")
            wb.receive_json()
            st = _act(wa, "END_TURN")
            assert st["state"]["currentPlayerId"] == guest["playerId"]

        # 断线重连：快照拉齐
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa:
            snap = wa.receive_json()
            assert snap["type"] == "snapshot"
            assert snap["state"]["currentPlayerId"] == guest["playerId"]

        # 日志可审计
        log = client.get(f"/api/rooms/{code}/log").json()
        types = [e["type"] for e in log]
        assert "GAME_STARTED" in types and "ASSET_BOUGHT" in types

        # 手动识别兜底：空候选
        r = client.post(f"/api/rooms/{code}/recognize",
                        files={"image": ("x.jpg", b"fake", "image/jpeg")},
                        data={"deckHint": "SMALL_DEAL"})
        d = r.json()
        assert d["candidates"] == [] and d["engine"] == "manual"
        assert "recognitionId" in d   # FR-28：识别统计关联 id


def test_lobby_password_takeover_delete():
    """大厅列表 / 房间密码 / 座位接管 / 删除房间（FR-1、NFR-6）。"""
    with TestClient(app) as client:
        a = client.post("/api/rooms", json={
            "nickname": "房主", "name": "加密局", "password": "8888"}).json()
        b = client.post("/api/rooms", json={"nickname": "路人", "name": "开放局"}).json()

        rooms = {r["code"]: r for r in client.get("/api/rooms").json()}
        assert rooms[a["roomCode"]]["hasPassword"] is True
        assert rooms[b["roomCode"]]["hasPassword"] is False
        assert rooms[a["roomCode"]]["playerCount"] == 1
        assert rooms[a["roomCode"]]["status"] == "LOBBY"

        # 加入：错密码拒绝，对密码进入
        r = client.post(f"/api/rooms/{a['roomCode']}/join",
                        json={"nickname": "小明", "password": "0000"})
        assert r.status_code == 400 and r.json()["code"] == "BAD_PASSWORD"
        guest = client.post(f"/api/rooms/{a['roomCode']}/join",
                            json={"nickname": "小明", "password": "8888"}).json()

        seats = client.get(f"/api/rooms/{a['roomCode']}/seats").json()
        assert seats["hasPassword"] is True
        assert {p["nickname"] for p in seats["players"]} == {"房主", "小明"}

        # 座位接管：错密码拒；成功后旧令牌作废、新令牌可连
        r = client.post(f"/api/rooms/{a['roomCode']}/takeover",
                        json={"playerId": guest["playerId"], "password": "0000"})
        assert r.status_code == 400 and r.json()["code"] == "BAD_PASSWORD"
        taken = client.post(f"/api/rooms/{a['roomCode']}/takeover",
                            json={"playerId": guest["playerId"], "password": "8888"}).json()
        assert taken["playerId"] == guest["playerId"]
        assert taken["playerToken"] != guest["playerToken"]
        with client.websocket_connect(f"/ws?token={taken['playerToken']}") as w:
            assert w.receive_json()["you"] == guest["playerId"]
        # 作废令牌：握手先 accept 再以 4001 关闭，前端据此清会话回大厅
        # （握手前 close 会被降级成 HTTP 403，浏览器只看得到 1006）
        with pytest.raises(WebSocketDisconnect) as ei:
            with client.websocket_connect(f"/ws?token={guest['playerToken']}") as w:
                w.receive_json()
        assert ei.value.code == 4001

        # 删除：未结束房间需房主令牌或密码；无密码房只认房主令牌
        r = client.request("DELETE", f"/api/rooms/{a['roomCode']}", json={})
        assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        r = client.request("DELETE", f"/api/rooms/{a['roomCode']}",
                           json={"password": "8888"})
        assert r.json() == {"ok": True}
        r = client.request("DELETE", f"/api/rooms/{b['roomCode']}",
                           json={"password": "随便"})
        assert r.status_code == 400
        r = client.request("DELETE", f"/api/rooms/{b['roomCode']}",
                           json={"token": b["playerToken"]})
        assert r.json() == {"ok": True}
        left = {x["code"] for x in client.get("/api/rooms").json()}
        assert a["roomCode"] not in left and b["roomCode"] not in left
        r = client.get(f"/api/rooms/{a['roomCode']}/seats")
        assert r.status_code == 400 and r.json()["code"] == "NO_ROOM"


def test_host_revert():
    with TestClient(app) as client:
        r = client.post("/api/rooms", json={"nickname": "房主"})
        host = r.json()
        code = host["roomCode"]
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json(); wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-006"); wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-010"); wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari"); wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet"); wa.receive_json()
            _act(wa, "SET_TURN_ORDER", order=[host["playerId"], guest["playerId"]]); wb.receive_json()
            _act(wa, "START_GAME"); wb.receive_json()
            st = _act(wa, "TAKE_LOAN", amount=5000); wb.receive_json()
            me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
            assert me["cash"] == 3950 + 5000
            loan_seq = max(e["seq"] for e in client.get(f"/api/rooms/{code}/log").json()
                           if e["type"] == "LOAN_TAKEN")
            st = _act(wa, "HOST_REVERT", eventSeq=loan_seq, reason="录错了")
            me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
            assert me["cash"] == 3950
            assert me["liabilities"]["bank_loan"] == 0
        log = client.get(f"/api/rooms/{code}/log").json()
        reverted = [e for e in log if e["type"] == "LOAN_TAKEN"]
        assert reverted and reverted[0]["revoked"] is True


def test_forced_card_settle_preview():
    """强制卡结算预览随状态下发；条件豁免时事件带卡名与原因（供日志展示）。"""
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "房主"}).json()
        code = host["roomCode"]
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json(); wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-006"); wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-010"); wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari"); wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet"); wa.receive_json()
            _act(wa, "SET_TURN_ORDER", order=[host["playerId"], guest["playerId"]]); wb.receive_json()
            _act(wa, "START_GAME"); wb.receive_json()

            # 无孩子抽「为女儿举行婚礼」：预览显示豁免，结算后现金不变
            st = _act(wa, "DRAW_CARD", cardId="dd-002"); wb.receive_json()
            assert st["state"]["activeCard"]["settlePreview"] == {
                "due": 0, "note": "无孩子，无需支付", "waived": True}
            st = _act(wa, "CARD_DECISION", decision="pay"); wb.receive_json()
            me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
            assert me["cash"] == 3950
        paid = [e for e in client.get(f"/api/rooms/{code}/log").json()
                if e["type"] == "DOODAD_PAID"]
        assert paid[0]["payload"]["title"] == "为女儿举行婚礼"
        assert paid[0]["payload"]["note"] == "无孩子，无需支付"
