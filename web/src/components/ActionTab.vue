<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { confirmAction } from '../confirm'
import { COLOR_PAYDAY, DECK_COLOR, DECK_LABEL, DECK_SHORT } from '../decks'
import { fmt, useGame } from '../store'
import type { CardDto } from '../types'
import CardPicker from './CardPicker.vue'
import FasttrackPanel from './FasttrackPanel.vue'
import ReceiptStack from './ReceiptStack.vue'
import StockTradeBox from './StockTradeBox.vue'
import BaseModal from './base/BaseModal.vue'
import GameCard from './cards/GameCard.vue'

const game = useGame()
const me = computed(() => game.me)
const st = computed(() => game.state!)
const myTurn = computed(() => game.isMyTurn)

const DECKS = DECK_LABEL
const PICKABLE_DECKS = ['SMALL_DEAL', 'BIG_DEAL', 'MARKET', 'DOODAD'] as const
const pickerDeck = ref<string | null>(null)
const activeCardInfo = ref<CardDto | null>(null)

/** 落定：CardPicker 已经把卡面摆出来核对过一次，这里不再叠一层文字确认 */
async function onPicked(card: CardDto) {
  pickerDeck.value = null
  if (await game.act('DRAW_CARD', { cardId: card.id })) activeCardInfo.value = card
}

const ac = computed(() => st.value.activeCard)
const iAmDrawer = computed(() => ac.value?.drawer_id === me.value?.id)
const drawerName = computed(() =>
  st.value.players.find(p => p.id === ac.value?.drawer_id)?.nickname ?? '玩家')

// 卡片数据对全员同步：说明书要求把卡「大声读出来」，线上就该人人看得见同一张牌。
// 这个 watchEffect 本来就跑在每个人的手机上，只是从前只有抽卡人会渲染。
watchEffect(async () => {
  const cur = ac.value
  if (!cur) { activeCardInfo.value = null; return }
  if (activeCardInfo.value?.id === cur.card_id) return
  const cards = await game.fetchCards(cur.deck)
  activeCardInfo.value = cards.find(c => c.id === cur.card_id) ?? null
})

// ---- 市场风云：抽卡人可能什么也得不到，真正被影响的是持有对应资产的人 ----
// 市场卡在抽卡那一刻就 resolved（engine `_a_card_drawn`：效果在伴随事件里完成），
// 所以这一段不看 resolved，只看牌堆；抽卡人要做的是「宣读 + 等各家答复」。
const isMarket = computed(() => ac.value?.deck === 'MARKET')
/** 求购类（会向持有人推要约的那几种）；现金流调整/强制没收不推要约，效果当场落地 */
const SELL_OFFERS = ['BUYER_OFFER', 'MULTIPLE_OFFER', 'PREMIUM_OFFER', 'INSTALLMENT_SALE']
const isSellOffer = computed(() => !!ac.value && SELL_OFFERS.includes(ac.value.subtype))

/** 还没答复的人（一人多套资产会有多条 prompt，按玩家归并）。
 *  serialize() 下发的是全量 prompts，不是只给本人的，所以抽卡人这边零协议改动就拿得到。 */
const marketPending = computed(() => {
  const cur = ac.value
  if (!cur || cur.deck !== 'MARKET') return []
  const byPlayer = new Map<string, number>()
  for (const p of st.value.prompts) {
    if (p.kind !== 'MARKET_SELL' || p.payload?.card_id !== cur.card_id) continue
    byPlayer.set(p.target_player_id, (byPlayer.get(p.target_player_id) ?? 0) + 1)
  }
  return [...byPlayer].map(([id, n]) => ({
    nickname: st.value.players.find(pl => pl.id === id)?.nickname ?? '玩家', assets: n }))
})

/** 卡面上方那行状态：市场卡「已结算」说不通——效果早就落地了，大家在等的是各家答复 */
const cardStatusText = computed(() => {
  const cur = ac.value
  if (!cur) return ''
  if (isMarket.value)
    return marketPending.value.length
      ? `抽到市场风云卡，正在等 ${marketPending.value.length} 位玩家答复`
      : '已宣读这张卡'
  return cur.resolved ? '已处理完这张卡' : `停在${DECK_SHORT[cur.deck] ?? cur.deck}，正在决定`
})
const cardStatusBadge = computed(() =>
  isMarket.value && marketPending.value.length ? '等待答复'
    : (ac.value?.resolved ? '已结算' : '行动中'))

/** 这张卡影响了谁（服务端事件派生，见 receipts.buildCardImpact） */
const impact = computed(() => game.cardImpact)
/** 一共通知了几位（含已答复的）；断线重连丢了事件就退回当前待决定人数 */
const notifiedCount = computed(() => impact.value?.notified.length || marketPending.value.length)

// 银行操作
const loanAmount = ref(1000)
const repayAmount = ref(1000)
const resellTo = ref('')
const resellPrice = ref(0)
const showResell = ref(false)
const transferTo = ref('')
const transferAmount = ref(0)
const transferReason = ref('')
// 常驻工具默认折叠：它们随时可用，但不是待办，不该和「你现在该做什么」抢注意力
const toolsOpen = ref(false)

