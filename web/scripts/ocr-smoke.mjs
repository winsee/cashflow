/**
 * 浏览器端 OCR 冒烟测试（design/08 §3.3 自托管资源）：在**真浏览器**里把
 * /tesseract/ 下的 worker + wasm core + 中文语言包加载起来，识别一张实拍卡面。
 *
 * 为什么需要它：自托管路径写错（workerPath / corePath / langPath 三个之一）时，
 * 手机上的表现只是「本机识别不可用」然后悄悄降级，不看控制台根本不知道哪错了。
 * 这个脚本把这类错误挡在出厂前，不用摸手机。真机取景帧的命中率仍需 §6.2 现场测。
 *
 * 依赖系统已装的 Edge/Chrome（puppeteer-core 不下载浏览器）。
 * 用法：npm run build && npm run ocr-smoke [-- --image ../build/cards_cropped/小生意/1.jpg]
 */
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(root, '..')
const DIST = join(root, 'dist')

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const imagePath = resolve(repo, arg('image', 'build/cards_cropped/小生意/1.jpg'))
if (!existsSync(join(DIST, 'tesseract', 'worker.min.js'))) {
  console.error('缺少 dist/tesseract/，先跑 npm run build')
  process.exit(1)
}
if (!existsSync(imagePath)) {
  console.error(`缺少测试图 ${imagePath}`)
  process.exit(1)
}

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/usr/bin/chromium', '/usr/bin/google-chrome',
]
const exe = arg('browser') ?? BROWSERS.find(p => existsSync(p))
if (!exe) {
  console.error('没找到 Edge/Chrome，可用 --browser <路径> 指定')
  process.exit(1)
}

const MIME = { '.js': 'text/javascript', '.wasm': 'application/wasm', '.gz': 'application/gzip',
               '.html': 'text/html', '.css': 'text/css', '.json': 'application/json' }

// 页面用的是 dist/ 里**已交付**的那套资源，路径和手机上完全一致
const PAGE = `<!doctype html><meta charset="utf-8"><body>
<script type="module">
import Tesseract from '/lib/tesseract.esm.min.js'   // ESM 构建只有 default 导出
const { createWorker } = Tesseract
window.run = async (dataUrl) => {
  const log = []
  const t0 = performance.now()
  const worker = await createWorker('chi_sim', 1, {
    workerPath: '/tesseract/worker.min.js',
    corePath: '/tesseract/',
    langPath: '/tesseract/',
    gzip: true,
    logger: m => log.push(m.status),
  })
  const loadMs = Math.round(performance.now() - t0)
  // 连跑 3 帧：第一帧含引擎冷启动，后面两帧才是连续扫描时的真实节奏
  const times = []
  let text = ''
  for (let i = 0; i < 3; i++) {
    const t1 = performance.now()
    const { data } = await worker.recognize(dataUrl)
    times.push(Math.round(performance.now() - t1))
    text = data.text
  }
  await worker.terminate()
  return { text, loadMs, times, log: [...new Set(log)] }
}
window.ready = true
</script></body>`

const server = createServer((req, res) => {
  const path = decodeURIComponent(req.url.split('?')[0])
  if (path === '/' || path === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' }).end(PAGE)
    return
  }
  if (path === '/favicon.ico') { res.writeHead(204).end(); return }
  const file = path.startsWith('/lib/')
    ? join(root, 'node_modules', 'tesseract.js', 'dist', path.slice(5))
    : join(DIST, path)
  if (!existsSync(file)) { res.writeHead(404).end('not found'); return }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' })
  res.end(readFileSync(file))
})
await new Promise(r => server.listen(0, '127.0.0.1', r))
const port = server.address().port

// 不用 puppeteer.launch：Windows 上的 Edge 会把启动交接给别的进程再自己退出
// （puppeteer 报 "Failed to launch the browser process: Code: 0"）。
// 自己拉起来 + 连调试端口，稳当得多。
const dbgPort = 9222 + (process.pid % 500)
const edge = spawn(exe, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
  `--remote-debugging-port=${dbgPort}`,
  `--user-data-dir=${join(tmpdir(), `cashflow-ocr-smoke-${process.pid}`)}`,
  'about:blank',
], { stdio: 'ignore' })

async function waitForDevtools(deadlineMs = 20000) {
  const until = Date.now() + deadlineMs
  while (Date.now() < until) {
    try {
      const r = await fetch(`http://127.0.0.1:${dbgPort}/json/version`)
      if (r.ok) return
    } catch { /* 还没起来 */ }
    await new Promise(r => setTimeout(r, 200))
  }
  throw new Error(`浏览器调试端口 ${dbgPort} 没起来`)
}
await waitForDevtools()
const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${dbgPort}` })
try {
  const page = await browser.newPage()
  const failed = []
  // tesseract 的 "Warning: Parameter not found: xxx" 是它自己刷屏的老毛病，不是错误
  const noise = (s) => /Parameter not found|Failed to load resource/.test(s)
  const loaded = []   // 实际取了哪几个自托管文件（core 变体由浏览器的 SIMD 支持决定）
  page.on('request', r => {
    const m = r.url().match(/\/tesseract\/(.+)$/)
    if (m) loaded.push(m[1])
  })
  page.on('requestfailed', r => failed.push(`${r.url()} ${r.failure()?.errorText}`))
  page.on('response', r => { if (r.status() >= 400) failed.push(`${r.url()} HTTP ${r.status()}`) })
  page.on('pageerror', e => failed.push(`pageerror: ${e.message}`))
  page.on('console', m => {
    if (m.type() === 'error' && !noise(m.text())) failed.push(`console: ${m.text()}`)
  })
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'networkidle0' })
  try {
    await page.waitForFunction('window.ready === true', { timeout: 15000 })
  } catch (e) {
    console.error('页面脚本没起来：')
    failed.forEach(f => console.error('  ' + f))
    throw e
  }

  const dataUrl = `data:image/jpeg;base64,${readFileSync(imagePath).toString('base64')}`
  const out = await page.evaluate(u => window.run(u), dataUrl)

  const text = out.text.replace(/\s+/g, ' ').trim()
  console.log(`浏览器: ${exe.split(/[\\/]/).pop()}`)
  console.log(`引擎加载: ${out.loadMs}ms   连续 3 帧识别: ${out.times.join(' / ')}ms`)
  console.log(`自托管资源: ${loaded.join(', ') || '（一个都没取到，路径肯定错了）'}`)
  console.log(`阶段: ${out.log.join(' → ')}`)
  console.log(`识别文本: ${text.slice(0, 120)}…`)
  if (failed.length) {
    console.error('\n有资源没加载成功（自托管路径写错时就长这样）：')
    failed.forEach(f => console.error('  ' + f))
    process.exitCode = 1
  } else if (text.length < 10) {
    console.error('\n识别文本几乎为空，引擎可能没真正跑起来')
    process.exitCode = 1
  } else {
    console.log('\n冒烟通过：自托管资源可加载、WASM 可运行、能出中文文本')
  }
} finally {
  await browser.close().catch(() => {})
  edge.kill()
  server.close()
}
