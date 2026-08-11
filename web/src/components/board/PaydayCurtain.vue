<script setup lang="ts">
/** 发薪帘幕（design/09 §5.5）：走格经过或停在结算格时，当事人的一屏全屏过场。
 *
 *  为什么值得占满一屏：结算日是这个游戏里所有投资努力**兑现**的那一刻，
 *  而它此前的呈现是轮盘上一个 13px 的飘字——同一套界面里抽一张小生意卡却有 2.05s 的
 *  全屏帘幕加翻牌。仪式感的排序和游戏机制的排序反了。
 *
 *  三条规矩：
 *  ① **自动消散**，不给「知道了」按钮。`FasttrackCheer` 和胜利屏一局只看几次，可以要求确认；
 *     这一屏一局要看十几次，每次逼人点一下就是骚扰。
 *  ② **点任意处跳过**（照 `DealCurtain`）：终止整条演出序列到终态，不是加速。
 *  ③ `skipAnim` / `prefers-reduced-motion` 下根本不弹——`store.ingestStage` 那条整条丢弃的
 *     出口天然覆盖，这里一行都不用写。
 *
 *  屏上的数**全部来自 `step`**（排队时从结算前的快照焊死，见 stage.ts），不读实时 store：
 *  权威状态在演出开始前就已经是结算后的样子，再去读就没有「$2,100 →」的左边那一半了。
 */
import { computed } from 'vue'
import { fmt, useGame } from '../../store'
import type { StageStep } from '../../stage'

const props = defineProps<{ step: Extract<StageStep, { kind: 'settle' }> }>()
const emit = defineEmits<{ (e: 'skip'): void }>()

const game = useGame()

const ft = computed(() => props.step.track === 'FAST_TRACK')
/** 老鼠赛跑的月现金流可以是负的——**负现金流的结算日恰恰是最该被看见的一刻**，
 *  所以它不是「少一点金色」，而是换一种语气：冷色底、📉、写「本月净支出」。 */
const neg = computed(() => props.step.amount < 0)

function signed(n: number): string {
  return (n >= 0 ? '+' : '−') + fmt(n < 0 ? -n : n)
}

const cashAfter = computed(() => props.step.cashBefore + props.step.amount)

/** 快车道「距胜利还差」：读实时快照是安全的——现金流量日只发钱，不改收入
 *  （胜利线 = 初始现金流量日收入 + $50,000，说明书 P.5）。 */
const toWin = computed(() => {
  const f = game.me?.fasttrack
  if (!f) return 0
  return Math.max(0, f.initial_income + 50000 - f.current_income)
})
</script>

<template>
  <div class="curtain payday" :class="{ ftx: ft, neg }" @click="emit('skip')">
    <div class="curtain-inner">
      <div class="glyph">{{ ft ? '💰' : neg ? '📉' : '🏦' }}</div>
      <h2>{{ ft ? '现金流量日' : '银行结算日' }}</h2>

      <!-- 快车道只有一个数，就让它自己占一行大字 -->
      <template v-if="ft">
        <div class="pay-big">{{ signed(step.amount) }}</div>
        <p class="pay-sub">非工资收入已自动入账</p>
        <div class="conv">
          <div class="cline">
            <span>银行储蓄</span>
            <b>{{ fmt(step.cashBefore) }} → {{ fmt(cashAfter) }}</b>
          </div>
        </div>
        <p v-if="toWin > 0" class="fineprint">距胜利还差 {{ fmt(toWin) }} 的现金流量日收入</p>
      </template>

      <!-- 老鼠赛跑：三行明细必然加得平（total_income = salary + passive，formulas.py） -->
      <template v-else>
        <!-- 一个 .conv 装下所有行：逐行入场的错相延迟是按 nth-child 给的，
             拆成两个 .conv 的话第二个会从头开始、抢在明细前面出现 -->
        <div class="conv">
          <div class="cline"><span>工资收入</span><b>{{ signed(step.salary) }}</b></div>
          <div class="cline"><span>非工资收入</span><b>{{ signed(step.passive) }}</b></div>
          <div class="cline"><span>总支出</span><b>{{ signed(-step.expenses) }}</b></div>
          <div v-if="step.times > 1" class="arrow">
            ↓ 本回合经过 {{ step.times }} 次 · 每次 {{ signed(step.cashflow) }}
          </div>
          <div class="cline hero">
            <span>{{ neg ? '本月净支出' : '本月净得' }}</span>
            <b>{{ signed(step.amount) }}</b>
          </div>
          <div class="cline cash">
            <span>银行储蓄</span>
            <b>{{ fmt(step.cashBefore) }} → {{ fmt(cashAfter) }}</b>
          </div>
        </div>
        <p v-if="neg" class="fineprint">
          现金不足以支付到期款项时直接进入破产清算（说明书 P.5），届时不能改为贷款
        </p>
      </template>

      <p class="fineprint">点一下跳过</p>
    </div>
  </div>
</template>
