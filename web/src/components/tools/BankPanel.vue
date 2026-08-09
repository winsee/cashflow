<script setup lang="ts">
/** 🏦 银行：贷款 / 还款 / 一次性还清。随时可用，不限自己回合。
 *
 *  线下辅助模式的「行动」页与纯线上模式的「账本 · 更多」页**共用这一块**。
 *  这里的文案里有规则说明（千元整数倍、月息 10%、其他负债去报表页），
 *  两份实现只会让同一句话日后各改各的。
 *
 *  调用方负责阶段闸门（`phase === 'RAT_RACE'` 才挂载）——快车道没有银行贷款。
 */
import { computed, ref } from 'vue'
import { confirmAction } from '../../confirm'
import { fmt, useGame } from '../../store'

const game = useGame()
const me = computed(() => game.me)
const loanAmount = ref(1000)
/** 供外部（强制卡「去贷款」）滚动定位 */
const root = ref<HTMLElement | null>(null)

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

/** 预填缺口金额（向上取整到千元），并滚到自己身上——「去贷款」按钮走这一条 */
function prefill(need: number) {
  loanAmount.value = Math.max(1000, Math.ceil(need / 1000) * 1000)
  requestAnimationFrame(() => root.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}

defineExpose({ root, prefill })
</script>

<template>
  <div v-if="me" ref="root" class="card">
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
</template>
