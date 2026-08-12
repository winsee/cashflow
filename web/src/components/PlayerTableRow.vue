<script setup lang="ts">
/** 牌桌上的一行：他是谁、走到回合哪一步、身上挂着什么持续状态、账面什么样。
 *
 *  两套界面共用同一份（design/09 §6 原话就是纯线上牌桌用「既有那套，不新写」，
 *  当时是照抄了一份，v0.8 收成一个组件）：
 *  - 线下 `ActionTab` 只画当前行动者一行（`.card`）
 *  - 纯线上 `OnlineRoomView` 画全员（`.card.inner`）
 *
 *  「走到哪一步」由调用方传进来：线下按声明式三步（结算日 / 停留格 / 结束），
 *  纯线上按掷骰 / 落点 / 卡片，本来就是两套口径，不该合并。
 *
 *  v0.12 加了进度条与资产计数（房主：「和总览里面一样，要有进度条，要有他的资产」）。
 *  分工判据：**牌桌多的是「此刻」，总览多的是「可点进去」**——所以这里给的是资产
 *  **计数**（一行放得下、一眼读得完），逐项列名与记录卡入口仍然归总览页。
 *  **不写棋子在第几格**：棋盘上那颗棋子已经把这件事画出来了（房主定案）。
 */
import { computed } from 'vue'
import { fmt, ftWinProgress, FT_WIN_INCREMENT } from '../store'
import type { Player } from '../types'
import StatusChips from './StatusChips.vue'
import { colorVars } from '../playercolor'

const props = defineProps<{
  player: Player
  /** 回合步骤文案，由调用方按本模式的口径给出 */
  step: string
  /** 是不是当前行动者 */
  now?: boolean
  /** 这一行就是我自己（纯线上全员列表里标一下） */
  self?: boolean
  /** 嵌在抽屉里时用 `.card.inner`，独立成块时用 `.card` */
  inner?: boolean
}>()

const ft = computed(() => props.player.phase === 'FAST_TRACK')

/** 出局 / 破产清算的人不画进度与家底：他的「离快车道还差多少」已经没有意义，
 *  处境由状态徽章一句话说完（同「一个位置只有一个主人」那条）。
 *  停赛照画——那只是这几轮不能动，账面照常在跑。 */
const live = computed(() => props.player.phase !== 'OUT' && !props.player.inBankruptcy)

const progress = computed(() => {
  const p = props.player
  if (ft.value) return ftWinProgress(p.fasttrack)
  const d = p.derived
  return d.totalExpenses ? Math.min(100, d.passiveIncome / d.totalExpenses * 100) : 100
})

/** 分子分母写在进度条上方：玩家能自己验算，比一条无标签的色带有用得多（同 HUD 的做法） */
const goalText = computed(() => {
  const p = props.player
  if (ft.value) {
    const left = Math.max(0, p.fasttrack.initial_income + FT_WIN_INCREMENT - p.fasttrack.current_income)
    return `距胜利还差 ${fmt(left)}`
  }
  return `离快车道 ${fmt(p.derived.passiveIncome)} / ${fmt(p.derived.totalExpenses)}`
})

/** 家底摘要。股票是**批次数组**（同一 symbol 可能有多条不同成本的 lot），
 *  所以按总股数汇总而不是数条目——口径同 `store.myStockWindow`。
 *  快车道下改数快车道企业：记录卡已翻面，老鼠赛跑那些资产不再参与计算。 */
const assets = computed<{ icon: string; text: string }[]>(() => {
  const p = props.player
  const out: { icon: string; text: string }[] = []
  if (ft.value) {
    if (p.fasttrack.businesses.length) out.push({ icon: '🏢', text: `×${p.fasttrack.businesses.length}` })
    return out
  }
  if (p.realEstates.length) out.push({ icon: '🏠', text: `×${p.realEstates.length}` })
  if (p.businesses.length) out.push({ icon: '🏢', text: `×${p.businesses.length}` })
  const shares = p.stocks.reduce((a, s) => a + s.shares, 0)
  if (shares) out.push({ icon: '📈', text: `${shares.toLocaleString('en-US')} 股` })
  return out
})
</script>

<template>
  <div class="card ptrow" :class="{ inner: props.inner }">
    <div class="row between">
      <div class="row" style="gap:8px">
        <span class="avatar-lg" :data-pid="props.player.id" :style="colorVars(props.player)">{{ props.player.nickname.slice(0, 1) }}</span>
        <div>
          <b style="font-size:13px">{{ props.player.nickname
            }}<span v-if="props.self">（你）</span></b>
          <!-- 步骤为空 = 这个人当下的处境已由状态徽章说清（出局 / 破产清算 / 停赛） -->
          <div v-if="props.step" class="muted" style="font-size:11px">{{ props.step }}</div>
        </div>
      </div>
      <span v-if="props.now" class="badge turn">行动中</span>
    </div>

    <!-- 持续状态：停赛 / 慈善 / 破产清算 / 出局。围观的人据此判断牌局形势 -->
    <StatusChips :player="props.player" style="margin-top:7px" />

    <!-- 进度：两个阶段用各自的进度语言，结构一致，便于横向比较（同总览页） -->
    <template v-if="live">
      <div class="row between muted ptrow-goal">
        <span>{{ goalText }}</span>
        <span>{{ Math.round(progress) }}%</span>
      </div>
      <div class="progress sm" :class="{ gold: ft }"><div :style="{ width: progress + '%' }" /></div>
    </template>

    <div class="row between muted" style="margin-top:8px">
      <span>现金 <b class="money">{{ fmt(props.player.cash) }}</b></span>
      <span v-if="ft">现金流量日收入
        <b class="money">{{ fmt(props.player.fasttrack.current_income) }}</b></span>
      <span v-else>月现金流
        <b class="money" :class="props.player.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">
          {{ props.player.derived.monthlyCashflow >= 0 ? '+' : ''
          }}{{ fmt(props.player.derived.monthlyCashflow) }}</b></span>
    </div>

    <!-- 家底：一行计数。全空就整行不渲染——开局摆一句「暂无资产」是废话 -->
    <div v-if="live && assets.length" class="ptrow-assets">
      <span v-for="a in assets" :key="a.icon">{{ a.icon }}{{ a.text }}</span>
    </div>
  </div>
</template>
