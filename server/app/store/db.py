"""SQLite（WAL）存储：事件为持久化权威，room_state 只是性能缓存（design/03 §3）。"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS room(
  id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'LOBBY', settings TEXT NOT NULL DEFAULT '{}',
  password_hash TEXT, mode TEXT NOT NULL DEFAULT 'OFFLINE_ASSIST',
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS player(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES room(id),
  seat INTEGER DEFAULT 0, nickname TEXT NOT NULL,
  token_hash TEXT NOT NULL, is_host INTEGER DEFAULT 0, connected INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS event(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL REFERENCES room(id),
  seq INTEGER NOT NULL,
  actor_player_id TEXT, type TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  revoked_by INTEGER,
  UNIQUE(room_id, seq));

CREATE TABLE IF NOT EXISTS action_dedupe(
  room_id TEXT NOT NULL, action_id TEXT NOT NULL,
  result TEXT NOT NULL, PRIMARY KEY(room_id, action_id));

CREATE TABLE IF NOT EXISTS room_state(
  room_id TEXT PRIMARY KEY REFERENCES room(id),
  seq INTEGER NOT NULL, state TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS recog_stat(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, deck TEXT, engine TEXT NOT NULL,
  duration_ms INTEGER NOT NULL, n_candidates INTEGER NOT NULL,
  candidates TEXT NOT NULL DEFAULT '[]',
  chosen_card_id TEXT, hit INTEGER,
  created_at TEXT DEFAULT (datetime('now')));
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        conn = self.conn
        conn.executescript(_SCHEMA)
        # 旧库迁移：早期版本 room 表无 password_hash 列；mode 列是后加的对局模式
        # （权威仍是事件流里的 ROOM_MODE_SET，这一列只作大厅列表查询的缓存）
        for ddl in ("ALTER TABLE room ADD COLUMN password_hash TEXT",
                    "ALTER TABLE room ADD COLUMN mode TEXT NOT NULL "
                    "DEFAULT 'OFFLINE_ASSIST'"):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    # ---- room / player ----

    def create_room(self, room_id: str, code: str, name: str, settings: dict,
                    password_hash: str | None = None,
                    mode: str = "OFFLINE_ASSIST") -> None:
        self.conn.execute(
            "INSERT INTO room(id, code, name, settings, password_hash, mode) "
            "VALUES(?,?,?,?,?,?)",
            (room_id, code, name, json.dumps(settings, ensure_ascii=False),
             password_hash, mode))
        self.conn.commit()

    def delete_room(self, room_id: str) -> None:
        for table in ("action_dedupe", "room_state", "event", "player", "room"):
            key = "id" if table == "room" else "room_id"
            self.conn.execute(f"DELETE FROM {table} WHERE {key}=?", (room_id,))
        self.conn.commit()

    def find_room_by_code(self, code: str):
        return self.conn.execute("SELECT * FROM room WHERE code=?", (code,)).fetchone()

    def all_rooms(self):
        return self.conn.execute("SELECT * FROM room").fetchall()

    def set_room_status(self, room_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE room SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, room_id))
        self.conn.commit()

    def add_player(self, player_id: str, room_id: str, nickname: str,
                   token_hash: str, is_host: bool) -> None:
        self.conn.execute(
            "INSERT INTO player(id, room_id, nickname, token_hash, is_host) VALUES(?,?,?,?,?)",
            (player_id, room_id, nickname, token_hash, int(is_host)))
        self.conn.commit()

    def find_player_by_token(self, token_hash: str):
        return self.conn.execute(
            "SELECT * FROM player WHERE token_hash=?", (token_hash,)).fetchone()

    def update_player_token(self, player_id: str, token_hash: str) -> None:
        """座位接管：重发令牌，旧令牌即刻失效。"""
        self.conn.execute(
            "UPDATE player SET token_hash=? WHERE id=?", (token_hash, player_id))
        self.conn.commit()

    def set_player_host(self, player_id: str, is_host: bool) -> None:
        """房主离开大厅后转让房主：同步 DB 侧的 is_host（delete_room 的权限判断依赖它）。"""
        self.conn.execute(
            "UPDATE player SET is_host=? WHERE id=?", (int(is_host), player_id))
        self.conn.commit()

    # ---- events ----

    def append_event(self, room_id: str, seq: int, actor: str | None,
                     etype: str, payload: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO event(room_id, seq, actor_player_id, type, payload) VALUES(?,?,?,?,?)",
            (room_id, seq, actor, etype, json.dumps(payload, ensure_ascii=False)))
        self.conn.commit()
        return cur.lastrowid

    def events_for_room(self, room_id: str, include_revoked: bool = False):
        q = "SELECT * FROM event WHERE room_id=?"
        if not include_revoked:
            q += " AND revoked_by IS NULL"
        q += " ORDER BY seq"
        return self.conn.execute(q, (room_id,)).fetchall()

    def revoke_event(self, room_id: str, seq: int, revoker_event_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE event SET revoked_by=? WHERE room_id=? AND seq=? AND revoked_by IS NULL",
            (revoker_event_id, room_id, seq))
        self.conn.commit()
        return cur.rowcount > 0

    def max_seq(self, room_id: str) -> int:
        row = self.conn.execute(
            "SELECT MAX(seq) AS m FROM event WHERE room_id=?", (room_id,)).fetchone()
        return row["m"] or 0

    # ---- dedupe / snapshot ----

    def dedupe_get(self, room_id: str, action_id: str):
        return self.conn.execute(
            "SELECT result FROM action_dedupe WHERE room_id=? AND action_id=?",
            (room_id, action_id)).fetchone()

    def dedupe_put(self, room_id: str, action_id: str, result: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO action_dedupe(room_id, action_id, result) VALUES(?,?,?)",
            (room_id, action_id, result))
        self.conn.commit()

    # ---- 识别统计（FR-28） ----

    def add_recog_stat(self, room_id: str | None, deck: str | None, engine: str,
                       duration_ms: int, candidate_ids: list[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO recog_stat(room_id, deck, engine, duration_ms, n_candidates, candidates) "
            "VALUES(?,?,?,?,?,?)",
            (room_id, deck, engine, duration_ms, len(candidate_ids),
             json.dumps(candidate_ids)))
        self.conn.commit()
        return cur.lastrowid

    def set_recog_chosen(self, stat_id: int, card_id: str) -> None:
        """玩家最终确认了哪张卡：命中 = 该卡在候选 Top-3 内。"""
        row = self.conn.execute(
            "SELECT candidates FROM recog_stat WHERE id=?", (stat_id,)).fetchone()
        if row is None:
            return
        hit = int(card_id in json.loads(row["candidates"]))
        self.conn.execute(
            "UPDATE recog_stat SET chosen_card_id=?, hit=? WHERE id=?",
            (card_id, hit, stat_id))
        self.conn.commit()

    def recog_summary(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT engine, COUNT(*) AS total, AVG(duration_ms) AS avg_ms, "
            "SUM(CASE WHEN chosen_card_id IS NOT NULL THEN 1 ELSE 0 END) AS confirmed, "
            "SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) AS hits "
            "FROM recog_stat GROUP BY engine").fetchall()
        out = []
        for r in rows:
            confirmed = r["confirmed"] or 0
            out.append({
                "engine": r["engine"], "total": r["total"],
                "avgMs": round(r["avg_ms"] or 0),
                "confirmed": confirmed, "hits": r["hits"] or 0,
                "hitRate": round((r["hits"] or 0) / confirmed, 4) if confirmed else None,
            })
        return out

    def save_snapshot(self, room_id: str, seq: int, state_json: str) -> None:
        self.conn.execute(
            "INSERT INTO room_state(room_id, seq, state) VALUES(?,?,?) "
            "ON CONFLICT(room_id) DO UPDATE SET seq=excluded.seq, state=excluded.state, "
            "updated_at=datetime('now')",
            (room_id, seq, state_json))
        self.conn.commit()
