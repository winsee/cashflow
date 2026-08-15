<script setup lang="ts">
/** 惩罚帘幕（design/09 §5.5 延伸）：失业/孩子/税务审计/离婚/官司这 5 种
 *  「必付无选项」的格子，当事人的一屏全屏过场。
 *
 *  自动结算本身不变——这 5 种从来没有「要不要付」的选项，帘幕只是把呈现从
 *  抽屉里一晃而过的小回执卡，升级成和结算日同一量级的全屏过场（同一条判据：
 *  design/09 §5.5「一件事该给多大的呈现，看它在游戏机制里有多重」，
 *  这 5 种早被 §4.3.1 归为「低频重击」，只是此前没吃到这条判据的红利）。
 *
 *  交互照抄 `PaydayCurtain`：点任意处跳过，不给「确认」按钮。
 *
 *  屏上的数**全部来自 `step`**（排队时从 stage.ts 焊死，不读实时 store）——
 *  UNEMPLOYMENT_HIT/FT_CASH_HIT 都是批内唯一一次改这个人现金的事件，
 *  CHILD_ADDED 没有现金变动，孩子数/月支出改由 prev 快照 +1 推出来。
 */
import { computed } from 'vue'
import { fmt, signed } from '../../store'
import type { StageStep } from '../../stage'

const props = defineProps<{ step: Extract<StageStep, { kind: 'penalty' }> }>()
const emit = defineEmits<{ (e: 'skip'): void }>()

const cashAfter = computed(() => props.step.cashBefore + props.step.amount)

/** 三种视觉语气：老鼠赛跑冷色（失业）/ 快车道金箔转冷（税务审计·离婚·官司）/ 暖色（孩子） */
const variant = computed(() => {
  switch (props.step.hitKind) {
    case 'UNEMPLOYMENT': return 'cold'
    case 'CHILD': return 'warm'
    default: return 'ftxcold'
  }
})

const TEXT: Record<string, { glyph: string; title: string; line: string; fine: string }> = {
  UNEMPLOYMENT: { glyph: '💼', title: '失业', line: '总支出', fine: '自动结算 · 从下一回合起停赛 2 轮' },
  TAX_AUDIT: { glyph: '🧾', title: '税务审计', line: '现金减半上缴', fine: '快车道 · 现金减半上缴国库' },
  LAWSUIT: { glyph: '⚖️', title: '官司', line: '现金减半赔付', fine: '快车道 · 现金减半赔付' },
  DIVORCE: { glyph: '💔', title: '离婚', line: '失去全部现金', fine: '快车道 · 现金归零' },
  CHILD: { glyph: '👶', title: '喜添一名孩子', line: '现在共', fine: '孩子格满 3 个后不再生效' },
}
const t = computed(() => TEXT[props.step.hitKind])
</script>

<template>
  <div class="curtain penalty" :class="variant" @click="emit('skip')">
    <div class="curtain-inner">
      <div class="glyph">{{ t.glyph }}</div>
      <h2>{{ t.title }}</h2>

      <template v-if="step.hitKind === 'CHILD'">
        <div class="conv">
          <div class="cline"><span>{{ t.line }}</span><b>{{ step.childCount }} 个孩子</b></div>
          <div class="cline hero"><span>每月孩子支出</span><b>{{ signed(step.childExpense) }}（永久）</b></div>
        </div>
      </template>
      <template v-else>
        <div class="conv">
          <div class="cline"><span>{{ t.line }}</span><b>{{ signed(-step.amount) }}</b></div>
          <div class="cline hero cash"><span>银行储蓄</span><b>{{ fmt(step.cashBefore) }} → {{ fmt(cashAfter) }}</b></div>
        </div>
      </template>

      <p class="fineprint">{{ t.fine }}</p>
      <p class="fineprint">点一下跳过</p>
    </div>
  </div>
</template>
