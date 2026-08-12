<script setup lang="ts">
/** 放射轮盘棋盘（design/09 §3）。
 *
 *  老鼠赛跑就是仓鼠轮——圆形是这个游戏的字面意思，实体棋盘的内圈本来也是 24 个扇格
 *  围着中心。快车道是同一只轮盘，格子多一倍、环收窄一半。
 *
 *  格子全部由 SVG 按角度算出来，几何常量在 geom.ts 一处定义（棋盘与走格动画共用）。
 *  板底走 --panel/--panel2：进快车道换 .skin-ft 金箔肤时，这块板自己会跟着变金，
 *  一行都不用为它另写。
 */
import { computed, ref } from 'vue'
import {
  MARKER_ANGLE, RINGS, V, markerLanePoint, outerLabelRadius, polar, sectorPath, slotPoint,
} from './geom'
import type { BoardSquare } from './geom'
import type { Player } from '../../types'

const props = defineProps<{
  track: 'RAT_RACE' | 'FAST_TRACK'
  squares: BoardSquare[]
  players: Player[]
  /** playerId → 1-based 格索引（0 = 起点/入口标记，不是格子） */
  positions: Record<string, number>
  meId: string
  /** 当前行动者停的那一格：整块棋盘只有这一个视觉焦点 */
  currentIndex?: number
  /** 走过的格子（trail）：提到 34% */
  trail?: number[]
  /** 过站结算正在这一格闪橙光 */
  settleIndex?: number
  settleAmount?: number
  /** 这一笔是我自己的：金额归全屏发薪帘幕说，板上只留橙光不再飘一遍字 */
  settleMine?: boolean
  /** 落点脉冲 */
  pulseIndex?: number
  /** 抽屉展开时把盘面标题收起来，把高度让给抽屉 */
  compact?: boolean
  offline?: boolean
}>()

const emit = defineEmits<{ (e: 'tap', sq: BoardSquare): void }>()

const ring = computed(() => RINGS[props.track])
const n = computed(() => props.squares.length || 1)

/** 发牌帘幕要拿某一格的屏幕位置当飞入起点（`geom.squareViewportRect`），而那把尺子是
 *  这只 `<svg>` 的外接矩形。露出元素本身、不在这里替调用方算——**几何只在 geom.ts 一处定义**。 */
const disc = ref<SVGSVGElement | null>(null)
defineExpose({ disc })

/** 格子色：直接取既有的牌堆色变量——它们本来就是「取自实体棋盘的格子」。
 *  这套色不参与阶段换肤：桌上那张牌不会因为你换了赛道就变色。 */
const TYPE_COLOR: Record<string, string> = {
  OPPORTUNITY: 'var(--deck-small)',
  PAYDAY: 'var(--deck-payday)',
  MARKET: 'var(--deck-market)',
  DOODAD: 'var(--deck-doodad)',
  CHARITY: 'var(--deck-payday)',
  CHILD: 'var(--line-2)',
  UNEMPLOYMENT: 'var(--line-2)',
  FT_BUSINESS: 'var(--deck-small)',
  FT_DREAM: 'var(--deck-dream)',
  FT_PAYDAY: 'var(--deck-payday)',
  FT_CHARITY: 'var(--deck-payday)',
  FT_TAX_AUDIT: 'var(--line-2)',
  FT_DIVORCE: 'var(--line-2)',
  FT_LAWSUIT: 'var(--line-2)',
}

function color(sq: BoardSquare): string {
  return TYPE_COLOR[sq.type] ?? 'var(--line-2)'
}

/** 三条视觉规则：常态 15% 的一层类型色、走过的提到 34%、**只有当前所在格上满色**。 */
function fillOpacity(sq: BoardSquare): number {
  if (sq.faded) return 0.08
  if (props.currentIndex === sq.index) return 0.92
  if (props.trail?.includes(sq.index)) return 0.34
  return 0.15
}

function path(sq: BoardSquare): string {
  return sectorPath(sq.index - 1, n.value, ring.value)
}

/** 外缘 7px 的实心弧——和 GameCard::before 的顶部色条是同一套语言 */
function rimPath(sq: BoardSquare): string {
  const r = ring.value
  return sectorPath(sq.index - 1, n.value, { ...r, R0: r.R1 - 7 })
}

function labelPoint(sq: BoardSquare): [number, number] {
  return slotPoint(sq.index, n.value, ring.value)
}

function dotPoint(sq: BoardSquare): [number, number] {
  return slotPoint(sq.index, n.value, ring.value, 0)
}

