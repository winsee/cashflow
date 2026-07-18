import { defineStore } from 'pinia'
import type { CardDto, LogEntry, Player, Prompt, RoomStateDto } from './types'

interface Session {
  roomCode: string
  playerId: string
  playerToken: string
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
    ws: null as WebSocket | null,
    pendingResolvers: new Map<string, (ok: boolean) => void>(),
    reconnectTimer: 0 as any,
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
    async createRoom(nickname: string, name = '现金流对局') {
      const r = await fetch('/api/rooms', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname, name }),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '创建失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
    },
    async joinRoom(code: string, nickname: string) {
      const r = await fetch(`/api/rooms/${code}/join`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname }),
      })
      if (!r.ok) throw new Error((await r.json()).message ?? '加入失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
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
    /** 发送行动；返回是否被服务器接受（错误会展示在 lastError） */
    act(type: string, payload: Record<string, any> = {}): Promise<boolean> {
      return new Promise((resolve) => {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
          this.lastError = '连接已断开，正在重连…'
          resolve(false)
          return
        }
        const actionId = crypto.randomUUID()
        this.pendingResolvers.set(actionId, (ok) => {
          this.pendingResolvers.delete(actionId)
          resolve(ok)
        })
        this.ws.send(JSON.stringify({ actionId, type, payload }))
        // 兜底超时
        setTimeout(() => {
          if (this.pendingResolvers.has(actionId)) {
            this.pendingResolvers.delete(actionId)
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

export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return '0'
  return '$' + n.toLocaleString('en-US')
}
