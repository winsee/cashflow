<script setup lang="ts">
/** 🆘 破产清算面板（说明书 P.5）：按首期付款的一半把资产卖给银行，直到月现金流转正。
 *  线下「行动」页与纯线上抽屉 full 档共用——一旦破产，两边都必须能把清算走完。 */
import { computed, ref } from 'vue'
import { confirmAction } from '../../confirm'
import { fmt, useGame } from '../../store'

/** 纯线上把「完成清算」钉在抽屉底（`.drawer-cta`），面板里就不再重复一颗 */
const props = withDefaults(defineProps<{ showResolve?: boolean }>(), { showResolve: true })

const game = useGame()
const me = computed(() => game.me)
const repayAmount = ref(1000)

/** 还差多少才能转正，是玩家真正要算的那个数 */
const bkGap = computed(() => Math.max(0, -(me.value?.derived.monthlyCashflow ?? 0)))

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
</script>

<template>
  <div v-if="me" class="card urgent">
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
    <button v-if="props.showResolve" class="btn block warn"
            @click="game.act('BANKRUPTCY_RESOLVE')">完成清算</button>
    <p class="muted" style="margin:8px 0 0">
      清算后仍为负，购车贷款、信用卡与额外负债将注销一半；若还是负值就出局。
    </p>
  </div>
</template>
