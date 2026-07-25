<script setup lang="ts">
// 二维码渲染：uqr 只负责算矩阵，这里画成内联 SVG
// —— 矢量不糊、不吃 canvas、非安全上下文（局域网 http）照样能画，且不发任何外部请求
import { computed } from 'vue'
import { encode } from 'uqr'

const props = withDefaults(defineProps<{ text: string; size?: number }>(), { size: 240 })

const qr = computed(() => encode(props.text, { ecc: 'M', border: 2 }))

// 所有黑模块合并成一条 path，DOM 里只有一个节点
const path = computed(() => {
  const { size, data } = qr.value
  const parts: string[] = []
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++)
      if (data[y][x]) parts.push(`M${x} ${y}h1v1h-1z`)
  return parts.join('')
})
</script>

<template>
  <svg class="qrcode" :width="size" :height="size"
       :viewBox="`0 0 ${qr.size} ${qr.size}`" shape-rendering="crispEdges"
       role="img" aria-label="房间邀请二维码">
    <!-- 底色固定纯白：暖白纸感底会降低扫码器的对比度余量 -->
    <rect :width="qr.size" :height="qr.size" fill="#fff" />
    <path :d="path" fill="#15120C" />
  </svg>
</template>

<style scoped>
.qrcode {
  display: block;
  max-width: 100%;
  height: auto;
  border-radius: 10px;
  background: #fff;
}
</style>
