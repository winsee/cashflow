<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { loadNickname, saveNickname, useGame } from '../store'
import type { RoomListItem, RoomSeats } from '../types'
import { confirmAction } from '../confirm'

const game = useGame()
const router = useRouter()
const nickname = ref(loadNickname())
const busy = ref(false)
const rooms = ref<RoomListItem[]>([])
const loading = ref(false)
let pollTimer = 0 as any

watch(nickname, n => saveNickname(n.trim()))

// ---------- 大厅列表 ----------

async function refresh() {
  loading.value = true
  try { rooms.value = await game.fetchRooms() }
  catch { /* 服务器未就绪时静默，下轮轮询再试 */ }
  finally { loading.value = false }
}

onMounted(() => {
  refresh()
  pollTimer = setInterval(refresh, 5000)
})
onUnmounted(() => clearInterval(pollTimer))

const STATUS_LABEL: Record<string, string> = {
  LOBBY: '等待中', SETUP: '准备中', PLAYING: '进行中', FINISHED: '已结束', CLOSED: '已解散',
}

// ---------- 创建房间 ----------

const roomName = ref('现金流对局')
const roomPassword = ref('')
const maxPlayers = ref(6)

async function create() {
  if (!roomName.value.trim() || !nickname.value.trim()) return
  busy.value = true
  try {
    await game.createRoom(nickname.value.trim(), roomName.value.trim() || '现金流对局',
                          roomPassword.value.trim(), maxPlayers.value)
    router.push('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

// ---------- 加入 / 接管 ----------

const dialog = ref<null | {
  mode: 'join' | 'takeover' | 'delete'
  room: RoomListItem
  seats?: RoomSeats
  seatId?: string
}>(null)
const password = ref('')

async function tapRoom(room: RoomListItem) {
  game.lastError = ''
  // 本机会话就在这个房间：直接回去
  if (game.session?.roomCode === room.code) {
    game.connect()
    router.push(room.status === 'LOBBY' || room.status === 'SETUP' ? '/room' : '/play')
    return
  }
  if (room.status === 'LOBBY' || room.status === 'SETUP') {
    password.value = ''
    dialog.value = { mode: 'join', room }
  } else {
    // 对局已开始/结束：只能接管已有座位（换设备恢复身份）
    try {
      const seats = await game.fetchSeats(room.code)
      password.value = ''
      dialog.value = { mode: 'takeover', room, seats, seatId: '' }
    } catch (e: any) { game.lastError = e.message }
  }
}

async function doJoin(room: RoomListItem, pw: string) {
  busy.value = true
  try {
    await game.joinRoom(room.code, nickname.value.trim(), pw)
    dialog.value = null
    router.push('/room')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

async function doTakeover() {
  const d = dialog.value
  if (!d?.seatId) return
  busy.value = true
  try {
    await game.takeover(d.room.code, d.seatId, password.value)
    const status = d.room.status
    dialog.value = null
    router.push(status === 'LOBBY' || status === 'SETUP' ? '/room' : '/play')
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

// ---------- 删除房间 ----------

async function tapDelete(room: RoomListItem) {
  game.lastError = ''
  const isMyHostRoom = game.session?.roomCode === room.code && !!game.state?.players
    .find(p => p.id === game.session!.playerId && p.isHost)
  if (room.status === 'FINISHED' || room.status === 'CLOSED') {
    const ok = await confirmAction({
      title: `删除房间 ${room.name}`,
      lines: ['对局已结束，删除后战绩与账目记录将一并清除。'],
      danger: true, okText: '删除',
    })
    if (ok) await doDelete(room, {})
  } else if (isMyHostRoom) {
    const ok = await confirmAction({
      title: `删除房间 ${room.name}`,
      warning: '对局尚未结束，删除后所有玩家将被踢出且无法恢复！',
      danger: true, okText: '删除',
    })
    if (ok) await doDelete(room, { token: game.session!.playerToken })
  } else {
    password.value = ''
    dialog.value = { mode: 'delete', room }
  }
}

async function doDelete(room: RoomListItem, opts: { token?: string; password?: string }) {
  busy.value = true
  try {
    await game.deleteRoom(room.code, opts)
    dialog.value = null
    game.flash(`房间 ${room.name} 已删除`)
    refresh()
  } catch (e: any) {
    game.lastError = e.message
  } finally { busy.value = false }
}

function submitDialog() {
  const d = dialog.value
  if (!d) return
  if (d.mode === 'join') doJoin(d.room, password.value)
  else if (d.mode === 'takeover') doTakeover()
  else doDelete(d.room, { password: password.value })
}
</script>

<template>
  <div class="page no-tabbar">
    <h1 style="margin-top:24px">💸 现金流助手</h1>
    <p class="muted">实体棋盘照常玩，手机自动记账。抛开纸笔，告别算错账。</p>

    <div class="card" v-if="game.session">
      <p>已有对局会话：房间 <b>{{ game.session.roomCode }}</b></p>
      <div class="row">
        <button class="grow" @click="game.connect(); router.push(game.state?.status === 'PLAYING' ? '/play' : '/room')">继续对局</button>
        <button class="ghost" @click="game.clearSession()">清除本机记录</button>
      </div>
    </div>

    <div class="card">
      <h2>创建房间</h2>
      <label>房间名</label>
      <input v-model="roomName" maxlength="20" placeholder="例如：周末局" />
      <label>房间密码（可选，防止别人随意加入）</label>
      <input v-model="roomPassword" maxlength="16" placeholder="留空则任何人可加入" />
      <label>人数上限</label>
      <select v-model.number="maxPlayers">
        <option v-for="n in [2,3,4,5,6]" :key="n" :value="n">{{ n }} 人</option>
      </select>
      <label>你的昵称（作为房主）</label>
      <input v-model="nickname" maxlength="12" placeholder="例如：老王" />
      <button class="block" style="margin-top:10px"
              :disabled="busy || !roomName.trim() || !nickname.trim()"
              @click="create">创建房间</button>
    </div>

    <div class="row between">
      <div class="section-title">房间大厅</div>
      <button class="small ghost" :disabled="loading" @click="refresh">🔄 刷新</button>
    </div>
    <div class="card" style="padding:4px 14px">
      <p v-if="!rooms.length" class="muted" style="text-align:center">
        暂无房间，点上方"创建房间"开一局</p>
      <div v-for="room in rooms" :key="room.code" class="list-item row between"
           @click="tapRoom(room)">
        <div>
          <b>{{ room.name }}</b>
          <span class="muted" style="margin-left:6px">{{ room.code }}</span>
          <span v-if="room.hasPassword" title="需要密码">🔒</span>
          <div class="muted">
            <span class="badge" :class="{ turn: room.status === 'PLAYING' }">
              {{ STATUS_LABEL[room.status] ?? room.status }}</span>
            {{ room.playerCount }}/{{ room.maxPlayers }} 人
            <template v-if="room.status !== 'LOBBY'">· 点击接管座位</template>
          </div>
        </div>
        <button class="small ghost" @click.stop="tapDelete(room)">🗑</button>
      </div>
    </div>

    <p class="muted" style="text-align:center">
      <router-link to="/manual" style="color:var(--muted)">📖 查看游戏说明书</router-link>
      ·
      <router-link to="/entry" style="color:var(--muted)">🗂️ 卡牌录入工具</router-link>
    </p>

    <!-- 密码 / 选座弹窗 -->
    <div v-if="dialog" class="modal-mask" @click.self="dialog = null">
      <div class="modal">
        <template v-if="dialog.mode === 'join'">
          <h2>加入 {{ dialog.room.name }}</h2>
          <label>你的昵称</label>
          <input v-model="nickname" maxlength="12" placeholder="例如：老王" />
          <template v-if="dialog.room.hasPassword">
            <label>房间密码</label>
            <input v-model="password" maxlength="16" placeholder="向房主索取"
                   @keyup.enter="submitDialog" />
          </template>
        </template>
        <template v-else-if="dialog.mode === 'takeover'">
          <h2>接管座位 · {{ dialog.room.name }}</h2>
          <p class="muted">对局已开始，新玩家无法加入；换了设备的玩家可选自己的座位恢复身份（原设备将下线）。</p>
          <div v-for="p in dialog.seats?.players" :key="p.id" class="list-item row between"
               :style="dialog.seatId === p.id ? 'background:var(--panel2)' : ''"
               @click="dialog.seatId = p.id">
            <span>{{ dialog.seatId === p.id ? '✅' : '👤' }} {{ p.nickname }}
              <span v-if="p.isHost" class="badge">房主</span></span>
            <span class="muted">{{ p.professionTitle }}</span>
          </div>
          <template v-if="dialog.room.hasPassword">
            <label>房间密码</label>
            <input v-model="password" maxlength="16" @keyup.enter="submitDialog" />
          </template>
        </template>
        <template v-else>
          <h2>删除房间 {{ dialog.room.name }}</h2>
          <p style="color:var(--red);font-weight:700">⚠️ 对局尚未结束，删除后所有玩家将被踢出且无法恢复！</p>
          <template v-if="dialog.room.hasPassword">
            <label>输入房间密码以确认</label>
            <input v-model="password" maxlength="16" @keyup.enter="submitDialog" />
          </template>
          <p v-else class="muted">该房间未设密码，只有房主（在房主手机上）才能删除。</p>
        </template>
        <div class="row" style="margin-top:12px">
          <button class="grow" :class="{ warn: dialog.mode === 'delete' }"
                  :disabled="busy
                    || (dialog.mode === 'join' && !nickname.trim())
                    || (dialog.mode === 'takeover' && !dialog.seatId)
                    || (dialog.mode !== 'takeover' && dialog.room.hasPassword && !password)
                    || (dialog.mode === 'delete' && !dialog.room.hasPassword)"
                  @click="submitDialog">
            {{ dialog.mode === 'join' ? '加入' : dialog.mode === 'takeover' ? '接管该座位' : '删除' }}
          </button>
          <button class="grow ghost" @click="dialog = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