const others = computed(() => st.value.players.filter(p => p.id !== me.value?.id && p.phase !== 'OUT'))

// 股票窗口（谁能买、我有多少）统一由 store 判定，买卖操作区见 StockTradeBox.vue
const stockWin = computed(() => game.myStockWindow)
// 抽卡人在页内卡里操作；其他人被「别人的动作」波及，走统一的底部弹层
const stockSheet = computed(() =>
  game.stockWindowOpen && !(iAmDrawer.value && ac.value && !ac.value.resolved))
const stockCollapsed = computed(() =>
  !!game.myStockWindow && !game.stockWindowOpen && !(iAmDrawer.value && ac.value && !ac.value.resolved))

// bd-031 比萨饼特许专卖店是全库唯一无市场买家的资产：标注出来，免得被当成 bug
const NO_MARKET_BUYER_TYPES = ['特许专卖店']
const noMarketBuyer = computed(() =>
  !!activeCardInfo.value && NO_MARKET_BUYER_TYPES.includes(activeCardInfo.value.data.assetType))

const bankruptable = computed(() =>
  me.value && me.value.derived.monthlyCashflow < 0 &&
  me.value.cash + me.value.derived.monthlyCashflow < 0)

// 强制卡现金不足时，「去银行贷款」滚到银行卡片
const bankCard = ref<HTMLElement | null>(null)

// 聚焦决策卡：买入后的现金 / 月现金流预览（纯前端派生提示，服务端仍是权威结算）
const buyPreview = computed(() => {
  const c = activeCardInfo.value, m = me.value
  if (!c || !m) return null
  const dp = c.data.downPayment ?? 0
  const hasFlow = typeof c.data.cashflow === 'number'
  return {
    cashAfter: m.cash - dp,
    flowAfter: m.derived.monthlyCashflow + (c.data.cashflow ?? 0),
    hasFlow,
  }
})

// 三步进度：银行结算日 → 停留格 → 结束
const stepPayday = computed(() => st.value.turnPaydayUsed)
const stepSquare = computed(() => st.value.turnSquareUsed)

// ---- 卡内资金决策：确认弹窗 + 成功提示 ----

async function decideBuy() {
  const c = activeCardInfo.value!
  const ok = await confirmAction({
    title: `买入「${c.title}」？`,
    lines: [`首付 ${fmt(c.data.downPayment)}`, `月现金流 +${fmt(c.data.cashflow)}`],
  })
  if (ok && await game.act('CARD_DECISION', { decision: 'buy' })) {
    game.flash(`已买入，支付首付 ${fmt(c.data.downPayment)}`)
    activeCardInfo.value = null
  }
}

async function decidePass(stockWindow = false) {
  const ok = await confirmAction({
    title: stockWindow ? '这张股票我不买？' : '放弃这次机会？',
    // 放弃购买不关闭交易窗口：全员（含自己）本回合仍可按今日价卖出持仓
    lines: stockWindow
      ? ['只表示你不按今日价买入', '全员的卖出窗口开到本回合结束']
      : ['机会卡将作废（本回合不能再抽卡）'],
  })
  if (ok && await game.act('CARD_DECISION', { decision: 'pass' })) activeCardInfo.value = null
}

// 选错卡反悔：撤销这次抽卡（FR-29 本人更正），随后重新打开同牌堆选卡列表
async function undoDraw() {
  const cur = ac.value!
  const title = activeCardInfo.value?.title ?? cur.card_id
  const ok = await confirmAction({
    title: `撤销抽卡「${title}」？`,
    lines: ['将撤销这次抽卡，可重新选卡', '全员账目立即重算，日志保留划线痕迹'],
    danger: true,
  })
  if (!ok) return
  const log = await game.fetchLog()
  const drawn = [...log].reverse().find(e =>
    e.type === 'CARD_DRAWN' && !e.revoked
    && e.actorId === game.session?.playerId && e.payload.card_id === cur.card_id)
  if (!drawn) { game.flash('未找到抽卡记录，请在「日志」中处理', 'info'); return }
  const deck = cur.deck
  if (await game.act('PLAYER_CORRECT', { eventSeq: drawn.seq, reason: '选错卡重选' })) {
    activeCardInfo.value = null
    pickerDeck.value = deck
    game.flash('已撤销，请重新选卡')
  }
}

// 强制卡（额外支出/损失/维修等）：金额与豁免说明由服务端 settlePreview 下发，前端不做规则判断
const settlePreview = computed(() => ac.value?.settlePreview ?? null)

