/** 棋盘几何：**一处定义**，棋盘渲染、走格动画、发牌飞入锚点共用（design/09 §3、§8）。
 *
 *  一张板上有两条轨道（v0.15）：
 *  - **内轮盘** 24 格，放射扇环——老鼠赛跑就是仓鼠轮，圆形是这个游戏的字面意思；
 *  - **外圈跑道** 48 格，圆角矩形——实体棋盘本来就是「中间一只轮盘 + 外面一圈方形跑道」，
 *    正圆盘的四个角一直空着，跑道正好住进去。快车道一格因此从 17.2px 宽到 23.5px。
 *
 *  v0.14 之前快车道也摊成正圆环，于是一次只画得下一条赛道——跨赛道的同桌互相看不见。
 *
 *  对外只暴露**认赛道**的 API（`squarePath` / `slotPoint` / `squareViewportRect` …）：
 *  组件不该认识任何一个半径常量，否则「几何只在这里定义」就名存实亡。
 */

export type Track = 'RAT_RACE' | 'FAST_TRACK'

/** 棋盘上的一格。棋盘完全由这个数组驱动——格数与顺序变了不用改一行呈现代码。 */
export interface BoardSquare {
  /** 1-based 格索引（0 留给起点/入口标记，那不是格子） */
  index: number
  /** 内圈七种 type，或快车道 FT_BUSINESS / FT_DREAM / FT_PAYDAY / FT_CHARITY / FT_* */
  type: string
  /** 快车道的 ft-b-* / ft-d-* / ft-s-*；内圈为 rr-XX */
  ref: string
  /** 格面文字；空串 = 不写字（内圈 12 个机会格、快车道的企业与梦想格） */
  label: string
  /** 褪成底色：已被买断的绿格 */
  faded?: boolean
  /** 没有占位道具时印一枚图标（快车道 18 绿格 / 23 梦想格） */
  icon?: 'biz' | 'dream'
  /** 占位道具：实体那块奶酪与那枚金币 */
  token?: SquareToken
  /** 梦想被加价的倍数（2 = ×2）。服务端不记是谁加的价，所以**不上任何人的颜色** */
  bump?: number
}

export interface SquareToken {
  /** cheese = 选定的梦想；coin = 买下的企业或买下占位的梦想；once = 一次性收益型企业 */
  kind: 'cheese' | 'coin' | 'once'
  /** 玩家色 solid */
  color: string
  /** 昵称首字：颜色永远不是唯一线索 */
  initial: string
  /** 无障碍全文，进 <title> */
  who: string
}

/** 棋盘上的一个落点：**索引必须带着赛道走**。两条轨道同屏之后，一个裸 index
 *  会在内圈第 7 格与快车道第 7 格上同时点亮——那是正确性问题，不是洁癖。 */
export interface Spot { track: Track; index: number }

/** SVG viewBox 边长（正方形），随板宽等比缩放 */
export const V = 320
export const C = V / 2

/** 每条轨道的格数。棋盘的格数由数据说了算，这里只是算角度/弧长用的默认值。 */
export const COUNT: Record<Track, number> = { RAT_RACE: 24, FAST_TRACK: 48 }

// ────────────────────────── 内轮盘（放射扇环） ──────────────────────────

export interface Ring {
  /** 外径 / 内径 / 中径（标签与棋子的基准） */
  R1: number
  R0: number
  RMID: number
  /** 格与格之间的缝（度） */
  GAP: number
}

/** 内轮盘：外径由**空档带的内沿**反推（见 BAND），不是拍出来的。
 *  一格弧宽 2π×92/24 = 24.1 单位（板宽 332px 时 25px），扣掉 1.5° 缝净 21.7 单位，
 *  两个 9px 的字正好放得下。 */
export const RR_RING: Ring = { R1: 110, R0: 74, RMID: 92, GAP: 1.5 }

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

// ────────────────────────── 外圈跑道（圆角矩形） ──────────────────────────

