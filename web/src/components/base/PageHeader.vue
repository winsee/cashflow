<script setup lang="ts">
/** 页面顶栏：左返回 / 中标题 / 右操作，三段固定，各页不再各写一套。 */
defineProps<{ title: string; back?: string }>()
const emit = defineEmits<{ (e: 'back'): void }>()
</script>

<template>
  <div class="appbar">
    <button v-if="back" class="btn ghost small" @click="emit('back')">{{ back }}</button>
    <span v-else class="grow"></span>
    <span class="title">{{ title }}</span>
    <span v-if="!$slots.actions" class="grow" style="text-align:right"></span>
    <slot name="actions" />
  </div>
</template>
