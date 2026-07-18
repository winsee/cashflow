<script setup lang="ts">
import { computed } from 'vue'
import { fmt, useGame } from '../store'

const game = useGame()
const prompt = computed(() => game.myPrompts[0] ?? null)

function nickOf(id: string): string {
  return game.state?.players.find(p => p.id === id)?.nickname ?? '玩家'
}
</script>

<template>
  <div v-if="prompt" class="modal-mask">
    <div class="modal">
      <template v-if="prompt.kind === 'MARKET_SELL'">
        <h2>📢 市场求购</h2>
        <p>有人求购 <b>{{ prompt.payload.asset_name }}</b>：
          卖价 {{ fmt(prompt.payload.price) }}，抵押 {{ fmt(prompt.payload.mortgage) }}，
          到手 <b class="num" :class="prompt.payload.price - prompt.payload.mortgage >= 0 ? 'pos' : 'neg'">
            {{ fmt(prompt.payload.price - prompt.payload.mortgage) }}</b></p>
        <div class="row">
          <button class="grow" @click="game.act('MARKET_SELL', { promptId: prompt.id, accept: true })">按价出售</button>
          <button class="grow ghost" @click="game.act('MARKET_SELL', { promptId: prompt.id, accept: false })">不卖</button>
        </div>
      </template>

      <template v-else-if="prompt.kind === 'TRANSFER_CONFIRM'">
        <h2>🤝 转账确认</h2>
        <p><b>{{ nickOf(prompt.payload.from_player_id) }}</b> 要转给你 {{ fmt(prompt.payload.amount) }}
          <span class="muted" v-if="prompt.payload.reason">（{{ prompt.payload.reason }}）</span></p>
        <div class="row">
          <button class="grow" @click="game.act('TRANSFER_CONFIRM', { promptId: prompt.id, accept: true })">确认收款</button>
          <button class="grow ghost" @click="game.act('TRANSFER_CONFIRM', { promptId: prompt.id, accept: false })">拒绝</button>
        </div>
      </template>

      <template v-else-if="prompt.kind === 'RESELL_CONFIRM'">
        <h2>🃏 机会卡转卖</h2>
        <p><b>{{ nickOf(prompt.payload.from_player_id) }}</b> 把机会卡
          「{{ prompt.payload.title }}」转卖给你：
          转让费 {{ fmt(prompt.payload.fee) }}，并须立即按卡面首付 {{ fmt(prompt.payload.down_payment) }} 购入该资产。</p>
        <div class="row">
          <button class="grow" @click="game.act('RESELL_CONFIRM', { promptId: prompt.id, accept: true })">确认购买</button>
          <button class="grow ghost" @click="game.act('RESELL_CONFIRM', { promptId: prompt.id, accept: false })">拒绝</button>
        </div>
      </template>
    </div>
  </div>
</template>
