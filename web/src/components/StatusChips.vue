<script setup lang="ts">
/** 持续状态徽章行：一处派生（`statuses.ts`），牌桌 / 总览 / 本人徽章共用。
 *
 *  默认只画主状态（停赛 / 慈善 / 破产 / 出局）——牌桌一行装不下更多；
 *  `minor` 打开才把次要状态（快车道、分期收款、孩子数）一并画出来，那是总览页的活。 */
import { computed } from 'vue'
import { playerStatuses } from '../statuses'
import type { Player } from '../types'

const props = defineProps<{ player: Player; minor?: boolean }>()

const list = computed(() =>
  playerStatuses(props.player).filter(s => props.minor || s.major))
</script>

<template>
  <div v-if="list.length" class="badge-row">
    <span v-for="s in list" :key="s.key + s.label" class="badge" :class="s.tone" :title="s.detail">
      {{ s.icon }} {{ s.label }}
    </span>
  </div>
</template>
