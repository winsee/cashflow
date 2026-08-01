<script setup lang="ts">
/** 「刚刚发生在你身上」：停在行动页顶部直到本人确认，跨回合保留。
 *  底部标签栏同时亮红点，玩家在别的页面也能察觉（见 PlayView 的 actionAlert）。 */
import { useGame } from '../store'
import BaseButton from './base/BaseButton.vue'

const game = useGame()
</script>

<template>
  <div v-if="game.receipts.length" class="stack" style="margin-bottom:12px">
    <div class="todo-label urgent">刚刚发生在你身上 · {{ game.receipts.length }} 条</div>
    <div v-for="r in game.receipts" :key="r.id" class="receipt"
         :class="{ up: r.tone === 'pos', info: r.tone === 'info',
                   neutral: r.tone === 'neutral', goldline: r.tone === 'gold' }">
      <span class="ic">{{ r.icon }}</span>
      <div class="tx">
        <div class="t1">{{ r.title }}</div>
        <div class="t2">{{ r.why }}</div>
      </div>
      <span v-if="r.amount" class="amt"
            :class="r.tone === 'pos' ? 'pos' : r.tone === 'neg' ? 'neg' : ''">{{ r.amount }}</span>
    </div>
    <div class="row">
      <BaseButton variant="ghost" small class="grow" @click="game.clearReceipts()">我知道了</BaseButton>
    </div>
  </div>
</template>
