<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const IDX_KEY = 'manual:page'

const pages = ref<string[]>([])
// 拉到之前**两支都不渲染**：没有这一态的话，`v-else` 那句「请去跑 build_manual_pages.py」
// 必然先渲染一帧——而图明明生成好了，等于每次进说明书都先闪一句假话
const loading = ref(true)
const failed = ref(false)
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
  try {
    const r = await fetch('/api/manual/pages')
    pages.value = (await r.json()).pages
  } catch {
    // 「拉不到」和「真的没生成」是两回事，空状态的文案分开给：
    // 断网时叫人去跑构建脚本，是把一句假话换成另一句假话
    failed.value = true
  } finally {
    loading.value = false
  }
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
    <!-- 载入中什么都不给：这一屏通常零延迟（分页图随镜像交付、还被 PWA 预缓存），
         摆一句「正在载入…」只是把一闪而过的噪音换成另一种 -->
    <div v-else-if="!loading" class="card">
      <p v-if="failed" class="muted">没能取到说明书分页图，请检查网络后重试。</p>
      <p v-else class="muted">尚未生成说明书分页图。在项目根目录运行
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
