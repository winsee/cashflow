<script setup lang="ts">
/** 纯线上模式的房间骨架（design/09 §2）：HUD → 棋盘 stage → 底部三档抽屉。
 *
 *  **不复用四标签页、不出现 tabbar**——棋盘要占满、抽屉要能拉到 88%，两者都跟一条
 *  56px 的常驻标签栏抢位置。报表/总览/日志收进棋盘右上角的「📋 账本」（full 档 + 分段控件），
 *  它们是「随时可查」而不是「本回合待办」，本就不该和棋盘平级。
 *  既有 `ActionTab` 等只服务线下辅助模式，一行不改。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { bankRequest } from '../bankrequest'
import { confirmAction } from '../confirm'
import { majorStatus } from '../statuses'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import type { CardDto, Player } from '../types'
import BoardView from '../components/board/BoardView.vue'
import Die3d from '../components/board/Die3d.vue'
import { RINGS, squareViewportRect } from '../components/board/geom'
import type { BoardSquare } from '../components/board/geom'
import FtSquareCard from '../components/cards/FtSquareCard.vue'
import DealCurtain from '../components/board/DealCurtain.vue'
import OnlineCardPanel from '../components/board/OnlineCardPanel.vue'
import OnlineLandingPanel from '../components/board/OnlineLandingPanel.vue'
import PaydayCurtain from '../components/board/PaydayCurtain.vue'
import PlayerTableRow from '../components/PlayerTableRow.vue'
import PromptModal from '../components/PromptModal.vue'
import ReceiptStack from '../components/ReceiptStack.vue'
import SeatStrip from '../components/SeatStrip.vue'
import ResultView from '../components/ResultView.vue'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import FasttrackIntro from '../components/FasttrackIntro.vue'
import FasttrackCheer from '../components/FasttrackCheer.vue'
import StatementTab from '../components/StatementTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import BankruptcyPanel from '../components/tools/BankruptcyPanel.vue'
import FundsSheet from '../components/board/FundsSheet.vue'
import StatRow from '../components/base/StatRow.vue'

const game = useGame()
const finished = computed(() => game.state?.status === 'FINISHED')
const me = computed(() => game.me)
const ft = computed(() => me.value?.phase === 'FAST_TRACK')

onMounted(() => { game.fetchBoard() })

// ---------- HUD ----------

const progress = computed(() => {
  const m = me.value
  if (!m) return 0
  if (m.phase === 'FAST_TRACK') return ftWinProgress(m.fasttrack)
  const d = m.derived
  return d.totalExpenses ? Math.min(100, d.passiveIncome / d.totalExpenses * 100) : 100
})
const toWin = computed(() => {
  const f = me.value?.fasttrack
  return f ? Math.max(0, f.initial_income + FT_WIN_INCREMENT - f.current_income) : 0
})

/** 自己回合内、老鼠赛跑走过一格后进入快车道：本回合到此为止，别再糊出老鼠赛跑最后那张已结算的卡
 *  （`_a_entered_fasttrack` 不清空 `active_card`，卡本身已 resolved，只是不该再显示）。
 *  同 `FasttrackPanel.vue` 的 justLanded 判据，之前只 port 到了线下路径。 */
const justLanded = computed(() =>
  game.isMyTurn && !!game.state?.turnSquareUsed
  && me.value?.fasttrack.entered_turn === game.state?.turnCount)

/** 我的家底（design/09 §2.0 v0.12）：HUD 末行一条资产计数，点开是逐项明细。
 *
 *  两条口径与牌桌那一行同源：股票按**总股数**汇总（`stocks` 是批次数组，同一 symbol
 *  可能有多条不同成本的 lot），快车道下改数快车道企业（记录卡已翻面，老鼠赛跑那些
 *  资产不再参与计算，不该继续在 HUD 上报数）。
 *
 *  **一项都没有就整行不渲染**：开局摆一句「暂无资产」是废话；买下第一项时多出这一行，
 *  这个跳变本身就是「你开始有家底了」的信号。 */
const myAssets = computed<{ icon: string; count: string }[]>(() => {
  const m = me.value
  if (!m) return []
  if (m.phase === 'FAST_TRACK') {
    return m.fasttrack.businesses.length
      ? [{ icon: '🏢', count: `×${m.fasttrack.businesses.length}` }] : []
  }
  const out: { icon: string; count: string }[] = []
  if (m.realEstates.length) out.push({ icon: '🏠', count: `×${m.realEstates.length}` })
  if (m.businesses.length) out.push({ icon: '🏢', count: `×${m.businesses.length}` })
  const shares = m.stocks.reduce((a, s) => a + s.shares, 0)
  if (shares) out.push({ icon: '📈', count: `${shares.toLocaleString('en-US')} 股` })
  return out
})

/** 展开后的逐项明细。房产 / 企业给月现金流（它们的意义就是那笔钱），
 *  股票给持仓与成本（它没有月现金流，股利另算在利息/股利里）。 */
const myAssetRows = computed<{ icon: string; name: string; value: string; pos?: boolean }[]>(() => {
  const m = me.value
  if (!m) return []
  if (m.phase === 'FAST_TRACK') {
    return m.fasttrack.businesses.map(b => ({
      icon: '🏢', name: b.name, value: '+' + fmt(b.cashflow), pos: true,
    }))
  }
  const rows: { icon: string; name: string; value: string; pos?: boolean }[] = []
  for (const r of m.realEstates)
    rows.push({ icon: '🏠', name: r.name, value: (r.cashflow >= 0 ? '+' : '') + fmt(r.cashflow), pos: r.cashflow >= 0 })
  for (const b of m.businesses)
    rows.push({ icon: '🏢', name: b.name, value: (b.cashflow >= 0 ? '+' : '') + fmt(b.cashflow), pos: b.cashflow >= 0 })
  // 同一 symbol 的多个批次合成一行，成本取加权均价——分开列的话「我有多少 OK4U」要自己加
  const bySymbol = new Map<string, { shares: number; cost: number }>()
  for (const s of m.stocks) {
    const cur = bySymbol.get(s.symbol) ?? { shares: 0, cost: 0 }
    cur.shares += s.shares
    cur.cost += s.shares * s.cost_per_share
    bySymbol.set(s.symbol, cur)
  }
  for (const [symbol, v] of bySymbol)
    rows.push({
      icon: '📈',
      name: `${symbol} ×${v.shares.toLocaleString('en-US')}（成本 ${fmt(Math.round(v.cost / v.shares))}/股）`,
      value: fmt(v.cost),
    })
  return rows
})

