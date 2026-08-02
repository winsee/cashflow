<script setup lang="ts">
/** 统一底部弹层。全 App 只有这一种弹层样式，六个固定槽位：
 *  ① 把手条 ② 标题 + 来源色标 ③ 内容 ④ 前后对比 ⑤ 一主一次两个按钮 ⑥ 一句说明
 *
 *  界线：**我的待办 → 页内聚焦卡；别人的动作波及到我 → 底部弹层**，无例外。
 *  可点遮罩收起的只有「可以稍后再处理」的（如股票窗口）；必须答复的（转账、
 *  求购要约）设 dismissable=false，只留明确的两个按钮。
 */
import { ref } from 'vue'

const props = defineProps<{
  title: string
  /** 谁触发的、依据哪张卡 */
  source?: string
  /** 来源色标：牌堆色 + 文案，如 #4FA8C8 / 市场风云 */
  deckColor?: string
  deckLabel?: string
  /** 能否点遮罩收起（同时决定把手条能否下滑收起） */
  dismissable?: boolean
  /** 同时来两条时排队，右上角标「还有 N 条」；绝不叠弹层 */
  queued?: number
  /** 层级：confirm = 二次确认，压在普通弹层之上（--z-confirm）。
   *  这是唯一允许「压住另一层」的例外——它是对已展开那一层的追问。 */
  layer?: 'sheet' | 'confirm'
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

// 下滑把手条收起：只有 dismissable 的弹层才接手势，跟点遮罩关闭的规则保持一致。
const modalEl = ref<HTMLElement | null>(null)
const dragY = ref(0)
const dragging = ref(false)
let startY = 0

function onGrabDown(e: PointerEvent) {
  if (!props.dismissable) return
  startY = e.clientY
  dragging.value = true
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}
function onGrabMove(e: PointerEvent) {
  if (!dragging.value) return
  dragY.value = Math.max(0, e.clientY - startY)
}
function onGrabUp() {
  if (!dragging.value) return
  dragging.value = false
  const threshold = Math.min(96, (modalEl.value?.offsetHeight ?? 400) * 0.25)
  if (dragY.value > threshold) {
    dragY.value = modalEl.value?.offsetHeight ?? 600
    setTimeout(() => emit('close'), 200)
  } else {
    dragY.value = 0
  }
}
</script>

<template>
  <div class="modal-mask" :class="{ confirm: layer === 'confirm' }"
       @click.self="dismissable && emit('close')">
    <div ref="modalEl" class="modal" :class="{ dragging }" role="dialog" aria-modal="true"
         :style="dragY ? { transform: `translateY(${dragY}px)` } : undefined">
      <div class="sheet-grab" :class="{ grabbable: dismissable }"
           @pointerdown="onGrabDown" @pointermove="onGrabMove"
           @pointerup="onGrabUp" @pointercancel="onGrabUp"></div>
      <div class="sheet-body">
        <div class="sheet-head">
          <div class="grow">
            <h4>{{ title }}</h4>
            <div v-if="source" class="src">{{ source }}</div>
          </div>
          <div class="stack" style="align-items:flex-end;gap:4px">
            <span v-if="deckLabel" class="deck-chip"
                  :style="deckColor ? { background: deckColor } : undefined">{{ deckLabel }}</span>
            <span v-if="queued && queued > 0" class="sheet-queue">还有 {{ queued }} 条</span>
          </div>
        </div>

        <slot />

        <slot name="preview" />

        <div v-if="$slots.actions" class="row">
          <slot name="actions" />
        </div>

        <p v-if="$slots.note" class="sheet-note"><slot name="note" /></p>
      </div>
    </div>
  </div>
</template>
