<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { keyNumbers } from '../cardinfo'
import { canvasToBlob, cropScanFrame, ensureOcr, ocrBroken, ocrSupported, recognizeImage,
         terminateOcr } from '../ocr'
import { DECK_COLOR, DECK_SHORT } from '../decks'
import { useGame } from '../store'
import type { CardDto } from '../types'
import BaseModal from './base/BaseModal.vue'
import GameCard from './cards/GameCard.vue'

const props = defineProps<{ deck: string; deckName: string }>()
/** 落定前的核对：卡面摆出来和手里那张对一遍 */
const pendingCard = ref<CardDto | null>(null)
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
// off=未开扫  scanning=连续识别中  locked=识别稳了，画面冻结等玩家点选
const scanState = ref<'off' | 'scanning' | 'locked'>('off')
const camOn = computed(() => scanState.value !== 'off')   // 锁定时画面定格但仍要显示
const scanStatus = ref('')
const ocrHint = ref('')          // 模型下载/引擎启动进度（首次约 5MB，别让人以为卡死）
// 手机上一帧要 1~3s，没有「正在识别」的反馈玩家会以为卡死了，一直挪卡反而更认不出
const busy = ref(false)
const liveCands = ref<{ card: CardDto; score: number }[]>([])
let stream: MediaStream | null = null
let lastRecognitionId = 0
// 识别在哪跑（design/08 §3.2 的降级链）：
// browser（手机上跑 tesseract.js，服务端零内存开销）→ server（服务端 PaddleOCR，
// 只有内存充裕的局域网部署装了）→ 手动检索（永远可用的兜底）
let engine: 'browser' | 'server' = ocrSupported() ? 'browser' : 'server'
// 连续硬失败（超时 / 服务不可用 / 网络断）计数：不能一直空转发帧，
// 小内存云端实例上那等于持续把服务器往 OOM 上推
let failStreak = 0
const MAX_FAIL_STREAK = 3
// 锁定判据：认出候选就停扫，否则候选区被后续帧一直覆盖/清空，玩家根本点不中。
// 但刚举起卡那几帧往往还没对准，只看分数会被一张糊帧锁死在错卡上，所以：
// top1 分够高**且甩开第二名** → 当帧就锁；分数一般 → 要连续 STABLE_FRAMES 帧同一张才锁。
// 阈值取自 194 张实拍的离线跑分（tools/eval_browser_ocr.py 同一套文本）：
// top1 认错的 20 例 margin 全是 0（同标题不同版本并列打平，见 design/08 §3.4），
// 所以「甩开第二名」这条门本身就把误锁挡光了；0.85/0.10 下 60% 的正确卡当帧快锁、
// 误锁 0 例。服务端 CONFIDENCE_FLOOR = 0.55，能进候选的分数都在 [0.55, 1]
const LOCK_SCORE = 0.85
const LOCK_MARGIN = 0.10
const STABLE_FRAMES = 2
let stableId = ''
let stableCount = 0

/** 识别一次的结果：reason 由服务端给（见 RecognizeOutcome），前端据此分文案 */
type RecogResult = { hit: boolean; reason: string; status: number; ms: number }

/** 不算「硬失败」的 reason：接着扫下一帧就行，不计入停扫计数 */
const SOFT_REASONS = ['no_match', 'no_text', 'no_session', 'no_frame', 'ocr_fallback']

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

async function search() {
  cards.value = await game.fetchCards(props.deck, q.value)
}
onMounted(async () => {
  await search()
  allCards.value = await game.fetchCards(props.deck)
  if (scanSupported) startScan()
})
onBeforeUnmount(() => { stopScan(); terminateOcr() })

function cardById(id: string): CardDto | undefined {
  return allCards.value.find(c => c.id === id) ?? cards.value.find(c => c.id === id)
}

/** 候选渲染：两条识别路线返回同一个形状，这里统一收口。
 *  空结果不覆盖已有候选：手一抖糊掉一帧就把候选区整块抹掉，是候选跳动的另一半来源。
 *  lastRecognitionId 也一并保留，让 FR-28 的命中统计对应玩家真正看到的那次识别。 */
function applyCandidates(d: any, status: number): RecogResult {
  const ms = d.durationMs ?? 0
  const found = (d.candidates ?? [])
    .map((c: any) => ({ card: cardById(c.card_id), score: c.score }))
    .filter((x: any) => x.card)
  if (!found.length) return { hit: false, reason: d.reason ?? 'no_match', status, ms }
  lastRecognitionId = d.recognitionId ?? 0
  liveCands.value = found
  return { hit: true, reason: d.reason ?? 'ok', status, ms }
}

