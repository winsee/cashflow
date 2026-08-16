<script setup lang="ts">
/** 非移动掷骰的全屏帘幕（design/09 §5.3 v0.25）：骰子赌局卡（`sd-013`）与
 *  快车道掷骰企业格（`FT_BUY_BUSINESS` 的 `diceRule`）。
 *
 *  **为什么这两种要一屏，而移动掷骰不要**：移动掷骰是玩家自己点轮心那颗骰子换来的，
 *  眼睛本来就在棋盘上；这两种是在**抽屉里**点了一个决策按钮换来的，而那一刻抽屉正被
 *  整张卡面撑高、`.board-stage` 被挤到最小，轮心那颗骰子按 `--bws` 只剩 20~35px，
 *  视线还停在刚点过的按钮上。按 §5.5「一件事该给多大的呈现，看它在游戏机制里有多重」，
 *  一笔六位数买入的成败不该是一颗 20px 的斑点。
 *
 *  交互照抄 `PaydayCurtain`/`PenaltyCurtain`：点任意处跳过，**不给「知道了」按钮**，
 *  **只给当事人**（旁观者维持现状——棋盘轮心那颗骰子照常转，同发薪帘幕的分工）。
 *
 *  屏上的数**全部来自 `store` 里那两份存根**（`catchDiceOutcome` 在换快照之前从事件流
 *  现抓，且本来就只给当事人），不新拉一份 payload：帘幕散场后抽屉里那张存根卡读的是
 *  同一份数据，抄两遍必然抄出两种口径。帘幕是仪式、会散场；存根是散场后还能回看的
 *  那一份（同 v0.9 ⑧ 发薪帘幕与结算日存根的分工）。
 */
import { computed } from 'vue'
import Die3d from './Die3d.vue'
import { fmt, signed, useGame } from '../../store'
import type { StageStep } from '../../stage'

const props = defineProps<{ step: Extract<StageStep, { kind: 'dice' }> }>()
defineEmits<{ (e: 'skip'): void }>()

const game = useGame()

/** 翻滚那一拍 `settling` 为假：骰子还在转，成败先不揭晓 */
const rolling = computed(() => !props.step.settling)
const total = computed(() => props.step.rolls.reduce((a, b) => a + b, 0))

/** 两种来源各给一套文案。`success` 只在落定那一拍才读——翻滚期间揭晓结果，
 *  等于让骰子转给一个已经知道答案的人看。 */
const biz = computed(() => (props.step.solo === 'FT_BUSINESS' ? game.bizStub : null))
const gamble = computed(() => (props.step.solo === 'GAMBLE' ? game.gambleStub : null))

const title = computed(() => biz.value?.name || gamble.value?.title || '掷骰')
/** 达标线：企业格是「≥ 阈值」，赌局卡的条件写在卡面上，这里只复述「掷出几点」 */
const need = computed(() => {
  const b = biz.value
  return b?.threshold ? `需 ${b.threshold} 点及以上` : ''
})
const success = computed(() => {
  if (biz.value) return biz.value.success
  if (gamble.value) return gamble.value.won
  return false
})

/** 收益行：企业格成功给月现金流或一次性收益，赌局卡给赔付；失败各写各的代价。 */
const gainLine = computed(() => {
  const b = biz.value
  if (b) {
    if (!b.success) return { label: '首付已支付 · 未获得收益', value: signed(-b.downPayment) }
    if (b.cashflow) return { label: '每月现金流', value: signed(b.cashflow) }
    return { label: '一次性收益', value: signed(b.lumpSum) }
  }
  const g = gamble.value
  if (!g) return null
  return g.won
    ? { label: '赢得', value: signed(g.payout) }
    : { label: '赌注已付', value: signed(-g.stake) }
})
</script>

<template>
  <div class="curtain dice" :class="{ ftx: step.solo === 'FT_BUSINESS', lost: !rolling && !success }"
       @click="$emit('skip')">
    <div class="curtain-inner">
      <div class="dice-title">{{ title }}</div>

      <!-- 一颗（赌局卡可能两颗）大号骰子。`--d` 在这儿写死，不吃 `--bws`：
           帘幕是全屏的，与棋盘此刻被挤成多大毫无关系。 -->
      <div class="dice-hero" :class="`n${step.rolls.length}`">
        <Die3d v-for="(r, i) in step.rolls" :key="i" :index="i"
               :value="rolling ? null : r" :rolling="rolling" />
      </div>

      <div class="conv">
        <div class="cline hero">
          <span>{{ rolling ? '骰子还在转…' : '掷出' }}</span>
          <b>{{ rolling ? '—' : `${total} 点` }}</b>
        </div>
        <div v-if="!rolling && need" class="cline"><span>达标线</span><b>{{ need }}</b></div>
        <div v-if="!rolling && gainLine" class="cline">
          <span>{{ gainLine.label }}</span><b>{{ gainLine.value }}</b>
        </div>
        <div v-if="!rolling && biz && biz.success" class="cline">
          <span>已支付首付</span><b>{{ fmt(biz.downPayment) }}</b>
        </div>
      </div>

      <h2 v-if="!rolling">{{ success ? '成功' : '未达标' }}</h2>

      <p class="fineprint">点一下跳过</p>
    </div>
  </div>
</template>
