"""M3：匹配器打分、识别统计（FR-28）、本人更正（FR-29）、录入 OCR 预填接口。"""
import os
import uuid

os.environ.setdefault("CASHFLOW_DB", os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db"))

import pytest                               # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

from app.data_loader import Card, load_library          # noqa: E402
from app.main import app                    # noqa: E402
from app.recognize.matcher import match_cards, normalize, score_card  # noqa: E402


# ---------------- matcher ----------------

LIB = load_library()
SMALL = LIB.by_deck("SMALL_DEAL")


def test_normalize_fullwidth_and_commas():
    assert normalize("＄５０,０００") == "$50000"
    assert "50000" in normalize("成本 $50,000")


def test_match_realestate_by_title_and_numbers():
    text = "3室2厅 出租房\n成本 $50,000 首付 $3,000\n抵押贷款 $47,000 现金流 100"
    top = match_cards(text, SMALL)
    assert top and top[0].card_id == "sd-006"
    assert top[0].score >= 0.9


def test_match_stock_by_code():
    text = "股票 ON2U 今日价 $30 买进"
    top = match_cards(text, SMALL)
    assert top and top[0].card_id == "sd-008"


def test_match_below_floor_returns_empty():
    assert match_cards("完全无关的文字内容 abcdefg", SMALL) == []
    assert match_cards("", SMALL) == []


def test_same_title_distinguished_by_numbers():
    a = Card(id="a", deck="SMALL_DEAL", subtype="REALESTATE", title="2室1厅出租房",
             data={}, ocr_keywords=("2室1厅", "40,000", "4,000"))
    b = Card(id="b", deck="SMALL_DEAL", subtype="REALESTATE", title="2室1厅出租房",
             data={}, ocr_keywords=("2室1厅", "45,000", "5,000"))
    text = "2室1厅 出租房 成本 $45,000 首付 $5,000"
    top = match_cards(text, [a, b])
    assert top[0].card_id == "b"
    assert score_card(text, b) > score_card(text, a)


# ---------------- API：识别统计 + 本人更正 ----------------

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


def _act_err(ws, atype, **payload) -> str:
    aid = uuid.uuid4().hex
    ws.send_json({"actionId": aid, "type": atype, "payload": payload})
    while True:
        msg = ws.receive_json()
        if msg["type"] == "error" and msg.get("actionId") == aid:
            return msg["code"]
        if msg["type"] == "ack" and msg.get("actionId") == aid:
            raise AssertionError(f"{atype} 应报错却成功了")


@pytest.fixture()
def playing_room():
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "房主"}).json()
        code = host["roomCode"]
        guest = client.post(f"/api/rooms/{code}/join", json={"nickname": "小明"}).json()
        with client.websocket_connect(f"/ws?token={host['playerToken']}") as wa, \
             client.websocket_connect(f"/ws?token={guest['playerToken']}") as wb:
            wa.receive_json()
            wb.receive_json()
            _act(wa, "SELECT_PROFESSION", professionId="prof-006")
            wb.receive_json()
            _act(wb, "SELECT_PROFESSION", professionId="prof-010")
            wa.receive_json()
            _act(wa, "SELECT_DREAM", dreamId="ft-d-safari")
            wb.receive_json()
            _act(wb, "SELECT_DREAM", dreamId="ft-d-jet")
            wa.receive_json()
            _act(wa, "SET_TURN_ORDER", order=[host["playerId"], guest["playerId"]])
            wb.receive_json()
            _act(wa, "START_GAME")
            wb.receive_json()
            yield client, code, host, guest, wa, wb


def _seq_of(client, code, etype):
    rows = client.get(f"/api/rooms/{code}/log").json()
    return next(r["seq"] for r in rows if r["type"] == etype and not r["revoked"])


