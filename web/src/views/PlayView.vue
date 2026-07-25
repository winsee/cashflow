<script setup lang="ts">
import { computed, ref } from 'vue'
import { fmt, useGame } from '../store'
import StatementTab from '../components/StatementTab.vue'
import ActionTab from '../components/ActionTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import PromptModal from '../components/PromptModal.vue'
import ResultView from '../components/ResultView.vue'
import ConnectingFallback from '../components/ConnectingFallback.vue'

const game = useGame()
const tab = ref<'statement' | 'action' | 'overview' | 'log'>('action')
const finished = computed(() => game.state?.status === 'FINISHED')
const me = computed(() => game.me)

// HUD 进度：老鼠赛跑=非工资/总支出；快车道=距 +$50,000 的收入增量
const progress = computed(() => {
  const m = me.value
  if (!m) return 0
  if (m.phase === 'FAST_TRACK')
    return Math.min(100, (m.fasttrack.current_income - m.fasttrack.initial_income) / 500)
  const d = m.derived
  return d.totalExpenses ? Math.min(100, d.passiveIncome / d.totalExpenses * 100) : 100
})
// 待办角标：我的回合有未结算强制卡，或有待我确认的推送
const actionAlert = computed(() =>
  game.myPrompts.length > 0 ||
  (game.isMyTurn && !!game.state?.activeCard && !game.state.activeCard.resolved
    && game.state.activeCard.drawer_id === game.session?.playerId))
</script>

<template>
  <ResultView v-if="finished" />

  <div class="page" v-else-if="game.state && me">
    <!-- 常驻状态条 -->
    <div class="hud">
      <div>
        <div class="lab">银行储蓄</div>
        <div class="cash money">{{ fmt(me.cash) }}</div>
      </div>
      <div class="hud-side">
        <div class="lab">月现金流</div>
        <div class="flow money" :class="me.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">
          {{ me.derived.monthlyCashflow >= 0 ? '+' : '' }}{{ fmt(me.derived.monthlyCashflow) }}
        </div>
      </div>
      <div class="hud-turn">
        <template v-if="game.isMyTurn"><span class="live-dot"></span> <b>轮到你了</b></template>
        <template v-else>等待 {{ game.currentPlayer?.nickname ?? '—' }} 行动</template>
        · 第 {{ game.state.turnCount }} 轮
        <span v-if="!game.connected" style="color:var(--red)">· 重连中…</span>
        <span class="grow"></span>
        <router-link to="/manual" style="color:var(--muted);text-decoration:none">📖 说明书</router-link>
      </div>
      <div class="progress" style="grid-column:1/-1;margin-top:8px" v-if="me.phase !== 'OUT'">
        <div :style="{ width: progress + '%' }" />
      </div>
    </div>

    <StatementTab v-if="tab === 'statement'" />
    <ActionTab v-else-if="tab === 'action'" />
    <OverviewTab v-else-if="tab === 'overview'" />
    <LogTab v-else />

    <PromptModal />

    <nav class="tabbar">
      <button :class="{ active: tab === 'statement' }" @click="tab = 'statement'">📋 报表</button>
      <button :class="{ active: tab === 'action' }" @click="tab = 'action'">
        🎲 行动<span v-if="actionAlert" class="live-dot" style="position:absolute;top:8px;margin-left:1px"></span>
      </button>
      <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">👥 总览</button>
      <button :class="{ active: tab === 'log' }" @click="tab = 'log'">📜 日志</button>
    </nav>
  </div>

  <ConnectingFallback v-else />
</template>
