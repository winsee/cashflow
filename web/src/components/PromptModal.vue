<script setup lang="ts">
/** 「要我响应」的统一入口：别人的动作波及到我时，一律走 BaseModal 这一种底部弹层。
 *  同时来两条就排队，一次只显示一条（队列由 game.myPrompts 的顺序决定），绝不叠弹层。
 *
 *  市场求购要特别对待：一张求购卡说的是资产**类别**，服务端会为我名下每一套符合条件的
 *  资产各推一条 prompt。界面必须把同一张卡的这几条合成一屏、逐套列出让我自己勾，
 *  **绝不替玩家决定卖哪一套，也绝不一次全卖** —— 每套的抵押与现金流都不一样，
 *  卖错一套可能直接把自己送进破产。要约也不因为「卖了会亏」而隐藏或折叠。 */
import { computed, ref, watch } from 'vue'
import { confirmAction } from '../confirm'
import { DECK_COLOR, DECK_SHORT } from '../decks'
import { fmt, signed, toneOf, useGame } from '../store'
import type { Prompt } from '../types'
import BaseModal from './base/BaseModal.vue'
import StatRow from './base/StatRow.vue'
import GameCard from './cards/GameCard.vue'
import type { CardDto } from '../types'

const game = useGame()

/** 求购/分期要约不可点遮罩收起（必须给出答复），但如果这张市场卡根本抽错了，
 *  抽卡人自己被困在这一屏、够不着「行动」页里的撤销入口——这里给他一条直达的路，
 *  不改弹层本身能不能收起。只有抽卡人自己看得到这条链接。 */
const iAmDrawer = computed(() => game.state?.activeCard?.drawer_id === game.me?.id)
const undoing = ref(false)
async function undoDraw() {
  const cardId = game.state?.activeCard?.card_id
  if (!cardId || undoing.value) return
  const ok = await confirmAction({
    title: '撤销这次抽卡？',
    lines: ['将撤销这次抽卡，可重新选卡', '全员账目立即重算，日志保留划线痕迹'],
    danger: true,
  })
  if (!ok) return
  undoing.value = true
  try {
    if (await game.undoCardDraw(cardId)) game.flash('已撤销，请到「行动」页重新选卡')
  } finally { undoing.value = false }
}

/** 当前这一条（或这一组）。市场求购按 card_id 归组，其余一条一屏。 */
const head = computed<Prompt | null>(() => game.myPrompts[0] ?? null)

const sellGroup = computed<Prompt[]>(() => {
  const h = head.value
  if (!h || h.kind !== 'MARKET_SELL' || h.payload.subtype === 'INSTALLMENT_SALE') return []
  return game.myPrompts.filter(p =>
    p.kind === 'MARKET_SELL' && p.payload.card_id === h.payload.card_id
    && p.payload.subtype !== 'INSTALLMENT_SALE'
    // 护栏：要约指向的资产已不在我名下（被撤销重放、或先一步卖掉）就别再问我卖不卖，
    // 那是一屏没有主语的弹层。服务端只推给持有人，这里兜住时序上的空档。
    && assetOf(p) !== null)
})

/** 队列里还剩几屏（本组算一屏） */
const queued = computed(() => {
  const grouped = sellGroup.value.length || 1
  return Math.max(0, game.myPrompts.length - grouped)
})

function nickOf(id: string): string {
  return game.state?.players.find(p => p.id === id)?.nickname ?? '玩家'
}

/** 名下这项资产的完整账（成本 / 首付 / 抵押 / 月现金流），指标全从这儿现算。 */
function assetOf(p: Prompt) {
  const me = game.me
  return [...(me?.realEstates ?? []), ...(me?.businesses ?? [])]
    .find(a => a.id === p.payload.asset_id) ?? null
}
function netOf(p: Prompt): number {
  return p.payload.price - p.payload.mortgage
}

/** 「为什么弹给我」：求购卡说的是资产**类别**，命中我手上任何一项同类资产都会弹。
 *  把命中的类别写出来，免得玩家对着一张没见过的卡名找不到自己哪来的这项资产。 */
