import { defineStore } from 'pinia'
import { buildCardImpact, buildReceipts, type CardImpact, type Receipt } from './receipts'
import type { CardDto, LogEntry, Player, Prompt, RoomListItem, RoomSeats, RoomStateDto } from './types'

/** toast 的四种口吻：成功 / 出错 / 仪式（金色高光）/ 中性信息 */
export type FlashVariant = 'ok' | 'err' | 'gold' | 'info'

export interface Notice {
  id: number
  msg: string
  variant: FlashVariant
}

interface Session {
  roomCode: string
  playerId: string
  playerToken: string
}

/** 当前股票报价窗口与「我」的关系（谁能买/能卖多少），由 myStockWindow 计算 */
export interface StockWindow {
  cardId: string
  symbol: string
  price: number
  buyerScope: 'DRAWER_ONLY' | 'ALL'
  /** 我在该代码上的全部持仓，可能因买入价不同分成多笔（引擎按此顺序扣减） */
  lots: Player['stocks']
  held: number
  canSell: boolean
  canBuy: boolean
  /** 本窗口的去重键：卡 + 轮次，回合一变即失效 */
  key: string
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

/** 带服务端错误码的 API 异常：调用方要按 code 分支（如 NICKNAME_TAKEN → 引导接管座位），
 *  靠中文文案匹配太脆。服务端所有 EngineError 都以 {code, message} 返回（main.py 的异常处理器）。 */
export class ApiError extends Error {
  code: string
  constructor(message: string, code = '') {
    super(message)
    this.code = code
  }
}

/** 统一解析失败响应：拿不到 JSON（网关 502 之类）时退回默认文案 */
async function apiError(r: Response, fallback: string): Promise<ApiError> {
  try {
    const body = await r.json()
    return new ApiError(body.message ?? fallback, body.code ?? '')
  } catch { return new ApiError(fallback) }
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem('cashflow.session')
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** 服务端主动拒绝本机身份的 WS 关闭码：4001 = 令牌无效/房间不存在（main.py 的 /ws 握手），
 *  4002 = 房间因 24h 无活动已归档（rooms.py archive_idle）。这两种都不可能靠重连恢复，
 *  必须停止重连并清会话，否则页面会永久停在「连接中…」。 */
const FATAL_CLOSE: Record<number, string> = {
  4001: '对局已不存在或身份已失效，已返回大厅',
  4002: '房间因长时间无人操作已归档，已返回大厅',
}

export const useGame = defineStore('game', {
  state: () => ({
    session: loadSession() as Session | null,
    state: null as RoomStateDto | null,
    seq: 0,
    connected: false,
    lastError: '' as string,
    /** toast 队列：同时来两条就排队，一次只显示一条，绝不叠加 */
    notices: [] as Notice[],
    sessionLost: false,          // 服务端拒绝了本机身份；App.vue 据此跳回大厅
    ws: null as WebSocket | null,
    pendingResolvers: new Map<string, (ok: boolean) => void>(),
    pendingTypes: {} as Record<string, boolean>,
    /** 我最近发出的行动类型 → 时间戳。用于把「自己主动做的事」从被动回执里排掉 */
    recentActionAt: {} as Record<string, number>,
    reconnectTimer: 0 as any,
    noticeTimer: 0 as any,
    stockDismissed: '' as string,   // 我点过「不需要」的股票窗口 key（纯本地，不广播）
    /** 我在本窗口内成功买入过的 key（纯本地）：区分「这次没买，历史仓位」和
     *  「这次真买了」，前者按钮该说「我不买」，后者不该——旧仓位不代表这次已表态 */
    stockBoughtAt: '' as string,
    /** 「刚刚发生在你身上」：没操作却改了我的账的事，停在行动页顶部直到本人确认 */
    receipts: [] as Receipt[],
    /** 当前这张卡波及了谁（全员可见的「大声读出来」那一份），随卡失效 */
    lastImpact: null as CardImpact | null,
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
    /** 当前股票窗口与我的关系；与我无关（无持仓且不可买）或我不在老鼠赛跑时为 null。
     *  卖出窗口活到抽卡人回合结束，抽卡人放弃购买不影响（engine._stock_card）。 */
    myStockWindow(): StockWindow | null {
      const ac = this.state?.activeCard
      const offer = ac?.stockOffer
      const m = this.me
      if (!ac || !offer || !m) return null
      if (m.phase !== 'RAT_RACE' || m.inBankruptcy) return null   // 与引擎的两道校验对齐
      const lots = m.stocks.filter(s => s.symbol === offer.symbol)
      const held = lots.reduce((a, s) => a + s.shares, 0)
      const canBuy = offer.buyerScope === 'ALL' || ac.drawer_id === m.id
      if (held <= 0 && !canBuy) return null
      return {
        cardId: ac.card_id, symbol: offer.symbol, price: offer.price,
        buyerScope: offer.buyerScope, lots, held,
        canSell: held > 0, canBuy,
        key: `${ac.card_id}@${this.state!.turnCount}`,
      }
    },
    /** 交易窗口是否要出现在我的「行动」页（点过「不需要」就收起，直到下一张卡） */
    stockWindowOpen(): boolean {
      const w = this.myStockWindow
      return !!w && this.stockDismissed !== w.key
    },
    /** 当前该显示的那一条 toast（队首） */
    notice(): Notice | null {
      return this.notices[0] ?? null
    },
    /** 当前活动卡的波及范围；换一张卡（或换一轮抽到同一张）即自动作废 */
    cardImpact(): CardImpact | null {
      const ac = this.state?.activeCard
      if (!ac || !this.lastImpact) return null
      return this.lastImpact.key === `${ac.card_id}@${this.state!.turnCount}` ? this.lastImpact : null
    },
    /** 我是不是在快车道：整屏换肤、报表翻面、HUD 换算都看它 */
    inFasttrack(): boolean {
      return this.me?.phase === 'FAST_TRACK'
    },
  },
  actions: {
    saveSession(s: Session) {
      // 换身份（新建/加入/接管）时旧连接必须先断：connect() 见 this.ws 非空就直接返回，
      // 留着旧 socket 会让新会话永远连不上，页面永久停在「连接中…」。
      if (this.ws && this.session?.playerToken !== s.playerToken) {
        clearTimeout(this.reconnectTimer)
        const old = this.ws
        this.ws = null            // 先摘掉，避免 onclose 里的自动重连拿新令牌重连旧 socket
        old.onclose = null
        old.close()
        this.state = null         // 旧房间的快照不能留，否则 /room 会闪一下上一局
        this.seq = 0
      }
      this.session = s
      localStorage.setItem('cashflow.session', JSON.stringify(s))
    },
    clearSession() {
      this.session = null
      this.state = null
      this.receipts = []
      localStorage.removeItem('cashflow.session')
      this.ws?.close()
      this.ws = null
    },
    async createRoom(nickname: string, name = '现金流对局', password = '', maxPlayers = 6) {
      const r = await fetch('/api/rooms', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname, name, maxPlayers, password: password || null }),
      })
      if (!r.ok) throw await apiError(r, '创建失败')
      const d = await r.json()
      this.saveSession({ roomCode: d.roomCode, playerId: d.playerId, playerToken: d.playerToken })
      this.connect()
    },
    async joinRoom(code: string, nickname: string, password = '') {
      const r = await fetch(`/api/rooms/${code}/join`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname, password: password || null }),
      })
      if (!r.ok) throw await apiError(r, '加入失败')
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
      if (!r.ok) throw await apiError(r, '接管失败')
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
      if (!r.ok) throw await apiError(r, '房间不存在')
      return r.json()
    },
    /** 删除房间：已结束房间直接删；否则需房主令牌或房间密码 */
    async deleteRoom(code: string, opts: { token?: string; password?: string } = {}) {
      const r = await fetch(`/api/rooms/${code}`, {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts),
      })
      if (!r.ok) throw await apiError(r, '删除失败')
      if (this.session?.roomCode === code) this.clearSession()
    },
    /** 普通玩家主动退出：服务端会记录退出、废弃令牌；本机随后清除会话。 */
    async leaveGame(): Promise<boolean> {
      const ok = await this.act('LEAVE_GAME')
      if (ok) this.clearSession()
      return ok
    },
    /** 房主结束对局（房间转 CLOSED，全员回大厅）。 */
    endGame(): Promise<boolean> {
      return this.act('END_GAME')
    },
    /** 房主发起再来一局：同一房间就地重置为准备阶段，全员自动回房间准备页重选职业。 */
    rematch(): Promise<boolean> {
      return this.act('REMATCH')
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
          // 先用「旧快照 + 本批事件」算回执，再换上新快照：
          // 被没收的资产在新快照里已经不存在了，名字只能从旧的那份拿。
          if (msg.type === 'state' && msg.lastEvents?.length) this.ingestEvents(msg.lastEvents)
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
      ws.onclose = (ev) => {
        this.connected = false
        this.ws = null
        // 房间已删除/已归档/令牌失效：重连一万次也没用，清会话回大厅并说明原因。
        // 4000（座位被接管/房间被删）不在此列：重连一次即拿到 4001，由这里统一收口。
        const fatal = FATAL_CLOSE[ev.code]
        if (fatal) {
          clearTimeout(this.reconnectTimer)
          this.clearSession()
          this.lastError = fatal
          this.sessionLost = true
          return
        }
        // 手机锁屏/切后台恢复：自动重连拉齐快照（NFR-4）
        if (this.session) {
          clearTimeout(this.reconnectTimer)
          this.reconnectTimer = setTimeout(() => this.connect(), 1500)
        }
      }
    },
    /** 「不需要」：只收起我自己这一次的股票交易窗口，不发事件、不影响别人。
     *  窗口本身活到抽卡人回合结束，收起后行动页顶部仍留一个重新打开的入口。 */
    dismissStockWindow() {
      const w = this.myStockWindow
      if (w) this.stockDismissed = w.key
    },
    reopenStockWindow() {
      this.stockDismissed = ''
    },
    /** 在当前股票窗口里成功买入了一次：记下窗口 key，供文案区分「没买」vs「买过」 */
    markStockBought() {
      const w = this.myStockWindow
      if (w) this.stockBoughtAt = w.key
    },
    /** 一句提示（默认绿色，3 秒自动消失）。同时来两条就排队，一次只显示一条。 */
    flash(msg: string, variant: FlashVariant = 'ok') {
      this.notices.push({ id: Date.now() + this.notices.length, msg, variant })
      if (this.notices.length === 1) this.scheduleNotice()
    },
    /** 队首显示满 3 秒（金色仪式提示停久一点）后出队，接着显示下一条 */
    scheduleNotice() {
      clearTimeout(this.noticeTimer)
      const cur = this.notices[0]
      if (!cur) return
      this.noticeTimer = setTimeout(() => this.dismissNotice(), cur.variant === 'gold' ? 4500 : 3000)
    },
    dismissNotice() {
      this.notices.shift()
      this.scheduleNotice()
    },

    /** 从本批事件里挑出「没经我操作却改了我的账」的部分，推成可消回执。
     *  必须在换上新快照之前调用（见 connect 里的注释）。 */
    ingestEvents(events: { type: string; payload: Record<string, any> }[]) {
      const meId = this.session?.playerId
      if (!meId || !this.state) return
      const fresh = buildReceipts(events, this.state, meId, this.recentActionAt)
      if (fresh.length) this.receipts.push(...fresh)
      // 波及范围与回执用同一批事件、同一个「换快照前」的时机：被没收的资产名只在旧快照里有
      const impact = buildCardImpact(events, this.state)
      if (impact) this.lastImpact = impact
    },
    dismissReceipt(id: string) {
      this.receipts = this.receipts.filter(r => r.id !== id)
    },
    clearReceipts() {
      this.receipts = []
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
        this.recentActionAt[type] = Date.now()
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
    /** 选错卡撤销重选（FR-29）：找到自己最近一条未撤销的同卡 CARD_DRAWN 并本人更正。
     *  只负责撤销本身，撤销后要不要重开选卡器由调用方决定——
     *  「行动」页要重开 CardPicker，市场求购弹层里只需要让自己消失即可。 */
    async undoCardDraw(cardId: string): Promise<boolean> {
      const log = await this.fetchLog()
      const drawn = [...log].reverse().find(e =>
        e.type === 'CARD_DRAWN' && !e.revoked
        && e.actorId === this.session?.playerId && e.payload.card_id === cardId)
      if (!drawn) { this.flash('未找到抽卡记录，请在「日志」中处理', 'info'); return false }
      return this.act('PLAYER_CORRECT', { eventSeq: drawn.seq, reason: '选错卡重选' })
    },
  },
})

export function loadNickname(): string {
  try { return localStorage.getItem('cashflow.nickname') ?? '' } catch { return '' }
}

export function saveNickname(n: string) {
  try { localStorage.setItem('cashflow.nickname', n) } catch { /* 隐私模式下忽略 */ }
}

/** 快车道胜利条件之一：现金流量日收入比进场时多出 $50,000（说明书 P.5） */
export const FT_WIN_INCREMENT = 50_000

/** 快车道胜利进度（%）。别再散着写 `/500` 这种魔数。 */
export function ftWinProgress(f: { initial_income: number; current_income: number }): number {
  return Math.min(100, Math.round((f.current_income - f.initial_income) / FT_WIN_INCREMENT * 100))
}

export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return '0'
  return '$' + n.toLocaleString('en-US')
}
