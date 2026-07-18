<script setup lang="ts">
import { computed } from 'vue'
import { fmt, useGame } from '../store'

const game = useGame()
const st = computed(() => game.state!)
</script>

<template>
  <div v-if="st">
    <div v-for="p in st.players" :key="p.id" class="card"
         :style="p.id === st.currentPlayerId ? 'border-color:var(--brand)' : ''">
      <div class="row between">
        <div>
          <b>{{ p.nickname }}</b>
          <span class="muted">· {{ p.professionTitle || '—' }}</span>
          <span v-if="p.id === st.currentPlayerId" class="badge turn" style="margin-left:6px">行动中</span>
          <span v-if="p.phase === 'FAST_TRACK'" class="badge ft" style="margin-left:6px">快车道</span>
          <span v-if="p.phase === 'OUT'" class="badge out" style="margin-left:6px">出局</span>
          <span v-if="p.skipTurns" class="badge" style="margin-left:6px">停赛 {{ p.skipTurns }}</span>
          <span v-if="p.inBankruptcy" class="badge out" style="margin-left:6px">破产清算中</span>
        </div>
        <div class="num big">{{ fmt(p.cash) }}</div>
      </div>

      <template v-if="p.phase === 'RAT_RACE'">
        <div class="row between muted" style="margin-top:6px">
          <span>月现金流 <b :class="p.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">{{ fmt(p.derived.monthlyCashflow) }}</b></span>
          <span>非工资 {{ fmt(p.derived.passiveIncome) }} / 支出 {{ fmt(p.derived.totalExpenses) }}</span>
        </div>
        <div class="progress" style="margin-top:4px">
          <div :style="{ width: Math.min(100, p.derived.totalExpenses ? p.derived.passiveIncome / p.derived.totalExpenses * 100 : 0) + '%' }" />
        </div>
      </template>
      <template v-else-if="p.phase === 'FAST_TRACK'">
        <div class="muted" style="margin-top:6px">
          现金流量日收入 {{ fmt(p.fasttrack.current_income) }}
          （胜利进度 +{{ fmt(p.fasttrack.current_income - p.fasttrack.initial_income) }} / $50,000）
        </div>
      </template>

      <div class="muted" style="margin-top:6px" v-if="p.realEstates.length || p.businesses.length || p.stocks.length">
        资产：
        <span v-for="r in p.realEstates" :key="r.id">🏠{{ r.asset_type }} </span>
        <span v-for="b in p.businesses" :key="b.id">🏢{{ b.name }} </span>
        <span v-for="s in p.stocks" :key="s.symbol + s.cost_per_share">📈{{ s.symbol }}×{{ s.shares }} </span>
      </div>
    </div>

    <div v-if="st.winnerId" class="card" style="border-color:var(--gold);text-align:center">
      <h1>🏆 {{ st.players.find(p => p.id === st.winnerId)?.nickname }} 获胜！</h1>
      <p class="muted">对局结束，可在「日志」中回顾全程账目</p>
    </div>
  </div>
</template>
