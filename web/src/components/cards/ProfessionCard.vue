<script setup lang="ts">
/** 职业卡：照实体卡的版式复刻。
 *  「您的职业」在最上，只有职业名是深色反白条；底下两行小字是抄写提示与目标。
 *  收入与支出各有一条只占中间一段宽度的黑条，下面是带框两栏：左逐项明细、右只放汇总。
 *  月现金流单独一行右对齐。最后资产与负债是两个并排黑条，共用一个两栏框。
 *  值为 0 的行不删掉，只降成浅灰 —— 实体卡上它们也在，玩家抄写时要按行对照。 */
import { computed } from 'vue'
import type { CardDto } from '../../types'

const props = defineProps<{ card: CardDto }>()

type Row = { label: string; value: string }
const raw = computed(() => props.card.raw ?? {})
const groups = computed(() => raw.value.groups ?? [])

function group(name: string): Row[] {
  return groups.value.find(g => g.name === name)?.rows ?? []
}

/** 汇总项进右栏，其余进左栏明细 */
const SUMMARY = new Set(['非工资收入', '总收入', '每个孩子支出', '总支出'])
const income = computed(() => group('收入'))
const incomeDetail = computed(() => income.value.filter(r => !SUMMARY.has(r.label)))
const incomeSum = computed(() => income.value.filter(r => SUMMARY.has(r.label)))
const expense = computed(() => group('支出').filter(r => r.label !== '月现金流'))
const expenseDetail = computed(() => expense.value.filter(r => !SUMMARY.has(r.label)))
const expenseSum = computed(() => expense.value.filter(r => SUMMARY.has(r.label)))
const cashflow = computed(() => group('支出').find(r => r.label === '月现金流')?.value ?? '')
const assets = computed(() => group('资产'))
const liabilities = computed(() => group('负债'))
const notes = computed(() => raw.value.notes ?? [])

/** 值是 0（不含 $0 之外的任何数字）时降成浅灰 */
const isZero = (v: string) => /^0$|^\$?0$/.test(v.trim())
</script>

<template>
  <div class="pcard">
    <div class="pcard-hd">{{ raw.subtitle || '您的职业' }}</div>
    <div class="pcard-name">{{ raw.title || card.title }}</div>
    <div v-if="raw.body?.[0]" class="pcard-tip">{{ raw.body[0] }}</div>
    <div v-if="raw.body?.[1]" class="pcard-goal">{{ raw.body[1] }}</div>

    <template v-if="income.length">
      <div class="pcard-band">收 入</div>
      <div class="pcard-grid">
        <div>
          <div v-for="r in incomeDetail" :key="r.label" class="pl" :class="{ dim: isZero(r.value) }">
            <span>{{ r.label }}</span><b>{{ r.value }}</b>
          </div>
          <div v-if="notes[0]" class="pcard-fine">{{ notes[0] }}</div>
        </div>
        <div>
          <div v-for="r in incomeSum" :key="r.label" class="pl k"><span>{{ r.label }}</span><b>{{ r.value }}</b></div>
        </div>
      </div>
    </template>

    <template v-if="expense.length">
      <div class="pcard-band">支 出</div>
      <div class="pcard-grid">
        <div>
          <div v-for="r in expenseDetail" :key="r.label" class="pl" :class="{ dim: isZero(r.value) }">
            <span>{{ r.label }}</span><b>{{ r.value }}</b>
          </div>
        </div>
        <div>
          <div v-for="r in expenseSum" :key="r.label" class="pl k"><span>{{ r.label }}</span><b>{{ r.value }}</b></div>
        </div>
      </div>
      <div v-if="notes[1]" class="pcard-fine">{{ notes[1] }}</div>
      <div v-if="cashflow" class="pcard-flow"><span>月现金流</span><b>{{ cashflow }}</b></div>
    </template>

    <template v-if="assets.length || liabilities.length">
      <div class="pcard-bands2"><span>资 产</span><span>负 债</span></div>
      <div class="pcard-grid">
        <div>
          <div v-for="r in assets" :key="r.label" class="pl" :class="{ dim: isZero(r.value) }">
            <span>{{ r.label }}</span><b>{{ r.value }}</b>
          </div>
        </div>
        <div>
          <div v-for="r in liabilities" :key="r.label" class="pl" :class="{ dim: isZero(r.value) }">
            <span>{{ r.label }}</span><b>{{ r.value }}</b>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