/** 跑道：中线是一只圆角矩形。改这几个数，48 格自己重排。
 *
 *  `INSET` 是**中线**的内缩，所以外边界在 `INSET − D/2 = 2`（留 2 单位给板描边），
 *  内边界在 `INSET + D/2 = 28`（12 点方向半径 132，正是空档带的外沿）。 */
export const RAIL = { INSET: 15, CR: 42, D: 26, GAP: 1.6 } as const

/** 中线直边段的长度（一条边） */
const RAIL_SIDE = (V - 2 * RAIL.INSET) - 2 * RAIL.CR            // 206
/** 中线周长 = 4 条直边 + 4 段 90° 圆弧 */
export const RAIL_LEN = 4 * RAIL_SIDE + 2 * Math.PI * RAIL.CR   // ≈ 1087.9
/** 一格占的弧长：22.66 单位 × 深 26，板宽 332px 时约 23.5 × 27px（旧的正圆环只有 17.2px） */
export const RAIL_W = RAIL_LEN / COUNT.FAST_TRACK

/** 两条轨道之间的空档带：起点三角、「开始」「在此进入」、**位置 0 的棋子**都住这儿。
 *
 *  它是整条半径链的**起点**而不是余数：两条轨道各有一批「还没上路」的人
 *  （老鼠赛跑位置 0 是开局全员，快车道位置 0 是每个刚逃出来的人要停留的整整一个回合），
 *  棋子直径 18 单位，带子必须站得下它。内轮盘的 R1 是由这条带子的内沿反推出来的。 */
export const BAND = { R0: RR_RING.R1, R1: V / 2 - (RAIL.INSET + RAIL.D / 2), MID: 121 } as const

export interface RailPoint { x: number; y: number; nx: number; ny: number }

type RailSeg =
  | { kind: 'line'; len: number; x0: number; y0: number; dx: number; dy: number; nx: number; ny: number }
  | { kind: 'arc'; len: number; cx: number; cy: number; f0: number }

/** 中线的 9 段（4 直 4 弧，**底边被起点切成两半**）。
 *
 *  `t = 0` 在底边中央（6 点）、顺时针为正——12 点留给内轮盘的「开始」，两枚标记不打架；
 *  这也更贴实体：实体棋盘上 1–14 格就是沿着底边走的。
 *  屏幕坐标里顺时针从 6 点起是**向左**，所以第 48 格落在起点右侧。 */
const RAIL_SEGS: RailSeg[] = (() => {
  const m = RAIL.INSET, r = RAIL.CR, s = RAIL_SIDE, M = V - m, q = Math.PI * r / 2
  return [
    { kind: 'line', len: s / 2, x0: C, y0: M, dx: -1, dy: 0, nx: 0, ny: 1 },
    { kind: 'arc', len: q, cx: m + r, cy: M - r, f0: 90 },
    { kind: 'line', len: s, x0: m, y0: M - r, dx: 0, dy: -1, nx: -1, ny: 0 },
    { kind: 'arc', len: q, cx: m + r, cy: m + r, f0: 180 },
    { kind: 'line', len: s, x0: m + r, y0: m, dx: 1, dy: 0, nx: 0, ny: -1 },
    { kind: 'arc', len: q, cx: M - r, cy: m + r, f0: 270 },
    { kind: 'line', len: s, x0: M, y0: m + r, dx: 0, dy: 1, nx: 1, ny: 0 },
    { kind: 'arc', len: q, cx: M - r, cy: M - r, f0: 360 },
    { kind: 'line', len: s / 2, x0: M - r, y0: M, dx: -1, dy: 0, nx: 0, ny: 1 },
  ]
})()

/** 中线上弧长 `t` 处的坐标与**朝外单位法线**。整套跑道几何的唯一入口。
 *
 *  9 段线性扫过去就够：48 格 × 每格 7 个采样 = 336 次/帧，这是纳秒级的事，不必二分。 */
