<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGame } from '../store'

const route = useRoute()
const router = useRouter()
const game = useGame()
const nickname = ref('')
const busy = ref(false)
const code = String(route.params.code || '').toUpperCase()

async function join() {
  busy.value = true
  try {
    await game.joinRoom(code, nickname.value.trim())
    router.replace('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}
</script>

<template>
  <div class="page no-tabbar">
    <h1 style="margin-top:40px">加入房间 {{ code }}</h1>
    <div class="card">
      <label>你的昵称</label>
      <input v-model="nickname" maxlength="12" placeholder="输入昵称后进入" />
      <button class="block" :disabled="busy || !nickname.trim()" @click="join">进入房间</button>
    </div>
  </div>
</template>