/** 服务端识别：整张图片传上去，服务器跑 OCR（局域网 WITH_OCR=1 部署才有） */
async function recognizeBlob(blob: Blob): Promise<RecogResult> {
  if (!game.session) return { hit: false, reason: 'no_session', status: 0, ms: 0 }
  const fd = new FormData()
  fd.append('image', blob, 'frame.jpg')
  fd.append('deckHint', props.deck)
  const r = await fetch(`/api/rooms/${game.session.roomCode}/recognize`, { method: 'POST', body: fd })
  if (!r.ok) return { hit: false, reason: 'http', status: r.status, ms: 0 }
  return applyCandidates(await r.json(), r.status)
}

/** 浏览器端识别：手机跑 OCR，只把文本发给服务端做封闭集匹配（design/08） */
async function recognizeByBrowser(image: HTMLCanvasElement | Blob): Promise<RecogResult> {
  if (!game.session) return { hit: false, reason: 'no_session', status: 0, ms: 0 }
  const { text, ms } = await recognizeImage(image, p => {
    ocrHint.value = p.progress >= 1 ? '' : p.status
  })
  ocrHint.value = ''
  const r = await fetch(`/api/rooms/${game.session.roomCode}/recognize-text`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text.slice(0, 4000), deckHint: props.deck, clientMs: ms }),
  })
  if (!r.ok) return { hit: false, reason: 'http', status: r.status, ms }
  return applyCandidates(await r.json(), r.status)
}

/** 硬失败文案：区分「服务器没装/没开 OCR」「太慢超时」「服务挂了」，
 *  别再一律显示「未识别到，调整角度试试」害人反复对焦 */
function failText(res: RecogResult): string {
  if (res.reason === 'timeout')
    return `服务器识别超时（${Math.max(1, Math.round(res.ms / 1000))}s）`
  if (res.reason === 'unavailable')
    return ocrBroken() ? '本机和服务器都没法识别' : '服务器未启用识别'
  if (res.reason === 'http') return `识别服务暂时不可用（HTTP ${res.status}）`
  if (res.reason.startsWith('error:')) return `服务器识别出错（${res.reason.slice(6)}）`
  return '识别请求发送失败，请检查网络'
}

/** 点中一张：先把卡面摆出来和实体卡核对一次，确认了才落定（每回合只能抽一次）。
 *  核对期间选卡弹层整块收起（不叠弹层），<video> 已不在 DOM 上，顺手把摄像头放开。 */
function pick(card: CardDto) {
  stopScan()
  pendingCard.value = card
}

/** 「重新选」：回到选卡列表，摄像头整条重开（rescan 见流已停会自己走 startScan） */
function backToList() {
  pendingCard.value = null
  if (scanSupported) rescan()
}

/** 落定：回填识别命中统计（FR-28，失败不影响入账），再交给上层入账 */
function confirmPick() {
  const card = pendingCard.value!
  if (lastRecognitionId && game.session) {
    fetch(`/api/recognize/${lastRecognitionId}/chosen`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cardId: card.id }),
    }).catch(() => {})
  }
  pendingCard.value = null
  stopScan()
  emit('picked', card)
}

async function startScan() {
  // 模型下载与「请求摄像头权限」并行：首次约 5MB，别等到第一帧才开始下
  if (engine === 'browser') {
    ensureOcr(p => { ocrHint.value = p.progress >= 1 ? '' : p.status })
      .catch(() => { engine = 'server'; ocrHint.value = '' })
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 } },
    })
  } catch {
    scanStatus.value = ''
    game.lastError = '摄像头不可用，请用「拍照」或手动检索'
    return
  }
  scanState.value = 'scanning'
  failStreak = 0
  stableId = ''
  stableCount = 0
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
  scanState.value = 'off'
  stream?.getTracks().forEach(t => t.stop())
  stream = null
}

/** 这一帧的候选够不够稳？够就锁；不够先记一笔连续计数，接着扫下一帧 */
function shouldLock(): boolean {
  const [a, b] = liveCands.value
  if (!a) return false
  if (a.score >= LOCK_SCORE && (!b || a.score - b.score >= LOCK_MARGIN)) return true
  if (a.card.id === stableId) stableCount++
  else { stableId = a.card.id; stableCount = 1 }
  return stableCount >= STABLE_FRAMES
}

/** 锁定：停掉识别循环，画面定格在这一帧，候选区不再被后续帧覆盖。
 *  只暂停 <video>、不停媒体流，「重新扫描」才能瞬时恢复（无黑屏、不再要权限） */
