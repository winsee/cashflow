<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { CardDto } from '../types'
import { DECKS, FIELDS, SUBTYPES, SUBTYPE_NAMES, readField } from '../entry-fields'

const deck = ref('SMALL_DEAL')
const cards = ref<CardDto[]>([])
const stats = ref<Record<string, { entry: number; runtime: number }>>({})
const editing = ref(false)
const form = ref<Record<string, any>>({})
const msg = ref('')

async function refresh() {
  cards.value = await (await fetch(`/api/entry/cards?deck=${deck.value}`)).json()
  stats.value = await (await fetch('/api/entry/stats')).json()
}

// 核对页「✗ 有问题」带 ?deck=&edit= 跳回来，直接打开对应卡的编辑表单
const route = useRoute()
onMounted(async () => {
  const qDeck = route.query.deck as string | undefined
  if (qDeck && DECKS[qDeck]) deck.value = qDeck
  await refresh()
  const editId = route.query.edit as string | undefined
  const target = editId && cards.value.find(c => c.id === editId)
  if (target) editCard(target)
})

// 多人同时录入：页面可见时每 5s 轮询，别人保存的卡自动出现在列表
const timer = window.setInterval(() => {
  if (!document.hidden && !editing.value) refresh()
}, 5000)
onUnmounted(() => window.clearInterval(timer))

const subtype = computed(() => form.value.subtype ?? SUBTYPES[deck.value][0])

function formDirty(): boolean {
  return editing.value && Object.entries(form.value).some(
    ([k, v]) => !['id', 'subtype'].includes(k) && v !== '' && v !== undefined && v !== null)
}

function confirmDiscard(): boolean {
  return !formDirty() || confirm('表单尚未保存，确定放弃当前编辑？')
}

function switchDeck(d: string) {
  if (!confirmDiscard()) return
  editing.value = false
  deck.value = d
  refresh()
}

function newCard() {
  if (!confirmDiscard()) return
  form.value = { id: '', title: '', subtype: SUBTYPES[deck.value][0], keywords: '' }
  editing.value = true
}

function editCard(c: CardDto) {
  if (!confirmDiscard()) return
  const f: Record<string, any> = { id: c.id, title: c.title, subtype: c.subtype, keywords: '' }
  for (const [key] of FIELDS[c.subtype] ?? []) f[key] = readField(c.data, key) ?? ''
  editing.value = true
  form.value = f
}

function cancelEdit() {
  if (!confirmDiscard()) return
  editing.value = false
}

function summary(data: Record<string, any>): string {
  return (FIELDS[subtype.value] ?? [])
    .map(([key, label]) => {
      const v = readField(data, key)
      return v === undefined || v === '' ? null : `${label}=${v}`
    })
    .filter(Boolean).join('，')
}

