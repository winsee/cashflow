<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import type { Player } from '../types'
import StatementTab from './StatementTab.vue'
import BaseModal from './base/BaseModal.vue'

const game = useGame()
const router = useRouter()
const st = computed(() => game.state!)
const isHost = computed(() => game.me?.isHost ?? false)

const detailPlayer = ref<Player | null>(null)

async function removePlayer(p: Player) {
  const ok = await confirmAction({
    title: `移除玩家「${p.nickname}」？`,
    lines: ['用于玩家中途退出：轮转将永久跳过 TA', '误点可由房主在「日志」中撤销'],
    danger: true,
    okText: '移除',
  })
  if (ok && await game.act('HOST_REMOVE_PLAYER', { playerId: p.id })) {
    game.flash(`已移除 ${p.nickname}`)
  }
}

async function endGame() {
  const ok = await confirmAction({
    title: '结束对局？',
    lines: ['所有玩家将退出房间返回首页', '账目日志保留在服务器，可在结束前导出'],
    warning: '此操作不可撤销',
    danger: true,
    okText: '结束对局',
  })
  if (ok) await game.act('END_GAME')
}

async function leaveGame() {
  const ok = await confirmAction({
    title: '退出对局？',
    lines: ['你的回合将被永久跳过，不能自行恢复该座位。', '如误退出，需由房主在日志中撤销退出记录。'],
    warning: '此操作会清除本机对局身份。',
    danger: true,
    okText: '退出对局',
  })
  if (ok && await game.leaveGame()) router.replace('/')
}
</script>

<template>
  <div v-if="st">
    <!-- 出局的人降透明度但不隐藏 —— 他还在桌上 -->
    <div v-for="p in st.players" :key="p.id" class="card"
         :class="{ current: p.id === st.currentPlayerId }"
         :style="{ cursor: 'pointer', opacity: p.phase === 'OUT' ? .55 : 1 }"
         @click="detailPlayer = p">
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
        <!-- 两个阶段用各自的进度语言，但卡片结构一致，便于横向比较 -->
        <div class="row between muted" style="margin-top:6px">
          <span>现金流量日收入 {{ fmt(p.fasttrack.current_income) }}</span>
          <span>距胜利还差 {{ fmt(Math.max(0, p.fasttrack.initial_income + FT_WIN_INCREMENT - p.fasttrack.current_income)) }}</span>
        </div>
        <div class="progress gold" style="margin-top:4px">
          <div :style="{ width: ftWinProgress(p.fasttrack) + '%' }" />
        </div>
      </template>

      <div class="muted" style="margin-top:6px" v-if="p.realEstates.length || p.businesses.length || p.stocks.length">
        资产：
        <span v-for="r in p.realEstates" :key="r.id">🏠{{ r.asset_type }} </span>
        <span v-for="b in p.businesses" :key="b.id">🏢{{ b.name }} </span>
        <span v-for="s in p.stocks" :key="s.symbol + s.cost_per_share">📈{{ s.symbol }}×{{ s.shares }} </span>
      </div>

      <div class="row between" style="margin-top:6px;align-items:center">
        <span class="muted" style="font-size:12px">📋 查看记录卡 ›</span>
        <button v-if="isHost && p.id !== game.me?.id && p.phase !== 'OUT' && st.status === 'PLAYING'"
                class="btn small ghost warn" @click.stop="removePlayer(p)">移除玩家</button>
      </div>
    </div>

    <div v-if="!isHost" class="card" style="border-color:var(--red)">
      <h2>退出对局</h2>
      <p class="muted">退出后不能自行接管该座位；误退出请联系房主在日志中撤销。</p>
      <button class="btn block warn" @click="leaveGame">退出对局</button>
    </div>

    <div v-if="isHost" class="card" style="border-color:var(--red)">
      <h2>房主操作</h2>
      <p class="muted">结束对局后所有玩家自动返回首页；重开一局请重新创建房间。</p>
      <button class="btn block warn" @click="endGame">🛑 结束对局</button>
    </div>

    <BaseModal v-if="detailPlayer" :title="`${detailPlayer.nickname} 的记录卡`"
               :source="detailPlayer.professionTitle || '—'" dismissable
               @close="detailPlayer = null">
      <StatementTab :player="detailPlayer" />
      <template #actions>
        <button class="btn ghost grow" @click="detailPlayer = null">关闭</button>
      </template>
    </BaseModal>
  </div>
</template>
