## 1. 一处派生

- [x] 1.1 新增 `web/src/statuses.ts`：`PlayerStatus` 类型 + `playerStatuses(p)` +
  `majorStatus(p)`。八种状态按优先级排；`major` 决定进不进牌桌与座次条
  （分期收款、孩子数、快车道三条是次要状态，只在总览露出）
- [x] 1.2 新增 `components/StatusChips.vue`（props: `player` / `minor`），
  `style.css` 只加一条 `.badge-row`；颜色复用既有 `.badge` / `.badge.ft` / `.badge.out`
- [x] 1.3 **停赛的颜色统一成中性灰**：线下行动页原来是红 `.badge.out`、总览页是灰，
  两边打架。红留给「出局 / 破产清算」这类真正的坏消息，停赛只是暂时轮空

## 2. 两处照抄的代码收成组件

- [x] 2.1 新增 `components/PlayerTableRow.vue`，线下 `ActionTab` 与纯线上 `OnlineRoomView`
  共用；class 名一个不改（`.avatar-lg` / `.badge.turn` / `.money`），
  既有冒烟屏 `03f` / `23a` 的断言原样通过
- [x] 2.2 新增 `components/SeatStrip.vue`，替掉 `OnlineRoomView` 里 HUD 与 peek 条
  各写一遍的那两份；`seats` 派生加 `mark`（`majorStatus` 的 tone）与 `title`
- [x] 2.3 步骤文案让位给徽章：`stepTextOf` / `tableStepText` 遇到出局 / 破产清算 / 停赛
  返回空串，`PlayerTableRow` 那一行随之隐藏（不是留一行空白）
- [x] 2.4 座次条角标 CSS：`.seat-dot .mark` 7px 圆点，`out`→红 / 无 tone→灰 / `ft`→金

## 3. 各处接上同一份派生

- [x] 3.1 `OverviewTab`：四行手写徽章 → `<StatusChips minor />`。
  这一页因此**净增**慈善、快车道永久慈善、分期收款、孩子数
- [x] 3.2 线下 `ActionTab` 本人那两枚手写徽章 → `<StatusChips :player="me" />`
- [x] 3.3 纯线上 peek 条与 `hubTip` 改用 `majorStatus(me)?.label`
- [x] 3.4 `FasttrackPanel` 那枚「已行善」徽章文案对齐 `CHARITY_FT`

## 4. 回执

- [x] 4.1 `receipts.ts` 加 5 个 case（失业他人侧 / 慈善 / 快车道慈善 /
  破产开始 / 破产收尾），一律 `player_id === meId` 排除当事人
- [x] 4.2 `buildReceipts` 加可选 `next`，`store.ts` 的 `ingestEvents` 从 `msg.state` 传入
  —— 破产收尾的结局（复活 vs 出局）写在服务端 apply 里，payload 看不出来
- [x] 4.3 **线下不多出一条**：失业在线下是玩家自己点的，既有 `SELF_ACTION` 6 秒窗
  照旧把当事人那份排掉；慈善两套模式都是自己点的，靠 id 排除即可，不进那张表
  （冒烟屏 `03h` 断言当事人页面上没有「刚刚发生在你身上」）

## 5. 验收

- [x] 5.1 `npx vue-tsc --noEmit` 通过
- [x] 5.2 后端 `pytest` **527 passed** 作回归（这次一行 Python 都没动）
- [x] 5.3 `npm run ui-smoke` 新增 4 屏、共 **65 屏**全过：
  `03h` 本人徽章 + 当事人不收自己的回执、`03i` 别人的牌桌徽章 + 回执、
  `03j` 总览页、`23b` 座次条两处都在且**没人有状态时一个角标都没有**、
  `29` 三人房里把一人标成出局 → 座次条角标 + 牌桌「已出局」（正例）
- [x] 5.4 溢出扫描与改动前逐项对比：没有新增溢出（改动后反而少了三项）
- [ ] 5.5 **真机那一遍**（留给房主）：4 人局里让一人失业、一人捐慈善，
  确认另外两人在牌桌 / 总览 / 座次条三处都看得见；19px 座次点上的 7px 角标看不看得清；
  回执会不会觉得吵

## 6. 顺带

- [x] 6.1 `ui-smoke.mjs` 的浏览器与 python 路径加 Linux 兜底（Windows 上取第一条命中的，
  行为不变），云端会话里也能跑完整 65 屏
- [x] 6.2 `.gitignore` 加 `server/*.egg-info/`（editable 安装的产物）