def test_player_correct_own_card_entry(playing_room):
    client, code, host, guest, wa, wb = playing_room
    _act(wa, "DRAW_CARD", cardId="sd-006")
    wb.receive_json()
    st = _act(wa, "CARD_DECISION", decision="buy")
    me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
    assert me["cash"] == 950
    wb.receive_json()

    seq = _seq_of(client, code, "ASSET_BOUGHT")
    # 他人不能更正我的入账
    assert _act_err(wb, "PLAYER_CORRECT", eventSeq=seq) == "NOT_YOURS"
    # 非卡牌入账类事件不允许本人更正
    started = _seq_of(client, code, "GAME_STARTED")
    assert _act_err(wa, "PLAYER_CORRECT", eventSeq=started) == "NOT_CORRECTABLE"
    # 本人更正：撤销买入，现金恢复，日志留 PLAYER_CORRECTED 痕迹
    st = _act(wa, "PLAYER_CORRECT", eventSeq=seq, reason="选错卡")
    wb.receive_json()
    me = next(p for p in st["state"]["players"] if p["id"] == host["playerId"])
    assert me["cash"] == 3950
    assert not me["realEstates"]
    rows = client.get(f"/api/rooms/{code}/log").json()
    assert any(r["type"] == "PLAYER_CORRECTED" for r in rows)
    assert next(r for r in rows if r["seq"] == seq)["revoked"]


def test_recognize_stats_roundtrip(playing_room):
    client, code, host, guest, wa, wb = playing_room
    r = client.post(f"/api/rooms/{code}/recognize",
                    files={"image": ("f.jpg", b"notimage", "image/jpeg")},
                    data={"deckHint": "SMALL_DEAL"})
    assert r.status_code == 200
    d = r.json()
    assert "recognitionId" in d and d["engine"] == "manual"
    rid = d["recognitionId"]
    assert client.post(f"/api/recognize/{rid}/chosen",
                       json={"cardId": "sd-006"}).status_code == 200
    stats = client.get("/api/stats/recognition").json()
    manual = next(s for s in stats if s["engine"] == "manual")
    assert manual["total"] >= 1 and manual["confirmed"] >= 1


