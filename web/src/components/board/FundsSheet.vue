<script setup lang="ts">
/** 💰 资金弹层（design/09 §2.4）：银行 · 转账 · 破产入口 · 本机显示偏好。
 *
 *  纯线上模式专属的**组合**，所以放 `components/board/` 而不是 `components/tools/`
 *  ——`tools/` 那三块是两模式共用的原子，这一层不该混进只有一种模式看得见的东西。
 *
 *  v0.4 之前它是「账本」的第四页「更多」。试玩反馈「银行埋得太深」：
 *  现金不够几乎总是发生在**抽屉正被卡面占着**的时候，让人先把当前那张卡的上下文
 *  推开、翻三层才能去借钱，是本末倒置。改为棋盘右上角第三枚悬浮钮直开这一层。
 *
 *  它属于「我主动打开的常驻工具」——既不是本回合待办（不进 `.drawer-cta`），
 *  也不是别人的动作波及到我（不由系统弹出）。dismissable，随时可以推开。
 */
import { computed, ref } from 'vue'
import { confirmAction } from '../../confirm'
import { useGame } from '../../store'
import BaseModal from '../base/BaseModal.vue'
import BankPanel from '../tools/BankPanel.vue'
import TransferPanel from '../tools/TransferPanel.vue'

const game = useGame()
const me = computed(() => game.me)
const emit = defineEmits<{ (e: 'close'): void }>()

const bankPanel = ref<InstanceType<typeof BankPanel> | null>(null)

/** 破产入口的判据与线下同一条（月现金流为负且现金加它小于零） */
const bankruptable = computed(() =>
  !!me.value && !me.value.inBankruptcy && me.value.derived.monthlyCashflow < 0
  && me.value.cash + me.value.derived.monthlyCashflow < 0)

async function startBankruptcy() {
  const ok = await confirmAction({
    title: '进入破产流程？',
    lines: ['将按首期付款 50% 向银行变卖资产，直至月现金流转正'],
    danger: true,
  })
  if (ok && await game.act('BANKRUPTCY_START')) emit('close')
}

/** 「去贷款」走这一条：转调 BankPanel 既有的 prefill（千元向上取整 + 滚到自己身上） */
function prefillBank(need: number) {
  bankPanel.value?.prefill(need)
}

defineExpose({ prefillBank })
</script>

<template>
  <BaseModal v-if="me" title="资金" dismissable @close="emit('close')">
    <BankPanel v-if="me.phase === 'RAT_RACE'" ref="bankPanel" />
    <p v-else class="muted">快车道没有银行贷款（说明书第 6 页），记录卡已翻面。</p>
    <TransferPanel />
    <button v-if="bankruptable" class="btn block warn" @click="startBankruptcy">
      🆘 进入破产流程
    </button>
    <!-- 本机的显示偏好：它是这台设备的事，不是账本的一页，所以收在这儿而不是占一格分段 -->
    <div class="card">
      <h3>🎬 显示设置</h3>
      <label class="row between" style="cursor:pointer">
        <span>跳过动画</span>
        <input type="checkbox" :checked="game.skipAnim"
               @change="game.setSkipAnim(!game.skipAnim)" />
      </label>
      <p class="muted" style="margin:6px 0 0">
        只影响这台设备：掷骰、走格、发牌不再播放过场，点数与卡面直接给出结果。
      </p>
    </div>
  </BaseModal>
</template>
