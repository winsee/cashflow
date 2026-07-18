"""服务端冒烟：REST 建房/加入 + WS 行动 + 断线重连快照 + 日志导出。"""
import os
import uuid

os.environ["CASHFLOW_DB"] = os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db")

from fastapi.testclient import TestClient   # noqa: E402

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
        assert {p["id"] for p in profs} >= {"prof-doctor", "prof-manager"}

        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            snap = wa.receive_json()
            assert snap["type"] == "snapshot" and snap["you"] == host["playerId"]
            wb.receive_json()

            _act(wa, "SELECT_PROFESSION", professionId="prof-doctor")
            wb.receive_json()   # 广播同步
            _act(wb, "SELECT_PROFESSION", professionId="prof-manager")
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
            _act(wa, "DRAW_CARD", cardId="sd-house-3b2b-01")
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
        assert r.json() == {"candidates": [], "engine": "manual"}


def test_host_revert():
    with TestClient(app) as client:
        r = client.post("/api/rooms", json={"nickname": "房主"})
        host = r.json()
        code = host["roomCode"]
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json(); wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-doctor"); wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-manager"); wa.receive_json()
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
