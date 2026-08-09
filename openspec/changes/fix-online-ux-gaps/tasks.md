## 1. 抽出资金三块并锁住「线下不变」（D1，风险最高，先做）

- [x] 1.1 新建 `web/src/components/tools/BankPanel.vue`：把 `ActionTab` 的 🏦 银行整块搬进来（当前贷款+月供、金额输入 `step=1000 min=1000`、贷款/还款/还清、两行规则说明），二次确认沿用 `confirmAction()` 且保留贷后月现金流为负时的 warning；`defineExpose({ root })` 供外部滚动定位
- [x] 1.2 新建 `web/src/components/tools/TransferPanel.vue`：搬 🤝 玩家间转账（转给/金额/备注/发起 + 「对方确认后才会扣款」）
- [x] 1.3 新建 `web/src/components/tools/BankruptcyPanel.vue`：搬破产清算面板（缺口两行、逐项资产「卖给银行」、股票半价卖出、还银行贷款、完成清算、清算后果说明）
- [x] 1.4 `ActionTab.vue` 模板等价替换成上面三个组件；`gotoBank(need)` 的滚动锚点改为 ref 到 `BankPanel` 根元素，`toolsOpen` 折叠态留在 `ActionTab`
- [x] 1.5 跑 `npm run build && npm run ui-smoke`，**逐屏比对线下 38 屏与改动前一致**（这是 design/09 §1.1 硬约束的兜底；有任何一屏变化就回到 1.4 修，不往下做）

## 2. 补上纯线上的死局出口（A 组，修的是「走不下去」）

- [x] 2.1 `OnlineRoomView`：`ledger` 类型加 `'more'`，账本分段控件变四个（报表/总览/日志/更多）
- [x] 2.2 「更多」页装入 `BankPanel`（仅 `phase === 'RAT_RACE'`）+ `TransferPanel` + 「🆘 进入破产流程」（仅 `bankruptable`）
- [x] 2.3 `me.inBankruptcy` 时 full 档只渲染 `BankruptcyPanel`，账本分段控件让位
- [x] 2.4 `.drawer-cta` 改两行（`flex-direction: column`）：上行卡片决策、下行「结束回合」；无卡时下行升为主按钮
- [x] 2.5 结束回合的禁用判据与 `_d_end_turn` 逐项对齐（只拦五种强制卡 + 机会/失业未处理），并在按钮上写明在等什么；**确认股票要约、房产、企业、收藏品、骰子赌局未决时可以结束回合**
- [x] 2.6 `StockTradeBox` / `OnlineCardPanel` / `OnlineLandingPanel` 的现金不足提示按模式切换文案，并加「去贷款」按钮：打开 账本 → 更多 → 银行 且金额预填 `ceil(缺口/1000)*1000`；快车道分支如实写「现金不够就买不了」
- [ ] 2.7 手动验一遍这条路走得通：现金不足 → 去贷款 → 买入 → 结束回合
  （**留给 5.4 真机那一遍**：要凑出「现金不够买当前这张卡」得靠服务端牌堆随机命中，
  ui-smoke 里做不成确定性用例。目前机械化覆盖到的是这条路的两端——
  账本 → 更多 → 银行 已能打开并预填（屏 27c），「结束回合」在卡未决时常驻可点（屏 26c））

## 3. 建房两步与开局准备（B 组 · online-mode）

