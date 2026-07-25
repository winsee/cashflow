/**
 * 把 tesseract.js 的运行时资源从 node_modules 拷进 public/tesseract/（design/08 §3.3）。
 *
 * 为什么要自托管：项目要求局域网/离线可用，tesseract.js 默认从 jsDelivr 拉 wasm 和
 * 语言包，断网就等于没有识别。拷进 public/ 后 vite 会原样打进 dist/，随镜像交付。
 *
 * 为什么是构建期拷贝而不是把文件提交进 git：三个 core 加起来 ~12MB（wasm 以 base64
 * 内嵌在 .wasm.js 里），仓库扛不住；npm install 之后跑一次就有，Docker 构建同理
 * （package.json 的 prebuild 钩子会自动调用本脚本）。
 *
 * 用法：node scripts/sync-tesseract-assets.mjs
 */
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const nm = join(root, 'node_modules')
const out = join(root, 'public', 'tesseract')

// core 有三个变体：浏览器按 relaxed-simd / simd / 无 SIMD 的支持情况自己挑一个下载
// （见 tesseract.js/src/worker-script/browser/getCore.js），手机只会下其中一个。
// 只需要 -lstm 变体：不开 legacy 引擎时 lstmOnly=true。
const FILES = [
  ['tesseract.js/dist/worker.min.js', 'worker.min.js'],
  ['tesseract.js-core/tesseract-core-relaxedsimd-lstm.wasm.js', 'tesseract-core-relaxedsimd-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-simd-lstm.wasm.js', 'tesseract-core-simd-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-lstm.wasm.js', 'tesseract-core-lstm.wasm.js'],
  // 4.0.0_best_int 是 tesseract.js 7 在 lstmOnly 下的默认语言包（1.7MB），
  // 别换成同目录的 4.0.0（20MB，含 legacy 数据，手机上没人等得起）
  ['@tesseract.js-data/chi_sim/4.0.0_best_int/chi_sim.traineddata.gz', 'chi_sim.traineddata.gz'],
]

mkdirSync(out, { recursive: true })
let total = 0
for (const [from, to] of FILES) {
  const src = join(nm, from)
  if (!existsSync(src)) {
    console.error(`[tesseract] 缺少 ${from}，先跑 npm install`)
    process.exit(1)
  }
  copyFileSync(src, join(out, to))
  total += statSync(src).size
}
console.log(`[tesseract] 已同步 ${FILES.length} 个文件到 public/tesseract/（${(total / 1048576).toFixed(1)} MB）`)