async function forcedSettle() {
  const c = activeCardInfo.value!
  const pv = settlePreview.value
  const shortfall = pv && !pv.waived ? pv.due - (me.value?.cash ?? 0) : 0
  const ok = await confirmAction({
    title: pv
      ? (pv.waived ? `结算「${c.title}」（无需支付）？` : `支付 ${fmt(pv.due)} 结算「${c.title}」？`)
      : `结算「${c.title}」？`,
    lines: pv?.note ? [pv.note] : [],
    warning: shortfall > 0 ? `现金不足，还差 ${fmt(shortfall)}，请先在「银行」贷款` : undefined,
  })
  if (ok && await game.act('CARD_DECISION', { decision: 'pay' })) {
    game.flash(pv ? (pv.waived ? `「${c.title}」已结算，无需支付` : `已支付 ${fmt(pv.due)}`) : '已结算')
    activeCardInfo.value = null
  }
}

async function doodadPay(method: 'pay' | 'credit') {
  const d = activeCardInfo.value!.data
  const ok = await confirmAction(method === 'credit'
    ? { title: '信用卡支付？', lines: [`信用卡负债 +${fmt(d.amount)}`, `每月还款 +${fmt(d.creditMonthly)}`] }
    : { title: `现金支付 ${fmt(d.amount)}？` })
  if (ok && await game.act('CARD_DECISION', { decision: method })) {
    game.flash(method === 'credit' ? '已记入信用卡' : `已支付 ${fmt(d.amount)}`)
    activeCardInfo.value = null
  }
}

// ---- 资金/不可逆操作：确认弹窗 + 成功提示 ----

const paydayTimes = ref(1)

// 说明书 P.5：结算日现金不足以支付到期款项即破产，服务端会直接进入清算，贷款不是这一刻的出口
const paydayBankrupts = computed(() =>
  !!me.value && me.value.cash + me.value.derived.monthlyCashflow * paydayTimes.value < 0)

async function payday() {
  const cf = me.value!.derived.monthlyCashflow
  const t = paydayTimes.value
  const ok = await confirmAction({
    title: `结算银行结算日 ×${t}？`,
    lines: [`月现金流 ${fmt(cf)} × ${t} = ${fmt(cf * t)}`, '经过多次请先在右侧选择次数一并结算'],
    warning: paydayBankrupts.value
      ? '现金不足以支付到期款项，本次结算将直接进入破产清算（说明书 P.5），不能改为贷款'
      : cf < 0 ? '月现金流为负，将从现金中扣除' : undefined,
    danger: paydayBankrupts.value,
  })
  if (!ok || !await game.act('PAYDAY', { times: t })) return
  if (me.value?.inBankruptcy) game.flash('结算日无力支付，已进入破产清算', 'err')
  else game.flash(`已结算银行结算日 ×${t}，现金${cf >= 0 ? ' +' : ' '}${fmt(cf * t)}`)
}

async function takeLoan() {
  const amt = loanAmount.value
  const interest = Math.floor(amt / 10)
  const cfAfter = me.value!.derived.monthlyCashflow - interest
  const ok = await confirmAction({
    title: `向银行贷款 ${fmt(amt)}？`,
    lines: [`每月利息 +${fmt(interest)}（月息 10%）`, `贷后月现金流 ${fmt(cfAfter)}`],
    warning: cfAfter < 0
      ? '贷后月现金流为负：下个银行结算日现金不足以支付即破产，届时不能再贷款'
      : undefined,
  })
  if (ok && await game.act('TAKE_LOAN', { amount: amt })) game.flash(`已贷款 ${fmt(amt)}`)
}

async function repayLoan() {
  const amt = Math.min(loanAmount.value, me.value!.liabilities.bank_loan)
  const ok = await confirmAction({
    title: `偿还银行贷款 ${fmt(amt)}？`,
    lines: [`每月利息 −${fmt(Math.floor(amt / 10))}`],
  })
  if (ok && await game.act('REPAY_LOAN', { amount: amt })) game.flash(`已还款 ${fmt(amt)}`)
}

// 一次性还清银行贷款：贷款额恒为千元倍数，floor 只是兜底
async function repayAllLoan() {
  loanAmount.value = Math.floor(me.value!.liabilities.bank_loan / 1000) * 1000
  await repayLoan()
}

