<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGame } from './store'
import ConfirmDialog from './components/ConfirmDialog.vue'

const game = useGame()
const router = useRouter()
const route = useRoute()

// 恢复会话自动连接；按房间状态落到正确页面
if (game.session) game.connect()

watch(() => game.state?.status, (status) => {
  if (!status) return
  if (status === 'CLOSED') {
    // 房主结束对局：全员清会话回首页，重开只需再创建/加入新房间
    game.clearSession()
    game.flash('房主已结束对局')
    router.replace('/')
    return
  }
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
  <div v-else-if="game.notice" class="toast ok" @click="game.notice = ''">{{ game.notice }}</div>
  <ConfirmDialog />
  <router-view />
</template>
