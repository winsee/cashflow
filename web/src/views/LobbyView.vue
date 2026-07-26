<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, loadNickname, saveNickname, useGame } from '../store'
import type { RoomListItem, RoomSeats } from '../types'
import { confirmAction } from '../confirm'
import SeatPicker from '../components/SeatPicker.vue'

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
    const room = { code, name: seats.name, status: seats.status,
                   hasPassword: seats.hasPassword,
                   onlineCount: seats.onlineCount } as RoomListItem
    sheet.value = null
    password.value = codePassword.value
    if (seats.status === 'LOBBY' || seats.status === 'SETUP') {
      dialog.value = { mode: 'join', room, seats, seatId: '' }
      await doJoin(room, codePassword.value, seats)
    } else {
      // 已开始：转入接管座位弹窗
      dialog.value = { mode: 'takeover', room, seats, seatId: '' }
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
  // 无论房间是否开局都先拉座位：等待中的房间同样可能有人换设备/清了缓存要认领座位
  try {
    const seats = await game.fetchSeats(room.code)
    password.value = ''
    const waiting = seats.status === 'LOBBY' || seats.status === 'SETUP'
    dialog.value = { mode: waiting ? 'join' : 'takeover', room, seats, seatId: '' }
  } catch (e: any) { game.lastError = e.message }
}

/** 从「加入」切到「接管座位」，可预选一个座位（昵称撞车时就是同名那位） */
function switchToTakeover(seatId = '') {
  if (!dialog.value) return
  dialog.value = { ...dialog.value, mode: 'takeover', seatId }
}

async function doJoin(room: RoomListItem, pw: string, seats?: RoomSeats) {
  busy.value = true
  try {
    await game.joinRoom(room.code, nickname.value.trim(), pw)
    dialog.value = null
    router.push('/room')
  } catch (e: any) {
    const known = seats ?? dialog.value?.seats
    const mine = known?.players.find(p => p.nickname === nickname.value.trim())
    if (e instanceof ApiError && e.code === 'NICKNAME_TAKEN' && mine) {
      // 多半就是本人换了设备/清了缓存：直接把他送到接管界面，并预选同名座位
      switchToTakeover(mine.id)
      game.lastError = `「${mine.nickname}」已经在房里了——如果那是你，点「恢复该座位」拿回身份`
    } else {
      game.lastError = e.message
    }
  }
  finally { busy.value = false }
}

async function doTakeover() {
  const d = dialog.value
  if (!d?.seatId) return
  const seat = d.seats?.players.find(p => p.id === d.seatId)
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
    await game.takeover(d.room.code, d.seatId, password.value)
    const status = d.seats?.status ?? d.room.status
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
  } else if (!room.hasPassword && room.onlineCount === 0
             && (room.status === 'LOBBY' || room.status === 'SETUP')) {
    // 空壳房间（建了没连上、房主换了设备）：服务端允许任何人删，不必找房主
    const ok = await confirmAction({
      title: `删除房间 ${room.name}`,
      lines: ['该房间尚未开局且当前无人在线，删除不会打断任何人。'],
      danger: true, okText: '删除',
    })
    if (ok) await doDelete(room, {})
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
            <span v-if="!room.onlineCount" class="badge">无人在线</span>
            <template v-if="room.status !== 'LOBBY'">· 点击恢复座位</template>
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
          <p v-if="dialog.seats?.players.length" class="muted" style="margin-top:12px">
            已经在这个房间里了？（换了手机 / 清了缓存）
            <a href="#" @click.prevent="switchToTakeover()" style="color:var(--brand);font-weight:700">
              恢复我的座位</a>
          </p>
        </template>
        <template v-else-if="dialog.mode === 'takeover'">
          <h2>恢复座位 · {{ dialog.room.name }}</h2>
          <p class="muted">选中你自己的座位即可拿回身份（该座位的原设备会立即下线）。</p>
          <SeatPicker :players="dialog.seats?.players ?? []" v-model="dialog.seatId" />
          <template v-if="dialog.seats?.hasPassword">
            <label>房间密码</label>
            <input v-model="password" maxlength="16" @keyup.enter="submitDialog" />
          </template>
          <p v-if="dialog.seats?.status === 'LOBBY' || dialog.seats?.status === 'SETUP'"
             class="muted" style="margin-top:12px">
            想以新身份进来？
            <a href="#" @click.prevent="dialog.mode = 'join'" style="color:var(--brand);font-weight:700">
              换个昵称加入</a>
          </p>
        </template>
        <template v-else>
          <h2>删除房间 {{ dialog.room.name }}</h2>
          <p style="color:var(--red);font-weight:700">⚠️ 对局尚未结束，删除后所有玩家将被踢出且无法恢复！</p>
          <template v-if="dialog.room.hasPassword">
            <label>输入房间密码以确认</label>
            <input v-model="password" maxlength="16" @keyup.enter="submitDialog" />
          </template>
          <p v-else class="muted">
            该房间未设密码且仍有人在线，只有房主（在房主手机上）才能删除。</p>
        </template>
        <div class="row" style="margin-top:14px">
          <button class="grow" :class="{ warn: dialog.mode === 'delete' }"
                  :disabled="busy
                    || (dialog.mode === 'join' && !nickname.trim())
                    || (dialog.mode === 'takeover' && !dialog.seatId)
                    || (dialog.mode !== 'takeover' && dialog.room.hasPassword && !password)
                    || (dialog.mode === 'delete' && !dialog.room.hasPassword)"
                  @click="submitDialog">
            {{ dialog.mode === 'join' ? '加入' : dialog.mode === 'takeover' ? '恢复该座位' : '删除' }}
          </button>
          <button class="grow ghost" @click="dialog = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