const matchedTypes = computed(() =>
  [...new Set(sellGroup.value.map(p => assetOf(p)?.asset_type).filter(Boolean))].join('、'))
function flowOf(p: Prompt): number {
  return assetOf(p)?.cashflow ?? 0
}

/** 卖出这一项之后，**我的**月现金流怎么变（不是「这项资产的现金流是多少」）。
 *  主语必须是「我的账」，才和右上角的「到手现金」以及底部的「卖出后 · 月现金流」同一口径：
 *  卖掉一套月现金流为 −$100 的房产（卡库里有 4 张），我每月是**多赚** $100。 */
function flowDeltaOf(p: Prompt): number {
  return -flowOf(p)
}

/** 「卖哪一套最划算」的口径：**到手现金 ÷ 月现金流** = 这笔现金抵得上多少个月的现金流，
 *  数越大越划算。三种情形不能落进同一个公式，各有各的说法：
 *   - 到手为负（抵押高于出价，说明书 §6.1 要向银行补差额）→ 谈不上划算，垫底；
 *   - 月现金流本来就 ≤ 0 → 既拿到钱、每月还多赚，无条件最优；
 *   - 其余 → net / cashflow。
 *  这只是**信息**：不排序、不置灰、不隐藏任何一项（`engine.py:640` 那条硬约束）。 */
function scoreOf(p: Prompt): number {
  const net = netOf(p), cf = flowOf(p)
  if (net <= 0) return -Infinity
  if (cf <= 0) return Infinity
  return net / cf
}

/** 每行第三行小字：较成本盈亏 + 换现金的划算程度。逐段给出（模板按段落防折行）。 */
function metricOf(p: Prompt): string[] {
  const a = assetOf(p)
  const net = netOf(p), cf = flowOf(p)
  const parts: string[] = []
  // `price` 已由服务端按 priceBasis 乘过套数/间数/枚数，与整项资产的 `cost` 同口径
  if (a) parts.push(`较成本 ${signed(p.payload.price - a.cost)}`)
  if (net <= 0) parts.push(`到手为负，还要倒贴 ${fmt(-net)}`)
  else if (cf <= 0) parts.push(`卖了每月还多赚 ${fmt(-cf)}`)
  else parts.push(`到手 ≈ ${Math.round(net / cf).toLocaleString('en-US')} 个月现金流`)
  return parts
}

/** ★ 落在哪一项。只在有得比（≥2 项）时给，并列则谁都不给——
 *  等价的选项之间不替玩家做决定。列表顺序**不动**，勾选时不会跳位。 */
const bestId = computed<string | null>(() => {
  const rows = sellGroup.value
  if (rows.length < 2) return null
  let best: Prompt | null = null
  let tied = false
  for (const p of rows) {
    if (scoreOf(p) === -Infinity) continue          // 倒贴的不参评
    if (!best) { best = p; continue }
    const d = scoreOf(p) - scoreOf(best)
    // 分数并列时看到手现金多的那一项；仍并列则记为平手
    const cmp = Number.isNaN(d) || d === 0 ? netOf(p) - netOf(best) : d
    if (cmp > 0) { best = p; tied = false }
    else if (cmp === 0) tied = true
  }
  return best && !tied ? best.id : null
})

// 勾选状态：默认全不选。绝不替玩家预设「全卖」。
const picked = ref<Set<string>>(new Set())
watch(() => sellGroup.value.map(p => p.id).join(','), () => { picked.value = new Set() })

function toggle(id: string) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
const pickedList = computed(() => sellGroup.value.filter(p => picked.value.has(p.id)))
const sumCash = computed(() => pickedList.value.reduce((a, p) => a + netOf(p), 0))
const sumFlow = computed(() => pickedList.value.reduce((a, p) => a + flowOf(p), 0))

const busy = ref(false)

/** 这张卡我已经卖掉几项（弹层文案与次按钮的措辞按它分两态）。
 *  换一张卡就归零——`sellGroup` 变短是「卖掉了一项」，不是「换了一张卡」，所以认 card_id。 */
const soldCount = ref(0)
watch(() => head.value?.payload.card_id, () => { soldCount.value = 0 })

