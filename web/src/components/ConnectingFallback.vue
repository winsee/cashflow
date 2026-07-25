<script setup lang="ts">
/** 还没拿到房间快照时的占位（/room 与 /play 共用）。
 *
 *  等待若干秒仍拿不到快照，就给一个「返回大厅」出口——否则服务器没起、网络不通时
 *  页面会永久停在「连接中…」而无路可走。这里**不**自动清会话：服务端只是短暂重启时
 *  store 的自动重连会把对局拉回来，误杀身份反而要玩家去「接管座位」找回。
 *  身份被服务端明确拒绝的情形由 store 的 FATAL_CLOSE 分支处理，不走这里。 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGame } from '../store'

const STALL_MS = 8000

const game = useGame()
const router = useRouter()
const stalled = ref(false)
let timer: any = 0

onMounted(() => { timer = setTimeout(() => { stalled.value = true }, STALL_MS) })
onUnmounted(() => clearTimeout(timer))

function backToLobby() {
  game.clearSession()
  router.replace('/')
}
</script>

<template>
  <div class="page no-tabbar">
    <p class="muted" v-if="!stalled">连接中…</p>
    <div class="card" v-else>
      <p style="color:var(--red)">连不上对局，服务器可能已重启或房间已结束。</p>
      <p class="muted">仍在后台重试，恢复后会自动回到对局。</p>
      <button class="block ghost" @click="backToLobby">返回大厅</button>
    </div>
  </div>
</template>
