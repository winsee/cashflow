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

// 阶段换肤：整屏从墨绿转金箔。挂在 <body> 上，覆盖的是一层颜色变量，
// 纸底、卡面、主按钮、待办色条、标签栏全部自动跟着走（见 style.css 的 .skin-ft）。
//
// 条件是两半：**在快车道** 且 **人在牌桌上**。金箔是对局中的阶段特效，不是跟着人走的
// 身份标签——`inFasttrack` 只看我的赛道，会话活着它就一直为真，留着会话回大厅
// （浏览器返回 / 直接开 `/#/` / 从大厅点进说明书，大厅那张「继续对局」卡就是为这种状态准备的）
// 时它照样是真，于是大厅、说明书、录入页全跟着变金。路由这一半就是用来兜住这条路的。
const SKIN_ROUTE = '/play'    // 对局页：线下 PlayView 与纯线上 OnlineRoomView 都挂在这儿
watch([() => game.inFasttrack, () => route.path], ([ft, path]) => {
  document.body.classList.toggle('skin-ft', ft && path === SKIN_ROUTE)
}, { immediate: true })

watch(() => game.state?.status, (status) => {
  if (!status) return
  if (status === 'CLOSED') {
    // 房主结束对局：全员清会话回大厅
    game.clearSession()
    game.flash('房主已结束对局，对局已解散')
    router.replace('/')
    return
  }
  const p = route.path
  if (p.startsWith('/join')) {
    router.replace(status === 'LOBBY' || status === 'SETUP' ? '/room' : '/play')
  } else if (p === '/room' && (status === 'PLAYING' || status === 'FINISHED')) {
    router.replace('/play')
  } else if (p === '/play' && (status === 'LOBBY' || status === 'SETUP')) {
    // 房主发起「再来一局」：房间就地重置为准备阶段，全员自动回准备页重选职业
    router.replace('/room')
  }
})

// 服务端明确拒绝了本机身份（房间已删除/已归档/令牌失效）：回大厅。
// 这条不依赖 game.state——上面两个 watch 都要求快照非空，而这种场景快照永远拿不到。
watch(() => game.sessionLost, (lost) => {
  if (!lost) return
  game.sessionLost = false
  if (route.path !== '/') router.replace('/')
})

// 被房主移出 / 出局后未带入下一局：快照里已无我，清会话回大厅（CLOSED 另行处理）
watch(() => !!(game.state && game.session && !game.me),
  (dropped) => {
    if (dropped && game.state?.status !== 'CLOSED') {
      game.clearSession()
      game.flash('你已不在该房间')
      router.replace('/')
    }
  })
</script>

<template>
  <!-- 断线：常驻红条，连上即撤。不进 notices 队列——它不是「一句提示」，
       而是一个持续状态，3 秒后自己消失反而会骗人（design 稿 §12） -->
  <div v-if="game.session && game.state && !game.connected" class="toast err">连接断开，正在重连…</div>
  <div v-else-if="game.lastError" class="toast" @click="game.lastError = ''">{{ game.lastError }}</div>
  <!-- 队列：一次只显示一条，还有几条写在下面，绝不叠 toast -->
  <div v-else-if="game.notice" class="toast" :class="game.notice.variant"
       @click="game.dismissNotice()">
    {{ game.notice.msg }}
    <span v-if="game.notices.length > 1" class="toast-more">还有 {{ game.notices.length - 1 }} 条</span>
  </div>
  <ConfirmDialog />
  <router-view />
</template>