/** 展开态**不撑高 HUD**，是从 HUD 下沿滑下来、压在棋盘上的一层浮层。
 *  棋盘 stage 的 `flex-basis` 是 0、负空间全由抽屉吸收，full 档下实测只剩 16px——
 *  HUD 再长高，先被挤没的是棋盘。过场与浮层可以叠上去，几何不动。 */
const assetsOpen = ref(false)
watch(myAssets, (a) => { if (!a.length) assetsOpen.value = false })

/** 观战牌桌（design/09 §6）：每位玩家走到回合的哪一步、账面什么样。
 *  全从已下发的字段派生，不加一次请求；口径与线下 `ActionTab.tableStepText` 同一套。 */
function stepTextOf(p: Player): string {
  const s = game.state!
  // 出局 / 破产清算 / 停赛这三句由状态徽章负责，这里不再说第二遍
  // （同「轮心把停赛说了两遍」那条：一个位置只有一个主人）
  if (p.phase === 'OUT' || p.inBankruptcy) return ''
  if (p.id !== s.currentPlayerId) return p.skipTurns ? '' : '等待中'
  if (!s.turnDiceUsed) return '正在掷骰'
  if (s.landing && !s.landing.resolved) return '正在处理落点'
  if (s.activeCard && !s.activeCard.resolved) return '正在决定这张卡'
  return '准备结束回合'
}

const tableRows = computed(() => (game.state?.players ?? []).map(p => ({
  id: p.id, p,
  now: p.id === game.state!.currentPlayerId,
  step: stepTextOf(p),
})))

// ---------- 棋盘 ----------

const RR_LABEL: Record<string, string> = {
  OPPORTUNITY: '', PAYDAY: '结算', MARKET: '市场', DOODAD: '支出',
  CHARITY: '慈善', CHILD: '孩子', UNEMPLOYMENT: '失业',
}

const FT_TYPE: Record<string, string> = {
  'ft-s-charity': 'FT_CHARITY', 'ft-s-cashflow-day': 'FT_PAYDAY',
  'ft-s-tax-audit': 'FT_TAX_AUDIT', 'ft-s-divorce': 'FT_DIVORCE',
  'ft-s-lawsuit': 'FT_LAWSUIT',
}

/** 快车道格子的类型由 ref 前缀给出（和服务端 `_ft_square_type` 同一条规则） */
function ftType(ref: string): string {
  if (ref.startsWith('ft-b-')) return 'FT_BUSINESS'
  if (ref.startsWith('ft-d-')) return 'FT_DREAM'
  return FT_TYPE[ref] ?? 'FT_LAWSUIT'
}

function hue(seat: number): number { return (seat * 67 + 120) % 360 }

const squares = computed<BoardSquare[]>(() => {
  const b = game.board
  if (!b) return []
  if (ft.value) {
    const claimed = new Map<string, string>()
    for (const p of game.state?.players ?? [])
      if (p.dreamId) claimed.set(p.dreamId, `hsl(${hue(p.seat)} 55% 62%)`)
    return b.fastTrack.squares.map((ref, i) => ({
      index: i + 1, type: ftType(ref), ref, label: '',
      faded: (game.state?.ftSoldSquares ?? []).includes(ref),
      dot: claimed.get(ref),
    }))
  }
  return b.ratRace.squares.map((sq, i) => ({
    index: i + 1, type: sq.type, ref: sq.id, label: RR_LABEL[sq.type] ?? sq.name,
  }))
})

/** 演出期间按 stagePos 画，播完回到权威位置 */
const positions = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const p of game.state?.players ?? [])
    out[p.id] = game.stagePos[p.id] ?? (ft.value ? p.ftPosition : p.rrPosition)
  return out
})

const currentIndex = computed(() => {
  const cur = game.state?.currentPlayerId
  return cur ? positions.value[cur] : undefined
})

/** 走过的格子（trail）：本次移动逐格点亮，下一次掷骰清空 */
const trail = ref<number[]>([])
watch(() => game.stageNow, (s) => {
  if (!s) return
  if (s.kind === 'dice') trail.value = []
  if (s.kind === 'step') trail.value = [...trail.value, s.index]
})

const settleStep = computed(() =>
  game.stageNow?.kind === 'settle' ? game.stageNow : null)
/** 发薪帘幕**只给当事人**——别人的回合也弹全屏就成了刷屏。
 *  旁观者拿到的是板上那一拍橙光飘字 + 座次条上的瞬时金额。
 *  破产那一批不弹：清算屏之前不该先演一场庆祝仪式（stage.ts 的 `bankrupting`）。 */
const paydayStep = computed(() =>
  settleStep.value
    && settleStep.value.playerId === game.session?.playerId
    && !settleStep.value.bankrupting
    ? settleStep.value : null)
const pulseIndex = computed(() =>
  game.stageNow?.kind === 'landing' ? game.stageNow.index : undefined)

/** 快车道格面不写字，点任意格弹详情——这是 24px 的弧读不出内容的补偿 */
const detail = ref<BoardSquare | null>(null)
function tapSquare(sq: BoardSquare) { detail.value = sq }
const detailBiz = computed(() =>
  game.board?.fastTrack.businesses.find(b => b.id === detail.value?.ref) ?? null)
const detailDream = computed(() =>
  game.board?.fastTrack.dreams.find(d => d.id === detail.value?.ref) ?? null)

// ---------- 骰子 ----------

/** 粒数上限按赛道分开：老鼠赛跑慈善给 1–2 粒 3 轮，快车道慈善给 1–3 粒且永久（P.4 / P.6） */
const diceMax = computed(() => {
  const m = me.value
  if (!m) return 1
  return m.phase === 'FAST_TRACK'
    ? (m.fasttrack.charity_forever ? 3 : 2)
    : (m.charityTurns > 0 ? 2 : 1)
})
// 默认预选允许的最大粒数：手滑直接点掷骰按钮，掷出的也是对自己最有利的选择
const diceCount = ref(1)
watch(diceMax, v => { diceCount.value = v }, { immediate: true })

// 只有翻滚那一拍是 rolling；`settling` 那一拍骰子已经落定，点数就该亮着
const rolling = computed(() =>
  game.stageNow?.kind === 'dice' && !game.stageNow.settling)
const shownRolls = computed(() => {
  if (game.stageNow?.kind === 'dice') return game.stageNow.rolls
  return game.lastRolls
})
// 换人就把上一位的点数收走（换轮次不行：一轮里每个人都掷过一次）
watch(() => game.state?.currentPlayerId, () => { game.lastRolls = [] })

const canRoll = computed(() =>
  game.isMyTurn && game.connected && !!me.value
  && !me.value.inBankruptcy && me.value.skipTurns === 0
  && me.value.phase !== 'OUT' && !game.state?.turnDiceUsed)