function lockScan() {
  scanState.value = 'locked'
  videoEl.value?.pause()
  scanStatus.value = '已锁定，点击候选确认；不对就「重新扫描」'
}

/** 重新扫描：清掉旧候选与稳定计数，续用同一条流；
 *  流已失效（切后台被系统回收等）就整条重开 */
function rescan() {
  liveCands.value = []
  lastRecognitionId = 0
  stableId = ''
  stableCount = 0
  if (!stream || !stream.getVideoTracks().some(t => t.readyState === 'live')) {
    stopScan()
    startScan()
    return
  }
  failStreak = 0
  scanState.value = 'scanning'
  scanStatus.value = '将卡面对准扫描框…'
  videoEl.value?.play().catch(() => {})
  scanLoop()
}

/** 服务端识别用：整帧压成 JPEG（服务端自己会找卡面） */
async function grabFrame(): Promise<Blob | null> {
  const v = videoEl.value
  if (!v || !v.videoWidth) return null
  const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(v.videoWidth * scale)
  canvas.height = Math.round(v.videoHeight * scale)
  canvas.getContext('2d')!.drawImage(v, 0, 0, canvas.width, canvas.height)
  return canvasToBlob(canvas)
}

/** 扫一帧：浏览器端 OCR 跑不起来就就地降级到服务端识别，本帧作废，下一帧接着来 */
async function scanOnce(): Promise<RecogResult> {
  if (engine === 'browser') {
    const canvas = cropScanFrame(videoEl.value)   // 只认扫描框里那块，别把桌面文字也认进来
    if (!canvas) return { hit: false, reason: 'no_frame', status: 0, ms: 0 }
    try {
      return await recognizeByBrowser(canvas)
    } catch {
      engine = 'server'
      ocrHint.value = ''
      scanStatus.value = '本机识别不可用，改用服务器识别…'
      return { hit: false, reason: 'ocr_fallback', status: 0, ms: 0 }
    }
  }
  const blob = await grabFrame()
  if (!blob) return { hit: false, reason: 'no_frame', status: 0, ms: 0 }
  return recognizeBlob(blob)
}

/** 连续识别循环。
 *  浏览器端 OCR 不占服务器资源，识别完直接扫下一帧；走服务端识别时保留 1.2s 保护间隔。
 *  识别稳了（shouldLock）就锁定退出循环，别再让后续帧把候选区刷得乱跳。
 *  硬失败（超时/服务不可用/网络断）连续 MAX_FAIL_STREAK 次就停扫并说明白原因，
 *  「服务器未启用识别」则一次就停——再扫多少帧都不会有结果。 */
async function scanLoop() {
  while (scanState.value === 'scanning') {
    let res: RecogResult
    busy.value = true
    try {
      res = await scanOnce()
    } catch {
      res = { hit: false, reason: 'network', status: 0, ms: 0 }
    } finally {
      busy.value = false
    }
    if (scanState.value !== 'scanning') break
    if (res.hit) {
      failStreak = 0
      if (shouldLock()) { lockScan(); break }
      scanStatus.value = '识别中，把卡拿稳对准框内…'
    } else if (SOFT_REASONS.includes(res.reason)) {
      failStreak = 0
      // 已经有候选挂着时别喊「未识别到」，那说的是这一帧，玩家会以为候选作废了
      if (res.reason === 'no_text' && !liveCands.value.length)
        scanStatus.value = '没看清卡面文字，靠近些或换个光线'
      else if (res.reason === 'no_match' && !liveCands.value.length)
        scanStatus.value = '未识别到，调整角度/光线试试'
    } else {
      failStreak++
      scanStatus.value = failText(res)
      if (res.reason === 'unavailable' || failStreak >= MAX_FAIL_STREAK) {
        game.lastError = `${failText(res)}，请手动检索选卡`
        stopScan()
        break
      }
    }
    // 帧间隔：命中但还没锁住时要尽快再来一帧去凑「连续一致」，所以不额外等；
    // 服务端识别一律 1.2s，避免把小内存实例压垮
    if (engine === 'server') await sleep(1200)
    else if (res.reason === 'no_frame') await sleep(200)
  }
}

