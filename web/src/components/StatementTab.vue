<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { confirmAction } from '../confirm'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import type { FtDream, Player } from '../types'
import EmptyState from './base/EmptyState.vue'

const props = defineProps<{ player?: Player }>()
const game = useGame()
const me = computed(() => props.player ?? game.me)
const d = computed(() => me.value?.derived)
const inFt = computed(() => me.value?.phase === 'FAST_TRACK')

// 记录卡翻面：老鼠赛跑那套损益表/资产负债表整体收进折叠区，只读、无任何操作按钮
const archiveOpen = ref(false)

// 清偿负债只在「自己的报表页 + 自己回合 + 还在老鼠赛跑」可用（与后端闸门一致）。
// 进快车道后记录卡已翻面封存，那边的负债不再参与计算，也就不能再清偿。
const canPayoff = computed(() =>
  !props.player && game.state?.status === 'PLAYING' &&
  game.isMyTurn && me.value?.phase === 'RAT_RACE')

// 职业卡带来的五项负债，可逐项一次性清偿（说明书 P.4）；金额为 0 也照常列出，记录卡就该有这些栏位
const FIXED_LIABILITIES = [
  { id: 'mortgage', label: '住房抵押贷款' },
  { id: 'school_loan', label: '教育贷款' },
  { id: 'car_loan', label: '购车贷款' },
  { id: 'credit_card', label: '信用卡' },
  { id: 'extra', label: '额外负债' },
] as const

const payoffRows = computed<{ id: string; label: string; amount: number }[]>(() => {
  const l = me.value!.liabilities
  const rows = FIXED_LIABILITIES.map(r => ({ id: r.id as string, label: r.label as string, amount: l[r.id] }))
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

// ---- 快车道记录卡 ----
const winProgress = computed(() => ftWinProgress(me.value!.fasttrack))
const winTarget = computed(() => me.value!.fasttrack.initial_income + FT_WIN_INCREMENT)
const ftGain = computed(() => me.value!.fasttrack.current_income - me.value!.fasttrack.initial_income)

const dreams = ref<FtDream[]>([])
onMounted(async () => {
  if (!me.value?.dreamId) return
  const board = await game.fetchFasttrackBoard()
  dreams.value = board.dreams
})
const myDream = computed(() => dreams.value.find(x => x.id === me.value?.dreamId) ?? null)
const myDreamPrice = computed(() => {
  const dm = myDream.value
  if (!dm) return 0
  return dm.price * (1 + (game.state?.dreamPriceBumps[dm.id] ?? 0))
})
const myDreamBumps = computed(() => game.state?.dreamPriceBumps[me.value?.dreamId ?? ''] ?? 0)

// 分期收款冻结中的房产 id（mk-029）：房子还挂在报表上，但已许诺给亲戚不能交易
const frozenIds = computed(() =>
  new Set((me.value?.installmentReceivables ?? []).map(r => r.asset_id)))
</script>

<template>
  <div v-if="me && d">
    <!-- ===================== 快车道记录卡（记录卡翻到背面） ===================== -->
    <template v-if="inFt">
      <div class="card gold">
        <div class="row between">
          <div>
            <div class="muted">现金流量日收入</div>
            <div class="big num">{{ fmt(me.fasttrack.current_income) }}</div>
          </div>
          <div style="text-align:right">
            <div class="muted">胜利目标</div>
            <div class="num" style="font-size:16px;font-weight:800">{{ fmt(winTarget) }}</div>
          </div>
        </div>
        <div class="progress" style="margin-top:10px"><div :style="{ width: winProgress + '%' }" /></div>
        <div class="muted" style="margin-top:5px">
          初始 {{ fmt(me.fasttrack.initial_income) }} · 已增加 {{ fmt(ftGain) }} / 需 {{ fmt(FT_WIN_INCREMENT) }}
        </div>
      </div>

      <div class="card">
        <h2>我的企业</h2>
        <table class="fin" v-if="me.fasttrack.businesses.length">
          <tbody>
            <tr v-for="b in me.fasttrack.businesses" :key="b.square_id">
              <td>{{ b.name }}</td><td class="pos">+{{ fmt(b.cashflow) }}/月</td>
            </tr>
            <tr class="total"><td>合计增量</td><td class="pos">+{{ fmt(ftGain) }}</td></tr>
          </tbody>
        </table>
        <EmptyState v-else icon="🏢" title="还没有买下任何企业"
                    hint="停在绿格时可以买断一格企业，月收入直接计入现金流量日收入" />
      </div>

      <div class="card" v-if="myDream">
        <div class="row between">
          <div>
            <div class="muted">我的梦想</div>
            <div style="font-size:15px;font-weight:800;margin-top:2px">{{ myDream.name }}</div>
          </div>
          <div style="text-align:right">
            <div class="muted">当前价</div>
            <div class="num" style="font-size:16px;font-weight:800">{{ fmt(myDreamPrice) }}</div>
          </div>
        </div>
        <div class="muted" style="margin-top:7px">
          <template v-if="myDreamBumps">
            原价 {{ fmt(myDream.price) }} · 已被加价 {{ myDreamBumps }} 次（每次按原价再叠一倍）。
          </template>
          买下即获胜。<template v-if="me.cash >= myDreamPrice">现金 {{ fmt(me.cash) }}，够了。</template>
          <template v-else>现金还差 {{ fmt(myDreamPrice - me.cash) }}。</template>
        </div>
      </div>

      <!-- 老鼠赛跑存档：只读，无任何按钮。这就是「记录卡翻面」在屏幕上的样子 -->
      <div class="card quiet" style="cursor:pointer" @click="archiveOpen = !archiveOpen">
        <div class="row between">
          <span class="muted">老鼠赛跑存档 · 记录卡已翻面</span>
          <span class="muted">{{ archiveOpen ? '收起 ⌃' : '展开 ⌄' }}</span>
        </div>
        <p v-if="archiveOpen" class="muted" style="margin:8px 0 0">
          以下数字不再参与计算，仅供查阅。
        </p>
      </div>
    </template>

    <!-- ===================== 老鼠赛跑记录卡 ===================== -->
    <div v-else class="card">
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
    </div>

    <!-- 损益表 / 资产负债表：快车道下收进存档折叠区、整体降透明、无操作按钮 -->
    <template v-if="!inFt || archiveOpen">
      <div class="card" :style="inFt ? 'opacity:.6' : ''">
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

      <div class="card" :style="inFt ? 'opacity:.6' : ''">
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
                <button v-if="o.amount > 0" class="btn ghost small" :disabled="shortfall(o.amount) > 0"
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
        <p v-if="inFt" class="muted">记录卡已翻面，以上负债不再参与计算，也不能再清偿。</p>
        <p v-else-if="!props.player && !canPayoff && game.state?.status === 'PLAYING' && me.phase !== 'OUT'" class="muted">
          清偿负债只能在自己回合进行
        </p>
        <p v-else-if="canPayoff" class="muted">
          清偿须一次性全额付清，清偿后对应的月支出一并消失（说明书 P.4）
        </p>
      </div>
    </template>
  </div>
</template>
