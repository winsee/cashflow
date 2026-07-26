"""说明书分页接口（FR-31）：列表排序、取图、目录穿越防护。"""
import os
import uuid

os.environ["CASHFLOW_DB"] = os.path.join(
    os.environ.get("TEMP", "/tmp"), f"cashflow-test-{uuid.uuid4().hex}.db")

import pytest                               # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

from app import main                        # noqa: E402
from app.main import app                    # noqa: E402


@pytest.fixture
def manual_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_DIR", tmp_path)
    return tmp_path


def test_pages_sorted_and_filtered(manual_dir):
    # 乱序写入，且混一个非图片文件（tools/build_manual_pages.py 会留 .gitkeep）
    for name in ("p03.webp", "p01.webp", "p02.webp", ".gitkeep", "notes.txt"):
        (manual_dir / name).write_bytes(b"x")
    with TestClient(app) as client:
        r = client.get("/api/manual/pages")
        assert r.status_code == 200
        # 零填充命名保证字典序 == 页序
        assert r.json()["pages"] == ["p01.webp", "p02.webp", "p03.webp"]


def test_pages_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_DIR", tmp_path / "nope")
    with TestClient(app) as client:
        assert client.get("/api/manual/pages").json() == {"pages": []}


def test_fetch_page_is_long_cached(manual_dir):
    (manual_dir / "p01.webp").write_bytes(b"fake-webp-bytes")
    with TestClient(app) as client:
        r = client.get("/api/manual/pages/p01.webp")
        assert r.status_code == 200
        assert r.content == b"fake-webp-bytes"
        assert "immutable" in r.headers["cache-control"]
        # Windows 的 mimetypes 不认 .webp，必须由代码显式给出，否则是 octet-stream
        assert r.headers["content-type"] == "image/webp"


def test_unknown_page_404(manual_dir):
    with TestClient(app) as client:
        assert client.get("/api/manual/pages/p99.webp").status_code == 404


def test_path_traversal_blocked(manual_dir, tmp_path):
    (tmp_path.parent / "secret.txt").write_bytes(b"top secret")
    with TestClient(app) as client:
        # Path(name).name 只留文件名，跳不出 MANUAL_DIR
        r = client.get("/api/manual/pages/..%2Fsecret.txt")
        assert r.status_code == 404
        assert b"top secret" not in r.content


def test_shipped_pages_present():
    """仓库里应带着 build_manual_pages.py 的产物，否则线上 /manual 是空的。"""
    with TestClient(app) as client:
        pages = client.get("/api/manual/pages").json()["pages"]
        assert pages, "server/manual_pages/ 为空，请跑 python tools/build_manual_pages.py"
        assert pages[0] == "p01.webp"