def test_entry_ocr_unavailable_without_paddle(playing_room):
    client, *_ = playing_room
    import app.recognize.local_ocr as lo
    if lo.available():
        pytest.skip("本机装了 OCR 依赖，该用例只验证未安装时的行为")
    r = client.post("/api/entry/ocr",
                    files={"image": ("f.jpg", b"notimage", "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["available"] is False


# ---------------- 诊断：识别链归因 + /api/health（部署排障用） ----------------

import asyncio  # noqa: E402

from app.recognize.base import (Candidate, ManualRecognizer,  # noqa: E402
                                RecognizerChain)


class _FakeEngine:
    """可编程的假引擎：不依赖 paddle，用来驱动降级链的每条失败分支。"""

    def __init__(self, name="local", result=None, exc=None, text_len=0):
        self.name = name
        self._result = result or []
        self._exc = exc
        self.last_text_len = text_len

    async def recognize(self, image, deck_hint, lib):
        if self._exc:
            raise self._exc
        return self._result


def _run_chain(engines):
    return asyncio.run(RecognizerChain(engines).recognize(b"x", None, LIB))


def test_chain_reason_unavailable_without_local_engine():
    out = _run_chain([ManualRecognizer()])
    assert out.reason == "unavailable" and out.engine == "manual"


def test_chain_reason_timeout_is_not_swallowed():
    # 云端弱 CPU 的典型症状：以前被 except Exception 吞成"没识别到"
    out = _run_chain([_FakeEngine(exc=asyncio.TimeoutError()), ManualRecognizer()])
    assert out.reason == "timeout"


def test_chain_reason_keeps_exception_type():
    out = _run_chain([_FakeEngine(exc=MemoryError()), ManualRecognizer()])
    assert out.reason == "error:MemoryError"


def test_chain_distinguishes_no_text_from_no_match():
    assert _run_chain([_FakeEngine(), ManualRecognizer()]).reason == "no_text"
    assert _run_chain([_FakeEngine(text_len=42), ManualRecognizer()]).reason == "no_match"


def test_chain_ok_returns_candidates_and_engine():
    c = Candidate("sd-006", "3室2厅出租房", 0.9, "local")
    out = _run_chain([_FakeEngine(result=[c]), ManualRecognizer()])
    assert out.reason == "ok" and out.engine == "local" and out.candidates == [c]


def test_recognize_api_returns_reason():
    with TestClient(app) as client:
        host = client.post("/api/rooms", json={"nickname": "房主"}).json()
        d = client.post(f"/api/rooms/{host['roomCode']}/recognize",
                        files={"image": ("f.jpg", b"notimage", "image/jpeg")},
                        data={"deckHint": "SMALL_DEAL"}).json()
    # 非图片喂进去：装了 OCR 是 no_text，没装是 unavailable
    assert d["reason"] in ("no_text", "unavailable")


def test_health_reports_ocr_memory_and_db():
    with TestClient(app) as client:
        d = client.get("/api/health").json()
    assert d["uptimeS"] >= 0
    assert {"configured", "available", "engines", "warm", "timeoutS"} <= d["ocr"].keys()
    assert "manual" in d["ocr"]["engines"]
    assert d["ocr"]["warm"]["state"] in ("n/a", "skipped", "pending", "ok", "failed")
    # 内存三项在非 Linux（开发机）为 None，字段本身必须在
    assert {"rssMb", "limitMb", "currentMb"} <= d["memory"].keys()
    assert d["db"]["recogStats"] >= 0


def test_ocr_probe_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CASHFLOW_DIAG", "off")
    with TestClient(app) as client:
        assert client.post("/api/health/ocr-probe").status_code == 404


def test_ocr_probe_reports_unavailable_without_local(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(app.state, "recognizer",
                            RecognizerChain([ManualRecognizer()]))
        d = client.post("/api/health/ocr-probe").json()
    assert d["ok"] is False and d["reason"] == "unavailable"


def test_ocr_timeout_configurable(monkeypatch):
    import app.recognize.local_ocr as lo
    monkeypatch.setenv("CASHFLOW_OCR_TIMEOUT", "30")
    assert lo.timeout_s() == 30.0
    monkeypatch.setenv("CASHFLOW_OCR_TIMEOUT", "不是数字")
    assert lo.timeout_s() == lo.OCR_TIMEOUT_S


# ---------------- 录入 OCR 预填解析（prefill，纯函数） ----------------

from app.recognize.prefill import merge_rows, parse_fields  # noqa: E402


def test_merge_rows_two_column_layout():
    # 模拟"左标签右数值"两栏卡面：标签与数值 y 相同、x 不同，应并成一行
    items = [
        ("工资:", (10.0, 100.0, 60.0, 120.0)),
        ("$3,300", (200.0, 101.0, 260.0, 121.0)),
        ("税金:", (10.0, 140.0, 60.0, 160.0)),
        ("630", (200.0, 141.0, 230.0, 161.0)),
        # 乱序输入也应按 y 归位
        ("您的职业", (10.0, 20.0, 90.0, 40.0)),
        ("小学教师", (120.0, 21.0, 200.0, 41.0)),
    ]
    rows = merge_rows(items)
    assert rows == ["您的职业 小学教师", "工资: $3,300", "税金: 630"]


def test_merge_rows_empty():
    assert merge_rows([]) == []


_TEACHER_ROWS = [
    "您的职业 小学教师",
    "请将所有数据（不包括0）抄到您的游戏卡上",
    "目标：使您的非工资收入大于总支出",
    "收入",
    "工资: $3,300 利息: 0",
    "股利: 0 非工资收入: 0",
    "房地产 0",
    "（非工资收入=利息+股利+房地产/企业）",
    "总收入: $3,300",
    "支出",
    "税金: 630",
    "住房抵押贷款/房租: 500",
    "教育贷款: 60 购车贷款: 100",
    "信用卡支出: 90 额外支出:",
    "每个孩子支出: $180",
    "其他支出: 760",
    "总支出: 2,190",
    "资产",
    "储蓄: $400",
    "负债",
    "住房抵押贷款: $38,000",
    "教育贷款: $12,000",
    "购车贷款: $5,000",
    "信用卡: $3,000",
]


def test_parse_profession_card():
    d = parse_fields(_TEACHER_ROWS, "PROFESSION", "PROFESSION")
    assert d["title"] == "小学教师"
    assert d["subtype"] == "PROFESSION"
    f = d["fields"]
    assert f["salary"] == 3300
    assert f["taxes"] == 630
    assert f["mortgagePayment"] == 500
    assert f["schoolLoanPayment"] == 60
    assert f["carLoanPayment"] == 100
    assert f["creditCardPayment"] == 90
    assert f["otherExpenses"] == 760
    assert f["perChildExpense"] == 180
    assert f["savings"] == 400
    assert f["liabilities.mortgage"] == 38000
    assert f["liabilities.schoolLoan"] == 12000
    assert f["liabilities.carLoan"] == 5000
    assert f["liabilities.creditCard"] == 3000
    # "非工资收入: 0"不得污染工资；额外支出无数值不应出现
    assert "extraExpenses" not in f


def test_parse_profession_without_section_headers():
    # OCR 漏掉"支出/负债"区段头：同名标签第一次归支出、第二次归负债
    rows = [r for r in _TEACHER_ROWS if r not in ("收入", "支出", "资产", "负债")]
    f = parse_fields(rows, "PROFESSION", "PROFESSION")["fields"]
    assert f["mortgagePayment"] == 500
    assert f["liabilities.mortgage"] == 38000
    assert f["schoolLoanPayment"] == 60
    assert f["liabilities.schoolLoan"] == 12000


def test_parse_profession_two_column_bottom_block():
    # 实拍经理卡：底部"资产/负债"左右两栏并排，区段头并成一行、数值行混排，
    # 区段追踪失效时靠"支出键已填→兜底负债键"归位（docs/职业卡片.jfif 布局）
    rows = [
        "您的职业",
        "经理",
        "请将所有数据（不包括0）抄到您的游戏卡上",
        "目标：使您的非工资收入大于总支出",
        "收入",
        "工资: $4,600",
        "利息: 0 非工资收入: 0",
        "股利: 0",
        "房地产: 0 总收入: $4,600",
        "支出",
        "税金: 910",
        "住房抵押贷款/房租: 700",
        "教育贷款: 60",
        "购车贷款: 120",
        "信用卡支出: 90 每个孩子支出: $240",
        "额外支出: 50",
        "其他支出: 1,000 总支出: $2,930",
        "孩子支出: 0",
        "月现金流: $1,670",
        "资产 负债",
        "住房抵押贷款: 75,000",
        "教育贷款: 12,000",
        "储蓄: $400 购车贷款: 7,000",
        "信用卡: 4,000",
        "额外负债: 1,000",
    ]
    d = parse_fields(rows, "PROFESSION", "PROFESSION")
    assert d["title"] == "经理"
    f = d["fields"]
    assert f["salary"] == 4600
    assert f["taxes"] == 910
    assert f["mortgagePayment"] == 700
    assert f["schoolLoanPayment"] == 60
    assert f["carLoanPayment"] == 120
    assert f["creditCardPayment"] == 90
    assert f["extraExpenses"] == 50
    assert f["otherExpenses"] == 1000
    assert f["perChildExpense"] == 240   # "孩子支出: 0"在后，不得覆盖
    assert f["savings"] == 400
    assert f["liabilities.mortgage"] == 75000
    assert f["liabilities.schoolLoan"] == 12000
    assert f["liabilities.carLoan"] == 7000
    assert f["liabilities.creditCard"] == 4000
    assert f["liabilities.extra"] == 1000


def test_parse_realestate_card():
    rows = [
        "3室2厅出租房",
        "屋主急售，价格低于市场价",
        "成本: $50,000 首期支付: $3,000",
        "抵押贷款: $47,000",
        "现金流: $100",
        "交易范围 $65,000-$135,000",
    ]
    d = parse_fields(rows, "SMALL_DEAL", "REALESTATE")
    assert d["subtype"] == "REALESTATE"
    assert d["title"] == "3室2厅出租房"
    f = d["fields"]
    assert f["cost"] == 50000
    assert f["downPayment"] == 3000
    assert f["mortgage"] == 47000
    assert f["cashflow"] == 100
    assert f["priceRange.0"] == 65000
    assert f["priceRange.1"] == 135000


def test_parse_realestate_inline_pct_and_range():
    # 实拍"待售公寓 2室1厅"真实 OCR 行序：收益率"42%"数字在标签前、价格区间
    # 跨两行、资产类型藏在标题——回归"收益率误抓卖价45000"的 bug
    rows = [
        "待售公寓 —2室1厅",
        "有父母准备出售上大学的孩子原来居住的",
        "公寓。该地区房屋出租率很高。可以自己接受",
        "这笔生意，也可以卖给其他玩家。",
        "42%的投资收益率，可以卖$45，000",
        "~$65,000。",
        "成本：$40,000 抵押贷款：$36,000",
        "首期支付：$4,000 月现金流：+$140",
    ]
    f = parse_fields(rows, "SMALL_DEAL", "REALESTATE")["fields"]
    assert f["cost"] == 40000
    assert f["downPayment"] == 4000
    assert f["mortgage"] == 36000
    assert f["cashflow"] == 140
    assert f["assetType"] == "2室1厅"
    assert f["roiPct"] == 42          # 不得是卖价 45000
    assert f["priceRange.0"] == 45000
    assert f["priceRange.1"] == 65000


def test_parse_realestate_land():
    # 土地卡卡面无"N室N厅"资产标注，assetType 统一识别为"土地"（售价不能确定，无价格区间）
    rows = [
        "20英亩土地待售",
        "20英亩空地待售，已被规划为住宅区。",
        "如果开发成商业区将是很好的投资机会。",
        "可以自己接受这笔生意，也可以卖给其他玩家。",
        "投资收益率为0%，售价不能确定。",
        "成本：$20,000 抵押贷款：$0",
        "首期支付：$20,000 月现金流：$0",
    ]
    f = parse_fields(rows, "BIG_DEAL", "REALESTATE")["fields"]
    assert f["assetType"] == "土地"
    assert f["cost"] == 20000
    assert f["downPayment"] == 20000
    assert f["mortgage"] == 0
    assert f["cashflow"] == 0
    assert "priceRange.0" not in f


def test_parse_detects_stock_subtype_in_small_deal():
    rows = [
        "OK4U 基金",
        "今日价格: $20",
        "每股红利: $1",
        "交易范围 $10-$30",
    ]
    # 请求带的是 REALESTATE，命中更多的 STOCK_OFFER 应胜出
    d = parse_fields(rows, "SMALL_DEAL", "REALESTATE")
    assert d["subtype"] == "STOCK_OFFER"
    f = d["fields"]
    assert f["price"] == 20
    assert f["dividendPerShare"] == 1
    assert f["symbol"] == "OK4U"
    assert f["priceRange.0"] == 10
    assert f["priceRange.1"] == 30


def test_parse_no_fields_keeps_requested_subtype():
    d = parse_fields(["完全无关的一段文字"], "SMALL_DEAL", "EXPENSE_EVENT")
    assert d["subtype"] == "EXPENSE_EVENT"
    assert d["fields"] == {}


def test_parse_preferred_stock_dividend_alias():
    # 优先股卡面写"分红"（非"红利"），别名须命中并识别为每股月分红
    rows = [
        "优先股 2BIG电力公司",
        "股票代码: 2BIG",
        "今日价格: $1,200",
        "分红: $10/月",
        "投资收益率: 10%",
        "价格范围 $1,200~$1,200",
    ]
    d = parse_fields(rows, "SMALL_DEAL", "STOCK_OFFER")
    assert d["subtype"] == "STOCK_OFFER"
    f = d["fields"]
    assert f["symbol"] == "2BIG"
    assert f["price"] == 1200
    assert f["dividendPerShare"] == 10
