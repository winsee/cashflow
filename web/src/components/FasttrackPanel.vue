<script setup lang="ts">
/** 快车道行动页。骨架和老鼠赛跑一模一样：收款 → 停留格 → 结束，只是内容换了。
 *  玩家好不容易熟悉的操作习惯，不该因为换了赛道就作废。
 *  企业与梦想改用底部弹层选择器，骰子点数收进对应那张格子卡里。 */
import { computed, onMounted, ref } from 'vue'
import { confirmAction } from '../confirm'
import { COLOR_DREAM, COLOR_FASTTRACK } from '../decks'
import { fmt, useGame } from '../store'
import type { FtBusiness, FtDream } from '../types'
import BaseModal from './base/BaseModal.vue'
import FtSquareCard from './cards/FtSquareCard.vue'

const game = useGame()
const me = computed(() => game.me!)
const st = computed(() => game.state!)
const myTurn = computed(() => game.isMyTurn)
// 停留格与收款每回合各一次（服务端权威校验，这里做禁用引导）
const squareLocked = computed(() => !myTurn.value || st.value.turnSquareUsed)
const paydayLocked = computed(() => !myTurn.value || st.value.turnPaydayUsed)

const businesses = ref<FtBusiness[]>([])
const dreams = ref<FtDream[]>([])
const sheet = ref<'' | 'biz' | 'dream'>('')
/** 每格骰子点数各记各的，免得两张掷骰格互相串 */
const diceRolls = ref<Record<string, number>>({})

onMounted(async () => {
  const b = await game.fetchFasttrackBoard()
  businesses.value = b.businesses
  dreams.value = b.dreams
})

function dreamPrice(d: FtDream): number {
  return d.price * (1 + (st.value.dreamPriceBumps[d.id] ?? 0))
}
function bumps(d: FtDream): number {
  return st.value.dreamPriceBumps[d.id] ?? 0
}
function ownerOf(d: FtDream) {
  return st.value.players.find(p => p.dreamId === d.id) ?? null
}
const myDream = computed(() => dreams.value.find(d => d.id === me.value.dreamId) ?? null)
/** 梦想选择器里排我的在前，其次是别人认领的，最后是无人认领的 */
const dreamList = computed(() => {
  const rank = (d: FtDream) => d.id === me.value.dreamId ? 0 : ownerOf(d) ? 1 : 2
  return [...dreams.value].sort((a, b) => rank(a) - rank(b))
})

const sold = (id: string) => st.value.ftSoldSquares.includes(id)

// 三步进度：现金流量日 → 停留格 → 结束
const stepPayday = computed(() => st.value.turnPaydayUsed)
const stepSquare = computed(() => st.value.turnSquareUsed)

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

/** 掷骰格的数值口径：成功后拿到的是月现金流还是一次性现金，卡面上要分清 */
function bizNums(b: FtBusiness) {
  const nums = [{ label: '首期', value: fmt(b.down_payment) }]
  if (b.dice_rule) {
    nums.push(b.dice_rule.lumpSum
      ? { label: '成功后', value: fmt(b.dice_rule.lumpSum) + ' 现金' }
      : { label: '成功后', value: '+' + fmt(b.dice_rule.successCashflow ?? 0) + '/月' })
    nums.push({ label: '需掷出', value: `≥ ${b.dice_rule.threshold}` })
  } else {
    nums.push({ label: '月现金流', value: '+' + fmt(b.cashflow) })
  }
  return nums
}

function bizLabel(b: FtBusiness): string {
  if (sold(b.id)) return '已买断'
  const gap = b.down_payment - me.value.cash
  // 快车道没有贷款，所以这里不给贷款入口，只把差额写在按钮上 —— 不留哑巴按钮
  if (gap > 0) return `差 ${fmt(gap)}`
  return '买'
}

async function buyBiz(b: FtBusiness) {
  const roll = diceRolls.value[b.id] ?? 1
  const lines = [`首期付款 ${fmt(b.down_payment)}`]
  if (b.dice_rule) lines.push(`掷出 ${roll} 点（≥${b.dice_rule.threshold} 才成功，失败不退款）`)
  const ok = await confirmAction({ title: `投资「${b.name}」？`, lines })
  if (!ok) return
  const payload: any = { squareId: b.id }
  if (b.dice_rule) payload.diceRoll = roll
  if (await game.act('FT_BUY_BUSINESS', payload)) {
    sheet.value = ''
    game.flash(`已投资 ${b.name}`)
  }
}

async function buyDream(d: FtDream) {
  const ok = await confirmAction({
    title: `买下梦想「${d.name}」？`,
    lines: [`支付 ${fmt(dreamPrice(d))}`, '买下自己的梦想即获胜，游戏结束'],
  })
  if (ok) await game.act('FT_BUY_DREAM', { squareId: d.id })
}

