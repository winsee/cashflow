<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'
import type { Player } from '../types'
import StatementTab from './StatementTab.vue'
import LogTab from './LogTab.vue'

const game = useGame()
const router = useRouter()
const st = computed(() => game.state!)
const isHost = computed(() => game.me?.isHost ?? false)
const players = computed(() => st.value.players)
const winner = computed(() => players.value.find(p => p.id === st.value.winnerId))

const PHASE_LABEL: Record<string, string> = {
  FAST_TRACK: '已出老鼠圈', RAT_RACE: '老鼠赛跑中', OUT: '已出局',
}

function phaseRank(p: Player): number {
  if (p.id === st.value.winnerId) return 4
  if (p.phase === 'FAST_TRACK') return 3
  if (p.phase === 'RAT_RACE') return 2
  return 1                                   // OUT
}
function passiveOf(p: Player): number {
  return p.phase === 'FAST_TRACK' ? p.fasttrack.current_income : p.derived.passiveIncome
}
const ranked = computed(() => [...players.value].sort((a, b) =>
  (phaseRank(b) - phaseRank(a)) || (passiveOf(b) - passiveOf(a))))

const MEDALS = ['🥇', '🥈', '🥉']
function isMe(p: Player) { return p.id === game.session?.playerId }

const detail = ref<null | 'statement' | 'log'>(null)

async function rematch() {
  const ok = await confirmAction({
    title: '再来一局？',
    lines: ['同一房间重新开始，所有人自动回到准备页重选职业', '当前战绩与账目将清空'],
  })
  if (ok) await game.rematch()     // 成功后 App.vue 侦测到 LOBBY，全员自动回 /room
}

async function dissolve() {
  const ok = await confirmAction({
    title: '解散房间？',
    lines: ['所有玩家将返回大厅', '账目日志随房间一并清除，需要请先导出'],
    warning: '此操作不可撤销',
    danger: true, okText: '解散',
  })
  if (ok) await game.endGame()
}

function backToLobby() {
  game.clearSession()
  router.replace('/')
}

function exportLog() {
  if (game.session) window.open(`/api/rooms/${game.session.roomCode}/export`, '_blank')
}
</script>

<template>
  <div class="page no-tabbar">
    <div class="result-hero">
      <div class="crown">🏆</div>
      <h1>{{ winner?.nickname ?? '——' }} 获胜！</h1>
      <div class="sub">用时 {{ st.turnCount }} 回合 · {{ players.length }} 人对局</div>
    </div>

    <div class="card">
      <div class="section-title">最终排名</div>
      <div v-for="(p, i) in ranked" :key="p.id" class="rank-row" :class="{ me: isMe(p) }">
        <div class="rank-medal">{{ MEDALS[i] ?? (i + 1) }}</div>
        <div class="grow">
          <div class="rank-name">
            {{ p.nickname }}
            <span v-if="isMe(p)" class="badge turn" style="margin-left:4px">你</span>
            <span v-if="p.isHost" class="badge" style="margin-left:4px">房主</span>
          </div>
          <div class="rank-meta">{{ PHASE_LABEL[p.phase] }} · 被动收入 {{ fmt(passiveOf(p)) }}</div>
        </div>
        <div class="money" :class="p.cash >= 0 ? '' : 'neg'">{{ fmt(p.cash) }}</div>
      </div>
    </div>

    <div class="row">
      <button class="ghost grow" @click="detail = 'statement'">📋 我的报表</button>
      <button class="ghost grow" @click="detail = 'log'">📜 全程日志</button>
    </div>

    <template v-if="isHost">
      <button class="block gold" style="margin-top:14px" @click="rematch">🔁 再来一局</button>
      <div class="row">
        <button class="ghost grow" @click="exportLog">⬇ 导出账目</button>
        <button class="warn grow" @click="dissolve">🛑 解散房间</button>
      </div>
    </template>
    <template v-else>
      <button class="block ghost" style="margin-top:14px" @click="backToLobby">↩ 返回大厅</button>
      <p class="muted" style="text-align:center">⏳ 等待房主决定是否再来一局…</p>
    </template>

    <!-- 报表 / 日志详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="row between" style="margin-bottom:8px;align-items:center">
          <h2 style="margin:0">{{ detail === 'statement' ? '我的记录卡' : '全程账目日志' }}</h2>
          <button class="small ghost" @click="detail = null">关闭</button>
        </div>
        <StatementTab v-if="detail === 'statement'" />
        <LogTab v-else />
      </div>
    </div>
  </div>
</template>
