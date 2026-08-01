<script setup lang="ts">
/** 主按钮。裸 <button> 已降级为中性重置，凡是「看起来像按钮」的都要显式走这里或 .btn 类。
 *  一屏之内只应有一个 variant="primary"，其余降为 ghost 或收进折叠区。 */
withDefaults(defineProps<{
  /** primary=主操作 ghost=次要 warn=不可逆扣款/出局 gold=仪式（三个高光时刻）link=纯文字 */
  variant?: 'primary' | 'ghost' | 'warn' | 'gold' | 'link'
  small?: boolean
  block?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}>(), { variant: 'primary', type: 'button' })
</script>

<template>
  <button class="btn" :type="type" :disabled="disabled"
          :class="[variant === 'primary' ? '' : variant, { small, block }]">
    <slot />
  </button>
</template>
