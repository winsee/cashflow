<script setup lang="ts">
/** 第 ② 步：处理落点（design/09 §4.3）。
 *
 *  「你停在哪」由服务端派发，这里只负责翻译成「你现在要决定什么」。
 *  只有机会格需要玩家做子选择（大 / 小生意），其余落点要么是「发牌 → 决策」，
 *  要么是「自动 → 回执」。
 */
import { computed } from 'vue'
import { confirmAction } from '../../confirm'
import { fmt, useGame } from '../../store'
import FtSquareCard from '../cards/FtSquareCard.vue'

const game = useGame()
const me = computed(() => game.me)
const landing = computed(() => game.state?.landing ?? null)
const board = computed(() => game.board)

const biz = computed(() => {
  if (landing.value?.type !== 'FT_BUSINESS') return null
  return board.value?.fastTrack.businesses.find(b => b.id === landing.value!.ref_id) ?? null
})
const dream = computed(() => {
  if (landing.value?.type !== 'FT_DREAM') return null
  return board.value?.fastTrack.dreams.find(d => d.id === landing.value!.ref_id) ?? null
})
/** 梦想被加价过就翻倍累加（服务端的 dreamPriceBumps 是权威，这里只作展示） */
const dreamPrice = computed(() => {
  const d = dream.value
  if (!d) return 0
  return d.price * (1 + (game.state?.dreamPriceBumps[d.id] ?? 0))
})
const dreamOwner = computed(() =>
  game.state?.players.find(p => p.dreamId === dream.value?.id) ?? null)
const isMyDream = computed(() => dreamOwner.value?.id === me.value?.id)
const bizSold = computed(() =>
  !!biz.value && (game.state?.ftSoldSquares ?? []).includes(biz.value.id))

/** 慈善捐款额 = 总收入 10%（与引擎同一口径，四舍五入到美元） */
const charityCost = computed(() =>
  Math.round((me.value?.derived.totalIncome ?? 0) / 10))

async function pay(action: string, payload: Record<string, any>, title: string, lines: string[]) {
  if (!await confirmAction({ title, lines, okText: '确认' })) return
  await game.act(action, payload)
}
</script>

<template>
  <div v-if="landing && !landing.resolved" class="stack" style="gap:10px">
    <!-- 机会格：唯一需要玩家做子选择的落点 -->
    <template v-if="landing.type === 'OPPORTUNITY'">
      <b style="font-size:13px">你停在机会格 · 抽哪一叠？</b>
      <p class="muted" style="margin:0">停在机会格必须抽一张牌，两叠只能选一叠。</p>
      <div class="btn-row">
        <button class="btn grow" @click="game.chooseDealSize('SMALL')">小生意</button>
        <button class="btn ghost grow" @click="game.chooseDealSize('BIG')">大买卖</button>
      </div>
    </template>

    <template v-else-if="landing.type === 'CHARITY'">
      <b style="font-size:13px">慈善事业</b>
      <p class="muted" style="margin:0">
        捐出总收入的 10%（{{ fmt(charityCost) }}），此后 3 轮可自选掷 1 或 2 粒骰。不捐也可以直接结束回合。
      </p>
      <button class="btn block" @click="pay('CHARITY', {}, '捐款做慈善？',
        [`将支付 ${fmt(charityCost)}`, '此后 3 轮内可自选掷 1 或 2 粒骰'])">
        捐 {{ fmt(charityCost) }}
      </button>
    </template>

    <template v-else-if="landing.type === 'UNEMPLOYMENT'">
      <b style="font-size:13px">失业</b>
      <p class="muted" style="margin:0">
        需支付一次总支出 {{ fmt(me?.derived.totalExpenses) }}，并停赛 2 轮。现金不够可先向银行贷款。
      </p>
      <button class="btn block warn" @click="pay('UNEMPLOYMENT', {}, '支付失业损失？',
        [`将支付 ${fmt(me?.derived.totalExpenses)}`, '随后停赛 2 轮'])">
        支付 {{ fmt(me?.derived.totalExpenses) }}
      </button>
    </template>

    <!-- 快车道绿格 -->
    <template v-else-if="landing.type === 'FT_BUSINESS' && biz">
      <FtSquareCard kind="biz" :kind-label="biz.dice_rule ? '企业投资 · 需掷骰' : '企业投资'"
                    :name="biz.name" :taken="bizSold"
                    :nums="[{ label: '首付', value: fmt(biz.down_payment) },
                            { label: '月现金流', value: '+' + fmt(biz.cashflow) }]"
                    :tip="biz.dice_rule ? `掷 1 粒骰，${biz.dice_rule.threshold} 点及以上才成功（骰子由服务端摇）` : ''" />
      <button v-if="!bizSold" class="btn block"
              @click="pay('FT_BUY_BUSINESS', { squareId: biz.id }, '买下这项企业投资？',
                [`将支付 ${fmt(biz.down_payment)}`])">
        买入 {{ fmt(biz.down_payment) }}
      </button>
    </template>

    <!-- 快车道粉格：自己的直接买下即获胜；别人的可加价；无主的可原价占位 -->
    <template v-else-if="landing.type === 'FT_DREAM' && dream">
      <FtSquareCard kind="dream" :kind-label="isMyDream ? '梦想 · 这是你的' : '梦想'"
                    :name="dream.name" :mine="isMyDream"
                    :nums="[{ label: '价格', value: fmt(dreamPrice) }]"
                    :tip="dreamOwner && !isMyDream ? `${dreamOwner.nickname} 选定的梦想，你只能加价` : ''" />
      <button v-if="isMyDream" class="btn block gold"
              @click="pay('FT_BUY_DREAM', { squareId: dream.id }, '买下你的梦想？',
                [`将支付 ${fmt(dreamPrice)}`, '买下即获胜'])">
        买下我的梦想 {{ fmt(dreamPrice) }}
      </button>
      <button v-else-if="dreamOwner" class="btn block"
              @click="pay('FT_DOUBLE_DREAM', { squareId: dream.id }, '给这个梦想加价？',
                [`将支付 ${fmt(dreamPrice)}`, '此后该梦想的价格翻一倍'])">
        加价 {{ fmt(dreamPrice) }}
      </button>
      <button v-else class="btn block"
              @click="pay('FT_CLAIM_DREAM', { squareId: dream.id }, '原价买下占位？',
                [`将支付 ${fmt(dreamPrice)}`, '纯粹占位：不获胜、不加价、不改任何人的现金流'])">
        买下占位 {{ fmt(dreamPrice) }}
      </button>
    </template>

    <template v-else-if="landing.type === 'FT_CHARITY'">
      <b style="font-size:13px">慈善事业</b>
      <p class="muted" style="margin:0">
        捐 {{ fmt(board?.fastTrack.charityCost) }}，此后**永久**可自选掷 1、2 或 3 粒骰。
      </p>
      <button class="btn block"
              @click="pay('FT_CHARITY', {}, '捐款做慈善？',
                [`将支付 ${fmt(board?.fastTrack.charityCost)}`, '此后永久可自选掷 1–3 粒骰'])">
        捐 {{ fmt(board?.fastTrack.charityCost) }}
      </button>
    </template>
  </div>
</template>
