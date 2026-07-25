<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { keyNumbers } from '../cardinfo'
import { useGame } from '../store'
import type { CardDto } from '../types'

const props = defineProps<{ deck: string; deckName: string }>()
const emit = defineEmits<{ (e: 'picked', card: CardDto): void; (e: 'close'): void }>()

const game = useGame()
const q = ref('')
const cards = ref<CardDto[]>([])
const allCards = ref<CardDto[]>([])
const recognizing = ref(false)
const fileInput = ref<HTMLInputElement>()
const videoEl = ref<HTMLVideoElement>()

// 扫描框（FR-9）：实时取景连续识别；getUserMedia 仅在 HTTPS/localhost 可用，
// 非安全上下文自动隐藏扫描入口，仅留系统相机拍照兜底
const scanSupported = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
const scanning = ref(false)
const scanStatus = ref('')
const liveCands = ref<{ card: CardDto; score: number }[]>([])
let stream: MediaStream | null = null
let lastRecognitionId = 0
// 连续硬失败（超时 / 服务不可用 / 网络断）计数：不能一直每 1.2s 空转发帧，
// 小内存云端实例上那等于持续把服务器往 OOM 上推
let failStreak = 0
const MAX_FAIL_STREAK = 3

/** 识别一次的结果：reason 由服务端给（见 RecognizeOutcome），前端据此分文案 */
type RecogResult = { hit: boolean; reason: string; status: number; ms: number }

async function search() {
  cards.value = await game.fetchCards(props.deck, q.value)
}
onMounted(async () => {
  await search()
  allCards.value = await game.fetchCards(props.deck)
  if (scanSupported) startScan()
})
onBeforeUnmount(stopScan)

function cardById(id: string): CardDto | undefined {
  return allCards.value.find(c => c.id === id) ?? cards.value.find(c => c.id === id)
}

/** 识别请求：扫描帧与拍照文件共用 */
async function recognizeBlob(blob: Blob): Promise<RecogResult> {
  if (!game.session) return { hit: false, reason: 'no_session', status: 0, ms: 0 }
  const fd = new FormData()
  fd.append('image', blob, 'frame.jpg')
  fd.append('deckHint', props.deck)
  const r = await fetch(`/api/rooms/${game.session.roomCode}/recognize`, { method: 'POST', body: fd })
  if (!r.ok) return { hit: false, reason: 'http', status: r.status, ms: 0 }
  const d = await r.json()
  lastRecognitionId = d.recognitionId ?? 0
  const found = (d.candidates ?? [])
    .map((c: any) => ({ card: cardById(c.card_id), score: c.score }))
    .filter((x: any) => x.card)
  liveCands.value = found
  return { hit: found.length > 0, reason: d.reason ?? (found.length ? 'ok' : 'no_match'),
           status: r.status, ms: d.durationMs ?? 0 }
}

/** 硬失败文案：区分「服务器没装/没开 OCR」「太慢超时」「服务挂了」，
 *  别再一律显示「未识别到，调整角度试试」害人反复对焦 */
function failText(res: RecogResult): string {
  if (res.reason === 'timeout')
    return `服务器识别超时（${Math.max(1, Math.round(res.ms / 1000))}s）`
  if (res.reason === 'unavailable') return '服务器未启用识别'
  if (res.reason === 'http') return `识别服务暂时不可用（HTTP ${res.status}）`
  if (res.reason.startsWith('error:')) return `服务器识别出错（${res.reason.slice(6)}）`
  return '识别请求发送失败，请检查网络'
}

/** 玩家确认选卡：回填识别命中统计（FR-28，失败不影响入账），再交给上层入账 */
function pick(card: CardDto) {
  if (lastRecognitionId && game.session) {
    fetch(`/api/recognize/${lastRecognitionId}/chosen`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cardId: card.id }),
    }).catch(() => {})
  }
  stopScan()
  emit('picked', card)
}

async function startScan() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 } },
    })
  } catch {
    scanStatus.value = ''
    game.lastError = '摄像头不可用，请用「拍照」或手动检索'
    return
  }
  scanning.value = true
  failStreak = 0
  scanStatus.value = '将卡面对准扫描框…'
  requestAnimationFrame(() => {
    if (videoEl.value && stream) {
      videoEl.value.srcObject = stream
      videoEl.value.play().catch(() => {})
    }
  })
  scanLoop()
}

function stopScan() {
  scanning.value = false
  stream?.getTracks().forEach(t => t.stop())
  stream = null
}

