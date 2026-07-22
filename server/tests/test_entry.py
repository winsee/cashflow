"""录入工具：录入库与运行时库分离、去重、自动 id、priceRange、清空、发布。"""
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("CASHFLOW_DB", os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db"))

from fastapi.testclient import TestClient   # noqa: E402

from app import data_loader, main as app_main  # noqa: E402
from app.data_loader import DataValidationError, load_library  # noqa: E402
from app.main import app                    # noqa: E402

SRC_DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    """server/data 拷到临时目录并定向 DATA_DIR，测完恢复（不碰真实数据文件）；
    每个用例用独立空 DB，避免其他测试模块留下的房间事件在 startup 被重放。"""
    dst = tmp_path / "data"
    shutil.copytree(SRC_DATA, dst)
    shutil.rmtree(dst / "entry", ignore_errors=True)   # 录入库从运行时库重新播种
    monkeypatch.setattr(app_main, "DB_PATH", str(tmp_path / "entry-test.db"))
    old = data_loader.DATA_DIR
    data_loader.DATA_DIR = dst
    yield dst
    data_loader.DATA_DIR = old


def _entry_json(dst: Path, name: str) -> list[dict]:
    return json.loads((dst / "entry" / "cards" / name).read_text(encoding="utf-8"))


def _runtime_json(dst: Path, name: str) -> list[dict]:
    return json.loads((dst / "cards" / name).read_text(encoding="utf-8"))


def _card(cid, title, amount=100, keywords=None, key=None, duplicate_of=None):
    """构造一张 v3 形态的卡（key/source/raw 是 schema v3 的必填字段）。"""
    c = {"id": cid, "key": key or cid, "deck": "DOODAD", "subtype": "CASH",
         "title": title, "data": {"amount": amount},
         "source": {"sheetNo": int(cid.rpartition("-")[2]), "image": ""},
         "raw": {"title": title}}
    if keywords:
        c["ocr_keywords"] = keywords
    if duplicate_of:
        c["duplicateOf"] = duplicate_of
    return c


def _write_doodad(dst: Path, cards: list[dict]):
    (dst / "cards" / "doodad.json").write_text(
        json.dumps(cards, ensure_ascii=False), encoding="utf-8")


# ---------------- 加载层去重（运行时库启动校验） ----------------

def test_loader_accepts_tagged_deck_duplicates(tmp_data):
    """实体牌堆本来就有 9 组共 20 张完全相同的卡，按实际张数入库才不改抽牌概率。

    合法形态 = 共用 key + 第 2 张起 duplicateOf 指向首张（design/06 §5）。
    """
    _write_doodad(tmp_data, [
        _card("dd-901", "买游艇", 17000, ["游艇"], key="boat-17k"),
        _card("dd-902", "买游艇", 17000, ["游艇"], key="boat-17k", duplicate_of="dd-901"),
    ])
    lib = load_library(tmp_data)
    assert {"dd-901", "dd-902"} <= set(lib.cards)          # 两张都在，不去重
    assert lib.cards["dd-902"].duplicate_of == "dd-901"
    assert lib.cards["dd-901"].key == lib.cards["dd-902"].key


def test_loader_rejects_untagged_duplicate(tmp_data):
    """同 key 同数值却没标 duplicateOf = 真·录入重复，仍要拦。"""
    _write_doodad(tmp_data, [
        _card("dd-901", "买游艇", 17000, key="boat-17k"),
        _card("dd-902", "买游艇", 17000, key="boat-17k"),
    ])
    with pytest.raises(DataValidationError, match="duplicateOf"):
        load_library(tmp_data)


def test_loader_rejects_same_key_diff_data(tmp_data):
    """共用 key 表示同内容；数值不同却共用 key 会让重复卡归组失真。"""
    _write_doodad(tmp_data, [
        _card("dd-901", "买游艇", 17000, key="boat"),
        _card("dd-902", "买游艇", 25000, key="boat"),
    ])
    with pytest.raises(DataValidationError, match="数值不一致"):
        load_library(tmp_data)


def test_loader_same_title_diff_data_requires_keywords(tmp_data):
    _write_doodad(tmp_data, [_card("dd-901", "买游艇", 17000),
                             _card("dd-902", "买游艇", 25000)])
    with pytest.raises(DataValidationError, match="区分关键词"):
        load_library(tmp_data)
    _write_doodad(tmp_data, [
        _card("dd-901", "买游艇", 17000, ["17,000"]),
        _card("dd-902", "买游艇", 25000, ["25,000"]),
    ])
    lib = load_library(tmp_data)
    assert lib.cards["dd-901"].title == lib.cards["dd-902"].title


def test_loader_rejects_duplicate_id_across_decks(tmp_data):
    _write_doodad(tmp_data, [_card("mk-003", "某支出", 100)])
    with pytest.raises(DataValidationError, match="id 重复"):
        load_library(tmp_data)


def test_loader_ok_with_all_decks_empty(tmp_data):
    for rel in data_loader.CARD_FILES.values():
        (tmp_data / rel).write_text("[]", encoding="utf-8")
    lib = load_library(tmp_data)
    assert lib.cards == {}


# ---------------- 录入库接口 ----------------

def _post(client, **kw):
    # 金额取真实牌叠里没有的值：录入库播种自 194 张全量库，撞上会被重复卡护栏拦下
    body = {"id": "", "deck": "DOODAD", "subtype": "CASH",
            "title": "测试卡", "data": {"amount": 12345}, "ocr_keywords": []}
    body.update(kw)
    return client.post("/api/entry/cards", json=body)


def test_staging_seeded_from_runtime(tmp_data):
    with TestClient(app) as client:
        cards = client.get("/api/entry/cards", params={"deck": "DOODAD"}).json()
        assert {c["id"] for c in cards} == {c["id"] for c in _runtime_json(tmp_data, "doodad.json")}


def test_api_auto_id_and_dup_rejection(tmp_data):
    with TestClient(app) as client:
        r1 = _post(client, title="新支出A", data={"amount": 12300})
        assert r1.status_code == 200
        id1 = r1.json()["id"]
        assert id1.startswith("dd-") and id1.split("-")[1].isdigit()

        r2 = _post(client, title="新支出B", data={"amount": 12400})
        id2 = r2.json()["id"]
        assert id2 != id1

        # 数值全同又没标 duplicateOf → 当作录入重复拒绝，录入库不变
        before = _entry_json(tmp_data, "doodad.json")
        r3 = _post(client, title="新支出A", data={"amount": 12300})
        assert r3.status_code == 400
        assert "重复卡" in r3.json()["message"]
        assert _entry_json(tmp_data, "doodad.json") == before

        # 同 id 重复提交 = 编辑，不误判为重复卡
        r4 = _post(client, id=id1, title="新支出A", data={"amount": 12300})
        assert r4.status_code == 200
        assert r4.json()["replaced"] is True

        # 录入只写录入库，运行时库不动
        assert not any(c["id"] == id1 for c in _runtime_json(tmp_data, "doodad.json"))


def test_api_same_title_multiversion_needs_keywords(tmp_data):
    with TestClient(app) as client:
        r1 = _post(client, title="买游艇2", data={"amount": 17000})
        assert r1.status_code == 200
        # 第二张同名不同值：现存那张没关键词 → 拒绝
        r2 = _post(client, title="买游艇2", data={"amount": 25000}, ocr_keywords=["25,000"])
        assert r2.status_code == 400
        assert "区分关键词" in r2.json()["message"]
        # 给第一张补关键词后，第二张可入库
        r3 = _post(client, id=r1.json()["id"], title="买游艇2",
                   data={"amount": 17000}, ocr_keywords=["17,000"])
        assert r3.status_code == 200
        r4 = _post(client, title="买游艇2", data={"amount": 25000}, ocr_keywords=["25,000"])
        assert r4.status_code == 200


def test_api_rejects_id_used_by_other_deck(tmp_data):
    with TestClient(app) as client:
        r = _post(client, id="dd-001", deck="MARKET", subtype="BUYER_OFFER",
                  title="求购", data={"targetAssetType": "3室2厅",
                                     "priceBasis": "PER_UNIT", "price": 65000})
        assert r.status_code == 400
        assert "占用" in r.json()["message"]


def test_api_price_range(tmp_data):
    with TestClient(app) as client:
        stock = {"symbol": "OK4U", "price": 20, "dividendPerShare": 0,
                 "roiPct": 0, "buyerScope": "DRAWER_ONLY", "priceRange": [30, 5]}
        r1 = _post(client, deck="SMALL_DEAL", subtype="STOCK_OFFER",
                   title="OK4U 20元", data=stock)
        assert r1.status_code == 400
        assert "价格区间" in r1.json()["message"]

        stock["priceRange"] = [5, 30]
        r2 = _post(client, deck="SMALL_DEAL", subtype="STOCK_OFFER",
                   title="OK4U 20元", data=stock)
        assert r2.status_code == 200
        saved = next(c for c in _entry_json(tmp_data, "small_deal.json")
                     if c["id"] == r2.json()["id"])
        assert saved["data"]["priceRange"] == [5, 30]


def test_api_clear_deck_only_touches_staging(tmp_data):
    with TestClient(app) as client:
        runtime_before = _runtime_json(tmp_data, "doodad.json")
        r = client.delete("/api/entry/decks/DOODAD")
        assert r.status_code == 200
        assert _entry_json(tmp_data, "doodad.json") == []
        s = client.get("/api/entry/stats").json()["DOODAD"]
        assert s["entry"] == 0 and s["runtime"] == len(runtime_before)
        assert _runtime_json(tmp_data, "doodad.json") == runtime_before
        # 清空后继续录入正常；全部叠清空也安全
        assert _post(client, title="清空后的第一张").status_code == 200
        for deck in data_loader.CARD_FILES:
            assert client.delete(f"/api/entry/decks/{deck}").status_code == 200
        assert all(v["entry"] == 0 for v in client.get("/api/entry/stats").json().values())


def test_api_delete_card(tmp_data):
    with TestClient(app) as client:
        cid = _post(client, title="待删卡").json()["id"]
        assert client.delete(f"/api/entry/cards/{cid}").status_code == 200
        assert client.delete(f"/api/entry/cards/{cid}").status_code == 400


# ---------------- 发布 ----------------

def test_publish_flow(tmp_data):
    with TestClient(app) as client:
        cid = _post(client, title="发布测试卡", data={"amount": 999}).json()["id"]
        pv = client.get("/api/entry/publish/preview")
        assert pv.status_code == 200
        assert cid in pv.json()["diff"]["DOODAD"]["added"]

        r = client.post("/api/entry/publish")
        assert r.status_code == 200
        assert cid in r.json()["diff"]["DOODAD"]["added"]
        # 运行时库文件已更新、热重载生效（游戏接口可见）
        assert any(c["id"] == cid for c in _runtime_json(tmp_data, "doodad.json"))
        assert any(c["id"] == cid for c in client.get("/api/cards", params={"deck": "DOODAD"}).json())
        s = client.get("/api/entry/stats").json()["DOODAD"]
        assert s["entry"] == s["runtime"]
        # 再发布一次：无差异
        r2 = client.post("/api/entry/publish")
        assert r2.json()["diff"]["DOODAD"] == {"added": [], "removed": [], "changed": []}


def test_publish_rejects_invalid_staging_and_keeps_runtime(tmp_data):
    with TestClient(app) as client:
        client.get("/api/entry/cards", params={"deck": "DOODAD"})   # 触发播种
        runtime_before = _runtime_json(tmp_data, "doodad.json")
        # 直接把录入库文件改坏（模拟手工编辑出错）：同 key 同数值却没标 duplicateOf
        (tmp_data / "entry" / "cards" / "doodad.json").write_text(
            json.dumps([_card("dd-901", "坏卡", 1, key="bad"),
                        _card("dd-902", "坏卡", 1, key="bad")],
                       ensure_ascii=False), encoding="utf-8")
        for path in ("/api/entry/publish/preview",):
            assert client.get(path).status_code == 400
        assert client.post("/api/entry/publish").status_code == 400
        assert _runtime_json(tmp_data, "doodad.json") == runtime_before
