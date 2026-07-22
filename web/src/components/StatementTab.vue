<script setup lang="ts">
import { computed } from 'vue'
import { fmt, useGame } from '../store'
import type { Player } from '../types'

const props = defineProps<{ player?: Player }>()
const game = useGame()
const me = computed(() => props.player ?? game.me)
const d = computed(() => me.value?.derived)

const ftProgress = computed(() => {
  if (!me.value || !d.value) return 0
  if (d.value.totalExpenses <= 0) return 100
  return Math.min(100, Math.round(d.value.passiveIncome / d.value.totalExpenses * 100))
})

// 分期收款冻结中的房产 id（mk-029）：房子还挂在报表上，但已许诺给亲戚不能交易
const frozenIds = computed(() =>
  new Set((me.value?.installmentReceivables ?? []).map(r => r.asset_id)))
</script>

<template>
  <div v-if="me && d">
    <div class="card">
      <div class="row between">
        <div>
          <div class="muted">银行储蓄（现金）</div>
          <div class="big num">{{ fmt(me.cash) }}</div>
        </div>
        <div style="text-align:right">
          <div class="muted">月现金流</div>
          <div class="big num" :class="d.monthlyCashflow >= 0 ? 'pos' : 'neg'">{{ fmt(d.monthlyCashflow) }}</div>
        </div>
      </div>
      <div style="margin-top:10px" v-if="me.phase === 'RAT_RACE'">
        <div class="row between muted">
          <span>离快车道：非工资收入 {{ fmt(d.passiveIncome) }} / 总支出 {{ fmt(d.totalExpenses) }}</span>
          <span>{{ ftProgress }}%</span>
        </div>
        <div class="progress"><div :style="{ width: ftProgress + '%' }" /></div>
      </div>
      <div v-if="me.phase === 'FAST_TRACK'" class="badge ft" style="margin-top:8px">
        🏎️ 快车道 · 现金流量日收入 {{ fmt(me.fasttrack.current_income) }}
        （目标 {{ fmt(me.fasttrack.initial_income + 50000) }}）
      </div>
    </div>

    <div class="card">
      <h2>损益表</h2>
      <div class="section-title">收入</div>
      <table class="fin">
        <tbody>
          <tr><td>工资</td><td>{{ fmt(me.salary) }}</td></tr>
          <tr><td>利息</td><td>{{ fmt(d.interestIncome) }}</td></tr>
          <tr><td>股利</td><td>{{ fmt(d.dividendIncome) }}</td></tr>
          <tr v-for="r in me.realEstates" :key="r.id"><td>🏠 {{ r.name }}<span v-if="frozenIds.has(r.id)" class="muted">（分期冻结）</span></td><td>{{ fmt(r.cashflow) }}</td></tr>
          <tr v-for="b in me.businesses" :key="b.id"><td>🏢 {{ b.name }}</td><td>{{ fmt(b.cashflow) }}</td></tr>
          <tr v-for="r in me.installmentReceivables" :key="r.id"><td>📄 {{ r.name }}（分期收款）</td><td>{{ fmt(r.monthly_delta) }}</td></tr>
          <tr class="total"><td>总收入（非工资 {{ fmt(d.passiveIncome) }}）</td><td>{{ fmt(d.totalIncome) }}</td></tr>
        </tbody>
      </table>

      <div class="section-title">支出</div>
      <table class="fin">
        <tbody>
          <tr><td>税金</td><td>{{ fmt(me.taxes) }}</td></tr>
          <tr><td>住房抵押贷款支出</td><td>{{ fmt(me.mortgagePayment) }}</td></tr>
          <tr><td>教育贷款支出</td><td>{{ fmt(me.schoolLoanPayment) }}</td></tr>
          <tr><td>购车贷款支出</td><td>{{ fmt(me.carLoanPayment) }}</td></tr>
          <tr><td>信用卡支出</td><td>{{ fmt(me.creditCardPayment) }}</td></tr>
          <tr><td>额外支出</td><td>{{ fmt(me.extraExpenses) }}</td></tr>
          <tr><td>其他支出</td><td>{{ fmt(me.otherExpenses) }}</td></tr>
          <tr><td>孩子支出（{{ me.childCount }} 个 × {{ fmt(me.perChildExpense) }}）</td><td>{{ fmt(d.childExpense) }}</td></tr>
          <tr><td>银行贷款支出（10%/月）</td><td>{{ fmt(d.bankLoanExpense) }}</td></tr>
          <tr v-for="l in me.extraLiabilities" :key="l.id"><td>{{ l.name }} 月供</td><td>{{ fmt(l.monthly) }}</td></tr>
          <tr class="total"><td>总支出</td><td>{{ fmt(d.totalExpenses) }}</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>资产负债表</h2>
      <div class="section-title">资产</div>
      <table class="fin">
        <tbody>
          <tr v-for="s in me.stocks" :key="s.symbol + s.cost_per_share">
            <td>📈 {{ s.symbol }} × {{ s.shares }}（成本 {{ fmt(s.cost_per_share) }}/股）</td>
            <td>{{ fmt(s.shares * s.cost_per_share) }}</td>
          </tr>
          <tr v-for="r in me.realEstates" :key="r.id">
            <td>🏠 {{ r.name }}（首期 {{ fmt(r.down_payment) }}）<span v-if="frozenIds.has(r.id)" class="muted">· 分期冻结，收满 $100,000 前不可交易</span></td><td>{{ fmt(r.cost) }}</td>
          </tr>
          <tr v-for="b in me.businesses" :key="b.id">
            <td>🏢 {{ b.name }}（首期 {{ fmt(b.down_payment) }}）</td><td>{{ fmt(b.cost) }}</td>
          </tr>
          <tr v-if="!me.stocks.length && !me.realEstates.length && !me.businesses.length">
            <td class="muted" colspan="2">暂无资产</td>
          </tr>
        </tbody>
      </table>

      <div class="section-title">负债</div>
      <table class="fin">
        <tbody>
          <tr><td>住房抵押贷款</td><td>{{ fmt(me.liabilities.mortgage) }}</td></tr>
          <tr><td>教育贷款</td><td>{{ fmt(me.liabilities.school_loan) }}</td></tr>
          <tr><td>购车贷款</td><td>{{ fmt(me.liabilities.car_loan) }}</td></tr>
          <tr><td>信用卡</td><td>{{ fmt(me.liabilities.credit_card) }}</td></tr>
          <tr><td>额外负债</td><td>{{ fmt(me.liabilities.extra) }}</td></tr>
          <tr v-for="r in me.realEstates" :key="r.id"><td>🏠 {{ r.name }} 抵押</td><td>{{ fmt(r.mortgage) }}</td></tr>
          <tr v-for="l in me.extraLiabilities" :key="l.id"><td>{{ l.name }}</td><td>{{ fmt(l.amount) }}</td></tr>
          <tr><td>银行贷款</td><td>{{ fmt(me.liabilities.bank_loan) }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
