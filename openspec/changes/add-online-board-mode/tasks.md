## 1. 棋盘数据补录与核对（前置，见 design D6/D7）

- [x] 1.1 从 `docs/游戏棋盘.jfif` 读出快车道的完整格子顺序 —— 48 格，落成 `squares` 数组（`{index, ref}`，不存 `type`/逐格 `id`，理由见 design D6）。修正：现金流量日只有 **3** 个；实体那圈弯弯曲曲是排版，不是两条轨道
- [x] 1.2 内圈 24 格从纯字符串升级为 `{id, type}`（`rr-01`..`rr-24`，7 种 type），顺序原样不动；显示名由 type 推出不入库。`data_loader.py` 加 `RatRaceSquare` 与 `_load_rr_squares()`（格数/id 唯一/type 合法/各类型计数）
- [x] ~~1.3 写 `tools/build_board_check.py`：生成可打印的棋盘核对页~~ —— **不做**：两条轨道的核对都已由房主对着实物直接走完（1.4），这个脚本要服务的对象没有了。校验交给 `validate_cards.py`（1.6）
- [x] 1.4 房主对着实体棋盘逐格核对 —— **快车道 48 格**与**内圈 24 格**均已核实通过（2026-08-08）。内圈核对顺带纠出一处文档转录错误：实物是**机会格与事件格严格交替**（末格是市场风云），`rat_race.json` 存的一直是对的，而 design/05 §1 与 design/09 §3.1 抄成了从第 7 格起错开一位的版本——两处文档已订正，JSON 未动
- [x] 1.5 落地 `fast_track.json` 的 `squares`（`businesses`/`dreams`/`specials` 原样保留）；`rat_race.json` 的结构化见 1.2
- [x] 1.6 `tools/validate_cards.py` 增加 `check_fast_track_board()`（格数、index 连续、`ref` 与企业/梦想清单双向对账）与 `check_rat_race_board()`（24 格、id 唯一、type 合法、七种类型计数 12/3/3/3/1/1/1）
- [x] 1.7 跑 `python tools/validate_cards.py` 通过（快车道 48 格 = 企业 18 · 梦想 23 · 特殊 7；内圈 24 格构成正确）；`pytest` **459 passed / 1 skipped**（新增 3 条内圈回归）

## 2. 对局模式（capability: online-mode）

- [x] 2.1 `models.py`：`RoomState` 加 `mode: GameMode`（`OFFLINE_ASSIST` 默认 / `ONLINE`）
- [x] 2.2 `engine.py`：新增 `ROOM_MODE_SET` 事件与 `_a_room_mode_set`，建房时作为事件流第一条追加（动作名 `SET_ROOM_MODE`，房间一旦有人就 `MODE_LOCKED`）。顺带修一处既有隐患：`handle_action` 的「大厅最后一人离开即解散房间」只看 `players` 为空，建房时房主还没 JOIN 会把新房当场删掉，改为同时要求这批事件里有 `PLAYER_LEFT`
- [x] 2.3 `store/db.py`：`room` 表加 `mode` 列（幂等 `ALTER TABLE`，既有房间落到 `OFFLINE_ASSIST`）
- [x] 2.4 `rooms.py`：`create_room` 接受模式参数；`serialize()`、`list_rooms()` 与 `seats()` 下发 `mode`
- [x] 2.5 `main.py`：`POST /api/rooms` 接受 `mode`（缺省 = `OFFLINE_ASSIST`）
- [x] 2.6 纯线上模式的服务端闸门（design D10 那张表）：`DRAW_CARD` 带 `cardId` 拒绝、`PAYDAY`/`FT_PAYDAY` 动作拒绝、`SET_TURN_ORDER` 拒绝（顺序由 2.7b 排）、**`PLAYER_CORRECT` 拒绝**（本人更正是线下认错实体卡的路径，纯线上退回堆顶再抽必然同一张）、`recognize` 与 `recognize-text` 接口拒绝
- [x] 2.7 职业卡随机分配（design D14）：`_d_select_profession` 在纯线上模式下忽略传入的 `professionId`，用 decide 阶段的 RNG 从尚未被占用的职业里随机挑一张，结果写进既有 `PROFESSION_SELECTED` 事件（`_a_profession_selected` 不改）；**已有职业的玩家再次提交拒绝**（线下的可改选行为保持不变）
- [x] 2.7b 回合顺序服务端掷骰（design D15）：`_d_start_game` 在纯线上模式下先替全员各摇一次骰（同 `_dice_gamble_event` 的做法）、按点数降序排、平局者之间重摇，结果与 `rolls` 写进既有 `TURN_ORDER_SET` 事件（`_a_turn_order_set` 不改），随后才产出 `GAME_STARTED`；那道 `if not state.turn_order` 校验在纯线上模式下挪到摇完之后，线下模式原样保留
- [x] 2.8 `SELECT_DREAM` 两种模式都保持开放、玩家手动挑，`DREAM_TAKEN` 校验不动（说明书步骤 9 是「选择」）——引擎零改动，只补回归
- [x] 2.9 测试：模式默认值、模式不可改、撤销后重放模式不丢（D1 的核心回归）、纯线上模式下各闸门返回明确错误码（`ONLINE_DECK_ONLY` / `ONLINE_AUTO_PAYDAY` / `ONLINE_AUTO_ORDER` / `ONLINE_NO_CORRECT` / `ONLINE_NO_RECOGNIZE`）
- [x] 2.10 测试：纯线上抽职业随机且互不相同、客户端传的 id 被忽略、抽过再抽被拒、重放一致、撤销后可重抽；纯线上抽到某职业后的报表与线下录入同一职业逐字相同
- [x] 2.10b 测试：纯线上开局自动排出回合顺序、平局重摇、重放顺序一致、房主改顺序被拒；线下模式的手排路径不受影响
- [x] 2.11 测试：既有测试一条不改、一条不跳全绿（线下模式行为不变的硬约束）——**动工前实测基准 459 passed / 1 skipped**，本节后 **482 passed / 1 skipped**（新增 23 条）

