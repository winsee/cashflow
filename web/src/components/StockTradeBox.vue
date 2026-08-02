<script setup lang="ts">
/** 股票交易操作区：持仓明细 + 数量 + 买/卖 + 预估。
 *  抽卡人的待办卡与其他玩家的交易窗口共用这一块，两处口径完全一致。
 *  能买能卖由 store.myStockWindow 判定（服务端下发的 buyerScope 与我的持仓）。 */
import { computed, ref, watch } from 'vue'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'

const game = useGame()
const w = computed(() => game.myStockWindow)
const qty = ref(1)

// 换一张卡/换一轮就把股数复位，免得沿用上一次的输入
watch(() => w.value?.key, () => { qty.value = 1 })

// 只有卖得出去的人才谈得上「卖超了」：无持仓的人这一屏从头到尾不该出现卖出侧的字
const overSell = computed(() => !!w.value && w.value.canSell && qty.value > w.value.held)
const amount = computed(() => (w.value ? w.value.price * Math.max(0, qty.value) : 0))
const shortOfCash = computed(() => !!game.me && amount.value > game.me.cash)

/** 卖出预估盈亏：按引擎的扣减顺序（lots 原始顺序）逐笔比对成本价，仅供参考 */
const sellPnl = computed(() => {
  const win = w.value
  if (!win || overSell.value || qty.value <= 0) return null
  let left = qty.value, pnl = 0
  for (const lot of win.lots) {
    if (left <= 0) break
    const take = Math.min(lot.shares, left)
    pnl += take * (win.price - lot.cost_per_share)
    left -= take
  }
  return pnl
})

async function sell() {
  const win = w.value!
  const ok = await confirmAction({
    title: `卖出 ${win.symbol} ×${qty.value}？`,
    lines: [`${fmt(win.price)}/股 × ${qty.value} = ${fmt(amount.value)}`,
            `卖出后剩余 ${win.held - qty.value} 股`],
  })
  if (ok && await game.act('STOCK_SELL', { qty: qty.value }))
    game.flash(`已卖出 ${win.symbol} ×${qty.value}，得 ${fmt(amount.value)}`)
}

async function buy() {
  const win = w.value!
  const ok = await confirmAction({
    title: `买入 ${win.symbol} ×${qty.value}？`,
    lines: [`${fmt(win.price)}/股 × ${qty.value} = ${fmt(amount.value)}`],
  })
  if (ok && await game.act('STOCK_BUY', { qty: qty.value })) {
    game.markStockBought()
    game.flash(`已买入 ${win.symbol} ×${qty.value}，支付 ${fmt(amount.value)}`)
  }
}
</script>

<template>
  <template v-if="w">
    <div class="preview">
      <div class="prow">
        <span>📈 {{ w.symbol }} · 今日价</span>
        <span class="money">{{ fmt(w.price) }}/股</span>
      </div>
      <div class="prow">
        <span>我的持仓</span>
        <span v-if="!w.held" class="muted">没有 {{ w.symbol }} 持仓</span>
        <span v-else-if="w.lots.length === 1" class="money">
          {{ w.held }} 股<span class="muted">（成本 {{ fmt(w.lots[0].cost_per_share) }}/股）</span>
        </span>
        <span v-else class="money">共 {{ w.held }} 股</span>
      </div>
      <!-- 同一代码分批买入、买价不同时会分成多笔，卖出按本表顺序扣减 -->
      <template v-if="w.lots.length > 1">
        <div v-for="(lot, i) in w.lots" :key="i" class="prow lot">
          <span>· {{ lot.shares }} 股</span>
          <span>成本 {{ fmt(lot.cost_per_share) }}/股</span>
        </div>
      </template>
    </div>

    <div class="row">
      <input type="number" v-model.number="qty" min="1"
             :max="w.canBuy ? undefined : w.held" />
      <button class="btn" v-if="w.canSell" :disabled="overSell || qty <= 0" @click="sell">卖出</button>
      <button v-if="w.canBuy" class="btn gold" :disabled="qty <= 0" @click="buy">买入</button>
    </div>

    <p v-if="overSell" class="muted" style="color:var(--red)">
      最多可卖 {{ w.held }} 股
    </p>
    <p v-else-if="qty > 0" class="muted">
      {{ qty }} 股 × {{ fmt(w.price) }} = <b class="money">{{ fmt(amount) }}</b>
      <template v-if="w.canSell && sellPnl !== null">
        · 卖出预估盈亏
        <b class="money" :class="sellPnl >= 0 ? 'pos' : 'neg'">
          {{ sellPnl >= 0 ? '+' : '−' }}{{ fmt(Math.abs(sellPnl)) }}</b>
      </template>
      <template v-if="w.canBuy && shortOfCash">
        · <span style="color:var(--red)">买入现金不足，请先在「更多 · 银行」贷款</span>
      </template>
    </p>
  </template>
</template>

<style scoped>
.lot { padding-left: 8px; font-size: 12px; }
</style>
