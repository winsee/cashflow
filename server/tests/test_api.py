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


def test_online_room_rejects_recognize():
    """纯线上房间没有实体卡可拍，两个识别端点一律拒绝（change D10）。"""
    with TestClient(app) as client:
        r = client.post("/api/rooms", json={"nickname": "房主", "name": "纯线上局",
                                            "mode": "ONLINE"}).json()
        code = r["roomCode"]
        assert {x["code"]: x["mode"] for x in client.get("/api/rooms").json()}[code] \
            == "ONLINE"
        img = client.post(f"/api/rooms/{code}/recognize",
                          files={"image": ("x.jpg", b"fake", "image/jpeg")},
                          data={"deckHint": "SMALL_DEAL"})
        assert img.status_code == 400 and img.json()["code"] == "ONLINE_NO_RECOGNIZE"
        txt = client.post(f"/api/rooms/{code}/recognize-text",
                          json={"text": "三室两厅", "deckHint": "SMALL_DEAL"})
        assert txt.status_code == 400 and txt.json()["code"] == "ONLINE_NO_RECOGNIZE"


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
        # 在线状态：没人连 WS 时全员离线（前端据此提示「接管会踢掉原设备」）
        assert seats["onlineCount"] == 0
        assert all(p["online"] is False for p in seats["players"])
        with client.websocket_connect(f"/ws?token={a['playerToken']}") as w:
            w.receive_json()
            live = client.get(f"/api/rooms/{a['roomCode']}/seats").json()
            assert live["onlineCount"] == 1
            assert {p["nickname"] for p in live["players"] if p["online"]} == {"房主"}
            assert {r["code"]: r["onlineCount"]
                    for r in client.get("/api/rooms").json()}[a["roomCode"]] == 1

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

        # 删除：未结束房间需房主令牌或密码。设了密码的房间即使没人在线也不许外人删
        r = client.request("DELETE", f"/api/rooms/{a['roomCode']}", json={})
        assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        r = client.request("DELETE", f"/api/rooms/{a['roomCode']}",
                           json={"password": "8888"})
        assert r.json() == {"ok": True}
        # 无密码房：有人在线时错密码删不掉
        with client.websocket_connect(f"/ws?token={b['playerToken']}") as w:
            w.receive_json()
            r = client.request("DELETE", f"/api/rooms/{b['roomCode']}",
                               json={"password": "随便"})
            assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        r = client.request("DELETE", f"/api/rooms/{b['roomCode']}",
                           json={"token": b["playerToken"]})
        assert r.json() == {"ok": True}
        left = {x["code"] for x in client.get("/api/rooms").json()}
        assert a["roomCode"] not in left and b["roomCode"] not in left
        r = client.get(f"/api/rooms/{a['roomCode']}/seats")
        assert r.status_code == 400 and r.json()["code"] == "NO_ROOM"


def test_orphan_lobby_room_recovery():
    """房主建了房又丢了本机令牌（清缓存/换手机）的无密码房：既能认领回座位，也能被删掉。

    这条链路曾经完全走死：等待中的房间前端只给「加入」，撞上 NICKNAME_TAKEN；
    而无密码房的删除只认房主令牌，令牌已经没了 —— 房间就永远挂在大厅里。
    """
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "谭耀辉", "name": "孤儿局"}).json()
        code = host["roomCode"]

        # 用同一个昵称加入会被引擎拦下 —— 前端据这个 code 引导去恢复座位
        r = client.post(f"/api/rooms/{code}/join", json={"nickname": "谭耀辉"})
        assert r.status_code == 400 and r.json()["code"] == "NICKNAME_TAKEN"

        # 等待中的房间同样可以认领座位（无密码房不需要口令），且房主身份完整迁移
        seats = client.get(f"/api/rooms/{code}/seats").json()
        assert seats["status"] == "LOBBY"
        seat = next(p for p in seats["players"] if p["nickname"] == "谭耀辉")
        assert seat["isHost"] is True and seat["online"] is False
        taken = client.post(f"/api/rooms/{code}/takeover", json={"playerId": seat["id"]}).json()
        assert taken["playerId"] == host["playerId"]
        assert taken["playerToken"] != host["playerToken"]
        with pytest.raises(WebSocketDisconnect) as ei:
            with client.websocket_connect(f"/ws?token={host['playerToken']}") as w:
                w.receive_json()
        assert ei.value.code == 4001

        # 新令牌就是房主：能开局，也能删房
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()
        with client.websocket_connect(f"/ws?token={taken['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json(); wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-006"); wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-010"); wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari"); wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet"); wa.receive_json()
            _act(wa, "SET_TURN_ORDER",
                 order=[taken["playerId"], guest["playerId"]]); wb.receive_json()
            st = _act(wa, "START_GAME"); wb.receive_json()
            assert st["state"]["status"] == "PLAYING"
            # 开局后就不再是「空壳房」：即便全员掉线，外人也不能删
            r = client.request("DELETE", f"/api/rooms/{code}", json={})
            assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        r = client.request("DELETE", f"/api/rooms/{code}", json={})
        assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        r = client.request("DELETE", f"/api/rooms/{code}", json={"token": taken["playerToken"]})
        assert r.json() == {"ok": True}


