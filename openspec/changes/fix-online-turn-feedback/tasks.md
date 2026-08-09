## 1. 演出期间界面不许抢跑（A 组，两条同源）

- [x] 1.1 `store.ts` `ingestStage()`：排队前扫一遍 events，遇 `PLAYER_MOVED` 就
  `stagePos[player_id] = payload.from`，把棋子钉回移动前那一格（`from` 可能是 `0`，
  `positions` 用 `??` 不是 `||`，`0` 不会被误 fallback）；放在 `skipAnim` 判断之后
  ——跳过动画的人直接 `skipStage()`，锁位没有意义
- [x] 1.2 `OnlineRoomView`：一道门 `held = game.staging`，门关着时不渲染
  `OnlineLandingPanel` / `OnlineCardPanel` / `cardCta` 那一行 / `PromptModal`，
  `wantDetent` 不提档，`.board-stage` 不加 `card-open`
- [x] 1.3 peek 条在 `held` 时按 `stageNow.kind` 写「正在移动…」/「正在发牌…」，
  不再显示「第 N 步 / 3」（那一步还没走到）
- [x] 1.4 三条跳过出口共用 `skipStage()`（清队列 + 清 `stagePos`），所以门与棋子位置同时释放；
  代码路径已核对。**机械化只覆盖到「不跳过」那一路**（ui-smoke 屏 24/26 断言演出期间不抢跑），
  三条跳过路径留给 5.4 真机那一遍

## 2. 自动落点的交代（B 组）

- [x] 2.1 `receipts.ts` 补三个 case：`CHILD_ADDED`（`−perChildExpense/月`）、
  `UNEMPLOYMENT_HIT`、`FT_CASH_HIT`（税务审计/离婚/官司），均只推给 `player_id === meId`。
  **实施时收窄了范围**：原计划里的 `PAYDAY`/`FT_PAYDAY` 不进回执——它们每回合都可能发生，
  而回执要点「我知道了」才消失，每回合逼人点一次是骚扰；那两件事改由落点结果卡带金额交代
  （design/09 §4.3.1 的频次判据）
- [x] 2.2 `SELF_ACTION` 补 `CHILD_ADDED: ['ADD_CHILD']`、`UNEMPLOYMENT_HIT: ['UNEMPLOYMENT']`、
  `FT_CASH_HIT: ['FT_TAX_AUDIT','FT_DIVORCE','FT_LAWSUIT']`
  ——线下这几件事是玩家自己点的，靠既有 6 秒窗口排掉；纯线上来自 `ROLL_DICE`，不在窗口内
- [x] 2.3 `OnlineRoomView` 在待办区顶部渲染既有 `ReceiptStack`
  （纯线上此前根本没有回执出口，别人的市场卡波及到我同样看不见）
- [x] 2.4 `OnlineLandingPanel` 加 `landing.resolved` 分支：结果卡（银行结算日 / 现金流量日 /
  孩子 / 服务端已写好 `note` 的那几种），`.card.inner`、不弹层、不改档位
- [x] 2.5 跑线下 39 屏，确认一条回执都没多出来（全部通过；线下唯一的变化是
  出牌顺序那行由「· 已选梦想」变成写出梦想名，见 3.4——那一行两模式共用）

## 3. 版面两处（C 组）

- [x] 3.1 `OnlineRoomView` + `style.css`：账本分段控件 `.ledger-seg` 移到 `drawer-body` 顶部
  （`sticky`、等宽四段、不折行），peek 条 `ledger` 分支只留「账本」+「收起 ✕」
- [x] 3.2 「跳过动画」移进「更多」页底部的「显示设置」卡
- [x] 3.3 `RoomView`：删只读轮盘整块 + `ftSquares`/`hue`/`FT_TYPE`/`ftType`/`BoardView` 与
  `BoardSquare` 两个 import / `onMounted` 里只为轮盘存在的 `fetchBoard()`
- [x] 3.4 出牌顺序每行的「· 已选梦想」改成写出梦想名（`dreamById`，已有）

## 4. 文档

- [x] 4.1 design/09 → v0.3：§1.4.2 撤销只读轮盘并写清理由、§2.4 分段控件位置与「跳过动画」归属、
  §4.3 自动落点的结果卡与回执规格、§5.1 新增「演出与权威状态」硬规则
- [x] 4.2 `CLAUDE.md` 补一段 ㉟
- [x] 4.3 删 `design/待办-纯线上试玩反馈-2026-08-08.md`（其自述「改完即删」，上一轮已全部落地）

## 5. 验证

- [x] 5.1 `npx vue-tsc --noEmit`
- [x] 5.2 `server\.venv\Scripts\python.exe -m pytest`（后端一行未动，作回归）
- [x] 5.3 `npm run build && npm run ui-smoke`：**58 屏全通过**（新增 24a「自动格的交代」）。
  新断言：发牌帘幕在屏时 `.drawer-body .gcard` 必须为 0、掷骰演出中不写「第 3 步 / 3」、
  `.ledger-seg` 四段且不折行（`offsetHeight ≤ 50`）、准备页 `.wheel` 数为 0 且不出现「· 已选梦想」
- [ ] 5.4 真机一遍：掷骰棋子不瞬移、市场风云先翻牌后进抽屉、停结算日有交代、账本四页一行
