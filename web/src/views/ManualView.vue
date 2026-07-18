<script setup lang="ts">
import { onMounted, ref } from 'vue'

const pages = ref<string[]>([])
const idx = ref(0)

onMounted(async () => {
  const r = await fetch('/api/manual/pages')
  pages.value = (await r.json()).pages
})
</script>

<template>
  <div class="page no-tabbar">
    <div class="row between">
      <h1>📖 游戏说明书</h1>
      <button class="small ghost" @click="$router.back()">返回</button>
    </div>
    <template v-if="pages.length">
      <div class="row between" style="margin:8px 0">
        <button class="small ghost" :disabled="idx === 0" @click="idx--">上一页</button>
        <span class="muted">第 {{ idx + 1 }} / {{ pages.length }} 页</span>
        <button class="small ghost" :disabled="idx >= pages.length - 1" @click="idx++">下一页</button>
      </div>
      <img :src="`/api/manual/pages/${pages[idx]}`"
           style="width:100%;border-radius:8px;background:#fff" />
    </template>
    <div v-else class="card">
      <p class="muted">尚未导入说明书扫描页。把 docs/棋盘细节 中的说明书页图片（PNG/JPG）放入
        <code>server/manual_pages/</code> 目录即可在此翻阅（离线可用）。</p>
    </div>
  </div>
</template>
