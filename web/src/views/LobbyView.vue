<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, loadNickname, saveNickname, useGame } from '../store'
import type { GameMode, RoomListItem, RoomSeats } from '../types'
import { confirmAction } from '../confirm'
import SeatPicker from '../components/SeatPicker.vue'
import BaseModal from '../components/base/BaseModal.vue'
import ModeBadge from '../components/ModeBadge.vue'

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
/** 建房时选定的对局模式（design/09 §1.2 分流点 1）；房间建好后谁都改不了 */
const createMode = ref<GameMode>('OFFLINE_ASSIST')
/** 建房分两步：① 只问「怎么玩」 ② 才是房间名/密码/人数。
 *  模式是这局唯一改不了的决定（MODE_LOCKED），不该和三个随时能改的表单项挤在一屏里。 */
const createStep = ref<1 | 2>(1)

function openCreate() {
  roomName.value = '现金流对局'; roomPassword.value = ''; maxPlayers.value = 6
  createMode.value = 'OFFLINE_ASSIST'
  createStep.value = 1
  sheet.value = 'create'
}
function openJoinCode() { joinCode.value = ''; codePassword.value = ''; codeError.value = ''; sheet.value = 'joincode' }

async function create() {
  if (!roomName.value.trim() || !nickname.value.trim()) return
  busy.value = true
  try {
    await game.createRoom(nickname.value.trim(), roomName.value.trim() || '现金流对局',
                          roomPassword.value.trim(), maxPlayers.value, createMode.value)
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
    const room = { code, name: seats.name, status: seats.status, mode: seats.mode,
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

/** 「继续对局」那张卡上的实时状态：第几轮、几人在线、轮到谁（大厅列表里就有） */
const myRoom = computed(() => rooms.value.find(r => r.code === game.session?.roomCode) ?? null)

const SHEET_TITLE: Record<string, string> = {
  create: '创建房间', joincode: '输入房间码', rename: '修改昵称',
}
const sheetTitle = computed(() =>
  sheet.value === 'create' && createStep.value === 1
    ? '这一局怎么玩？' : (SHEET_TITLE[sheet.value ?? ''] ?? ''))

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

    <!-- 继续对局：永远排第一，写清进行到哪一步了 -->
    <div class="card gold" v-if="game.session">
      <div class="row between">
        <div>
          <div class="muted" style="font-size:11px">继续对局</div>
          <div style="font-size:15px;font-weight:800;margin-top:2px">
            {{ myRoom?.name ?? '你有一局进行中' }}
            <template v-if="myRoom?.turnCount"> · 第 {{ myRoom.turnCount }} 轮</template>
          </div>
          <div class="muted">
            房间 {{ game.session.roomCode }}
            <template v-if="myRoom"> · {{ myRoom.onlineCount }} 人在线</template>
            <template v-if="myRoom?.currentPlayer"> · 轮到{{ myRoom.currentPlayer }}</template>
          </div>
        </div>
        <div class="row">
          <button class="btn small gold" @click="continueGame">回到牌桌</button>
          <button class="btn small ghost" @click="game.clearSession()">清除</button>
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
      <button class="btn small ghost" :disabled="loading" @click="refresh">🔄 刷新</button>
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
            <!-- 模式排在「第 N 轮 · X 人在线」之前：点进去之前就该知道玩的是哪一种 -->
            <ModeBadge :mode="room.mode ?? 'OFFLINE_ASSIST'" />
            {{ room.playerCount }} / {{ room.maxPlayers }} 人 ·
            {{ room.onlineCount ? `${room.onlineCount} 人在线` : '无人在线' }}
            <template v-if="room.turnCount"> · 第 {{ room.turnCount }} 轮</template>
            <template v-if="room.currentPlayer"> · 轮到{{ room.currentPlayer }}</template>
            <template v-if="room.status !== 'LOBBY'"> · 点击恢复座位</template>
          </div>
        </div>
        <button class="btn small ghost" @click.stop="tapDelete(room)">🗑</button>
      </div>
    </div>
    <p v-else class="muted" style="text-align:center;padding:18px 0">
      暂无房间，点上方「创建房间」开一局</p>

    <p class="muted" style="text-align:center;margin-top:18px">
      <router-link to="/manual" style="color:var(--muted)">📖 游戏说明书</router-link>
      ·
      <router-link to="/entry" style="color:var(--muted)">🗂️ 卡牌录入</router-link>
    </p>

    <!-- ===== 底部弹层：创建 / 输入房间码 / 改名 ===== -->
    <BaseModal v-if="sheet" :title="sheetTitle" dismissable @close="sheet = null">
      <div>
        <template v-if="sheet === 'create'">
          <!-- 第 ① 步：只问模式。模式此后谁都改不了，这一屏就该只讲这一件事，
               并把「玩这一局需要准备什么」逐条写出来 -->
          <template v-if="createStep === 1">
            <div class="bigbtn-row mode-pick">
              <div class="bigbtn alt" :class="{ selected: createMode === 'OFFLINE_ASSIST' }"
                   @click="createMode = 'OFFLINE_ASSIST'">
                <span v-if="createMode === 'OFFLINE_ASSIST'" class="tick">✓</span>
                <span class="ic">⚄</span>
                <span class="t">线下辅助</span>
                <span class="s">围着实体棋盘玩，手机只管识别卡面和记账。</span>
                <ul class="prep">
                  <li>实体棋盘、骰子、全套卡牌</li>
                  <li>每人一台手机，进同一个房间</li>
                </ul>
              </div>
              <div class="bigbtn" :class="{ selected: createMode === 'ONLINE' }"
                   @click="createMode = 'ONLINE'">
                <span v-if="createMode === 'ONLINE'" class="tick">✓</span>
                <span class="ic">▣</span>
                <span class="t">纯线上</span>
                <span class="s">棋盘、骰子、发牌全在屏幕里。</span>
                <ul class="prep">
                  <li>什么实物都不用准备</li>
                  <li>每人一台手机就能开局</li>
                </ul>
              </div>
            </div>
          </template>

          <!-- 第 ② 步：房间本身。顶部回显已选模式，「改」退回第 ① 步重选 -->
          <template v-else>
            <div class="row between" style="margin-bottom:10px">
              <ModeBadge :mode="createMode" />
              <button class="btn ghost small" @click="createStep = 1">改</button>
            </div>
            <label>房间名</label>
            <input v-model="roomName" maxlength="20" placeholder="例如：周末局" />
            <label>房间密码（可选，防止别人随意加入）</label>
            <input v-model="roomPassword" maxlength="16" placeholder="留空则任何人可加入" />
            <label>人数上限</label>
            <select v-model.number="maxPlayers">
              <option v-for="n in [2,3,4,5,6]" :key="n" :value="n">{{ n }} 人</option>
            </select>
          </template>
        </template>

        <template v-else-if="sheet === 'joincode'">
          <label>房间码（4 位）</label>
          <input v-model="joinCode" maxlength="6" placeholder="例如：JP8Q"
                 style="text-transform:uppercase;letter-spacing:3px;font-weight:700"
                 @keyup.enter="submitCode" />
          <label>房间密码（若有）</label>
          <input v-model="codePassword" maxlength="16" placeholder="没有就留空" @keyup.enter="submitCode" />
          <p v-if="codeError" class="muted" style="color:var(--red)">{{ codeError }}</p>
        </template>

        <template v-else>
          <label>昵称会记在本机，之后自动带上</label>
          <input v-model="nickname" maxlength="12" placeholder="例如：老王" @keyup.enter="sheet = null" />
        </template>
      </div>
      <template #actions>
        <button v-if="sheet === 'create' && createStep === 1" class="btn grow"
                @click="createStep = 2">下一步</button>
        <button v-else-if="sheet === 'create'" class="btn grow"
                :disabled="busy || !roomName.trim() || !nickname.trim()" @click="create">
          创建房间（你作为房主）
        </button>
        <button v-else-if="sheet === 'joincode'" class="btn grow"
                :disabled="busy || !joinCode.trim() || !nickname.trim()" @click="submitCode">加入</button>
        <button v-else class="btn grow" :disabled="!nickname.trim()" @click="sheet = null">完成</button>
        <button class="btn ghost grow" @click="sheet = null">取消</button>
      </template>
    </BaseModal>

    <!-- ===== 列表房间：加入 / 接管 / 删除 ===== -->
    <BaseModal v-if="dialog" dismissable @close="dialog = null"
               :title="dialog.mode === 'join' ? `加入 ${dialog.room.name}`
                 : dialog.mode === 'takeover' ? `恢复座位 · ${dialog.room.name}`
                 : `删除房间 ${dialog.room.name}`">
      <div>
        <template v-if="dialog.mode === 'join'">
          <!-- 加入前先说清这是哪一种局：纯线上的不用带任何实物 -->
          <p class="muted" style="margin-top:0">
            <ModeBadge :mode="dialog.seats?.mode ?? dialog.room.mode ?? 'OFFLINE_ASSIST'" />
            <template v-if="(dialog.seats?.mode ?? dialog.room.mode) === 'ONLINE'">
              棋盘和牌都在屏幕里，不用带任何实物。</template>
            <template v-else>需要一副实体棋盘、骰子和卡牌。</template>
          </p>
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
          <p style="color:var(--red);font-weight:700">⚠️ 对局尚未结束，删除后所有玩家将被踢出且无法恢复！</p>
          <template v-if="dialog.room.hasPassword">
            <label>输入房间密码以确认</label>
            <input v-model="password" maxlength="16" @keyup.enter="submitDialog" />
          </template>
          <p v-else class="muted">
            该房间未设密码且仍有人在线，只有房主（在房主手机上）才能删除。</p>
        </template>
      </div>
      <template #actions>
        <button class="btn grow" :class="{ warn: dialog.mode === 'delete' }"
                :disabled="busy
                  || (dialog.mode === 'join' && !nickname.trim())
                  || (dialog.mode === 'takeover' && !dialog.seatId)
                  || (dialog.mode !== 'takeover' && dialog.room.hasPassword && !password)
                  || (dialog.mode === 'delete' && !dialog.room.hasPassword)"
                @click="submitDialog">
          {{ dialog.mode === 'join' ? '加入' : dialog.mode === 'takeover' ? '恢复该座位' : '删除' }}
        </button>
        <button class="btn ghost grow" @click="dialog = null">取消</button>
      </template>
    </BaseModal>
  </div>
</template>
