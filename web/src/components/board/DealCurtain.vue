<script setup lang="ts">
/** 全屏发牌翻牌（design/09 §5.3）：牌背飞向屏心 → Y 轴 3D 翻转 → 定格 → 收进抽屉。
 *
 *  **全员同步播放**——说明书要求把卡「大声读出来」，线上就该人人看见同一张牌翻过来。
 *  帘幕底色 = 该牌堆色降到 12% 叠在纸底上：牌翻过来之前就知道面对的是机会还是额外支出。
 *  牌背是米白卡纸 + 该牌堆色双线边框 + 宋体牌堆名，和 GameCard 的正面同一套材质。
 *
 *  点击任意处**终止**整条演出序列并刷到终态（不是加速）。
 *
 *  **卡面由调用方决定**：默认插槽不传就照旧渲染 `GameCard`，职业卡场景传 `ProfessionCard`
 *  （design/09 §1.4.1）。发牌组件不该认识职业卡——那是调用方的知识；
 *  而翻牌的 3D 结构、牌背材质、帘幕基座只该有一份。
 *
 *  **卡面没到就不起翻**（design/09 §5.4 v0.5）：牌背是 `inset:0` 贴着牌面的，牌面高度一变
 *  牌背跟着变。职业卡那条路径是「帘幕先落下、请求还在路上」，卡面会在翻转途中换进来——
 *  于是一条扁扁的牌背忽然长成一整张。所以卡没到就停在拍 1「牌背待命」，到了才加 `.flipping`。
 */
import { computed, useSlots } from 'vue'
import { DECK_COLOR, DECK_LABEL } from '../../decks'
import type { CardDto } from '../../types'
import GameCard from '../cards/GameCard.vue'

const props = defineProps<{
  deck: string
  title: string
  /** 卡面原文；还没拉到就只显示牌背与标题，不阻塞演出 */
  card?: CardDto | null
}>()
const emit = defineEmits<{ (e: 'skip'): void }>()

const slots = useSlots()
const color = computed(() => DECK_COLOR[props.deck] ?? 'var(--line-2)')
const label = computed(() => DECK_LABEL[props.deck] ?? '牌堆')
/** 卡面到齐了没有。牌堆发牌（§5.3）挂载时 `card` 就有值，恒为真、逐帧不变；
 *  只有职业卡（§5.4）会经历一个几十毫秒的待命拍 */
const ready = computed(() => !!slots.default || !!props.card)
</script>

<template>
  <div class="curtain deal-curtain"
       :style="{ '--deck': color, background: `color-mix(in srgb, ${color} 12%, var(--bg))` }"
       @click="emit('skip')">
    <div class="deal-card">
      <div class="deal-inner" :class="{ flipping: ready }">
        <div class="deal-face">
          <slot>
            <GameCard v-if="props.card" :card="props.card" />
            <!-- 占位卡面撑住 3:4（与页内 `.prof-back` 同一比例），牌背才有个稳定的尺寸可跟 -->
            <div v-else class="gcard hold"><div class="gcard-title">{{ props.title }}</div></div>
          </slot>
        </div>
        <div class="deal-back card-back" :style="{ color }">{{ label }}</div>
      </div>
    </div>
    <p class="muted" style="margin-top:14px">点一下跳过</p>
  </div>
</template>
