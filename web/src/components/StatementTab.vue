<script setup lang="ts">
import { computed } from 'vue'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'
import type { Player } from '../types'

const props = defineProps<{ player?: Player }>()
const game = useGame()
const me = computed(() => props.player ?? game.me)
const d = computed(() => me.value?.derived)

// 清偿负债只在「自己的报表页 + 自己回合」可用（与后端 _require_current 一致）。
// 带 player prop 的是在看别人的记录卡，战报页 status 已是 FINISHED，都不出按钮。
const canPayoff = computed(() =>
  !props.player && game.state?.status === 'PLAYING' &&
  game.isMyTurn && me.value?.phase !== 'OUT')

// 职业卡带来的五项负债，可逐项一次性清偿（说明书 P.4）；金额为 0 也照常列出，记录卡就该有这些栏位
const FIXED_LIABILITIES = [
  { id: 'mortgage', label: '住房抵押贷款' },
  { id: 'school_loan', label: '教育贷款' },
  { id: 'car_loan', label: '购车贷款' },
  { id: 'credit_card', label: '信用卡' },
  { id: 'extra', label: '额外负债' },
] as const

const payoffRows = computed(() => {
  const l = me.value!.liabilities
  const rows = FIXED_LIABILITIES.map(r => ({ id: r.id as string, label: r.label, amount: l[r.id] }))
  for (const el of me.value!.extraLiabilities) rows.push({ id: el.id, label: el.name, amount: el.amount })
  return rows
})

// 现金缺口：>0 说明现在还清不起，按钮置灰并直接把差额写在按钮上
const shortfall = (amount: number) => amount - (me.value?.cash ?? 0)
const payoffLabel = (amount: number) =>
  shortfall(amount) > 0 ? `差 ${fmt(shortfall(amount))}` : '清偿'

async function payOffDebt(label: string, id: string, amount: number) {
  const ok = await confirmAction({
    title: `一次性清偿「${label}」？`,
    lines: [`支付 ${fmt(amount)}，删除该负债及对应月支出`, '不支持部分清偿（说明书 P.4）'],
  })
  if (ok && await game.act('PAY_OFF_DEBT', { liabilityId: id })) game.flash(`已清偿 ${label}`)
}

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
      <table class="fin payoff">
        <tbody>
          <tr v-for="o in payoffRows" :key="o.id">
            <td>{{ o.label }}</td>
            <td>{{ fmt(o.amount) }}</td>
            <td v-if="canPayoff">
              <button v-if="o.amount > 0" class="small ghost" :disabled="shortfall(o.amount) > 0"
                      @click="payOffDebt(o.label, o.id, o.amount)">{{ payoffLabel(o.amount) }}</button>
            </td>
          </tr>
          <tr v-for="r in me.realEstates" :key="r.id">
            <td>🏠 {{ r.name }} 抵押</td><td>{{ fmt(r.mortgage) }}</td>
            <td v-if="canPayoff" class="muted">随房产出售注销</td>
          </tr>
          <tr>
            <td>银行贷款</td><td>{{ fmt(me.liabilities.bank_loan) }}</td>
            <td v-if="canPayoff" class="muted">在「行动」页还款</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!props.player && !canPayoff && game.state?.status === 'PLAYING' && me.phase !== 'OUT'" class="muted">
        清偿负债只能在自己回合进行
      </p>
      <p v-else-if="canPayoff" class="muted">
        清偿须一次性全额付清，清偿后对应的月支出一并消失（说明书 P.4）
      </p>
    </div>
  </div>
</template>
