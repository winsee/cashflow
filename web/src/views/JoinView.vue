<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, loadNickname, saveNickname, useGame } from '../store'
import type { RoomSeats } from '../types'
import { confirmAction } from '../confirm'
import SeatPicker from '../components/SeatPicker.vue'

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
/** 手动展开「恢复座位」；对局已开始时强制展开（那时不能加入新玩家） */
const restoring = ref(false)

const started = computed(() =>
  !!seats.value && seats.value.status !== 'LOBBY' && seats.value.status !== 'SETUP')
const pickSeat = computed(() => started.value || restoring.value)

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
    const mine = seats.value?.players.find(p => p.nickname === nickname.value.trim())
    if (e instanceof ApiError && e.code === 'NICKNAME_TAKEN' && mine) {
      // 多半就是本人换了设备/清了缓存：转到恢复座位并预选同名座位
      restoring.value = true
      seatId.value = mine.id
      game.lastError = `「${mine.nickname}」已经在房里了——如果那是你，点「恢复该座位」拿回身份`
    } else {
      game.lastError = e.message
    }
  } finally { busy.value = false }
}

async function takeover() {
  if (!seatId.value) return
  const seat = seats.value?.players.find(p => p.id === seatId.value)
  if (seat?.online) {
    const ok = await confirmAction({
      title: `恢复「${seat.nickname}」的座位`,
      warning: '该座位现在有设备在线，恢复后原设备会立即掉线。确认那是你自己的手机吗？',
      okText: '确认恢复',
    })
    if (!ok) return
  }
  busy.value = true
  try {
    await game.takeover(code, seatId.value, password.value)
    router.replace(started.value ? '/play' : '/room')
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
      <button class="btn block ghost" @click="router.replace('/')">返回大厅</button>
    </div>

    <div class="card" v-else-if="pickSeat">
      <p class="muted" v-if="started">
        对局已开始，新玩家无法加入；换了设备的玩家可选自己的座位恢复身份（原设备将下线）。</p>
      <p class="muted" v-else>选中你自己的座位即可拿回身份（该座位的原设备会立即下线）。</p>
      <SeatPicker :players="seats?.players ?? []" v-model="seatId" />
      <template v-if="seats?.hasPassword">
        <label>房间密码</label>
        <input v-model="password" maxlength="16" placeholder="向房主索取" />
      </template>
      <button class="btn block" :disabled="busy || !seatId || (seats?.hasPassword && !password)"
              @click="takeover">恢复该座位</button>
      <p v-if="!started" class="muted" style="margin-top:12px;text-align:center">
        想以新身份进来？
        <a href="#" @click.prevent="restoring = false" style="color:var(--brand);font-weight:700">
          换个昵称加入</a>
      </p>
    </div>

    <div class="card" v-else>
      <label>你的昵称</label>
      <input v-model="nickname" maxlength="12" placeholder="输入昵称后进入" />
      <template v-if="seats?.hasPassword">
        <label>房间密码</label>
        <input v-model="password" maxlength="16" placeholder="向房主索取" />
      </template>
      <button class="btn block"
              :disabled="busy || !nickname.trim() || (seats?.hasPassword && !password)"
              @click="join">进入房间</button>
      <p v-if="seats?.players.length" class="muted" style="margin-top:12px;text-align:center">
        已经在这个房间里了？（换了手机 / 清了缓存）
        <a href="#" @click.prevent="restoring = true" style="color:var(--brand);font-weight:700">
          恢复我的座位</a>
      </p>
    </div>
  </div>
</template>
