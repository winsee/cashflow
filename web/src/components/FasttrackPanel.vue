<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'

const game = useGame()
const me = computed(() => game.me!)
const st = computed(() => game.state!)
const myTurn = computed(() => game.isMyTurn)
// 停留格与收款每回合各一次（服务端权威校验，这里做禁用引导）
const squareLocked = computed(() => !myTurn.value || st.value.turnSquareUsed)
const paydayLocked = computed(() => !myTurn.value || st.value.turnPaydayUsed)

interface FtBusiness { id: string; name: string; down_payment: number; cashflow: number; dice_rule: any }
interface FtDream { id: string; name: string; price: number }

const businesses = ref<FtBusiness[]>([])
const dreams = ref<FtDream[]>([])
const showBiz = ref(false)
const showDreams = ref(false)
const diceRoll = ref(1)

onMounted(async () => {
  const b = await game.fetchFasttrackBoard()
  businesses.value = b.businesses
  dreams.value = b.dreams
})

function dreamPrice(d: FtDream): number {
  const bumps = st.value.dreamPriceBumps[d.id] ?? 0
  return d.price * (1 + bumps)
}
const myDream = computed(() => dreams.value.find(d => d.id === me.value.dreamId))
const othersDreams = computed(() => {
  const chosen = new Set(st.value.players.filter(p => p.id !== me.value.id).map(p => p.dreamId))
  return dreams.value.filter(d => chosen.has(d.id))
})

const paydayTimes = ref(1)

async function ftPayday() {
  const t = paydayTimes.value
  const amount = me.value.fasttrack.current_income * t
  const ok = await confirmAction({
    title: `现金流量日收款 ×${t}？`,
    lines: [`${fmt(me.value.fasttrack.current_income)} × ${t} = ${fmt(amount)}`],
  })
  if (ok && await game.act('FT_PAYDAY', { times: t })) game.flash(`已收款 ${fmt(amount)}`)
}

async function buyBiz(b: FtBusiness) {
  const lines = [`首期付款 ${fmt(b.down_payment)}`]
  if (b.dice_rule) lines.push(`掷骰 ${diceRoll.value} 点（≥${b.dice_rule.threshold} 才成功，失败不退款）`)
  const ok = await confirmAction({ title: `投资「${b.name}」？`, lines })
  if (!ok) return
  const payload: any = { squareId: b.id }
  if (b.dice_rule) payload.diceRoll = diceRoll.value
  if (await game.act('FT_BUY_BUSINESS', payload)) {
    showBiz.value = false
    game.flash(`已投资 ${b.name}`)
  }
}

async function buyDream(d: FtDream) {
  const ok = await confirmAction({
    title: `买下梦想「${d.name}」？`,
    lines: [`支付 ${fmt(dreamPrice(d))}`, '买下自己的梦想即获胜！'],
  })
  if (ok) await game.act('FT_BUY_DREAM', { squareId: d.id })
}

async function doubleDream(d: FtDream) {
  const ok = await confirmAction({
    title: `双倍加价「${d.name}」？`,
    lines: [`支付当前价 ${fmt(dreamPrice(d))}，使该梦想价格再翻倍`],
    danger: true,
  })
  if (ok && await game.act('FT_DOUBLE_DREAM', { squareId: d.id })) game.flash(`已加价 ${d.name}`)
}

async function ftCharity() {
  const ok = await confirmAction({
    title: '快车道慈善捐款？',
    lines: ['支付 $100,000，此后每轮可选掷 1–3 粒骰子（永久）'],
  })
  if (ok && await game.act('FT_CHARITY')) game.flash('已捐款 $100,000')
}

async function ftHit(action: string, title: string, desc: string, amount: number) {
  const ok = await confirmAction({ title, lines: [desc], warning: `将失去 ${fmt(amount)}`, danger: true })
  if (ok && await game.act(action)) game.flash(`已扣款 ${fmt(amount)}`)
}
</script>