/** 同格多子沿半径错开（一内一外）；超过 3 个折成 +N。 */
const pawnLanes = computed(() => {
  const byIndex = new Map<number, string[]>()
  for (const p of props.players) {
    if (p.phase === 'OUT' && !props.positions[p.id]) continue
    const idx = props.positions[p.id] ?? 0
    if (!idx) continue                       // 位置 0 在环外的起点标记上，另画
    const arr = byIndex.get(idx) ?? []
    arr.push(p.id)
    byIndex.set(idx, arr)
  }
  const out: { id: string; x: number; y: number; extra: number }[] = []
  for (const [idx, ids] of byIndex) {
    const shown = ids.slice(0, 3)
    shown.forEach((id, i) => {
      const lane = shown.length === 1 ? 0 : (i === 0 ? -1 : i === 1 ? 1 : 0)
      const [x, y] = slotPoint(idx, n.value, ring.value, lane)
      out.push({ id, x, y, extra: i === shown.length - 1 ? ids.length - shown.length : 0 })
    })
  }
  return out
})

/** 还站在起点/入口标记上的人（位置 0）：画在环外那枚三角旁边 */
const atMarker = computed(() =>
  props.players.filter(p => !(props.positions[p.id] ?? 0)))

function playerOf(id: string): Player | undefined {
  return props.players.find(p => p.id === id)
}

/** 棋子色相由座位序号定，与总览页的头像圈同源，不另发一套色 */
function hue(seat: number): number {
  return (seat * 67 + 120) % 360
}

const markerPoint = computed(() => polar(ring.value.R1 + 9, MARKER_ANGLE))
const markerLabel = computed(() => polar(outerLabelRadius(ring.value), MARKER_ANGLE))
/** 还没上路的棋子挂在**环外**的起点标记旁（见 geom.markerLanePoint 的理由）。
 *  名牌已经移出圆盘，环外那一层空出来了，不再跟任何东西挤。 */
const markerLane = computed(() => markerLanePoint(ring.value))

const settlePoint = computed(() =>
  props.settleIndex ? slotPoint(props.settleIndex, n.value, ring.value) : null)
/** 月现金流为负时这一笔是扣钱：号与色都得跟着走，不能一律绿色 `+` */
const settleNeg = computed(() => (props.settleAmount ?? 0) < 0)
const settleText = computed(() => {
  const v = props.settleAmount ?? 0
  return (v < 0 ? '−' : '+') + Math.abs(v).toLocaleString('en-US')
})

/** 棋盘只负责画棋盘：点哪一格由调用方解释（详情弹层 / 什么都不做），这里不做筛选 */
function tap(sq: BoardSquare) {
  emit('tap', sq)
}

/** 环外标注（「开始」「在此进入」）用 SVG 的 text，字号跟着 viewBox 缩放 */
const markerText = computed(() => props.track === 'FAST_TRACK' ? '在此进入' : '开始')
</script>

