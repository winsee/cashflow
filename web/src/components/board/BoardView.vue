<script setup lang="ts">
/** 一张板，两条赛道（design/09 §3，v0.15 重写）。
 *
 *  实体棋盘本来就是这个结构：中间一只 24 格的轮盘，外面一圈方形跑道
 *  （`docs/游戏棋盘.jfif`）。v0.14 之前线上把快车道也摊成正圆环，于是
 *  ① 正圆盘的四个角一直空着、快车道一格只有 17.2px；
 *  ② 一次只画得下一条赛道——跨赛道的同桌互相看不见。
 *
 *  现在两条一起画：**每个玩家画在他自己 `phase` 对应的那条上**，与观看者是谁无关。
 *  观看者的身份只决定 `focus`（哪条是主赛道，另一条降饱和），**一个棋子的位置都不由它决定**。
 *
 *  格子全部由 SVG 按几何算出来，常量在 geom.ts 一处定义——这个组件不认识任何一个半径。
 *  板底走 --panel/--panel2：进快车道换 .skin-ft 金箔肤时，这块板自己会跟着变金。
 */
import { computed, ref } from 'vue'
import {
  RR_RING, V, markerLabelPoint, markerLanePoint, markerPoint,
  rimPath, slotPoint, squarePath,
} from './geom'
import type { BoardSquare, Spot, Track } from './geom'
import {
  BIZ_DOOR, BIZ_ICON, CHEESE, CHEESE_HOLES, DEPTH, DREAM_FLAG, DREAM_POLE, ONCE_BAR,
} from './tokens'
import { seatColor } from '../../playercolor'
import type { Player } from '../../types'

const props = defineProps<{
  /** 观看者自己的赛道：只决定哪条是主赛道（标题、降饱和），**不决定任何棋子的位置** */
  focus: Track
  /** 内圈 24 格 */
  rr: BoardSquare[]
  /** 快车道 48 格 */
  ft: BoardSquare[]
  players: Player[]
  /** playerId → 落点（index 为 0 表示还在起点/入口标记上，那不是格子） */
  positions: Record<string, Spot>
  meId: string
  /** 当前行动者停的那一格：整块棋盘只有这一个视觉焦点 */
  current?: Spot | null
  /** 走过的格子（trail）：提到 34%。**按赛道分开存**——裸 index 会在两条轨道上同时点亮 */
  trail?: Partial<Record<Track, number[]>>
  /** 过站结算正在这一格闪橙光 */
  settle?: (Spot & { amount: number; mine?: boolean }) | null
  /** 落点脉冲 */
  pulse?: Spot | null
  /** 抽屉展开：格面文字与图标退场，道具留着；名牌隐藏，**但工具带不动**（它不在这个组件里） */
  compact?: boolean
  offline?: boolean
}>()

const emit = defineEmits<{ (e: 'tap', sq: BoardSquare, track: Track): void }>()

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

/** trail 查表用 Set：两条轨道 72 格 × 每格一次 `includes` 是白花的 O(n·m) */
const trailSets = computed(() => ({
  RAT_RACE: new Set(props.trail?.RAT_RACE ?? []),
  FAST_TRACK: new Set(props.trail?.FAST_TRACK ?? []),
}))

/** 三条视觉规则：常态 15% 的一层类型色、走过的提到 34%、**只有当前所在格上满色**。 */
function fillOpacity(track: Track, sq: BoardSquare): number {
  if (sq.faded) return 0.08
  if (isCurrent(track, sq)) return 0.92
  if (trailSets.value[track].has(sq.index)) return 0.34
  return 0.15
}

function isCurrent(track: Track, sq: BoardSquare): boolean {
  return props.current?.track === track && props.current.index === sq.index
}

/** 同格多子错开：内圈沿半径、快车道沿切向（差异由 geom.slotPoint 消化）。
 *  内圈最多 3 枚然后折 `+N`；快车道一格窄，最多 2 枚。 */
