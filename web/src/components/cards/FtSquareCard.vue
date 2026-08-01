<script setup lang="ts">
/** 快车道格子卡：棋盘外环的绿格（企业投资）与粉格（梦想）。
 *  横排数值、没有正文 —— 它是「踩上去的位置」，不是从牌堆抽出来的东西。
 *  多一个「已被买断」态：整体降透明、去掉颜色、状态写在数值位上。 */
defineProps<{
  kind: 'biz' | 'dream'
  /** 类别行文案，如「企业投资 · 需掷骰」「梦想 · 这是你的」 */
  kindLabel: string
  name: string
  /** 横排数值，标签 + 值 */
  nums?: { label: string; value: string }[]
  /** 已被别人买走/认领 */
  taken?: boolean
  /** 我自己的梦想：金色描边，快车道上只有它能直接终结游戏 */
  mine?: boolean
  /** 现金不够：底色转灰，但仍然显示，不隐藏 */
  poor?: boolean
  tip?: string
}>()
</script>

<template>
  <div class="fcard" :class="[kind, { taken, mine, poor: poor && !taken }]">
    <div class="fcard-kind">{{ kindLabel }}</div>
    <div class="row between top">
      <div class="grow">
        <div class="fcard-name">{{ name }}</div>
        <div v-if="nums?.length" class="fcard-nums">
          <div v-for="n in nums" :key="n.label">
            <span>{{ n.label }}</span><b>{{ n.value }}</b>
          </div>
        </div>
      </div>
      <slot name="action" />
    </div>
    <p v-if="tip" class="fcard-tip">{{ tip }}</p>
    <slot />
  </div>
</template>
