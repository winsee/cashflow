// 与服务端 serialize() 对应的类型
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
  fasttrack: { initial_income: number; current_income: number; businesses: { square_id: string; name: string; cashflow: number }[]; charity_forever: boolean }
  derived: Derived
}

export interface Prompt {
  id: string
  kind: 'MARKET_SELL' | 'TRANSFER_CONFIRM' | 'RESELL_CONFIRM'
  target_player_id: string
  payload: Record<string, any>
}

export interface RoomStateDto {
  roomCode: string
  status: RoomStatus
  settings: { max_players: number; name: string }
  players: Player[]
  turnOrder: string[]
  turnIndex: number
  turnCount: number
  turnSquareUsed: boolean
  turnPaydayUsed: boolean
  currentPlayerId: string | null
  activeCard: {
    card_id: string; deck: string; subtype: string; drawer_id: string; resolved: boolean
    /** 强制卡结算预览（服务端计算：应付金额/说明/是否条件豁免），机会卡等为 null */
    settlePreview?: { due: number; note: string; waived: boolean } | null
  } | null
  prompts: Prompt[]
  ftSoldSquares: string[]
  dreamPriceBumps: Record<string, number>
  winnerId: string | null
}

export interface CardDto {
  id: string
  deck: string
  subtype: string
  title: string
  data: Record<string, any>
}

export interface LogEntry {
  seq: number
  actorId: string | null
  actor: string | null
  type: string
  payload: Record<string, any>
  at: string
  revoked: boolean
}

export type RoomStatus = 'LOBBY' | 'SETUP' | 'PLAYING' | 'FINISHED' | 'CLOSED'

export interface RoomListItem {
  code: string
  name: string
  status: RoomStatus
  playerCount: number
  maxPlayers: number
  hasPassword: boolean
  createdAt: string
}

export interface RoomSeats {
  code: string
  name: string
  status: RoomStatus
  hasPassword: boolean
  maxPlayers: number
  players: { id: string; nickname: string; isHost: boolean; professionTitle: string }[]
}