const pawns = computed(() => {
  const byKey = new Map<string, string[]>()
  for (const p of props.players) {
    const spot = props.positions[p.id]
    if (!spot || !spot.index) continue          // 位置 0 在空档带的起点标记上，另画
    const key = `${spot.track}:${spot.index}`
    const arr = byKey.get(key) ?? []
    arr.push(p.id)
    byKey.set(key, arr)
  }
  const out: { id: string; x: number; y: number; extra: number; track: Track }[] = []
  for (const [key, ids] of byKey) {
    const track = key.slice(0, key.indexOf(':')) as Track
    const index = Number(key.slice(key.indexOf(':') + 1))
    const cap = track === 'FAST_TRACK' ? 2 : 3
    const shown = ids.slice(0, cap)
    shown.forEach((id, i) => {
      const lane = shown.length === 1 ? 0 : (i === 0 ? -1 : i === 1 ? 1 : 0)
      const [x, y] = slotPoint(track, index, lane)
      out.push({ id, x, y, track, extra: i === shown.length - 1 ? ids.length - shown.length : 0 })
    })
  }
  return out
})

/** 还站在起点/入口标记上的人（位置 0），**按赛道分两组** */
const atMarker = computed(() => {
  const g: Record<Track, Player[]> = { RAT_RACE: [], FAST_TRACK: [] }
  for (const p of props.players) {
    const spot = props.positions[p.id]
    if (spot && !spot.index) g[spot.track].push(p)
  }
  return g
})

function playerOf(id: string): Player | undefined {
  return props.players.find(p => p.id === id)
}

function pawnColor(id: string) {
  return seatColor(playerOf(id)?.seat ?? 0)
}

const settlePoint = computed(() =>
  props.settle ? slotPoint(props.settle.track, props.settle.index) : null)
/** 月现金流为负时这一笔是扣钱：号与色都得跟着走，不能一律绿色 `+` */
const settleNeg = computed(() => (props.settle?.amount ?? 0) < 0)
const settleText = computed(() => {
  const v = props.settle?.amount ?? 0
  return (v < 0 ? '−' : '+') + Math.abs(v).toLocaleString('en-US')
})

/** 棋盘只负责画棋盘：点哪一格由调用方解释（详情弹层 / 什么都不做），这里不做筛选 */
function tap(sq: BoardSquare, track: Track) {
  emit('tap', sq, track)
}

const TRACKS: { key: Track; text: string }[] = [
  { key: 'RAT_RACE', text: '开始' },
  { key: 'FAST_TRACK', text: '在此进入' },
]

function squaresOf(track: Track): BoardSquare[] {
  return track === 'FAST_TRACK' ? props.ft : props.rr
}

/** 道具/图标的深度：有道具时图标让位（tokens.DEPTH 里写了为什么） */
function glyphPoint(track: Track, sq: BoardSquare): [number, number] {
  return slotPoint(track, sq.index, 0, sq.token ? DEPTH.glyphWithToken : DEPTH.glyph)
}
function tokenPoint(track: Track, sq: BoardSquare): [number, number] {
  return slotPoint(track, sq.index, 0, DEPTH.token)
}
function bumpPoint(track: Track, sq: BoardSquare): [number, number] {
  return slotPoint(track, sq.index, 0.3, DEPTH.bump)
}

/** 轮心可用直径：由内轮盘内径算出，公式不动（v0.15 起是 42.25%，板宽 332 时 140px）。
 *  三粒 40px 的骰子塞不进 124px 的净宽，所以 `.board-dice.n3` 把 `--d` 收到 34px。 */
const hubPct = RR_RING.R0 * 2 / V * 100 - 4

/** 起点三角的三个点。算在这儿而不是模板表达式里：坐标算式写进模板等于几何漏出去。 */
function markerTri(track: Track): string {
  const [x, y] = markerPoint(track)
  return track === 'FAST_TRACK'
    // 快车道的三角在空档带里、指向**外**（跑道在外圈）
    ? `${x - 5},${y - 5} ${x + 5},${y - 5} ${x},${y + 4}`
    // 内圈的三角指向**内**（轮盘在里面）
    : `${x - 5},${y - 6} ${x + 5},${y - 6} ${x},${y + 2}`
}
</script>

