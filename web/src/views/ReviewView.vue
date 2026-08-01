<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import type { CardDto } from '../types'
import { DECKS, SUBTYPE_NAMES, fieldRows } from '../entry-fields'

const router = useRouter()

const deck = ref('SMALL_DEAL')
const cards = ref<CardDto[]>([])
const mode = ref<'one' | 'list'>('one')
const q = ref('')
const idx = ref(0)
const checked = ref<Set<string>>(new Set())

const storeKey = computed(() => `cf-review-${deck.value}`)

function loadProgress() {
  try {
    checked.value = new Set(JSON.parse(localStorage.getItem(storeKey.value) ?? '[]'))
  } catch { checked.value = new Set() }
}
function saveProgress() {
  localStorage.setItem(storeKey.value, JSON.stringify([...checked.value]))
}

async function refresh() {
  cards.value = await (await fetch(`/api/entry/cards?deck=${deck.value}`)).json()
  loadProgress()
  idx.value = Math.min(idx.value, Math.max(0, cards.value.length - 1))
}
onMounted(refresh)
watch(deck, () => { idx.value = 0; q.value = ''; refresh() })

const current = computed<CardDto | undefined>(() => cards.value[idx.value])
const doneCount = computed(() => cards.value.filter(c => checked.value.has(c.id)).length)

const filtered = computed(() => {
  if (!q.value) return cards.value
  const needle = q.value.toLowerCase()
  return cards.value.filter(c =>
    c.title.toLowerCase().includes(needle)
    || c.id.includes(needle)
    || fieldRows(c).some(([, v]) => v.toLowerCase().includes(needle)))
})

function jumpTo(c: CardDto) {
  idx.value = cards.value.findIndex(x => x.id === c.id)
  mode.value = 'one'
  q.value = ''
}

function nextUnchecked(from: number) {
  const n = cards.value.length
  for (let step = 1; step <= n; step++) {
    const i = (from + step) % n
    if (!checked.value.has(cards.value[i].id)) return i
  }
  return from
}

function markOk() {
  const c = current.value
  if (!c) return
  checked.value.add(c.id)
  saveProgress()
  if (doneCount.value < cards.value.length) idx.value = nextUnchecked(idx.value)
}

async function markProblem() {
  const c = current.value
  if (!c) return
  const ok = await confirmAction({
    title: `「${c.title}」数值有误？`,
    lines: ['将跳转到录入工具修改这张卡'],
  })
  if (!ok) return
  router.push({ path: '/entry', query: { deck: deck.value, edit: c.id } })
}

async function resetProgress() {
  const ok = await confirmAction({
    title: `重置「${DECKS[deck.value]}」的核对进度？`,
    lines: [`当前已核对 ${doneCount.value}/${cards.value.length} 张`],
    danger: true, okText: '重置',
  })
  if (!ok) return
  checked.value = new Set()
  saveProgress()
  idx.value = 0
}
</script>

<template>
  <div class="page no-tabbar">
    <div class="row between">
      <h1>🔍 卡牌核对</h1>
      <button class="btn small ghost" @click="$router.push('/entry')">返回录入</button>
    </div>

    <div class="row wrap" style="margin:8px 0">
      <button v-for="(name, d) in DECKS" :key="d" class="btn small"
              :class="{ ghost: deck !== d }" @click="deck = d as string">{{ name }}</button>
    </div>
    <div class="row wrap" style="margin:8px 0">
      <button class="btn small" :class="{ ghost: mode !== 'one' }" @click="mode = 'one'">逐张核对</button>
      <button class="btn small" :class="{ ghost: mode !== 'list' }" @click="mode = 'list'">全字段清单</button>
      <span class="muted" style="margin-left:auto">已核对 {{ doneCount }}/{{ cards.length }}</span>
      <button class="btn small ghost" v-if="doneCount" @click="resetProgress">重置进度</button>
    </div>

    <input v-model="q" placeholder="搜索标题 / id / 数值…" />
    <div v-if="q" style="margin:6px 0">
      <div v-for="c in filtered" :key="c.id" class="card" @click="jumpTo(c)" style="cursor:pointer">
        <b>{{ c.title }}</b> <span class="muted">{{ c.id }}</span>
        <span v-if="checked.has(c.id)"> ✅</span>
      </div>
      <p v-if="!filtered.length" class="muted">无匹配</p>
    </div>

    <template v-if="!q && mode === 'one'">
      <p v-if="!cards.length" class="muted">本叠暂无卡牌</p>
      <div v-else-if="current" class="card" style="border-color:var(--gold)">
        <div class="row between">
          <span class="muted">{{ idx + 1 }} / {{ cards.length }}</span>
          <span v-if="checked.has(current.id)">✅ 已核对</span>
        </div>
        <h2 style="margin:8px 0">{{ current.title }}</h2>
        <p class="muted">{{ SUBTYPE_NAMES[current.subtype] }} · {{ current.id }}</p>
        <div v-for="[label, value] in fieldRows(current)" :key="label"
             class="row between" style="font-size:1.15em; padding:4px 0">
          <span class="muted">{{ label }}</span><b>{{ value }}</b>
        </div>
        <div class="row" style="margin-top:12px">
          <button class="btn grow" @click="markOk">✓ 与实体卡一致</button>
          <button class="btn warn" @click="markProblem">✗ 有问题</button>
        </div>
        <div class="row" style="margin-top:8px">
          <button class="btn small ghost grow" :disabled="idx === 0" @click="idx--">‹ 上一张</button>
          <button class="btn small ghost grow" :disabled="idx >= cards.length - 1" @click="idx++">下一张 ›</button>
        </div>
      </div>
    </template>

    <template v-if="!q && mode === 'list'">
      <p v-if="!cards.length" class="muted">本叠暂无卡牌</p>
      <div v-for="c in cards" :key="c.id" class="card">
        <div class="row between">
          <div><b>{{ c.title }}</b>
            <span class="badge" style="margin-left:6px">{{ SUBTYPE_NAMES[c.subtype] }}</span>
            <span v-if="checked.has(c.id)"> ✅</span>
          </div>
          <span class="muted">{{ c.id }}</span>
        </div>
        <div class="row wrap" style="gap:4px 14px; margin-top:4px">
          <span v-for="[label, value] in fieldRows(c)" :key="label" class="muted">
            {{ label }} <b style="color:var(--text)">{{ value }}</b>
          </span>
        </div>
      </div>
    </template>
  </div>
</template>