function grabFrame(): Promise<Blob | null> {
  return new Promise((resolve) => {
    const v = videoEl.value
    if (!v || !v.videoWidth) { resolve(null); return }
    const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(v.videoWidth * scale)
    canvas.height = Math.round(v.videoHeight * scale)
    canvas.getContext('2d')!.drawImage(v, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(b => resolve(b), 'image/jpeg', 0.8)
  })
}

/** 连续识别循环：上一帧返回后间隔 1.2s 再发下一帧，避免压垮服务器 OCR。
 *  硬失败（超时/服务不可用/网络断）连续 MAX_FAIL_STREAK 次就停扫并说明白原因，
 *  「服务器未启用识别」则一次就停——再扫多少帧都不会有结果。 */
async function scanLoop() {
  while (scanning.value) {
    const blob = await grabFrame()
    if (blob) {
      let res: RecogResult
      try {
        res = await recognizeBlob(blob)
      } catch {
        res = { hit: false, reason: 'network', status: 0, ms: 0 }
      }
      if (!scanning.value) break
      if (res.hit) {
        failStreak = 0
        scanStatus.value = '识别到候选，点击确认'
      } else if (res.reason === 'no_match' || res.reason === 'no_text' || res.reason === 'no_session') {
        failStreak = 0
        scanStatus.value = res.reason === 'no_text'
          ? '没看清卡面文字，靠近些或换个光线'
          : '未识别到，调整角度/光线试试'
      } else {
        failStreak++
        scanStatus.value = failText(res)
        if (res.reason === 'unavailable' || failStreak >= MAX_FAIL_STREAK) {
          game.lastError = `${failText(res)}，请手动检索选卡`
          stopScan()
          break
        }
      }
    }
    await new Promise(r => setTimeout(r, 1200))
  }
}

/** 系统相机拍照兜底（非安全上下文或摄像头被拒时） */
async function onPhoto(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  recognizing.value = true
  try {
    const res = await recognizeBlob(file)
    if (!res.hit) {
      game.lastError = (res.reason === 'no_match' || res.reason === 'no_text')
        ? '这张没认出来，请手动检索选卡'
        : `${failText(res)}，请手动检索选卡`
    }
  } catch {
    game.lastError = '识别请求发送失败，请手动检索选卡'
  } finally { recognizing.value = false }
}

function close() { stopScan(); emit('close') }
</script>

<template>
  <div class="modal-mask" @click.self="close">
    <div class="modal">
      <div class="row between">
        <h2>选卡：{{ deckName }}</h2>
        <button class="small ghost" @click="close">关闭</button>
      </div>

      <div v-if="scanning" class="scan-area">
        <video ref="videoEl" autoplay playsinline muted></video>
        <div class="scan-frame"></div>
        <div class="scan-status">{{ scanStatus }}</div>
      </div>
      <div v-if="scanning && liveCands.length" class="scan-cands">
        <div v-for="x in liveCands" :key="x.card.id" class="list-item" @click="pick(x.card)">
          <div class="row between">
            <b>{{ x.card.title }}</b>
            <span class="muted">{{ Math.round(x.score * 100) }}%</span>
          </div>
          <div class="muted">{{ keyNumbers(x.card) }}</div>
        </div>
      </div>

      <div class="row" style="margin:8px 0">
        <input v-model="q" placeholder="搜标题 / 关键词 / 金额" @input="search" />
        <button v-if="scanSupported && !scanning" class="small ghost" @click="startScan">📷 扫描</button>
        <button v-else-if="scanning" class="small ghost" @click="stopScan">停止扫描</button>
        <button v-else class="small ghost" :disabled="recognizing" @click="fileInput?.click()">
          {{ recognizing ? '识别中…' : '📷 拍照' }}
        </button>
        <input ref="fileInput" type="file" accept="image/*" capture="environment"
               style="display:none" @change="onPhoto" />
      </div>
      <p v-if="!scanSupported" class="muted" style="margin:0 0 8px">
        想要实时扫描框？<a href="/trust" target="_blank">开启扫描识别（一次性信任证书）</a>
      </p>
      <div v-for="c in cards" :key="c.id" class="list-item" @click="pick(c)">
        <b>{{ c.title }}</b>
        <div class="muted">{{ keyNumbers(c) }}</div>
      </div>
      <p v-if="!cards.length" class="muted">没有匹配的卡，请换个关键词</p>
    </div>
  </div>
</template>

<style scoped>
.scan-area {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  background: #000;
  aspect-ratio: 4 / 3;
  margin-bottom: 8px;
}
.scan-area video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.scan-frame {
  position: absolute;
  inset: 12% 18%;
  border: 2px solid rgba(80, 200, 120, 0.9);
  border-radius: 10px;
  box-shadow: 0 0 0 999px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}
.scan-status {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 6px;
  text-align: center;
  color: #fff;
  font-size: 13px;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}
.scan-cands {
  margin-bottom: 8px;
  border: 1px solid rgba(80, 200, 120, 0.5);
  border-radius: 8px;
  padding: 4px;
}
</style>
