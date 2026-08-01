<script setup lang="ts">
/** 「要我响应」的统一入口：别人的动作波及到我时，一律走 BaseModal 这一种底部弹层。
 *  同时来两条就排队，一次只显示一条（队列由 game.myPrompts 的顺序决定），绝不叠弹层。
 *
 *  市场求购要特别对待：一张求购卡说的是资产**类别**，服务端会为我名下每一套符合条件的
 *  资产各推一条 prompt。界面必须把同一张卡的这几条合成一屏、逐套列出让我自己勾，
 *  **绝不替玩家决定卖哪一套，也绝不一次全卖** —— 每套的抵押与现金流都不一样，
 *  卖错一套可能直接把自己送进破产。要约也不因为「卖了会亏」而隐藏或折叠。 */
import { computed, ref, watch } from 'vue'
import { DECK_COLOR, DECK_SHORT } from '../decks'
import { fmt, useGame } from '../store'
import type { Prompt } from '../types'
import BaseModal from './base/BaseModal.vue'
import StatRow from './base/StatRow.vue'
import GameCard from './cards/GameCard.vue'
import type { CardDto } from '../types'

const game = useGame()

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

/** 每套资产的两个数：到手现金（出价减抵押）与月现金流损失。玩家权衡的就是这一对。 */
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

/** 勾中的按价出售，没勾中的明确拒绝 —— 两边都要给服务端一个答复，否则要约会一直挂着。 */
async function submitSell(sellPicked: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    for (const p of sellGroup.value) {
      const accept = sellPicked && picked.value.has(p.id)
      await game.act('MARKET_SELL', { promptId: p.id, accept })
    }
    if (sellPicked && pickedList.value.length)
      game.flash(`已卖出 ${pickedList.value.length} 项，到手 ${fmt(sumCash.value)}`)
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
    <p class="muted" style="margin:0">
      这张卡求购<b style="color:var(--text)">{{ matchedTypes || '这类资产' }}</b>，
      你名下有 <b style="color:var(--text)">{{ sellGroup.length }} 项</b>属于这一类，选择卖哪几项。
    </p>

    <div class="stack">
      <button v-for="p in sellGroup" :key="p.id" class="apick" :class="{ on: picked.has(p.id) }"
              @click="toggle(p.id)">
        <span class="box">✓</span>
        <span class="tx">
          <span class="t1">{{ p.payload.asset_name }}</span>
          <span class="t2">出价 {{ fmt(p.payload.price) }} · 抵押 {{ fmt(p.payload.mortgage) }}</span>
        </span>
        <span class="rt">
          <b :class="netOf(p) >= 0 ? 'pos' : 'neg'">{{ netOf(p) >= 0 ? '+' : '−' }}{{ fmt(Math.abs(netOf(p))) }}</b>
          <span>−{{ fmt(flowOf(p)) }}/月</span>
        </span>
      </button>
    </div>

    <template #preview>
      <div class="preview">
        <div class="prow"><span>卖 {{ pickedList.length }} 项 · 到手现金</span>
          <span class="money" :class="sumCash >= 0 ? 'pos' : 'neg'">
            {{ sumCash >= 0 ? '+' : '−' }}{{ fmt(Math.abs(sumCash)) }}</span></div>
        <div class="prow"><span>卖出后 · 现金</span>
          <span class="money">{{ fmt(me?.cash ?? 0) }} <span class="arrow">→</span> {{ fmt((me?.cash ?? 0) + sumCash) }}</span></div>
        <div class="prow"><span>卖出后 · 月现金流</span>
          <span class="money">
            {{ fmt(me?.derived.monthlyCashflow ?? 0) }} <span class="arrow">→</span>
            <b :class="(me?.derived.monthlyCashflow ?? 0) - sumFlow >= 0 ? 'pos' : 'neg'">
              {{ fmt((me?.derived.monthlyCashflow ?? 0) - sumFlow) }}</b></span></div>
      </div>
    </template>

    <template #actions>
      <button class="btn grow" :disabled="busy || !pickedList.length" @click="submitSell(true)">
        {{ pickedList.length ? `卖出选中的 ${pickedList.length} 项` : '请先勾选要卖的' }}
      </button>
      <button class="btn ghost" :disabled="busy" @click="submitSell(false)">都不卖</button>
    </template>

    <template #note>
      卖出的资产从资产负债表移除，对应月现金流一并消失。没选中的照旧保留。
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