async function roll() {
  if (!canRoll.value) return
  await game.rollDice(diceCount.value)
}

// ---------- 回合三步 ----------

const landing = computed(() => game.state?.landing ?? null)
const step = computed<1 | 2 | 3>(() => {
  if (!game.state?.turnDiceUsed) return 1
  if (landing.value && !landing.value.resolved) return 2
  if (game.state.activeCard && !game.state.activeCard.resolved) return 2
  return 3
})

/** 演出还在播：**界面此刻显示到哪一帧由 stage 说了算，不由权威状态说了算**。
 *
 *  服务端一批事件里，移动和它的后果是一起到的，`this.state` 在 `ingestStage()` 之后
 *  立刻就换成了「这一切都已经发生完」的样子。不按住的话，牌还没翻过来卡片就躺在抽屉里了，
 *  帘幕落下时它还在那儿——演出成了状态的追认，而不是状态的呈现。
 *  发牌是队列的最后一拍，所以这道门一开，卡片正好在收牌之后落进抽屉（design/09 §5.1 第 9 拍）。
 */
const held = computed(() => game.staging)
const heldTip = computed(() => {
  switch (game.stageNow?.kind) {
    case 'dice': return game.stageNow.settling
      ? `掷出 ${game.stageNow.rolls.reduce((a, b) => a + b, 0)} 点` : '骰子还在转…'
    case 'deal': return '正在发牌…'
    case 'reshuffle': return '正在洗牌…'
    default: return '正在移动…'
  }
})

/** 我身上优先级最高的持续状态（停赛 / 慈善 / 破产 …）：轮心与 peek 条共用这一句 */
const myStatus = computed(() => (me.value ? majorStatus(me.value) : null))

const hubTip = computed(() => {
  if (!game.connected) return '重新连上之前，不能掷骰'
  if (held.value) return heldTip.value
  if (!game.isMyTurn) return `${game.currentPlayer?.nickname ?? '对手'} 正在行动`
  // 「停赛中 · 还需跳过 N 轮」与牌桌、总览、座次条同一份派生，不在这里另写一遍
  if (me.value?.skipTurns) return myStatus.value?.label ?? ''
  if (step.value === 1) return '点骰子开始这一回合'
  if (step.value === 2) return landing.value?.note || '这一格还欠你一个决定'
  return '这一格处理完了'
})

const activeCardInfo = ref<CardDto | null>(null)
watch(() => game.state?.activeCard?.card_id, async (id) => {
  if (!id) { activeCardInfo.value = null; return }
  const list = await game.fetchCards(game.state!.activeCard!.deck)
  activeCardInfo.value = list.find(c => c.id === id) ?? null
}, { immediate: true })

async function endTurn() {
  const ok = await confirmAction({
    title: '结束本回合？',
    lines: ft.value
      ? ['结束后本回合的现金流量日与格子操作都不能再补。']
      : ['结束后本回合的银行结算日与格子操作都不能再补。'],
    okText: '结束回合',
  })
  if (ok) await game.act('END_TURN')
}

// ---------- 三档抽屉 ----------

type Detent = 'peek' | 'half' | 'full'
type LedgerPage = 'statement' | 'overview' | 'log'
const DETENT_H: Record<Detent, string> = { peek: '128px', half: '46dvh', full: '88dvh' }
const RANK: Record<Detent, number> = { peek: 0, half: 1, full: 2 }
const ORDER: Detent[] = ['peek', 'half', 'full']
const detent = ref<Detent>('peek')
const ledger = ref<null | LedgerPage>(null)

/** 牌桌是**显式的内容态**（design/09 §6 v0.12），不再是「默认层里恰好没别的东西」的兜底。
 *
 *  v0.11 之前它的条件是 `!isMyTurn && (held || !activeCardInfo)`，而 `activeCard` 从抽卡
 *  一直活到回合结束——于是别人一个回合里牌桌能露脸的窗口只剩「掷骰 → 落点」那几秒
 *  （房主：「一旦他抽了卡之后，就会被那个卡片的事件覆盖」）。更要命的是座次条的
 *  `@open` 改的是**档位**不是内容，「点头像列看牌桌」这个心智模型从来没对齐过。
 *
 *  现在它与 `ledger` 同一范式：点座次条开，牌桌**压过卡面与落点卡**。
 *  主动打开的东西盖住被动内容是这套界面既有的规矩（同 `FundsSheet`）——
 *  牌桌不是系统弹给你的，是你自己伸手要的。 */
const table = ref(false)
function toggleTable() {
  table.value = !table.value
  if (table.value && RANK[detent.value] < RANK.half) detent.value = 'half'
}

/** 档位由内容决定，不由用户记忆决定 */
const wantDetent = computed<Detent>(() => {
  if (ledger.value) return 'full'
  if (me.value?.inBankruptcy) return 'full'
  // 牌桌是自己要来的，不该被别的事按回 peek；但它也只要半档，不抢满屏
  if (table.value) return 'half'
  // 演出没播完就不动档位：牌还没翻过来，抽屉不该先弹起来抢戏。
  // 返回当前档而不是 'peek'——玩家自己拉起来看牌桌的抽屉，不该被一次掷骰按回去。
  if (held.value) return detent.value
  if (game.state?.activeCard || (landing.value && !landing.value.resolved)) return 'half'
  // peek 档只有 128px，扣掉把手、状态条与钉底的按钮条，正文剩不下几十像素。
  // 所以这两样东西一出现就得提档，否则等于没给：
  // ① 没确认的回执；② 落点结果卡（这一格没问过我就处理完了，得有个地方说清楚）
  if (game.receipts.length) return 'half'
  if (game.isMyTurn && landing.value?.resolved && !game.state?.activeCard) return 'half'
  return 'peek'
})
/** 用户可以拖动覆盖，但下一次系统事件会重新提档，且**提档只升不降**——
 *  别人抽的市场卡要我答复时，不能因为我刚把抽屉推下去就把这件事藏起来。 */
watch(wantDetent, (w) => {
  if (RANK[w] > RANK[detent.value]) detent.value = w
  else if (w === 'peek' && !ledger.value) detent.value = 'peek'
})

/** 跟手期间抽屉的实时像素高（null = 没在拖，交回档位说了算） */
const dragH = ref<number | null>(null)
const dragging = computed(() => dragH.value !== null)
const drawerH = computed(() =>
  dragH.value !== null ? `${dragH.value}px` : DETENT_H[detent.value])
/** 档位切换缩的是棋盘**自身的宽度变量**（stage 有 overflow:hidden，缩 stage 等于白缩） */
const boardWidth = computed(() =>
  detent.value === 'full' ? '150px' : detent.value === 'half' ? '230px' : '332px')

