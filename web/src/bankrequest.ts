import { ref } from 'vue'

/** 「去贷款」的转接台（design/09 §2.4）。
 *
 *  纯线上模式里，现金不足的提示长在抽屉深处的组件里（股票交易框、卡面预览、落点面板），
 *  而银行在**另一条路**上（账本 → 更多）。为一次跳转把回调逐层传下去不划算，
 *  和 confirm.ts 同一种做法：一个模块级的信号，由 `OnlineRoomView` 接住。
 *
 *  线下辅助模式不走这里——那边银行就在同一页上，`ActionTab.gotoBank()` 直接展开即可。
 */
export const bankRequest = ref<{ need: number; seq: number } | null>(null)

let seq = 0

/** need = 还差多少现金；向上取整到千元由 `BankPanel.prefill()` 负责。
 *  带 seq 是因为「同一个缺口点第二次」也必须重新触发一次跳转。 */
export function askBankLoan(need: number) {
  bankRequest.value = { need, seq: ++seq }
}