export function railPoint(t: number): RailPoint {
  let u = ((t % RAIL_LEN) + RAIL_LEN) % RAIL_LEN
  for (const g of RAIL_SEGS) {
    if (u <= g.len) {
      if (g.kind === 'line') {
        return { x: g.x0 + g.dx * u, y: g.y0 + g.dy * u, nx: g.nx, ny: g.ny }
      }
      const f = g.f0 * Math.PI / 180 + u / RAIL.CR
      return {
        x: g.cx + RAIL.CR * Math.cos(f), y: g.cy + RAIL.CR * Math.sin(f),
        nx: Math.cos(f), ny: Math.sin(f),
      }
    }
    u -= g.len
  }
  // 浮点误差把 u 落到最后一段之外：钳回起点，绝不返回 undefined
  const g = RAIL_SEGS[0] as Extract<RailSeg, { kind: 'line' }>
  return { x: g.x0, y: g.y0, nx: g.nx, ny: g.ny }
}

/** 沿法线偏移：`d > 0` 朝板外，`d < 0` 朝盘心。 */
export function railOffset(p: RailPoint, d: number): [number, number] {
  return [p.x + p.nx * d, p.y + p.ny * d]
}

/** 跑道上第 `index` 格（**1-based**）的路径，`d0`/`d1` 是深度窗口（默认整格）。
 *
 *  **不给外/内边界各自按比例分参**——两条边界周长不等，角上的格子会歪成梯形。
 *  改为在中线上按弧长参数化，外边 = `P + N·d1`、内边 = `P + N·d0`，
 *  沿 t 采样 7 个点连成 6 段折线。误差核算：最坏情形整格落在角弧内，中线半径 42，
 *  一格张角 30.9°，每小段 5.15°，外边界（R=55）矢高 0.056 单位 = 板宽 332px 时的 0.058px。
 *  不必为直边与弧段写任何特例。 */
export function railSquarePath(index: number, d0 = -RAIL.D / 2, d1 = RAIL.D / 2): string {
  const K = 6
  const t0 = (index - 1) * RAIL_W + RAIL.GAP / 2
  const t1 = index * RAIL_W - RAIL.GAP / 2
  const outer: string[] = []
  const inner: string[] = []
  for (let i = 0; i <= K; i++) {
    const p = railPoint(t0 + (t1 - t0) * i / K)
    const [ox, oy] = railOffset(p, d1)
    const [ix, iy] = railOffset(p, d0)
    outer.push(`${ox.toFixed(2)} ${oy.toFixed(2)}`)
    inner.push(`${ix.toFixed(2)} ${iy.toFixed(2)}`)
  }
  inner.reverse()
  return `M${outer.join('L')}L${inner.join('L')}Z`
}

// ────────────────────────── 两条轨道的统一入口 ──────────────────────────

/** 第 `index` 格（**1-based**）的格子路径 */
export function squarePath(track: Track, index: number, n = COUNT[track]): string {
  return track === 'FAST_TRACK'
    ? railSquarePath(index)
    : sectorPath(index - 1, n, RR_RING)
}

/** 外缘那道实心色条——和 `GameCard::before` 的顶部色条是同一套语言 */
export function rimPath(track: Track, index: number, n = COUNT[track]): string {
  return track === 'FAST_TRACK'
    ? railSquarePath(index, RAIL.D / 2 - 5, RAIL.D / 2)
    : sectorPath(index - 1, n, { ...RR_RING, R0: RR_RING.R1 - 6 })
}

/** 第 `index` 格（**1-based**）上的一点。
 *
 *  `lane` 是同格多子的错开档（0 居中、±1 各让一边）；
 *  `depth` 沿法线/半径微调，用来给图标与占位道具分层。
 *
 *  **两条轨道的 lane 方向不同**：内圈沿半径错开（环宽 36 单位，摞得下）；
 *  快车道深度只有 26 单位，两枚 18 单位的圆片径向摞不下，改沿**切向**错开。
 *  这条差异由这里消化——调用方只传 lane，不该知道它是径向还是切向。 */