<template>
  <div class="card" style="border-color:var(--gold)">
    <h2>🏎️ 快车道</h2>
    <p>
      现金流量日收入 <b class="num">{{ fmt(me.fasttrack.current_income) }}</b>
      <span class="muted">（初始 {{ fmt(me.fasttrack.initial_income) }}，+{{ fmt(me.fasttrack.current_income - me.fasttrack.initial_income) }} / 目标 +$50,000）</span>
    </p>
    <div class="progress" style="margin:6px 0">
      <div :style="{ width: Math.min(100, (me.fasttrack.current_income - me.fasttrack.initial_income) / 500) + '%' }" />
    </div>
    <p v-if="!myTurn" class="muted">⏳ 不是你的回合，快车道操作暂不可用</p>
    <p v-else-if="st.turnSquareUsed" class="muted">✅ 本回合已声明停留格事件（每回合只停一格；误录请房主在「日志」中撤销）</p>
    <div class="row" style="margin-top:8px">
      <button :disabled="paydayLocked" @click="ftPayday">
        {{ st.turnPaydayUsed && myTurn ? '💰 现金流量日（已收款）' : '💰 现金流量日收款' }}
      </button>
      <select v-model.number="paydayTimes" :disabled="paydayLocked"
              style="width:110px" title="本轮经过/停留次数">
        <option v-for="n in 4" :key="n" :value="n">×{{ n }} 次</option>
      </select>
    </div>
    <div class="row wrap" style="margin-top:8px">
      <button class="ghost" @click="showBiz = !showBiz">🏢 企业投资</button>
      <button class="ghost" @click="showDreams = !showDreams">🌟 梦想</button>
    </div>
    <div class="row wrap" style="margin-top:8px">
      <button class="small ghost" v-if="!me.fasttrack.charity_forever" :disabled="squareLocked"
              @click="ftCharity">💝 慈善 $100,000</button>
      <span class="badge ft" v-else>💝 已行善：每轮可掷 1–3 粒骰</span>
      <button class="small warn" :disabled="squareLocked"
              @click="ftHit('FT_TAX_AUDIT', '税务审计？', '停在税务审计格：现金减半上缴', Math.floor(me.cash / 2))">🧾 税务审计（半额）</button>
      <button class="small warn" :disabled="squareLocked"
              @click="ftHit('FT_LAWSUIT', '官司？', '停在官司格：现金减半赔付', Math.floor(me.cash / 2))">⚖️ 官司（半额）</button>
      <button class="small warn" :disabled="squareLocked"
              @click="ftHit('FT_DIVORCE', '离婚？', '停在离婚格：失去全部现金', me.cash)">💔 离婚（现金清零）</button>
    </div>

    <div v-if="showBiz" class="card inner">
      <h3>企业投资（绿格，停格后选择；已被买断的不可选）</h3>
      <div class="row" style="margin:6px 0">
        <label style="margin:0">掷骰格点数：</label>
        <select v-model.number="diceRoll" style="width:80px">
          <option v-for="n in 6" :key="n" :value="n">{{ n }}</option>
        </select>
      </div>
      <div v-for="b in businesses" :key="b.id" class="row between" style="padding:6px 0;border-bottom:1px dashed var(--line)">
        <div>
          <b>{{ b.name }}</b>
          <div class="muted">
            首期 {{ fmt(b.down_payment) }}
            <template v-if="b.dice_rule">
              · 掷骰 ≥{{ b.dice_rule.threshold }} →
              {{ b.dice_rule.lumpSum ? '领 ' + fmt(b.dice_rule.lumpSum) + ' 现金' : '+' + fmt(b.dice_rule.successCashflow) + '/月' }}
            </template>
            <template v-else>· +{{ fmt(b.cashflow) }}/月</template>
          </div>
        </div>
        <button class="small" :disabled="squareLocked || st.ftSoldSquares.includes(b.id) || me.cash < b.down_payment"
                @click="buyBiz(b)">
          {{ st.ftSoldSquares.includes(b.id) ? '已买断' : '买' }}
        </button>
      </div>
    </div>

    <div v-if="showDreams" class="card inner">
      <h3>梦想（粉格）</h3>
      <div v-if="myDream" class="row between" style="padding:6px 0">
        <div>
          <b>⭐ {{ myDream.name }}（我的梦想）</b>
          <div class="muted">当前价 {{ fmt(dreamPrice(myDream)) }} — 买下即获胜！</div>
        </div>
        <button class="small gold" :disabled="squareLocked || me.cash < dreamPrice(myDream)"
                @click="buyDream(myDream)">买下</button>
      </div>
      <div v-for="d in othersDreams" :key="d.id" class="row between" style="padding:6px 0">
        <div>
          <b>{{ d.name }}（他人梦想）</b>
          <div class="muted">当前价 {{ fmt(dreamPrice(d)) }} · 双倍购买使其加价 100%</div>
        </div>
        <button class="small warn" :disabled="squareLocked || me.cash < dreamPrice(d)"
                @click="doubleDream(d)">加价</button>
      </div>
    </div>
    <p class="muted">快车道无银行贷款；现金不足不能买。</p>
  </div>
</template>