/** 抽屉的手势（design/09 §2.2 v0.10）：**整块都接**，不只那根 34×4px 的把手。
 *
 *  v0.7 把手从「只认拖拽」补成「也认点击」，解决的是「点了没反应」；把手势限死在
 *  把手上是当时省下的一步，真机上的代价是：想收抽屉只能去够那根小横条，
 *  而在正文里往下拉换来的是**浏览器把整页刷新掉**（滚动链溢出到根，见 style.css
 *  那几条 `overscroll-behavior` / `touch-action`）。
 *
 *  现在三处入口共用同一台状态机：
 *  - 把手：跟手 + **点击**（peek 档点是展开，其余档位点是退一步；账本的「退一步」
 *    是整个关掉账本，不停在 half——账本只有 full 一种形态）
 *  - 状态条：只跟手。它从来不是个按钮，给它点击语义等于凭空多一个不写在脸上的开关
 *  - 正文：只跟手，且要先判归属（见 `onBodyMove`）——那儿的主人是滚动
 *
 *  松手就近吸附到三档里最近的一档；`ORDER` 的逐档升降只留给点击与合成事件。 */
const drawerEl = ref<HTMLElement | null>(null)
const TAP_DY = 24        // 把手：位移不到这个数算点击
const BODY_DY = 12       // 正文：起判要早于浏览器决定滚动
let dragFromY = 0
let dragFromH = 0

function raise() {
  detent.value = ORDER[Math.min(ORDER.length - 1, ORDER.indexOf(detent.value) + 1)]
}
function lower() {
  if (ledger.value) { closeLedger(); return }
  // 牌桌只有 half 一种形态，收下去就是关掉它（同账本那条）
  if (table.value) { table.value = false; detent.value = wantDetent.value; return }
  detent.value = ORDER[Math.max(0, ORDER.indexOf(detent.value) - 1)]
}

/** 三档的像素高。full 实际被 `flex: 0 1 auto` 压过，但标称值单调，够拿来就近吸附 */
function detentPx(): Record<Detent, number> {
  const vh = window.innerHeight
  return { peek: 128, half: vh * 0.46, full: vh * 0.88 }
}
function nearestDetent(h: number): Detent {
  const px = detentPx()
  return ORDER.reduce((best, d) =>
    Math.abs(px[d] - h) < Math.abs(px[best] - h) ? d : best, ORDER[0])
}

function beginDrag(y: number) {
  dragFromY = y
  // **实测**起始高，不用标称值：full 档被 flex 压过，标称 88dvh 不是它的真高度
  dragFromH = drawerEl.value?.offsetHeight ?? 128
}
function moveDrag(y: number) {
  const px = detentPx()
  dragH.value = Math.min(px.full, Math.max(px.peek, dragFromH - (y - dragFromY)))
}
/** @param tappable 位移不够时算不算一次点击（只有把手算） */
function endDrag(y: number, tappable: boolean) {
  const dy = y - dragFromY
  const followed = dragH.value !== null
  dragH.value = null
  // 位移不到 TAP_DY 一律不换档（跟过手的就弹回原档）：手指点一下难免带三五像素，
  // 拿「有没有 move 事件」当判据的话，点一下把手就成了拖一下，什么都不会发生
  if (Math.abs(dy) < TAP_DY) {
    if (tappable) detent.value === 'peek' ? raise() : lower()
    return
  }
  // 账本只有 full 一种形态，半开着既读不成也让不开路：向下就整个关掉，向上留在 full
  if (ledger.value) { if (dy > 0) closeLedger(); return }
  // 牌桌同理：向下拖就是收起它，不停在 peek 档看半行
  if (table.value && dy > 0) { table.value = false; detent.value = wantDetent.value; return }
  // 没跟过手（合成事件、或指针一步到位）就退回逐档升降
  if (!followed) { dy < 0 ? raise() : lower(); return }
  detent.value = nearestDetent(dragFromH - dy)
}

// ---- 入口一/二：把手与状态条（都是 touch-action:none 的非滚动块，pointer 事件够用）----

function onGrab(e: PointerEvent) {
  beginDrag(e.clientY)
  // 指针已经不活跃时 setPointerCapture 会抛 NotFoundError；捕获只是为了拖得跟手，
  // 抓不到也不该把这一次交互整个废掉（下面的 pointerup 照样要认）
  try { (e.target as HTMLElement).setPointerCapture(e.pointerId) } catch { /* 无妨 */ }
}
function onGrabMove(e: PointerEvent) {
  if (!e.buttons && e.pointerType === 'mouse') return
  if (dragH.value === null && Math.abs(e.clientY - dragFromY) < 3) return
  moveDrag(e.clientY)
}
function onGrabUp(e: PointerEvent) { endDrag(e.clientY, true) }

/** 状态条：里头有头像列和「⋯ 代结束」，从按钮上起手的不是拖抽屉 */
let peekArmed = false
function onPeekDown(e: PointerEvent) {
  peekArmed = !(e.target as HTMLElement).closest('button, a, input, select')
  if (!peekArmed) return
  onGrab(e)
}
function onPeekMove(e: PointerEvent) { if (peekArmed) onGrabMove(e) }
function onPeekUp(e: PointerEvent) {
  if (!peekArmed) return
  peekArmed = false
  endDrag(e.clientY, false)   // 状态条不认点击
}

// ---- 入口三：正文。这里的主人是滚动，抽屉只在滚不动的方向上接管 ----

/** null = 还没判；'drawer' = 归抽屉；'scroll' = 归原生滚动，这一次触摸不再重判
 *  （滚到顶就突然被抽屉接管，是比「拖不动」更糟的手感） */
let bodyOwner: null | 'drawer' | 'scroll' = null

/** 正文必须用 touch 事件而不是 pointer：要在浏览器把手势判成滚动**之前**
 *  `preventDefault()` 才抢得过来，而 `touch-action: pan-y` 下滚动一开始，
 *  pointermove 就被 `pointercancel` 掉了。Vue 3 的 `@touchmove` 默认非 passive，正合用。 */
