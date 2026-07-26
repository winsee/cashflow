<script setup lang="ts">
/** 座位选择列表（换设备恢复身份用）：大厅弹窗与扫码加入页共用。
 *
 *  在线/离线要标出来——接管在线座位会把原设备立刻踢下线，玩家有权先知道。
 *  但不禁用在线座位：旧设备的僵尸连接会让正当的换设备恢复卡死，见 design/01 FR-4。 */
import type { Seat } from '../types'

defineProps<{ players: Seat[]; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
</script>

<template>
  <div v-for="p in players" :key="p.id" class="list-item row between seat"
       :class="{ picked: modelValue === p.id }"
       @click="emit('update:modelValue', p.id)">
    <span>{{ modelValue === p.id ? '✅' : '👤' }} {{ p.nickname }}
      <span v-if="p.isHost" class="badge">房主</span>
      <span class="badge" :class="p.online ? 'on' : 'off'">{{ p.online ? '在线' : '离线' }}</span>
    </span>
    <span class="muted">{{ p.professionTitle }}</span>
  </div>
</template>

<style scoped>
.seat { cursor: pointer; }
.picked { background: var(--brand-soft); border-radius: 10px; }
.badge.on { color: var(--brand); }
.badge.off { color: var(--muted); }
</style>