/** 卖：**只答复勾中的那几条，没勾的一个字都不发**。
 *
 *  从前这里对整组都发（没勾的一律 `accept:false`），于是「先卖一套、再想想要不要卖第二套」
 *  这条路整个没有——一次提交就把剩下的要约全否了，玩家只能一开始就把要卖的全勾上。
 *  服务端从一开始就支持分次卖：`_a_market_sold` 只移除**自己那一条** prompt，其余照旧挂着；
 *  抽卡人 `TURN_ENDED` 时未答复的要约自动作废，所以「不答复」也不会把谁卡住。
 *  这是 design/09 那条通则的又一例：**UI 的闸门不许比服务端严**。
 *
 *  `sellPicked === false` 是「不再卖了」：对**剩余全部**发拒绝，一次收口。
 */
async function submitSell(sellPicked: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    // 固化本轮快照：提交循环期间服务端每处理一条就会广播新 state，sellGroup 随之变短，
    // 下面那个 watch 会把 picked 清空，循环体内再读响应式的值就全乱了。
    const pickedIds = new Set(picked.value)
    const targets = sellPicked
      ? sellGroup.value.filter(p => pickedIds.has(p.id))
      : sellGroup.value
    // 只把**服务端认下来的**那几条记成「已卖出」：`act()` 返回是否被接受，
    // 而到手为负的要约会被 `_require_cash` 拒掉（说明书 §6.1 要向银行补差额）。
    // 数错了不只是 flash 里少一个数——「已卖出 N 项」和「不再卖了」都归它管，
    // 卖失败却写着「已卖出 1 项」，那一屏就在说谎。
    const sold: typeof targets = []
    for (const p of targets) {
      if (await game.act('MARKET_SELL', { promptId: p.id, accept: sellPicked }) && sellPicked) {
        sold.push(p)
      }
    }
    if (sold.length) {
      soldCount.value += sold.length
      const cash = sold.reduce((a, p) => a + netOf(p), 0)
      game.flash(`已卖出 ${sold.length} 项，到手 ${fmt(cash)}`)
    }
  } finally { busy.value = false }
}

async function answer(kind: string, accept: boolean) {
  if (busy.value || !head.value) return
  busy.value = true
  try { await game.act(kind, { promptId: head.value.id, accept }) }
  finally { busy.value = false }
}

// 转卖确认要把卡面也摆出来：接手人付的是「转让费 + 卡面首付」两笔钱
const resellCard = ref<CardDto | null>(null)
watch(head, async (h) => {
  resellCard.value = null
  // 要约里没带 deck（那是抽卡人那侧的信息），所以整库捞一次按 id 找
  if (h?.kind !== 'RESELL_CONFIRM' || !h.payload.card_id) return
  const cards = await game.fetchCards()
  resellCard.value = cards.find(c => c.id === h.payload.card_id) ?? null
}, { immediate: true })

const me = computed(() => game.me)
</script>

