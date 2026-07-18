<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useGame } from '../store'
import type { CardDto } from '../types'

const game = useGame()
const professions = ref<CardDto[]>([])
const dreams = ref<{ id: string; name: string; price: number }[]>([])
const order = ref<string[]>([])

onMounted(async () => {
  professions.value = await game.fetchCards('PROFESSION')
  const board = await game.fetchFasttrackBoard()
  dreams.value = board.dreams
})

const joinUrl = computed(() =>
  `${location.origin}/#/join/${game.session?.roomCode ?? ''}`)

const players = computed(() => game.state?.players ?? [])
const isHost = computed(() => game.me?.isHost ?? false)

function syncOrder() {
  if (!order.value.length) order.value = players.value.map(p => p.id)
  // 补充新加入的玩家
  for (const p of players.value) if (!order.value.includes(p.id)) order.value.push(p.id)
  order.value = order.value.filter(id => players.value.some(p => p.id === id))
}

function move(idx: number, dir: number) {
  syncOrder()
  const j = idx + dir
  if (j < 0 || j >= order.value.length) return
  ;[order.value[idx], order.value[j]] = [order.value[j], order.value[idx]]
}

const orderedPlayers = computed(() => {
  syncOrder()
  return order.value.map(id => players.value.find(p => p.id === id)!).filter(Boolean)
})

async function saveOrder() {
  syncOrder()
  await game.act('SET_TURN_ORDER', { order: order.value })
}

async function start() {
  await saveOrder()
  await game.act('START_GAME')
}

function nickOf(id: string | null): string {
  return players.value.find(p => p.id === id)?.nickname ?? '—'
}

async function copyUrl() {
  try { await navigator.clipboard.writeText(joinUrl.value) } catch {}
}
</script>

<template>
  <div class="page no-tabbar" v-if="game.state">
    <div class="row between">
      <h1>房间 {{ game.state.roomCode }}</h1>
      <span class="badge">{{ players.length }}/{{ game.state.settings.max_players }} 人</span>
    </div>

    <div class="card">
      <div class="muted">邀请：让朋友访问下方地址，或输入房间码 <b>{{ game.state.roomCode }}</b></div>
      <div class="row" style="margin-top:6px">
        <input readonly :value="joinUrl" style="font-size:12px" />
        <button class="small ghost" @click="copyUrl">复制</button>
      </div>
    </div>

    <div class="card">
      <h2>我的开局设置</h2>
      <label>职业（抽实体职业卡后在此选择）</label>
      <select :value="game.me?.professionId ?? ''"
              @change="game.act('SELECT_PROFESSION', { professionId: ($event.target as HTMLSelectElement).value })">
        <option value="" disabled>请选择职业</option>
        <option v-for="p in professions" :key="p.id" :value="p.id">
          {{ p.title }}（工资 ${{ p.data.salary.toLocaleString() }}）
        </option>
      </select>

      <label>梦想（快车道粉格，开局必选）</label>
      <select :value="game.me?.dreamId ?? ''"
              @change="game.act('SELECT_DREAM', { dreamId: ($event.target as HTMLSelectElement).value })">
        <option value="" disabled>请选择梦想</option>
        <option v-for="d in dreams" :key="d.id" :value="d.id">
          {{ d.name }}（${{ d.price.toLocaleString() }}）
        </option>
      </select>
    </div>

    <div class="card">
      <h2>玩家 <span class="muted" v-if="isHost">（线下掷骰后由房主排先后）</span></h2>
      <div v-for="(p, i) in orderedPlayers" :key="p.id" class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div>
          <b>{{ i + 1 }}. {{ p.nickname }}</b>
          <span v-if="p.isHost" class="badge" style="margin-left:6px">房主</span>
          <div class="muted">
            {{ p.professionTitle || '未选职业' }} ·
            {{ p.dreamId ? '已选梦想' : '未选梦想' }}
          </div>
        </div>
        <div class="row" v-if="isHost">
          <button class="small ghost" @click="move(i, -1)">↑</button>
          <button class="small ghost" @click="move(i, 1)">↓</button>
        </div>
      </div>
    </div>

    <button v-if="isHost" class="block" :disabled="players.length < 2" @click="start">
      开始对局（自动发钱）
    </button>
    <p v-else class="muted" style="text-align:center">等待房主开始对局…</p>
  </div>
  <div class="page no-tabbar" v-else>
    <p class="muted">连接中…</p>
  </div>
</template>
