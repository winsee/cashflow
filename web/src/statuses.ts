/** 玩家身上「跨回合持续」的状态：一处派生，牌桌 / 总览 / 座次条 / 本人徽章共用。
 *
 *  为什么要有这个文件：同一句「停赛中 · 还需跳过 N 轮」以前在五个地方各写一遍，
 *  措辞和配色已经开始打架（线下是红徽章、总览是灰徽章）。状态本身全是服务端算好、
 *  对全员下发的字段（`rooms.py serialize()` 不区分视角），这里**只负责怎么说**，
 *  一个数都不重算。
 *
 *  另有一条只能靠呈现解决的：`skip_turns` 是在 `_advance_turn()` 里静默递减并跳过的，
 *  那段代码跑在 apply/重放阶段，发不出事件——所以「谁被跳过了」没有事件可听，
 *  只能由状态本身说出来。
 */
import { fmt } from './store'
import type { Player } from './types'

export type StatusKey =
  | 'OUT' | 'BANKRUPTCY' | 'SKIP' | 'CHARITY' | 'CHARITY_FT'
  | 'FAST_TRACK' | 'INSTALLMENT' | 'CHILDREN'

export interface PlayerStatus {
  key: StatusKey
  /** 徽章前缀的 emoji */
  icon: string
  /** 徽章正文，如「停赛中 · 还需跳过 2 轮」 */
  label: string
  /** 一句「所以呢」，给 title 提示与总览页 */
  detail: string
  /** 直接对应既有 `.badge` 的三个修饰符，不新造颜色 */
  tone: '' | 'ft' | 'out'
  /** 主状态才进牌桌与座次条；次要状态（分期/孩子）只在总览露出 */
  major: boolean
}

/** 全部持续状态，按优先级从高到低。
 *
 *  「行动中」不在这里——那是回合状态（由 `currentPlayerId` 决定），不是这个人身上的状态。
 */
export function playerStatuses(p: Player): PlayerStatus[] {
  const out: PlayerStatus[] = []

  if (p.phase === 'OUT') {
    out.push({
      key: 'OUT', icon: '🚫', label: '已出局', tone: 'out', major: true,
      detail: '破产清算后仍资不抵债，资产已由银行收回',
    })
  }

  if (p.inBankruptcy) {
    out.push({
      key: 'BANKRUPTCY', icon: '⚠️', label: '破产清算中', tone: 'out', major: true,
      detail: '须按首期 50% 向银行变卖资产，直到月现金流转正',
    })
  }

  // 停赛**不写来源**：引擎只存 skip_turns，2 轮来自失业、3 轮来自破产复活，
  // 状态里没有这个信息，猜出来的来源迟早会错。
  if (p.skipTurns > 0) {
    out.push({
      key: 'SKIP', icon: '⏸️', label: `停赛中 · 还需跳过 ${p.skipTurns} 轮`, tone: '', major: true,
      detail: '轮到时自动跳过，其间不能掷骰、不能买卖',
    })
  }

  // 两条赛道的慈善是**两条**，不合并：老鼠赛跑 3 轮 1–2 粒（P.4），
  // 快车道永久 1–3 粒（P.6）。口径与引擎 `dice_limits()` 一致。
  if (p.charityTurns > 0) {
    out.push({
      key: 'CHARITY', icon: '💝', label: `慈善生效中 · 还剩 ${p.charityTurns} 轮`, tone: 'ft', major: true,
      detail: '这几轮可以自选掷 1 或 2 粒骰',
    })
  }
  if (p.phase === 'FAST_TRACK' && p.fasttrack.charity_forever) {
    out.push({
      key: 'CHARITY_FT', icon: '💝', label: '已行善 · 可掷 1–3 粒骰', tone: 'ft', major: true,
      detail: '快车道的慈善是永久的，每轮都能自选粒数',
    })
  }

  if (p.phase === 'FAST_TRACK') {
    out.push({
      key: 'FAST_TRACK', icon: '🏁', label: '快车道', tone: 'ft', major: false,
      detail: '已逃出老鼠赛跑',
    })
  }

  // mk-029：房子冻结、每月倒扣，收满 $100,000 才移交（design/06 §6.4）
  for (const r of p.installmentReceivables) {
    const left = r.duration_months - r.months_elapsed
    if (left <= 0) continue
    out.push({
      key: 'INSTALLMENT', icon: '📄', label: `分期收款中 · 还剩 ${left} 个月`, tone: '', major: false,
      detail: `「${r.name}」冻结中，每月 ${r.monthly_delta < 0 ? '−' : '+'}${fmt(Math.abs(r.monthly_delta))}`
        + `，收满 ${fmt(r.total_price)} 才移交`,
    })
  }

  if (p.childCount > 0) {
    out.push({
      key: 'CHILDREN', icon: '👶', label: `${p.childCount} 个孩子`, tone: '', major: false,
      detail: `每月孩子支出 ${fmt(p.derived.childExpense)}`,
    })
  }

  return out
}

/** 座次条上一个人只画得下一个记号，取优先级最高的主状态 */
export function majorStatus(p: Player): PlayerStatus | null {
  return playerStatuses(p).find(s => s.major) ?? null
}
