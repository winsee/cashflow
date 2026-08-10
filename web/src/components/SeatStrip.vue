<script setup lang="ts">
/** 一轮的行动顺序座次条（design/09 §2.0）：一眼读出现在轮到谁、这一轮还剩几个人到我。
 *
 *  HUD 与抽屉 peek 条各用一次，所以收成组件（peek 那处是可点的，点开牌桌）。
 *
 *  **角标点**是这次新加的：19px 的圆写不下字，但「还剩几个人到我」这句话，
 *  在有人停赛时本来就是错的——被跳过的人根本不会轮到。所以右下角给一个 7px 的点，
 *  颜色取该玩家优先级最高的持续状态（红=出局/破产，灰=停赛，金=慈善），
 *  全文放进 title。 */
import { computed } from 'vue'
import { majorStatus } from '../statuses'
import { useGame } from '../store'

const props = defineProps<{
  /** 可点：点开抽屉里的牌桌 */
  clickable?: boolean
}>()
const emit = defineEmits<{ (e: 'open'): void }>()

const game = useGame()

const seats = computed(() => {
  const s = game.state
  if (!s) return []
  return s.turnOrder.map((pid, i) => {
    const p = s.players.find(x => x.id === pid)
    const st = p ? majorStatus(p) : null
    return {
      id: pid, initial: p?.nickname.slice(0, 1) ?? '?',
      now: i === s.turnIndex, done: i < s.turnIndex, out: p?.phase === 'OUT',
      mark: st?.tone ?? null,
      title: st ? `${p!.nickname} · ${st.label}` : (p?.nickname ?? ''),
    }
  })
})
</script>

<template>
  <component :is="props.clickable ? 'button' : 'span'" class="seat-strip"
             :title="props.clickable ? '看牌桌' : undefined"
             @click="props.clickable && emit('open')">
    <span v-for="s in seats" :key="s.id" class="seat-dot"
          :class="{ now: s.now, done: s.done, out: s.out }" :title="s.title">
      {{ s.initial }}
      <span v-if="s.mark !== null" class="mark" :class="s.mark || 'plain'"></span>
    </span>
  </component>
</template>
