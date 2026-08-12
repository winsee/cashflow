/** 放射轮盘的几何：**一处定义**，棋盘渲染与走格动画共用（design/09 §8）。
 *
 *  改半径不会漏掉哪一边——格子扇环、标签、棋子、起点三角全部由这几个常量算出来。
 *  环按传入的格数自己重新分角，所以格数与顺序改了不用动一行呈现代码。
 */

/** 棋盘上的一格。棋盘完全由这个数组驱动——格数与顺序变了不用改一行呈现代码。 */
export interface BoardSquare {
  /** 1-based 格索引（0 留给起点/入口标记，那不是格子） */
  index: number
  /** 内圈七种 type，或快车道 FT_BUSINESS / FT_DREAM / FT_PAYDAY / FT_CHARITY / FT_* */
  type: string
  /** 快车道的 ft-b-* / ft-d-* / ft-s-*；内圈为 rr-XX */
  ref: string
  /** 格面文字；空串 = 不写字（12 个机会格与全部快车道格） */
  label: string
  /** 褪成底色：已被买断的绿格 */
  faded?: boolean
  /** 中径上插一枚玩家色圆点：已被认领的梦想（就是实体那块奶酪） */
  dot?: string
}

/** SVG viewBox 边长（正方形），随板宽等比缩放 */
export const V = 320
export const C = V / 2

export interface Ring {
  /** 外径 / 内径 / 中径（标签与棋子的基准） */
  R1: number
  R0: number
  RMID: number
  /** 格与格之间的缝（度） */
  GAP: number
}

/** 内圈 24 格环宽 40px，快车道 48 格环收窄一半、中心因此更大，正好摞下两粒骰。 */
export const RINGS: Record<'RAT_RACE' | 'FAST_TRACK', Ring> = {
  RAT_RACE: { R1: 134, R0: 94, RMID: 114, GAP: 1.5 },
  FAST_TRACK: { R1: 140, R0: 114, RMID: 127, GAP: 0.9 },
}

/** 极坐标 → 直角坐标。0° 指向 12 点，顺时针为正（和棋盘的走向一致）。 */
export function polar(r: number, deg: number): [number, number] {
  const rad = (deg - 90) * Math.PI / 180
  return [C + r * Math.cos(rad), C + r * Math.sin(rad)]
}

/** 第 i 格（0-based）的中心角 */
export function slotAngle(i: number, n: number): number {
  return (i + 0.5) * (360 / n)
}

/** 第 i 格（0-based）的扇环路径 */
export function sectorPath(i: number, n: number, ring: Ring): string {
  const per = 360 / n
  const a0 = i * per + ring.GAP / 2
  const a1 = (i + 1) * per - ring.GAP / 2
  const [x0o, y0o] = polar(ring.R1, a0)
  const [x1o, y1o] = polar(ring.R1, a1)
  const [x1i, y1i] = polar(ring.R0, a1)
  const [x0i, y0i] = polar(ring.R0, a0)
  const large = a1 - a0 > 180 ? 1 : 0
  return `M${x0o} ${y0o}A${ring.R1} ${ring.R1} 0 ${large} 1 ${x1o} ${y1o}`
    + `L${x1i} ${y1i}A${ring.R0} ${ring.R0} 0 ${large} 0 ${x0i} ${y0i}Z`
}

/** 棋子/标签落点：第 index 格（**1-based**）的中径坐标。
 *  `lane` 是同格多子的径向错开档（0 居中、±1 一内一外）。 */
export function slotPoint(index: number, n: number, ring: Ring, lane = 0): [number, number] {
  const spread = (ring.R1 - ring.R0) * 0.27
  return polar(ring.RMID + lane * spread, slotAngle(index - 1, n))
}

/** 第 index 格（**1-based**）在**视口坐标**里的外接矩形——发牌帘幕的「飞入」拍要拿它当起点
 *  （design/09 §5.1 拍 6：牌背**从格子位置**飞向屏心）。
 *
 *  viewBox 是 `0 0 V V` 的正方形、随板宽等比缩放，所以一次线性换算就够，不必动 `getScreenCTM()`。
 *  边长取一格的弧宽（`2π·RMID/n`），同一把尺子换算过去——飞入的起点大小该由格子说了算。
 *
 *  **量不到就返回 `null`**（棋盘在 full 档被压成一条、或还没挂上）：调用方据此退回不带锚点的
 *  老行为，而不是拿一个 0×0 的矩形去算出满屏乱飞的位移。 */
export function squareViewportRect(
  svg: SVGSVGElement | null | undefined, index: number, n: number, ring: Ring,
): DOMRect | null {
  if (!svg || index < 1 || index > n) return null
  const box = svg.getBoundingClientRect()
  if (box.width < 1 || box.height < 1) return null
  const k = box.width / V
  const [x, y] = slotPoint(index, n, ring)
  const side = (2 * Math.PI * ring.RMID / n) * k
  return new DOMRect(box.left + x * k - side / 2, box.top + y * k - side / 2, side, side)
}

/** 起点/入口标记的角度：**它不是格子**（位置 0），落在最后一格与第 1 格之间的接缝上，
 *  也就是 12 点方向——第 1 格从这里开始数。 */
export const MARKER_ANGLE = 0

/** 环外标注的半径：按 `R1 + 文字半径 ≤ V/2 − 一行字高` 反算，确保不被 viewBox 裁掉。
 *  （「开始」「在此进入」这两处最容易落到 viewBox 之外被裁掉半个字。） */
export function outerLabelRadius(ring: Ring, lineHeight = 14): number {
  return Math.min(ring.R1 + 13, V / 2 - lineHeight)
}

/** 还没上路的棋子（位置 0）的落点：**环外**那圈，就是「开始」二字原本的位置。
 *
 *  位置 0 不是格子、没有效果，掷出 1 才走到第 1 格——把棋子画在环的中径上等于宣称
 *  「大家都站在第 1 格」，顺带压住 12 点方向那一格的标签（design/09 §3.3.1）。
 *  环外只有一层的空间，所以有人在起点时那两个字让位；四枚棋子挤在起跑线上
 *  本身就说明了这里是起点，第一次掷骰后文字自动回来。 */
export function markerLanePoint(ring: Ring): [number, number] {
  return polar(outerLabelRadius(ring), MARKER_ANGLE)
}