## 3. 牌堆（capability: card-decks）

- [x] 3.1 `models.py`：`RoomState` 加 `decks: dict[str, list[str]]` 与 `discards: dict[str, list[str]]`
- [x] 3.2 `engine.py`：`_build_decks(lib)` 按卡库实际张数（含重复卡）建四副堆（职业卡不进这个模型，见 2.7）
- [x] 3.3 `DECKS_SHUFFLED` 事件：`START_GAME` 时（仅纯线上）decide 阶段摇出牌序、整串写入 payload
- [x] 3.4 `DECK_RESHUFFLED` 事件：牌堆取空时先洗回弃牌堆再发牌；牌堆与弃牌堆同时为空返回明确错误
- [x] 3.5 `apply` 侧：`CARD_DRAWN` 按 id 从堆中移除（**不是 `pop(0)`**——按 id 移除才能让「撤销中间一次发牌后整流重放」成立）；卡进入终态时经 `_discard_active` 压入弃牌堆，`ActiveCard.discarded` 保证只入一次；没做决定就结束回合的牌也一并进弃牌堆，否则会从牌堆里凭空消失
- [x] 3.6 `_draw_from_deck(state, player, deck)` 共用函数，供落点派发与 `CHOOSE_DEAL_SIZE` 调用；线下模式的 `_d_draw_card` 走原路径不变
- [x] 3.7 `serialize()` 只下发各副的剩余/弃牌张数，**不下发牌序**
- [x] 3.7b 出口脱敏（design D2）：`_sanitize_payload(etype, payload)` 剔除 `DECKS_SHUFFLED.orders` / `DECK_RESHUFFLED.order`（换成张数），在 `broadcast_state` 的 `lastEvents`（`rooms.py:97`/`:277`）与 `log_rows()` 的 `payload`（`rooms.py:359`）两个出口各调一次；SQLite 里的事件流保持完整牌序，脱敏只发生在出口
- [x] 3.8 测试：建堆张数等于卡库总数、重复卡按份数入堆
- [x] 3.9 测试：撤销一次发牌后下一张发出的仍是同一张；撤销跨越一次洗回后重放结果与当前状态一致
- [x] 3.10 测试：整局重放得到同一串发牌序列；**三个出口**（`serialize()`、WS 广播的 `lastEvents`、`/log` 接口）的输出里都不含未发出的牌；同时断言事件表里牌序仍在（脱敏没伤到重放）

## 4. 位置与掷骰移动（capability: board-movement）

