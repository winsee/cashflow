# 现金流游戏辅助工具（Cashflow Companion）

把纸质《富爸爸现金流》桌游做成线上辅助工具：实体棋盘/骰子/卡牌照常线下玩，每人手机开网页完成选卡录入、自动记账、全员状态同步。记账全部由服务端计算，玩家现金显示在手机的"银行储蓄"栏，不需要实体现金。

设计文档见 [design/](design/)（[00-文档索引](design/00-文档索引.md) 是总入口，[02-游戏规则引擎规格](design/02-游戏规则引擎规格.md) 是规则的唯一权威）。

## 功能

- **房间与对局**：建房/加入/断线重连、回合流程、老鼠赛跑全部记账（薪资、资产负债、市场/机会/大小生意/出局卡）、总览面板、可回溯的操作日志
- **快车道**：切入判定、被动收入投资、破产处理、玩家间交易需双方确认、房主可撤销改账
- **卡牌识别（可选）**：手机对准卡面自动连续识别（本地 PaddleOCR，封闭集匹配，只用来定位"是哪张卡"，数值一律取自卡库）；未装 OCR 或识别失败自动降级为系统相机拍照/手动检索，功能等价；`/api/stats/recognition` 可查各引擎命中率与耗时；选错卡可在日志页「更正」，全程留痕
- **194 张实体卡数字化**：市场/大小生意/出局卡/职业卡按官方牌堆真实张数与数值入库，`server/data/cards/`，规则引擎按 [design/02](design/02-游戏规则引擎规格.md) 全量测试驱动（`server/app/engine/tests`，391 passed / 1 skipped，含说明书数值回归与整卡库逐卡扫描）
- **说明书查看**：App 内 `📖 说明书` 直接翻阅扫描页，不用线下翻纸质说明书
- **单镜像交付**：Docker 镜像内嵌前端静态资源，只跑 HTTP 8000；云端由反向代理终止 TLS（真实证书），玩家直接 `https://<域名>` 访问，扫描识别（getUserMedia）在真实 HTTPS 下即可用。云端房间 24 小时无活动自动归档

## 快速开始

本地跑起来（构建当前代码并启动），浏览器打开 `http://localhost:8000`：

```powershell
docker compose up -d --build
```

异地开黑用云主机部署见下方「Docker 部署」。

## 本地开发

```powershell
# 后端（端口 8000，热重载：改动 app/ 下代码自动重启）
# 首次建 venv：uv venv --python 3.12 .venv && uv pip install -e .[dev]
# 本地 OCR 可选：uv pip install -e .[ocr]，未安装时识别自动降级为手动选卡
cd server
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
# 或 HTTP+HTTPS 双端口（扫描框需要 HTTPS；双端口启动器不支持热重载）：
.venv\Scripts\python.exe -m app.serve

# 前端热更新开发（可选，端口 5173，已配置代理到 8000；只有要改前端代码时才需要）
cd web
npm install
npm run dev

# 前端构建（构建后后端 8000 端口直接服务 web/dist，手机访问 http://<局域网IP>:8000 即可，不需要单独跑 5173）
npm run build

# 跑测试
cd server
.venv\Scripts\python.exe -m pytest
```

## Docker 部署

镜像发布在 GitHub Packages：打 `v*` tag（或在 Actions 手动触发 `publish-image`）会自动构建含本地 OCR 的完整镜像并推送到 `ghcr.io/winsee2017/cashflow`（`.github/workflows/publish-image.yml`）。

**本地**（构建当前代码并启动，改完即测）：

```powershell
docker compose up -d --build
```

**云端**（不用 compose，直接 `docker run` 拉取 ghcr 镜像；TLS 交给反向代理）：

```bash
docker login ghcr.io                       # 首次：用户名 winsee2017 + PAT(勾 read:packages)；把包设为 public 则可免登录
docker pull ghcr.io/winsee2017/cashflow:latest
docker run -d --name cashflow \
  -e CASHFLOW_HTTPS=off \
  -p 127.0.0.1:8000:8000 \                  # 反代与容器不同机时改为 -p 8000:8000
  -v cashflow-data:/data \
  --restart unless-stopped \
  ghcr.io/winsee2017/cashflow:latest
```

云端由反向代理（nginx/caddy 等）持有真实证书，把 443 转发到 `127.0.0.1:8000`，玩家直接访问 `https://<域名>`，扫描识别在真实 HTTPS 下即可用，无需自签证书或 `/trust`。镜像默认内置本地 OCR 与模型（离线可用，约 2GB）；不需要 OCR 时 `docker build --build-arg WITH_OCR=0` 得到精简镜像。云端房间 24 小时无活动自动归档（事件流留在数据库里可导出查账，但不再可加入）。

## 卡牌录入（录入库与运行时库分离）

- **录入库** `server/data/entry/cards/*.json`：录入工具（`/#/entry`）的纯数据记录，随录随存，怎么改都不影响对局；id 自动生成；同叠内「标题+数值全同」判定为重复卡拒绝入库，同名多版本卡须每张填区分关键词
- **运行时库** `server/data/cards/*.json`：游戏引擎/识别实际使用的数据，仅在录入页点「🚀 发布」（校验整库 → 拷贝 → 热重载，失败自动回滚）时更新；也可手动把 entry 下文件拷到 cards 下重启服务
- 两库均进 git；核对工具（`/#/entry/review`）提供逐张翻页核对与全字段清单，用于录完后与实体卡对数值
- 改完卡库务必跑 `python tools/validate_cards.py`（schema + 恒等式 + 张数对账 + 资产↔求购卡交叉检查）

## 说明书查看

把说明书扫描页图片（按页码命名的 PNG/JPG）放入 `server/manual_pages/`，App 内 `📖 说明书` 即可翻阅。该目录随仓库入库、随 Docker 镜像交付，远程部署无需额外拷贝。

## 目录结构

```
server/app/engine/    规则引擎（纯函数，事件溯源）＋全量测试
server/app/store/     SQLite 事件存储
server/app/recognize/ 识别适配层（本地 PaddleOCR + 封闭集匹配）
server/data/          卡牌/棋盘 JSON —— 权威数据源，人工可改，进 git
server/manual_pages/  说明书扫描页图片，App 内「📖 说明书」直接翻阅
web/                  Vue3 + Vite + TS + Pinia（手机端 PWA）
Dockerfile            单镜像构建（前端内嵌，默认含本地 OCR）
docker-compose.yaml   本地构建 + 启动（云端用 docker run，见「Docker 部署」）
.github/workflows/    publish-image：打 tag 自动构建并推送镜像到 ghcr.io
design/               设计文档（需求、规则引擎规格、架构、卡库设计）
tools/                卡库校验、说明书渲染等命令行工具
```
