<script setup lang="ts">
import { confirmState, settleConfirm } from '../confirm'
</script>

<template>
  <div v-if="confirmState.visible" class="modal-mask confirm" @click.self="settleConfirm(false)">
    <div class="modal">
      <h2>{{ confirmState.opts.title }}</h2>
      <p v-for="(line, i) in confirmState.opts.lines" :key="i">{{ line }}</p>
      <p v-if="confirmState.opts.warning" style="color:var(--red);font-weight:700">
        ⚠️ {{ confirmState.opts.warning }}</p>
      <div class="row" style="margin-top:12px">
        <button class="grow" :class="{ warn: confirmState.opts.danger }"
                @click="settleConfirm(true)">{{ confirmState.opts.okText ?? '确认' }}</button>
        <button class="grow ghost" @click="settleConfirm(false)">取消</button>
      </div>
    </div>
  </div>
</template>
