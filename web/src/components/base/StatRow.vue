<script setup lang="ts">
/** 一行「标签 → 数值」。数值等宽对齐，正负走语义色（换肤时不跟着变）。 */
import { fmt, signed } from '../../store'

const props = withDefaults(defineProps<{
  label: string
  /** 传 number 会自动格式化成 $x,xxx；传 string 原样显示 */
  value: number | string
  /** 按正负着色（正绿负红），并给正数补 + 号 */
  signed?: boolean
  /** 强制着色，覆盖 signed 的判断 */
  tone?: 'pos' | 'neg' | ''
}>(), { tone: '' })

function text(): string {
  if (typeof props.value !== 'number') return props.value
  return props.signed ? signed(props.value) : fmt(props.value)
}
function cls(): string {
  if (props.tone) return props.tone
  if (props.signed && typeof props.value === 'number') return props.value >= 0 ? 'pos' : 'neg'
  return ''
}
</script>

<template>
  <div class="statrow">
    <span class="k">{{ label }}</span>
    <span class="v" :class="cls()">{{ text() }}</span>
  </div>
</template>
