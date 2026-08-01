<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const IDX_KEY = 'manual:page'

const pages = ref<string[]>([])
const idx = ref(0)
const zoomed = ref(false)
const viewer = ref<HTMLElement | null>(null)

const pageUrl = (name: string) => `/api/manual/pages/${name}`

// 相邻页预取：扫描页单张 200~350KB，提前拉好翻页就不白屏
function prefetch(i: number) {
  const name = pages.value[i]
  if (name) new Image().src = pageUrl(name)
}

function go(delta: number) {
  const next = idx.value + delta
  if (next < 0 || next >= pages.value.length) return
  idx.value = next
  zoomed.value = false
  viewer.value?.scrollTo({ top: 0, left: 0 })
}

function toggleZoom() {
  zoomed.value = !zoomed.value
  nextTick(() => {
    const el = viewer.value
    if (!el) return
    // 放大后停在页面中间：扫描件正文是居中排版的
    el.scrollLeft = zoomed.value ? (el.scrollWidth - el.clientWidth) / 2 : 0
  })
}

watch(idx, (i) => {
  sessionStorage.setItem(IDX_KEY, String(i))
  prefetch(i + 1)
  prefetch(i - 1)
})

onMounted(async () => {
  const r = await fetch('/api/manual/pages')
  pages.value = (await r.json()).pages
  if (!pages.value.length) return
  // 从对局页点进来看一眼再返回，回来还在原页
  const saved = Number(sessionStorage.getItem(IDX_KEY))
  if (Number.isInteger(saved)) idx.value = Math.min(Math.max(saved, 0), pages.value.length - 1)
  prefetch(idx.value + 1)
})
</script>

<template>
  <div class="page no-tabbar">
    <div class="row between">
      <h1>📖 游戏说明书</h1>
      <button class="btn small ghost" @click="$router.back()">返回</button>
    </div>
    <template v-if="pages.length">
      <div class="row between" style="margin:8px 0">
        <button class="btn small ghost" :disabled="idx === 0" @click="go(-1)">上一页</button>
        <span class="muted">第 {{ idx + 1 }} / {{ pages.length }} 页</span>
        <button class="btn small ghost" :disabled="idx >= pages.length - 1" @click="go(1)">下一页</button>
      </div>
      <div ref="viewer" class="viewer" :class="{ zoomed }">
        <img :src="pageUrl(pages[idx])" :alt="`说明书第 ${idx + 1} 页`" @click="toggleZoom" />
      </div>
      <p class="muted hint">{{ zoomed ? '再点一下图片缩回整页，左右拖动看两侧' : '点一下图片放大看清小字，也可双指缩放' }}</p>
    </template>
    <div v-else class="card">
      <p class="muted">尚未生成说明书分页图。在项目根目录运行
        <code>python tools/build_manual_pages.py</code>，
        即可从 <code>docs/现金流游戏说明书.pdf</code> 生成分页图到
        <code>server/manual_pages/</code>，在此翻阅（离线可用）。</p>
    </div>
  </div>
</template>

<style scoped>
.viewer {
  overflow: auto;
  border-radius: 8px;
  background: #fff;
  -webkit-overflow-scrolling: touch;
}
.viewer img {
  display: block;
  width: 100%;
  cursor: zoom-in;
}
.viewer.zoomed img {
  width: 200%;
  max-width: none;
  cursor: zoom-out;
}
.hint {
  margin-top: 8px;
  text-align: center;
  font-size: 13px;
}
</style>