/** 系统相机拍照兜底（非安全上下文或摄像头被拒时）：同样优先在本机识别 */
async function onPhoto(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  // 重拍一张就是要换结果：这条路线没有"锁定"，得自己清掉上一张的候选
  liveCands.value = []
  lastRecognitionId = 0
  recognizing.value = true
  try {
    let res: RecogResult
    try {
      res = engine === 'browser' ? await recognizeByBrowser(file) : await recognizeBlob(file)
    } catch {
      engine = 'server'
      ocrHint.value = ''
      res = await recognizeBlob(file)
    }
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
  <!-- 选卡弹层。pendingCard 有值时整块收起：核对弹层不叠在它上面（稿子：绝不叠弹层） -->
  <BaseModal v-if="!pendingCard" :title="`选卡：${deckName}`"
             source="扫描识别、拍照或手动检索都行"
             :deck-label="DECK_SHORT[deck] ?? deckName" :deck-color="DECK_COLOR[deck]"
             dismissable @close="close">
    <div>
      <div v-if="camOn" class="scan-area">
        <video ref="videoEl" autoplay playsinline muted></video>
        <div class="scan-frame" :class="{ locked: scanState === 'locked' }"></div>
        <div class="scan-status">
          <span v-if="busy" class="scan-dot"></span>{{ ocrHint || scanStatus }}
        </div>
      </div>
      <div v-if="liveCands.length" class="scan-cands">
        <div class="section-title">最可能的几张</div>
        <button v-for="x in liveCands" :key="x.card.id" class="list-item" @click="pick(x.card)">
          <div class="row between">
            <b>{{ x.card.title }}</b>
            <span class="badge" :class="{ turn: x.score >= 0.85 }">{{ x.score >= 0.85 ? '很可能' : '可能' }}</span>
          </div>
          <div class="muted">{{ keyNumbers(x.card) }}</div>
        </button>
      </div>

      <div class="row" style="margin:8px 0">
        <input v-model="q" placeholder="搜标题 / 关键词 / 金额" @input="search" />
        <button v-if="scanSupported && scanState === 'off'" class="btn small ghost" @click="startScan">📷 扫描</button>
        <button v-else-if="scanState === 'locked'" class="btn small ghost" @click="rescan">🔄 重新扫描</button>
        <button v-else-if="scanState === 'scanning'" class="btn small ghost" @click="stopScan">停止扫描</button>
        <button v-else class="btn small ghost" :disabled="recognizing" @click="fileInput?.click()">
          {{ recognizing ? (ocrHint || '识别中…') : '📷 拍照' }}
        </button>
        <input ref="fileInput" type="file" accept="image/*" capture="environment"
               style="display:none" @change="onPhoto" />
      </div>
      <p v-if="!scanSupported" class="muted" style="margin:0 0 8px">
        拍照识别照常可用（在本机识别）。想要实时扫描框？<a href="/trust" target="_blank">开启扫描识别（一次性信任证书）</a>
      </p>
      <div>
        <button v-for="c in cards" :key="c.id" class="list-item" @click="pick(c)">
          <b>{{ c.title }}</b>
          <div class="muted">{{ keyNumbers(c) }}</div>
        </button>
      </div>
      <p v-if="!cards.length" class="muted">没有匹配的卡，请换个关键词</p>
    </div>
    <template #actions>
      <button class="btn ghost grow" @click="close">关闭</button>
    </template>
  </BaseModal>

  <!-- 落定前和实体卡核对一次：每回合只能抽一次 -->
  <BaseModal v-if="pendingCard" title="确认是这张？"
             source="和手里的实体卡核对，每回合只能抽一次"
             :deck-label="DECK_SHORT[pendingCard.deck] ?? deckName"
             :deck-color="DECK_COLOR[pendingCard.deck]"
             @close="backToList()">
    <GameCard :card="pendingCard" compact />
    <template #actions>
      <button class="btn grow" @click="confirmPick">就是这张</button>
      <button class="btn ghost grow" @click="backToList()">重新选</button>
    </template>
    <template #note>核对无误再落定；落定后仍可在待办卡上「撤销重选」。</template>
  </BaseModal>
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
  /* 改这里必须同步改 src/ocr.ts 的 SCAN_INSET：OCR 只认框里那块，两边对不上就框偏 */
  inset: 12% 18%;
  border: 2px solid rgba(80, 200, 120, 0.9);
  border-radius: 10px;
  box-shadow: 0 0 0 999px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}
/* 已锁定：加粗描边 + 画面已定格，一眼看出"停了，等你点候选" */
.scan-frame.locked {
  border: 3px solid rgb(80, 200, 120);
  box-shadow: 0 0 0 999px rgba(0, 0, 0, 0.55), 0 0 12px rgba(80, 200, 120, 0.7);
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
.scan-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 50%;
  background: rgb(80, 200, 120);
  animation: scan-pulse 1s ease-in-out infinite;
}
@keyframes scan-pulse {
  50% { opacity: 0.25; }
}
.scan-cands {
  margin-bottom: 8px;
  border: 1px solid rgba(80, 200, 120, 0.5);
  border-radius: 8px;
  padding: 4px;
}
</style>
