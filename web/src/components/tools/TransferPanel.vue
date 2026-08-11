<script setup lang="ts">
/** 🤝 玩家间转账：发起后待对方确认才扣款。
 *  线下「行动」页与纯线上「资金」弹层共用（见 BankPanel 的同一条理由）。 */
import { computed, ref } from 'vue'
import { useGame } from '../../store'

const game = useGame()
const me = computed(() => game.me)
const transferTo = ref('')
const transferAmount = ref(0)
const transferReason = ref('')

const others = computed(() =>
  (game.state?.players ?? []).filter(p => p.id !== me.value?.id && p.phase !== 'OUT'))

async function submit() {
  const ok = await game.act('TRANSFER_REQUEST', {
    toPlayerId: transferTo.value, amount: transferAmount.value, reason: transferReason.value,
  })
  if (ok) { transferTo.value = ''; transferAmount.value = 0; transferReason.value = '' }
}
</script>

<template>
  <div v-if="me && me.phase !== 'OUT'" class="card">
    <h3>🤝 玩家间转账</h3>
    <label>转给</label>
    <select v-model="transferTo">
      <option value="" disabled>选择玩家</option>
      <option v-for="p in others" :key="p.id" :value="p.id">{{ p.nickname }}</option>
    </select>
    <label>金额</label>
    <input type="number" v-model.number="transferAmount" min="1" />
    <label>备注（如：机会卡转让费）</label>
    <input v-model="transferReason" />
    <button class="btn block" style="margin-top:10px" :disabled="!transferTo || transferAmount <= 0"
            @click="submit">
      发起转账（待对方确认）
    </button>
    <p class="muted">对方确认后才会扣款。</p>
  </div>
</template>