function onBodyStart(e: TouchEvent) {
  if (e.touches.length !== 1) { bodyOwner = 'scroll'; return }
  bodyOwner = null
  beginDrag(e.touches[0].clientY)
}
function onBodyMove(e: TouchEvent) {
  if (bodyOwner === 'scroll' || e.touches.length !== 1) return
  const y = e.touches[0].clientY
  const dy = y - dragFromY
  if (bodyOwner === null) {
    if (Math.abs(dy) < BODY_DY) return
    const el = e.currentTarget as HTMLElement
    const scrollable = el.scrollHeight - el.clientHeight > 2
    // 向下且已经在顶（再滚也没得滚，这一拉本来就要溢出给浏览器去刷新整页）→ 归抽屉
    // 向上且正文根本滚不动（peek 档的常态）→ 归抽屉
    bodyOwner = (dy > 0 ? el.scrollTop <= 0 : !scrollable) ? 'drawer' : 'scroll'
    if (bodyOwner === 'scroll') return
  }
  e.preventDefault()
  moveDrag(y)
}
function onBodyEnd(e: TouchEvent) {
  const owner = bodyOwner
  bodyOwner = null
  if (owner !== 'drawer') return
  // 松手时也要 preventDefault：否则浏览器会朝手指底下那个东西补一次 click，
  // 而正文里全是「买入 / 放弃」——拖一下抽屉顺手买了张卡是不可接受的
  e.preventDefault()
  endDrag(e.changedTouches[0]?.clientY ?? dragFromY, false)
}

function openLedger(page: LedgerPage = 'statement') {
  ledger.value = page
  table.value = false        // 账本与牌桌是两屏，不叠在一起
  detent.value = 'full'
}
function closeLedger() {
  ledger.value = null
  detent.value = wantDetent.value
}

// 进入破产清算时把账本与牌桌都收掉：清算期间抽屉里只该有清算面板
watch(() => me.value?.inBankruptcy, (v) => { if (v) { ledger.value = null; table.value = false } })

/** 牌桌让位的两处（照 §2.3「我的待办优先于我自己翻开的东西」）：
 *  ① 轮到我了——该我掷骰了，围观到此为止；
 *  ② 有人的动作要我答复——`PromptModal` 一到，压在下面的牌桌只是噪音。 */
watch(() => game.isMyTurn, (mine) => { if (mine) table.value = false })
watch(() => game.myPrompts.length, (n) => { if (n) table.value = false })

// ---------- 资金弹层（银行 · 转账 · 破产入口 · 显示设置） ----------

const funds = ref(false)
const fundsSheet = ref<InstanceType<typeof FundsSheet> | null>(null)

/** 绝不叠弹层（design/09 §2.3）：别人的动作要我答复时，我自己翻开的这一层让位。
 *  反方向不用管——`.modal-mask` 是全屏 fixed 且压在 `.board-tools` 之上，
 *  `PromptModal` 在场时那枚 🏦 本来就点不到。 */
watch(() => game.myPrompts.length, (n) => { if (n) funds.value = false })

// 现金不足的三处提示点「去贷款」→ 打开资金弹层的银行块，并把缺口预填进去
watch(bankRequest, async (req) => {
  if (!req) return
  funds.value = true
  await nextTick()
  fundsSheet.value?.prefillBank(req.need)
})

// ---------- 逃出老鼠赛跑（沿用线下模式那一套判据与 sessionStorage 记忆） ----------

const showIntro = ref(false)
const canEscape = computed(() =>
  !!me.value && me.value.phase === 'RAT_RACE' && !me.value.inBankruptcy
  && me.value.derived.canEnterFasttrack)
const escapeReady = computed(() =>
  canEscape.value && game.isMyTurn && !game.myPrompts.length
  && !(game.state?.activeCard && !game.state.activeCard.resolved))
const dismissKey = computed(() =>
  `ftIntro:${game.session?.roomCode ?? ''}:${game.session?.playerId ?? ''}`)
const introDismissed = ref(sessionStorage.getItem(dismissKey.value) === '1')
watch(escapeReady, v => { if (v && !introDismissed.value) showIntro.value = true }, { immediate: true })
watch(canEscape, v => {
  if (!v) {
    showIntro.value = false
    introDismissed.value = false
    sessionStorage.removeItem(dismissKey.value)
  }
})
function dismissIntro() {
  showIntro.value = false
  introDismissed.value = true
  sessionStorage.setItem(dismissKey.value, '1')
}
async function confirmEnterFasttrack() {
  if (await game.act('ENTER_FASTTRACK')) {
    showIntro.value = false
    sessionStorage.removeItem(dismissKey.value)
    game.flash('🏁 你进入快车道了，启动资金已到账', 'gold')
  }
}

const dealStep = computed(() => game.stageNow?.kind === 'deal' ? game.stageNow : null)

/** 发牌帘幕的**起飞矩形** = 抽卡人停的那一格此刻在屏上的位置（design/09 §5.1 拍 6）。
 *  `stage.ts` 一直算着 `fromIndex`，此前一路没人用——于是屏上只剩一次没有起点的原地放大，
 *  眼睛读不出「牌从哪儿来」，只能读成「牌背的尺寸变了一下」。
 *
 *  量不到就给 `null`（位置 0 是起点标记不是格子；棋盘在 full 档被压成一条时也量不到），
 *  组件那边自会退回不带锚点的老行为。 */
const boardRef = ref<InstanceType<typeof BoardView> | null>(null)
const dealFrom = computed(() => {
  const from = dealStep.value?.fromIndex ?? 0
  if (!from) return null
  return squareViewportRect(
    boardRef.value?.disc, from, squares.value.length,
    RINGS[ft.value ? 'FAST_TRACK' : 'RAT_RACE'],
  )
})

/** 这张卡此刻要不要给我一排决策按钮（钉在抽屉底） */
const cardCta = computed(() => {
  const ac = game.state?.activeCard
  if (held.value) return null            // 牌还没翻过来，按钮不能先摆出来
  if (!ac || ac.resolved || !activeCardInfo.value) return null
  return ac.drawer_id === game.session?.playerId ? ac : null
})
async function decide(decision: string) {
  await game.act('CARD_DECISION', { decision })
}

/** 现在还不能结束回合的话，写清在等什么（与服务端 `_d_end_turn` 的两道闸门同口径） */
const blockedBy = computed(() => {
  const ac = game.state?.activeCard
  if (ac && !ac.resolved && ['EXPENSE_EVENT', 'CASH', 'CREDIT_OPTION', 'INSTALLMENT',
    'STOCK_EVENT'].includes(ac.subtype)) return '先结算这张卡'
  const lg = landing.value
  if (lg && !lg.resolved) {
    if (lg.type === 'OPPORTUNITY') return '先抽一张牌'
    if (lg.type === 'UNEMPLOYMENT') return '先支付失业损失'
  }
  return ''
})
</script>

