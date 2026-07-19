import { defineStore } from 'pinia'
import type { CardDto, LogEntry, Player, Prompt, RoomListItem, RoomSeats, RoomStateDto } from './types'

interface Session {
  roomCode: string
  playerId: string
  playerToken: string
}

/** 局域网 HTTP（非安全上下文）没有 crypto.randomUUID，用 getRandomValues 兜底 */
function uuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, x => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem('cashflow.session')
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export const useGame = defineStore('game', {
  state: () => ({
    session: loadSession() as Session | null,
    state: null as RoomStateDto | null,
    seq: 0,
    connected: false,
    lastError: '' as string,
    notice: '' as string,
    ws: null as WebSocket | null,
    pendingResolvers: new Map<string, (ok: boolean) => void>(),
    pendingTypes: {} as Record<string, boolean>,
    reconnectTimer: 0 as any,
    noticeTimer: 0 as any,
  }),
  getters: {
    me(): Player | null {
      if (!this.state || !this.session) return null
      return this.state.players.find(p => p.id === this.session!.playerId) ?? null
    },
    isMyTurn(): boolean {
      return !!this.state && !!this.session && this.state.currentPlayerId === this.session.playerId
    },
    myPrompts(): Prompt[] {
      if (!this.state || !this.session) return []
      return this.state.prompts.filter(p => p.target_player_id === this.session!.playerId)
    },
    currentPlayer(): Player | null {
      if (!this.state?.currentPlayerId) return null
      return this.state.players.find(p => p.id === this.state!.currentPlayerId) ?? null
    },
  },
  actions: {
    saveSession(s: Session) {
      this.session = s
      localStorage.setItem('cashflow.session', JSON.stringify(s))
    },
    clearSession() {
      this.session = null
      this.state = null
      localStorage.removeItem('cashflow.session')
      this.ws?.close()
      this.ws = null
    },
    async createRoom(nickname: string, name = '现金流对局', password = '', maxPlayers = 6) {
      const r = await fetch('/api/rooms', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname, name, maxPlayers, password: password || null }),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '创建失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
    },
    async joinRoom(code: string, nickname: string, password = '') {
      const r = await fetch(`/api/rooms/${code}/join`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname, password: password || null }),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '加入失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
    },
    /** 座位接管（换设备恢复身份）：凭房间密码认领已有座位，旧令牌作废 */
    async takeover(code: string, playerId: string, password = '') {
      const r = await fetch(`/api/rooms/${code}/takeover`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ playerId, password: password || null }),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '接管失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
    },
    async fetchRooms(): Promise<RoomListItem[]> {
      const r = await fetch('/api/rooms')
      if (!r.ok) throw new Error('获取房间列表失败')
      return r.json()
    },
    async fetchSeats(code: string): Promise<RoomSeats> {
      const r = await fetch(`/api/rooms/${code}/seats`)
      if (!r.ok) throw new Error((await r.json()).message ?? '房间不存在')
      return r.json()
    },
    /** 删除房间：已结束房间直接删；否则需房主令牌或房间密码 */
    async deleteRoom(code: string, opts: { token?: string; password?: string } = {}) {
      const r = await fetch(`/api/rooms/${code}`, {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '删除失败')
      if (this.session?.roomCode === code) this.clearSession()
    },
    /** 普通玩家主动退出：服务端会记录退出、废弃令牌；本机随后清除会话。 */
    async leaveGame(): Promise<boolean> {
      const ok = await this.act('LEAVE_GAME')
      if (ok) this.clearSession()
      return ok
    },
    connect() {
      if (!this.session || this.ws) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws?token=${this.session.playerToken}`)
      this.ws = ws
      ws.onopen = () => { this.connected = true }
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        if (msg.type === 'snapshot' || msg.type === 'state') {
          this.seq = msg.seq
          this.state = msg.state
        } else if (msg.type === 'ack') {
          if (msg.actionId) this.pendingResolvers.get(msg.actionId)?.(true)
        } else if (msg.type === 'error') {
          this.lastError = msg.message
          if (msg.actionId) this.pendingResolvers.get(msg.actionId)?.(false)
          setTimeout(() => { if (this.lastError === msg.message) this.lastError = '' }, 5000)
        }
      }
      ws.onclose = () => {
        this.connected = false
        this.ws = null
        // 手机锁屏/切后台恢复：自动重连拉齐快照（NFR-4）
        if (this.session) {
          clearTimeout(this.reconnectTimer)
          this.reconnectTimer = setTimeout(() => this.connect(), 1500)
        }
      }
    },
    /** 成功提示（绿色 toast，3 秒自动消失） */
    flash(msg: string) {
      this.notice = msg
      clearTimeout(this.noticeTimer)
      this.noticeTimer = setTimeout(() => { this.notice = '' }, 3000)
    },
    /** 发送行动；返回是否被服务器接受（错误会展示在 lastError）。
     *  同类型行动在途时忽略后续点击，防止双击造成两笔贷款/结算。 */
    act(type: string, payload: Record<string, any> = {}): Promise<boolean> {
      return new Promise((resolve) => {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
          this.lastError = '连接已断开，正在重连…'
          resolve(false)
          return
        }
        if (this.pendingTypes[type]) {
          resolve(false)
          return
        }
        this.pendingTypes[type] = true
        const actionId = uuid()
        this.pendingResolvers.set(actionId, (ok) => {
          this.pendingResolvers.delete(actionId)
          delete this.pendingTypes[type]
          resolve(ok)
        })
        try {
          this.ws.send(JSON.stringify({ actionId, type, payload }))
        } catch (e) {
          this.pendingResolvers.delete(actionId)
          delete this.pendingTypes[type]
          this.lastError = '发送失败，请重试'
          resolve(false)
          return
        }
        // 兜底超时
        setTimeout(() => {
          if (this.pendingResolvers.has(actionId)) {
            this.pendingResolvers.delete(actionId)
            delete this.pendingTypes[type]
            resolve(true)
          }
        }, 5000)
      })
    },
    async fetchCards(deck?: string, q = ''): Promise<CardDto[]> {
      const params = new URLSearchParams()
      if (deck) params.set('deck', deck)
      if (q) params.set('q', q)
      const r = await fetch(`/api/cards?${params}`)
      return r.json()
    },
    async fetchLog(): Promise<LogEntry[]> {
      if (!this.session) return []
      const r = await fetch(`/api/rooms/${this.session.roomCode}/log`)
      return r.json()
    },
    async fetchFasttrackBoard() {
      const r = await fetch('/api/board/fasttrack')
      return r.json()
    },
  },
})

export function loadNickname(): string {
  try { return localStorage.getItem('cashflow.nickname') ?? '' } catch { return '' }
}

export function saveNickname(n: string) {
  try { localStorage.setItem('cashflow.nickname', n) } catch { /* 隐私模式下忽略 */ }
}

export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return '0'
  return '$' + n.toLocaleString('en-US')
}
