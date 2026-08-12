/** 演出层：把服务端刚产出的一批事件翻译成「界面此刻显示到哪一帧」。
 *
 *  入口和 receipts.ts 是同一个——WS `state.lastEvents`。这带来两条白得的性质：
 *  ① 重连首帧是 `type:'snapshot'`、不带 lastEvents，所以**重连不补播**任何动效；
 *  ② 权威状态在演出开始前就已经是最终值，演出播不播、播到哪，都不影响账。
 *
 *  设计稿 design/09 §5.1 的九拍在这里压成六种 step：掷骰、逐格、过站、落点脉冲、
 *  洗回提示、发牌（发牌那一拍自己内部还有飞出/翻转/定格/收牌四小段，由帘幕组件走 CSS）。
 */
import type { BoardDto, RoomStateDto } from './types'

export type Track = 'RAT_RACE' | 'FAST_TRACK'

export type StageStep =
  /** 拍 1–2：骰子翻滚 + 点数落定。终值就是服务端的点数，绝不本地预演。
   *  `settling` 是落定后**多停的那一拍**：骰子已经转到那一面，棋子还没起步。
   *  没有这一拍的话，点数刚出现棋子就走了，读数的时间要跟走格动画抢（第三轮试玩） */
  | { kind: 'dice'; ms: number; playerId: string; rolls: number[]; settling?: boolean }
  /** 拍 3：棋子逐格跳跃，一格一步 */
  | { kind: 'step'; ms: number; playerId: string; track: Track; index: number }
  /** 拍 4：过站结算——当事人一屏发薪帘幕，旁观者是格子橙光 + 金额飘字。
   *
   *  帘幕上那几个数**在排队时就从结算前的快照里焊死**（`buildStage` 的 `prev`），
   *  播放时不再读 store：权威状态在演出开始前就已经换成「这一切都发生完了」的样子，
   *  再去读就会拿到结算**后**的现金，「$2,100 → $2,980」的左边那一半就没了。
   *  收支结构不受 payday 影响（它只改 cash），所以 `prev` 的三行明细正是要显示的。 */
  | {
    kind: 'settle'; ms: number; playerId: string; index: number
    track: Track
    /** 总额：PAYDAY 是 cashflow×times，FT_PAYDAY 事件本身就是总额 */
    amount: number
    /** 结算了几个月 —— 一次移动可能连过两个结算格，那是两拍；这里是**单拍内**的月数 */
    times: number
    /** 单月净额（快车道 = current_income） */
    cashflow: number
    /** 以下三项仅老鼠赛跑有意义：total_income = salary + passive（formulas.py），所以三行加得平 */
    salary: number
    passive: number
    expenses: number
    cashBefore: number
    /** 这一批事件里当事人已经破产了：只留板上橙光，**不演发薪帘幕**——
     *  破产清算屏之前不该先来一场庆祝仪式。付得起的那几个月照样入账，所以拍还在。 */
    bankrupting?: boolean
  }
  /** 拍 5：落点脉冲 */
  | { kind: 'landing'; ms: number; index: number }
  /** 边界态：牌堆洗回，中央飘一行，不弹层 */
  | { kind: 'reshuffle'; ms: number; deck: string }
  /** 拍 6–9：全屏发牌翻牌（帘幕组件负责四小段的 CSS 时序） */
  | { kind: 'deal'; ms: number; deck: string; cardId: string; title: string; fromIndex: number }

export interface StageEvent {
  type: string
  payload: Record<string, any>
}

/** 逐拍时长（ms）。顿拍比时长重要，别为了「快」把节奏抹平（design/09 §5.1）。
 *
 *  v0.4 整体放慢一档（第三轮试玩：「骰子转太快、走格子唰一下就过去了」）。
 *  快慢节奏靠三样东西，不是靠把每一拍都拉长：
 *  ① 骰子**匀速快转** → 大幅缓出转到那一面（CSS `.cube` 的 0.62s ease-out）；
 *  ② 落定后**空一拍**（`diceStop`）让人读数，棋子才起步；
 *  ③ 走格是快的（每格 240ms），过站结算与落点才是慢的——重的地方停，轻的地方走。
 */