<template>
  <!-- 盘面标题排在**圆盘之外**：圆内顶部净空只有 V/2 − R1 = 26px，还要留给起点三角，
       塞进去只会换个地方打架（v0.1 挪到板底的下场就是压住了底部三格）。
       圆盘内部只画棋盘本身：格子、棋子、起点标记、轮心。 -->
  <div class="board-wrap">
    <div v-if="!compact" class="wheel-name">
      <span class="logo">CA$HFLOW</span>
      <span class="sub">{{ track === 'FAST_TRACK' ? '快车道' : '老鼠赛跑' }}</span>
    </div>
    <div class="wheel plate" :class="{ 'offline-dim': offline }">
    <svg ref="disc" class="disc" :viewBox="`0 0 ${V} ${V}`" role="img"
         :aria-label="`${track === 'FAST_TRACK' ? '快车道' : '老鼠赛跑'}棋盘`">
      <!-- 格子：底色一层 + 外缘实心弧 + 压印边 -->
      <g v-for="sq in squares" :key="sq.index" class="board-sq tappable"
         @click="tap(sq)">
        <path :d="path(sq)" :fill="color(sq)" :fill-opacity="fillOpacity(sq)"
              stroke="var(--line)" stroke-width="0.6" />
        <path :d="rimPath(sq)" :fill="color(sq)"
              :fill-opacity="sq.faded ? 0.18 : 0.85" />
        <path v-if="currentIndex === sq.index" :d="path(sq)" fill="none"
              :stroke="color(sq)" stroke-width="2" />
        <text v-if="sq.label" :x="labelPoint(sq)[0]" :y="labelPoint(sq)[1]"
              class="sq-label" text-anchor="middle" dominant-baseline="middle">
          {{ sq.label }}
        </text>
        <!-- 已被认领的梦想：中径上一枚玩家色圆点，就是实体那块奶酪 -->
        <circle v-if="sq.dot" :cx="dotPoint(sq)[0]" :cy="dotPoint(sq)[1]" r="5"
                :fill="sq.dot" stroke="var(--panel)" stroke-width="1.5" />
      </g>

      <!-- 落点脉冲：外扩两圈同色光环 -->
      <path v-if="pulseIndex" class="sq-pulse"
            :d="sectorPath(pulseIndex - 1, n, ring)" fill="none"
            stroke="var(--brand)" stroke-width="2.5" />

      <!-- 过站结算：格子脉冲橙光 + 金额飘字。
           **飘字只给旁观者**——当事人此刻正被 PaydayCurtain 盖着屏，帘幕背后不该有它自己
           要揭晓的那个数（同职业卡那条通则）；帘幕散场后这一拍也过去了，看不到残影。 -->
      <g v-if="settlePoint" class="sq-settle">
        <path :d="sectorPath((settleIndex ?? 1) - 1, n, ring)"
              :fill="settleNeg ? 'var(--neg)' : 'var(--deck-payday)'" fill-opacity="0.55" />
        <text v-if="!settleMine" :x="settlePoint[0]" :y="settlePoint[1] - 14"
              class="settle-amt" :class="{ neg: settleNeg }"
              text-anchor="middle">{{ settleText }}</text>
      </g>

      <!-- 起点 / 在此进入：环外一枚三角 + 两个字。它是标记不是格子（位置 0） -->
      <g class="board-marker">
        <polygon
          :points="`${markerPoint[0] - 6},${markerPoint[1] - 7} ${markerPoint[0] + 6},${markerPoint[1] - 7} ${markerPoint[0]},${markerPoint[1] + 3}`"
          :fill="track === 'FAST_TRACK' ? 'var(--gold)' : 'var(--brand)'" />
        <!-- 有人还站在起点时文字让位给棋子：环外只有一层的空间，
             而挤在起跑线上的几枚棋子本身就说明了这里是起点 -->
        <text v-if="!atMarker.length" :x="markerLabel[0]" :y="markerLabel[1]" class="marker-label"
              text-anchor="middle">{{ markerText }}</text>
      </g>

      <!-- 棋子：19px 圆片（viewBox 里 9.5 半径），我的多一圈主色描边并永远在最上层 -->
      <g class="board-pawns">
        <g v-for="(pw, i) in atMarker" :key="'m' + pw.id" class="board-pawn"
           :class="{ mine: pw.id === meId, out: pw.phase === 'OUT' }"
           :transform="`translate(${markerLane[0] + (i - (atMarker.length - 1) / 2) * 15},${markerLane[1]})`">
          <circle r="9.5" :fill="`hsl(${hue(pw.seat)} 45% 88%)`"
                  :stroke="pw.id === meId ? 'var(--brand)' : 'var(--line-2)'"
                  :stroke-width="pw.id === meId ? 2 : 1" />
          <text class="pawn-txt" text-anchor="middle" dominant-baseline="central">
            {{ pw.nickname.slice(0, 1) }}</text>
        </g>
        <g v-for="pw in pawnLanes" :key="pw.id" class="board-pawn"
           :class="{ mine: pw.id === meId, out: playerOf(pw.id)?.phase === 'OUT' }"
           :transform="`translate(${pw.x},${pw.y})`">
          <circle r="9.5" :fill="`hsl(${hue(playerOf(pw.id)?.seat ?? 0)} 45% 88%)`"
                  :stroke="pw.id === meId ? 'var(--brand)' : 'var(--line-2)'"
                  :stroke-width="pw.id === meId ? 2 : 1" />
          <text class="pawn-txt" text-anchor="middle" dominant-baseline="central">
            {{ playerOf(pw.id)?.nickname.slice(0, 1) }}</text>
          <text v-if="pw.extra > 0" class="pawn-extra" x="11" y="-7">+{{ pw.extra }}</text>
        </g>
      </g>
    </svg>

    <!-- 轮心：只放骰盘 + 一行状态提示（轮次归 HUD，进度归 HUD 进度带） -->
    <div class="wheel-hub" :style="{ '--hub': (ring.R0 * 2 / V * 100 - 4) + '%' }">
      <div class="hub"><slot name="hub" /></div>
    </div>
    </div>
  </div>
</template>
