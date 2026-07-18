<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useGame } from '../store'
import type { CardDto } from '../types'

const game = useGame()

const DECKS: Record<string, string> = {
  SMALL_DEAL: '小生意', BIG_DEAL: '大买卖', MARKET: '市场风云',
  DOODAD: '额外支出', PROFESSION: '职业卡',
}
const SUBTYPES: Record<string, string[]> = {
  SMALL_DEAL: ['REALESTATE', 'STOCK_OFFER', 'STOCK_EVENT', 'LOSS_EVENT'],
  BIG_DEAL: ['REALESTATE', 'BUSINESS', 'EXPENSE_EVENT'],
  MARKET: ['BUYER_OFFER', 'MULTIPLE_OFFER', 'ECONOMY_EVENT'],
  DOODAD: ['CASH', 'CREDIT_OPTION', 'INSTALLMENT'],
  PROFESSION: ['PROFESSION'],
}
const SUBTYPE_NAMES: Record<string, string> = {
  REALESTATE: '房地产', STOCK_OFFER: '股票报价', STOCK_EVENT: '拆并股', LOSS_EVENT: '损失事件',
  BUSINESS: '企业投资', EXPENSE_EVENT: '维修支出', BUYER_OFFER: '定价求购',
  MULTIPLE_OFFER: '倍数收购', ECONOMY_EVENT: '经济事件', CASH: '现金支出',
  CREDIT_OPTION: '可信用卡', INSTALLMENT: '分期负债', PROFESSION: '职业',
}
// 字段模板（design/04 §3），n=数字 s=文本
const FIELDS: Record<string, [string, string, 'n' | 's'][]> = {
  REALESTATE: [['assetType', '资产类型(如 3室2厅)', 's'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '抵押贷款', 'n'], ['cashflow', '月现金流', 'n'], ['roiPct', '收益率%', 'n']],
  BUSINESS: [['assetType', '资产类型', 's'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '负债', 'n'], ['cashflow', '月现金流', 'n']],
  STOCK_OFFER: [['symbol', '代码', 's'], ['price', '今日价格', 'n'], ['dividendPerShare', '每股红利', 'n']],
  STOCK_EVENT: [['symbol', '代码', 's'], ['ratio', '比例(如 2:1)', 's']],
  LOSS_EVENT: [['condition', '条件(hasRentalProperty/hasChildren/空)', 's'], ['amount', '金额', 'n']],
  EXPENSE_EVENT: [['targetAssetType', '目标资产类型', 's'], ['amountPerUnit', '每套金额', 'n']],
  BUYER_OFFER: [['targetAssetType', '目标资产类型', 's'], ['pricePerUnit', '每套价格', 'n']],
  MULTIPLE_OFFER: [['targetAssetType', '目标资产类型', 's'], ['multiple', '倍数', 'n']],
  ECONOMY_EVENT: [['kind', '类型(FORCED_SURRENDER)', 's'], ['targetAssetType', '目标资产类型', 's']],
  CASH: [['amount', '金额', 'n'], ['condition', '条件(hasChildren/空)', 's']],
  CREDIT_OPTION: [['amount', '金额', 'n'], ['creditMonthly', '信用卡月供', 'n']],
  INSTALLMENT: [['downPayment', '首付', 'n'], ['liability', '负债', 'n'], ['liabilityName', '负债名称', 's'], ['monthly', '月供', 'n']],
  PROFESSION: [['salary', '工资', 'n'], ['taxes', '税金', 'n'], ['mortgagePayment', '住房抵押支出', 'n'], ['schoolLoanPayment', '教育贷款支出', 'n'], ['carLoanPayment', '购车贷款支出', 'n'], ['creditCardPayment', '信用卡支出', 'n'], ['otherExpenses', '其他支出', 'n'], ['extraExpenses', '额外支出', 'n'], ['perChildExpense', '每孩支出', 'n'], ['savings', '储蓄', 'n'], ['liabilities.mortgage', '负债·住房抵押', 'n'], ['liabilities.schoolLoan', '负债·教育贷款', 'n'], ['liabilities.carLoan', '负债·购车贷款', 'n'], ['liabilities.creditCard', '负债·信用卡', 'n'], ['liabilities.extra', '负债·额外', 'n']],
}