export const BEAT = {
  dice: 1300,       // 翻滚（匀速，服务端已经回来了但节奏要给足）
  diceStop: 650,    // 点数落定 + 读数的空拍，棋子还没起步
  step: 240,
  // 发薪帘幕：220ms 淡入 + 三行明细错相 360 + hero 打出 300 + 停 600 + 200 收起。
  // 比发牌（2050）短——发牌之后要读一张卡，发薪只有一个数。
  settle: 1700,
  landing: 620,
  reshuffle: 1600,
  // 帘幕是**仪式**不是阅读界面：卡面随后就落进抽屉，可以慢慢看。
  // 2.9s 试玩反馈「停太久」，收回到 2.05s（翻牌 0.95 + 定格 1.1）
  deal: 2050,
}

/** 从一批事件派生演出队列。与账目无关——这里只决定「先看到什么、后看到什么」。 */
export function buildStage(events: StageEvent[], prev: RoomStateDto | null): StageStep[] {
  const out: StageStep[] = []
  let track: Track = 'RAT_RACE'
  let mover = ''
  /** 这一批里谁走到了哪一格：发牌帘幕的起飞格取它（见 `landingIndexOf`） */
  const landedAt: Record<string, number> = {}
  // 过站结算的事件排在 PLAYER_MOVED 之前（服务端按「先结算再落位」产出），
  // 先攒着，等拿到 path 才知道该把橙光打在哪一格上。
  type Settle = Extract<StageStep, { kind: 'settle' }>
  const pending: Omit<Settle, 'kind' | 'ms' | 'index'>[] = []
  // 这一批里谁破产了：`BANKRUPTCY_STARTED` 排在 `PAYDAY` 之后，所以先扫一遍再逐条排队
  const bankrupted = new Set<string>(
    events.filter(e => e.type === 'BANKRUPTCY_STARTED')
      .map(e => e.payload?.player_id).filter(Boolean))
  // 一次移动可能连过**两个**结算格（慈善加骰之后真会发生，引擎测试已钉死会产出两条 PAYDAY）。
  // 第二张帘幕的「银行储蓄 旧 → 新」得接着第一张的结果往下走，不能两张都从批前那个数起算。
  const cashRun: Record<string, number> = {}
  const before = (playerId: string, amount: number) => {
    const f = beforeFigures(prev, playerId)
    const cashBefore = cashRun[playerId] ?? f.cashBefore
    cashRun[playerId] = cashBefore + amount
    return { ...f, cashBefore }
  }

  for (const ev of events) {
    const p = ev.payload ?? {}
    switch (ev.type) {
      case 'DICE_ROLLED':
        mover = p.player_id
        out.push({ kind: 'dice', ms: BEAT.dice, playerId: p.player_id, rolls: p.rolls ?? [] })
        // 落定后空一拍：骰子停稳、点数亮出来，棋子这时候还在原地
        out.push({
          kind: 'dice', ms: BEAT.diceStop, playerId: p.player_id,
          rolls: p.rolls ?? [], settling: true,
        })
        break
      case 'PAYDAY': {
        const times = p.times ?? 1
        const cf = p.cashflow ?? 0
        pending.push({
          playerId: p.player_id, track: 'RAT_RACE',
          amount: cf * times, times, cashflow: cf,
          ...before(p.player_id, cf * times),
          bankrupting: bankrupted.has(p.player_id),
        })
        break
      }
      case 'FT_PAYDAY': {
        const times = p.times ?? 1
        const amount = p.amount ?? 0
        pending.push({
          playerId: p.player_id, track: 'FAST_TRACK',
          // FT_PAYDAY 的 payload 本身就是总额（口径与 PAYDAY 不同），单次值要除回来
          amount, times, cashflow: times ? Math.round(amount / times) : amount,
          ...before(p.player_id, amount),
          bankrupting: bankrupted.has(p.player_id),
        })
        break
      }
      case 'PLAYER_MOVED': {
        track = p.track === 'FAST_TRACK' ? 'FAST_TRACK' : 'RAT_RACE'
        mover = p.player_id
        const path: number[] = p.path ?? []
        const settleAt = settlementIndexes(path, track, prev)
        for (const index of path) {
          out.push({ kind: 'step', ms: BEAT.step, playerId: p.player_id, track, index })
          if (settleAt.has(index) && pending.length) {
            out.push({ kind: 'settle', ms: BEAT.settle, index, ...pending.shift()! })
          }
        }
        if (path.length) {
          landedAt[p.player_id] = path[path.length - 1]
          out.push({ kind: 'landing', ms: BEAT.landing, index: path[path.length - 1] })
        }
        break
      }
      case 'DECK_RESHUFFLED':
        out.push({ kind: 'reshuffle', ms: BEAT.reshuffle, deck: p.deck })
        break
      case 'CARD_DRAWN':
        out.push({
          kind: 'deal', ms: BEAT.deal, deck: p.deck, cardId: p.card_id,
          title: p.title ?? '', fromIndex: landingIndexOf(prev, p.player_id ?? mover, landedAt),
        })
        break
    }
  }
  return out
}

