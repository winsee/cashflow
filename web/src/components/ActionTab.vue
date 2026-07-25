<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { keyNumbers } from '../cardinfo'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'
import type { CardDto } from '../types'
import CardPicker from './CardPicker.vue'
import FasttrackPanel from './FasttrackPanel.vue'

const game = useGame()
const me = computed(() => game.me)
const st = computed(() => game.state!)
const myTurn = computed(() => game.isMyTurn)

const DECKS: Record<string, string> = {
  SMALL_DEAL: '机会 · 小生意', BIG_DEAL: '机会 · 大买卖',
  MARKET: '市场风云', DOODAD: '额外支出',
}
const pickerDeck = ref<string | null>(null)
const activeCardInfo = ref<CardDto | null>(null)

async function onPicked(card: CardDto) {
  const nums = keyNumbers(card)
  const ok = await confirmAction({
    title: `抽卡：「${card.title}」？`,
    lines: [DECKS[card.deck] ?? card.deck, ...(nums ? [nums] : []),
            '每回合只能抽一次，请核对与实体卡一致'],
  })
  if (!ok) return                       // 留在选卡列表，可重选
  pickerDeck.value = null
  if (await game.act('DRAW_CARD', { cardId: card.id })) activeCardInfo.value = card
}

const ac = computed(() => st.value.activeCard)
const iAmDrawer = computed(() => ac.value?.drawer_id === me.value?.id)

// 刷新/重连后从卡库恢复当前卡详情（否则强制卡无法结算）
watchEffect(async () => {
  const cur = ac.value
  if (!cur) { activeCardInfo.value = null; return }
  if (activeCardInfo.value?.id === cur.card_id) return
  const cards = await game.fetchCards(cur.deck)
  activeCardInfo.value = cards.find(c => c.id === cur.card_id) ?? null
})

// 银行操作
const loanAmount = ref(1000)
const repayAmount = ref(1000)
const stockQty = ref(1)
const resellTo = ref('')
const resellPrice = ref(0)
const showResell = ref(false)
const transferTo = ref('')
const transferAmount = ref(0)
const transferReason = ref('')

const others = computed(() => st.value.players.filter(p => p.id !== me.value?.id && p.phase !== 'OUT'))

const payoffOptions = computed(() => {
  if (!me.value) return []
  const l = me.value.liabilities
  const opts: { id: string; label: string; amount: number }[] = []
  if (l.mortgage) opts.push({ id: 'mortgage', label: '住房抵押贷款', amount: l.mortgage })
  if (l.school_loan) opts.push({ id: 'school_loan', label: '教育贷款', amount: l.school_loan })
  if (l.car_loan) opts.push({ id: 'car_loan', label: '购车贷款', amount: l.car_loan })
  if (l.credit_card) opts.push({ id: 'credit_card', label: '信用卡', amount: l.credit_card })
  if (l.extra) opts.push({ id: 'extra', label: '额外负债', amount: l.extra })
  for (const el of me.value.extraLiabilities) opts.push({ id: el.id, label: el.name, amount: el.amount })
  return opts
})

// 我持有的、当前股票窗口可卖的股数
const sellableShares = computed(() => {
  if (!me.value || !activeCardInfo.value || ac.value?.subtype !== 'STOCK_OFFER') return 0
  const sym = activeCardInfo.value.data.symbol
  return me.value.stocks.filter(s => s.symbol === sym).reduce((a, s) => a + s.shares, 0)
})

// 「每个人都能以此价格购买」的卡（优先股 2BIG、银行存单 CD），非抽卡人也能买
const canBuyThisStock = computed(() =>
  ac.value?.subtype === 'STOCK_OFFER' && activeCardInfo.value?.data.buyerScope === 'ALL')

// bd-031 比萨饼特许专卖店是全库唯一无市场买家的资产：标注出来，免得被当成 bug
const NO_MARKET_BUYER_TYPES = ['特许专卖店']
const noMarketBuyer = computed(() =>
  !!activeCardInfo.value && NO_MARKET_BUYER_TYPES.includes(activeCardInfo.value.data.assetType))

const bankruptable = computed(() =>
  me.value && me.value.derived.monthlyCashflow < 0 &&
  me.value.cash + me.value.derived.monthlyCashflow < 0)

