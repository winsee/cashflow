"""双端口启动器（design/03 §7）：HTTP 8000（零配置兜底）+ HTTPS 8443（扫描框用）。

两个 uvicorn Server 跑在同一进程、同一事件循环上，共享同一个 app 与房间状态
（main.lifespan 已做幂等保护）。证书首次启动自动生成（app/certs.py），手机按
/trust 页引导一次性信任根证书即可用扫描识别。

用法：python -m app.serve
环境变量：CASHFLOW_HTTP_PORT(8000) / CASHFLOW_HTTPS_PORT(8443) /
         CASHFLOW_HTTPS=off 关闭 HTTPS / CASHFLOW_EXTRA_HOSTS 追加证书域名或公网 IP
"""
from __future__ import annotations

import asyncio
import os

import uvicorn

from .certs import ensure_certs, lan_ips
from .main import app, cert_dir


async def _run() -> None:
    http_port = int(os.environ.get("CASHFLOW_HTTP_PORT", "8000"))
    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=http_port))]

    https_port = int(os.environ.get("CASHFLOW_HTTPS_PORT", "8443"))
    if os.environ.get("CASHFLOW_HTTPS", "on") != "off":
        cert, key = ensure_certs(cert_dir())
        servers.append(uvicorn.Server(uvicorn.Config(
            app, host="0.0.0.0", port=https_port,
            ssl_certfile=str(cert), ssl_keyfile=str(key))))
        for ip in lan_ips() or ["<本机IP>"]:
            print(f"  手机访问: http://{ip}:{http_port}  |  "
                  f"扫描识别: https://{ip}:{https_port} （首次先开 /trust 信任证书）")
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
