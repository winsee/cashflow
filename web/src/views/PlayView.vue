<script setup lang="ts">
import { computed, ref } from 'vue'
import { useGame } from '../store'
import StatementTab from '../components/StatementTab.vue'
import ActionTab from '../components/ActionTab.vue'
import OverviewTab from '../components/OverviewTab.vue'
import LogTab from '../components/LogTab.vue'
import PromptModal from '../components/PromptModal.vue'

const game = useGame()
const tab = ref<'statement' | 'action' | 'overview' | 'log'>('action')
const finished = computed(() => game.state?.status === 'FINISHED')
</script>

<template>
  <div class="page" v-if="game.state">
    <div class="row between" style="margin-bottom:4px">
      <span class="badge">房间 {{ game.state.roomCode }}</span>
      <span class="badge" :style="game.connected ? '' : 'color:var(--red)'">
        {{ game.connected ? '已连接' : '重连中…' }}
      </span>
      <router-link to="/manual" class="badge" style="text-decoration:none">📖 说明书</router-link>
    </div>

    <div v-if="finished" class="card" style="border-color:var(--gold);text-align:center">
      <h1>🏆 {{ game.state.players.find(p => p.id === game.state!.winnerId)?.nickname }} 获胜！</h1>
    </div>

    <StatementTab v-if="tab === 'statement'" />
    <ActionTab v-else-if="tab === 'action'" />
    <OverviewTab v-else-if="tab === 'overview'" />
    <LogTab v-else />

    <PromptModal />

    <nav class="tabbar">
      <button :class="{ active: tab === 'statement' }" @click="tab = 'statement'">📋 我的报表</button>
      <button :class="{ active: tab === 'action' }" @click="tab = 'action'">
        🎲 行动<span v-if="game.isMyTurn" style="color:var(--gold)">●</span>
      </button>
      <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">👥 总览</button>
      <button :class="{ active: tab === 'log' }" @click="tab = 'log'">📜 日志</button>
    </nav>
  </div>
  <div class="page no-tabbar" v-else><p class="muted">连接中…</p></div>
</template>