const showMore = ref(false)

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
    title: stockWindow ? '结束股票报价？' : '放弃这次机会？',
    lines: stockWindow
      ? ['全员按今日价卖出的窗口将一并关闭']
      : ['机会卡将作废（本回合不能再抽卡）'],
  })
  if (ok && await game.act('CARD_DECISION', { decision: 'pass' })) activeCardInfo.value = null
}

async function stockBuy() {
  const d = activeCardInfo.value!.data
  const qty = stockQty.value
  const ok = await confirmAction({
    title: `买入 ${d.symbol} ×${qty}？`,
    lines: [`${fmt(d.price)}/股 × ${qty} = ${fmt(d.price * qty)}`],
  })
  if (ok && await game.act('STOCK_BUY', { qty }))
    game.flash(`已买入 ${d.symbol} ×${qty}，支付 ${fmt(d.price * qty)}`)
}

async function stockSell() {
  const d = activeCardInfo.value?.data
  const qty = stockQty.value
  const ok = await confirmAction({
    title: `卖出 ${d?.symbol ?? '股票'} ×${qty}？`,
    lines: d?.price != null ? [`${fmt(d.price)}/股 × ${qty} = ${fmt(d.price * qty)}`] : [],
  })
  if (ok && await game.act('STOCK_SELL', { qty }))
    game.flash(`已卖出 ×${qty}` + (d?.price != null ? `，得 ${fmt(d.price * qty)}` : ''))
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
  if (!drawn) { game.flash('未找到抽卡记录，请在「日志」中处理'); return }
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

async function payday() {
  const cf = me.value!.derived.monthlyCashflow
  const t = paydayTimes.value
  const ok = await confirmAction({
    title: `结算银行结算日 ×${t}？`,
    lines: [`月现金流 ${fmt(cf)} × ${t} = ${fmt(cf * t)}`, '经过多次请先在右侧选择次数一并结算'],
    warning: cf < 0 ? '月现金流为负，将从现金中扣除' : undefined,
  })
  if (ok && await game.act('PAYDAY', { times: t }))
    game.flash(`已结算银行结算日 ×${t}，现金${cf >= 0 ? ' +' : ' '}${fmt(cf * t)}`)
}

async function takeLoan() {
  const amt = loanAmount.value
  const interest = Math.floor(amt / 10)
  const cfAfter = me.value!.derived.monthlyCashflow - interest
  const ok = await confirmAction({
    title: `向银行贷款 ${fmt(amt)}？`,
    lines: [`每月利息 +${fmt(interest)}（月息 10%）`, `贷后月现金流 ${fmt(cfAfter)}`],
    warning: cfAfter < 0 ? '贷款后月现金流将为负！' : undefined,
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

async function payOffDebt(o: { id: string; label: string; amount: number }) {
  const ok = await confirmAction({
    title: `一次性清偿「${o.label}」？`,
    lines: [`支付 ${fmt(o.amount)}，删除该负债及对应月支出`],
  })
  if (ok && await game.act('PAY_OFF_DEBT', { liabilityId: o.id })) game.flash(`已清偿 ${o.label}`)
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

async function enterFasttrack() {
  const ok = await confirmAction({
    title: '进入快车道？',
    lines: [`当前现金 ${fmt(me.value!.cash)} 将交回银行（说明书规则）`,
            '非工资收入 ×100 换算为现金流量日收入'],
    danger: true,
  })
  if (ok && await game.act('ENTER_FASTTRACK')) game.flash('🏎️ 已进入快车道！')
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
</script>

<template>
  <div v-if="me && st">
    <!-- 慈善/停赛状态 -->
    <div v-if="me.charityTurns > 0 || me.skipTurns > 0" class="row wrap" style="margin-bottom:8px">
      <span v-if="me.charityTurns > 0" class="badge ft">💝 慈善生效中 · 还剩 {{ me.charityTurns }} 轮 · 可掷 1 或 2 粒骰</span>
      <span v-if="me.skipTurns > 0" class="badge out">⏸️ 停赛中 · 还需跳过 {{ me.skipTurns }} 轮</span>
    </div>

    <!-- 破产清算（最高优先） -->
    <div v-if="me.inBankruptcy" class="card urgent">
      <div class="todo-label urgent">本回合待办 · 破产清算</div>
      <h2>🆘 破产清算</h2>
      <p class="muted">按规则以首期付款的 50% 将资产逐项卖给银行，直至月现金流转正；然后点「完成清算」。（说明书第5页）</p>
      <div v-for="a in [...me.realEstates, ...me.businesses]" :key="a.id" class="row between" style="padding:6px 0">
        <span>{{ a.name }}（可得 {{ fmt(Math.floor(a.down_payment / 2)) }}）</span>
        <button class="small warn" @click="bankruptcySell(a.name, a.id, Math.floor(a.down_payment / 2))">卖给银行</button>
      </div>
      <div v-for="sym in [...new Set(me.stocks.map(s => s.symbol))]" :key="sym" class="row between" style="padding:6px 0">
        <span>股票 {{ sym }}</span>
        <button class="small warn" @click="bankruptcySell('股票 ' + sym, 'stock:' + sym)">半价卖出</button>
      </div>
      <div class="row" style="margin-top:8px">
        <input type="number" v-model.number="repayAmount" step="1000" min="1000" />
        <button class="small" :disabled="!me.liabilities.bank_loan" @click="bankruptcyRepay">还银行贷款</button>
      </div>
      <button class="block warn" @click="game.act('BANKRUPTCY_RESOLVE')">完成清算</button>
    </div>

    <!-- 快车道面板 -->
    <FasttrackPanel v-else-if="me.phase === 'FAST_TRACK'" />

    <template v-else-if="me.phase === 'RAT_RACE'">
      <!-- 待办：我抽的、未结算的卡 → 聚焦决策卡 -->
      <div v-if="ac && !ac.resolved && iAmDrawer && activeCardInfo"
           class="card" :class="settlePreview !== null ? 'urgent' : 'focus'">
        <div class="todo-label" :class="{ urgent: settlePreview !== null }">
          {{ settlePreview !== null ? '本回合待办 · 先结算这张卡' : '本回合待办 · 处理抽到的卡' }}
        </div>
        <div class="focus-emoji">🃏</div>
        <div class="focus-title">{{ activeCardInfo.title }}</div>
        <p class="muted" style="margin-top:0">{{ DECKS[ac.deck] }}</p>

        <template v-if="ac.subtype === 'REALESTATE' || ac.subtype === 'BUSINESS' || ac.subtype === 'COLLECTIBLE'">
          <p>首付 {{ fmt(activeCardInfo.data.downPayment) }} · 成本 {{ fmt(activeCardInfo.data.cost) }}
            · 月现金流 {{ activeCardInfo.data.cashflow < 0 ? '' : '+' }}{{ fmt(activeCardInfo.data.cashflow) }}</p>
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
          <p v-if="buyPreview && buyPreview.cashAfter < 0" class="muted" style="color:var(--red)">
            现金不足，买入前请先在下方「更多 · 银行」贷款</p>
          <div class="btn-row row wrap">
            <button @click="decideBuy">买入</button>
            <button class="ghost" @click="decidePass()">放弃</button>
            <button class="gold" @click="showResell = !showResell">转卖给玩家</button>
          </div>
        </template>

        <template v-else-if="ac.subtype === 'STOCK_OFFER'">
          <p>今日价 {{ fmt(activeCardInfo.data.price) }}/股
            <span class="muted">区间 {{ fmt(activeCardInfo.data.priceRange?.[0]) }}–{{ fmt(activeCardInfo.data.priceRange?.[1]) }}</span></p>
          <div class="row">
            <input type="number" v-model.number="stockQty" min="1" />
            <button @click="stockBuy">买入</button>
          </div>
          <p class="muted">其他玩家此刻可按今日价卖出持仓（他们的手机上会显示卖出入口）</p>
          <button class="ghost block" @click="decidePass(true)">不买了/结束报价</button>
        </template>

        <template v-else-if="ac.subtype === 'DICE_GAMBLE'">
          <p>投入 {{ fmt(activeCardInfo.data.downPayment) }}，掷 {{ activeCardInfo.data.diceCount }} 粒骰子：
            点数 {{ activeCardInfo.data.winCondition }} 得 {{ fmt(activeCardInfo.data.payout) }}，否则没有收入</p>
          <p class="muted">骰子由服务端掷出并记入日志，结果不可重掷</p>
          <div class="preview" v-if="buyPreview">
            <div class="prow"><span>投入后 · 现金</span>
              <span class="money" :class="buyPreview.cashAfter < 0 ? 'neg' : ''">{{ fmt(buyPreview.cashAfter) }}</span></div>
          </div>
          <div class="btn-row row wrap">
            <button @click="decideBuy">接受这笔生意</button>
            <button class="ghost" @click="decidePass()">放弃</button>
            <button class="gold" @click="showResell = !showResell">转卖给玩家</button>
          </div>
        </template>

        <template v-else-if="ac.subtype === 'STOCK_EVENT'">
          <p>按卡面对全员执行拆股/并股（总成本不变，此时不能交易）</p>
          <button class="block" @click="game.act('CARD_DECISION', { decision: 'apply' }).then(ok => ok && (activeCardInfo = null))">执行</button>
        </template>

        <template v-else-if="ac.subtype === 'CREDIT_OPTION'">
          <p>金额 {{ fmt(activeCardInfo.data.amount) }}，可选信用卡支付（月供 +{{ fmt(activeCardInfo.data.creditMonthly) }}）</p>
          <div class="row">
            <button @click="doodadPay('pay')">现金支付</button>
            <button class="gold" @click="doodadPay('credit')">信用卡支付</button>
          </div>
        </template>

        <template v-else>
          <p v-if="settlePreview">
            应付 <b class="money">{{ fmt(settlePreview.due) }}</b>
            <span class="muted" v-if="settlePreview.note">· {{ settlePreview.note }}</span>
          </p>
          <p class="muted">强制卡：结算后才能结束回合。</p>
          <div v-if="settlePreview && !settlePreview.waived && me.cash < settlePreview.due"
               class="row between" style="background:var(--red-soft);padding:8px 11px;border-radius:10px;margin:8px 0">
            <span style="color:var(--red);font-weight:600">现金不足，还差 {{ fmt(settlePreview.due - me.cash) }}</span>
            <button class="small gold" @click="loanAmount = Math.max(1000, Math.ceil((settlePreview.due - me.cash) / 1000) * 1000); showMore = true">去银行贷款</button>
          </div>
          <button class="block" @click="forcedSettle">
            {{ settlePreview ? (settlePreview.waived ? '确认（无需支付）' : `支付 ${fmt(settlePreview.due)}`) : '结算' }}
          </button>
        </template>

        <!-- 转卖表单：机会卡（含赌局）都可让给其他玩家（说明书 p8） -->
        <div v-if="showResell" class="card inner">
          <label>转卖对象（价格线下议定）</label>
          <select v-model="resellTo">
            <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
          </select>
          <label>转让费（对方还需按卡面价购买资产）</label>
          <input type="number" v-model.number="resellPrice" min="0" />
          <button class="block" :disabled="!resellTo"
                  @click="game.act('CARD_DECISION', { decision: 'resell', toPlayerId: resellTo, price: resellPrice }).then(ok => ok && (showResell = false, activeCardInfo = null))">
            发起转卖（待对方确认）
          </button>
        </div>

        <button class="ghost small" style="margin-top:10px" @click="undoDraw">↩️ 选错卡？撤销重选</button>
      </div>

      <!-- 股票交易窗口（非抽卡人）：卖出人人可用，买入看 buyerScope -->
      <div v-if="ac && ac.subtype === 'STOCK_OFFER' && !iAmDrawer" class="card focus">
        <div class="todo-label">股票交易窗口</div>
        <h2 style="margin-top:2px">📈 {{ activeCardInfo?.title ?? '股票报价' }}</h2>
        <p class="muted">
          {{ game.currentPlayer?.nickname }} 抽到股票报价，你可按今日价格卖出该股持仓<template v-if="canBuyThisStock">；这张卡注明人人可买，你也能买入</template>
        </p>
        <div class="row">
          <input type="number" v-model.number="stockQty" min="1" />
          <button @click="stockSell">卖出</button>
          <button v-if="canBuyThisStock" class="gold" @click="stockBuy">买入</button>
        </div>
      </div>

      <!-- 本回合待办：停留格分诊（我的回合） -->
      <div v-if="myTurn" class="card">
        <div class="todo-label">本回合待办 · 你停在哪种格子？</div>
        <div class="section-title">机会 / 市场 / 支出（抽卡）</div>
        <div class="pill-row">
          <button v-for="(name, deck) in DECKS" :key="deck" class="pill"
                  :class="{ done: st.turnSquareUsed }"
                  :disabled="(!!ac && !ac.resolved) || st.turnSquareUsed"
                  @click="pickerDeck = deck as string">{{ name }}</button>
        </div>

        <div class="section-title">银行结算日</div>
        <div class="row">
          <button class="pill grow" :class="{ done: st.turnPaydayUsed }" :disabled="st.turnPaydayUsed" @click="payday">
            {{ st.turnPaydayUsed ? '💰 已结算' : '💰 结算银行结算日' }}
          </button>
          <select v-model.number="paydayTimes" :disabled="st.turnPaydayUsed"
                  style="width:96px" title="本轮经过/停留次数">
            <option v-for="n in 3" :key="n" :value="n">×{{ n }} 次</option>
          </select>
        </div>

        <div class="section-title">其他停留格</div>
        <div class="pill-row">
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="addChild">👶 生孩子</button>
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="charity">💝 慈善（总收入10%）</button>
          <button class="pill" :class="{ done: st.turnSquareUsed }" :disabled="st.turnSquareUsed" @click="unemployment">📉 失业（付总支出停2轮）</button>
        </div>
        <p v-if="st.turnSquareUsed" class="muted" style="margin-top:8px">✅ 本回合已声明停留格事件（每回合只停一格；误录请房主在「日志」中撤销）</p>

        <button v-if="me.derived.canEnterFasttrack" class="block gold" style="margin-top:12px" @click="enterFasttrack">
          🏎️ 进入快车道（现金交回银行，财产换算 ×100）
        </button>
        <button v-if="bankruptable" class="block warn" style="margin-top:8px" @click="startBankruptcy">🆘 进入破产流程</button>
      </div>
    </template>

    <!-- 更多操作：银行 / 转账（折叠副区） -->
    <div v-if="me.phase !== 'OUT'" class="card">
      <button class="more-toggle" @click="showMore = !showMore">
        {{ showMore ? '收起更多操作' : '⋯ 更多操作（银行 · 转账）' }}
      </button>
      <div v-if="showMore" style="margin-top:12px">
        <template v-if="me.phase === 'RAT_RACE' && !me.inBankruptcy">
          <h3>🏦 银行</h3>
          <div class="row">
            <input type="number" v-model.number="loanAmount" step="1000" min="1000" />
            <button class="small" @click="takeLoan">贷款</button>
            <button class="small ghost" :disabled="!me.liabilities.bank_loan" @click="repayLoan">还款</button>
          </div>
          <p class="muted">千元整数倍，月息 10%（每借 $1,000 月付 $100）</p>
          <template v-if="myTurn && payoffOptions.length">
            <div class="section-title">一次性清偿负债（本回合）</div>
            <div v-for="o in payoffOptions" :key="o.id" class="row between" style="padding:4px 0">
              <span>{{ o.label }} {{ fmt(o.amount) }}</span>
              <button class="small ghost" :disabled="me.cash < o.amount" @click="payOffDebt(o)">清偿</button>
            </div>
          </template>
        </template>

        <h3 :style="me.phase === 'RAT_RACE' ? 'margin-top:16px' : ''">🤝 玩家间转账</h3>
        <label>转给</label>
        <select v-model="transferTo">
          <option value="" disabled>选择玩家</option>
          <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
        </select>
        <label>金额</label>
        <input type="number" v-model.number="transferAmount" min="1" />
        <label>备注（如：机会卡转让费）</label>
        <input v-model="transferReason" />
        <button class="block" style="margin-top:10px" :disabled="!transferTo || transferAmount <= 0"
                @click="game.act('TRANSFER_REQUEST', { toPlayerId: transferTo, amount: transferAmount, reason: transferReason }).then(ok => ok && (transferTo = '', transferAmount = 0, transferReason = ''))">
          发起转账（待对方确认）
        </button>
      </div>
    </div>

    <!-- 结束回合 主 CTA -->
    <button v-if="myTurn && !me.inBankruptcy" class="block" @click="endTurn">✅ 结束回合</button>
    <button v-else-if="me.isHost && !myTurn" class="block ghost" @click="hostEndTurn">
      ⏭ 代 {{ game.currentPlayer?.nickname ?? '当前玩家' }} 结束回合
    </button>

    <CardPicker v-if="pickerDeck" :deck="pickerDeck" :deck-name="DECKS[pickerDeck]"
                @picked="onPicked" @close="pickerDeck = null" />
  </div>
</template>
