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
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import type { CardDto, Player } from '../types'
import BoardView from '../components/board/BoardView.vue'
import Die3d from '../components/board/Die3d.vue'
import type { BoardSquare } from '../components/board/geom'
import FtSquareCard from '../components/cards/FtSquareCard.vue'
import DealCurtain from '../components/board/DealCurtain.vue'
import OnlineCardPanel from '../components/board/OnlineCardPanel.vue'
import OnlineLandingPanel from '../components/board/OnlineLandingPanel.vue'
import PromptModal from '../components/PromptModal.vue'
import ReceiptStack from '../components/ReceiptStack.vue'
import ResultView from '../components/ResultView.vue'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import FasttrackIntro from '../components/FasttrackIntro.vue'
import FasttrackCheer from '../components/FasttrackCheer.vue'
import StatementTab from '../components/StatementTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import BankPanel from '../components/tools/BankPanel.vue'
import BankruptcyPanel from '../components/tools/BankruptcyPanel.vue'
import TransferPanel from '../components/tools/TransferPanel.vue'

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

/** 本轮的行动顺序座次条：一眼读出现在第几轮、轮到谁、这一轮还剩几个人到我 */
const seats = computed(() => {
  const s = game.state
  if (!s) return []
  return s.turnOrder.map((pid, i) => {
    const p = s.players.find(x => x.id === pid)
    return {
      id: pid, initial: p?.nickname.slice(0, 1) ?? '?',
      now: i === s.turnIndex, done: i < s.turnIndex, out: p?.phase === 'OUT',
    }
  })
})

/** 观战牌桌（design/09 §6）：每位玩家走到回合的哪一步、账面什么样。
 *  全从已下发的字段派生，不加一次请求；口径与线下 `ActionTab.tableStepText` 同一套。 */
function stepTextOf(p: Player): string {
  const s = game.state!
  if (p.phase === 'OUT') return '已出局'
  if (p.inBankruptcy) return '正在破产清算'
  if (p.id !== s.currentPlayerId)
    return p.skipTurns ? `停赛中 · 还需跳过 ${p.skipTurns} 轮` : '等待中'
  if (!s.turnDiceUsed) return '正在掷骰'
  if (s.landing && !s.landing.resolved) return '正在处理落点'
  if (s.activeCard && !s.activeCard.resolved) return '正在决定这张卡'
  return '准备结束回合'
}

