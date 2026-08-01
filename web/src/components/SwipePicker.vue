<script setup lang="ts">
/** 横滑卡堆：一次一张，左右滑动核对整张卡。
 *
 *  四条规格（design 稿 §02）：
 *  ① 吸附 —— scroll-snap，松手必定停在某张正中；首尾两张靠左右留白也能滑到正中。
 *  ② 连续缩放 —— 离中心越远越小、越淡、越去色，**跟着手指连续变化**，
 *     用 smoothstep 缓动（两端平缓、中间过渡快），手指停在半路时不会显得僵。
 *  ③ 当前有描边 —— 正中那张加主色描边，与放大、提亮三个信号同时指向它。
 *  ④ 圆点可点 —— 不想滑就点圆点跳过去；热区由 CSS 扩到 28×28。
 *  「减弱动态效果」开启时缩放与淡出全部关掉，只保留吸附与描边。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  /** 每项要有稳定的 id 与用于朗读/回显的 name */
  items: { id: string; name: string }[]
  /** 当前居中项的 id（v-model） */
  modelValue?: string
  /** 卡片半宽（px）：职业卡宽些，梦想卡窄些 */
  halfWidth?: number
}>(), { halfWidth: 143 })

const emit = defineEmits<{ (e: 'update:modelValue', id: string): void }>()

const track = ref<HTMLElement | null>(null)
const currentIdx = ref(0)
const reduce = typeof matchMedia === 'function'
  && matchMedia('(prefers-reduced-motion: reduce)').matches

function centerOn(idx: number, smooth: boolean) {
  const el = track.value
  const item = el?.children[idx] as HTMLElement | undefined
  if (!el || !item) return
  const left = item.offsetLeft - (el.clientWidth - item.offsetWidth) / 2
  if (smooth && !reduce) el.scrollTo({ left, behavior: 'smooth' })
  else el.scrollLeft = left
}

function render() {
  const el = track.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const cx = r.left + r.width / 2
  let best = 0, bestD = Infinity
  Array.from(el.children).forEach((node, i) => {
    const item = node as HTMLElement
    const ir = item.getBoundingClientRect()
    const d = Math.abs(ir.left + ir.width / 2 - cx)
    if (d < bestD) { bestD = d; best = i }
    if (reduce) return
    // 归一化到「离中心一张卡宽」为完全退场
    const t = Math.min(1, d / (item.offsetWidth * 0.9))
    const e = t * t * (3 - 2 * t)                      // smoothstep
    item.style.transform = `scale(${(1 - 0.10 * e).toFixed(4)})`
    item.style.opacity = (1 - 0.55 * e).toFixed(3)
    item.style.filter = `saturate(${(1 - 0.5 * e).toFixed(3)})`
  })
  if (best !== currentIdx.value) {
    currentIdx.value = best
    const id = props.items[best]?.id
    if (id && id !== props.modelValue) emit('update:modelValue', id)
  }
}

let ticking = false
function onScroll() {
  if (ticking) return
  ticking = true
  requestAnimationFrame(() => { render(); ticking = false })
}

onMounted(() => {
  window.addEventListener('resize', render)
  nextTick(() => {
    const i = Math.max(0, props.items.findIndex(x => x.id === props.modelValue))
    centerOn(i, false)
    render()
  })
})
onBeforeUnmount(() => window.removeEventListener('resize', render))

// 卡堆是异步加载的：拿到数据后要重新定位到当前项
watch(() => props.items.length, () => nextTick(() => {
  const i = Math.max(0, props.items.findIndex(x => x.id === props.modelValue))
  centerOn(i, false)
  render()
}))
</script>

<template>
  <div>
    <div ref="track" class="swipe" :style="{ '--swipe-half': halfWidth + 'px' }" @scroll.passive="onScroll">
      <div v-for="(it, i) in items" :key="it.id" :class="{ 'is-current': i === currentIdx }">
        <slot :item="it" :index="i" :current="i === currentIdx" />
      </div>
    </div>
    <div class="swipe-dots">
      <button v-for="(it, i) in items" :key="it.id" type="button"
              :class="{ on: i === currentIdx }"
              :aria-label="`第 ${i + 1} 张：${it.name}`"
              @click="centerOn(i, true)" />
    </div>
    <div class="swipe-cap">
      <span>当前 <b>{{ items[currentIdx]?.name ?? '—' }}</b></span>
      <slot name="meta" :current="items[currentIdx]" />
    </div>
  </div>
</template>

<style scoped>
/* 正中那张：主色描边（与放大、提亮三个信号同时指向它） */
.swipe > .is-current > :deep(*) { outline: 2px solid var(--brand); outline-offset: 3px; border-radius: var(--r); }
</style>
