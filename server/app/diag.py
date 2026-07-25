"""运行环境自检：进程内存与容器内存上限，不引第三方依赖。

为什么需要：云端小实例（Render Free = 512MB）跑 PaddleOCR 会被 OOM 直接杀掉，
症状是请求半途断连、实例重启、SQLite 里的房间和识别统计一起清空——从外面看
和"识别不出来"长得一模一样。把内存数字摆到 /api/health 上就不用猜了。

非 Linux（开发机 Windows）各项返回 None，端点照常可用。
"""
from __future__ import annotations

from pathlib import Path

# cgroup v1 无限制时填的是一个接近 2^63 的哨兵值，不是真实上限
_NO_LIMIT = 1 << 62


def _read_first_int(path: str) -> int | None:
    try:
        text = Path(path).read_text().strip()
    except OSError:
        return None
    if text == "max":
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def rss_bytes() -> int | None:
    """当前进程常驻内存，取自 /proc/self/status 的 VmRSS（单位 kB）。"""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def cgroup_limit_bytes() -> int | None:
    """容器内存上限：先 cgroup v2，回退 v1。无限制返回 None。"""
    for path in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        val = _read_first_int(path)
        if val is not None and val < _NO_LIMIT:
            return val
    return None


def cgroup_current_bytes() -> int | None:
    """容器当前用量（含页缓存），OOM 判决看的是它逼近 limit 的程度。"""
    for path in ("/sys/fs/cgroup/memory.current",
                 "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        val = _read_first_int(path)
        if val is not None:
            return val
    return None


def _mb(val: int | None) -> int | None:
    return round(val / 1024 / 1024) if val is not None else None


def memory_report() -> dict:
    return {"rssMb": _mb(rss_bytes()),
            "limitMb": _mb(cgroup_limit_bytes()),
            "currentMb": _mb(cgroup_current_bytes())}