- [x] 3.1 `LobbyView`：建房弹层拆 `createStep: 1 | 2`，第 ① 步只放两张**竖排**模式卡（`.bigbtn-row` 加 `flex-direction: column`）+ 准备物清单 + 选中态（描边 + 浅底 + ✓ 角标），按钮「下一步 / 取消」
- [x] 3.2 第 ② 步放房间名/密码/人数，顶部回显模式徽章 + 「改」退回第 ① 步；沿用既有 disabled 判据
- [x] 3.3 `DealCurtain` 加默认插槽（不传仍渲染 `GameCard`）
- [x] 3.4 `RoomView` 第 1 步的 `online` 分支改为牌背 → 点击 → 翻牌 → 整张 `ProfessionCard`；等待期只显示「正在发牌…」，翻开后不留任何可换一张的控件；`me.professionId` 已有值时直接显示翻开态不放动画
- [x] 3.5 `RoomView` 第 2 步的 `online` 分支改为与线下同一段 `SwipePicker` + 梦想卡（含「已被选走」图章与 `dreamTip()`），删掉 `pickDreamOnBoard`
- [x] 3.6 摘要区加只读小轮盘公示梦想归属（`compact`，不可点）；删掉 `BoardView` 的 `pickable` prop 与 `tap()` 里的 guard

## 4. 棋盘与骰子（B 组 · board-presentation）

- [x] 4.1 `.wheel-name` 去掉 `position:absolute; bottom:5%`，改为棋盘之上的静态一行，`compact` 时隐藏；确认任何档位下都不压格子
- [x] 4.2 新增 `.die3d/.cube/.face` 一族（六面朝向按对面之和为 7、尺寸只由 `--d` 驱动、透视按 `--d` 比例算），并把「点数 → cube 旋转」写成一张六行表放在一处
- [x] 4.3 四态接线：可掷（主色实心）/ 摇动（`infinite` 多轴翻滚 + 轻浮起）/ 落定（转到那一面 + 回弹）/ 还没掷（**保留平面 `?`**，并在代码注释写明理由）
- [x] 4.4 多粒错相位：第 2、3 粒各给负 `animation-delay` 与略不同周期，落定圈数也不同；`prefers-reduced-motion` 与「跳过动画」下直接显示终值
- [x] 4.5 观战牌桌：peek 条右侧头像列点开 half 档牌桌（头像 + 昵称 + 回合步骤 + 现金与月现金流），复用线下那套派生逻辑
- [x] 4.6 起点棋子移到**环外**：`geom.ts` 里位置 0 的落点从 `polar(RMID, MARKER_ANGLE)`（环内中径）改为 `outerLabelRadius(ring)` 半径处，多枚沿切向排开 15px；`BoardView` 在 `atMarker.length > 0` 时隐藏「开始」/「在此进入」文字（三角保留）
- [x] 4.7 验起点那一屏：开局四人全在起点时不压第 24 / 第 1 格的文字、棋子不被 viewBox 裁切；掷 1 后棋子进第 1 格且文字标注恢复
- [ ] 4.8 真机看两个骰子尺寸极端：58px（轮心 1 粒）与 **40px**（慈善 3 粒；界面里没有 32px 的骰子——
  开局的顺序是服务端替全员掷的，排序列表上并不摆骰子），确认不糊、不穿面

## 5. 验收

- [x] 5.1 `npx vue-tsc --noEmit` 通过
- [x] 5.2 `server\.venv\Scripts\python.exe -m pytest` 全绿（本变更不动后端，作回归确认）
- [x] 5.3 `npm run ui-smoke` 共 **57 屏**全通过。纯线上新增 5 屏（建房第 ① 步、职业卡牌背、职业卡翻开、
  梦想滑动卡片、账本·更多·银行）+ 观战牌桌 1 屏；线下另加 1 屏 `03g` 专钉被抽走的银行/转账
  （那三块原来一屏都没覆盖，是 D1 唯一真正的风险面）。线下逐屏与改动前比对：差异只出现在
  随机房间码、日志时间戳与 3 秒 toast 的存留，其余字节一致
- [ ] 5.4 真机试玩一局纯线上，重点复验：现金不足 → 贷款 → 买入 → 结束回合；破产清算能走完；观战牌桌能展开
- [x] 5.5 更新 `CLAUDE.md` 当前状态与 `design/待办-纯线上试玩反馈-2026-08-08.md`（七条全部打勾；第 6 条已于 2026-08-09 定案并落地，proposal/design 的旧「不做」措辞一并订正）