/** 帘幕上那四个数：一律取**结算之前**那一份快照。
 *
 *  拿不到快照（首帧、或当事人刚进房）就全给 0 —— 帘幕会因此退化成只报总额的一版，
 *  这比显示一组算不平的数字好。收支结构不受 payday 影响（`_a_payday` 只改 cash），
 *  所以「结算前」的三行明细和结算后是同一组数，唯独现金必须是旧的。
 */
function beforeFigures(prev: RoomStateDto | null, playerId: string) {
  const pl = prev?.players.find(x => x.id === playerId)
  return {
    salary: pl?.salary ?? 0,
    passive: pl?.derived.passiveIncome ?? 0,
    expenses: pl?.derived.totalExpenses ?? 0,
    cashBefore: pl?.cash ?? 0,
  }
}

/** 走过的这几格里哪些是结算格——只用来决定橙光打在哪一格，算钱一律以事件为准。 */
function settlementIndexes(path: number[], track: Track, prev: RoomStateDto | null): Set<number> {
  const out = new Set<number>()
  const board = boardCache
  if (!board) return new Set(path)     // 棋盘还没拉到：宁可每格都亮，也别一格不亮
  for (const index of path) {
    if (track === 'FAST_TRACK') {
      if (board.fastTrack.squares[index - 1] === 'ft-s-cashflow-day') out.add(index)
    } else if (board.ratRace.squares[index - 1]?.type === 'PAYDAY') {
      out.add(index)
    }
  }
  return out
}

/** 牌背从哪一格飞出来：**抽卡人此刻站的那一格**（拿不到就从屏心飞，fromIndex = 0）。
 *
 *  两条路径的落点不在同一个地方，都要认：
 *  ① 掷骰那一批里连着抽卡（停在额外支出/市场风云格）——落点在这批的 `PLAYER_MOVED.path` 末尾，
 *     `prev` 里那份还是**掷骰之前**的位置，用它会从上一格飞出来；
 *  ② 「你停在机会格 → 点小生意/大生意」那一批里只有 `CARD_DRAWN`，一个移动事件都没有，
 *     这时才该回 `prev` 取位置。
 *  赛道也取玩家自己的 `phase`，不取批内那个由 `PLAYER_MOVED` 才置位的变量——②那条路径上它没被置过。 */
function landingIndexOf(
  prev: RoomStateDto | null, playerId: string, landedAt: Record<string, number>,
): number {
  if (!playerId) return 0
  if (landedAt[playerId]) return landedAt[playerId]
  const pl = prev?.players.find(x => x.id === playerId)
  if (!pl) return 0
  return pl.phase === 'FAST_TRACK' ? pl.ftPosition : pl.rrPosition
}

/** 棋盘数据在演出层里只用来判「哪一格是结算格」，由 store 拉到后塞进来，省得逐拍再取一次。 */
let boardCache: BoardDto | null = null
export function setStageBoard(board: BoardDto | null) {
  boardCache = board
}

/** 本机的「跳过动画」偏好：存 localStorage、不进房间状态（它是这台设备的事，不是房间的事实）。 */
const SKIP_KEY = 'cashflow.skipAnim'

export function loadSkipAnim(): boolean {
  try { return localStorage.getItem(SKIP_KEY) === '1' } catch { return false }
}

export function saveSkipAnim(v: boolean) {
  try { localStorage.setItem(SKIP_KEY, v ? '1' : '0') } catch { /* 隐私模式下忽略 */ }
}

/** 系统级「减少动态效果」：命中时整条序列压成一次淡入，与设置开关同一条出口。 */
export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches
}
