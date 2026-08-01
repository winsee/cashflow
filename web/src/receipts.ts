/** 被动回执：有些事在你没操作的时候改了你的账，它们必须被看见。
 *
 *  数据来源是 WS `state` 消息里已有的 `lastEvents`（服务端本来就下发了本批事件），
 *  **不需要改协议**。事件本身已带受影响玩家（`CASHFLOW_MODIFIED.targets`、
 *  `ASSETS_SURRENDERED.player_id` 等），这里只做「与我有关吗」和「怎么讲给我听」。
 *
 *  每条回执答三件事：发生了什么、为什么、对我的账有什么影响。
 *  一次性扣款和月现金流变化用「/月」区分，不能混。
 */
import type { RoomStateDto } from './types'

export interface Receipt {
  id: string
  /** 决定左侧色条：红=扣款 绿=进账 青=中性信息 金=梦想相关 灰=撤销重算 */
  tone: 'neg' | 'pos' | 'info' | 'gold' | 'neutral'
  icon: string
  /** 发生了什么 */
  title: string
  /** 为什么 */
  why: string
  /** 对我的账什么影响：文本已带正负号与单位 */
  amount?: string
}

/** 一张卡的波及范围：影响到谁、各变多少。抽卡人要向同桌宣读的就是这些数。
 *
 *  同样只从 `state.lastEvents` 派生——`CASHFLOW_MODIFIED.targets` 与
 *  `ASSETS_SURRENDERED.asset_ids` 已经是引擎算好的权威结果，客户端只做展示，
 *  绝不自己重算 `_asset_matches`（那就成了客户端算账）。
 */
export interface CardImpact {
  /** 卡 + 轮次；换一张卡或换一轮即失效，见 store 的 cardImpact getter */
  key: string
  /** 逐人一行：「小雨 · 2室公寓 −$50/月」 */
  rows: { playerId: string; nickname: string; detail: string; amount: string; tone: 'pos' | 'neg' }[]
  /** 求购卡通知到的人（按玩家去重）：抽卡人据此知道自己在等谁 */
  notified: { playerId: string; nickname: string; assets: number }[]
}

/**
 * @param events 本批事件（WS `state.lastEvents`）
 * @param prev   **换上新快照之前**的房间状态：被没收的资产只在这里还查得到名字
 */
export function buildCardImpact(
  events: { type: string; payload: Record<string, any> }[],
  prev: RoomStateDto,
): CardImpact | null {
  const nickOf = (id: string) => prev.players.find(p => p.id === id)?.nickname ?? '玩家'
  const assetsOf = (id: string) => {
    const p = prev.players.find(x => x.id === id)
    return p ? [...p.realEstates, ...p.businesses] : []
  }
  let cardId = ''
  const rows: CardImpact['rows'] = []
  const notified: CardImpact['notified'] = []

  for (const ev of events) {
    const p = ev.payload ?? {}
    switch (ev.type) {
      case 'MARKET_PROMPTED': {
        cardId = p.card_id ?? cardId
        const hit = notified.find(n => n.playerId === p.player_id)
        if (hit) hit.assets++
        else notified.push({ playerId: p.player_id, nickname: nickOf(p.player_id), assets: 1 })
        break
      }
      case 'CASHFLOW_MODIFIED': {
        cardId = p.card_id ?? cardId
        const targets: Record<string, string[]> = p.targets ?? {}
        for (const [pid, ids] of Object.entries(targets)) {
          const own = assetsOf(pid)
          const names = ids.map(id => own.find(a => a.id === id)?.name).filter(Boolean)
          rows.push({
            playerId: pid, nickname: nickOf(pid),
            detail: names.join('、') || `${ids.length} 项资产`,
            amount: signed(p.delta * ids.length, true),
            tone: p.delta >= 0 ? 'pos' : 'neg',
          })
        }
        break
      }
      case 'ASSETS_SURRENDERED': {
        cardId = p.card_id ?? cardId
        const own = assetsOf(p.player_id)
        const hit = (p.asset_ids ?? []).map((id: string) => own.find(a => a.id === id)).filter(Boolean)
        const lost = hit.reduce((a: number, x: any) => a + x.cashflow, 0)
        rows.push({
          playerId: p.player_id, nickname: nickOf(p.player_id),
          detail: `${hit.map((x: any) => x.name).join('、') || '资产'} 被收回`,
          amount: lost ? signed(-lost, true) : '—',
          tone: 'neg',
        })
        break
      }
    }
  }
  if (!cardId || (!rows.length && !notified.length)) return null
  return { key: `${cardId}@${prev.turnCount}`, rows, notified }
}

