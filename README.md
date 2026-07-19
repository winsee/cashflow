# 现金流游戏辅助工具（Cashflow Companion）

把纸质《富爸爸现金流》桌游做成线上辅助工具：实体棋盘/骰子/卡牌照常线下玩，每人手机开网页完成选卡录入、自动记账、全员状态同步。设计文档见 [design/](design/)。

## 当前进度

- ✅ **M0** 卡牌库 schema + 数据文件（`server/data/`，含 14 张种子卡 + 快车道全部格子）+ 网页录入工具（`/#/entry`）与核对工具（`/#/entry/review`）
- ✅ **M1** 房间/开局/回合/手动选卡 + 全部老鼠赛跑记账 + 总览 + 日志（不用 OCR 可完整玩）
- ✅ **M2 引擎部分** 快车道/破产/交易确认/房主撤销改账（含前端面板）
- ⬜ **M3** OCR（识别接口已预留，`ManualPick` 兜底已可用）
- ⬜ **M4** 云部署 / HTTPS（Docker 文件已备，见 `deploy/`）

规则引擎按 design/02 全量测试驱动：`server/app/engine/tests`（41 项：说明书三组数值回归、全部流程用例、随机行动重放属性测试）。

## 卡牌录入（录入库与运行时库分离）

- **录入库** `server/data/entry/cards/*.json`：录入工具（`/#/entry`）的纯数据记录，随录随存，怎么改都不影响对局；id 自动生成；同叠内「标题+数值全同」判定为重复卡拒绝入库，同名多版本卡须每张填区分关键词
- **运行时库** `server/data/cards/*.json`：游戏引擎/识别实际使用的数据，仅在录入页点「🚀 发布」（校验整库 → 拷贝 → 热重载，失败自动回滚）时更新；也可手动把 entry 下文件拷到 cards 下重启服务
- 两库均进 git；核对工具（`/#/entry/review`）提供逐张翻页核对与全字段清单，用于录完后与实体卡对数值

## 本地开发运行

```powershell
# 后端（端口 8000；首次先建 venv：uv venv --python 3.12 .venv && uv pip install -e .[dev]）
cd server
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端热更新开发（可选，端口 5173，已配置代理到 8000）
cd web
npm install
npm run dev

# 前端构建（构建后后端直接服务 web/dist，手机访问 http://<局域网IP>:8000 即可）
npm run build

# 跑测试
cd server
.venv\Scripts\python.exe -m pytest
```

## Docker（交付形态）

```powershell
docker compose -f deploy/compose.yaml up -d
```

## 目录

```
server/app/engine/    规则引擎（纯函数，事件溯源）＋全量测试
server/app/store/     SQLite 事件存储
server/app/recognize/ 识别适配层（M3 接 PaddleOCR）
server/data/          卡牌/棋盘 JSON —— 权威数据源，人工可改，进 git
web/                  Vue3 + Vite + TS + Pinia（手机端 PWA）
deploy/               Dockerfile + compose
```

## 说明书查看（FR-31）

把说明书扫描页图片（按页码命名的 PNG/JPG）放入 `server/manual_pages/`，App 内 `📖 说明书` 即可翻阅。该目录随仓库入库、随 Docker 镜像交付，远程部署无需额外拷贝。
