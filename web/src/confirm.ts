import { reactive } from 'vue'

/** 全局确认弹窗：confirmAction(...) → Promise<boolean>，由 ConfirmDialog.vue 渲染 */
export interface ConfirmOptions {
  title: string
  lines?: string[]        // 说明行（金额、后果）
  warning?: string        // 红字警告
  danger?: boolean        // 确认按钮用警示色
  okText?: string
}

export const confirmState = reactive({
  visible: false,
  opts: { title: '' } as ConfirmOptions,
  resolve: null as ((ok: boolean) => void) | null,
})

export function confirmAction(opts: ConfirmOptions): Promise<boolean> {
  if (confirmState.visible) return Promise.resolve(false)   // 已有弹窗时不叠加
  confirmState.opts = opts
  confirmState.visible = true
  return new Promise(res => { confirmState.resolve = res })
}

export function settleConfirm(ok: boolean) {
  confirmState.visible = false
  confirmState.resolve?.(ok)
  confirmState.resolve = null
}
