<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadNickname, saveNickname, useGame } from '../store'
import type { RoomSeats } from '../types'

const route = useRoute()
const router = useRouter()
const game = useGame()
const nickname = ref(loadNickname())
const password = ref('')
const seatId = ref('')
const busy = ref(false)
const code = String(route.params.code || '').toUpperCase()
const seats = ref<RoomSeats | null>(null)
const notFound = ref('')

watch(nickname, n => saveNickname(n.trim()))

onMounted(async () => {
  try { seats.value = await game.fetchSeats(code) }
  catch (e: any) { notFound.value = e.message }
})

async function join() {
  busy.value = true
  try {
    await game.joinRoom(code, nickname.value.trim(), password.value)
    router.replace('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

async function takeover() {
  if (!seatId.value) return
  busy.value = true
  try {
    await game.takeover(code, seatId.value, password.value)
    const status = seats.value?.status
    router.replace(status === 'LOBBY' || status === 'SETUP' ? '/room' : '/play')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}
</script>

<template>
  <div class="page no-tabbar">
    <h1 style="margin-top:40px">加入房间 {{ code }}</h1>

    <div class="card" v-if="notFound">
      <p style="color:var(--red)">{{ notFound }}</p>
      <button class="block ghost" @click="router.replace('/')">返回大厅</button>
    </div>

    <div class="card" v-else-if="seats && seats.status !== 'LOBBY' && seats.status !== 'SETUP'">
      <p class="muted">对局已开始，新玩家无法加入；换了设备的玩家可选自己的座位恢复身份（原设备将下线）。</p>
      <div v-for="p in seats.players" :key="p.id" class="list-item row between"
           :style="seatId === p.id ? 'background:var(--panel2)' : ''"
           @click="seatId = p.id">
        <span>{{ seatId === p.id ? '✅' : '👤' }} {{ p.nickname }}
          <span v-if="p.isHost" class="badge">房主</span></span>
        <span class="muted">{{ p.professionTitle }}</span>
      </div>
      <template v-if="seats.hasPassword">
        <label>房间密码</label>
        <input v-model="password" maxlength="16" placeholder="向房主索取" />
      </template>
      <button class="block" :disabled="busy || !seatId || (seats.hasPassword && !password)"
              @click="takeover">接管该座位</button>
    </div>

    <div class="card" v-else>
      <label>你的昵称</label>
      <input v-model="nickname" maxlength="12" placeholder="输入昵称后进入" />
      <template v-if="seats?.hasPassword">
        <label>房间密码</label>
        <input v-model="password" maxlength="16" placeholder="向房主索取" />
      </template>
      <button class="block"
              :disabled="busy || !nickname.trim() || (seats?.hasPassword && !password)"
              @click="join">进入房间</button>
    </div>
  </div>
</template>