async function doubleDream(d: FtDream) {
  const ok = await confirmAction({
    title: `双倍加价「${d.name}」？`,
    lines: [`支付当前价 ${fmt(dreamPrice(d))}（不是原价 ${fmt(d.price)}）`,
            `${ownerOf(d)?.nickname ?? '对方'}的梦想涨到 ${fmt(d.price * (bumps(d) + 2))}`,
            '你不会拥有它，纯粹是拖慢对方'],
    danger: true,
  })
  if (ok && await game.act('FT_DOUBLE_DREAM', { squareId: d.id })) game.flash(`已加价 ${d.name}`)
}

/** 没人选的梦想：按原价买下纯粹是占位，不获胜、不影响任何人 */
async function claimDream(d: FtDream) {
  const ok = await confirmAction({
    title: `买下「${d.name}」占位？`,
    lines: [`支付原价 ${fmt(dreamPrice(d))}`, '没人选这个梦想，买下不会获胜，对任何人都没有影响'],
  })
  if (ok && await game.act('FT_CLAIM_DREAM', { squareId: d.id })) game.flash(`已买下 ${d.name} 占位`)
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
  <div>
    <!-- 三步进度条：与老鼠赛跑同构 -->
    <div class="steps">
      <span class="s" :class="stepPayday ? 'ok' : 'now'"><span class="n">{{ stepPayday ? '✓' : '1' }}</span>现金流量日</span>
      <span class="ln"></span>
      <span class="s" :class="stepSquare ? 'ok' : (stepPayday ? 'now' : '')"><span class="n">{{ stepSquare ? '✓' : '2' }}</span>停留格</span>
      <span class="ln"></span>
      <span class="s"><span class="n">3</span>结束</span>
    </div>

    <div class="card focus">
      <div class="todo-label">本回合待办 · 你停在哪种格子？</div>

      <div class="section-title">现金流量日</div>
      <div class="row">
        <button class="pill grow" :class="{ done: st.turnPaydayUsed }" :disabled="paydayLocked" @click="ftPayday">
          {{ st.turnPaydayUsed && myTurn ? '💰 已收款' : '💰 现金流量日收款' }}
        </button>
        <select v-model.number="paydayTimes" :disabled="paydayLocked"
                style="width:106px" title="本轮经过/停留次数">
          <option v-for="n in 4" :key="n" :value="n">×{{ n }} 次</option>
        </select>
      </div>

      <div class="section-title">买东西</div>
      <div class="pill-row">
        <button class="pill" :class="{ done: stepSquare }" :disabled="squareLocked" @click="sheet = 'biz'">
          <span class="dot" :style="{ background: COLOR_FASTTRACK }"></span>企业投资
        </button>
        <button class="pill" :class="{ done: stepSquare }" :disabled="squareLocked" @click="sheet = 'dream'">
          <span class="dot" :style="{ background: COLOR_DREAM }"></span>梦想
        </button>
        <button v-if="!me.fasttrack.charity_forever" class="pill" :class="{ done: stepSquare }"
                :disabled="squareLocked" @click="ftCharity">
          <span class="dot" style="background:#E8913C"></span>慈善 $100,000
        </button>
        <span v-else class="badge ft">💝 已行善：每轮可掷 1–3 粒骰</span>
      </div>

      <div class="section-title">倒霉格</div>
      <div class="pill-row">
        <button class="pill" :class="{ done: stepSquare }" :disabled="squareLocked"
                @click="ftHit('FT_TAX_AUDIT', '税务审计？', '停在税务审计格：现金减半上缴', Math.floor(me.cash / 2))">🧾 税务审计（半额）</button>
        <button class="pill" :class="{ done: stepSquare }" :disabled="squareLocked"
                @click="ftHit('FT_LAWSUIT', '官司？', '停在官司格：现金减半赔付', Math.floor(me.cash / 2))">⚖️ 官司（半额）</button>
        <button class="pill" :class="{ done: stepSquare }" :disabled="squareLocked"
                @click="ftHit('FT_DIVORCE', '离婚？', '停在离婚格：失去全部现金', me.cash)">💔 离婚（现金清零）</button>
      </div>

      <p v-if="!myTurn" class="muted" style="margin-top:10px">⏳ 不是你的回合，快车道操作暂不可用</p>
      <p v-else-if="stepSquare" class="muted" style="margin-top:10px">
        ✅ 本回合已声明停留格事件（每回合只停一格；误录请房主在「日志」中撤销）
      </p>
    </div>

    <p class="muted" style="margin:0 2px">快车道没有银行贷款，现金不够就买不了。</p>

    <!-- 企业选择器：一格只能被一个人买走，骰子点数收进对应那张卡 -->
    <BaseModal v-if="sheet === 'biz'" title="你停在哪一格企业？"
               source="一格只能被一个人买走，买下后月收入计入现金流量日收入"
               deck-label="快车道" :deck-color="COLOR_FASTTRACK" dismissable @close="sheet = ''">
      <div class="stack">
        <FtSquareCard v-for="b in businesses" :key="b.id" kind="biz"
                      :kind-label="b.dice_rule ? '企业投资 · 需掷骰' : '企业投资'"
                      :name="b.name" :nums="sold(b.id) ? [{ label: '状态', value: '已被买断' }] : bizNums(b)"
                      :taken="sold(b.id)" :poor="me.cash < b.down_payment"
                      :tip="b.dice_rule && !sold(b.id)
                        ? `失败则不退款，但这一格对你保持开放。` : undefined">
          <template #action>
            <button class="btn small" :disabled="squareLocked || sold(b.id) || me.cash < b.down_payment"
                    @click="buyBiz(b)">{{ bizLabel(b) }}</button>
          </template>
          <div v-if="b.dice_rule && !sold(b.id)" class="row wrap" style="margin-top:10px;gap:5px">
            <span class="muted" style="color:#5E7A22">你掷出</span>
            <button v-for="n in 6" :key="n" class="pill"
                    :class="{ on: (diceRolls[b.id] ?? 1) === n }"
                    style="padding:5px 10px;min-height:34px"
                    @click="diceRolls[b.id] = n">{{ n }}</button>
          </div>
        </FtSquareCard>
      </div>
      <template #note>
        买不起的格子只把差额写在按钮上 —— 快车道没有贷款入口。
      </template>
    </BaseModal>

    <!-- 梦想选择器：身份直接写在卡的类别行上 -->
    <BaseModal v-if="sheet === 'dream'" title="你停在哪一个梦想？"
               source="停自己的梦想可买下获胜，停别人的可以加价，没人选的可以原价买下占位"
               deck-label="快车道" :deck-color="COLOR_DREAM" dismissable @close="sheet = ''">
      <div class="stack">
        <FtSquareCard v-for="d in dreamList" :key="d.id" kind="dream"
                      :kind-label="d.id === me.dreamId ? '梦想 · 这是你的'
                        : ownerOf(d) ? `梦想 · ${ownerOf(d)!.nickname}的` : '梦想 · 无人认领'"
                      :name="d.name" :mine="d.id === me.dreamId"
                      :nums="d.id === me.dreamId
                        ? [{ label: '当前价', value: fmt(dreamPrice(d)) }, { label: '你的现金', value: fmt(me.cash) }]
                        : ownerOf(d)
                          ? [{ label: '原价', value: fmt(d.price) }, { label: '已加价', value: `${bumps(d)} 次` }, { label: '现价', value: fmt(dreamPrice(d)) }]
                          : [{ label: '价格', value: fmt(d.price) }]"
                      :tip="d.id === me.dreamId ? '买下立刻获胜，游戏结束。'
                        : ownerOf(d) ? `你付 ${fmt(dreamPrice(d))}（当前价，不是原价），对方的梦想涨到 ${fmt(d.price * (bumps(d) + 2))}。你不会拥有它，纯粹是拖慢对方。`
                        : '没人选这个梦想，你可以按原价买下占位，但不会获胜，对任何人都没有影响。'">
          <template #action>
            <button v-if="d.id === me.dreamId" class="btn small gold"
                    :disabled="squareLocked || me.cash < dreamPrice(d)" @click="buyDream(d)">
              {{ me.cash < dreamPrice(d) ? `差 ${fmt(dreamPrice(d) - me.cash)}` : '买下' }}
            </button>
            <button v-else-if="ownerOf(d)" class="btn small warn"
                    :disabled="squareLocked || me.cash < dreamPrice(d)" @click="doubleDream(d)">
              {{ me.cash < dreamPrice(d) ? `差 ${fmt(dreamPrice(d) - me.cash)}` : '加价' }}
            </button>
            <button v-else class="btn small"
                    :disabled="squareLocked || me.cash < dreamPrice(d)" @click="claimDream(d)">
              {{ me.cash < dreamPrice(d) ? `差 ${fmt(dreamPrice(d) - me.cash)}` : '买下占位' }}
            </button>
          </template>
        </FtSquareCard>
      </div>
      <template #note v-if="myDream">
        你的梦想「{{ myDream.name }}」当前价 {{ fmt(dreamPrice(myDream)) }}，买下即获胜。
      </template>
    </BaseModal>
  </div>
</template>
