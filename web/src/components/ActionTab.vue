<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
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
  pickerDeck.value = null
  const ok = await game.act('DRAW_CARD', { cardId: card.id })
  if (ok) activeCardInfo.value = card
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
const showTransfer = ref(false)

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

const bankruptable = computed(() =>
  me.value && me.value.derived.monthlyCashflow < 0 &&
  me.value.cash + me.value.derived.monthlyCashflow < 0)

async function endTurn() {
  activeCardInfo.value = null
  await game.act('END_TURN')
}
</script>

<template>
  <div v-if="me && st">
    <!-- 回合横幅 -->
    <div class="card" style="border-color:var(--brand-dark)">
      <div class="row between">
        <div>
          <b v-if="myTurn">🎲 轮到你了（第 {{ st.turnCount }} 轮）</b>
          <b v-else>等待 {{ game.currentPlayer?.nickname ?? '—' }} 行动（第 {{ st.turnCount }} 轮）</b>
          <div class="muted" v-if="me.charityTurns > 0">💝 慈善生效：{{ me.charityTurns }} 轮内可掷 2 粒骰子</div>
          <div class="muted" v-if="me.skipTurns > 0">⏸️ 停赛中：还需跳过 {{ me.skipTurns }} 轮</div>
        </div>
        <button v-if="myTurn && !me.inBankruptcy" @click="endTurn">结束回合</button>
      </div>
    </div>

    <!-- 破产流程 -->
    <div v-if="me.inBankruptcy" class="card" style="border-color:var(--red)">
      <h2>🆘 破产清算</h2>
      <p class="muted">按规则以首期付款的 50% 将资产逐项卖给银行，直至月现金流转正；然后点「完成清算」。（说明书第5页）</p>
      <div v-for="a in [...me.realEstates, ...me.businesses]" :key="a.id" class="row between" style="padding:6px 0">
        <span>{{ a.name }}（可得 {{ fmt(Math.floor(a.down_payment / 2)) }}）</span>
        <button class="small warn" @click="game.act('BANKRUPTCY_SELL_ASSET', { assetId: a.id })">卖给银行</button>
      </div>
      <div v-for="sym in [...new Set(me.stocks.map(s => s.symbol))]" :key="sym" class="row between" style="padding:6px 0">
        <span>股票 {{ sym }}</span>
        <button class="small warn" @click="game.act('BANKRUPTCY_SELL_ASSET', { assetId: 'stock:' + sym })">半价卖出</button>
      </div>
      <div class="row" style="margin-top:8px">
        <input type="number" v-model.number="repayAmount" step="1000" min="1000" />
        <button class="small" @click="game.act('REPAY_LOAN', { amount: repayAmount })">还银行贷款</button>
      </div>
      <button class="block warn" @click="game.act('BANKRUPTCY_RESOLVE')">完成清算</button>
    </div>

    <!-- 快车道面板 -->
    <FasttrackPanel v-if="me.phase === 'FAST_TRACK'" />

    <template v-if="me.phase === 'RAT_RACE' && !me.inBankruptcy">
      <!-- 当前卡牌处理 -->
      <div v-if="ac && !ac.resolved && iAmDrawer && activeCardInfo" class="card" style="border-color:var(--gold)">
        <h2>🃏 {{ activeCardInfo.title }}</h2>
        <p class="muted">{{ DECKS[ac.deck] }}</p>

        <template v-if="ac.subtype === 'REALESTATE' || ac.subtype === 'BUSINESS'">
          <p>首付 {{ fmt(activeCardInfo.data.downPayment) }} · 成本 {{ fmt(activeCardInfo.data.cost) }}
            · 月现金流 +{{ fmt(activeCardInfo.data.cashflow) }}</p>
          <div class="row wrap">
            <button @click="game.act('CARD_DECISION', { decision: 'buy' }).then(ok => ok && (activeCardInfo = null))">买入</button>
            <button class="ghost" @click="game.act('CARD_DECISION', { decision: 'pass' }).then(ok => ok && (activeCardInfo = null))">放弃</button>
            <button class="gold" @click="showResell = !showResell">转卖给玩家</button>
          </div>
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
        </template>

        <template v-else-if="ac.subtype === 'STOCK_OFFER'">
          <p>今日价 {{ fmt(activeCardInfo.data.price) }}/股
            <span class="muted">区间 {{ fmt(activeCardInfo.data.priceRange?.[0]) }}–{{ fmt(activeCardInfo.data.priceRange?.[1]) }}</span></p>
          <div class="row">
            <input type="number" v-model.number="stockQty" min="1" />
            <button @click="game.act('STOCK_BUY', { qty: stockQty })">买入</button>
          </div>
          <p class="muted">其他玩家此刻可按今日价卖出持仓（他们的手机上会显示卖出入口）</p>
          <button class="ghost block" @click="game.act('CARD_DECISION', { decision: 'pass' }).then(ok => ok && (activeCardInfo = null))">不买了/结束报价</button>
        </template>

        <template v-else-if="ac.subtype === 'STOCK_EVENT'">
          <p>按卡面对全员执行拆股/并股</p>
          <button class="block" @click="game.act('CARD_DECISION', { decision: 'apply' }).then(ok => ok && (activeCardInfo = null))">执行</button>
        </template>

        <template v-else-if="ac.subtype === 'CREDIT_OPTION'">
          <p>金额 {{ fmt(activeCardInfo.data.amount) }}，可选信用卡支付（月供 +{{ fmt(activeCardInfo.data.creditMonthly) }}）</p>
          <div class="row">
            <button @click="game.act('CARD_DECISION', { decision: 'pay' }).then(ok => ok && (activeCardInfo = null))">现金支付</button>
            <button class="gold" @click="game.act('CARD_DECISION', { decision: 'credit' }).then(ok => ok && (activeCardInfo = null))">信用卡支付</button>
          </div>
        </template>

        <template v-else>
          <p class="muted">强制结算（现金不足请先贷款）</p>
          <button class="block" @click="game.act('CARD_DECISION', { decision: 'pay' }).then(ok => ok && (activeCardInfo = null))">结算</button>
        </template>
      </div>

      <!-- 股票卖出窗口（非抽卡人） -->
      <div v-if="ac && ac.subtype === 'STOCK_OFFER' && !iAmDrawer" class="card" style="border-color:var(--gold)">
        <h2>📈 股票卖出窗口</h2>
        <p class="muted">{{ game.currentPlayer?.nickname }} 抽到股票报价，你可按今日价格卖出该股持仓</p>
        <div class="row">
          <input type="number" v-model.number="stockQty" min="1" />
          <button @click="game.act('STOCK_SELL', { qty: stockQty })">卖出</button>
        </div>
      </div>

      <!-- 本回合行动 -->
      <div v-if="myTurn" class="card">
        <h2>抽卡（停在对应格后）</h2>
        <div class="row wrap">
          <button v-for="(name, deck) in DECKS" :key="deck" class="ghost"
                  :disabled="!!ac && !ac.resolved" @click="pickerDeck = deck as string">{{ name }}</button>
        </div>
        <h2 style="margin-top:12px">棋盘格事件</h2>
        <div class="row wrap">
          <button class="ghost" @click="game.act('PAYDAY')">💰 银行结算日</button>
          <button class="ghost" @click="game.act('ADD_CHILD')">👶 生孩子</button>
          <button class="ghost" @click="game.act('CHARITY')">💝 慈善（总收入10%）</button>
          <button class="ghost" @click="game.act('UNEMPLOYMENT')">📉 失业（付总支出停2轮）</button>
        </div>
        <div v-if="me.derived.canEnterFasttrack" style="margin-top:12px">
          <button class="block gold" @click="game.act('ENTER_FASTTRACK')">
            🏎️ 进入快车道（现金交回银行，财产换算 ×100）
          </button>
        </div>
        <div v-if="bankruptable" style="margin-top:8px">
          <button class="block warn" @click="game.act('BANKRUPTCY_START')">🆘 进入破产流程</button>
        </div>
      </div>

      <!-- 银行（任意时刻） -->
      <div class="card">
        <h2>🏦 银行</h2>
        <div class="row">
          <input type="number" v-model.number="loanAmount" step="1000" min="1000" />
          <button class="small" @click="game.act('TAKE_LOAN', { amount: loanAmount })">贷款</button>
          <button class="small ghost" :disabled="!me.liabilities.bank_loan"
                  @click="game.act('REPAY_LOAN', { amount: Math.min(loanAmount, me.liabilities.bank_loan) })">还款</button>
        </div>
        <p class="muted">千元整数倍，月息 10%（每借 $1,000 月付 $100）</p>
        <template v-if="myTurn && payoffOptions.length">
          <div class="section-title">一次性清偿负债（本回合）</div>
          <div v-for="o in payoffOptions" :key="o.id" class="row between" style="padding:4px 0">
            <span>{{ o.label }} {{ fmt(o.amount) }}</span>
            <button class="small ghost" :disabled="me.cash < o.amount"
                    @click="game.act('PAY_OFF_DEBT', { liabilityId: o.id })">清偿</button>
          </div>
        </template>
      </div>
    </template>

    <!-- 转账（两阶段皆可用） -->
    <div class="card" v-if="me.phase !== 'OUT'">
      <div class="row between">
        <h2>🤝 玩家间转账</h2>
        <button class="small ghost" @click="showTransfer = !showTransfer">{{ showTransfer ? '收起' : '发起' }}</button>
      </div>
      <div v-if="showTransfer">
        <label>转给</label>
        <select v-model="transferTo">
          <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
        </select>
        <label>金额</label>
        <input type="number" v-model.number="transferAmount" min="1" />
        <label>备注（如：机会卡转让费）</label>
        <input v-model="transferReason" />
        <button class="block" :disabled="!transferTo || transferAmount <= 0"
                @click="game.act('TRANSFER_REQUEST', { toPlayerId: transferTo, amount: transferAmount, reason: transferReason }).then(ok => ok && (showTransfer = false))">
          发起（待对方确认）
        </button>
      </div>
    </div>

    <CardPicker v-if="pickerDeck" :deck="pickerDeck" :deck-name="DECKS[pickerDeck]"
                @picked="onPicked" @close="pickerDeck = null" />
  </div>
</template>
