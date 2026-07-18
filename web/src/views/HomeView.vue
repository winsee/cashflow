<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGame } from '../store'

const game = useGame()
const router = useRouter()
const nickname = ref('')
const code = ref('')
const busy = ref(false)

async function create() {
  if (!nickname.value.trim()) return
  busy.value = true
  try {
    await game.createRoom(nickname.value.trim())
    router.push('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

async function join() {
  if (!nickname.value.trim() || !code.value.trim()) return
  busy.value = true
  try {
    await game.joinRoom(code.value.trim().toUpperCase(), nickname.value.trim())
    router.push('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}
</script>

<template>
  <div class="page no-tabbar">
    <h1 style="margin-top:40px">💸 现金流助手</h1>
    <p class="muted">实体棋盘照常玩，手机自动记账。抛开纸笔，告别算错账。</p>

    <div class="card" v-if="game.session">
      <p>已有对局会话：房间 <b>{{ game.session.roomCode }}</b></p>
      <div class="row">
        <button class="grow" @click="game.connect(); router.push(game.state?.status === 'PLAYING' ? '/play' : '/room')">继续对局</button>
        <button class="ghost" @click="game.clearSession()">退出</button>
      </div>
    </div>

    <div class="card">
      <label>你的昵称</label>
      <input v-model="nickname" maxlength="12" placeholder="例如：老王" />

      <div class="section-title">创建房间（房主）</div>
      <button class="block" :disabled="busy || !nickname.trim()" @click="create">创建房间</button>

      <div class="section-title">加入房间</div>
      <input v-model="code" placeholder="4 位房间码，例如 AB3D"
             style="text-transform:uppercase" maxlength="4" />
      <button class="block ghost" :disabled="busy || !nickname.trim() || code.length < 4" @click="join">加入房间</button>
    </div>

    <p class="muted" style="text-align:center">
      <router-link to="/manual" style="color:var(--muted)">📖 查看游戏说明书</router-link>
      ·
      <router-link to="/entry" style="color:var(--muted)">🗂️ 卡牌录入工具</router-link>
    </p>
  </div>
</template>