- [x] 4.1 `models.py`：`PlayerState` 加 `rr_position` / `ft_position`（**1-based 格索引，0 = 起点/入口标记，不是格子**，见 design D3）；`RoomState` 加 `landing`
- [x] 4.2 `data_loader.py`：加载棋盘 `ring` 与内圈序列，暴露按索引取格子的接口；数据损坏时启动报错
- [x] 4.3 把 `_d_payday` 里算钱的部分抽成共用函数（动作层的 `_require_payday_free` 留在动作里），确保线下模式结果逐字不变
- [x] 4.4 新动作 `ROLL_DICE`：校验（当前玩家 / 本回合未掷 / 未停赛 / 非清算中 / 粒数合法）+ 服务端摇骰 → `DICE_ROLLED`
- [x] 4.5 移动与经过结算：逐格前进，经过的每个结算格产出一次 `PAYDAY`（或 `FT_PAYDAY`），随后 `PLAYER_MOVED { track, from, to, path }`
- [x] 4.6 结算中破产：产出 `PAYDAY_UNPAYABLE + BANKRUPTCY_STARTED` 后移动就地终止，棋子停在该结算格
- [x] 4.7 骰子粒数规则**按赛道分开**（两条赛道的慈善不是同一种权利）：老鼠赛跑默认 1 粒，慈善生效时允许 **1 或 2** 粒并消耗一轮慈善（`charity_turns` 0..3，`models.py:151`）；快车道默认 2 粒，捐过款后**永久**允许 **1、2 或 3** 粒（`charity_forever`，`models.py:115`）；超出本赛道上限的粒数拒绝——校验要读 `phase`，不能写成一个 `1 <= n <= 3`
- [x] 4.8 落点派发（自动格）：市场风云/额外支出发牌、孩子、失业、税务审计、离婚、官司 → 复用既有动作的事件产出，`landing.resolved = True`
- [x] 4.9 落点派发（选择格）：机会 / 慈善 / 快车道绿格 / 快车道粉格 → `landing.resolved = False`，等玩家动作
- [x] 4.10 新动作 `CHOOSE_DEAL_SIZE`：校验落点是机会格且未决 → 从对应牌堆发牌
- [x] 4.11 纯线上模式下给既有落点动作（`CHARITY`/`FT_BUY_BUSINESS`/`FT_BUY_DREAM`/`FT_DOUBLE_DREAM`/`FT_CLAIM_DREAM` 等）加「落点一致」前置校验；线下模式跳过这道校验
- [x] 4.12 `ENTERED_FASTTRACK` 事件补 `ft_position` = 快车道入口格；进场当回合的既有语义（`turn_closed`）不变
- [x] 4.12b 落点未决时的结束回合闸门（design D5）：纯线上模式下 `_d_end_turn` 对 `landing.resolved == False` **按格子类型判**——机会格未抽牌拒绝（`LANDING_UNRESOLVED`），慈善格/快车道绿格/粉格允许直接结束（不做本就是合法选择）；线下模式不受影响
- [x] 4.13 `_revert` 侧：把一次掷骰产出的整串事件作为一批一起撤——区间规则见 design D4（从 `DICE_ROLLED` 到下一条 `TURN_ENDED` 或下一次 `DICE_ROLLED` 之前的连续 seq），区间内每条市场卡 `CARD_DRAWN` 再并入 `_market_cascade`（`rooms.py:119`）的结果，**两层 cascade 会嵌套**；纯线上模式下 `PLAYER_CORRECT` 已关（2.6），这条只服务房主撤销
- [x] 4.14 `serialize()` 下发位置、`landing`、本回合是否已掷骰
- [x] 4.15 棋盘接口：`server/app/main.py:186` 已有 `/api/board/fasttrack`，**扩展这一套路径**补内圈序列（如 `/api/board/ratrace`，或合并为 `/api/board` 同时返回两条轨道并保留旧路径），别新造第二套命名
- [x] 4.16 测试：每回合只能掷一次、非当前玩家被拒、停赛玩家不掷骰、清算中被拒、客户端自带点数被忽略；两条赛道的非法粒数各一条（老鼠赛跑慈善期请求 3 粒被拒）
- [x] 4.17 测试：跨一个结算日、跨两个结算日、恰好停在结算日三种情形的账目
- [x] 4.18 测试：跨结算日时付不出钱 → 就地终止 + 进清算
- [x] 4.19 测试：每种落点类型各派发到正确的动作；停在已被买断的绿格 = 本格无事发生；开局位置为 0 且第一次掷 N 点落到第 N 格（起点标记不占步、不触发效果），进快车道后同理
- [x] 4.19b 测试：机会格未抽牌时结束回合被拒；慈善格/绿格未决时结束回合放行
- [x] 4.20 测试：撤销一次掷骰后位置、结算、发牌全部回退且重放一致；**掷骰落在市场风云格、别人已答复后房主撤掷骰**（两层 cascade 嵌套）也一并回退且重放一致
- [x] 4.21 测试：纯线上模式跑通完整一局（老鼠赛跑 → 进快车道 → 分出胜负），说明书示例数值回归在纯线上模式下同样通过