const tableRows = computed(() => (game.state?.players ?? []).map(p => ({
  id: p.id, nickname: p.nickname,
  now: p.id === game.state!.currentPlayerId,
  ft: p.phase === 'FAST_TRACK',
  cash: p.cash, flow: p.derived.monthlyCashflow, ftIncome: p.fasttrack.current_income,
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
const diceDefault = computed(() => (ft.value ? 2 : 1))
const diceCount = ref(1)
watch(diceDefault, v => { diceCount.value = v }, { immediate: true })
watch(diceMax, v => { if (diceCount.value > v) diceCount.value = diceDefault.value })

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

const hubTip = computed(() => {
  if (!game.connected) return '重新连上之前，不能掷骰'
  if (held.value) return heldTip.value
  if (!game.isMyTurn) return `${game.currentPlayer?.nickname ?? '对手'} 正在行动`
  if (me.value?.skipTurns) return `停赛中 · 还需跳过 ${me.value.skipTurns} 轮`
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
type LedgerPage = 'statement' | 'overview' | 'log' | 'more'
const DETENT_H: Record<Detent, string> = { peek: '128px', half: '46dvh', full: '88dvh' }
const RANK: Record<Detent, number> = { peek: 0, half: 1, full: 2 }
const detent = ref<Detent>('peek')
const ledger = ref<null | LedgerPage>(null)

/** 档位由内容决定，不由用户记忆决定 */
const wantDetent = computed<Detent>(() => {
  if (ledger.value) return 'full'
  if (me.value?.inBankruptcy) return 'full'
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

const drawerH = computed(() => DETENT_H[detent.value])
/** 档位切换缩的是棋盘**自身的宽度变量**（stage 有 overflow:hidden，缩 stage 等于白缩） */
const boardWidth = computed(() =>
  detent.value === 'full' ? '150px' : detent.value === 'half' ? '230px' : '332px')

let grabStart = 0
function onGrab(e: PointerEvent) {
  grabStart = e.clientY
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}
function onGrabUp(e: PointerEvent) {
  const dy = e.clientY - grabStart
  if (Math.abs(dy) < 24) return
  const order: Detent[] = ['peek', 'half', 'full']
  const i = order.indexOf(detent.value)
  detent.value = order[Math.min(order.length - 1, Math.max(0, i + (dy < 0 ? 1 : -1)))]
}

function openLedger(page: LedgerPage = 'statement') {
  ledger.value = page
  detent.value = 'full'
}
function closeLedger() {
  ledger.value = null
  detent.value = wantDetent.value
}

// 进入破产清算时把账本收掉：清算期间抽屉里只该有清算面板，分段控件让位
watch(() => me.value?.inBankruptcy, (v) => { if (v) ledger.value = null })

/** 破产入口的判据与线下同一条（月现金流为负且现金加它小于零） */
const bankruptable = computed(() =>
  !!me.value && !me.value.inBankruptcy && me.value.derived.monthlyCashflow < 0
  && me.value.cash + me.value.derived.monthlyCashflow < 0)

async function startBankruptcy() {
  const ok = await confirmAction({
    title: '进入破产流程？',
    lines: ['将按首期付款 50% 向银行变卖资产，直至月现金流转正'],
    danger: true,
  })
  if (ok) await game.act('BANKRUPTCY_START')
}

// 现金不足的三处提示点「去贷款」→ 打开 账本 → 更多 → 银行，并把缺口预填进去
const bankPanel = ref<InstanceType<typeof BankPanel> | null>(null)
watch(bankRequest, async (req) => {
  if (!req) return
  openLedger('more')
  await nextTick()
  bankPanel.value?.prefill(req.need)
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
        <span class="seat-strip">
          <span v-for="s in seats" :key="s.id" class="seat-dot"
                :class="{ now: s.now, done: s.done, out: s.out }">{{ s.initial }}</span>
        </span>
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
    </div>

    <!-- ===== 棋盘 =====
         演出进行中点棋盘任意处即**终止**当前序列并刷到终态（不是加速）：
         玩到第 20 轮的人不该被自己看过 20 遍的动画拖住 -->
    <div class="board-stage" :class="{ 'card-open': !held && !!game.state.activeCard }"
         :style="{ '--bw': boardWidth }"
         @click="game.staging && game.skipStage()">
      <div class="board-tools">
        <button class="board-float" title="账本" @click="openLedger()">📋</button>
        <router-link to="/manual" class="board-float" title="说明书">📖</router-link>
      </div>

      <BoardView :track="ft ? 'FAST_TRACK' : 'RAT_RACE'" :squares="squares"
                 :players="game.state.players" :positions="positions"
                 :me-id="game.session?.playerId ?? ''"
                 :current-index="currentIndex" :trail="trail"
                 :settle-index="settleStep?.index" :settle-amount="settleStep?.amount"
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
    </div>

    <!-- ===== 底部三档抽屉 ===== -->
    <div class="board-drawer" :style="{ '--dh': drawerH }">
      <div class="sheet-grab grabbable" @pointerdown="onGrab" @pointerup="onGrabUp"></div>

      <div class="drawer-peek">
        <!-- 破产清算优先于一切：这时候抽屉里只有清算面板，分段控件让位 -->
        <template v-if="me.inBankruptcy">
          <b class="who">破产清算</b>
          <span class="muted">卖资产直到月现金流转正</span>
        </template>
        <!-- 账本打开时状态条上只有标题与出口：四页归四页，分段控件在内容区顶部。
             七个按钮挤一条的老排法在 375 屏宽下必然折成两行 -->
        <template v-else-if="ledger">
          <b class="who">账本</b>
          <span class="grow"></span>
          <button class="btn ghost small" @click="closeLedger">收起 ✕</button>
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
          <!-- 头像列就是展开牌桌的入口：围观也是玩，别人的账面不该只能靠猜 -->
          <button class="seat-strip" title="看牌桌"
                  @click="detent = detent === 'peek' ? 'half' : 'peek'">
            <span v-for="s in seats" :key="s.id" class="seat-dot"
                  :class="{ now: s.now, done: s.done, out: s.out }">{{ s.initial }}</span>
          </button>
          <button v-if="me.isHost" class="btn ghost small"
                  @click="game.act('HOST_END_TURN')">⋯ 代结束</button>
        </template>
        <template v-else-if="held">
          <span class="who">{{ heldTip }}</span>
        </template>
        <template v-else>
          <span class="who">第 {{ step }} 步 / 3</span>
          <span class="muted">
            <template v-if="me.charityTurns">慈善生效中 · 还剩 {{ me.charityTurns }} 轮</template>
            <template v-else-if="step === 1">掷骰</template>
            <template v-else-if="step === 2">处理落点</template>
            <template v-else>可以结束回合</template>
          </span>
        </template>
      </div>

      <div class="drawer-body">
        <!-- 破产清算：抽屉自动升到 full 档，里面只有这块面板——
             卖资产、还贷、完成清算，每一步都得走得完，否则一破产就锁死 -->
        <template v-if="me.inBankruptcy">
          <BankruptcyPanel :show-resolve="false" />
        </template>
        <!-- 分段控件钉在内容区顶部：四段等宽、任何屏宽都排得下一行 -->
        <template v-else-if="ledger">
          <div class="ledger-seg">
            <button :class="{ on: ledger === 'statement' }" @click="ledger = 'statement'">报表</button>
            <button :class="{ on: ledger === 'overview' }" @click="ledger = 'overview'">总览</button>
            <button :class="{ on: ledger === 'log' }" @click="ledger = 'log'">日志</button>
            <button :class="{ on: ledger === 'more' }" @click="ledger = 'more'">更多</button>
          </div>
          <StatementTab v-if="ledger === 'statement'" />
          <OverviewTab v-else-if="ledger === 'overview'" />
          <LogTab v-else-if="ledger === 'log'" />
          <!-- 「更多」：随时可用但不是待办的三块（design/09 §2.4）。
               它们与报表/总览/日志同属「随时可查、随时可用」，本就该在同一层。 -->
          <template v-else-if="ledger === 'more'">
            <BankPanel v-if="me.phase === 'RAT_RACE'" ref="bankPanel" />
            <p v-else class="muted">快车道没有银行贷款（说明书第 6 页），记录卡已翻面。</p>
            <TransferPanel />
            <button v-if="bankruptable" class="btn block warn" @click="startBankruptcy">
              🆘 进入破产流程
            </button>
            <!-- 本机的显示偏好：它是这台设备的事，不是账本的一页，所以收在这儿而不是占一格分段 -->
            <div class="card">
              <h3>🎬 显示设置</h3>
              <label class="row between" style="cursor:pointer">
                <span>跳过动画</span>
                <input type="checkbox" :checked="game.skipAnim"
                       @change="game.setSkipAnim(!game.skipAnim)" />
              </label>
              <p class="muted" style="margin:6px 0 0">
                只影响这台设备：掷骰、走格、发牌不再播放过场，点数与卡面直接给出结果。
              </p>
            </div>
          </template>
        </template>
        <template v-else>
          <div v-if="!game.connected" class="card quiet" style="padding:14px;text-align:center">
            <span class="muted">重新连上之前，操作暂不可用</span>
          </div>
          <div v-else-if="me.skipTurns && game.isMyTurn" class="card inner">
            停赛中 · 还需跳过 {{ me.skipTurns }} 轮，这一回合只能跳过
          </div>
          <div v-else-if="me.phase === 'OUT'" class="card inner muted">
            你已出局 · 可以继续观战
          </div>
          <!-- 「刚刚发生在你身上」：银行结算日、别人的市场卡波及到我……
               这些事没经我的手就改了我的账，必须被看见。纯线上此前根本没有这个出口。 -->
          <ReceiptStack />
          <!-- 演出没播完就先按住：棋子还在走的时候写「你停在机会格」，
               和牌没翻过来卡片就躺在抽屉里，是同一个毛病 -->
          <OnlineLandingPanel v-if="game.isMyTurn && !held" />
          <OnlineCardPanel v-if="activeCardInfo && !held" :card="activeCardInfo" />

          <!-- 别人的回合：牌桌。他是谁、走到回合哪一步、账面什么样，一屏看得见。
               演出期间照旧显示（这时卡面还没落进抽屉，正文不该是空的） -->
          <template v-if="!game.isMyTurn && (held || !activeCardInfo) && game.connected">
            <div class="section-title">牌桌</div>
            <div v-for="r in tableRows" :key="r.id" class="card inner">
              <div class="row between">
                <div class="row" style="gap:8px">
                  <span class="avatar-lg">{{ r.nickname.slice(0, 1) }}</span>
                  <div>
                    <b style="font-size:13px">{{ r.nickname
                      }}<span v-if="r.id === me.id">（你）</span></b>
                    <div class="muted" style="font-size:11px">{{ r.step }}</div>
                  </div>
                </div>
                <span v-if="r.now" class="badge turn">行动中</span>
              </div>
              <div class="row between muted" style="margin-top:8px">
                <span>现金 <b class="money">{{ fmt(r.cash) }}</b></span>
                <span v-if="r.ft">现金流量日收入 <b class="money">{{ fmt(r.ftIncome) }}</b></span>
                <span v-else>月现金流
                  <b class="money" :class="r.flow >= 0 ? 'pos' : 'neg'">
                    {{ r.flow >= 0 ? '+' : '' }}{{ fmt(r.flow) }}</b></span>
              </div>
            </div>
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
               UI 的闸门不许比服务端严，服务端准结束的情形界面就必须准。 -->
          <div v-if="game.isMyTurn" class="cta-row">
            <button v-if="me.skipTurns" class="btn ghost grow" @click="game.act('END_TURN')">
              跳过本回合
            </button>
            <button v-else class="btn grow" :class="{ ghost: !!cardCta || (step === 1 && canRoll) }"
                    :disabled="!!blockedBy" @click="endTurn">
              {{ blockedBy || '✅ 结束回合' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 全屏发牌翻牌：全员同步播放 -->
    <DealCurtain v-if="dealStep" :deck="dealStep.deck" :title="dealStep.title"
                 :card="activeCardInfo" @skip="game.skipStage()" />

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

    <!-- 弹层同样等演出播完：别人抽的市场卡要我答复，也得先让我看见那张牌翻过来 -->
    <PromptModal v-if="!held" />
    <FasttrackCheer v-if="game.cheer" :cheer="game.cheer" @close="game.cheer = null" />
    <FasttrackIntro v-if="showIntro" @close="dismissIntro" @confirm="confirmEnterFasttrack" />
  </div>

  <ConnectingFallback v-else />
</template>
