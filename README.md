# 现金流游戏辅助工具（Cashflow Companion）

把纸质《富爸爸现金流》桌游做成线上辅助工具：实体棋盘/骰子/卡牌照常线下玩，每人手机开网页完成选卡录入、自动记账、全员状态同步。记账全部由服务端计算，玩家现金显示在手机的"银行储蓄"栏，不需要实体现金。

设计文档见 [design/](design/)（[00-文档索引](design/00-文档索引.md) 是总入口，[02-游戏规则引擎规格](design/02-游戏规则引擎规格.md) 是规则的唯一权威）。

## 功能

- **房间与对局**：建房/加入/断线重连、回合流程、老鼠赛跑全部记账（薪资、资产负债、市场/机会/大小生意/出局卡）、总览面板、可回溯的操作日志。换了手机或清了缓存也能在大厅点回自己的座位恢复身份（有密码的房间凭口令）
- **快车道**：切入判定、被动收入投资、破产处理、玩家间交易需双方确认、房主可撤销改账
- **卡牌识别**：手机对准卡面自动连续识别，**OCR 在手机浏览器里跑**（tesseract.js + WASM），服务端只做封闭集匹配——只用来定位"是哪张卡"，数值一律取自卡库，玩家点选确认才入账。服务端零 OCR 内存开销，小内存云主机也能用（详见「识别在手机上跑」）；`/api/stats/recognition` 可查各引擎命中率与耗时；选错卡可在日志页「更正」，全程留痕
- **194 张实体卡数字化**：市场/大小生意/出局卡/职业卡按官方牌堆真实张数与数值入库，`server/data/cards/`，规则引擎按 [design/02](design/02-游戏规则引擎规格.md) 全量测试驱动（`server/app/engine/tests` 357 条，含说明书数值回归与整卡库逐卡扫描；连同接口测试全量 419 passed / 1 skipped）
- **说明书查看**：App 内 `📖 说明书` 直接翻阅扫描页，不用线下翻纸质说明书
- **单镜像交付**：Docker 镜像内嵌前端静态资源（压缩后 ~60MB），只跑 HTTP 8000；云端由反向代理终止 TLS（真实证书），玩家直接 `https://<域名>` 访问。房间 24 小时无活动自动归档；建了没人进的空房间 1 小时后自动清掉

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

镜像同时发布在两处，内容完全一致（同一 digest），按拉取方便挑一个即可：

- Docker Hub：`winsee2017/cashflow`（免登录直接拉）
- GitHub Packages：`ghcr.io/winsee2017/cashflow`

打 `v*` tag（或在 Actions 手动触发 `publish-image`）会自动构建镜像并推送到这两处（`.github/workflows/publish-image.yml`）。推 Docker Hub 需要在仓库 Settings → Secrets 里配 `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN`（Docker Hub 的 Access Token，权限 Read & Write）；没配时 workflow 自动跳过 Docker Hub，只推 ghcr。

本机手动推一版（不走 CI）：

```powershell
docker build -t winsee2017/cashflow:latest -t winsee2017/cashflow:0.1.0 .
docker push winsee2017/cashflow:latest
docker push winsee2017/cashflow:0.1.0
```

**本地**（构建当前代码并启动，改完即测）：

```powershell
docker compose up -d --build
```

**云端**（不用 compose，直接 `docker run` 拉镜像；TLS 交给反向代理）：

```bash
docker pull winsee2017/cashflow:latest     # 或 ghcr.io/winsee2017/cashflow:latest
docker run -d --name cashflow \
  -p 127.0.0.1:8000:8000 \                  # 反代与容器不同机时改为 -p 8000:8000
  -v cashflow-data:/data \
  --restart unless-stopped \
  winsee2017/cashflow:latest
```

镜像默认 `CASHFLOW_HTTPS=off`（只跑 HTTP 8000，TLS 由反代终止），不需要额外传环境变量；要让容器自己起自签 HTTPS 才需 `-e CASHFLOW_HTTPS=on -p 8443:8443`。

拉 ghcr 上的私有包需先 `docker login ghcr.io`（用户名 winsee2017 + PAT，勾 `read:packages`）；把包设为 public 或改用 Docker Hub 则免登录。

云端由反向代理（nginx/caddy 等）持有真实证书，把 443 转发到 `127.0.0.1:8000`，玩家直接访问 `https://<域名>`，无需自签证书或 `/trust`。云端房间 24 小时无活动自动归档（事件流留在数据库里可导出查账，但不再可加入）；从未开局又无人在线的空房间 1 小时后直接删除，不在大厅里堆着——这类房间没设密码时，大厅里任何人都能点 🗑 立刻删掉。

### 识别在手机上跑（浏览器端 OCR）

扫描识别默认走**手机浏览器**（tesseract.js + WASM），服务端只拿识别出的文本做封闭集匹配
（`POST /api/rooms/{code}/recognize-text`，纯字符串计算，一次 20~80ms，**零 OCR 内存开销**）。
512MB 的小云主机因此也能扫卡。方案与实测数据见 [design/08](design/08-浏览器端OCR方案.md)。