## 5. 前端骨架与模式分叉（design/09 §1–§2）

- [x] 5.1 `types.ts` / `store.ts`：接住 `mode`、位置、`landing`、牌堆余量、`GET /api/board`
- [x] 5.2 模式徽章组件（「线下辅助」/「纯线上」两个固定说法，一处定义）
- [x] 5.3 大厅建房加模式选择（两张 `.bigbtn` 二选一，各写清「你需要准备什么」）
- [x] 5.4 徽章的另外三处复用：大厅房间列表、加入房间确认卡、房间准备页（准备页带锁图标，点击说明「模式在建房时选定，不可更改」）
- [x] 5.5 纯线上模式下隐藏手动选卡（`CardPicker`）与 OCR 扫描入口
- [x] 5.5b 纯线上模式下前端也关掉三个入口：日志页的「本人更正」（`correctable()` 加模式判断，只留「请房主撤销」）、准备页的手排回合顺序（改为开局自动排的说明文案）、行动页的手动结算日按钮
- [x] 5.6 新增纯线上房间骨架 `OnlineRoomView`：HUD → 棋盘 stage → 三档抽屉；**不复用四标签页、不出现 tabbar**（既有 `ActionTab` 等只服务线下模式，一行不改）
- [x] 5.7 HUD：银行储蓄 / 月现金流 / 目标进度带 / 「第 N 轮 · 轮到谁」+ 本轮行动顺序座次条（当前行动者实心、已行动过的淡出、出局的灰掉）
- [x] 5.8 抽屉三档（peek 128px / half 46dvh / full 88dvh）：档位由内容决定、可拖动覆盖、下一次系统事件重新提档且**只升不降**、展开时棋盘不加遮罩、把手复用 `.sheet-grab`
- [x] 5.9 抽屉里的决策按钮钉底（`position: sticky` + 上方渐变），内容可滚而按钮不滚走
- [x] 5.10 悬浮工具：「📋 账本」（full 档 + 报表/总览/日志三分段）与「📖 说明书」；**挂在棋盘 stage 内部的右上角**（档位切换缩的是棋盘自身宽度、stage 无 transform）
- [x] 5.11 三步流：① 掷骰 → ② 处理落点 → ③ 结束回合；已完成的步骤收拢为摘要行；落点无事发生时写明「本格无事发生」并把主操作切到结束回合
- [x] 5.12 抽屉与既有弹层的分工不变：我的待办→抽屉、别人波及我→`BaseModal`（压在抽屉之上）、二次确认→`ConfirmDialog`
- [x] 5.13 房间准备页（纯线上）· 职业：职业列表换成一个「🎴 抽职业卡」按钮，点完翻出 `ProfessionCard` 卡面（复用翻牌序列）；抽过之后按钮消失、原位改显示自己的职业卡，界面上不留任何看着能换一张的控件
- [x] 5.14 房间准备页（纯线上）· 梦想：改为在快车道棋盘上点粉格选，选中即在该格插一枚自己颜色的圆点（就是实体那块奶酪），全员可见谁选了哪个
- [x] 5.15 `npx vue-tsc --noEmit` 通过

## 6. 棋盘视图（capability: board-presentation，design/09 §3）

