<script setup lang="ts">
/** 还没拿到房间快照时的占位（/room 与 /play 共用）。
 *
 *  等待若干秒仍拿不到快照，就给一个「先回大厅」出口——否则服务器没起、网络不通时
 *  页面会永久停在「连接中…」而无路可走。这个出口**绝不能清会话**：清掉本机令牌后，
 *  无密码房间的房主既进不去也删不掉自己的房间（只能靠大厅的「恢复座位」找回）。
 *  服务端只是短暂重启时，store 的自动重连本来就能把对局拉回来。
 *  身份被服务端明确拒绝的情形由 store 的 FATAL_CLOSE 分支处理，不走这里。 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const STALL_MS = 5000

const router = useRouter()
const stalled = ref(false)
let timer: any = 0

onMounted(() => { timer = setTimeout(() => { stalled.value = true }, STALL_MS) })
onUnmounted(() => clearTimeout(timer))

function backToLobby() {
  router.replace('/')
}
</script>

<template>
  <div class="page no-tabbar">
    <p class="muted" v-if="!stalled">连接中…</p>
    <div class="card" v-else>
      <p style="color:var(--red)">连不上对局，服务器可能已重启或房间已结束。</p>
      <p class="muted">仍在后台重试，恢复后会自动回到对局。</p>
      <button class="block ghost" @click="backToLobby">先回大厅（对局身份会保留）</button>
    </div>
  </div>
</template>
