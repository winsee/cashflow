<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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

const initial = computed(() => (nickname.value.trim()[0] ?? '👤'))

const STATUS_LABEL: Record<string, string> = {
  LOBBY: '等待中', SETUP: '准备中', PLAYING: '进行中', FINISHED: '已结束', CLOSED: '已解散',
}

// ---------- 大厅列表 ----------
async function refresh() {
  loading.value = true
  try { rooms.value = await game.fetchRooms() }
  catch { /* 服务器未就绪时静默，下轮轮询再试 */ }
  finally { loading.value = false }
}
onMounted(() => { refresh(); pollTimer = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(pollTimer))

// ---------- 底部 sheet：创建 / 输入房间码 / 改名 ----------
const sheet = ref<null | 'create' | 'joincode' | 'rename'>(null)
const roomName = ref('现金流对局')
const roomPassword = ref('')
const maxPlayers = ref(6)
const joinCode = ref('')
const codePassword = ref('')
const codeError = ref('')

function openCreate() { roomName.value = '现金流对局'; roomPassword.value = ''; maxPlayers.value = 6; sheet.value = 'create' }
function openJoinCode() { joinCode.value = ''; codePassword.value = ''; codeError.value = ''; sheet.value = 'joincode' }

async function create() {
  if (!roomName.value.trim() || !nickname.value.trim()) return
  busy.value = true
  try {
    await game.createRoom(nickname.value.trim(), roomName.value.trim() || '现金流对局',
                          roomPassword.value.trim(), maxPlayers.value)
    sheet.value = null
    router.push('/room')
  } catch (e: any) { game.lastError = e.message }
  finally { busy.value = false }
}

async function submitCode() {
  const code = joinCode.value.trim().toUpperCase()
  if (!code) return
  codeError.value = ''
  busy.value = true
  try {
    const seats = await game.fetchSeats(code)
    if (game.session?.roomCode === code) {   // 本机就在这个房间：直接回去
      game.connect(); sheet.value = null
      router.push(seats.status === 'LOBBY' || seats.status === 'SETUP' ? '/room' : '/play')
      return
    }
    if (seats.status === 'LOBBY' || seats.status === 'SETUP') {
      await game.joinRoom(code, nickname.value.trim(), codePassword.value)
      sheet.value = null
      router.push('/room')
    } else {
      // 已开始：转入接管座位弹窗
      sheet.value = null
      dialog.value = { mode: 'takeover', room: { code, name: seats.name } as RoomListItem, seats, seatId: '' }
      password.value = codePassword.value
    }
  } catch (e: any) { codeError.value = e.message }
  finally { busy.value = false }
}

// ---------- 点击列表中的房间：加入 / 接管 / 删除（沿用原逻辑） ----------
const dialog = ref<null | {
  mode: 'join' | 'takeover' | 'delete'
  room: RoomListItem
  seats?: RoomSeats
  seatId?: string
}>(null)
const password = ref('')

async function tapRoom(room: RoomListItem) {
  game.lastError = ''
  if (game.session?.roomCode === room.code) {
    game.connect()
    router.push(room.status === 'LOBBY' || room.status === 'SETUP' ? '/room' : '/play')
    return
  }
  if (room.status === 'LOBBY' || room.status === 'SETUP') {
    password.value = ''
    dialog.value = { mode: 'join', room }
  } else {
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
  } catch (e: any) { game.lastError = e.message }
  finally { busy.value = false }
}

async function doTakeover() {
  const d = dialog.value
  if (!d?.seatId) return
  busy.value = true
  try {
    await game.takeover(d.room.code, d.seatId, password.value)
    const status = d.room.status ?? d.seats?.status
    dialog.value = null
    router.push(status === 'LOBBY' || status === 'SETUP' ? '/room' : '/play')
  } catch (e: any) { game.lastError = e.message }
  finally { busy.value = false }
}

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
  } catch (e: any) { game.lastError = e.message }
  finally { busy.value = false }
}

function submitDialog() {
  const d = dialog.value
  if (!d) return
  if (d.mode === 'join') doJoin(d.room, password.value)
  else if (d.mode === 'takeover') doTakeover()
  else doDelete(d.room, { password: password.value })
}

function continueGame() {
  game.connect()
  router.push(game.state?.status === 'PLAYING' || game.state?.status === 'FINISHED' ? '/play' : '/room')
}
</script>