<template>
  <!-- 这个组件只画板本身。名牌与三枚悬浮圆钮都钉在 stage 顶上那条带里（design/09 §3.2.1 v0.15），
       不在这里——它们要在抽屉拉到任何档位时都待在同一个屏幕位置。 -->
  <div class="board-wrap" :class="{ compact }">
    <div class="wheel plate" :class="{ 'offline-dim': offline }">
    <svg ref="disc" class="disc" :class="{ compact }" :viewBox="`0 0 ${V} ${V}`" role="img"
         aria-label="老鼠赛跑内轮盘与快车道外圈跑道">
      <!-- 两条轨道。**降饱和只作用在格子上**——人和人的道具不参与「这条赛道不是我的」
           这种氛围表达，棋子永远满色（它们画在 .board-pawns 里，不在 .track 内）。 -->
      <g v-for="t in TRACKS" :key="t.key" class="track" :class="[
           t.key === 'FAST_TRACK' ? 'track-ft' : 'track-rr', { dim: focus !== t.key }]">
        <g v-for="sq in squaresOf(t.key)" :key="sq.index" class="board-sq tappable"
           :data-index="sq.index" @click="tap(sq, t.key)">
          <path :d="squarePath(t.key, sq.index, squaresOf(t.key).length)" :fill="color(sq)"
                :fill-opacity="fillOpacity(t.key, sq)" stroke="var(--line)" stroke-width="0.6" />
          <path :d="rimPath(t.key, sq.index, squaresOf(t.key).length)" :fill="color(sq)"
                :fill-opacity="sq.faded ? 0.18 : 0.85" />
          <path v-if="isCurrent(t.key, sq)" :d="squarePath(t.key, sq.index, squaresOf(t.key).length)"
                fill="none" :stroke="color(sq)" stroke-width="2" />

          <!-- 格面：文字 → 图标 → 道具，compact 档按这个顺序退场，道具留到最后 -->
          <template v-if="!compact">
            <text v-if="sq.label" :x="glyphPoint(t.key, sq)[0]" :y="glyphPoint(t.key, sq)[1]"
                  class="sq-label" text-anchor="middle" dominant-baseline="middle">{{ sq.label }}</text>
            <g v-else-if="sq.icon === 'biz'" class="sq-icon biz"
               :transform="`translate(${glyphPoint(t.key, sq)[0]},${glyphPoint(t.key, sq)[1]})${sq.token ? ' scale(.82)' : ''}`">
              <path v-for="(d, i) in BIZ_ICON" :key="i" :d="d" />
              <rect :x="BIZ_DOOR.x" :y="BIZ_DOOR.y" :width="BIZ_DOOR.w" :height="BIZ_DOOR.h"
                    rx=".5" class="hole" />
            </g>
            <g v-else-if="sq.icon === 'dream'" class="sq-icon dream"
               :transform="`translate(${glyphPoint(t.key, sq)[0]},${glyphPoint(t.key, sq)[1]})${sq.token ? ' scale(.82)' : ''}`">
              <rect :x="DREAM_POLE.x" :y="DREAM_POLE.y" :width="DREAM_POLE.w"
                    :height="DREAM_POLE.h" rx=".5" />
              <path :d="DREAM_FLAG" />
            </g>
          </template>

          <!-- 占位道具：实体那块奶酪与那枚金币 -->
          <g v-if="sq.token" class="ft-token" :class="sq.token.kind"
             :transform="`translate(${tokenPoint(t.key, sq)[0]},${tokenPoint(t.key, sq)[1]})`">
            <title>{{ sq.token.who }}</title>
            <template v-if="sq.token.kind === 'cheese'">
              <path :d="CHEESE" :fill="sq.token.color" stroke="var(--panel)"
                    stroke-width="1.2" stroke-linejoin="round" />
              <circle v-for="(h, i) in CHEESE_HOLES" :key="i" :cx="h.cx" :cy="h.cy" :r="h.r"
                      fill="var(--panel)" fill-opacity=".78" />
            </template>
            <template v-else>
              <circle r="4.9" :fill="sq.token.color" stroke="var(--panel)" stroke-width="1.2" />
              <circle r="3.2" fill="none" stroke="var(--panel)" stroke-opacity=".5" stroke-width=".8" />
              <text v-if="!compact" class="token-ini" text-anchor="middle" dominant-baseline="central"
                    fill="var(--panel)">{{ sq.token.initial }}</text>
              <path v-if="sq.token.kind === 'once'" :d="ONCE_BAR" :stroke="sq.token.color"
                    stroke-width="1.6" stroke-linecap="round" />
            </template>
          </g>

          <!-- 被加价的梦想：价格不是归属，所以不上任何人的颜色 -->
          <text v-if="sq.bump && !compact" :x="bumpPoint(t.key, sq)[0]" :y="bumpPoint(t.key, sq)[1]"
                class="sq-bump" text-anchor="middle" dominant-baseline="central">×{{ sq.bump + 1 }}</text>
        </g>

        <!-- 起点 / 在此进入：空档带里一枚三角 + 两个字。它是标记不是格子（位置 0）。
             有人站在起跑线上时文字让位——挤在那儿的几枚棋子本身就说明了这里是起点 -->
        <g class="board-marker">
          <polygon :points="markerTri(t.key)"
                   :fill="t.key === 'FAST_TRACK' ? 'var(--gold)' : 'var(--brand)'" />
          <text v-if="!atMarker[t.key].length && !compact"
                :x="markerLabelPoint(t.key)[0]" :y="markerLabelPoint(t.key)[1]"
                class="marker-label" text-anchor="middle" dominant-baseline="central">{{ t.text }}</text>
        </g>
      </g>

      <!-- 落点脉冲：外扩两圈同色光环 -->
      <path v-if="pulse" class="sq-pulse" :d="squarePath(pulse.track, pulse.index)" fill="none"
            stroke="var(--brand)" stroke-width="2.5" />

      <!-- 过站结算：格子脉冲橙光 + 金额飘字。
           **飘字只给旁观者**——当事人此刻正被 PaydayCurtain 盖着屏，帘幕背后不该有它自己
           要揭晓的那个数（同职业卡那条通则）；帘幕散场后这一拍也过去了，看不到残影。 -->
      <g v-if="settle && settlePoint" class="sq-settle">
        <path :d="squarePath(settle.track, settle.index)"
              :fill="settleNeg ? 'var(--neg)' : 'var(--deck-payday)'" fill-opacity="0.55" />
        <text v-if="!settle.mine" :x="settlePoint[0]" :y="settlePoint[1] - 14"
              class="settle-amt" :class="{ neg: settleNeg }"
              text-anchor="middle">{{ settleText }}</text>
      </g>

      <!-- 棋子：18px 圆片，我的多一圈主色描边并永远在最上层。
           **两条轨道的棋子一起画**，各自落在自己那条上 -->
      <g class="board-pawns">
        <template v-for="t in TRACKS" :key="'m' + t.key">
          <g v-for="(pw, i) in atMarker[t.key]" :key="'m' + pw.id" class="board-pawn"
             :data-pid="pw.id" :data-track="t.key"
             :class="{ mine: pw.id === meId, out: pw.phase === 'OUT' }"
             :transform="`translate(${markerLanePoint(t.key, i, atMarker[t.key].length)[0]},${markerLanePoint(t.key, i, atMarker[t.key].length)[1]})`">
            <circle r="9" :fill="seatColor(pw.seat).soft"
                    :stroke="pw.id === meId ? 'var(--brand)' : 'var(--line-2)'"
                    :stroke-width="pw.id === meId ? 2 : 1" />
            <text class="pawn-txt" :fill="seatColor(pw.seat).ink" text-anchor="middle"
                  dominant-baseline="central">{{ pw.nickname.slice(0, 1) }}</text>
          </g>
        </template>
        <g v-for="pw in pawns" :key="pw.id" class="board-pawn"
           :data-pid="pw.id" :data-track="pw.track"
           :class="{ mine: pw.id === meId, out: playerOf(pw.id)?.phase === 'OUT' }"
           :transform="`translate(${pw.x},${pw.y})`">
          <circle r="9" :fill="pawnColor(pw.id).soft"
                  :stroke="pw.id === meId ? 'var(--brand)' : 'var(--line-2)'"
                  :stroke-width="pw.id === meId ? 2 : 1" />
          <text class="pawn-txt" :fill="pawnColor(pw.id).ink" text-anchor="middle"
                dominant-baseline="central">{{ playerOf(pw.id)?.nickname.slice(0, 1) }}</text>
          <text v-if="pw.extra > 0" class="pawn-extra" x="10.5" y="-7">+{{ pw.extra }}</text>
        </g>
      </g>
    </svg>

    <!-- 轮心：只放骰盘 + 一行状态提示（轮次归 HUD，进度归 HUD 进度带） -->
    <div class="wheel-hub" :style="{ '--hub': hubPct + '%' }">
      <div class="hub"><slot name="hub" /></div>
    </div>
    </div>
  </div>
</template>
