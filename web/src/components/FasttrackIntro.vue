<script setup lang="ts">
/** 逃出老鼠赛跑的全屏过场：先预演，再承诺。
 *
 *  按钮文案是「看看能换到多少」而不是「进入快车道」—— 玩家先看到换算结果与四条后果，
 *  再决定要不要走，「再想想」随时可退。**点主按钮才真正提交。**
 *  换算与四条说明依据说明书 P.5；这里算的只是预演，服务端仍是权威。 */
import { computed } from 'vue'
import { fmt, useGame } from '../store'
import BaseButton from './base/BaseButton.vue'

const emit = defineEmits<{ (e: 'close'): void; (e: 'confirm'): void }>()

const game = useGame()
const me = computed(() => game.me!)

const passive = computed(() => me.value.derived.passiveIncome)
/** 本回合已在老鼠赛跑走过一格 → 进场后棋子只落到「在此进入」箭头，这一回合就结束了。
 *  承诺之前先说清楚，别让玩家进去以后才发现点不动。 */
const turnWillClose = computed(() => !!game.state?.turnSquareUsed)
/** 说明书 P.5：以千元为单位四舍五入得到「您的财产」，再 ×100 得现金流量日收入 */
const wealth = computed(() => Math.round(passive.value / 1000) * 1000)
const initial = computed(() => wealth.value * 100)
</script>

<template>
  <div class="curtain ftx">
    <div class="curtain-inner">
      <div class="glyph">🏁</div>
      <h2>你逃出老鼠赛跑了</h2>

      <div class="conv">
        <div class="cline"><span>非工资收入</span><b>{{ fmt(passive) }}</b></div>
        <div class="arrow">↓ 以千元为单位四舍五入</div>
        <div class="cline"><span>你的财产</span><b>{{ fmt(wealth) }}</b></div>
        <div class="arrow">↓ × 100</div>
        <div class="cline hero"><span>现金流量日收入</span><b>{{ fmt(initial) }}</b></div>
      </div>

      <div class="facts">
        <div class="fact"><i>①</i><span>银行<b>立刻发放 {{ fmt(initial) }}</b> 到你的账上，作为进入快车道的启动资金。</span></div>
        <div class="fact"><i>②</i><span>此后每次<b>停在或经过「现金流量日」</b>，再领 {{ fmt(initial) }}。</span></div>
        <div class="fact"><i>③</i><span>老鼠赛跑的记录卡<b>翻面封存</b>，那边的资产、负债与收支不再计入。</span></div>
        <div class="fact"><i>④</i><span>胜利条件二选一：<b>现金流量日收入涨到 {{ fmt(initial + 50000) }}</b>，或<b>买下自己的梦想</b>。</span></div>
        <div v-if="turnWillClose" class="fact"><i>⑤</i><span>本回合你已经在老鼠赛跑走过一格，<b>进场后本回合就到此为止</b>；下一回合起才在外环掷骰移动。</span></div>
      </div>

      <div class="tail">
        <BaseButton variant="gold" block @click="emit('confirm')">进入快车道</BaseButton>
        <BaseButton variant="ghost" small block @click="emit('close')">再想想</BaseButton>
        <p class="fineprint">依据游戏说明书 P.5</p>
      </div>
    </div>
  </div>
</template>