// 强制卡「去银行贷款」：展开常驻工具、预填缺口金额并滚到银行卡片
function gotoBank(need: number) {
  loanAmount.value = Math.max(1000, Math.ceil(need / 1000) * 1000)
  toolsOpen.value = true
  requestAnimationFrame(() => bankCard.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}

async function charity() {
  const amount = Math.round(me.value!.derived.totalIncome / 10)
  const ok = await confirmAction({
    title: '慈善捐款？',
    lines: [`捐出总收入 10% = ${fmt(amount)}`, '此后 3 轮可选掷 1 或 2 粒骰子'],
  })
  if (ok && await game.act('CHARITY')) game.flash(`已捐款 ${fmt(amount)}`)
}

async function addChild() {
  const p = me.value!
  const ok = await confirmAction({
    title: '生孩子？',
    lines: p.childCount >= 3
      ? ['已有 3 个孩子，此格无效果（仍计为本回合停留格）']
      : [`每月孩子支出 +${fmt(p.perChildExpense)}（不可逆）`],
  })
  if (ok && await game.act('ADD_CHILD')) game.flash('已记录孩子事件')
}

async function unemployment() {
  const amount = me.value!.derived.totalExpenses
  const ok = await confirmAction({
    title: '失业？',
    lines: [`支付一次总支出 ${fmt(amount)}`, '并停赛 2 轮，慈善状态清零'],
    danger: true,
  })
  if (ok && await game.act('UNEMPLOYMENT')) game.flash(`已支付 ${fmt(amount)}，停赛 2 轮`)
}

async function bankruptcySell(name: string, assetId: string, proceeds?: number) {
  const ok = await confirmAction({
    title: `把「${name}」卖给银行？`,
    lines: [proceeds !== undefined ? `按规则可得 ${fmt(proceeds)}（首期付款 50%）` : '股票按买入成本 50% 回收'],
    danger: true,
  })
  if (ok && await game.act('BANKRUPTCY_SELL_ASSET', { assetId })) game.flash(`已变卖 ${name}`)
}

async function bankruptcyRepay() {
  const amt = Math.min(repayAmount.value, me.value!.liabilities.bank_loan)
  const ok = await confirmAction({
    title: `偿还银行贷款 ${fmt(amt)}？`,
    lines: [`每月利息 −${fmt(Math.floor(amt / 10))}`],
  })
  if (ok && await game.act('REPAY_LOAN', { amount: amt })) game.flash(`已还款 ${fmt(amt)}`)
}

async function startBankruptcy() {
  const ok = await confirmAction({
    title: '进入破产流程？',
    lines: ['将按首期付款 50% 向银行变卖资产，直至月现金流转正'],
    danger: true,
  })
  if (ok) await game.act('BANKRUPTCY_START')
}

async function endTurn() {
  if (!st.value.turnSquareUsed && !st.value.turnPaydayUsed) {
    const ok = await confirmAction({
      title: '结束回合？',
      lines: ['本回合尚未记录任何棋盘事件',
              '若本轮经过/停在银行结算日，请先点「银行结算日」结算'],
    })
    if (!ok) return
  }
  activeCardInfo.value = null
  await game.act('END_TURN')
}

async function hostEndTurn() {
  const who = game.currentPlayer?.nickname ?? '当前玩家'
  const ok = await confirmAction({
    title: `代 ${who} 结束回合？`,
    lines: ['用于玩家临时离开时推进对局', '其未结算的卡牌将作废；误点可在「日志」中撤销'],
  })
  if (ok && await game.act('HOST_END_TURN')) game.flash(`已代 ${who} 结束回合`)
}

/** 破产清算：还差多少才能转正，是玩家真正要算的那个数 */
const bkGap = computed(() => Math.max(0, -(me.value?.derived.monthlyCashflow ?? 0)))
</script>

<template>
  <div v-if="me && st">
    <!-- 「刚刚发生在你身上」：没操作却改了我的账的事，停在最上直到本人确认 -->
    <ReceiptStack />

    <!-- 慈善/停赛状态 -->
    <div v-if="me.charityTurns > 0 || me.skipTurns > 0" class="row wrap" style="margin-bottom:8px">
      <span v-if="me.charityTurns > 0" class="badge ft">💝 慈善生效中 · 还剩 {{ me.charityTurns }} 轮 · 可掷 1 或 2 粒骰</span>
      <span v-if="me.skipTurns > 0" class="badge out">⏸️ 停赛中 · 还需跳过 {{ me.skipTurns }} 轮</span>
    </div>

    <!-- 破产清算（最高优先） -->
    <div v-if="me.inBankruptcy" class="card urgent">
      <div class="todo-label urgent">本回合待办 · 破产清算</div>
      <h2 style="margin:4px 0 5px">现金不够付这个月的账</h2>
      <p class="muted" style="margin:0 0 10px">
        按说明书：以首期付款的一半把资产卖给银行，直到月现金流转正。（说明书第 5 页）</p>
      <div class="preview">
        <div class="prow"><span>当前月现金流</span>
          <span class="money neg">{{ fmt(me.derived.monthlyCashflow) }}</span></div>
        <div class="prow"><span>转正还差</span><span class="money">+{{ fmt(bkGap) }}</span></div>
      </div>
      <div v-for="a in [...me.realEstates, ...me.businesses]" :key="a.id" class="card inner">
        <div class="row between">
          <div>
            <b style="font-size:13px">{{ a.name }}</b>
            <div class="muted">卖出得 {{ fmt(Math.floor(a.down_payment / 2)) }} · 月现金流 −{{ fmt(a.cashflow) }}</div>
          </div>
          <button class="btn small warn" @click="bankruptcySell(a.name, a.id, Math.floor(a.down_payment / 2))">卖给银行</button>
        </div>
      </div>
      <div v-for="sym in [...new Set(me.stocks.map(s => s.symbol))]" :key="sym" class="card inner">
        <div class="row between">
          <div><b style="font-size:13px">股票 {{ sym }}</b><div class="muted">按买入成本半价卖出</div></div>
          <button class="btn small warn" @click="bankruptcySell('股票 ' + sym, 'stock:' + sym)">卖出</button>
        </div>
      </div>
      <div class="row between" style="margin-top:10px">
        <span class="muted">当前银行贷款</span>
        <span class="money">{{ fmt(me.liabilities.bank_loan) }}</span>
      </div>
      <div class="row" style="margin-top:6px">
        <input type="number" v-model.number="repayAmount" step="1000" min="1000" />
        <button class="btn small" :disabled="!me.liabilities.bank_loan" @click="bankruptcyRepay">还银行贷款</button>
      </div>
      <p class="muted">清偿其他负债请到「报表」页的负债表操作</p>
      <button class="btn block warn" @click="game.act('BANKRUPTCY_RESOLVE')">完成清算</button>
      <p class="muted" style="margin:8px 0 0">
        清算后仍为负，购车贷款、信用卡与额外负债将注销一半；若还是负值就出局。
      </p>
    </div>

    <!-- 快车道面板 -->
    <FasttrackPanel v-else-if="me.phase === 'FAST_TRACK'" />

    <template v-else-if="me.phase === 'RAT_RACE'">
      <!-- 三步进度条：任何时刻只强调当前该做的那一步 -->
      <div v-if="myTurn" class="steps">
        <span class="s" :class="stepPayday ? 'ok' : 'now'"><span class="n">{{ stepPayday ? '✓' : '1' }}</span>结算日</span>
        <span class="ln"></span>
        <span class="s" :class="stepSquare ? 'ok' : (stepPayday ? 'now' : '')"><span class="n">{{ stepSquare ? '✓' : '2' }}</span>停留格</span>
        <span class="ln"></span>
        <span class="s"><span class="n">3</span>结束</span>
      </div>

      <!-- 当前这张牌：**人人看得见同一张**。抽卡人得到操作区，其他人看到等待态。
           说明书要求把卡「大声读出来」，线上就该照做。 -->
      <div v-if="ac && activeCardInfo"
           class="card" :class="iAmDrawer && !ac.resolved ? (settlePreview !== null ? 'urgent' : 'focus') : ''">
        <template v-if="iAmDrawer && !ac.resolved">
          <div class="todo-label" :class="{ urgent: settlePreview !== null }">
            {{ settlePreview !== null ? '本回合待办 · 先结算这张卡' : '本回合待办 · 处理抽到的卡' }}
          </div>
        </template>
        <template v-else-if="iAmDrawer && isMarket">
          <div class="todo-label">本回合待办 · 宣读这张卡</div>
        </template>
        <template v-else>
          <div class="row between" style="margin-bottom:9px">
            <div>
              <b style="font-size:13.5px">{{ drawerName }}{{ iAmDrawer ? '（你）' : '' }}</b>
              <div class="muted" style="font-size:11px">{{ cardStatusText }}</div>
            </div>
            <span class="badge turn">{{ cardStatusBadge }}</span>
          </div>
        </template>

        <GameCard :card="activeCardInfo" style="margin:8px 0 12px" />

        <!-- 波及范围：影响到不止一个人的卡，逐人列清各变多少。
             抽卡人要向同桌宣读的就是这些数，旁观者也该看得见自己那一行。 -->
        <div v-if="impact && impact.rows.length" class="card inner"
             :style="{ borderLeft: `3px solid ${DECK_COLOR[ac.deck] ?? 'var(--muted)'}` }">
          <div class="section-title">这张卡影响了 {{ impact.rows.length }} 人</div>
          <div v-for="(r, i) in impact.rows" :key="i" class="row between" style="margin-top:4px">
            <span style="font-size:12.5px">
              {{ r.nickname }}{{ r.playerId === me.id ? '（你）' : '' }} · {{ r.detail }}</span>
            <span class="money" :class="r.tone">{{ r.amount }}</span>
          </div>
        </div>

        <!-- 抽卡人侧：通知了谁、谁还没决定——他才知道自己在等什么、什么时候能结束回合 -->
        <div v-if="iAmDrawer && isSellOffer" class="card inner" style="margin-top:8px">
          <template v-if="marketPending.length">
            <div class="muted">已通知 {{ notifiedCount }} 位持有该资产的玩家</div>
            <div class="row wrap" style="margin-top:8px;gap:6px">
              <span v-for="p in marketPending" :key="p.nickname" class="badge">
                {{ p.nickname }} · 待决定<template v-if="p.assets > 1">（{{ p.assets }} 项）</template>
              </span>
            </div>
          </template>
          <div v-else class="muted">
            {{ notifiedCount ? '大家都已答复，可以结束回合' : '没有人持有相关资产，可以结束回合' }}
          </div>
        </div>
        <!-- 现金流调整/强制没收不推要约，效果在抽卡那一刻已经落地：没人被波及就直说 -->
        <div v-else-if="iAmDrawer && isMarket && !impact?.rows.length"
             class="card inner muted" style="margin-top:8px">
          没有人持有相关资产，可以结束回合
        </div>

        <!-- 只有抽卡人有操作区；其他人到此为止（要他响应的事走底部弹层） -->
        <template v-if="iAmDrawer && !ac.resolved">
          <template v-if="ac.subtype === 'REALESTATE' || ac.subtype === 'BUSINESS' || ac.subtype === 'COLLECTIBLE'">
            <p v-if="activeCardInfo.data.rooms" class="muted">{{ activeCardInfo.data.rooms }} 室公寓（求购卡可能按间计价）</p>
            <p v-if="activeCardInfo.data.units" class="muted">{{ activeCardInfo.data.units }} 套公寓楼（求购卡可能按套计价）</p>
            <p v-if="activeCardInfo.data.quantity" class="muted">共 {{ activeCardInfo.data.quantity }} 枚（求购卡按枚计价）</p>
            <p v-if="noMarketBuyer" class="muted">⚠️ 全套市场卡里没有求购此类资产的买家，只能持有或私下转让给其他玩家</p>
            <div class="preview" v-if="buyPreview">
              <div class="prow"><span>买入后 · 现金</span>
                <span class="money" :class="buyPreview.cashAfter < 0 ? 'neg' : ''">{{ fmt(buyPreview.cashAfter) }}</span></div>
              <div class="prow" v-if="buyPreview.hasFlow"><span>买入后 · 月现金流</span>
                <span class="money" :class="buyPreview.flowAfter >= 0 ? 'pos' : 'neg'">
                  {{ buyPreview.flowAfter >= 0 ? '+' : '' }}{{ fmt(buyPreview.flowAfter) }}</span></div>
            </div>
            <!-- 买不起：按钮置灰并写清差额，旁边直接给贷款入口 -->
            <div v-if="buyPreview && buyPreview.cashAfter < 0" class="card inner danger"
                 style="background:var(--red-soft)">
              <div class="row between">
                <span style="font-size:12.5px;font-weight:700;color:var(--red)">
                  现金还差 {{ fmt(-buyPreview.cashAfter) }}</span>
                <button class="btn small gold" @click="gotoBank(-buyPreview.cashAfter)">去贷款</button>
              </div>
            </div>
            <div class="btn-row wrap">
              <button class="btn grow" :disabled="!!buyPreview && buyPreview.cashAfter < 0" @click="decideBuy">
                买入 {{ fmt(activeCardInfo.data.downPayment) }}
              </button>
              <button class="btn ghost" @click="decidePass()">放弃</button>
              <button class="btn ghost" @click="showResell = !showResell">转卖</button>
            </div>
          </template>

          <template v-else-if="ac.subtype === 'STOCK_OFFER'">
            <p class="muted">区间 {{ fmt(activeCardInfo.data.priceRange?.[0]) }}–{{ fmt(activeCardInfo.data.priceRange?.[1]) }}</p>
            <StockTradeBox />
            <p class="muted">持有该股的玩家此刻也可按今日价卖出（他们的手机上会弹出交易窗口）</p>
            <button class="btn ghost block" @click="decidePass(true)">我不买</button>
          </template>

          <template v-else-if="ac.subtype === 'DICE_GAMBLE'">
            <p class="muted">骰子由服务端掷出并记入日志，结果不可重掷</p>
            <div class="preview" v-if="buyPreview">
              <div class="prow"><span>投入后 · 现金</span>
                <span class="money" :class="buyPreview.cashAfter < 0 ? 'neg' : ''">{{ fmt(buyPreview.cashAfter) }}</span></div>
            </div>
            <div class="btn-row wrap">
              <button class="btn grow" @click="decideBuy">接受这笔生意</button>
              <button class="btn ghost" @click="decidePass()">放弃</button>
              <button class="btn ghost" @click="showResell = !showResell">转卖</button>
            </div>
          </template>

          <template v-else-if="ac.subtype === 'STOCK_EVENT'">
            <p class="muted">按卡面对全员执行拆股/并股（总成本不变，此时不能交易）</p>
            <button class="btn block" @click="game.act('CARD_DECISION', { decision: 'apply' }).then(ok => ok && (activeCardInfo = null))">执行</button>
          </template>

          <template v-else-if="ac.subtype === 'CREDIT_OPTION'">
            <div class="preview">
              <div class="prow"><span>应付</span><span class="money neg">{{ fmt(activeCardInfo.data.amount) }}</span></div>
              <div class="prow"><span>改记信用卡 · 每月还款</span>
                <span class="money neg">+{{ fmt(activeCardInfo.data.creditMonthly) }}</span></div>
            </div>
            <div class="btn-row">
              <button class="btn grow" @click="doodadPay('pay')">现金支付</button>
              <button class="btn ghost grow" @click="doodadPay('credit')">信用卡支付</button>
            </div>
          </template>

          <!-- 强制卡：额外支出 / 现金损失 / 分期购买。**显式列出**，
               别再让以后新增的 subtype 静默落进这个模板、拿到一个按下必报错的按钮 -->
          <template v-else-if="['EXPENSE_EVENT', 'CASH', 'INSTALLMENT'].includes(ac.subtype)">
            <div class="preview" v-if="settlePreview">
              <div class="prow"><span>应付</span>
                <span class="money neg">{{ fmt(settlePreview.due) }}</span></div>
              <div class="prow"><span>支付后 · 现金</span>
                <span class="money" :class="me.cash - settlePreview.due < 0 ? 'neg' : ''">
                  {{ fmt(me.cash) }} <span class="arrow">→</span> {{ fmt(me.cash - settlePreview.due) }}</span></div>
            </div>
            <p v-if="settlePreview?.note" class="muted">{{ settlePreview.note }}</p>
            <div v-if="settlePreview && !settlePreview.waived && me.cash < settlePreview.due"
                 class="card inner danger" style="background:var(--red-soft)">
              <div class="row between">
                <span style="color:var(--red);font-weight:700;font-size:12.5px">
                  现金不足，还差 {{ fmt(settlePreview.due - me.cash) }}</span>
                <button class="btn small gold" @click="gotoBank(settlePreview.due - me.cash)">去贷款</button>
              </div>
            </div>
            <button class="btn block warn" @click="forcedSettle">
              {{ settlePreview ? (settlePreview.waived ? '确认（无需支付）' : `支付 ${fmt(settlePreview.due)}`) : '结算' }}
            </button>
            <p class="muted" style="margin:6px 0 0">强制卡：结算后才能结束回合。</p>
          </template>

          <template v-else>
            <p class="muted" style="margin:0">这张卡不需要在这里结算，直接结束回合即可。</p>
          </template>

          <!-- 转卖表单：机会卡（含赌局）都可让给其他玩家（说明书 p8） -->
          <div v-if="showResell" class="card inner">
            <div class="section-title">转卖给同桌</div>
            <label>转卖对象（价格线下议定）</label>
            <select v-model="resellTo">
              <option value="" disabled>选择玩家</option>
              <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
            </select>
            <label>转让费（对方还需按卡面首付买下这项资产）</label>
            <input type="number" v-model.number="resellPrice" min="0" />
            <button class="btn block" :disabled="!resellTo"
                    @click="game.act('CARD_DECISION', { decision: 'resell', toPlayerId: resellTo, price: resellPrice }).then(ok => ok && (showResell = false, activeCardInfo = null))">
              发起转卖（待对方确认）
            </button>
          </div>

          <button class="btn ghost small" style="margin-top:10px" @click="undoDraw">↩️ 选错卡？撤销重选</button>
        </template>

        <p v-else-if="!ac.resolved" class="muted" style="margin:0">
          等 {{ drawerName }} 决定。若这张卡和你有关（求购你的资产、股票开放交易、转卖给你），
          会弹出需要你答复的窗口。
        </p>
      </div>

      <!-- 不是我的回合、也没有活动卡：显示牌桌，围观也是玩 -->
      <div v-else-if="!myTurn" class="card quiet" style="padding:14px;text-align:center">
        <span class="muted">{{ game.currentPlayer?.nickname ?? '其他玩家' }} 正在行动</span>
      </div>

      <!-- 股票交易窗口收起后的重开入口 -->
      <button v-if="stockCollapsed" class="card quiet" style="width:100%;text-align:left"
              @click="game.reopenStockWindow()">
        <span class="muted">📈 {{ stockWin?.symbol }} 交易窗口已收起 · 点此重新打开（开到本回合结束）</span>
      </button>

      <!-- 本回合待办：停留格分诊（我的回合） -->
      <div v-if="myTurn" class="card focus">
        <div class="todo-label">本回合待办 · 你停在哪种格子？</div>

        <div class="section-title">银行结算日</div>
        <div class="row">
          <button class="pill grow" :class="{ done: st.turnPaydayUsed }" :disabled="st.turnPaydayUsed" @click="payday">
            <span class="dot" :style="{ background: COLOR_PAYDAY }"></span>
            {{ st.turnPaydayUsed ? '已结算' : '结算银行结算日' }}
          </button>
          <select v-model.number="paydayTimes" :disabled="st.turnPaydayUsed"
                  style="width:96px" title="本轮经过/停留次数">
            <option v-for="n in 3" :key="n" :value="n">×{{ n }} 次</option>
          </select>
        </div>
        <p v-if="paydayBankrupts && !st.turnPaydayUsed" class="muted" style="color:var(--red)">
          ⚠️ 现金不足以支付到期款项，本次结算将直接进入破产清算（说明书第5页），不能改为贷款
        </p>

        <div class="section-title">抽卡</div>
        <div class="pill-row">
          <button v-for="deck in PICKABLE_DECKS" :key="deck" class="pill"
                  :class="{ done: st.turnSquareUsed }"
                  :disabled="(!!ac && !ac.resolved) || st.turnSquareUsed"
                  @click="pickerDeck = deck">
            <span class="dot" :style="{ background: DECK_COLOR[deck] }"></span>{{ DECK_SHORT[deck] }}
          </button>
        </div>

        <div class="section-title">不抽卡的格子</div>
        <div class="pill-row">
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="addChild">👶 生孩子</button>
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="charity">💝 慈善（总收入10%）</button>
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="unemployment">📉 失业（付总支出停2轮）</button>
        </div>
        <p v-if="st.turnSquareUsed" class="muted" style="margin-top:8px">✅ 本回合已声明停留格事件（每回合只停一格；误录请房主在「日志」中撤销）</p>

        <button v-if="bankruptable" class="btn block warn" style="margin-top:12px" @click="startBankruptcy">🆘 进入破产流程</button>
      </div>
    </template>

    <!-- 常驻工具：随时可用，但不是待办，默认折叠 -->
    <div v-if="me.phase !== 'OUT' && !me.inBankruptcy" class="card quiet">
      <button class="row between" style="width:100%" @click="toolsOpen = !toolsOpen">
        <span class="muted">
          <template v-if="me.phase === 'RAT_RACE'">银行 · 贷款与还款　　转账给玩家</template>
          <template v-else>转账给玩家</template>
        </span>
        <span class="muted">{{ toolsOpen ? '收起 ⌃' : '展开 ⌄' }}</span>
      </button>
    </div>

    <template v-if="toolsOpen && !me.inBankruptcy">
      <!-- 银行：贷款 / 还款（随时可用，不限自己回合） -->
      <div v-if="me.phase === 'RAT_RACE'" ref="bankCard" class="card">
        <h3>🏦 银行</h3>
        <p v-if="me.liabilities.bank_loan" class="row between" style="margin:6px 0">
          <span class="muted">当前银行贷款</span>
          <span><b class="money">{{ fmt(me.liabilities.bank_loan) }}</b>
            <span class="muted"> · 月供 {{ fmt(me.derived.bankLoanExpense) }}</span></span>
        </p>
        <p v-else class="muted" style="margin:6px 0">当前无银行贷款</p>
        <div class="row wrap">
          <input type="number" v-model.number="loanAmount" step="1000" min="1000" />
          <button class="btn small" @click="takeLoan">贷款</button>
          <button class="btn small ghost" :disabled="!me.liabilities.bank_loan" @click="repayLoan">还款</button>
          <button v-if="me.liabilities.bank_loan" class="btn small ghost" @click="repayAllLoan">
            还清 {{ fmt(me.liabilities.bank_loan) }}
          </button>
        </div>
        <p class="muted">千元整数倍，月息 10%（每借 $1,000 月付 $100）</p>
        <p class="muted">清偿房贷/学贷/车贷等其他负债请到「报表」页的负债表</p>
      </div>

      <!-- 玩家间转账 -->
      <div v-if="me.phase !== 'OUT'" class="card">
        <h3>🤝 玩家间转账</h3>
        <label>转给</label>
        <select v-model="transferTo">
          <option value="" disabled>选择玩家</option>
          <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
        </select>
        <label>金额</label>
        <input type="number" v-model.number="transferAmount" min="1" />
        <label>备注（如：机会卡转让费）</label>
        <input v-model="transferReason" />
        <button class="btn block" style="margin-top:10px" :disabled="!transferTo || transferAmount <= 0"
                @click="game.act('TRANSFER_REQUEST', { toPlayerId: transferTo, amount: transferAmount, reason: transferReason }).then(ok => ok && (transferTo = '', transferAmount = 0, transferReason = ''))">
          发起转账（待对方确认）
        </button>
        <p class="muted">对方确认后才会扣款。</p>
      </div>
    </template>

    <!-- 结束回合 主 CTA -->
    <button v-if="myTurn && !me.inBankruptcy" class="btn block" @click="endTurn">✅ 结束回合</button>
    <button v-else-if="me.isHost && !myTurn" class="btn block ghost" @click="hostEndTurn">
      ⏭ 代 {{ game.currentPlayer?.nickname ?? '当前玩家' }} 结束回合
    </button>

    <CardPicker v-if="pickerDeck" :deck="pickerDeck" :deck-name="DECKS[pickerDeck]"
                @picked="onPicked" @close="pickerDeck = null" />

    <!-- 别人抽到的股票开放交易 → 走统一的底部弹层（可以先收起，窗口开到本回合结束） -->
    <BaseModal v-if="stockSheet && stockWin" :title="`${stockWin.symbol} 开放交易`"
               :source="iAmDrawer ? '你已表示不买；持仓仍可按今日价卖出'
                 : `${drawerName}抽到「${activeCardInfo?.title ?? '股票报价'}」`"
               :deck-label="DECK_SHORT[ac?.deck ?? ''] ?? '股票'"
               :deck-color="DECK_COLOR[ac?.deck ?? ''] ?? '#8FBF3F'"
               dismissable @close="game.dismissStockWindow()">
      <StockTradeBox />
      <template #actions>
        <button class="btn ghost grow" @click="game.dismissStockWindow()">不需要，收起</button>
      </template>
      <template #note>
        窗口开到 {{ drawerName }} 的回合结束，可以先收起再回来。
      </template>
    </BaseModal>
  </div>
</template>
