<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGame } from './store'

const game = useGame()
const router = useRouter()
const route = useRoute()

// 恢复会话自动连接；按房间状态落到正确页面
if (game.session) game.connect()

watch(() => game.state?.status, (status) => {
  if (!status) return
  const p = route.path
  if (p.startsWith('/join') || p === '/' ) {
    if (status === 'LOBBY' || status === 'SETUP') router.replace('/room')
    else router.replace('/play')
  } else if (p === '/room' && (status === 'PLAYING' || status === 'FINISHED')) {
    router.replace('/play')
  }
})
</script>

<template>
  <div v-if="game.lastError" class="toast" @click="game.lastError = ''">{{ game.lastError }}</div>
  <router-view />
</template>
