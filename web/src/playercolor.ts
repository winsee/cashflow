/** 玩家主题色：**唯一权威**（design/09 §3.7）。
 *
 *  从前色相是 `(seat * 67 + 120) % 360` 这条公式，在 `BoardView` 与 `OnlineRoomView` 里
 *  各写了一遍，饱和度与明度还按用途各写各的（棋子 45%/88%、梦想圆点 55%/62%）——
 *  于是同一个人在两个地方是两种颜色，看着不像同一个人；而头像圈与座次条压根不参与，
 *  一律主色绿，所有人长得一模一样。
 *
 *  换成一张手挑的表：6 个座位（`max_players` 上限 6），每色三档。
 *
 *  ## 两条硬约束
 *
 *  **① 玩家色只上「人和人的道具」，永不上数字或状态。**
 *  正数永远绿（`--pos`）、扣款永远红（`--neg`），这条规矩比玩家色老一个版本，一步都不能让。
 *  金箔肤的 `--gold`（#B4832A）也不许被撞——色板里最接近的是赭橙，明度已经压到金色之下。
 *  不着色的清单：金额、进度条、语义色、三种卡面、状态徽章 tone、`.seat-pay` 角标。
 *
 *  **② 颜色永远不是唯一线索。** 用到玩家色的每一处都同时带昵称首字或图标形状——
 *  色盲玩家靠字读人、靠形状读道具（奶酪是楔形、金币是圆片）。
 *
 *  ## 排序
 *
 *  按「相邻座位对比最大」排：2 人局拿到靛蓝 + 赭橙（冷暖对冲），3 人局再加青。
 *  绿、红、金黄三个色相整段划给了语义色与阶段色，所以这里只在蓝／青／紫／品红／赭／石板里选。
 */

export interface PlayerColor {
  /** 中文色名，进 aria-label 与详情卡 */
  name: string
  /** 奶酪 / 金币；座次条当前位的那圈光晕 */
  solid: string
  /** 棋子底、头像圈底 */
  soft: string
  /** 底上的昵称首字。与 soft 的对比一律 ≥ 7:1（AAA）——那个字只有 9~10px */
  ink: string
}

export const PLAYER_COLORS: readonly PlayerColor[] = [
  { name: '靛蓝', solid: '#3457C7', soft: '#DEE4F8', ink: '#1F3583' },
  { name: '赭橙', solid: '#C0621C', soft: '#FAE3D0', ink: '#7A3A0C' },
  { name: '青',   solid: '#0F8FA8', soft: '#D6EDF3', ink: '#0A5A6B' },
  { name: '品红', solid: '#B4308A', soft: '#F8DBEF', ink: '#721956' },
  { name: '石板', solid: '#46586B', soft: '#DFE5EC', ink: '#293441' },
  { name: '紫',   solid: '#7B3FB5', soft: '#E9DEF6', ink: '#4C2277' },
]

/** 座位序号 → 颜色。越界取模，**绝不返回 undefined**：颜色是呈现层的兜底，不该让调用方判空。
 *
 *  `seat` 在 `SET_TURN_ORDER` 时会被引擎重排成 `0..n-1`（rematch 也会），
 *  所以颜色可能在**准备阶段变一次**，开局后恒定。 */
export function seatColor(seat: number): PlayerColor {
  const i = Number.isFinite(seat) ? Math.abs(Math.trunc(seat)) : 0
  return PLAYER_COLORS[i % PLAYER_COLORS.length]
}

export function playerColor(p?: { seat: number } | null): PlayerColor | null {
  return p ? seatColor(p.seat) : null
}

/** 把三档挂成内联自定义属性，CSS 侧统一写 `var(--pc-soft, var(--brand-soft))`。
 *
 *  这一层是关键：让 `.avatar-lg` / `.seat-dot` 这些**两模式共用**的类保持
 *  「没有玩家时退回主色」的老行为，改动就不会溢出到任何没传玩家的调用点
 *  （大厅那枚昵称 chip 就是——那里还没有房间，也就没有座位，硬编一个色等于凭空发明一条信息）。 */
export function colorVars(p?: { seat: number } | null): Record<string, string> {
  const c = playerColor(p)
  return c ? { '--pc-solid': c.solid, '--pc-soft': c.soft, '--pc-ink': c.ink } : {}
}
