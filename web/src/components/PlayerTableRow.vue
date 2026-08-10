<script setup lang="ts">
/** 牌桌上的一行：他是谁、走到回合哪一步、身上挂着什么持续状态、账面什么样。
 *
 *  两套界面共用同一份（design/09 §6 原话就是纯线上牌桌用「既有那套，不新写」，
 *  当时是照抄了一份，这次收成一个组件）：
 *  - 线下 `ActionTab` 只画当前行动者一行（`.card`）
 *  - 纯线上 `OnlineRoomView` 画全员（`.card.inner`）
 *
 *  「走到哪一步」由调用方传进来：线下按声明式三步（结算日 / 停留格 / 结束），
 *  纯线上按掷骰 / 落点 / 卡片，本来就是两套口径，不该合并。 */
import { fmt } from '../store'
import type { Player } from '../types'
import StatusChips from './StatusChips.vue'

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
</script>

<template>
  <div class="card" :class="{ inner: props.inner }">
    <div class="row between">
      <div class="row" style="gap:8px">
        <span class="avatar-lg">{{ props.player.nickname.slice(0, 1) }}</span>
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

    <div class="row between muted" style="margin-top:8px">
      <span>现金 <b class="money">{{ fmt(props.player.cash) }}</b></span>
      <span v-if="props.player.phase === 'FAST_TRACK'">现金流量日收入
        <b class="money">{{ fmt(props.player.fasttrack.current_income) }}</b></span>
      <span v-else>月现金流
        <b class="money" :class="props.player.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">
          {{ props.player.derived.monthlyCashflow >= 0 ? '+' : ''
          }}{{ fmt(props.player.derived.monthlyCashflow) }}</b></span>
    </div>
  </div>
</template>