async function save() {
  const data: Record<string, any> = {}
  for (const [key, label, typ] of FIELDS[subtype.value]) {
    let v = form.value[key]
    if (v === '' || v === undefined || v === null) continue
    if (typ === 'n') {
      v = Number(String(v).replace(/[,，$￥\s]/g, ''))   // 千分位/全半角清洗
      if (Number.isNaN(v)) { msg.value = `❌ ${label} 不是有效数字`; return }
    }
    if (key.includes('.')) {
      const [head, tail] = key.split('.')
      if (head === 'priceRange') {
        data.priceRange = data.priceRange ?? []
        data.priceRange[Number(tail)] = v
      } else {
        data[head] = data[head] ?? {}
        data[head][tail] = v
      }
    } else data[key] = v
  }
  if (data.priceRange !== undefined) {
    const [lo, hi] = data.priceRange
    if (lo === undefined || hi === undefined) { msg.value = '❌ 价格区间需低/高都填（或都不填）'; return }
    if (lo > hi) { msg.value = '❌ 价格区间下限不能大于上限'; return }
  }
  if (!form.value.title) { msg.value = '❌ 标题不能为空'; return }
  const isEdit = !!form.value.id
  const hint = isEdit
    ? `将覆盖已有卡「${form.value.title}」(${form.value.id})：\n${summary(data)}\n确认保存？`
    : `新增「${form.value.title}」(${SUBTYPE_NAMES[subtype.value]})：\n${summary(data)}\n确认入库？`
  if (!confirm(hint)) return
  const body = {
    id: form.value.id ?? '', deck: deck.value, subtype: subtype.value,
    title: form.value.title, data,
    ocr_keywords: String(form.value.keywords ?? '').split(/[,，]/).map(s => s.trim()).filter(Boolean),
  }
  const r = await fetch('/api/entry/cards', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const d = await r.json()
  if (!r.ok) { msg.value = '❌ ' + d.message; return }
  msg.value = `✅ 已保存 ${d.id}${d.replaced ? '（覆盖）' : ''}，写回 JSON`
  editing.value = false
  refresh()
}

async function remove(c: CardDto) {
  if (!confirm(`删除「${c.title}」？（从 JSON 文件中移除）`)) return
  const r = await fetch(`/api/entry/cards/${c.id}`, { method: 'DELETE' })
  const d = await r.json()
  msg.value = r.ok ? `✅ 已删除「${c.title}」` : '❌ ' + d.message
  refresh()
}

async function clearDeck() {
  const n = cards.value.length
  if (!confirm(`清空录入库「${DECKS[deck.value]}」整叠？（不影响游戏运行时库）`)) return
  if (!confirm(`再次确认：将删除录入库 ${DECKS[deck.value]} 全部 ${n} 张卡！`)) return
  const r = await fetch(`/api/entry/decks/${deck.value}`, { method: 'DELETE' })
  const d = await r.json()
  msg.value = r.ok ? `✅ 已清空录入库 ${DECKS[deck.value]}` : '❌ ' + d.message
  refresh()
}

function diffText(diff: Record<string, { added: string[]; removed: string[]; changed: string[] }>): string {
  const lines: string[] = []
  for (const [d, x] of Object.entries(diff)) {
    if (!x.added.length && !x.removed.length && !x.changed.length) continue
    lines.push(`${DECKS[d]}：新增 ${x.added.length}、修改 ${x.changed.length}、删除 ${x.removed.length}`)
  }
  return lines.length ? lines.join('\n') : '（与运行时库无差异）'
}

async function publish() {
  const pr = await fetch('/api/entry/publish/preview')
  const pd = await pr.json()
  if (!pr.ok) { msg.value = '❌ 发布前校验失败：' + pd.message; return }
  const text = diffText(pd.diff)
  if (!confirm(`将录入库发布到游戏运行时库：\n${text}\n\n进行中的对局不受影响（新抽卡用新数据）。确认发布？`)) return
  const r = await fetch('/api/entry/publish', { method: 'POST' })
  const d = await r.json()
  msg.value = r.ok ? '✅ 已发布到游戏运行时库' : '❌ ' + d.message
  refresh()
}
</script>

<template>
  <div class="page no-tabbar">
    <div class="row between">
      <h1>🗂️ 卡牌录入工具</h1>
      <div class="row">
        <button class="small ghost" @click="$router.push('/entry/review')">🔍 核对</button>
        <button class="small ghost" @click="$router.back()">返回</button>
        <button class="small ghost" @click="$router.push('/')">🏠 大厅</button>
      </div>
    </div>
    <p class="muted">录入库为纯数据记录（server/data/entry/），随录随存；
      点「发布」才导入游戏运行时库。各叠 录入/游戏：
      <span v-for="(s, d) in stats" :key="d">{{ DECKS[d] }} {{ s.entry }}/{{ s.runtime }} · </span></p>

    <div class="row wrap" style="margin:8px 0">
      <button v-for="(name, d) in DECKS" :key="d" class="small"
              :class="{ ghost: deck !== d }" @click="switchDeck(d as string)">{{ name }}</button>
      <button class="small gold" @click="newCard">＋ 新增</button>
      <button class="small" @click="publish">🚀 发布</button>
      <button class="small warn" v-if="cards.length" @click="clearDeck">清空本叠</button>
    </div>
    <p v-if="msg" class="muted">{{ msg }}</p>

    <div v-if="editing" class="card" style="border-color:var(--gold)">
      <p v-if="form.id" class="muted">编辑中：{{ form.id }}（id 由系统生成，不可改）</p>
      <p v-else class="muted">新卡 id 将由系统自动生成</p>
      <label>标题（简短，不抄整段卡面文案）</label>
      <input v-model="form.title" />
      <label>子类型</label>
      <select v-model="form.subtype">
        <option v-for="s in SUBTYPES[deck]" :key="s" :value="s">{{ SUBTYPE_NAMES[s] }}</option>
      </select>
      <template v-for="[key, label] in FIELDS[subtype]" :key="key">
        <label>{{ label }}</label>
        <input v-model="form[key]" />
      </template>
      <label>识别关键词（逗号分隔；同名多版本卡每张必填，用于区分）</label>
      <input v-model="form.keywords" placeholder="如：游艇, 17,000, 340" />
      <div class="row" style="margin-top:10px">
        <button class="grow" @click="save">保存入库</button>
        <button class="ghost" @click="cancelEdit">取消</button>
      </div>
    </div>

    <div v-for="c in cards" :key="c.id" class="card">
      <div class="row between">
        <div>
          <b>{{ c.title }}</b>
          <span class="badge" style="margin-left:6px">{{ SUBTYPE_NAMES[c.subtype] }}</span>
          <div class="muted">{{ c.id }}</div>
        </div>
        <div class="row">
          <button class="small ghost" @click="editCard(c)">改</button>
          <button class="small warn" @click="remove(c)">删</button>
        </div>
      </div>
    </div>
  </div>
</template>
