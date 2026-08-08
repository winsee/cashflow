<script setup lang="ts">
/** 对局模式徽章（design/09 §1.3）：一处定义，四处复用——建房页、大厅列表、
 *  加入房间确认卡、房间准备页。文字固定这四个字，不用「模式一 / 模式二」，
 *  那是文档里的编号，玩家不认。 */
import type { GameMode } from '../types'

const props = defineProps<{
  mode: GameMode
  /** 准备页那处带一把锁：模式在建房时选定，看起来就该是不可改的 */
  locked?: boolean
}>()

const emit = defineEmits<{ (e: 'lock'): void }>()
</script>

<template>
  <span class="badge" :class="{ turn: props.mode === 'ONLINE' }"
        :role="props.locked ? 'button' : undefined"
        @click="props.locked && emit('lock')">
    <template v-if="props.mode === 'ONLINE'">▣ 纯线上</template>
    <template v-else>⚄ 线下辅助</template>
    <template v-if="props.locked"> 🔒</template>
  </span>
</template>
