<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { keyNumbers } from '../cardinfo'
import { useGame } from '../store'
import type { CardDto } from '../types'

const props = defineProps<{ deck: string; deckName: string }>()
const emit = defineEmits<{ (e: 'picked', card: CardDto): void; (e: 'close'): void }>()

const game = useGame()
const q = ref('')
const cards = ref<CardDto[]>([])
const recognizing = ref(false)
const fileInput = ref<HTMLInputElement>()

async function search() {
  cards.value = await game.fetchCards(props.deck, q.value)
}
onMounted(search)

/** 拍照识别（FR-9）：本期识别链返回空候选 → 停留在手动检索 */
async function onPhoto(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !game.session) return
  recognizing.value = true
  try {
    const fd = new FormData()
    fd.append('image', file)
    fd.append('deckHint', props.deck)
    const r = await fetch(`/api/rooms/${game.session.roomCode}/recognize`, { method: 'POST', body: fd })
    const d = await r.json()
    if (!d.candidates?.length) {
      game.lastError = '识别不可用或未识别到，请手动检索选卡'
    } else {
      cards.value = d.candidates.map((c: any) =>
        cards.value.find(x => x.id === c.card_id)).filter(Boolean)
    }
  } finally { recognizing.value = false }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <div class="row between">
        <h2>选卡：{{ deckName }}</h2>
        <button class="small ghost" @click="emit('close')">关闭</button>
      </div>
      <div class="row" style="margin:8px 0">
        <input v-model="q" placeholder="搜标题 / 关键词 / 金额" @input="search" />
        <button class="small ghost" :disabled="recognizing" @click="fileInput?.click()">
          {{ recognizing ? '识别中…' : '📷 拍照' }}
        </button>
        <input ref="fileInput" type="file" accept="image/*" capture="environment"
               style="display:none" @change="onPhoto" />
      </div>
      <div v-for="c in cards" :key="c.id" class="list-item" @click="emit('picked', c)">
        <b>{{ c.title }}</b>
        <div class="muted">{{ keyNumbers(c) }}</div>
      </div>
      <p v-if="!cards.length" class="muted">没有匹配的卡，请换个关键词</p>
    </div>
  </div>
</template>
