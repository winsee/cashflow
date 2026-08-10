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
  /** 拍 4：过站结算——格子脉冲橙光 + 金额飘字 */
  | { kind: 'settle'; ms: number; playerId: string; index: number; amount: number }
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
  settle: 1150,
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
  // 过站结算的事件排在 PLAYER_MOVED 之前（服务端按「先结算再落位」产出），
  // 先攒着，等拿到 path 才知道该把橙光打在哪一格上。
  const pending: { playerId: string; amount: number }[] = []

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
      case 'PAYDAY':
        pending.push({ playerId: p.player_id, amount: (p.cashflow ?? 0) * (p.times ?? 1) })
        break
      case 'FT_PAYDAY':
        pending.push({ playerId: p.player_id, amount: p.amount ?? 0 })
        break
      case 'PLAYER_MOVED': {
        track = p.track === 'FAST_TRACK' ? 'FAST_TRACK' : 'RAT_RACE'
        mover = p.player_id
        const path: number[] = p.path ?? []
        const settleAt = settlementIndexes(path, track, prev)
        for (const index of path) {
          out.push({ kind: 'step', ms: BEAT.step, playerId: p.player_id, track, index })
          if (settleAt.has(index) && pending.length) {
            const s = pending.shift()!
            out.push({ kind: 'settle', ms: BEAT.settle, playerId: p.player_id, index, amount: s.amount })
          }
        }
        if (path.length) out.push({ kind: 'landing', ms: BEAT.landing, index: path[path.length - 1] })
        break
      }
      case 'DECK_RESHUFFLED':
        out.push({ kind: 'reshuffle', ms: BEAT.reshuffle, deck: p.deck })
        break
      case 'CARD_DRAWN':
        out.push({
          kind: 'deal', ms: BEAT.deal, deck: p.deck, cardId: p.card_id,
          title: p.title ?? '', fromIndex: landingIndexOf(prev, mover, track),
        })
        break
    }
  }
  return out
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

/** 牌背从哪一格飞出来：抽卡人此刻站的那一格（拿不到就从屏心飞，fromIndex = 0） */
function landingIndexOf(prev: RoomStateDto | null, playerId: string, track: Track): number {
  const pl = prev?.players.find(x => x.id === playerId)
  if (!pl) return 0
  return track === 'FAST_TRACK' ? pl.ftPosition : pl.rrPosition
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
