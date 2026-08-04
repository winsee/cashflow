<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import StatementTab from '../components/StatementTab.vue'
import ActionTab from '../components/ActionTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import PromptModal from '../components/PromptModal.vue'
import ResultView from '../components/ResultView.vue'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import FasttrackIntro from '../components/FasttrackIntro.vue'
import FasttrackCheer from '../components/FasttrackCheer.vue'

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

// 逃出老鼠赛跑：一局只有一次的转折点，达成条件就直接把全屏换算推到脸上。
// 屏上按钮仍是「进入快车道」/「再想想」—— 看的是预演，点主按钮才真正提交。
const showIntro = ref(false)
const canEscape = computed(() =>
  !!me.value && me.value.phase === 'RAT_RACE' && !me.value.inBankruptcy
  && me.value.derived.canEnterFasttrack)

// 自动弹屏的条件比 canEscape 严：服务端 _d_enter_fasttrack 要求必须是当前玩家，
// 而别人的市场卡完全可能把我的非工资收入顶过线。非我回合就只留 HUD 下的横幅当入口。
const escapeReady = computed(() =>
  canEscape.value && game.isMyTurn
  && !game.myPrompts.length                    // 别盖住待我答复的求购/市场弹层
  && !(game.state?.activeCard && !game.state.activeCard.resolved))

/** 「再想想」记在 sessionStorage：不然刷新一次就把已经推开的过场重新糊到脸上 */
const dismissKey = computed(() =>
  `ftIntro:${game.session?.roomCode ?? ''}:${game.session?.playerId ?? ''}`)
const introDismissed = ref(sessionStorage.getItem(dismissKey.value) === '1')
function dismissIntro() {
  showIntro.value = false
  introDismissed.value = true
  sessionStorage.setItem(dismissKey.value, '1')
}

watch(escapeReady, v => {
  if (v && !introDismissed.value) showIntro.value = true
}, { immediate: true })
// 收入被市场卡打回线下：收起过场并复位，下次再达成还会自动弹
watch(canEscape, v => {
  if (!v) {
    showIntro.value = false
    introDismissed.value = false
    sessionStorage.removeItem(dismissKey.value)
  }
})

async function confirmEnterFasttrack() {
  if (await game.act('ENTER_FASTTRACK')) {
    showIntro.value = false
    sessionStorage.removeItem(dismissKey.value)
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

    <!-- 达成逃出条件但轮不到自己（或刚推开过场）：横幅留在 HUD 正下方当入口 -->
    <button v-if="canEscape && !showIntro" class="hud-banner" @click="showIntro = true">
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
    <FasttrackCheer v-if="game.cheer" :cheer="game.cheer" @close="game.cheer = null" />
    <FasttrackIntro v-if="showIntro" @close="dismissIntro" @confirm="confirmEnterFasttrack" />

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