- [x] 6.1 `components/board/BoardView.vue`：内联 SVG 放射轮盘，几何常量（`V`/`R1`/`R0`/`RMID`/`RPAWN`）**一处定义**、棋盘渲染与走格动画共用；环按 JSON 里的格数自己重新分角
- [x] 6.2 内圈 24 格：每格 15°/缝 1.5°、外径 134/内径 94/中径 114、轮心可用直径 180px；格子色沿用 `decks.ts` 既有色板
- [x] 6.3 格子视觉三条：常态只铺 15% 类型色 + 外缘 7px 实心弧、走过的格子（trail）提到 34%、**只有当前所在格上满色**；标签一律水平不旋转；**12 个机会格不写字**
- [x] 6.4 板：暖白卡纸底（`--panel`/`--panel2` + `--line-2` 描边，不引入实体那块紫）+ 板顶 `CA$HFLOW` 名牌与「老鼠赛跑 / 快车道」，抽屉展开时名牌隐藏；起点是外环一枚三角 + 「开始」
- [x] 6.5 棋子：19px 圆片、`.avatar-lg` 同款、色相由座位序号定（与总览头像圈同源）；我的多一圈 2px 主色描边并永远在最上层；同格多子沿半径错开，超 3 个折成 `+N` 可点开
- [x] 6.6 轮心：只放骰盘 + 一行状态提示（轮次归 HUD、进度归 HUD 进度带，不在轮心重复）；文字不用 `nowrap` 硬撑，换行 + `text-wrap: balance`
- [x] 6.7 骰盘 1–3 粒：老鼠赛跑 1 粒 58px、快车道 2 粒 46px、慈善 3 粒 40px；慈善生效时粒数选择器**替换**轮心状态提示行（不叠高度、不弹层），「慈善生效中 · 还剩 N 轮」与「🎲 掷 N 粒骰」写在抽屉 peek 条
- [x] 6.8 快车道环：同一只轮盘、外径 140/内径 114；格面不写字只留色块，**点任意格弹 `FtSquareCard` 详情**；已买断绿格褪到 8%、已认领梦想在中径插一枚玩家色圆点；入口金色三角 +「在此进入」（它是标记不是格子，对应位置 0）。48 格数据已到位（任务 1.5），按 JSON 渲染即可
- [x] 6.9 手机竖屏：档位切换缩的是**棋盘自身的宽度变量**（不是 `transform: scale`，stage 有 `overflow:hidden`，缩 stage 等于白缩）；页面本身不横向滚动
- [x] 6.10 阶段换肤：`.skin-ft` 下棋盘自己跟着走金（板底本就是 `--panel`/`--panel2`，不为它另写一套），牌堆色标与语义色不参与换肤
- [x] 6.11 材质与层次（design D11）：格子压印边、纸纹、棋子接触阴影；卡牌翻开时棋盘压暗一档（`.board-stage.card-open`）
- [x] 6.12 环外标注（「开始」「在此进入」）按 `R1 + 文字半径 ≤ V/2 − 一行字高` 反算，确保不被 viewBox 裁掉

## 7. 演出层（capability: board-presentation，design/09 §5 节拍表）

- [x] 7.1 `web/src/stage.ts`：从 WS `state.lastEvents` 派生演出队列（与 `receipts.ts` 同一入口）
- [x] 7.2 拍 1–2 掷骰：滚动 0.5s +（网络等待）→ 点数放大回弹落定 0.25s。**不本地预演**：网络慢时持续翻滚直到结果到达，绝不本地随机再纠正
- [x] 7.3 拍 3 逐格前进：按 `PLAYER_MOVED.path` 每格 120ms 抛物线小跳，格子依次点亮
- [x] 7.4 拍 4 过站结算：经过结算日时该格脉冲橙光 + 金额飘字 + 回执入栈，每次 0.9s，之后继续走
- [x] 7.5 拍 5 落点脉冲 0.4s
- [x] 7.6 拍 6–9 发牌：牌背从**落点格子**飞向屏心 0.5s → Y 轴 3D 翻转 0.45s → 定格标题扫光 0.6s → 帘幕上移、卡落进抽屉 half 档 0.4s。帘幕底色 = 该牌堆色 12% 叠纸底，牌背 = 米白卡纸 + 该牌堆色双线边框 + 宋体牌堆名；复用既有三种卡面组件按 `raw` 渲染，**全员同步播放**（帘幕落下后抽卡人得操作区，其他人 peek 显示「X 正在决定」）
- [x] 7.7 跳过：点击任意处**终止**当前序列并刷到终态（不是加速）
- [x] 7.8 `prefers-reduced-motion`：整条压成 120ms 淡入，棋子直接出现在落点（棋子位移要额外写一条 `transition: none`）
- [x] 7.9 设置里的「跳过动画」开关：存 localStorage、不进房间状态，默认关；与 7.7/7.8 同一条出口
- [x] 7.10 断线/重连：断线时顶部常驻红条 + 棋盘 `.offline-dim` + 骰盘禁用并写「重新连上之前，不能掷骰」；重连以快照为准，不补播错过的动效
- [x] 7.11 非我回合观战：中央骰盘变只读点数；抽屉 peek 一行写清他走到哪一步；peek 右侧头像列点开是 half 档牌桌（复用既有「非我回合的牌桌」）；房主代结束回合收进 `⋯`
- [x] 7.12 边界态呈现：停赛（不给骰盘 +「停赛中 · 还需跳过 N 轮」+「跳过本回合」）、破产清算（抽屉直升 full）、出局（棋子变灰**留原地**）、牌堆洗回（中央飘一行 1.6s，**不弹层**）
- [x] 7.13 撤销：撤抽卡时棋子**不回退**、发牌序列不重播、抽屉回到落点未决态；撤掷骰时位置与该次移动的结算/发牌一并从界面消失（design D13）。**由构造保证**：棋子位置只从 `state.players[*].rrPosition/ftPosition` 读，演出队列只认 `DICE_ROLLED/PLAYER_MOVED/CARD_DRAWN` 这几类，`HOST_REVERTED` 派生不出任何一拍，所以撤销既不会重播发牌也不会挪棋子；服务端侧由 `test_revert_draw_does_not_move_the_pawn` 钉死