<template>
  <!-- ① 市场求购：一张卡、名下多套，逐套勾选 -->
  <BaseModal v-if="sellGroup.length" title="有人求购你的资产"
             :source="`市场风云卡 · 每套出价 ${fmt(sellGroup[0].payload.price)}`"
             :deck-label="DECK_SHORT.MARKET" :deck-color="DECK_COLOR.MARKET" :queued="queued">
    <!-- 卖过之后换一句话：「还剩几项、还能接着卖」——否则玩家会以为这一屏没关掉是卡住了 -->
    <p class="muted" style="margin:0">
      <template v-if="soldCount">
        已卖出 <b style="color:var(--text)">{{ soldCount }} 项</b>，名下还有
        <b style="color:var(--text)">{{ sellGroup.length }} 项</b>符合这张卡，可以接着卖。
      </template>
      <template v-else>
        这张卡求购<b style="color:var(--text)">{{ matchedTypes || '这类资产' }}</b>，
        你名下有 <b style="color:var(--text)">{{ sellGroup.length }} 项</b>属于这一类，选择卖哪几项。
      </template>
    </p>
    <!-- 这张卡其实是抽错的：不必先勾/先答复才能改口，抽卡人自己在这一屏就能直接撤销重选 -->
    <button v-if="iAmDrawer" class="btn ghost small" style="margin-top:6px" :disabled="undoing" @click="undoDraw">
      抽错卡了？撤销这次抽卡
    </button>

    <div class="stack">
      <button v-for="p in sellGroup" :key="p.id" class="apick" :class="{ on: picked.has(p.id) }"
              @click="toggle(p.id)">
        <span class="box">✓</span>
        <span class="tx">
          <span class="t1">
            {{ p.payload.asset_name }}
            <span v-if="bestId === p.id" class="star">★ 最划算</span>
          </span>
          <!-- 每段各自不换行：折行只许发生在「·」上，不许把「首付」和它的数字拆到两行去 -->
          <span class="t2">
            <span class="seg">出价 {{ fmt(p.payload.price) }}</span> ·
            <span class="seg">抵押 {{ fmt(p.payload.mortgage) }}</span>
            <template v-if="assetOf(p)">
              · <span class="seg">首付 {{ fmt(assetOf(p)!.down_payment) }}</span>
            </template>
          </span>
          <span class="t3">
            <span v-for="(seg, i) in metricOf(p)" :key="i">
              <template v-if="i"> · </template><span class="seg">{{ seg }}</span>
            </span>
          </span>
        </span>
        <span class="rt">
          <b :class="toneOf(netOf(p))">{{ signed(netOf(p)) }}</b>
          <!-- 这一格问的是「卖掉它，**我的**月现金流怎么变」，所以负现金流的房产在这儿是绿的 +$100 -->
          <span :class="toneOf(flowDeltaOf(p))">{{ signed(flowDeltaOf(p)) }}/月</span>
        </span>
      </button>
    </div>

    <template #preview>
      <div class="preview">
        <div class="prow"><span>卖 {{ pickedList.length }} 项 · 到手现金</span>
          <span class="money" :class="toneOf(sumCash)">{{ signed(sumCash) }}</span></div>
        <div class="prow"><span>卖出后 · 现金</span>
          <span class="money">{{ fmt(me?.cash ?? 0) }} <span class="arrow">→</span> {{ fmt((me?.cash ?? 0) + sumCash) }}</span></div>
        <div class="prow"><span>卖出后 · 月现金流</span>
          <span class="money">
            {{ fmt(me?.derived.monthlyCashflow ?? 0) }} <span class="arrow">→</span>
            <b :class="toneOf((me?.derived.monthlyCashflow ?? 0) - sumFlow)">
              {{ fmt((me?.derived.monthlyCashflow ?? 0) - sumFlow) }}</b></span></div>
      </div>
    </template>

    <template #actions>
      <button class="btn grow" :disabled="busy || !pickedList.length" @click="submitSell(true)">
        {{ pickedList.length ? `卖出选中的 ${pickedList.length} 项` : '请先勾选要卖的' }}
      </button>
      <button class="btn ghost" :disabled="busy" @click="submitSell(false)">
        {{ soldCount ? '不再卖了' : '都不卖' }}
      </button>
    </template>

    <template #note>
      卖出的资产从资产负债表移除，对应月现金流一并消失。
      可以<b>先卖一套，再决定要不要卖下一套</b>；点「{{ soldCount ? '不再卖了' : '都不卖' }}」，
      或者抽卡人结束这一回合，剩下的要约就作废。
      <template v-if="bestId">★ 是「到手现金 ÷ 月现金流」最高的那一项，卖不卖仍由你决定。</template>
    </template>
  </BaseModal>

  <!-- ② 分期收款：房子只是冻结，不移房、不解押，成交当下不动现金 -->
  <BaseModal v-else-if="head?.kind === 'MARKET_SELL'" title="有人要分期买你的房产"
             :source="`市场风云卡 · 总价 ${fmt(head.payload.price)}`"
             :deck-label="DECK_SHORT.MARKET" :deck-color="DECK_COLOR.MARKET" :queued="queued">
    <div class="card inner">
      <StatRow label="房产" :value="head.payload.asset_name" />
      <StatRow label="每月收款" :value="head.payload.monthly_delta" signed />
      <StatRow label="共计" :value="`${head.payload.duration_months} 个月`" />
    </div>
    <button v-if="iAmDrawer" class="btn ghost small" style="margin-top:6px" :disabled="undoing" @click="undoDraw">
      抽错卡了？撤销这次抽卡
    </button>
    <template #actions>
      <button class="btn grow" :disabled="busy" @click="answer('MARKET_SELL', true)">接受</button>
      <button class="btn ghost grow" :disabled="busy" @click="answer('MARKET_SELL', false)">不卖</button>
    </template>
    <template #note>
      房子暂不移交也不解押，收满 {{ fmt(head.payload.price) }} 时才过户；期间该房产不能交易。
    </template>
  </BaseModal>

  <!-- ③ 转账确认：必须给出答复，不能点遮罩收起 -->
  <BaseModal v-else-if="head?.kind === 'TRANSFER_CONFIRM'"
             :title="`${nickOf(head.payload.from_player_id)} 要转给你 ${fmt(head.payload.amount)}`"
             source="玩家间转账 · 需要你确认才成交"
             deck-label="转账" :queued="queued">
    <div v-if="head.payload.reason" class="card inner">
      <StatRow label="备注" :value="head.payload.reason" />
    </div>
    <template #preview>
      <div class="preview">
        <div class="prow"><span>收下后 · 现金</span>
          <span class="money pos">{{ fmt(me?.cash ?? 0) }} <span class="arrow">→</span> {{ fmt((me?.cash ?? 0) + head.payload.amount) }}</span></div>
      </div>
    </template>
    <template #actions>
      <button class="btn grow" :disabled="busy" @click="answer('TRANSFER_CONFIRM', true)">确认收款</button>
      <button class="btn ghost grow" :disabled="busy" @click="answer('TRANSFER_CONFIRM', false)">拒绝</button>
    </template>
    <template #note>
      拒绝后这笔钱退回 {{ nickOf(head.payload.from_player_id) }}，不会有任何变动。
    </template>
  </BaseModal>

  <!-- ④ 机会卡转卖：接手人要付两笔钱，分行列出再给合计 -->
  <BaseModal v-else-if="head?.kind === 'RESELL_CONFIRM'"
             :title="`${nickOf(head.payload.from_player_id)} 把一张卡转给你`"
             source="机会卡转让 · 需要你确认才成交"
             :deck-label="DECK_SHORT[resellCard?.deck ?? ''] ?? '机会'"
             :deck-color="DECK_COLOR[resellCard?.deck ?? ''] ?? DECK_COLOR.BIG_DEAL" :queued="queued">
    <GameCard v-if="resellCard" :card="resellCard" compact />
    <div v-else class="card inner">
      <StatRow label="卡牌" :value="head.payload.title" />
    </div>
    <template #preview>
      <div class="preview">
        <div class="prow"><span>付给 {{ nickOf(head.payload.from_player_id) }} · 转让费</span>
          <span class="money neg">{{ fmt(head.payload.fee) }}</span></div>
        <div class="prow"><span>付给银行 · 卡面首付</span>
          <span class="money neg">{{ fmt(head.payload.down_payment) }}</span></div>
        <div class="prow"><span>合计</span>
          <span class="money neg">{{ fmt(head.payload.fee + head.payload.down_payment) }}</span></div>
        <div class="prow"><span>接手后 · 现金</span>
          <span class="money" :class="(me?.cash ?? 0) - head.payload.fee - head.payload.down_payment < 0 ? 'neg' : ''">
            {{ fmt((me?.cash ?? 0) - head.payload.fee - head.payload.down_payment) }}</span></div>
      </div>
    </template>
    <template #actions>
      <button class="btn grow" :disabled="busy" @click="answer('RESELL_CONFIRM', true)">确认接手</button>
      <button class="btn ghost grow" :disabled="busy" @click="answer('RESELL_CONFIRM', false)">拒绝</button>
    </template>
    <template #note>
      除转让费外还要按卡面首付买下这项资产，两笔钱都要付。
    </template>
  </BaseModal>
</template>
