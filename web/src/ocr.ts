/**
 * 浏览器端 OCR（design/08）：识别在手机上跑，服务端只拿文本做封闭集匹配。
 *
 * 为什么不在服务端跑：PaddleOCR 光加载模型就 500MB+，512MB 的云主机一识别就被
 * OOM 杀掉（实测 exit 137）。搬到手机后服务端识别内存开销为 0。
 *
 * 资源全部自托管在 /tesseract/（见 web/scripts/sync-tesseract-assets.mjs），
 * 不走 jsDelivr——局域网/离线部署是硬需求。
 */
import type { Worker as TessWorker } from 'tesseract.js'

/** 扫描框在取景画面里的比例，必须与 CardPicker.vue 里 .scan-frame 的 inset 一致 */
export const SCAN_INSET = { x: 0.18, y: 0.12 }

export type OcrProgress = { status: string; progress: number }

let worker: TessWorker | null = null
let loading: Promise<TessWorker> | null = null
/** 一旦确认跑不起来（老机型 / WASM 被禁 / 资源 404）就别再重试，直接降级 */
let broken = false

const PROGRESS_TEXT: Record<string, string> = {
  'loading tesseract core': '首次使用需下载识别模型（约 5MB）…',
  'loading language traineddata': '首次使用需下载识别模型（约 5MB）…',
  'initializing tesseract': '识别引擎启动中…',
  'initializing api': '识别引擎启动中…',
  'initialized api': '识别引擎就绪',
}

export function ocrBroken(): boolean {
  return broken
}

export function ocrSupported(): boolean {
  return !broken && typeof WebAssembly === 'object' && typeof Worker === 'function'
}

/**
 * 建 worker（只建一次，多帧复用）。每帧新建会重复加载 1.7MB 语言包，手机上必卡死。
 * 加载失败抛异常，调用方据此降级到服务端识别或手动检索。
 */
export async function ensureOcr(onProgress?: (p: OcrProgress) => void): Promise<TessWorker> {
  if (worker) return worker
  if (loading) return loading
  loading = (async () => {
    const { createWorker } = await import('tesseract.js')
    // oem=1（LSTM_ONLY）：决定加载哪个 core 文件（tesseract-core-*-lstm.wasm.js），
    // 也是 tesseract.js 的默认值，这里写死免得默认值变了资源对不上
    const w = await createWorker('chi_sim', 1, {
      workerPath: '/tesseract/worker.min.js',
      corePath: '/tesseract/',
      langPath: '/tesseract/',
      gzip: true,
      logger: onProgress
        ? (m) => onProgress({ status: PROGRESS_TEXT[m.status] ?? m.status, progress: m.progress })
        : undefined,
    })
    worker = w
    return w
  })()
  try {
    return await loading
  } catch (e) {
    broken = true
    throw e
  } finally {
    loading = null
  }
}

export async function terminateOcr(): Promise<void> {
  const w = worker
  worker = null
  loading = null
  if (w) await w.terminate().catch(() => {})
}

/** 识别一张图，返回识别文本与耗时（毫秒，进服务端统计） */
export async function recognizeImage(
  image: HTMLCanvasElement | Blob,
  onProgress?: (p: OcrProgress) => void,
): Promise<{ text: string; ms: number }> {
  const w = await ensureOcr(onProgress)
  const t0 = performance.now()
  const { data } = await w.recognize(image)
  return { text: data.text ?? '', ms: Math.round(performance.now() - t0) }
}

/**
 * 从取景视频里裁出扫描框那块。
 *
 * 必须裁：整帧送进去会把桌面、旁边的卡、记录卡上的字一起认进来，匹配分被稀释。
 * video 是 object-fit: cover，画面被裁过，所以要先按 cover 还原出「可见区」，
 * 再在可见区里按 inset 取框——直接对 videoWidth 取百分比会框偏。
 */
export function cropScanFrame(video: HTMLVideoElement | null | undefined,
                              maxWidth = 1400): HTMLCanvasElement | null {
  // 组件正在卸载 / 视频还没就绪时返回 null，调用方当作「这一帧没抓到」跳过
  if (!video) return null
  const vw = video.videoWidth
  const vh = video.videoHeight
  if (!vw || !vh) return null
  const boxW = video.clientWidth || 4
  const boxH = video.clientHeight || 3
  const cover = Math.max(boxW / vw, boxH / vh)
  const visW = boxW / cover
  const visH = boxH / cover
  const sw = visW * (1 - 2 * SCAN_INSET.x)
  const sh = visH * (1 - 2 * SCAN_INSET.y)
  const sx = (vw - visW) / 2 + visW * SCAN_INSET.x
  const sy = (vh - visH) / 2 + visH * SCAN_INSET.y

  // 小画面适当放大：卡面小字放大到 ~1000px 宽后笔画更完整，认字率明显好过原始尺寸
  const k = Math.min(1.5, Math.max(1, Math.min(maxWidth, 1000) / sw))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(Math.min(sw * k, maxWidth))
  canvas.height = Math.round(sh * (canvas.width / sw))
  const ctx = canvas.getContext('2d')!
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height)
  return canvas
}

export function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise(resolve => canvas.toBlob(b => resolve(b), 'image/jpeg', 0.8))
}
