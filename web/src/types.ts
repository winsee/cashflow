// 与服务端 serialize() 对应的类型

/** 对局模式：建房时选定，此后不可更改（design/09 §1） */
export type GameMode = 'OFFLINE_ASSIST' | 'ONLINE'
export interface Derived {
  interestIncome: number
  dividendIncome: number
  realEstateIncome: number
  businessIncome: number
  installmentCashflow: number
  passiveIncome: number
  totalIncome: number
  childExpense: number
  bankLoanExpense: number
  cardMonthlyExpenses: number
  totalExpenses: number
  monthlyCashflow: number
  canEnterFasttrack: boolean
}

export interface OwnedAssetDto {
  id: string
  asset_type: string
  name: string
  cost: number
  down_payment: number
  mortgage: number
  cashflow: number
  // v3 规格字段：决定求购卡按套/按间/按枚计价（design/06 §3.2）
  rooms?: number | null
  units?: number | null
  quantity?: number | null
  business_kind?: string | null
  income_category?: string | null
}

export interface Player {
  id: string
  nickname: string
  seat: number
  isHost: boolean
  phase: 'RAT_RACE' | 'FAST_TRACK' | 'OUT'
  professionId: string | null
  professionTitle: string
  cash: number
  childCount: number
  charityTurns: number
  skipTurns: number
  dreamId: string | null
  inBankruptcy: boolean
  /** 棋盘位置（纯线上）：1-based 格索引，0 = 起点/入口标记本身，不是格子 */
  rrPosition: number
  ftPosition: number
  salary: number
  taxes: number
  mortgagePayment: number
  schoolLoanPayment: number
  carLoanPayment: number
  creditCardPayment: number
  extraExpenses: number
  otherExpenses: number
  perChildExpense: number
  interestIncome: number
  stocks: { symbol: string; shares: number; cost_per_share: number; dividend_per_share: number; income_category?: string }[]
  realEstates: OwnedAssetDto[]
  businesses: OwnedAssetDto[]
  extraLiabilities: { id: string; name: string; amount: number; monthly: number }[]
  installmentReceivables: { id: string; card_id: string; name: string; asset_id: string; total_price: number; monthly_delta: number; duration_months: number; months_elapsed: number }[]
  liabilities: { mortgage: number; school_loan: number; car_loan: number; credit_card: number; extra: number; bank_loan: number }
  fasttrack: { initial_income: number; current_income: number; businesses: { square_id: string; name: string; cashflow: number }[]; charity_forever: boolean; entered_turn: number | null }
  derived: Derived
}

export interface Prompt {
  id: string
  kind: 'MARKET_SELL' | 'TRANSFER_CONFIRM' | 'RESELL_CONFIRM'
  target_player_id: string
  payload: Record<string, any>
}

/** 落点：「现在轮到你处理这一格」（纯线上，design/09 §4.3） */
export interface Landing {
  track: 'RAT_RACE' | 'FAST_TRACK'
  index: number
  /** 内圈七种 type，或快车道 FT_BUSINESS / FT_DREAM / FT_CHARITY / FT_PAYDAY / FT_TAX_AUDIT / FT_DIVORCE / FT_LAWSUIT */
  type: string
  ref_id: string | null
  resolved: boolean
  note: string
}

export interface RoomStateDto {
  roomCode: string
  status: RoomStatus
  mode: GameMode
  settings: { max_players: number; name: string }
  players: Player[]
  turnOrder: string[]
  turnIndex: number
  turnCount: number
  turnSquareUsed: boolean
  turnPaydayUsed: boolean
  /** 本回合已掷过骰（纯线上） */
  turnDiceUsed: boolean
  landing: Landing | null
  /** 各副牌的余量：只有张数，绝无牌序（服务端出口脱敏） */
  decks: Record<string, { remaining: number; discarded: number }>
  currentPlayerId: string | null
  activeCard: {
    card_id: string; deck: string; subtype: string; drawer_id: string; resolved: boolean
    /** 强制卡结算预览（服务端计算：应付金额/说明/是否条件豁免），机会卡等为 null */
    settlePreview?: { due: number; note: string; waived: boolean } | null
    /** 股票窗口摘要（服务端派生），非股票卡为 null。窗口活到回合结束，与 resolved 无关 */
    stockOffer?: { symbol: string; price: number; buyerScope: 'DRAWER_ONLY' | 'ALL' } | null
  } | null
  prompts: Prompt[]
  ftSoldSquares: string[]
  dreamPriceBumps: Record<string, number>
  winnerId: string | null
}

/** 卡面原文（卡库双轨的 raw 一侧）：逐字转录，用于渲染「和手里那张一样」的卡面。
 *  牌堆卡有 body/fields/notes；职业卡另有 subtitle/groups。数值一律走 data，不从这里取。 */
export interface CardRaw {
  title?: string
  subtitle?: string
  body?: string[]
  fields?: { label: string; value: string }[]
  groups?: { name: string; rows: { label: string; value: string }[] }[]
  notes?: string[]
}

export interface CardDto {
  id: string
  deck: string
  subtype: string
  title: string
  data: Record<string, any>
  raw?: CardRaw
}

/** 快车道棋盘外环的两种格子（/api/board/fasttrack） */
export interface FtBusiness {
  id: string
  name: string
  down_payment: number
  cashflow: number
  dice_rule: { threshold: number; successCashflow?: number; lumpSum?: number } | null
}

export interface FtDream {
  id: string
  name: string
  price: number
}

/** 内圈一格（/api/board/ratrace）：显示名由 type 推出，服务端一并下发省得前端再抄一份 */
export interface RrSquare {
  id: string
  type: string
  name: string
}

/** 两条轨道一次取全（/api/board） */
export interface BoardDto {
  ratRace: { squares: RrSquare[] }
  fastTrack: {
    businesses: FtBusiness[]
    dreams: FtDream[]
    charityCost: number
    /** 48 格排布，下标 0 = 第 1 格；元素是 ft-b-* / ft-d-* / ft-s-* */
    squares: string[]
  }
}

export interface LogEntry {
  seq: number
  /** 该事件发生在第几轮（服务端重放给出）；0 = 开局前 */
  turn: number
  actorId: string | null
  actor: string | null
  type: string
  payload: Record<string, any>
  at: string
  revoked: boolean
  /** 被谁撤销的：房主撤销 / 本人更正。撤销画在被撤销那一行上，不另起一行 */
  revokedBy: 'host' | 'self' | null
  revokedByActor: string | null
}

export type RoomStatus = 'LOBBY' | 'SETUP' | 'PLAYING' | 'FINISHED' | 'CLOSED'

export interface RoomListItem {
  code: string
  name: string
  status: RoomStatus
  mode: GameMode
  playerCount: number
  maxPlayers: number
  hasPassword: boolean
  /** 当前握着 WebSocket 的人数；0 = 空壳房间，任何人可删 */
  onlineCount: number
  /** 第几轮；0 = 尚未开局 */
  turnCount: number
  /** 轮到谁的昵称；未开局为 null */
  currentPlayer: string | null
  createdAt: string
}

export interface Seat {
  id: string
  nickname: string
  isHost: boolean
  professionTitle: string
  /** 该座位现在有没有设备连着：接管在线座位会把原设备踢下线 */
  online: boolean
}

export interface RoomSeats {
  code: string
  name: string
  status: RoomStatus
  mode: GameMode
  hasPassword: boolean
  maxPlayers: number
  onlineCount: number
  players: Seat[]
}
