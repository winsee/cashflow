<script setup lang="ts">
/** 二次确认：走统一弹层，但挂在 confirm 层（压住已展开的那一层）。
 *  不可点遮罩关闭——问题必须被回答，误触遮罩当成「取消」太容易丢掉一次操作。 */
import { confirmState, settleConfirm } from '../confirm'
import BaseModal from './base/BaseModal.vue'
</script>

<template>
  <BaseModal v-if="confirmState.visible" :title="confirmState.opts.title" layer="confirm">
    <div>
      <p v-for="(line, i) in confirmState.opts.lines" :key="i" style="margin:0 0 6px">{{ line }}</p>
      <p v-if="confirmState.opts.warning" style="color:var(--red);font-weight:700;margin:6px 0 0">
        ⚠️ {{ confirmState.opts.warning }}</p>
    </div>
    <template #actions>
      <button class="btn grow" :class="{ warn: confirmState.opts.danger }"
              @click="settleConfirm(true)">{{ confirmState.opts.okText ?? '确认' }}</button>
      <button class="btn grow ghost" @click="settleConfirm(false)">取消</button>
    </template>
  </BaseModal>
</template>
