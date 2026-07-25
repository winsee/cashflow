/**
 * 离线命中率基准（design/08 §6.1）：对 build/cards_cropped/ 下的实拍裁剪图跑
 * 浏览器端同款 tesseract.js，把识别文本落成 JSON，交给 tools/eval_browser_ocr.py
 * 用服务端的 matcher 打分算 Top-1/Top-3 命中率。
 *
 * 放在 web/ 下是因为它必须用**和手机上完全同一套**依赖与语言包（node_modules +
 * public/tesseract/），换一套就不算验证了。Node 与浏览器共用同一份 worker 逻辑，
 * 差别只在图像解码，命中率结论可以迁移。
 *
 * 用法（先 npm run sync-tesseract）：
 *   npm run ocr-bench                    # 全部 194 张
 *   npm run ocr-bench -- --deck 小生意 --limit 10
 *   npm run ocr-bench -- --psm 3 --out texts-psm3.json
 */
import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createWorker, PSM } from 'tesseract.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(root, '..')
const CROPPED = join(repo, 'build', 'cards_cropped')
const OUT_DIR = join(repo, 'build', 'ocr_bench')

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const onlyDeck = arg('deck')
const limit = Number(arg('limit', '0')) || 0
const psm = arg('psm', String(PSM.SINGLE_BLOCK))
const outFile = arg('out', 'texts.json')

if (!existsSync(CROPPED)) {
  console.error(`缺少 ${CROPPED}，先跑 python tools/crop_cards.py`)
  process.exit(1)
}

const images = []
for (const deck of readdirSync(CROPPED)) {
  if (onlyDeck && deck !== onlyDeck) continue
  const files = readdirSync(join(CROPPED, deck))
    .filter(f => /\.jpe?g$/i.test(f))
    .sort((a, b) => parseInt(a) - parseInt(b))
  for (const f of files) images.push({ deck, file: f, path: join(CROPPED, deck, f) })
}
const targets = limit ? images.slice(0, limit) : images
console.log(`OCR ${targets.length} 张（psm=${psm}）…`)

// worker 只建一次：每张新建会重复加载 1.7MB 语言包，手机上必卡死（§3.2 同款约束）
const worker = await createWorker('chi_sim', 1, {
  langPath: join(root, 'public', 'tesseract'),
  gzip: true,
  cachePath: OUT_DIR,
})
await worker.setParameters({ tessedit_pageseg_mode: psm })

const results = {}
let done = 0
for (const t of targets) {
  const t0 = Date.now()
  let text = ''
  try {
    const { data } = await worker.recognize(t.path)
    text = data.text
  } catch (e) {
    text = ''
    console.error(`  ! ${t.deck}/${t.file} ${e}`)
  }
  const ms = Date.now() - t0
  results[`${t.deck}/${t.file}`] = { text, ms }
  done++
  if (done % 10 === 0 || done === targets.length) {
    console.log(`  ${done}/${targets.length}`)
  }
}
await worker.terminate()

mkdirSync(OUT_DIR, { recursive: true })
const times = Object.values(results).map(r => r.ms).sort((a, b) => a - b)
const out = {
  psm,
  count: targets.length,
  msMedian: times[Math.floor(times.length / 2)] ?? 0,
  msMax: times[times.length - 1] ?? 0,
  results,
}
writeFileSync(join(OUT_DIR, outFile), JSON.stringify(out, null, 1), 'utf-8')
console.log(`写入 build/ocr_bench/${outFile}（中位 ${out.msMedian}ms，最慢 ${out.msMax}ms）`)
