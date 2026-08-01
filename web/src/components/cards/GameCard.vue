<script setup lang="ts">
/** 牌堆卡面：照实体卡复刻 —— 米白卡纸、宋体正文首行缩进两字、底部两栏数值、顶部牌堆色条。
 *  内容一律取 raw（卡面原文逐字转录），**不参与阶段换肤**：桌上那张不会因为你换了赛道就变色。
 *  raw 缺失时退回 title + data 的关键数字，保证永远能显示点什么。 */
import { computed } from 'vue'
import { keyNumbers } from '../../cardinfo'
import { DECK_COLOR, DECK_LABEL } from '../../decks'
import type { CardDto } from '../../types'

const props = defineProps<{ card: CardDto; compact?: boolean }>()

const raw = computed(() => props.card.raw ?? {})
const color = computed(() => DECK_COLOR[props.card.deck] ?? 'var(--deck-small)')
const label = computed(() => DECK_LABEL[props.card.deck] ?? props.card.deck)
const fields = computed(() => raw.value.fields ?? [])
const body = computed(() => raw.value.body ?? [])
const notes = computed(() => raw.value.notes ?? [])
const fallback = computed(() => (!body.value.length && !fields.value.length) ? keyNumbers(props.card) : '')
</script>

<template>
  <div class="gcard" :class="{ compact }" :style="{ '--dc': color }">
    <div class="gcard-deck">{{ label }}</div>
    <h4 class="gcard-title">{{ raw.title || card.title }}</h4>
    <div v-if="body.length" class="gcard-body">
      <p v-for="(p, i) in body" :key="i">{{ p }}</p>
    </div>
    <div v-if="fields.length" class="gcard-fields">
      <div v-for="(f, i) in fields" :key="i">
        <span>{{ f.label }}</span><b>{{ f.value }}</b>
      </div>
    </div>
    <div v-if="fallback" class="gcard-note">{{ fallback }}</div>
    <div v-for="(n, i) in notes" :key="'n' + i" class="gcard-note">{{ n }}</div>
  </div>
</template>