## 8. 验收

- [x] 8.1 `npm run ui-smoke` 增加纯线上模式的一局，**共 13 屏**（18 建房选模式 / 19 大厅徽章 / 20 准备页模式锁 + 抽职业卡 / 21 棋盘选梦想 / 21a 收成摘要 / 22 待掷骰 / 23 观战 / 24 骰子与走格 / 25 机会格选大小 / 26 全屏发牌翻牌 / 26a 卡面决策 / 26b 旁观者同屏 / 26c 结束回合 / 27+27a+27b 账本三页 / 28 断线）。
      **点数由服务端摇、落到哪一格无法预设**，所以脚本反复掷到停在机会格为止（24 格里 12 个是机会），中途落点顺手处理掉。
      清单里余下的 **8 屏未进冒烟**，原因与去处写在这里，别当成漏做：
      · 慈善选粒数 / 过站结算 / 破产清算 —— 要特定落点或特定账面，掷骰随机时无法稳定构造，
        逻辑侧已由 `test_online_board.py` 的 `test_rat_race_two_dice_only_with_charity`、
        `test_pass_two_paydays_settles_twice`、`test_bankruptcy_during_move_stops_in_place` 钉死；
      · 市场风云抽卡人侧 / 牌桌 —— 呈现代码与线下模式同源（既有 08d、03f 两屏已覆盖）；
      · 跨轨道飞行 / 快车道棋盘 / 快车道格子详情 / 停在自己的梦想获胜 —— 纯线上要走到快车道
        得靠真实抽卡攒到「非工资收入 > 总支出」，随机牌堆下约需上百回合，脚本化只会做成一条
        必然抖动的用例。快车道轮盘本身已由 21 屏（准备页在同一只轮盘上选梦想）覆盖渲染链路，
        余下四项留给 **8.6 真机试玩**。
- [x] 8.1b ui-smoke 补两屏：准备页抽职业卡（抽过之后无重抽入口，20 屏）、准备页在快车道棋盘上选梦想（21 屏，含「别人选走的梦想插上圆点」断言）
- [x] 8.2 截图脚本跑完扫一遍 `.screen` 内 `scrollWidth > clientWidth` / `scrollHeight > clientHeight` 的元素并列出来（跳过可滚容器与 SVG 内部），文字溢出不靠肉眼查
- [x] 8.3 `npm run ui-smoke` 既有 38 屏（线下辅助模式）全部保持通过，连跑三次无抖动
- [x] 8.4 服务端全量测试通过，既有测试一条不改、一条不跳：**526 passed / 1 skipped**（动工前 459 passed / 1 skipped，新增 67 条）
- [x] 8.5 `python tools/validate_cards.py` 通过（含新增的棋盘校验）
- [ ] 8.6 真机试玩一局纯线上模式（手机竖屏），确认动效节奏、跳过、断线重连三项
- [x] 8.7 更新 CLAUDE.md 当前状态（新增 ㉕–㉙ 五条 + 必读清单把 design/09 提到第 1 位）、design/01（模式二从「暂缓」改为「已实现」，范围外与 M5 一并订正）、design/05（棋盘序列已核对，并写明它现在是引擎的取数来源）