def test_empty_room_deletable_by_anyone():
    """没设密码、没开局、当前无人在线的房间：任何人都能在大厅里删掉。"""
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "房主", "name": "空壳局"}).json()
        code = host["roomCode"]
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as w:
            w.receive_json()
            # 有人在线：外人删不掉
            r = client.request("DELETE", f"/api/rooms/{code}", json={})
            assert r.status_code == 400 and r.json()["code"] == "FORBIDDEN"
        # 断线后（detach 走 finally，僵尸连接不会残留）：任何人可删
        assert client.get("/api/rooms/" + code + "/seats").json()["onlineCount"] == 0
        assert client.request("DELETE", f"/api/rooms/{code}", json={}).json() == {"ok": True}
        assert code not in {x["code"] for x in client.get("/api/rooms").json()}


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


def test_stock_window_end_to_end():
    """股票窗口全链路：广播摘要 → 非抽卡人买入 → 抽卡人放弃 → 仍能卖出（design/02 §6.2）。

    回归实战 bug：抽卡人点「我不买」后，全场卖出都被 NO_STOCK_WINDOW 拒绝。
    """
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

            def guest_of(st):
                return next(p for p in st["state"]["players"] if p["id"] == guest["playerId"])

            # 房主抽优先股 2BIG（buyerScope=ALL）：广播里带窗口摘要，前端据此决定给谁弹
            st = _act(wa, "DRAW_CARD", cardId="sd-001"); wb.receive_json()
            assert st["state"]["activeCard"]["stockOffer"] == {
                "symbol": "2BIG", "price": 1200, "buyerScope": "ALL"}

            # 非抽卡人按今日价买入（人人可买的卡）
            st = _act(wb, "STOCK_BUY", qty=1); wa.receive_json()
            assert guest_of(st)["cash"] == 2070 - 1200
            assert guest_of(st)["stocks"][0]["symbol"] == "2BIG"

            # 抽卡人「我不买」：只结清自己的待办，窗口摘要仍在
            st = _act(wa, "CARD_DECISION", decision="pass"); wb.receive_json()
            assert st["state"]["activeCard"]["resolved"] is True
            assert st["state"]["activeCard"]["stockOffer"]["symbol"] == "2BIG"

            # 回归点：此时其他玩家仍能卖出
            st = _act(wb, "STOCK_SELL", qty=1); wa.receive_json()
            assert guest_of(st)["cash"] == 2070
            assert guest_of(st)["stocks"] == []

            # 回合结束才关闭窗口
            st = _act(wa, "END_TURN"); wb.receive_json()
            assert st["state"]["activeCard"] is None


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


def test_log_turn_and_lobby_progress():
    """日志按轮分组用的 turn 字段（含撤销行不推进轮次）+ 大厅列表的「第几轮 · 轮到谁」。"""
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "房主", "name": "分组局"}).json()
        code = host["roomCode"]
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()

        rooms = {r["code"]: r for r in client.get("/api/rooms").json()}
        assert rooms[code]["turnCount"] == 0            # 未开局不报轮次
        assert rooms[code]["currentPlayer"] is None

        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json(); wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-006"); wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-010"); wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari"); wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet"); wa.receive_json()
            _act(wa, "SET_TURN_ORDER", order=[host["playerId"], guest["playerId"]])
            wb.receive_json()
            _act(wa, "START_GAME"); wb.receive_json()

            _act(wa, "PAYDAY"); wb.receive_json()
            _act(wa, "END_TURN"); wb.receive_json()     # 第 1 轮 · 房主结束
            _act(wb, "PAYDAY"); wa.receive_json()
            _act(wb, "END_TURN"); wa.receive_json()     # 回到首位 → 第 2 轮
            _act(wa, "PAYDAY"); wb.receive_json()

        log = client.get(f"/api/rooms/{code}/log").json()
        turns = lambda t: [e["turn"] for e in log if e["type"] == t]   # noqa: E731
        assert turns("PLAYER_JOINED") == [0, 0]         # 开局前的事件不属于任何一轮
        assert turns("GAME_STARTED") == [0]
        assert turns("TURN_ENDED") == [1, 1]            # 记的是「结束的那一轮」
        assert turns("PAYDAY") == [1, 1, 2]

        rooms = {r["code"]: r for r in client.get("/api/rooms").json()}
        assert rooms[code]["turnCount"] == 2
        assert rooms[code]["currentPlayer"] == "房主"

        # 撤销那条让轮次进位的 TURN_ENDED：之后的行退回第 1 轮（撤销行不参与重放）
        wrap = max(e["seq"] for e in log if e["type"] == "TURN_ENDED")
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa:
            wa.receive_json()
            _act(wa, "HOST_REVERT", eventSeq=wrap, reason="测试撤销")
        after = client.get(f"/api/rooms/{code}/log").json()
        assert next(e for e in after if e["seq"] == wrap)["revoked"] is True
        assert [e["turn"] for e in after if e["type"] == "PAYDAY"] == [1, 1, 1]
