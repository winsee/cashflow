<script setup lang="ts">
/** 别人逃出老鼠赛跑：推给其余所有人的一屏祝贺。
 *
 *  一局只会发生几次，而且是整局的转折点 —— 值得占满一屏，而不是在日志里多一行。
 *  不自动消失（跟胜利屏一个规矩），点掉之后行动页顶部还留一条金色回执当存根。
 *  正在答复弹层的人不会看到这一屏，见 store.catchCheer 的守卫。
 *  布局照 ResultView 的胜利屏：垂直居中，不用 .tail（它的 margin-top:auto 会把内容顶散）。 */
import { computed } from 'vue'
import { fmt, useGame } from '../store'
import type { Cheer } from '../store'
import BaseButton from './base/BaseButton.vue'

defineProps<{ cheer: Cheer }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const game = useGame()
/** 看这一屏的人多半还在老鼠赛跑里；已经在快车道的就不必再被"教育"一次 */
const stillRacing = computed(() => game.me?.phase === 'RAT_RACE')
</script>

<template>
  <div class="curtain cheer">
    <div class="curtain-inner" style="justify-content:center;align-items:center">
      <div class="glyph">🏁</div>
      <h2 style="font-size:24px">{{ cheer.nickname }} 逃出老鼠赛跑了</h2>
      <div class="win-sub">非工资收入超过总支出，换到快车道去了</div>

      <div class="win-box">
        <div class="t">
          {{ cheer.nickname }}<template v-if="cheer.profession"> · {{ cheer.profession }}</template>
        </div>
        <div class="s">现金流量日收入 {{ fmt(cheer.income) }} · 第 {{ cheer.turn }} 轮</div>
      </div>

      <BaseButton variant="gold" block style="margin-top:4px" @click="emit('close')">知道了</BaseButton>
      <p v-if="stillRacing" class="fineprint">
        你的非工资收入超过总支出，就能跟上去
      </p>
    </div>
  </div>
</template>
