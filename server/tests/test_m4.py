"""M4：自签证书生成（幂等/SAN/CA 稳定）+ 24h 房间自动归档。"""
import asyncio
import os
import time
import uuid

os.environ.setdefault("CASHFLOW_DB", os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db"))

from cryptography import x509                       # noqa: E402

from app.certs import ensure_certs                  # noqa: E402
from app.data_loader import load_library            # noqa: E402
from app.rooms import RoomManager                   # noqa: E402
from app.store.db import Database                   # noqa: E402


# ---------------- 证书 ----------------

def test_ensure_certs_idempotent_and_san(tmp_path, monkeypatch):
    monkeypatch.delenv("CASHFLOW_EXTRA_HOSTS", raising=False)
    cert_path, key_path = ensure_certs(tmp_path)
    assert cert_path.exists() and key_path.exists()
    assert (tmp_path / "ca.crt").exists() and (tmp_path / "ca.key").exists()

    leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert any(str(ip) == "127.0.0.1" for ip in san.get_values_for_type(x509.IPAddress))

    # 幂等：重复调用不重签
    before = cert_path.read_bytes()
    ensure_certs(tmp_path)
    assert cert_path.read_bytes() == before


def test_extra_hosts_reissue_leaf_keeps_ca(tmp_path, monkeypatch):
    monkeypatch.delenv("CASHFLOW_EXTRA_HOSTS", raising=False)
    cert_path, _ = ensure_certs(tmp_path)
    ca_before = (tmp_path / "ca.crt").read_bytes()
    leaf_before = cert_path.read_bytes()

    monkeypatch.setenv("CASHFLOW_EXTRA_HOSTS", "cashflow.example.com, 203.0.113.7")
    cert_path, _ = ensure_certs(tmp_path)
    assert (tmp_path / "ca.crt").read_bytes() == ca_before   # 根 CA 不变，手机无需重新信任
    assert cert_path.read_bytes() != leaf_before
    leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "cashflow.example.com" in san.get_values_for_type(x509.DNSName)
    assert any(str(ip) == "203.0.113.7" for ip in san.get_values_for_type(x509.IPAddress))


# ---------------- 归档 ----------------

async def _start_game(manager: RoomManager, code: str, host_id: str) -> str:
    """把房间推进到 PLAYING（归档测试要一个「真有内容」的对局），返回客人的 player_id。"""
    sess = manager.get(code)
    guest_id = (await manager.join_room(code, "小明"))["playerId"]
    await sess.handle_action(host_id, None, "SELECT_PROFESSION", {"professionId": "prof-006"})
    await sess.handle_action(guest_id, None, "SELECT_PROFESSION", {"professionId": "prof-010"})
    await sess.handle_action(host_id, None, "SELECT_DREAM", {"dreamId": "ft-d-safari"})
    await sess.handle_action(guest_id, None, "SELECT_DREAM", {"dreamId": "ft-d-jet"})
    await sess.handle_action(host_id, None, "SET_TURN_ORDER", {"order": [host_id, guest_id]})
    await sess.handle_action(host_id, None, "START_GAME", {})
    return guest_id


def test_archive_idle_rooms(tmp_path):
    db = Database(tmp_path / "t.db")
    manager = RoomManager(db, load_library())

    async def scenario():
        r = await manager.create_room("测试局", "房主", 6, None)
        code = r["roomCode"]
        await _start_game(manager, code, r["playerId"])
        # 未到 24h：不归档（已开局的房间不受空房短 TTL 影响）
        assert await manager.archive_idle() == {"archived": [], "deleted": []}
        assert await manager.archive_idle(now=time.time() + 2 * 3600) == \
            {"archived": [], "deleted": []}
        assert code in manager.rooms
        # 模拟 24h 无活动
        out = await manager.archive_idle(now=time.time() + 24 * 3600 + 1)
        assert out == {"archived": [code], "deleted": []}
        assert code not in manager.rooms
        row = db.find_room_by_code(code)
        assert row["status"] == "ARCHIVED"
        # 事件流保留可查
        assert db.events_for_room(row["id"])
        # 重启恢复时跳过已归档房间
        m2 = RoomManager(db, load_library())
        m2.restore_all()
        assert code not in m2.rooms

    asyncio.run(scenario())


def test_empty_lobby_room_deleted_after_1h(tmp_path):
    """建了没连上的空壳房：1h 后直接删掉，不留在大厅也不留在库里。"""
    db = Database(tmp_path / "t.db")
    manager = RoomManager(db, load_library())

    async def scenario():
        r = await manager.create_room("空壳局", "房主", 6, None)
        code = r["roomCode"]
        assert await manager.archive_idle(now=time.time() + 3000) == \
            {"archived": [], "deleted": []}
        out = await manager.archive_idle(now=time.time() + 3600 + 1)
        assert out == {"archived": [], "deleted": [code]}
        assert code not in manager.rooms
        assert db.find_room_by_code(code) is None

    asyncio.run(scenario())
