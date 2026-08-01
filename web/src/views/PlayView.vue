<script setup lang="ts">
import { computed, ref } from 'vue'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import StatementTab from '../components/StatementTab.vue'
import ActionTab from '../components/ActionTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import PromptModal from '../components/PromptModal.vue'
import ResultView from '../components/ResultView.vue'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import FasttrackIntro from '../components/FasttrackIntro.vue'

const game = useGame()
const tab = ref<'statement' | 'action' | 'overview' | 'log'>('action')
const finished = computed(() => game.state?.status === 'FINISHED')
const me = computed(() => game.me)
const ft = computed(() => me.value?.phase === 'FAST_TRACK')

// HUD 进度：老鼠赛跑=非工资/总支出；快车道=距 +$50,000 的收入增量
const progress = computed(() => {
  const m = me.value
  if (!m) return 0
  if (m.phase === 'FAST_TRACK') return ftWinProgress(m.fasttrack)
  const d = m.derived
  return d.totalExpenses ? Math.min(100, d.passiveIncome / d.totalExpenses * 100) : 100
})
// 快车道距胜利还差多少（另一条路是买下自己的梦想）
const toWin = computed(() => {
  const f = me.value?.fasttrack
  if (!f) return 0
  return Math.max(0, f.initial_income + FT_WIN_INCREMENT - f.current_income)
})

// 待办角标：我的回合有未结算强制卡，有待我确认的推送，有对我开放的股票交易窗口，或有未读回执
const actionAlert = computed(() =>
  game.myPrompts.length > 0 || game.stockWindowOpen || game.receipts.length > 0 ||
  (game.isMyTurn && !!game.state?.activeCard && !game.state.activeCard.resolved
    && game.state.activeCard.drawer_id === game.session?.playerId))

// 逃出老鼠赛跑：达成条件的横幅提到 HUD 正下方，点开才是全屏换算预演。
// 「看看能换到多少」而不是「进入快车道」—— 点主按钮才真正提交。
const showIntro = ref(false)
const canEscape = computed(() =>
  !!me.value && me.value.phase === 'RAT_RACE' && !me.value.inBankruptcy
  && me.value.derived.canEnterFasttrack)

async function confirmEnterFasttrack() {
  if (await game.act('ENTER_FASTTRACK')) {
    showIntro.value = false
    game.flash('🏁 你进入快车道了，启动资金已到账', 'gold')
  }
}
</script>

<template>
  <ResultView v-if="finished" />

  <div class="page" v-else-if="game.state && me">
    <!-- 常驻状态条 -->
    <div class="hud" :class="{ 'offline-dim': !game.connected }">
      <div>
        <div class="lab">银行储蓄</div>
        <div class="cash money">{{ fmt(me.cash) }}</div>
      </div>
      <div class="hud-side">
        <template v-if="ft">
          <div class="lab">现金流量日收入</div>
          <div class="flow money" style="color:var(--gold-deep)">{{ fmt(me.fasttrack.current_income) }}</div>
        </template>
        <template v-else>
          <div class="lab">月现金流</div>
          <div class="flow money" :class="me.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">
            {{ me.derived.monthlyCashflow >= 0 ? '+' : '' }}{{ fmt(me.derived.monthlyCashflow) }}
          </div>
        </template>
      </div>
      <div class="hud-turn">
        <template v-if="game.isMyTurn"><span class="live-dot"></span> <b>轮到你了</b></template>
        <template v-else>等待 {{ game.currentPlayer?.nickname ?? '—' }} 行动</template>
        · 第 {{ game.state.turnCount }} 轮
        <span v-if="!game.connected" style="color:var(--red)">· 重连中…</span>
        <span class="grow"></span>
        <router-link to="/manual" style="color:var(--muted);text-decoration:none">📖 说明书</router-link>
      </div>
      <!-- 这条进度是这个阶段唯一的目标，得写出它是什么，不然就是一条没来由的色带 -->
      <template v-if="me.phase !== 'OUT'">
        <div class="hud-goal">
          <span v-if="ft">距胜利还差 {{ fmt(toWin) }}</span>
          <span v-else>离快车道 · 非工资收入 {{ fmt(me.derived.passiveIncome) }} /
            总支出 {{ fmt(me.derived.totalExpenses) }}</span>
          <span class="grow"></span>
          <span>{{ Math.round(progress) }}%</span>
        </div>
        <div class="progress" :class="{ gold: ft }">
          <div :style="{ width: progress + '%' }" />
        </div>
      </template>
    </div>

    <!-- 达成逃出条件：横幅就在 HUD 正下方，不埋进分诊卡底部 -->
    <button v-if="canEscape" class="hud-banner" @click="showIntro = true">
      <span class="ic">🏁</span>
      <span class="grow">
        <span class="t">你赢下老鼠赛跑了</span>
        <span class="s">非工资收入 {{ fmt(me.derived.passiveIncome) }} 已超过总支出 {{ fmt(me.derived.totalExpenses) }}</span>
      </span>
      <span class="btn gold small">看看能换到多少</span>
    </button>

    <div :class="{ 'offline-dim': !game.connected }">
      <!-- 断线：界面保留但明说失效，别让人对着一个看起来正常的界面点了没反应 -->
      <div v-if="!game.connected" class="card quiet" style="padding:14px;text-align:center">
        <span class="muted">重新连上之前，操作暂不可用</span>
      </div>
      <StatementTab v-if="tab === 'statement'" />
      <ActionTab v-else-if="tab === 'action'" />
      <OverviewTab v-else-if="tab === 'overview'" />
      <LogTab v-else />
    </div>

    <PromptModal />
    <FasttrackIntro v-if="showIntro" @close="showIntro = false" @confirm="confirmEnterFasttrack" />

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