- 首次点扫描要下约 5.6MB（WASM core + 中文语言包），界面会明说；之后走浏览器缓存
- 资源全部自托管在 `/tesseract/`（构建时由 `web/scripts/sync-tesseract-assets.mjs`
  从 node_modules 生成），**不依赖 CDN**，局域网/离线可用
- 一帧 1~3s（视机型），扫描框状态行有脉冲小圆点表示正在识别
- 降级链：浏览器 OCR → 服务端 OCR（下节，仅 `WITH_OCR=1` 的部署有）→ 手动检索
- 离线命中率：194 张实拍图，四个游戏牌堆 Top-3 全部 100%（详见 design/08 §6.1）

```powershell
cd web; npm run ocr-bench      # 194 张实拍图跑一遍 OCR（产物进 build/ocr_bench/）
server\.venv\Scripts\python.exe tools/eval_browser_ocr.py   # 算 Top-1/Top-3 命中率
cd web; npm run ocr-smoke      # 真实浏览器冒烟：自托管资源能不能加载、WASM 能不能跑
```

### 服务端 OCR 默认关闭

镜像**默认不装** PaddleOCR（压缩后 ~60MB）。带 OCR 的镜像压缩后 ~520MB，运行时光加载模型
就占 500MB+ 内存，识别一帧再涨 100MB——512MB 的小云主机（如 Render Free）上实测**必被
OOM 杀掉**（`exit 137`），表现为手机端扫描永远「未识别到」、服务反复重启、无持久盘时连
房间存档一起清空。**这正是识别搬到手机上的原因。**

服务端识别现在只是降级链上的第二档：浏览器 OCR 起不来（老机型 / WASM 被禁）时才会用到，
两档都没有就转手动检索（永远可用的兜底）。内存充裕的机器（局域网自建，建议 ≥2GB）
要服务端识别就自己构建：

```powershell
docker build --build-arg WITH_OCR=1 -t cashflow:ocr .
```

### 扫描识别排障

下面这些端点是给**服务端 OCR**（`WITH_OCR=1`）排障用的；浏览器端识别的问题看手机浏览器
控制台，或用 `npm run ocr-smoke` 在开发机上复现。

服务端 OCR 对 CPU 和内存的胃口不小（开发机实测整卡一帧 ≈2.5s，容器内 ≈3.4s，模型常驻数百 MB）。
超时、被 OOM 杀掉、依赖没装，从手机上看都只是「扫描不出来」。两个端点直接定性：

```bash
curl https://<域名>/api/health                                  # OCR 装没装、预热成没成、内存离上限多远
curl -F image=@卡面.jpg -F deckHint=SMALL_DEAL \
     https://<域名>/api/health/ocr-probe                        # 实测一帧：耗时 / OCR 出的文本 / 候选
```

`ocr-probe` 不用建房间也不写库，不传图片就用一张空白图只测「模型跑不跑得通」，
`-F timeout=60` 可临时放宽超时，用来区分「跑不动」和「只是慢」。对照判断：

| 观察到 | 结论 |
| --- | --- |
| `memory.limitMb` 512 且 `rssMb` 逼近它；probe 请求半途断连；`uptimeS` 反复归零 | 内存不够，进程被 OOM 杀掉 |
| `reason=timeout`，放宽 `timeout` 后能出结果但要几十秒 | CPU 太弱，调 `CASHFLOW_OCR_TIMEOUT` 或换机器 |
| `ocr.available=false` / `reason=unavailable` | 默认精简镜像（`WITH_OCR=0`）就长这样，或设了 `CASHFLOW_OCR=off` |
| `ok=true`、`texts` 有内容但 `candidates` 空 | 算力够，是识别质量问题（光线/取景/匹配阈值） |

相关环境变量：

- `CASHFLOW_OCR=off` — 关掉服务端 OCR（不影响手机上的浏览器端识别）
- `CASHFLOW_OCR_TIMEOUT` — 单帧超时秒数，默认 8（按开发机标定，弱 CPU 机器需调大）
- `CASHFLOW_OCR_WARMUP=off` — 跳过启动预热。小内存实例上「启动即加载模型」本身就可能触发 OOM
- `CASHFLOW_DIAG=off` — 关闭上面两个诊断端点

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
server/app/recognize/ 识别适配层（封闭集匹配 + 本地 PaddleOCR 降级档）
web/src/ocr.ts        浏览器端 OCR（tesseract.js，取景帧裁剪 + worker 复用）
web/scripts/          tesseract 资源同步、离线命中率基准、浏览器冒烟测试
server/data/          卡牌/棋盘 JSON —— 权威数据源，人工可改，进 git
server/manual_pages/  说明书扫描页图片，App 内「📖 说明书」直接翻阅
web/                  Vue3 + Vite + TS + Pinia（手机端 PWA）
Dockerfile            单镜像构建（前端内嵌；默认不含 OCR，WITH_OCR=1 可加）
docker-compose.yaml   本地构建 + 启动（云端用 docker run，见「Docker 部署」）
.github/workflows/    publish-image：打 tag 自动构建并推送镜像到 Docker Hub 与 ghcr.io
design/               设计文档（需求、规则引擎规格、架构、卡库设计）
tools/                卡库校验、说明书渲染等命令行工具
```