<template>
  <ResultView v-if="finished" />

  <div class="board-page" v-else-if="game.state && me">
    <!-- ===== HUD ===== -->
    <div class="hud" :class="{ 'offline-dim': !game.connected }">
      <div>
        <div class="lab">银行储蓄</div>
        <div class="cash money">{{ fmt(me.cash) }}</div>
      </div>
      <div class="hud-side">
        <template v-if="ft">
          <div class="lab">现金流量日收入</div>
          <div class="flow money" style="color:var(--gold-deep)">{{ fmt(me.fasttrack.current_income) }}</div>
        </template>
        <template v-else>
          <div class="lab">月现金流</div>
          <div class="flow money" :class="me.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">
            {{ me.derived.monthlyCashflow >= 0 ? '+' : '' }}{{ fmt(me.derived.monthlyCashflow) }}
          </div>
        </template>
      </div>
      <div class="hud-turn">
        <template v-if="game.isMyTurn"><span class="live-dot"></span> <b>轮到你了</b></template>
        <template v-else>等待 {{ game.currentPlayer?.nickname ?? '—' }} 行动</template>
        · 第 {{ game.state.turnCount }} 轮
        <span v-if="!game.connected" style="color:var(--red)">· 重连中…</span>
        <span class="grow"></span>
        <!-- HUD 这条也是牌桌的开关（peek 条那条同理）：两处长得一样、管的是同一件事，
             就不该只有一处能点 -->
        <SeatStrip clickable :active="table" @open="toggleTable" />
      </div>
      <template v-if="me.phase !== 'OUT'">
        <div class="hud-goal">
          <span v-if="ft">距胜利还差 {{ fmt(toWin) }}</span>
          <span v-else>离快车道 · 非工资收入 {{ fmt(me.derived.passiveIncome) }} /
            总支出 {{ fmt(me.derived.totalExpenses) }}</span>
          <span class="grow"></span>
          <span>{{ Math.round(progress) }}%</span>
        </div>
        <div class="progress" :class="{ gold: ft }">
          <div :style="{ width: progress + '%' }" />
        </div>
      </template>
      <!-- 我的家底：一项都没有就整行不在（开局不摆「暂无资产」这句废话） -->
      <button v-if="myAssets.length" class="hud-assets" :class="{ on: assetsOpen }"
              :aria-expanded="assetsOpen" @click="assetsOpen = !assetsOpen">
        <span v-for="a in myAssets" :key="a.icon">{{ a.icon }}{{ a.count }}</span>
        <span class="grow"></span>
        <span class="chev">{{ assetsOpen ? '⌄' : '›' }}</span>
      </button>
    </div>

    <!-- ===== 棋盘 =====
         演出进行中点棋盘任意处即**终止**当前序列并刷到终态（不是加速）：
         玩到第 20 轮的人不该被自己看过 20 遍的动画拖住 -->
    <div class="board-stage"
         :class="{ 'card-open': (!held && !!game.state.activeCard) || assetsOpen }"
         :style="{ '--bw': boardWidth }"
         @click="assetsOpen ? (assetsOpen = false) : (game.staging && game.skipStage())">
      <!-- 悬浮工具挂在 stage 内部的右上角（design/09 §8）。
           🏦 排最上：三个里只有它是「事到临头才需要」的，另外两个是随便什么时候翻翻。
           **full 档整列收起**：那时 stage 只剩 16px（HUD + 88dvh 已超一屏，负空间全由抽屉吸收，
           而 stage 的 flex-basis 是 0），三枚圆钮会被 `overflow:hidden` 切成一条边——
           一枚切了一半的圆看着像渲染坏了，而不像一个决定。full 档只在「账本打开」与
           「破产清算」两种情形出现，前者点一下把手就退出来，后者本就只该有清算面板。 -->
      <div v-if="detent !== 'full'" class="board-tools">
        <button class="board-float" title="资金" @click="funds = true">🏦</button>
        <button class="board-float" title="账本" @click="openLedger()">📋</button>
        <router-link to="/manual" class="board-float" title="说明书">📖</router-link>
      </div>

      <BoardView ref="boardRef" :track="ft ? 'FAST_TRACK' : 'RAT_RACE'" :squares="squares"
                 :players="game.state.players" :positions="positions"
                 :me-id="game.session?.playerId ?? ''"
                 :current-index="currentIndex" :trail="trail"
                 :settle-index="settleStep?.index" :settle-amount="settleStep?.amount"
                 :settle-mine="!!paydayStep"
                 :pulse-index="pulseIndex" :compact="detent !== 'peek'"
                 :offline="!game.connected" @tap="tapSquare">
        <template #hub>
          <!-- 轮心只放骰盘 + 一行状态提示；轮次归 HUD，进度归 HUD 进度带。
               停赛的人不给骰盘——那是一个按下必被拒的按钮。
               **但也不在这里另写一行「停赛中」**：那句话是状态提示的职责，
               `hubTip` 已经说了，两处都写就会在轮心里重复两遍（第二轮试玩） -->
          <div v-if="!(game.isMyTurn && me.skipTurns)" class="board-dice"
               :class="`n${Math.max(1, shownRolls.length || diceCount)}`">
            <Die3d v-for="i in Math.max(1, shownRolls.length || diceCount)" :key="i"
                   :index="i - 1" :value="rolling ? null : (shownRolls[i - 1] ?? null)"
                   :rolling="rolling" :rollable="canRoll" @roll="roll" />
          </div>
          <!-- 慈善生效时粒数选择器**替换**状态提示行（不叠高度、不弹层） -->
          <div v-if="canRoll && diceMax > 1" class="dice-pick"
               @click.stop>
            <button v-for="n in diceMax" :key="n" :class="{ on: diceCount === n }"
                    @click="diceCount = n">{{ n }} 粒</button>
          </div>
          <div v-else class="hub-tip">{{ hubTip }}</div>
        </template>
      </BoardView>

      <div v-if="game.stageFlash" class="board-flash">{{ game.stageFlash }}</div>

      <!-- 资产明细浮层：贴 HUD 下沿落在棋盘上，HUD 与抽屉的高度一个像素都不动。
           点浮层外任意处收起（由 `.board-stage` 那个 @click 接住） -->
      <div v-if="assetsOpen" class="asset-pop" @click.stop>
        <div v-for="(r, i) in myAssetRows" :key="i" class="arow">
          <span>{{ r.icon }}</span>
          <span class="nm">{{ r.name }}</span>
          <span class="vl" :class="r.pos === undefined ? '' : (r.pos ? 'pos' : 'neg')">{{ r.value }}</span>
        </div>
        <button class="foot" @click="assetsOpen = false; openLedger('statement')">
          查看完整报表 ›
        </button>
      </div>
    </div>

    <!-- ===== 底部三档抽屉 ===== -->
    <div ref="drawerEl" class="board-drawer" :class="{ dragging }" :style="{ '--dh': drawerH }">
      <!-- 把手：跟手 + 点击（§2.2 v0.10）。用 `<button>` 而不是 `<div>`：
           它能点，语义与键盘可达性得跟上；裸 button 早已被重置成中性，视觉不变。
           手势现在铺到了整个抽屉，但**点击只有这一根认**——状态条和正文不是按钮。 -->
      <button class="sheet-grab grabbable"
              :aria-label="detent === 'peek' ? '展开抽屉' : (ledger ? '收起账本' : '收起抽屉')"
              @pointerdown="onGrab" @pointermove="onGrabMove"
              @pointerup="onGrabUp" @pointercancel="onGrabUp"></button>

      <!-- 状态条也能拖：整块抽屉都该跟手，而不是只有那根 34×4px 的小横条 -->
      <div class="drawer-peek"
           @pointerdown="onPeekDown" @pointermove="onPeekMove"
           @pointerup="onPeekUp" @pointercancel="onPeekUp">
        <!-- 破产清算优先于一切：这时候抽屉里只有清算面板，分段控件让位 -->
        <template v-if="me.inBankruptcy">
          <b class="who">破产清算</b>
          <span class="muted">卖资产直到月现金流转正</span>
        </template>
        <!-- 账本打开时状态条上**只剩标题**：分段控件在内容区顶部，收起归把手。
             从前这里还挂着一枚「收起 ✕」——一枚实心描边按钮，只为关一个本来就有把手的抽屉 -->
        <template v-else-if="ledger">
          <b class="who">账本</b>
        </template>
        <!-- 牌桌开着时状态条只写标题 + 轮次：正文里逐人都写全了，这里不再复述谁在做什么 -->
        <template v-else-if="table">
          <b class="who">牌桌</b>
          <span class="muted">第 {{ game.state.turnCount }} 轮</span>
          <span class="grow"></span>
          <SeatStrip clickable active @open="toggleTable" />
        </template>
        <template v-else-if="!game.isMyTurn">
          <span class="who">{{ game.currentPlayer?.nickname ?? '对手' }}</span>
          <span class="muted">
            <template v-if="held">{{ heldTip }}</template>
            <template v-else-if="!game.state.turnDiceUsed">还没掷骰</template>
            <template v-else-if="landing && !landing.resolved">正在决定</template>
            <template v-else>准备结束回合</template>
          </span>
          <span class="grow"></span>
          <!-- 头像列就是牌桌的开关：围观也是玩，别人的账面不该只能靠猜 -->
          <SeatStrip clickable @open="toggleTable" />
          <button v-if="me.isHost" class="btn ghost small"
                  @click="game.act('HOST_END_TURN')">⋯ 代结束</button>
        </template>
        <template v-else-if="held">
          <span class="who">{{ heldTip }}</span>
        </template>
        <template v-else>
          <span class="who">第 {{ step }} 步 / 3</span>
          <span class="muted">
            <template v-if="myStatus">{{ myStatus.label }}</template>
            <template v-else-if="step === 1">掷骰</template>
            <template v-else-if="step === 2">处理落点</template>
            <template v-else>可以结束回合</template>
          </span>
        </template>
      </div>

      <!-- 正文的主人是滚动，抽屉只在滚不动的那个方向上接管（见 `onBodyMove` 的判归属）。
           在这儿往下拉从前是把整页交给浏览器去刷新——对局中途的一次误刷新，
           代价远大于一个没收起来的抽屉。 -->
      <div class="drawer-body"
           @touchstart="onBodyStart" @touchmove="onBodyMove"
           @touchend="onBodyEnd" @touchcancel="onBodyEnd">
        <!-- 破产清算：抽屉自动升到 full 档，里面只有这块面板——
             卖资产、还贷、完成清算，每一步都得走得完，否则一破产就锁死 -->
        <template v-if="me.inBankruptcy">
          <BankruptcyPanel :show-resolve="false" />
        </template>
        <!-- 分段控件钉在内容区顶部：三段等宽、任何屏宽都排得下一行。
             第四段「更多」（银行/转账/破产/显示设置）已搬去悬浮的资金弹层——
             账本是「随时可查」的三张表，资金是「事到临头要动手」的工具，两回事 -->
        <template v-else-if="ledger">
          <div class="ledger-seg">
            <button :class="{ on: ledger === 'statement' }" @click="ledger = 'statement'">报表</button>
            <button :class="{ on: ledger === 'overview' }" @click="ledger = 'overview'">总览</button>
            <button :class="{ on: ledger === 'log' }" @click="ledger = 'log'">日志</button>
          </div>
          <StatementTab v-if="ledger === 'statement'" />
          <OverviewTab v-else-if="ledger === 'overview'" />
          <LogTab v-else />
        </template>
        <!-- 牌桌（显式态）：压过卡面与落点卡。标题归状态条，这里直接是人。
             回执照旧渲染——它是「刚刚发生在你身上」的事，不能因为我在围观就被吞掉 -->
        <template v-else-if="table">
          <ReceiptStack />
          <PlayerTableRow v-for="r in tableRows" :key="r.id" inner
                          :player="r.p" :step="r.step" :now="r.now" :self="r.id === me.id" />
        </template>
        <template v-else>
          <div v-if="!game.connected" class="card quiet" style="padding:14px;text-align:center">
            <span class="muted">重新连上之前，操作暂不可用</span>
          </div>
          <!-- 停赛（skip_turns>0）不在此另开分支：`_advance_turn` 对停赛玩家静默递减 +
               continue，从不让他们成为 current player，所以这个条件与 `isMyTurn` 同时成立
               时，只可能是停赛刚刚生效的那一回合（失业已结算/破产刚复活）——玩家这一回合
               正常行动过，不是"什么都不能做只能跳过"，按普通回合处理即可，见下方 ReceiptStack /
               OnlineLandingPanel 与结束回合按钮。停赛状态本身由 hubTip 与座次条/牌桌/总览角标
               持续展示，不靠这里。 -->
          <div v-else-if="me.phase === 'OUT'" class="card inner muted">
            你已出局 · 可以继续观战
          </div>
          <!-- 「刚刚发生在你身上」：银行结算日、别人的市场卡波及到我……
               这些事没经我的手就改了我的账，必须被看见。纯线上此前根本没有这个出口。 -->
          <ReceiptStack />
          <!-- 演出没播完就先按住：棋子还在走的时候写「你停在机会格」，
               和牌没翻过来卡片就躺在抽屉里，是同一个毛病 -->
          <OnlineLandingPanel v-if="game.isMyTurn && !held" />
          <!-- 进场当回合（老鼠赛跑里已走过一格）：本回合到此为止，不再糊出上一张已结算的旧卡 -->
          <div v-if="justLanded && !held" class="card focus ft-landed">
            <div class="todo-label gold">🏁 你已进入快车道</div>
            <p class="landed-lead">
              <b>本回合到此为止</b> —— 点下方「结束回合」。下一回合起，每次掷 <b>2 粒骰子</b>在外环移动{{
                me?.fasttrack.charity_forever ? '（你已行善，可选 1–3 粒）' : '' }}。
            </p>
            <div class="landed-nums">
              <StatRow label="启动资金已到账" :value="me?.cash ?? 0" />
              <StatRow label="现金流量日收入" :value="me?.fasttrack.current_income ?? 0" />
            </div>
          </div>
          <OnlineCardPanel v-else-if="activeCardInfo && !held" :card="activeCardInfo" />

          <!-- 别人的回合、且此刻没有别的东西可显示：牌桌自动兜底。
               这条兜底是对的，只是不够——抽了卡就轮不到它了，所以另有上面那个显式态。
               演出期间照旧显示（这时卡面还没落进抽屉，正文不该是空的） -->
          <template v-if="!game.isMyTurn && (held || !activeCardInfo) && game.connected">
            <div class="section-title">牌桌</div>
            <PlayerTableRow v-for="r in tableRows" :key="r.id" inner
                            :player="r.p" :step="r.step" :now="r.now" :self="r.id === me.id" />
          </template>
        </template>
      </div>

      <!-- 决策按钮钉底：一张牌堆卡加上前后对比就超过 half 档的高度，
           内容必须能滚，但「买入 / 放弃」不能跟着滚走。
           **最后一行永远留给「结束回合」**：卡片决策排它上面一行，不取代它——
           试玩里「买不起的 CD + 只有『我不买』」就是这样把出口关掉的。 -->
      <div v-if="!ledger" class="drawer-cta">
        <template v-if="me.inBankruptcy">
          <div class="cta-row">
            <button class="btn grow warn" @click="game.act('BANKRUPTCY_RESOLVE')">完成清算</button>
          </div>
        </template>
        <template v-else>
          <!-- 上行：这一格/这张卡此刻的决策（可有可无） -->
          <div v-if="cardCta" class="cta-row">
            <template v-if="['REALESTATE', 'BUSINESS', 'COLLECTIBLE', 'DICE_GAMBLE'].includes(cardCta.subtype)">
              <button class="btn grow" @click="decide('buy')">
                {{ cardCta.subtype === 'DICE_GAMBLE' ? '接受' : '买入' }}
                {{ fmt(activeCardInfo?.data.downPayment) }}
              </button>
              <button class="btn ghost grow" @click="decide('pass')">放弃</button>
            </template>
            <button v-else-if="cardCta.subtype === 'STOCK_OFFER'" class="btn ghost grow"
                    @click="decide('pass')">我不买</button>
            <button v-else-if="cardCta.subtype === 'STOCK_EVENT'" class="btn grow"
                    @click="decide('apply')">执行拆股 / 并股</button>
            <template v-else-if="cardCta.subtype === 'CREDIT_OPTION'">
              <button class="btn grow" @click="decide('pay')">现金支付</button>
              <button class="btn ghost grow" @click="decide('credit')">信用卡支付</button>
            </template>
            <button v-else-if="['EXPENSE_EVENT', 'CASH', 'INSTALLMENT'].includes(cardCta.subtype)"
                    class="btn grow warn" @click="decide('pay')">
              {{ cardCta.settlePreview?.waived ? '确认（无需支付）'
                 : `支付 ${fmt(cardCta.settlePreview?.due ?? 0)}` }}
            </button>
          </div>
          <div v-else-if="game.isMyTurn && step === 1 && canRoll" class="cta-row">
            <button class="btn grow" @click="roll">🎲 掷 {{ diceCount }} 粒骰</button>
          </div>

          <!-- 下行：结束回合。判据与服务端 `_d_end_turn` 逐项对齐——
               UI 的闸门不许比服务端严，服务端准结束的情形界面就必须准。
               停赛（skip_turns>0）不再另开分支：这个状态与 `isMyTurn` 同时成立时只可能是
               停赛刚生效的这一回合（见上方注释），按普通回合结束即可，不必绕开确认弹窗。 -->
          <div v-if="game.isMyTurn" class="cta-row">
            <button class="btn grow" :class="{ ghost: !!cardCta || (step === 1 && canRoll) }"
                    :disabled="!!blockedBy" @click="endTurn">
              {{ blockedBy || '✅ 结束回合' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 全屏发薪：只给当事人，自动消散（design/09 §5.5） -->
    <PaydayCurtain v-if="paydayStep" :step="paydayStep" @skip="game.skipStage()" />

    <!-- 全屏发牌翻牌：全员同步播放 -->
    <DealCurtain v-if="dealStep" :deck="dealStep.deck" :title="dealStep.title"
                 :card="activeCardInfo" :from="dealFrom" @skip="game.skipStage()" />

    <!-- 快车道格子详情：格面不写字的补偿 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="sheet-grab"></div>
        <div class="sheet-body">
          <FtSquareCard v-if="detailBiz" kind="biz"
                        :kind-label="detailBiz.dice_rule ? '企业投资 · 需掷骰' : '企业投资'"
                        :name="detailBiz.name"
                        :taken="(game.state.ftSoldSquares ?? []).includes(detailBiz.id)"
                        :nums="[{ label: '首付', value: fmt(detailBiz.down_payment) },
                                { label: '月现金流', value: '+' + fmt(detailBiz.cashflow) }]" />
          <FtSquareCard v-else-if="detailDream" kind="dream" kind-label="梦想"
                        :name="detailDream.name"
                        :mine="me.dreamId === detailDream.id"
                        :nums="[{ label: '价格', value: fmt(detailDream.price) }]" />
          <p v-else class="muted">{{ detail.ref }}</p>
          <button class="btn block ghost" @click="detail = null">知道了</button>
        </div>
      </div>
    </div>

    <!-- 资金：我主动翻开的常驻工具，随时可推开。要我答复的弹层一到就自动让位（见 watch） -->
    <FundsSheet v-if="funds" ref="fundsSheet" @close="funds = false" />

    <!-- 弹层同样等演出播完：别人抽的市场卡要我答复，也得先让我看见那张牌翻过来 -->
    <PromptModal v-if="!held" />
    <FasttrackCheer v-if="game.cheer" :cheer="game.cheer" @close="game.cheer = null" />
    <FasttrackIntro v-if="showIntro" @close="dismissIntro" @confirm="confirmEnterFasttrack" />
  </div>

  <ConnectingFallback v-else />
</template>