export function slotPoint(
  track: Track, index: number, lane = 0, depth = 0, n = COUNT[track],
): [number, number] {
  if (track === 'FAST_TRACK') {
    return railOffset(railPoint((index - 0.5) * RAIL_W + lane * 6), depth)
  }
  const spread = (RR_RING.R1 - RR_RING.R0) * 0.27
  return polar(RR_RING.RMID + lane * spread + depth, slotAngle(index - 1, n))
}

/** 一格的标称边长：内圈取中径弧宽，快车道取跑道一格的弧长。 */
export function squareSide(track: Track, n = COUNT[track]): number {
  return track === 'FAST_TRACK' ? RAIL_W : 2 * Math.PI * RR_RING.RMID / n
}

/** 第 `index` 格（**1-based**）在**视口坐标**里的外接矩形——发牌帘幕的「飞入」拍拿它当起点
 *  （design/09 §5.1 拍 6：牌背**从格子位置**飞向屏心）。
 *
 *  viewBox 是 `0 0 V V` 的正方形、随板宽等比缩放，所以一次线性换算就够，不必动 `getScreenCTM()`。
 *
 *  **量不到就返回 `null`**（棋盘在 full 档被压成一条、或还没挂上）：调用方据此退回不带锚点的
 *  老行为，而不是拿一个 0×0 的矩形去算出满屏乱飞的位移。 */
export function squareViewportRect(
  svg: SVGSVGElement | null | undefined, track: Track, index: number, n = COUNT[track],
): DOMRect | null {
  if (!svg || index < 1 || index > n) return null
  const box = svg.getBoundingClientRect()
  if (box.width < 1 || box.height < 1) return null
  const k = box.width / V
  const [x, y] = slotPoint(track, index, 0, 0, n)
  const side = squareSide(track, n) * k
  return new DOMRect(box.left + x * k - side / 2, box.top + y * k - side / 2, side, side)
}

// ────────────────────────── 起点 / 入口标记 ──────────────────────────

/** 内轮盘的「开始」在 12 点接缝上——**它不是格子**（位置 0），第 1 格从这里开始数。 */
export const MARKER_ANGLE = 0

/** 起点三角的尖：两条轨道都画在**空档带**里。
 *
 *  快车道的跑道外边界离板边只有 2 单位，环外已经没有地方了；而空档带正好在两条轨道中间，
 *  一枚三角 + 一行字 + 几枚等待中的棋子都装得下。 */
export function markerPoint(track: Track): [number, number] {
  return track === 'FAST_TRACK'
    ? railOffset(railPoint(0), -(RAIL.D / 2 + 6))
    : polar(RR_RING.R1 + 6, MARKER_ANGLE)
}

/** 「开始」/「在此进入」两个字的落点。
 *
 *  **沿轨道方向让开三角，不在半径上让**：空档带只有 22 单位，而一行 10px 的字加一枚
 *  9 单位高的三角要 19 单位——挤在同一个角度上必然叠在一起（第一版就是这么糊的）。
 *  带子本身是一整圈，沿着它挪二三十个单位有大把地方。 */
export function markerLabelPoint(track: Track): [number, number] {
  return track === 'FAST_TRACK'
    // 4 个字约 36 单位宽，沿跑道挪 30 单位就完全离开三角
    ? railOffset(railPoint(30), -(RAIL.D / 2 + 8))
    // 2 个字约 18 单位宽，13° × 半径 121 ≈ 27 单位的弧长
    : polar(BAND.MID, MARKER_ANGLE + 13)
}

/** 位置 0 的棋子（还没上路的人）落在哪儿：**空档带上**，起点标记旁。
 *
 *  「多枚沿切向 15 单位排开、整体居中」这条排布也收在这里——它是几何，
 *  从前写在 `BoardView` 模板的 transform 表达式里，那是几何漏在组件里。 */
export function markerLanePoint(track: Track, i = 0, total = 1): [number, number] {
  const off = (i - (total - 1) / 2) * 15
  if (track === 'FAST_TRACK') {
    return railOffset(railPoint(off), -(RAIL.D / 2 + 8))
  }
  const [x, y] = polar(BAND.MID, MARKER_ANGLE)
  return [x + off, y]
}