<template>
  <div class="page no-tabbar">
    <div class="appbar">
      <div class="brand"><span class="logo">💸</span>现金流助手</div>
      <div class="chip" @click="sheet = 'rename'">
        <span class="avatar">{{ initial }}</span>{{ nickname || '设置昵称' }} ⌄
      </div>
    </div>

    <!-- 继续对局 -->
    <div class="card" v-if="game.session" style="border-color:#cdb98a;background:linear-gradient(160deg,#FFFDF8,#F6ECD3)">
      <div class="row between">
        <div>
          <b>你有一局进行中</b>
          <div class="muted">房间 {{ game.session.roomCode }}</div>
        </div>
        <div class="row">
          <button class="small" @click="continueGame">继续对局</button>
          <button class="small ghost" @click="game.clearSession()">清除</button>
        </div>
      </div>
    </div>

    <!-- 双主入口 -->
    <div class="bigbtn-row">
      <div class="bigbtn" @click="openCreate">
        <span class="ic">＋</span>
        <span class="t">创建房间</span>
        <span class="s">开一桌新对局</span>
      </div>
      <div class="bigbtn alt" @click="openJoinCode">
        <span class="ic">🔑</span>
        <span class="t">输入房间码</span>
        <span class="s">加入朋友的对局</span>
      </div>
    </div>

    <!-- 房间大厅 -->
    <div class="row between">
      <div class="section-title">房间大厅</div>
      <button class="small ghost" :disabled="loading" @click="refresh">🔄 刷新</button>
    </div>
    <div class="card" style="padding:2px 14px" v-if="rooms.length">
      <div v-for="room in rooms" :key="room.code" class="list-item row between" @click="tapRoom(room)">
        <div>
          <b>{{ room.name }}</b>
          <span class="muted" style="margin-left:6px">{{ room.code }}</span>
          <span v-if="room.hasPassword" title="需要密码">🔒</span>
          <div class="muted" style="margin-top:3px">
            <span class="badge" :class="{ turn: room.status === 'PLAYING' }">
              {{ STATUS_LABEL[room.status] ?? room.status }}</span>
            {{ room.playerCount }}/{{ room.maxPlayers }} 人
            <template v-if="room.status !== 'LOBBY'">· 点击接管座位</template>
          </div>
        </div>
        <button class="small ghost" @click.stop="tapDelete(room)">🗑</button>
      </div>
    </div>
    <p v-else class="muted" style="text-align:center;padding:18px 0">
      暂无房间，点上方「创建房间」开一局</p>

    <p class="muted" style="text-align:center;margin-top:18px">
      <router-link to="/manual" style="color:var(--muted)">📖 游戏说明书</router-link>
      ·
      <router-link to="/entry" style="color:var(--muted)">🗂️ 卡牌录入</router-link>
    </p>

    <!-- ===== 底部 sheet ===== -->
    <div v-if="sheet" class="modal-mask" @click.self="sheet = null">
      <div class="modal">
        <template v-if="sheet === 'create'">
          <h2>创建房间</h2>
          <label>房间名</label>
          <input v-model="roomName" maxlength="20" placeholder="例如：周末局" />
          <label>房间密码（可选，防止别人随意加入）</label>
          <input v-model="roomPassword" maxlength="16" placeholder="留空则任何人可加入" />
          <label>人数上限</label>
          <select v-model.number="maxPlayers">
            <option v-for="n in [2,3,4,5,6]" :key="n" :value="n">{{ n }} 人</option>
          </select>
          <button class="block" style="margin-top:14px"
                  :disabled="busy || !roomName.trim() || !nickname.trim()" @click="create">
            创建房间（你作为房主）
          </button>
        </template>

        <template v-else-if="sheet === 'joincode'">
          <h2>输入房间码</h2>
          <label>房间码（4 位）</label>
          <input v-model="joinCode" maxlength="6" placeholder="例如：JP8Q"
                 style="text-transform:uppercase;letter-spacing:3px;font-weight:700"
                 @keyup.enter="submitCode" />
          <label>房间密码（若有）</label>
          <input v-model="codePassword" maxlength="16" placeholder="没有就留空" @keyup.enter="submitCode" />
          <p v-if="codeError" class="muted" style="color:var(--red)">{{ codeError }}</p>
          <button class="block" style="margin-top:14px"
                  :disabled="busy || !joinCode.trim() || !nickname.trim()" @click="submitCode">
            加入
          </button>
        </template>

        <template v-else>
          <h2>修改昵称</h2>
          <label>昵称会记在本机，之后自动带上</label>
          <input v-model="nickname" maxlength="12" placeholder="例如：老王" @keyup.enter="sheet = null" />
          <button class="block" style="margin-top:14px" :disabled="!nickname.trim()" @click="sheet = null">
            完成
          </button>
        </template>
      </div>
    </div>

    <!-- ===== 列表房间：加入 / 接管 / 删除弹窗 ===== -->
    <div v-if="dialog" class="modal-mask" @click.self="dialog = null">
      <div class="modal">
        <template v-if="dialog.mode === 'join'">
          <h2>加入 {{ dialog.room.name }}</h2>
          <label>你的昵称</label>
          <input v-model="nickname" maxlength="12" placeholder="例如：老王" />
          <template v-if="dialog.room.hasPassword">
            <label>房间密码</label>
            <input v-model="password" maxlength="16" placeholder="向房主索取" @keyup.enter="submitDialog" />
          </template>
        </template>
        <template v-else-if="dialog.mode === 'takeover'">
          <h2>接管座位 · {{ dialog.room.name }}</h2>
          <p class="muted">对局已开始，新玩家无法加入；换了设备的玩家可选自己的座位恢复身份（原设备将下线）。</p>
          <div v-for="p in dialog.seats?.players" :key="p.id" class="list-item row between"
               :style="dialog.seatId === p.id ? 'background:var(--brand-soft);border-radius:10px' : ''"
               @click="dialog.seatId = p.id">
            <span>{{ dialog.seatId === p.id ? '✅' : '👤' }} {{ p.nickname }}
              <span v-if="p.isHost" class="badge">房主</span></span>
            <span class="muted">{{ p.professionTitle }}</span>
          </div>
          <template v-if="dialog.seats?.hasPassword">
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
        <div class="row" style="margin-top:14px">
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
