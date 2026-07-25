<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadNickname, saveNickname } from '../store'

const router = useRouter()
const route = useRoute()
const nickname = ref(loadNickname())
const editing = loadNickname() !== ''   // 已有昵称即「修改」场景

function submit() {
  const n = nickname.value.trim()
  if (!n) return
  saveNickname(n)
  const back = String(route.query.redirect || '/')
  router.replace(back.startsWith('/') ? back : '/')
}
</script>

<template>
  <div class="page no-tabbar welcome">
    <div class="hero">
      <div class="logo">💸</div>
      <h1>现金流助手</h1>
      <p class="muted tagline">实体棋盘照常玩，手机自动记账。<br>抛开纸笔，告别算错账。</p>
    </div>

    <div class="card namecard">
      <label>{{ editing ? '修改昵称' : '给自己起个昵称' }}</label>
      <input v-model="nickname" maxlength="12" placeholder="例如：老王"
             @keyup.enter="submit" autofocus />
      <p class="muted hint">昵称会记在这台设备上，之后创建/加入房间都自动带上，随时可改。</p>
      <button class="block" style="margin-top:12px" :disabled="!nickname.trim()" @click="submit">
        {{ editing ? '保存' : '进入大厅' }} →
      </button>
    </div>
  </div>
</template>

<style scoped>
.welcome { display: flex; flex-direction: column; justify-content: center; min-height: 100dvh; padding-bottom: 40px; }
.hero { text-align: center; margin-bottom: 8px; }
.hero .logo { font-size: 56px; line-height: 1; }
.hero h1 { font-size: 2rem; margin: 10px 0 6px; }
.tagline { font-size: 14px; line-height: 1.7; }
.namecard { margin-top: 18px; }
.hint { margin: 8px 0 0; }
</style>
