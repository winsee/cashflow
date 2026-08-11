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
 *  **两条节拍表由 `variant` 分开**（design/09 §5.4 v1.0）：牌堆发牌有「飞入放大」那一拍，
 *  职业卡揭牌没有（牌已经在屏上被点了）。共用一段 keyframes 的代价是职业卡白演 0.43s 缩放。
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
  /** 哪一条节拍表。两条路径的拍子本来就不同，**不该共用一段 keyframes**：
   *  - `deal`（默认）= 牌堆发牌，§5.1 拍 6–7：牌背飞向屏心并放大 0.43s + 翻牌 0.52s；
   *  - `reveal` = 职业卡揭牌，§5.4 拍 1–2：牌背待命（静止，与页内那张同尺寸）+ 整 0.95s 纯翻牌。
   *
   *  职业卡是玩家点了**页内那张牌背**才起的，它已经在屏上了；再演一遍飞入放大，
   *  屏上就成了「先缩小、再长回来、然后正面突然蹦出来」——0.43s 花在不属于它的拍子上，
   *  真正的翻转只剩 0.52s。（第四轮试玩「怎么没有翻面的动画」正是这个） */
  variant?: 'deal' | 'reveal'
}>()
const emit = defineEmits<{ (e: 'skip'): void }>()

const slots = useSlots()
const color = computed(() => DECK_COLOR[props.deck] ?? 'var(--line-2)')
const label = computed(() => DECK_LABEL[props.deck] ?? '牌堆')
/** 卡面到齐了没有。牌堆发牌（§5.3）挂载时 `card` 就有值，恒为真、逐帧不变；
 *  只有职业卡（§5.4）会经历一个几十毫秒的待命拍。
 *
 *  **必须在渲染时求值，不能写成 `computed`**（v1.0 修）：`useSlots()` 拿到的是组件实例上
 *  那个**普通对象**，父组件重渲染时它被就地改写，没有任何响应式依赖可以追踪。
 *  写成 computed 的话，职业卡这条路径上 `props.card` 恒为 undefined、永远不会让它失效——
 *  第一次算出 `false` 就永远是 `false`，`.flipping` 一辈子加不上，
 *  **整段翻牌动画一次都没播过**（第四轮试玩「怎么没有翻面的动画」的真正根因：
 *  屏上只剩基础 transform 那张缩小的牌背，帘幕一撤，页内的正面直接顶上来）。 */
const ready = () => !!slots.default || !!props.card
</script>

<template>
  <div class="curtain deal-curtain"
       :style="{ '--deck': color, background: `color-mix(in srgb, ${color} 12%, var(--bg))` }"
       @click="emit('skip')">
    <div class="deal-card">
      <div class="deal-inner" :class="{ flipping: ready(), reveal: props.variant === 'reveal' }">
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
