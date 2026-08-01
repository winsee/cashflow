<script setup lang="ts">
/** 空态：图标 + 一句结论 + 一句出路。别只留一片空白让人以为没加载出来。 */
defineProps<{ icon?: string; title: string; hint?: string }>()
</script>

<template>
  <div class="empty">
    <div v-if="icon" class="ic">{{ icon }}</div>
    <div class="t">{{ title }}</div>
    <div v-if="hint" class="s">{{ hint }}</div>
    <slot />
  </div>
</template>