const deck = ref('SMALL_DEAL')
const cards = ref<CardDto[]>([])
const stats = ref<Record<string, number>>({})
const editing = ref(false)
const form = ref<Record<string, any>>({})
const msg = ref('')

async function refresh() {
  cards.value = await game.fetchCards(deck.value)
  stats.value = await (await fetch('/api/entry/stats')).json()
}
onMounted(refresh)

const subtype = computed(() => form.value.subtype ?? SUBTYPES[deck.value][0])

function newCard() {
  form.value = { id: '', title: '', subtype: SUBTYPES[deck.value][0], keywords: '' }
  editing.value = true
}

function editCard(c: CardDto) {
  const f: Record<string, any> = { id: c.id, title: c.title, subtype: c.subtype, keywords: '' }
  for (const [key] of FIELDS[c.subtype] ?? []) {
    if (key.startsWith('liabilities.')) f[key] = c.data.liabilities?.[key.split('.')[1]] ?? 0
    else f[key] = c.data[key] ?? (typeof c.data[key] === 'string' ? '' : undefined)
  }
  editing.value = true
  form.value = f
}

async function save() {
  const data: Record<string, any> = {}
  for (const [key, , typ] of FIELDS[subtype.value]) {
    let v = form.value[key]
    if (v === '' || v === undefined || v === null) continue
    if (typ === 'n') v = Number(String(v).replace(/[,，$￥\s]/g, ''))   // 千分位/全半角清洗
    if (key.startsWith('liabilities.')) {
      data.liabilities = data.liabilities ?? {}
      data.liabilities[key.split('.')[1]] = v
    } else data[key] = v
  }
  const body = {
    id: form.value.id, deck: deck.value, subtype: subtype.value,
    title: form.value.title, data,
    ocr_keywords: String(form.value.keywords ?? '').split(/[,，]/).map(s => s.trim()).filter(Boolean),
  }
  const r = await fetch('/api/entry/cards', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const d = await r.json()
  if (!r.ok) { msg.value = '❌ ' + d.message; return }
  msg.value = '✅ 已保存并写回 JSON'
  editing.value = false
  refresh()
}

async function remove(id: string) {
  if (!confirm(`删除卡 ${id}？（写回 JSON 文件）`)) return
  await fetch(`/api/entry/cards/${id}`, { method: 'DELETE' })
  refresh()
}
</script>

<template>
  <div class="page no-tabbar">
    <div class="row between">
      <h1>🗂️ 卡牌录入工具</h1>
      <button class="small ghost" @click="$router.back()">返回</button>
    </div>
    <p class="muted">保存即写回 server/data/cards/*.json（权威数据源，git 版本管理）。
      各叠进度：<span v-for="(n, d) in stats" :key="d">{{ DECKS[d] }} {{ n }} 张 · </span></p>

    <div class="row wrap" style="margin:8px 0">
      <button v-for="(name, d) in DECKS" :key="d" class="small"
              :class="{ ghost: deck !== d }" @click="deck = d as string; refresh()">{{ name }}</button>
      <button class="small gold" @click="newCard">＋ 新增</button>
    </div>
    <p v-if="msg" class="muted">{{ msg }}</p>

    <div v-if="editing" class="card" style="border-color:var(--gold)">
      <label>卡 id（小写字母数字连字符，如 sd-house-2b1b-01）</label>
      <input v-model="form.id" />
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
      <label>识别关键词（逗号分隔：标题词/代码/显著金额）</label>
      <input v-model="form.keywords" placeholder="如：游艇, 17,000, 340" />
      <div class="row" style="margin-top:10px">
        <button class="grow" @click="save">保存入库</button>
        <button class="ghost" @click="editing = false">取消</button>
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
          <button class="small warn" @click="remove(c.id)">删</button>
        </div>
      </div>
    </div>
  </div>
</template>
