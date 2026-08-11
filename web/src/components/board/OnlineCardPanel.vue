<script setup lang="ts">
/** 抽屉里的卡面区（纯线上模式）。纯呈现，不含按钮——
 *  决策按钮钉在抽屉底（`.drawer-cta`），由 `OnlineRoomView` 渲染，见 design/09 §2.2。
 *
 *  卡面组件与决策语义沿用既有那一套（`GameCard` / `StockTradeBox` / `CARD_DECISION`），
 *  **线下模式的 ActionTab 一行不改**——两套骨架各走各的。
 */
import { computed } from 'vue'
import { askBankLoan } from '../../bankrequest'
import { fmt, useGame } from '../../store'
import { DECK_COLOR, DECK_SHORT } from '../../decks'
import type { CardDto } from '../../types'
import GameCard from '../cards/GameCard.vue'
import StockTradeBox from '../StockTradeBox.vue'

const props = defineProps<{ card: CardDto }>()
const game = useGame()

const ac = computed(() => game.state?.activeCard ?? null)
const me = computed(() => game.me)
const iAmDrawer = computed(() => !!ac.value && ac.value.drawer_id === game.session?.playerId)
const preview = computed(() => ac.value?.settlePreview ?? null)

const deckLabel = computed(() => DECK_SHORT[ac.value?.deck ?? ''] ?? '')
const deckColor = computed(() => DECK_COLOR[ac.value?.deck ?? ''] ?? 'var(--line-2)')

const BUY_SUBTYPES = ['REALESTATE', 'BUSINESS', 'COLLECTIBLE', 'DICE_GAMBLE']
const FORCED_SUBTYPES = ['EXPENSE_EVENT', 'CASH', 'INSTALLMENT']

/** 这张卡此刻要我掏多少、还差多少现金。
 *  信用卡分支不算在内——「改记信用卡」本来就是留给现金不够的人的那条路。 */
const shortfall = computed(() => {
  const a = ac.value, m = me.value
  if (!a || a.resolved || !m || !iAmDrawer.value) return 0
  if (BUY_SUBTYPES.includes(a.subtype))
    return Math.max(0, (props.card.data.downPayment ?? 0) - m.cash)
  const pv = preview.value
  if (pv && !pv.waived && FORCED_SUBTYPES.includes(a.subtype))
    return Math.max(0, pv.due - m.cash)
  return 0
})

/** 市场卡抽卡人侧：写清「已通知 N 位持有该资产的玩家 + 谁还没决定」（沿用既有口径）。
 *  市场卡在抽卡那一瞬就 resolved（效果在伴随事件里完成），所以这一段按牌堆判断而非 resolved。 */
const marketPending = computed(() => {
  if (ac.value?.deck !== 'MARKET' || !game.state) return null
  const rows = game.state.prompts.filter(p => p.kind === 'MARKET_SELL'
    && p.payload?.card_id === ac.value!.card_id)
  return {
    total: rows.length,
    who: rows.map(p => game.state!.players.find(x => x.id === p.target_player_id)?.nickname)
      .filter(Boolean).join('、'),
  }
})
</script>

<template>
  <div class="stack" style="gap:10px">
    <div class="row between">
      <b style="font-size:13px">
        {{ iAmDrawer ? '轮到你决定' : `${game.currentPlayer?.nickname ?? '对手'} 正在决定` }}
      </b>
      <span class="deck-chip" :style="{ background: deckColor }">{{ deckLabel }}</span>
    </div>

    <GameCard :card="props.card" />

    <p v-if="marketPending" class="muted">
      <template v-if="marketPending.total">
        已通知 {{ marketPending.total }} 位持有该资产的玩家，正在等 {{ marketPending.who }} 答复
      </template>
      <template v-else>没有人持有相关资产，可以结束回合</template>
    </p>

    <template v-if="iAmDrawer && ac && !ac.resolved">
      <div v-if="['REALESTATE', 'BUSINESS', 'COLLECTIBLE'].includes(ac.subtype)" class="preview">
        <div class="prow"><span>首付</span>
          <span class="money neg">{{ fmt(props.card.data.downPayment) }}</span></div>
        <div class="prow"><span>每月现金流</span>
          <span class="money pos">+{{ fmt(props.card.data.cashflow) }}</span></div>
      </div>

      <StockTradeBox v-else-if="ac.subtype === 'STOCK_OFFER'" />

      <p v-else-if="ac.subtype === 'DICE_GAMBLE'" class="muted">
        骰子由服务端掷出并记入日志，结果不可重掷</p>

      <!-- 强制卡：金额与豁免说明由服务端 settlePreview 下发，前端不做规则判断 -->
      <template v-else-if="['EXPENSE_EVENT', 'CASH', 'INSTALLMENT'].includes(ac.subtype)">
        <div class="preview" v-if="preview">
          <div class="prow"><span>应付</span>
            <span class="money neg">{{ fmt(preview.due) }}</span></div>
          <div class="prow"><span>支付后 · 现金</span>
            <span class="money" :class="(me?.cash ?? 0) - preview.due < 0 ? 'neg' : ''">
              {{ fmt(me?.cash) }} <span class="arrow">→</span>
              {{ fmt((me?.cash ?? 0) - preview.due) }}</span></div>
        </div>
        <p v-if="preview?.note" class="muted">{{ preview.note }}</p>
      </template>

      <div v-else-if="ac.subtype === 'CREDIT_OPTION'" class="preview">
        <div class="prow"><span>应付</span>
          <span class="money neg">{{ fmt(props.card.data.amount) }}</span></div>
        <div class="prow"><span>改记信用卡 · 每月还款</span>
          <span class="money neg">+{{ fmt(props.card.data.creditMonthly) }}</span></div>
      </div>

      <!-- 钱不够：写出缺口，并给一条通往银行的路（直开资金弹层的银行块，金额已预填）。
           只写「现金不足」而不给入口，玩家在纯线上就真的无路可走。 -->
      <div v-if="shortfall > 0" class="card inner danger" style="background:var(--red-soft)">
        <div class="row between">
          <span style="font-size:12.5px;font-weight:700;color:var(--red)">
            现金还差 {{ fmt(shortfall) }}</span>
          <button class="btn small gold" @click="askBankLoan(shortfall)">去贷款</button>
        </div>
      </div>
    </template>
  </div>
</template>