/** 事件类型 → 若这事是我自己发起的，我刚才会送出的行动类型。
 *  在途/刚发过就说明是主动操作，不该再推「刚刚发生在你身上」。 */
const SELF_ACTION: Record<string, string[]> = {
  EXPENSE_EVENT_PAID: ['CARD_DECISION'],
  DOODAD_PAID: ['CARD_DECISION'],
  SHARES_ADJUSTED: ['CARD_DECISION'],
  CASHFLOW_MODIFIED: ['DRAW_CARD', 'CARD_DECISION'],
  ASSETS_SURRENDERED: ['DRAW_CARD', 'CARD_DECISION'],
  HOST_ADJUSTED: ['HOST_ADJUST'],
  TRANSFER_COMPLETED: ['TRANSFER_CONFIRM'],
  HOST_REVERTED: ['HOST_REVERT'],
  PLAYER_CORRECTED: ['PLAYER_CORRECT', 'HOST_REVERT'],
}

/** 刚发出的行动在这个窗口内不再算「被动」；服务端往返一般远快于此 */
const SELF_WINDOW_MS = 6000

function money(n: number): string {
  return '$' + Math.abs(n).toLocaleString('en-US')
}
function signed(n: number, per = false): string {
  return (n >= 0 ? '+' : '−') + money(n) + (per ? '/月' : '')
}

let seq = 0
function make(r: Omit<Receipt, 'id'>): Receipt {
  return { ...r, id: `rc-${Date.now()}-${seq++}` }
}

/**
 * @param events    本批事件（WS `state.lastEvents`）
 * @param prev      **换上新快照之前**的房间状态：被没收的资产只在这里还查得到名字
 * @param meId      我的玩家 id
 * @param recentAt  我最近发出的行动类型 → 时间戳
 */
