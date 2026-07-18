<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fmt, useGame } from '../store'

const game = useGame()
const me = computed(() => game.me!)
const st = computed(() => game.state!)

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

async function buyBiz(b: FtBusiness) {
  const payload: any = { squareId: b.id }
  if (b.dice_rule) payload.diceRoll = diceRoll.value
  const ok = await game.act('FT_BUY_BUSINESS', payload)
  if (ok) showBiz.value = false
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
    <div class="row wrap" style="margin-top:8px">
      <button @click="game.act('FT_PAYDAY')">💰 现金流量日收款</button>
      <button class="ghost" @click="showBiz = !showBiz">🏢 企业投资</button>
      <button class="ghost" @click="showDreams = !showDreams">🌟 梦想</button>
    </div>
    <div class="row wrap" style="margin-top:8px">
      <button class="small ghost" v-if="!me.fasttrack.charity_forever" @click="game.act('FT_CHARITY')">💝 慈善 $100,000</button>
      <span class="badge ft" v-else>💝 已行善：每轮可掷 1–3 粒骰</span>
      <button class="small warn" @click="game.act('FT_TAX_AUDIT')">🧾 税务审计（半额）</button>
      <button class="small warn" @click="game.act('FT_LAWSUIT')">⚖️ 官司（半额）</button>
      <button class="small warn" @click="game.act('FT_DIVORCE')">💔 离婚（现金清零）</button>
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
        <button class="small" :disabled="st.ftSoldSquares.includes(b.id) || me.cash < b.down_payment"
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
        <button class="small gold" :disabled="me.cash < dreamPrice(myDream)"
                @click="game.act('FT_BUY_DREAM', { squareId: myDream.id })">买下</button>
      </div>
      <div v-for="d in othersDreams" :key="d.id" class="row between" style="padding:6px 0">
        <div>
          <b>{{ d.name }}（他人梦想）</b>
          <div class="muted">当前价 {{ fmt(dreamPrice(d)) }} · 双倍购买使其加价 100%</div>
        </div>
        <button class="small warn" :disabled="me.cash < dreamPrice(d)"
                @click="game.act('FT_DOUBLE_DREAM', { squareId: d.id })">加价</button>
      </div>
    </div>
    <p class="muted">快车道无银行贷款；现金不足不能买。</p>
  </div>
</template>