export function buildReceipts(
  events: { type: string; payload: Record<string, any> }[],
  prev: RoomStateDto,
  meId: string,
  recentAt: Record<string, number>,
): Receipt[] {
  const me = prev.players.find(p => p.id === meId)
  if (!me) return []
  const now = Date.now()
  const nickOf = (id: string) => prev.players.find(p => p.id === id)?.nickname ?? '有人'
  const selfInitiated = (type: string) =>
    (SELF_ACTION[type] ?? []).some(a => now - (recentAt[a] ?? 0) < SELF_WINDOW_MS)

  const out: Receipt[] = []
  for (const ev of events) {
    const p = ev.payload ?? {}
    if (selfInitiated(ev.type)) continue

    switch (ev.type) {
      // ① 支出卡把钱从我账上扣走（房主代结算、或将来出现的全员支出卡）
      case 'EXPENSE_EVENT_PAID':
      case 'DOODAD_PAID': {
        if (p.player_id !== meId || !p.amount) break
        out.push(make({
          tone: 'neg', icon: '📉',
          title: `额外支出 · ${p.title ?? '卡牌结算'}`,
          why: '这张卡的结算已记到你名下',
          amount: signed(-p.amount),
        }))
        break
      }

      // ② 拆股 / 并股：总值不变，但持仓与成本都换算过了
      case 'SHARES_ADJUSTED': {
        if (!me.stocks.some(s => s.symbol === p.symbol)) break
        const merge = p.ratio_num > p.ratio_den
        out.push(make({
          tone: 'info', icon: '📈',
          title: `${p.symbol} ${merge ? '并股' : '拆股'} ${p.ratio_num}:${p.ratio_den}`,
          why: '持仓与成本同步换算，总值不变',
        }))
        break
      }

      // ③ 现金流调整：不转移资产，只改我名下资产条目的月现金流
      case 'CASHFLOW_MODIFIED': {
        const ids: string[] = p.targets?.[meId] ?? []
        if (!ids.length) break
        const own = [...me.realEstates, ...me.businesses]
        const names = ids.map(id => own.find(a => a.id === id)?.name).filter(Boolean)
        out.push(make({
          tone: p.delta >= 0 ? 'pos' : 'neg', icon: p.delta >= 0 ? '📈' : '📉',
          title: `「${names.join('、') || '你的资产'}」月现金流变了`,
          why: '市场风云卡对这类资产统一调整',
          amount: signed(p.delta * ids.length, true),
        }))
        break
      }

      // ④ 强制没收：资产直接交回银行，对应月收入一并消失
      case 'ASSETS_SURRENDERED': {
        if (p.player_id !== meId) break
        const ids: string[] = p.asset_ids ?? []
        const own = [...me.realEstates, ...me.businesses]
        const hit = ids.map(id => own.find(a => a.id === id)).filter(Boolean) as typeof own
        const lost = hit.reduce((a, x) => a + x.cashflow, 0)
        out.push(make({
          tone: 'neg', icon: '🏚️',
          title: `「${hit.map(x => x.name).join('、') || '你的资产'}」被没收`,
          why: '市场风云卡：该类资产强制交回银行',
          amount: lost ? signed(-lost, true) : undefined,
        }))
        break
      }

      // ⑤ 房主撤销 / 本人更正：账已重算，日志留划线痕迹
      case 'HOST_REVERTED':
      case 'PLAYER_CORRECTED': {
        out.push(make({
          tone: 'neutral', icon: '↩️',
          title: ev.type === 'HOST_REVERTED' ? '房主撤销了一条记录' : '有人更正了一条记录',
          why: `${p.reason || '账目已按撤销后的事件流重算'}`,
        }))
        break
      }

      // ⑥ 我的梦想被加价：目标一下变远了多少，必须立刻看见
      case 'FT_DREAM_DOUBLED': {
        if (p.square_id !== me.dreamId) break
        // 加价按原价再叠一倍：prev 里的次数是这次之前的，所以新价 = 原价 ×(次数+2)
        const before = prev.dreamPriceBumps?.[p.square_id] ?? 0
        out.push(make({
          tone: 'gold', icon: '💔',
          title: '你的梦想被加价了',
          why: `${nickOf(p.player_id)}双倍购买「${p.name}」，你要花更多钱才能买下`,
          amount: `现价 ${money((p.base_price ?? 0) * (before + 2))}`,
        }))
        break
      }

      // 房主直接调账：不是任何卡的结果，更该说清楚
      case 'HOST_ADJUSTED': {
        if (p.player_id !== meId) break
        out.push(make({
          tone: p.delta >= 0 ? 'pos' : 'neg', icon: '🛠️',
          title: '房主调整了你的现金',
          why: p.reason || '房主在总览页做的手工修正',
          amount: signed(p.delta),
        }))
        break
      }

      // 我发起的转账被对方收下：扣款发生在对方点头的那一刻，对我是被动的
      case 'TRANSFER_COMPLETED': {
        if (p.from_player_id === meId) {
          out.push(make({
            tone: 'neg', icon: '🤝',
            title: `${nickOf(p.to_player_id)} 收下了你的转账`,
            why: p.reason || '玩家间转账，对方确认后才扣款',
            amount: signed(-p.amount),
          }))
        } else if (p.to_player_id === meId) {
          out.push(make({
            tone: 'pos', icon: '🤝',
            title: `收到 ${nickOf(p.from_player_id)} 的转账`,
            why: p.reason || '玩家间转账',
            amount: signed(p.amount),
          }))
        }
        break
      }
    }
  }
  return out
}
