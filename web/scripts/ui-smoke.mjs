/**
 * UI 冒烟：在真浏览器里开两个页面跑一局，覆盖这次重构改动最大的几屏，逐屏截图。
 *
 * 它挡的是「类型过了、构建过了、但一进页面就白屏」这类错误 —— 双设备端到端仍需人在
 * 现场按 README 的验收清单走一遍，这里只保证渲染链路不断。
 *
 * 依赖：npm run build 先跑过（服务端挂 web/dist）；系统装了 Edge/Chrome。
 * 用法：npm run ui-smoke
 * 产物：build/ui-smoke/*.png（不进 git）
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(root, '..')
const OUT = join(repo, 'build', 'ui-smoke')
const PORT = 8391
const BASE = `http://127.0.0.1:${PORT}`

// 开发机是 Windows，所以 Edge 排在最前面；后面几条是为了这套冒烟也能在
// Linux 容器里跑（CI / 远程会话），`UI_SMOKE_BROWSER` 可以直接指一个可执行文件
const BROWSERS = [
  process.env.UI_SMOKE_BROWSER,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/microsoft-edge',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean)
const browserPath = BROWSERS.find(existsSync)
if (!browserPath) { console.error('找不到 Edge/Chrome'); process.exit(1) }
if (!existsSync(join(root, 'dist', 'index.html'))) {
  console.error('缺少 dist/，先跑 npm run build'); process.exit(1)
}

/** 静态护栏：calc() 里不许做量纲除法（design/09 §3.4.2 规则 ③）。
 *
 *  `calc(58px * (var(--bw) / 332px))` 这种「长度 ÷ 长度」是 CSS Values 4 的类型运算，
 *  2025 年才陆续进各家稳定版——旧 Safari 不认，整条声明 invalid at computed-value time，
 *  骰子的 `--d` 因此失效、整颗塌成零尺寸（iPad Safari 骰子看不见的根因）。
 *  这台冒烟跑在新 Chromium 上，几何断言**原理上**照不出这种「只在旧引擎坏」的解析级问题，
 *  所以只能在源文件层面把这个写法本身挡住：除法必须在 JS 里做完，CSS 只拿无量纲数乘长度。
 *  除以纯数（`/ 2`）合法，不拦；注释先剥掉（里面写着「不许 / 332px」的示例本身会撞上）。 */
function scanCalcDimensionDivision() {
  const cssPath = join(root, 'src', 'style.css')
  const raw = readFileSync(cssPath, 'utf8')
  // 剥注释但保留换行，行号才对得上
  const css = raw.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
  const bad = []
  for (let i = css.indexOf('calc('); i !== -1; i = css.indexOf('calc(', i + 1)) {
    let depth = 0, end = i + 4
    for (; end < css.length; end++) {
      if (css[end] === '(') depth++
      else if (css[end] === ')' && --depth === 0) break
    }
    const expr = css.slice(i, end + 1)
    // 除号后面跟「带单位的数」或 var()（变量多半装着长度）即判违规
    if (/\/\s*(?:\.?\d[\d.]*[a-z%]|var\()/i.test(expr)) {
      const line = css.slice(0, i).split('\n').length
      bad.push(`style.css:${line}  ${expr.replace(/\s+/g, ' ')}`)
    }
  }
  if (bad.length) {
    console.error('calc() 里发现量纲除法（长度÷长度），旧 Safari 会让整条声明失效：')
    for (const b of bad) console.error(`  ${b}`)
    console.error('除法请在 JS 里做完，CSS 只拿无量纲数乘长度（如 --bws，见 OnlineRoomView）。')
    process.exit(1)
  }
}
scanCalcDimensionDivision()

rmSync(OUT, { recursive: true, force: true })
mkdirSync(OUT, { recursive: true })

// 同上：Windows 的 venv 布局在前，Linux 的 bin/ 兜底
const py = [
  join(repo, 'server', '.venv', 'Scripts', 'python.exe'),
  join(repo, 'server', '.venv', 'bin', 'python'),
].find(existsSync)
if (!py) { console.error('找不到 server/.venv 里的 python'); process.exit(1) }
const server = spawn(py, ['-m', 'app.serve'], {
  cwd: join(repo, 'server'),
  env: { ...process.env, CASHFLOW_HTTPS: 'off', CASHFLOW_HTTP_PORT: String(PORT) },
  // 管道必须有人读，否则 uvicorn 写满缓冲就卡住不动
  stdio: ['ignore', 'pipe', 'pipe'],
})
server.stdout.on('data', () => {})
server.stderr.on('data', d => { if (/Traceback|Error/.test(String(d))) process.stdout.write(String(d)) })

const sleep = ms => new Promise(r => setTimeout(r, ms))

async function waitServer() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${BASE}/api/health`)).ok) return } catch {}
    await sleep(500)
  }
  throw new Error('服务端没起来')
}

/** 直接走 REST 建房/入座，避免把冒烟测试写成脆弱的点击脚本 */
async function api(path, body) {
  const r = await fetch(BASE + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} → ${r.status} ${await r.text()}`)
  return r.json()
}

const failures = []
const killers = []
// 断线那一屏是故意把网切掉的：重连失败的 WS 报错是被测行为本身，不算问题
let offlineOnPurpose = false
const EXPECTED_OFFLINE = /WebSocket connection to .* failed/
// tesseract 的 WASM 引擎启动时会往 console.error 刷一串 “Parameter not found”，
// 是它自己的配置项告警，不是本项目的代码问题
const OCR_NOISE = /Parameter not found|Estimating resolution|Warning: Invalid resolution/

/** 截图并断言这一屏确实渲染出来了（要求出现的选择器写在 must 里）。
 *  先等元素再截：日志/报表这些要异步拉一次数据，固定 sleep 会随机差那么一点点，
 *  失败的屏每次还不一样。等不到照样按失败记，不会把真问题盖掉。 */
async function shot(page, name, must) {
  if (must) await page.waitForSelector(must, { timeout: 6000 }).catch(() => {})
  await sleep(500)
  await page.screenshot({ path: join(OUT, `${name}.png`) })
  const ok = await page.evaluate(sel => {
    const text = (document.getElementById('app')?.innerText ?? '').trim()
    return text.length >= 8 && (!sel || !!document.querySelector(sel))
  }, must ?? '')
  if (!ok) failures.push(`${name}: 没渲染出预期内容（${must ?? '非空'}）`)
  console.log(`  ${ok ? '✓' : '✗'} ${name}`)
}

/** 只在场一两秒的那一拍（发薪帘幕、座次条上的瞬时金额）：立刻截，不等也不回头验。
 *  `shot()` 是「等元素 → 停 500ms → 截 → 再验」，等验到的时候这一拍早过去了，
 *  于是截出来的图是对的、断言却报「没渲染出来」。所以这类屏的断言必须在**发现的那一刻**
 *  就把 DOM 取到手（见调用处），这里只负责把画面留下来。 */
async function shotNow(page, name) {
  await page.screenshot({ path: join(OUT, `${name}.png`) })
  console.log(`  ✓ ${name}`)
}

/** 骰子 3D 的回归护栏。分两半，**缺一不可**：
 *
 *  【结构】（iPad Safari 骰子渲染不出来那次修复）Chromium 测不出 WebKit 那个合成 bug
 *  本身，但能钉住导致它的两个前提条件不被误回退——
 *  ① perspective 根（.cube-scene）不能再被任何 <button> 包含；
 *  ② 从 .cube-scene 往上到 body，途中任何祖先都不许有 opacity!=1 / filter!=none
 *     （WebKit 对 3D 合成比 Chromium 保守，这两条是它最常见的拍平来源）。
 *
 *  【几何】（design/09 v0.22）光有结构断言是**不够的**：上一轮结构全对，`.cube` 却因为
 *  是块盒里的一个 `<span>` 退回了 `display: inline`——非替换行内盒不适用 width/height/
 *  transform，preserve-3d 一并失效，六个面拍成一簇散点，而上面那两条一条都没报。
 *  所以这里要直接量「立方体到底有没有盒子、有没有真的转起来」。 */
async function checkDice3dContext(page) {
  return page.evaluate(() => {
    const scene = document.querySelector('.cube-scene')
    if (!scene) return { ok: true, reason: '' } // 这一刻没有立方体骰在场（平面 `?` 骰），跳过
    if (getComputedStyle(scene).perspective === 'none')
      return { ok: false, reason: '.cube-scene 没有 perspective' }
    let el = scene.parentElement
    while (el && el !== document.body) {
      if (el.tagName === 'BUTTON')
        return { ok: false, reason: `3D 上下文被 <button class="${el.className}"> 包含` }
      const cs = getComputedStyle(el)
      if (cs.opacity !== '1' || cs.filter !== 'none')
        return { ok: false, reason: `祖先 .${el.className} 带 opacity/filter` }
      el = el.parentElement
    }

    // —— 几何：立方体每一层都必须是有盒子的块级元素 ——
    const cube = scene.querySelector('.cube')
    const face = cube && cube.querySelector('.face')
    if (!cube || !face) return { ok: false, reason: '.cube / .face 不在场' }
    for (const [sel, node] of [['.cube-scene', scene], ['.cube', cube]]) {
      const d = getComputedStyle(node).display
      if (d === 'inline')
        return { ok: false, reason: `${sel} 是行内盒（display:${d}），width/height/transform 全都不适用` }
    }
    // 量**布局**尺寸而不是 getBoundingClientRect()：立方体与每个面身上都挂着 3D 变换，
    // rect 给的是投影后的框（f1 被 translateZ 推近镜头还会放大），拿它当判据必然误报。
    if (cube.offsetWidth < 1 || cube.offsetHeight < 1)
      return { ok: false, reason: `.cube 没有盒子（${cube.offsetWidth}×${cube.offsetHeight}）` }
    // 面是 inset:0 铺在 .cube 上的，尺寸必须一致；对不上就说明包含块退化了
    if (Math.abs(face.offsetWidth - cube.offsetWidth) > 1
      || Math.abs(face.offsetHeight - cube.offsetHeight) > 1)
      return {
        ok: false,
        reason: `.face 与 .cube 的盒子对不上（面 ${face.offsetWidth}×${face.offsetHeight} ` +
          `vs 立方体 ${cube.offsetWidth}×${cube.offsetHeight}）`,
      }
    // REST_TILT 含 rotateX/rotateY，只要 transform 真的生效就必然是 3D 矩阵
    const tf = getComputedStyle(cube).transform
    if (!tf.startsWith('matrix3d('))
      return { ok: false, reason: `.cube 的 transform 没生效（${tf}）` }
    return { ok: true, reason: '' }
  })
}

/** 文案断言：有些屏的关键不是「有没有元素」，而是「写没写清楚 / 有没有多出不该有的按钮」 */
async function expectText(page, name, { has = [], hasNot = [], noButtons = [] } = {}) {
  const { text, buttons } = await page.evaluate(() => ({
    text: document.getElementById('app')?.innerText ?? '',
    buttons: [...document.querySelectorAll('.btn')].map(b => b.textContent.trim()),
  }))
  for (const s of has) if (!text.includes(s)) failures.push(`${name}: 少了「${s}」`)
  for (const s of hasNot) if (text.includes(s)) failures.push(`${name}: 不该出现「${s}」`)
  for (const s of noButtons) if (buttons.includes(s)) failures.push(`${name}: 不该有「${s}」按钮`)
}

async function main() {
  await waitServer()

  // 建房 + 两名玩家（A 房主 / B）
  const a = await api('/api/rooms', { nickname: '阿明', name: '冒烟局', maxPlayers: 4, password: null })
  const b = await api(`/api/rooms/${a.roomCode}/join`, { nickname: '小雨', password: null })

  // 不用 puppeteer.launch：Windows 上的 Edge 会把启动交接给别的进程再自己退出
  // （puppeteer 报 "Failed to launch the browser process: Code: 0"）。自己拉起来再连调试端口。
  const dbgPort = 9700 + (process.pid % 200)
  const edge = spawn(browserPath, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    `--remote-debugging-port=${dbgPort}`,
    `--user-data-dir=${join(tmpdir(), `cashflow-ui-smoke-${process.pid}`)}`,
    'about:blank',
  ], { stdio: 'ignore' })
  killers.push(() => edge.kill())
  for (let i = 0; ; i++) {
    try { if ((await fetch(`http://127.0.0.1:${dbgPort}/json/version`)).ok) break } catch {}
    if (i > 100) throw new Error(`浏览器调试端口 ${dbgPort} 没起来`)
    await sleep(200)
  }
  const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${dbgPort}` })

  // 每个玩家一个独立的浏览器上下文：同一个 profile 里两个 tab 共享 localStorage，
  // 会话会互相覆盖，第二个人一开就把第一个人的身份顶掉。
  /** `tapWs`：把 store 自己那条 WebSocket 抓在 `window.__ws` 上，并记下最后一份快照。
   *  只有 30 屏（结局屏闸门）用得着——它要往 store 真正的 `onmessage` 上补发一帧合成消息。
   *  默认关掉：包一层 `window.WebSocket` 是全局改动，没必要让另外 74 屏都跑在补丁下。 */
  async function openAs(session, tapWs = false) {
    const ctx = await browser.createBrowserContext()
    const page = await ctx.newPage()
    await page.setViewport({ width: 400, height: 860, deviceScaleFactor: 2 })
    if (tapWs) await page.evaluateOnNewDocument(() => {
      const Real = window.WebSocket
      window.WebSocket = function (...args) {
        const ws = new Real(...args)
        // 只认**第一条**：store 的 connect() 最早建连，`send()` 那些临时连接会顶掉它
        if (String(args[0]).includes('/ws?') && !window.__ws) {
          window.__ws = ws
          ws.addEventListener('message', e => {
            const m = JSON.parse(e.data)
            if (m.state) { window.__lastState = m.state; window.__lastSeq = m.seq }
          })
        }
        return ws
      }
      window.WebSocket.prototype = Real.prototype
      Object.assign(window.WebSocket, Real)
    })
    page.on('pageerror', e => failures.push(`控制台异常: ${e.message}`))
    // 渲染进程崩溃时 puppeteer 只会在下一次 evaluate 抛「detached Frame」，看不出原因
    page.on('error', e => failures.push(`页面崩溃: ${e.message}`))
    page.on('console', m => {
      if (m.type() !== 'error') return
      if (offlineOnPurpose && EXPECTED_OFFLINE.test(m.text())) return
      if (OCR_NOISE.test(m.text())) return
      failures.push(`console.error: ${m.text()}`)
    })
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.evaluate((s, nick) => {
      localStorage.setItem('cashflow.session', JSON.stringify(s))
      localStorage.setItem('cashflow.nickname', nick)   // 没有昵称会被路由守卫弹回欢迎页
    }, session, session.nickname)
    // 只改 hash 不会重新加载页面，store 就永远拿不到刚写进去的会话 —— 必须真刷一次
    await page.goto(`${BASE}/#/play`, { waitUntil: 'domcontentloaded' })
    await page.reload({ waitUntil: 'networkidle2' })
    await page.waitForSelector('.page', { timeout: 10000 }).catch(() => {})
    return page
  }

  const pa = await openAs({ ...a, nickname: '阿明' })
  const pb = await openAs({ ...b, nickname: '小雨' })

  // 房间准备：职业/梦想横滑选择器
  await pa.goto(`${BASE}/#/room`, { waitUntil: 'networkidle2' })
  await shot(pa, '01-房间准备-职业卡横滑', '.swipe .pcard')

  // 走 WS 太绕，直接用 REST 之外的路径不现实 —— 改在页面里点
  const send = (page, type, payload = {}) => page.evaluate((t, p) => {
    const s = JSON.parse(localStorage.getItem('cashflow.session'))
    return new Promise(res => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws?token=${s.playerToken}`)
      ws.onopen = () => ws.send(JSON.stringify({ actionId: String(Math.random()), type: t, payload: p }))
      ws.onmessage = e => {
        const m = JSON.parse(e.data)
        if (m.type === 'ack' || m.type === 'error') { ws.close(); res(m) }
      }
      setTimeout(() => { ws.close(); res({ type: 'timeout' }) }, 4000)
    })
  }, type, payload)

  // 划到别人已选走的那张：先等阿明自己那条 WS 连接真收到小雨选走的广播（taken 类出现），
  // 再找是第几个圆点点过去 —— 不然会跟没收到广播之前就已经存在的別的已选走卡片撞在一起，
  // 断言看到 .taken-overlay 就误判通过，实际截图划到的还是别的卡
  const gotoTaken = async page => {
    await page.waitForFunction(
      () => document.querySelector('.pcard.taken, .fcard.dreampick.taken'),
      { timeout: 4000 },
    ).catch(() => {})
    await page.evaluate(() => {
      const items = [...document.querySelectorAll('.swipe > div')]
      const idx = items.findIndex(el => el.querySelector('.pcard.taken, .fcard.dreampick.taken'))
      if (idx >= 0) document.querySelectorAll('.swipe-dots button')[idx]?.click()
    })
    await sleep(400)   // 圆点触发的是 smooth scroll，等它滑到位再截图
  }

  // 小雨先选定职业，验证阿明视角下"已被选走"半透明遮罩（选卡画面，非快车道格子）
  await send(pb, 'SELECT_PROFESSION', { professionId: 'prof-010' })   // 经理
  await gotoTaken(pa)
  await shot(pa, '01a-职业卡-已被选走', '.swipe .is-current .taken-overlay')

  await send(pa, 'SELECT_PROFESSION', { professionId: 'prof-006' })   // 医生
  await sleep(400)   // 阿明自己的 store 收到状态推送，本地 step 才会跳到梦想那屏

  // 小雨也先选定梦想，同样验证阿明视角下的遮罩
  await send(pb, 'SELECT_DREAM', { dreamId: 'ft-d-jet' })
  await gotoTaken(pa)
  await shot(pa, '01b-梦想卡-已被选走', '.swipe .is-current .taken-overlay')

  await send(pa, 'SELECT_DREAM', { dreamId: 'ft-d-safari' })
  await pa.reload({ waitUntil: 'networkidle2' })
  await shot(pa, '02-房间准备-已选完', '.steps .s.ok')

  const clickText = (page, sel, text) => page.evaluate((s, t) => {
    const el = [...document.querySelectorAll(s)].find(x => x.textContent.includes(t))
    if (el) el.click()
  }, sel, text)

  // 「重选」：服务端旧选择原封不动，但画面得看起来跟刚进大厅一样——
  // 出牌顺序、步骤条打勾都得跟着收起，不然像是叠了一层没收干净
  await clickText(pa, '.btn', '重选')
  await shot(pa, '02a-点了重选', '.swipe .pcard')
  await expectText(pa, '02a-点了重选', {
    has: ['找到你手上那张职业卡'],
    hasNot: ['出牌顺序'],
    noButtons: ['重选'],
  })
  await pa.evaluate(() => {
    const ok = document.querySelectorAll('.steps .s.ok')
    if (ok.length) throw new Error('重选期间步骤条不该还打着勾')
  }).catch(e => failures.push(`02a-点了重选: ${e.message}`))

  // 重新选完（哪怕选回一样那张），editing 得自己清掉，摘要卡和出牌顺序都要回来——
  // 这条 doneSetup 全程是 true，watch(doneSetup) 那次性复位逻辑吃不到，得在 pickDream 里自己收尾。
  // 必须真点按钮走 pickProfession/pickDream，直接用 send() 绕开 UI 是测不出这个修复的
  // （editing=false 是点按钮那条代码路径自己收的尾，服务端动作本身不知道 editing 是什么）
  await clickText(pa, '.btn', '选这张')
  // 等第 2 步真的渲染出来再点：固定 sleep 卡在服务端往返上，点空了就一路错到底
  const waitBtn = (page, text) => page.waitForFunction(
    t => [...document.querySelectorAll('.btn')].some(b => b.textContent.includes(t)),
    { timeout: 6000 }, text).catch(() => {})
  await waitBtn(pa, '我准备好了')
  await clickText(pa, '.btn', '我准备好了')
  await sleep(400)
  await shot(pa, '02b-重选完成', '.steps .s.ok')
  await expectText(pa, '02b-重选完成', { has: ['出牌顺序'] })

  await send(pa, 'SET_TURN_ORDER', { order: [a.playerId, b.playerId] })
  await send(pa, 'START_GAME')
  await sleep(400)

  // 老鼠赛跑：行动页 / 报表页 / 总览 / 日志
  await pa.goto(`${BASE}/#/play`, { waitUntil: 'networkidle2' })
  await shot(pa, '03-老鼠赛跑-行动页', '.hud .cash')

  // 选卡 → 核对：两层都走统一弹层，且**绝不叠**（核对时选卡列表整块收起）

  // 第 ① 步：银行结算日独立成步，此时**不该**冒出停留格那一堆牌堆按钮
  await shot(pa, '03a-第1步-银行结算日', '.card.focus .todo-label')
  await expectText(pa, '03a-第1步-银行结算日', {
    has: ['本回合待办 · 银行结算日', '本回合没经过'],
    hasNot: ['你停在哪种格子'],
  })

  // 二次确认：压在弹层之上的那一层（--z-confirm）
  await clickText(pa, '.btn', '结算银行结算日')
  await shot(pa, '03d-二次确认', '.modal-mask.confirm')
  await clickText(pa, '.modal .btn', '取消')

  // 内圈 24 格只有 3 个结算日，「没经过」是常态：第 ① 步得走得完，焦点才让给第 ② 步
  await clickText(pa, '.btn', '本回合没经过')
  await shot(pa, '03e-第2步-停留格', '.card.focus .pill')
  await expectText(pa, '03e-第2步-停留格', {
    has: ['你停在哪种格子', '本回合没经过'],
    noButtons: ['结算银行结算日'],
  })

  // 银行 / 转账被抽成共用组件（纯线上的「账本 · 更多」用的是同一份）——
  // 线下这一屏是那条「线下一个字都不变」硬约束里最容易被碰坏的地方，单独钉一屏
  await clickText(pa, 'button', '银行 · 贷款与还款')
  await shot(pa, '03g-线下-常驻工具-银行与转账', '.card input[step="1000"]')
  await expectText(pa, '03g-线下-常驻工具-银行与转账', {
    has: ['🏦 银行', '当前无银行贷款', '月息 10%', '🤝 玩家间转账', '对方确认后才会扣款'],
  })
  await clickText(pa, 'button', '收起')

  // 围观也是玩：不是自己回合时，牌桌上写清那个人是谁、走到哪一步、账面什么样
  await shot(pb, '03f-非我回合的牌桌', '.avatar-lg')
  await expectText(pb, '03f-非我回合的牌桌', { has: ['行动中', '月现金流'] })

  await clickText(pa, '.pill', '大买卖')
  // 弹层一开就并行拉起浏览器端 OCR（WASM 十几 MB），首帧渲染会被拖慢，等它一下
  await pa.waitForSelector('.modal .list-item', { timeout: 20000 }).catch(() => {})
  await shot(pa, '03b-选卡弹层', '.modal .list-item')
  await pa.evaluate(() => document.querySelector('.modal .list-item')?.click())
  await pa.waitForSelector('.modal .gcard', { timeout: 5000 }).catch(() => {})
  await shot(pa, '03c-选卡核对', '.modal .gcard')
  const layers = await pa.evaluate(() => document.querySelectorAll('.modal-mask').length)
  if (layers !== 1) failures.push(`03c-选卡核对: 弹层叠了 ${layers} 层`)
  await clickText(pa, '.modal .btn', '重新选')
  await clickText(pa, '.modal .btn', '关闭')

  // 抽一张大买卖卡 → 两台应同时显示同一张卡面
  await send(pa, 'DRAW_CARD', { cardId: 'bd-001' })
  await sleep(600)
  await shot(pa, '04-抽卡人看到的卡面', '.gcard-title')
  await shot(pb, '05-旁观者看到同一张卡', '.gcard-title')

  await send(pa, 'CARD_DECISION', { decision: 'pass' })
  await sleep(300)

  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[0].click())
  await shot(pa, '06-报表页-老鼠赛跑', 'table.fin')
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[2].click())
  await shot(pa, '07-总览页', '.progress')
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[3].click())
  await shot(pa, '08-日志页', '.logdot')

  // 「更正」是「抽错卡当场重选」，不是回头翻旧账：不是小雨的回合就不该给她这个按钮
  await pb.evaluate(() => document.querySelectorAll('.tabbar button')[3].click())
  await shot(pb, '08a-非本人回合无更正', '.logdot')
  await expectText(pb, '08a-非本人回合无更正', { noButtons: ['更正'] })
  await pb.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())

  // 被动回执：房主给小雨调账 → 小雨没操作却被改了账，应收到「刚刚发生在你身上」
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())
  await send(pa, 'HOST_ADJUST', { playerId: b.playerId, delta: -1500, reason: '冒烟：代收罚款' })
  await sleep(600)
  await shot(pb, '08b-被动回执', '.receipt')

  // 房主撤销：痕迹画在被撤销那一行上，不另起一行；回执只推给当事人
  const logRows = await (await fetch(`${BASE}/api/rooms/${a.roomCode}/log`)).json()
  const adjSeq = logRows.find(e => e.type === 'HOST_ADJUSTED').seq
  await send(pa, 'HOST_REVERT', { eventSeq: adjSeq, reason: '冒烟：撤销调账' })
  await sleep(700)
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[3].click())
  await shot(pa, '08f-日志-撤销画在被撤销那行上', '.logitem.revoked')
  await expectText(pa, '08f-日志-撤销画在被撤销那行上', {
    has: ['已被'],
    hasNot: ['房主撤销 ·'],      // 撤销本身不占一行
  })
  // 撤销的是小雨的调账：她收到回执，房主自己不该收到
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())
  await expectText(pa, '08g-撤销回执只给当事人', { hasNot: ['刚刚发生在你身上'] })
  await shot(pb, '08g-撤销回执只给当事人', '.receipt')
  await expectText(pb, '08g-撤销回执只给当事人', { has: ['房主撤销'] })
  await clickText(pb, '.btn', '我知道了')

  // 持续状态（慈善 / 停赛这类跨回合的）**必须让同桌看得见**：
  // 引擎里 skip_turns 是在 _advance_turn 的重放路径里静默递减的，发不出事件，
  // 所以「谁身上还挂着什么」只能靠状态本身说出来。
  await send(pa, 'END_TURN')                             // 换一个回合，停留格才是空的
  await send(pb, 'END_TURN')
  await sleep(300)
  await send(pa, 'CHARITY')
  await sleep(700)
  // 本人：行动页顶部一枚徽章；捐款是自己点的，不该再给自己推一条回执
  await shot(pa, '03h-线下-本人的持续状态', '.badge-row .badge')
  await expectText(pa, '03h-线下-本人的持续状态', {
    has: ['慈善生效中'], hasNot: ['刚刚发生在你身上'],
  })
  // 别人：牌桌那一行同样写着，外加一条「别人身上开始了一段持续状态」的回执
  await shot(pb, '03i-线下-别人的持续状态', '.badge-row .badge')
  await expectText(pb, '03i-线下-别人的持续状态', {
    has: ['慈善生效中', '捐款做慈善', '可自选掷 1 或 2 粒骰'],
  })
  await clickText(pb, '.btn', '我知道了')
  // 总览页信息最全：主状态之外，次要状态（快车道 / 分期收款 / 孩子数）也写出来
  await pb.evaluate(() => document.querySelectorAll('.tabbar button')[2].click())
  await shot(pb, '03j-线下-总览-别人的持续状态', '.badge-row .badge')
  await expectText(pb, '03j-线下-总览-别人的持续状态', { has: ['慈善生效中'] })
  // 03k 总览页去红（v0.12，房主：「那个红色菜单好丑」）：**危险画在闸门上，不画在入口上**。
  // 页尾两块红框卡改成一行安静的文字链，红只留给二次确认的确认键
  await shot(pb, '03k-线下-总览-安静的出口', '.quiet-links button')
  const reds = await pb.evaluate(() => ({
    framed: [...document.querySelectorAll('.card')]
      .filter(c => (c.getAttribute('style') ?? '').includes('--red')).length,
    warn: [...document.querySelectorAll('#app .btn.warn')].filter(b => !b.classList.contains('ghost')).length,
    links: [...document.querySelectorAll('.quiet-links button')].map(b => b.textContent.trim()),
  }))
  if (reds.framed) failures.push(`03k-线下-总览-安静的出口: 还有 ${reds.framed} 块红框卡`)
  if (reds.warn) failures.push(`03k-线下-总览-安静的出口: 还有 ${reds.warn} 枚红实心按钮`)
  if (!reds.links.length) failures.push('03k-线下-总览-安静的出口: 页尾没有退出/结束对局的出口')
  // 03l 移除玩家搬进了记录卡弹层：它是针对这个人的处置，上下文就是他的记录卡。
  // pb 不是房主，所以他点开谁的记录卡都不该有这枚按钮
  await pb.evaluate(() => document.querySelector('.card')?.click())
  await shot(pb, '03l-线下-记录卡弹层-非房主', '.modal .fin')
  await expectText(pb, '03l-线下-记录卡弹层-非房主', { noButtons: ['移除玩家'] })
  await clickText(pb, '.modal .btn', '关闭')
  await pb.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())

  // 「人人可买」的股票卡：无持仓的人也弹（卡面写明每个人都能买），但一个字都不该问他卖不卖
  await send(pa, 'END_TURN')                             // 这一回合的停留格已经用掉了
  await send(pb, 'END_TURN')
  await sleep(300)
  await send(pa, 'DRAW_CARD', { cardId: 'sd-001' })      // 优先股 2BIG，buyerScope=ALL
  await sleep(700)
  await shot(pb, '08i-无持仓者的股票窗口', '.modal')
  await expectText(pb, '08i-无持仓者的股票窗口', {
    has: ['这张卡注明人人可买', '没有 2BIG 持仓'],
    hasNot: ['最多可卖', '卖出预估盈亏'],
    noButtons: ['卖出'],
  })
  await send(pa, 'CARD_DECISION', { decision: 'pass' })
  await send(pa, 'END_TURN')
  await send(pb, 'END_TURN')
  await sleep(400)

  // 市场求购：阿明名下三套 3室2厅 → 小雨抽到求购卡 → 阿明这边应弹出逐套勾选的弹层。
  //
  // 三张卡是**挑过的对照组**，不是随便找三套一样的（从前买两套一模一样的 bd-001，
  // 两行逐字相同，既照不出「哪套最划算」也照不出负现金流）。mk-016 每套出价 $100,000：
  //   sd-051  抵押 50,000  月现金流 **−100**  → 到手 +$50,000  卖了每月还多赚 $100  ★
  //   bd-013  抵押 50,000  月现金流   500     → 到手 +$50,000  ≈ 100 个月现金流
  //   bd-026  抵押 64,000  月现金流   750     → 到手 +$36,000  ≈  48 个月现金流
  // sd-051 那一行同时钉死 `+$-100` 那一类出号（它的月现金流是负的）。
  await send(pa, 'HOST_ADJUST', { playerId: a.playerId, delta: 100000, reason: '冒烟：买房本金' })
  for (const cardId of ['sd-051', 'bd-013', 'bd-026']) {
    await send(pa, 'DRAW_CARD', { cardId })
    await send(pa, 'CARD_DECISION', { decision: 'buy' })
    await send(pa, 'END_TURN')
    await send(pb, 'END_TURN')
    await sleep(250)          // 每条动作各开一条 WS，别让下一轮抢在广播前面
  }
  await send(pa, 'END_TURN')
  await send(pb, 'DRAW_CARD', { cardId: 'mk-016' })   // 求购 3室2厅，每套 $100,000
  await sleep(800)
  await shot(pa, '08c-市场求购-逐套勾选', '.apick')
  await expectText(pa, '08c-市场求购-逐套勾选', {
    has: [
      '★ 最划算',
      '较成本 +$50,000 · 卖了每月还多赚 $100',   // sd-051：月现金流为负，卖掉反而每月多赚
      '较成本 +$30,000 · 到手 ≈ 100 个月现金流',
      '较成本 +$20,000 · 到手 ≈ 48 个月现金流',
      '首付 $0',
    ],
    // 负号一律在 `$` 外面：`$-100` / `+$-100` / `−$-100` 三种旧写法一个都不许再出现
    hasNot: ['$-', '+$-', '−$-'],
  })
  const bestRow = await pa.evaluate(() => {
    const rows = [...document.querySelectorAll('.apick')]
    const stars = rows.filter(r => r.querySelector('.star'))
    const sd = rows.find(r => r.innerText.includes('抵押 $50,000') && r.innerText.includes('多赚'))
    return {
      stars: stars.length,
      starOnBest: stars.length === 1 && sd != null && stars[0] === sd,
      // 卖掉负现金流的房产，我的月现金流是**变好**的：绿色 +$100/月，不是红色
      flowText: sd?.querySelector('.rt span')?.textContent.trim() ?? '',
      flowPos: sd?.querySelector('.rt span')?.classList.contains('pos') ?? false,
    }
  })
  if (bestRow.stars !== 1) failures.push(`08c-市场求购-逐套勾选: ★ 应有且只有 1 枚，实为 ${bestRow.stars}`)
  if (!bestRow.starOnBest) failures.push('08c-市场求购-逐套勾选: ★ 没落在最划算的那一项（sd-051）上')
  if (bestRow.flowText !== '+$100/月')
    failures.push(`08c-市场求购-逐套勾选: 负现金流那一行该写 +$100/月，实为「${bestRow.flowText}」`)
  if (!bestRow.flowPos) failures.push('08c-市场求购-逐套勾选: 卖掉负现金流资产是加分，不该染成红色')

  // 抽卡人侧：写清通知了谁、谁还没决定；不该出现那个按下会报 BAD_CARD 的「结算」
  await shot(pb, '08d-市场求购-抽卡人侧', '.badge')
  await expectText(pb, '08d-市场求购-抽卡人侧', {
    has: ['已通知 1 位持有该资产的玩家', '待决定'],
    hasNot: ['强制卡'],
    noButtons: ['结算'],
  })

  // 08c2 只卖一套之后还能接着卖 —— 从前一次提交把没勾的也一并否掉，
  // 「先卖一套再想想」这条路整个没有（服务端一直是允许的，是 UI 把闸门收严了）。
  // 故意卖**不带 ★ 的那一套**（bd-026）：分次卖与「系统推荐了哪一套」无关，
  // 而且卖掉它之后 sd-051 还留在名下，正好给下面那屏当负现金流的样本。
  await pa.evaluate(() => {
    const row = [...document.querySelectorAll('.apick')].find(r => r.innerText.includes('48 个月'))
    row?.click()
  })
  await sleep(200)
  await clickText(pa, '.modal .btn', '卖出选中的 1 项')
  await sleep(900)
  await shot(pa, '08c2-市场求购-卖一套之后还能接着卖', '.apick')
  await expectText(pa, '08c2-市场求购-卖一套之后还能接着卖', {
    has: ['已卖出 1 项', '名下还有'],
    noButtons: ['都不卖'],          // 卖过之后这枚按钮改说「不再卖了」
  })
  const left = await pa.evaluate(() => document.querySelectorAll('.apick').length)
  if (left !== 2) failures.push(`08c2-市场求购-卖一套之后还能接着卖: 该还剩 2 项可卖，实为 ${left}`)
  await clickText(pa, '.modal .btn', '不再卖了')
  await sleep(600)
  const sellClosed = await pa.evaluate(() => document.querySelectorAll('.apick').length)
  if (sellClosed !== 0) failures.push(`08c2-市场求购-卖一套之后还能接着卖: 点了「不再卖了」弹层没收口（还剩 ${sellClosed} 项）`)

  // 08e 报表页那一行才是 `fmt()` 那一层的正主：损益表逐行是**裸的** fmt(cashflow)，
  // 负现金流的资产（阿明名下还留着 sd-051）从前在这儿写成 `$-100`——负号落在 `$` 里面。
  // 08c 那一屏的数全走 signed()（先取绝对值再拼号），钉不住这一条。
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[0].click())
  await shot(pa, '08c3-线下-报表页-负现金流资产', 'table.fin')
  await expectText(pa, '08c3-线下-报表页-负现金流资产', {
    has: ['-$100'],       // 负号在 $ 外面
    hasNot: ['$-100'],    // 负号在 $ 里面：这一版写法一个字都不许再出现
  })
  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())
  await send(pb, 'END_TURN')

  // 现金流调整卡：影响所有持有该类资产的人 → 抽卡人侧应逐人列出各变多少
  await send(pa, 'DRAW_CARD', { cardId: 'sd-018' })      // 自建企业 · 小型机械公司
  await send(pa, 'CARD_DECISION', { decision: 'buy' })
  await send(pa, 'END_TURN')
  await send(pb, 'DRAW_CARD', { cardId: 'mk-008' })      // 小企业的营业额增加 +$250/月
  await sleep(800)
  await shot(pb, '08e-现金流调整-波及范围', '.gcard-title')
  await expectText(pb, '08e-现金流调整-波及范围', { has: ['这张卡影响了 1 人', '阿明'] })
  await send(pb, 'END_TURN')

  // 用房主调账凑不出被动收入，改为直接买一张高现金流企业卡（医生总支出 $9,650）
  for (const cardId of ['bd-031', 'bd-031', 'bd-031']) {
    await send(pa, 'HOST_ADJUST', { playerId: a.playerId, delta: 500000, reason: '冒烟：代替攒钱' })
    await send(pa, 'DRAW_CARD', { cardId })
    await send(pa, 'CARD_DECISION', { decision: 'buy' })
    await send(pa, 'END_TURN')
    await send(pb, 'END_TURN')
  }
  await sleep(600)
  await pa.reload({ waitUntil: 'networkidle2' })
  // 轮到自己 + 手上没别的待办 → 换算过场自动弹，不必再点横幅（横幅退居非我回合的入口）
  await shot(pa, '09-达成条件-自动进入换算过场', '.curtain.ftx .cline.hero')
  await expectText(pa, '09-达成条件-自动进入换算过场', { has: ['你逃出老鼠赛跑了', '现金流量日收入'] })

  // 「再想想」推开后横幅接手，且刷新不该把过场重新糊上来（sessionStorage 记着）
  await clickText(pa, '.curtain .btn', '再想想')
  await shot(pa, '10-推开过场后-横幅接手', '.hud-banner')
  await pa.reload({ waitUntil: 'networkidle2' })
  await sleep(400)
  await expectText(pa, '10-推开过场后-横幅接手', { has: ['你赢下老鼠赛跑了'] })

  await pa.evaluate(() => {
    const el = document.querySelector('.hud-banner')
    if (el) el.click()
  })
  await pa.waitForSelector('.curtain.ftx')
  await clickText(pa, '.curtain .btn', '进入快车道')
  await sleep(900)
  await shot(pa, '11-快车道-整屏转金', 'body.skin-ft .hud')

  await shot(pb, '12-其他玩家-祝贺过场', '.curtain.cheer')
  await expectText(pb, '12-其他玩家-祝贺过场', { has: ['逃出老鼠赛跑了', '现金流量日收入'] })
  await clickText(pb, '.curtain .btn', '知道了')
  await shot(pb, '12b-其他玩家-金色回执存根', '.receipt.goldline')
  await clickText(pb, '.btn', '我知道了')

  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[0].click())
  await shot(pa, '13-快车道记录卡-已翻面', '.card.quiet')

  await pa.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())
  await sleep(200)
  await pa.evaluate(() => {
    const el = [...document.querySelectorAll('.pill')].find(x => x.textContent.includes('企业投资'))
    if (el) el.click()
  })
  await shot(pa, '14-快车道-企业选择器弹层', '.modal .fcard.biz')

  // 另一种进场口径：自己回合抽卡买资产当场过线（阿明走的是「回合开始就进场」那一种）。
  // 棋子这一回合只是移到外环「在此进入」箭头，本回合到此为止 —— 照常渲染就是一排
  // 点不动的灰按钮（试玩反馈「只有现金流量日能点」），所以整块换成进场引导卡。
  await send(pa, 'END_TURN')
  await send(pa, 'HOST_ADJUST', { playerId: b.playerId, delta: 500000, reason: '冒烟：代替攒钱' })
  await send(pb, 'DRAW_CARD', { cardId: 'bd-031' })     // 经理总支出 $2,930，一张就过线
  await send(pb, 'CARD_DECISION', { decision: 'buy' })
  await sleep(700)
  await shot(pb, '14a-进场过场-预告本回合到此为止', '.curtain.ftx .fact')
  await expectText(pb, '14a-进场过场-预告本回合到此为止', { has: ['进场后本回合就到此为止'] })

  await clickText(pb, '.curtain .btn', '进入快车道')
  await sleep(900)
  await pb.evaluate(() => document.querySelectorAll('.tabbar button')[1].click())
  await shot(pb, '14b-进场当回合-本回合到此为止', '.ft-landed')
  await expectText(pb, '14b-进场当回合-本回合到此为止', {
    has: ['你已进入快车道', '本回合到此为止', '启动资金已到账'],
    hasNot: ['本回合待办', '企业投资'],
  })

  // 断线：红条常驻 + 明说操作不可用（界面保留但失效）
  offlineOnPurpose = true
  await pb.setOfflineMode(true)
  // Chrome 的离线模式不掐已建立的 WebSocket，得自己关一次；
  // 之后的自动重连在离线下必然失败，界面才会真正停在断线态
  await pb.evaluate(() => document.querySelector('#app').__vue_app__
    .config.globalProperties.$pinia.state.value.game.ws?.close())
  await sleep(1200)
  await shot(pb, '15-断线态', '.toast.err')
  await expectText(pb, '15-断线态', { has: ['连接断开，正在重连…', '重新连上之前，操作暂不可用'] })
  await pb.setOfflineMode(false)
  await sleep(1800)          // 等自动重连接上，别把重连期的报错算到后面的屏上
  offlineOnPurpose = false

  // 大厅：继续对局写清第几轮/几人在线/轮到谁
  await pa.goto(`${BASE}/#/`, { waitUntil: 'networkidle2' })
  await shot(pa, '16-大厅-继续对局', '.card.gold')
  await expectText(pa, '16-大厅-继续对局', { has: ['继续对局', '回到牌桌', '人在线'] })
  // 会话还在快车道、人却已回大厅：金箔是对局中的阶段特效，不该跟着人走出牌桌
  // （正例在第 11 屏：`body.skin-ft .hud`）
  if (await pa.evaluate(() => document.body.classList.contains('skin-ft')))
    failures.push('16-大厅-继续对局: 大厅不该是金箔皮肤——.skin-ft 只在对局页挂')
  await clickText(pa, '.bigbtn', '创建房间')

  // ===== 纯线上模式（design/09 §10 的屏幕清单） =====
  // 18 建房第 ① 步：只问「怎么玩」，两张竖排大卡各写清准备物，屏上不该有任何表单项
  await shot(pa, '18-建房第1步-模式二选一', '.mode-pick .bigbtn')
  await expectText(pa, '18-建房第1步-模式二选一', {
    has: ['线下辅助', '纯线上', '一台手机', '什么实物都不用准备'],
    hasNot: ['房间名', '人数上限'],
  })
  const step1Inputs = await pa.evaluate(() => document.querySelectorAll('.modal input, .modal select').length)
  if (step1Inputs) failures.push(`18-建房第1步-模式二选一: 第 ① 步不该有 ${step1Inputs} 个输入控件`)

  // 18b 选中态就是那块高亮色块本身：点谁谁整块变绿，屏上不该再有 ✓ 角标那种「单选框」
  await clickText(pa, '.mode-pick .bigbtn', '纯线上')
  await shot(pa, '18b-建房第1步-选中纯线上', '.mode-pick .bigbtn.selected')
  const modePick = await pa.evaluate(() => ({
    n: document.querySelectorAll('.mode-pick .bigbtn.selected').length,
    who: document.querySelector('.mode-pick .bigbtn.selected .t')?.textContent?.trim(),
    ticks: document.querySelectorAll('.mode-pick .tick').length,
  }))
  if (modePick.n !== 1 || modePick.who !== '纯线上' || modePick.ticks)
    failures.push(`18b-建房第1步-选中纯线上: 应只有一张「纯线上」高亮卡且无 ✓ 角标，实测 ${JSON.stringify(modePick)}`)

  // 17 第 ② 步才是房间名/密码/人数，顶部回显模式并可退回
  await clickText(pa, '.modal .btn', '下一步')
  await shot(pa, '17-建房第2步-房间设置', '.modal input')
  await expectText(pa, '17-建房第2步-房间设置', { has: ['房间名', '人数上限', '纯线上'] })
  await clickText(pa, '.modal .btn', '取消')

  const oa = await api('/api/rooms', {
    nickname: '阿线', name: '纯线上局', maxPlayers: 4, password: null, mode: 'ONLINE' })
  const ob = await api(`/api/rooms/${oa.roomCode}/join`, { nickname: '小上', password: null })

  // 同一个 hash 再 goto 一次不会重新挂载大厅，列表还是旧的——必须真刷一次
  await pa.goto(`${BASE}/#/`, { waitUntil: 'networkidle2' })
  await pa.reload({ waitUntil: 'networkidle2' })
  await sleep(600)
  await shot(pa, '19-大厅-房间列表带模式徽章', '.list-item .badge')
  await expectText(pa, '19-大厅-房间列表带模式徽章', { has: ['▣ 纯线上', '⚄ 线下辅助'] })

  const qa = await openAs({ ...oa, nickname: '阿线' })
  const qb = await openAs({ ...ob, nickname: '小上' })

  // 20 准备页：职业卡是一张**牌背**，点一下才发（说明书写的是「抽」，不是挑）
  await qa.goto(`${BASE}/#/room`, { waitUntil: 'networkidle2' })
  await shot(qa, '20-纯线上准备页-职业卡牌背', '.prof-back')
  await expectText(qa, '20-纯线上准备页-职业卡牌背', {
    has: ['抽一张职业卡', '不能重抽', '点一下，抽你的职业'],
    hasNot: ['找到你手上那张职业卡'],
  })

  // 点击的同时挂一个 rAF 采样：帘幕挂载后的**第一帧**就把牌的布局高度记下来。
  // 后面拿它和翻完之后比——`transform` 不进 offsetHeight，所以这一对数只测一件事：
  // 牌在翻转途中有没有「长个」（占位卡面换成真卡那一跳，第四轮试玩的主因）
  await qa.evaluate(() => {
    window.__dealH0 = -1
    document.querySelector('.prof-back')?.click()
    requestAnimationFrame(() => {
      window.__dealH0 = document.querySelector('.deal-curtain .deal-inner')?.offsetHeight ?? -1
    })
  })
  // 20c 帘幕一落下，页内那张牌背**不许还在抖**：`waiting` 的轻晃是「请求还在路上」的提示，
  // 帘幕落下就没有观众了，留着只会在淡入的那几帧里从底下透出来打架。
  // （截到的是翻转途中那一帧——`ready` 修好之后卡面本地几十毫秒就到，
  //   拍 1「牌背待命」只在服务端慢时才看得见，不作为截图目标）
  await sleep(120)
  const shaking = await qa.evaluate(() =>
    !!document.querySelector('.deal-curtain') && !!document.querySelector('.prof-back.waiting'))
  if (shaking) failures.push('20c-揭牌: 帘幕已落下，页内牌背还挂着 .waiting 在抖（会透出来打架）')
  await shot(qa, '20c-揭牌-翻转途中', '.deal-curtain')

  // 20d 「翻转真的在转」——第四轮试玩「怎么没有翻面的动画？点一下背面，背面变小，
  // 又稍稍变长，然后突然出现正面」。以前一条断言都没钉住这件事：20b/20c 只管
  // 「别闪正面」「别长个」，动画本身是不是还在转，没人问过。
  //
  // **不靠 rAF 采样**：这一拍只有 0.95s，中间还夹着两次截图，掉帧会让计数忽多忽少。
  // 改成把动画**暂停后逐点 seek**（`anim.currentTime = t` 再读 computed style），
  // 结果只由 CSS 决定，与真机快慢、截图停顿全都无关。取完把进度放回去继续播。
  //
  // 读 `matrix3d` 的第 11 个数：`translateZ(z) rotateY(θ) scale(s)` 展开后
  // a11 = cos θ，**不含缩放**（缩放落在 a1 = s·cos θ 上）。所以这一个数干净地回答
  // 「牌转到哪个角度了」，不会被「飞入放大」的 scale 混进来。
  const spin = await qa.evaluate(() => {
    const el = document.querySelector('.deal-curtain .deal-inner')
    if (!el) return { err: '帘幕里没有牌' }
    const anim = el.getAnimations()[0]
    if (!anim?.effect) {
      const cs = getComputedStyle(el)
      return { err: `牌上没挂动画：class="${el.className}" n=${el.getAnimations().length} `
        + `name=${cs.animationName} dur=${cs.animationDuration} play=${cs.animationPlayState}` }
    }
    // **必须把延迟算进去**（v0.12）：`anim.currentTime` 是从 `animation-delay` 开始算的，
    // 职业卡揭牌 v0.18 起延迟已经是 0（不再等一段飞入先播完），但牌堆抽卡那条 `deal` 变体
    // 仍然有延迟——这段逻辑对两条路径都要成立，不能假设延迟恒为 0。
    // 照旧 seek 到 [0, dur] 的话，有延迟时会全部落在延迟里，每一帧都是 0% 的入场填充
    // （一律 180°），下面「三成时间过去必须已起转」当场误报。
    const { delay } = anim.effect.getComputedTiming()
    const dur = anim.effect.getTiming().duration
    const keep = anim.currentTime
    anim.pause()
    const xs = []
    for (let i = 0; i <= 32; i++) {
      anim.currentTime = delay + (dur * i) / 32
      xs.push(getComputedStyle(el).transform)
    }
    anim.currentTime = keep
    anim.play()
    // 顺手把「翻完之后」的牌高也带回去（20b' 用）。整段揭牌只有 ack + 1.9s
    // （v0.18 起不再有飞入那一拍，比之前短了 0.3s），而这会儿翻牌（0.95s）已经播完、
    // 帘幕铁定还在——比之后再 sleep 一次去量稳得多
    return { dur, xs, h1: el.offsetHeight }
  })
  if (spin?.err) failures.push(`20d-翻转: ${spin.err}`)
  else if (!spin) failures.push('20d-翻转: 采不到样')
  else {
    // 两种序列化都要认：牌**正对着**镜头（θ = 0° 或 180°）时 3D 分量全为零，
    // Chromium 会把它压成 2D 的 `matrix(a,b,c,d,e,f)`——这是正常的，不是拍平。
    // 2D 那一支里 a = s·cos θ、d = s，所以 cos θ = a/d，缩放照样约掉。
    const cosOf = t => {
      const n = t.slice(t.indexOf('(') + 1, -1).split(',').map(parseFloat)
      return t.startsWith('matrix3d(') ? n[10] : n[0] / n[3]
    }
    const cos = spin.xs.map(cosOf)
    const at = f => cos[Math.round(f * 32)]
    // 侧过来的那些帧**必须**是 matrix3d：转到中途还只有 2D 矩阵，说明 3D 被拍平了，
    // 「翻过来」退化成一次横向压扁（perspective / preserve-3d 掉了就是这个样子）
    const flat = spin.xs.filter((t, i) => !t.startsWith('matrix3d(') && Math.abs(cos[i]) < 0.99)
    if (flat.length) {
      failures.push(`20d-翻转: ${flat.length}/33 帧侧过来了却不是 matrix3d，3D 被拍平了（${flat[0]}）`)
    } else if (!(Math.min(...cos) < -0.9 && Math.max(...cos) > 0.9)) {
      failures.push(`20d-翻转: cos θ 没有从 -1 扫到 +1（${Math.min(...cos).toFixed(2)}~${Math.max(...cos).toFixed(2)}），牌没翻满 180°`)
    } else if (at(0.3) <= -0.95) {
      // 修之前：0→45% 是牌堆发牌的「飞入放大」拍，rotateY 纹丝不动钉在 180°，
      // cos θ 恒为 -1。这一条专钉「前小半段白演缩放」。
      failures.push(`20d-翻转: 三成时间过去了牌还没起转（cos θ=${at(0.3).toFixed(3)}，≈ 钉在 180°）`)
    } else if (Math.abs(at(0.5)) >= 0.35) {
      // 90° 交界点（`backface-visibility` 正反切换的那一帧）必须在正中间。
      // 被缓动压到段首的话，观感就是「突然出现正面」而不是「翻过来」。
      failures.push(`20d-翻转: 90° 交界点没落在正中间（半程 cos θ=${at(0.5).toFixed(3)}，应接近 0）`)
    }
  }

  // 20e（v0.18 起）职业卡揭牌不再飞入——v0.12–v0.17 四轮都在修「对齐页内那张牌背飞过来」
  // 这条测量链路本身，每轮都在这里（旧版 20e）验证通过，却在真机上反复复现翻转前的一次
  // 尺寸突变；索性砍掉飞入，`.deal-card` 从第一帧起就该是它自己样式表写死的终态尺寸
  // （`transform: none`），不存在任何依赖运行时矩形测量的中间态。
  // 断言换成正面：帘幕刚挂载的这一刻就该没有 `.flying` 动画、没有 transform，
  // 且矩形宽度已经等于它自己不带缩放的终态宽度（`offsetWidth`）——但凡有人把飞入逻辑
  // 加回 `reveal` 分支，这条会立刻报「还挂着动画」或「transform 不是 none」。
  const steady = await qa.evaluate(() => {
    const el = document.querySelector('.deal-curtain .deal-card')
    if (!el) return { err: '帘幕里没有 .deal-card' }
    const anims = el.getAnimations()
    const r = el.getBoundingClientRect()
    return {
      transform: getComputedStyle(el).transform,
      animCount: anims.length,
      rectW: r.width,
      offsetW: el.offsetWidth,
    }
  })
  if (steady?.err) failures.push(`20e-不再飞入: ${steady.err}`)
  else if (!steady) failures.push('20e-不再飞入: 采不到样')
  else {
    if (steady.transform !== 'none') {
      failures.push(`20e-不再飞入: .deal-card 的 transform 不是 none（${steady.transform}），`
        + '还在套用飞入/缩放，第一帧就会跟终态尺寸对不上')
    } else if (steady.animCount > 0) {
      failures.push(`20e-不再飞入: .deal-card 身上还挂着 ${steady.animCount} 个动画，`
        + '不该再有飞入这一拍')
    } else if (Math.abs(steady.rectW - steady.offsetW) > 0.5) {
      failures.push(`20e-不再飞入: 矩形宽度 ${steady.rectW.toFixed(1)}px 与终态宽度 `
        + `${steady.offsetW}px 对不上，说明还有缩放在生效`)
    }
  }

  // 20b 揭牌期间**页内不许摆着那张正面**：`.curtain` 是淡入的，
  // 帘幕变实之前它会从底下透出来，看着就是「点了先闪一下正面」（第三轮试玩①）
  // 不再另 sleep：上面 20c 的截图 + 20d 的采样已经花掉一秒有余，翻牌早播完了，
  // 而帘幕只活 ack + 1.9s——多睡一次就会踩着它落幕（实测会截空）
  const leak = await qa.evaluate(() =>
    document.querySelectorAll('.pcard').length
    - document.querySelectorAll('.deal-curtain .pcard').length)
  if (!(await qa.$('.deal-curtain'))) failures.push('20b-揭牌: 帘幕没落下')
  else if (leak > 0) failures.push(`20b-揭牌: 帘幕底下还摆着 ${leak} 张职业卡正面（会透出来）`)
  await shot(qa, '20b-揭牌-帘幕底下不许有正面', '.deal-curtain')
  // 20b' 牌的几何在整段揭牌里不许变（第四轮试玩：点了还是闪一下，闪的是牌背忽然长高）
  const h0 = await qa.evaluate(() => window.__dealH0)
  const h1 = spin?.h1 ?? -1
  // 容差从 120px 收到 4px（v1.0）。以前留 120px 是因为占位卡面撑的是通用 3:4（实测 400px）、
  // 真卡随行数浮动（实测 444px），那 44px 消不掉——只能靠 `scale(.55)` 缩成 ≈24px 掩着。
  // 现在 `.deal-inner.reveal` 自己焊死 3:4、两面都绝对定位铺上去，**牌的外框不再由卡面驱动**，
  // 换卡那一帧一个像素都不该动（真卡多出来的 44px 向下溢出，牌背早已转走看不见）。
  // 只留 4px 给亚像素舍入。
  if (h0 <= 0) failures.push(`20b-揭牌: 首帧没量到牌的高度（${h0}），帘幕挂载慢了？`)
  else if (Math.abs(h1 - h0) > 4) failures.push(`20b-揭牌: 牌在翻转途中长个了 ${h0}px → ${h1}px`)
  await sleep(2000)          // 揭牌帘幕：翻牌 0.95s + 定格到 1.9s，等它自己收
  // 20a 翻开后是整张职业卡，且页面上不留任何看着能换一张的控件
  await shot(qa, '20a-纯线上准备页-职业卡翻开', '.pcard')
  await expectText(qa, '20a-纯线上准备页-职业卡翻开', {
    has: ['这就是你这一局的身份'],
    hasNot: ['点一下，抽你的职业'],
    noButtons: ['🎴 抽职业卡', '重抽', '换一张'],
  })
  await waitBtn(qa, '下一步')
  await clickText(qa, '.btn', '下一步')
  await sleep(400)

  // 21 梦想：与线下**同一套**滑动实体卡片（价格 / 被加价一次 / 策略提示），棋盘不参与挑选。
  // 小上先占掉最后一个梦想，阿线用默认聚焦的第一张，不会撞车
  const ftBoard = await (await fetch(`${BASE}/api/board/fasttrack`)).json()
  await send(qb, 'SELECT_PROFESSION')
  await sleep(300)
  await send(qb, 'SELECT_DREAM', { dreamId: ftBoard.dreams[ftBoard.dreams.length - 1].id })
  await sleep(500)
  await shot(qa, '21-纯线上准备页-梦想滑动卡片', '.swipe .fcard.dreampick')
  await expectText(qa, '21-纯线上准备页-梦想滑动卡片', {
    has: ['被加价一次', '我准备好了'],
    hasNot: ['点棋盘上的粉色格子'],
  })

  await waitBtn(qa, '我准备好了')
  await clickText(qa, '.btn', '我准备好了')
  await sleep(800)
  // 21a 收成摘要。梦想归属公示在下面的出牌顺序里、一人一行写出名字——
  // v0.2 那只只读轮盘已撤销（48 个不写字的格子里插两个圆点，读不出谁是谁）
  await shot(qa, '21a-梦想已选-摘要与出牌顺序', '.steps .s.ok')
  const wheels = await qa.evaluate(() => document.querySelectorAll('.wheel').length)
  if (wheels) failures.push(`21a-梦想已选-摘要与出牌顺序: 准备页不该再出现快车道轮盘（${wheels} 只）`)
  await expectText(qa, '21a-梦想已选-摘要与出牌顺序', { hasNot: ['· 已选梦想'] })
  // 出牌顺序：纯线上不给手排，写明开局自动排
  await qa.reload({ waitUntil: 'networkidle2' })
  await expectText(qa, '21b-纯线上-顺序由服务端排', {
    has: ['系统会替每个人各摇一次骰'],
    noButtons: ['↑'],
  })
  await send(qa, 'START_GAME')
  await sleep(600)

  // 23 棋盘主视图 · 待掷骰（抽屉 peek，没有 tabbar）
  await qa.goto(`${BASE}/#/play`, { waitUntil: 'networkidle2' })
  await sleep(600)
  const [pOne, pTwo] = (await (await fetch(`${BASE}/api/rooms/${oa.roomCode}/log`)).json())
    ? [qa, qb] : [qa, qb]
  // 谁先手由服务端掷骰定，找出当前该行动的那一页
  const whoseTurn = async () => {
    const s = await (await fetch(`${BASE}/api/rooms/${oa.roomCode}/seats`)).json()
    return s
  }
  await whoseTurn()
  const cur = await qa.evaluate(() => document.querySelector('.hud-turn b')?.textContent ?? '')
  const [pMe, pOther] = cur.includes('轮到你') ? [qa, qb] : [qb, qa]

  await shot(pMe, '22-纯线上-棋盘待掷骰', '.board-dice .die3d')
  await expectText(pMe, '22-纯线上-棋盘待掷骰', {
    has: ['第 1 步 / 3', '掷骰'],
    hasNot: ['你停在哪种格子', '手动选卡'],
  })
  // 还没掷骰这一步只该有「掷骰」一个按钮，不该同时冒出「结束回合」
  // （试玩反馈：这一步该只能掷骰，不是掷骰/结束回合二选一）
  const preRollCta = await pMe.evaluate(() => ({
    rows: document.querySelectorAll('.drawer-cta .cta-row').length,
    endTurn: [...document.querySelectorAll('.drawer-cta .btn')]
      .some(b => b.textContent.includes('结束回合')),
  }))
  if (preRollCta.rows !== 1 || preRollCta.endTurn)
    failures.push(`22-纯线上-棋盘待掷骰: 还没掷骰就有「结束回合」（${preRollCta.rows} 行，` +
      `endTurn=${preRollCta.endTurn}）`)
  const diceCtx = await checkDice3dContext(pMe)
  if (!diceCtx.ok) failures.push(`22-纯线上-棋盘待掷骰: 骰子 3D 上下文结构回归（${diceCtx.reason}）`)
  // 名牌是装饰，不许压住任何一格：它必须排在圆盘之外
  const nameInDisc = await pMe.evaluate(() => {
    const n = document.querySelector('.wheel-name'), w = document.querySelector('.wheel')
    if (!n || !w) return false
    const a = n.getBoundingClientRect(), b = w.getBoundingClientRect()
    return a.bottom > b.top + 1
  })
  if (nameInDisc) failures.push('22-纯线上-棋盘待掷骰: 盘面标题压进了圆盘')
  const tabbars = await pMe.evaluate(() => document.querySelectorAll('.tabbar').length)
  if (tabbars) failures.push('22-纯线上-棋盘待掷骰: 纯线上不该有常驻标签栏')
  // 资金 / 账本 / 说明书三枚悬浮圆钮，peek 档必须整枚都在 stage 里（stage 有 overflow:hidden）
  const floats = await pMe.evaluate(() => {
    const stage = document.querySelector('.board-stage').getBoundingClientRect()
    const all = [...document.querySelectorAll('.board-float')]
    return {
      n: all.length,
      whole: all.filter(b => b.getBoundingClientRect().bottom <= stage.bottom + 1).length,
      text: all.map(b => b.textContent.trim()).join(''),
    }
  })
  if (floats.n !== 3 || floats.whole !== 3)
    failures.push(`22-纯线上-棋盘待掷骰: 悬浮圆钮 ${floats.n} 枚、完整可见 ${floats.whole} 枚`)
  if (!floats.text.includes('🏦'))
    failures.push('22-纯线上-棋盘待掷骰: 没有资金入口（🏦）')
  // 棋盘底边不许探出 stage：stage 有 overflow:hidden，超出的一截会被裁掉（曾在 HUD 偏高
  // 的设备上把棋盘最下面一圈格子吃掉）。boardWidth 现在按实测 stage 高度自适应收缩，
  // 这条断言钉的就是这件事：不管 stage 量出来多高，.wheel 的底边永远落在它里面
  const wheelClipped = await pMe.evaluate(() => {
    const stage = document.querySelector('.board-stage').getBoundingClientRect()
    const wheel = document.querySelector('.wheel').getBoundingClientRect()
    return wheel.bottom > stage.bottom + 1
  })
  if (wheelClipped) failures.push('22-纯线上-棋盘待掷骰: 棋盘底边超出了 stage，被裁切')
  // ── v0.15 两条轨道同在一张板上（design/09 §3） ──
  // 这一条钉的就是根因：从前 BoardView 靠 `track` prop 只画一条环，
  // 退回那个版本必然有一条是 0 格。
  const tracks = await pMe.evaluate(() => ({
    rr: document.querySelectorAll('.track-rr .board-sq').length,
    ft: document.querySelectorAll('.track-ft .board-sq').length,
    dimRR: document.querySelectorAll('.track-rr.dim').length,
    dimFT: document.querySelectorAll('.track-ft.dim').length,
  }))
  if (tracks.rr !== 24 || tracks.ft !== 48)
    failures.push(`22-纯线上-棋盘待掷骰: 两条轨道该是 24 + 48 格，实际 ${tracks.rr} + ${tracks.ft}`)
  // 满对比的永远是**我自己**那条赛道。我在老鼠赛跑，所以内圈不许降饱和、外圈必须降
  if (tracks.dimRR !== 0 || tracks.dimFT !== 1)
    failures.push(`22-纯线上-棋盘待掷骰: 焦点该跟着我走（内圈 dim=${tracks.dimRR}、外圈 dim=${tracks.dimFT}）`)

  // 板是圆角方，不是正圆——外圈跑道住在四个角上
  const plateR = await pMe.evaluate(() => {
    const el = document.querySelector('.plate')
    // border-radius 写的是百分比，computed style 原样返回 "17.8%"——按单位换算，
    // 直接 parseFloat 会把 17.8 当成 px（第一版就是这么误报的）
    const raw = getComputedStyle(el).borderTopLeftRadius
    const w = el.getBoundingClientRect().width
    return { pct: raw.endsWith('%') ? parseFloat(raw) : parseFloat(raw) / w * 100, raw, w }
  })
  if (!(plateR.pct > 10 && plateR.pct < 30))
    failures.push(`22-纯线上-棋盘待掷骰: 板圆角 ${plateR.raw}（= 板宽的 ${plateR.pct.toFixed(1)}%）不在 10%~30% 之间`)

  // 快车道格面：**只有 7 个格写字**（3 个现金流量日 + 4 个特殊格），
  // 剩下 41 格（18 企业 + 23 梦想）印图标。退回「快车道不写字」这一条当场挂。
  const ftFace = await pMe.evaluate(() => ({
    labels: [...document.querySelectorAll('.track-ft .sq-label')].map(t => t.textContent.trim()),
    icons: document.querySelectorAll('.track-ft .sq-icon').length,
  }))
  const wantLabels = ['结算', '结算', '结算', '慈善', '税审', '离婚', '官司'].sort().join()
  if (ftFace.labels.slice().sort().join() !== wantLabels)
    failures.push(`22-纯线上-棋盘待掷骰: 快车道该有 7 个写字的格，实际 ${ftFace.labels.join('/')}`)
  if (ftFace.icons !== 41)
    failures.push(`22-纯线上-棋盘待掷骰: 企业与梦想格该印 41 枚图标，实际 ${ftFace.icons}`)

  // 一格 22.66 单位 × 板宽/320：正圆环时代只有 17.2px，方形跑道 23.5px。
  // 断言 > 20px —— 退回正圆环当场挂
  const cellW = await pMe.evaluate(() => {
    const sq = document.querySelector('.track-ft .board-sq path')
    return sq ? sq.getBoundingClientRect().width : 0
  })
  if (!(cellW > 20))
    failures.push(`22-纯线上-棋盘待掷骰: 快车道一格只有 ${cellW.toFixed(1)}px，方形跑道该有 23.5px`)

  // 占位道具：准备阶段全员都选了梦想，所以盘上该有**和玩家数一样多**的奶酪，
  // 每一枚的 <title> 写着是谁的。退回「梦想画成一枚 5px 圆点」当场挂
  const cheese = await pMe.evaluate(() => ({
    n: document.querySelectorAll('.track-ft .ft-token.cheese').length,
    who: [...document.querySelectorAll('.track-ft .ft-token.cheese title')].map(t => t.textContent),
    dots: document.querySelectorAll('.track-ft circle[r="5"]').length,
  }))
  if (cheese.n !== 2)
    failures.push(`22-纯线上-棋盘待掷骰: 两人各选了一个梦想，盘上该有 2 块奶酪，实际 ${cheese.n}`)
  if (!cheese.who.every(t => /选定的梦想/.test(t)))
    failures.push('22-纯线上-棋盘待掷骰: 奶酪缺少「谁的梦想」那句无障碍文本')

  // 玩家色**只有一个源**（playercolor.ts）：同一个人的棋子与座次点必须是同一个颜色，
  // 不同人之间必须不同。退回旧代码时棋子是 hsl(...)、座次点是 --panel，三处互不相等
  const colors = await pMe.evaluate(() => {
    const out = {}
    for (const el of document.querySelectorAll('.board-pawn[data-pid]')) {
      const pid = el.dataset.pid
      out[pid] = { pawn: getComputedStyle(el.querySelector('circle')).fill }
    }
    for (const el of document.querySelectorAll('.seat-dot[data-pid]')) {
      const pid = el.dataset.pid
      if (out[pid]) out[pid].dot = getComputedStyle(el).backgroundColor
    }
    return out
  })
  const rows = Object.values(colors)
  for (const [pid, c] of Object.entries(colors)) {
    if (!c.dot) { failures.push(`22-纯线上-棋盘待掷骰: 座次条上找不到 ${pid}`); continue }
    if (c.pawn !== c.dot)
      failures.push(`22-纯线上-棋盘待掷骰: ${pid} 的棋子(${c.pawn})与座次点(${c.dot})不同色——玩家色该只有一个源`)
  }
  if (rows.length >= 2 && rows[0].pawn === rows[1].pawn)
    failures.push('22-纯线上-棋盘待掷骰: 两个玩家的棋子同色，一人一色没生效')

  // HUD 资产条的**反例**：开局一项资产都没有，那一行就该整个不在。
  // 摆一句「暂无资产」是废话，还白占 HUD 一行——正例见 26f（买成了才有）
  const emptyAssets = await pMe.evaluate(() => document.querySelectorAll('.hud-assets').length)
  if (emptyAssets)
    failures.push('22b-纯线上-开局无资产: 名下一项资产都没有，HUD 却画了资产条')

  // 24 观战：别人的回合是只读骰盘（平面 `?`，不摆点数）+ 一行「他走到哪一步」
  await shot(pOther, '23-纯线上-观战', '.drawer-peek')
  const otherDice = await pOther.evaluate(() => ({
    flat: document.querySelectorAll('.board-dice .die').length,
    cube: document.querySelectorAll('.board-dice .die3d').length,
  }))
  if (!otherDice.flat || otherDice.cube)
    failures.push(`23-纯线上-观战: 别人还没掷时骰盘不该摆点数（平面 ${otherDice.flat} / 立方 ${otherDice.cube}）`)
  // 点头像列展开牌桌：每位玩家的昵称、回合步骤、现金与月现金流，
  // v0.12 起还有进度条与分子分母（房主：「和总览里面一样，要有进度条」）
  await pOther.evaluate(() => document.querySelector('.drawer-peek .seat-strip')?.click())
  await shot(pOther, '23a-纯线上-观战牌桌', '.drawer-body .avatar-lg')
  await expectText(pOther, '23a-纯线上-观战牌桌', {
    has: ['牌桌', '行动中', '月现金流', '离快车道'],
  })
  const tableRow = await pOther.evaluate(() => ({
    rows: document.querySelectorAll('.drawer-body .ptrow').length,
    prog: document.querySelectorAll('.drawer-body .ptrow .progress').length,
    on: document.querySelectorAll('.drawer-peek .seat-strip.on').length,
  }))
  if (tableRow.prog !== tableRow.rows)
    failures.push(`23a-纯线上-观战牌桌: ${tableRow.rows} 行只画了 ${tableRow.prog} 条进度条`)
  // 座次条从「点开半档抽屉」变成了「开关那一屏」，开关就得看得出自己是开是关
  if (tableRow.on !== 1)
    failures.push('23a-纯线上-观战牌桌: 牌桌开着，座次条却没有选中态')
  // 23b 点击只有把手认（§2.2：手势铺到整块抽屉，点击仍归把手一个主人）：
  // 手动拉起来看牌桌之后，点一下把手就该退回 peek。
  // 从前这里一个收起控件都没有，只能再点一次头像列（design/09 §2.2 v0.5）
  const grabBack = await pOther.evaluate(async () => {
    const el = document.querySelector('.board-drawer .sheet-grab')
    const before = document.querySelector('.board-drawer').offsetHeight
    for (const t of ['pointerdown', 'pointerup'])
      el.dispatchEvent(new PointerEvent(t, { bubbles: true, clientY: 400, pointerId: 1 }))
    await new Promise(r => setTimeout(r, 700))
    return { before, after: document.querySelector('.board-drawer').offsetHeight }
  })
  if (!(grabBack.after < grabBack.before))
    failures.push(`23b-纯线上-点把手收起: 抽屉没退档（${grabBack.before}px → ${grabBack.after}px）`)
  await shot(pOther, '23b-纯线上-点把手收起', '.drawer-peek')

  // 座次条抽成了组件，HUD 与 peek 条两处必须都还在（这两处以前是各写一份的）
  await shot(pOther, '23c-纯线上-座次条两处都在', '.hud-turn .seat-strip .seat-dot')
  const strips = await pOther.evaluate(() => ({
    hud: document.querySelectorAll('.hud-turn .seat-strip .seat-dot').length,
    peek: document.querySelectorAll('.drawer-peek .seat-strip .seat-dot').length,
    marks: document.querySelectorAll('.seat-dot .mark').length,
  }))
  if (strips.hud !== 2 || strips.peek !== 2)
    failures.push(`23c-纯线上-座次条两处都在: HUD ${strips.hud} 个 / peek ${strips.peek} 个，应各 2 个`)
  // 开局谁身上都没有持续状态，所以此刻一个角标都不该有——有角标就是判据写漏了
  if (strips.marks)
    failures.push(`23c-纯线上-座次条两处都在: 没人有持续状态，却画了 ${strips.marks} 个角标`)

  // 23d 手势铺到整个抽屉（design/09 §2.2 v0.10）：在**正文**里往下拖一段就该收起来，
  // 不必去够那根 34×4px 的把手。修之前这一拖是溢出给浏览器去刷新整页的。
  // 同时钉死：这一拖不许把手指底下那个东西顺手点掉（正文里全是「买入 / 放弃」）。
  await pOther.evaluate(() => document.querySelector('.drawer-peek .seat-strip')?.click())
  await sleep(700)
  const bodyDrag = await pOther.evaluate(async () => {
    const drawer = document.querySelector('.board-drawer')
    const body = document.querySelector('.drawer-body')
    const before = drawer.offsetHeight
    let stray = 0
    const spy = () => { stray++ }
    body.addEventListener('click', spy, true)
    const at = y => {
      const t = new Touch({ identifier: 1, target: body, clientX: 40, clientY: y })
      return { touches: [t], changedTouches: [t], bubbles: true, cancelable: true }
    }
    body.dispatchEvent(new TouchEvent('touchstart', at(200)))
    for (const y of [215, 260, 320, 380])
      body.dispatchEvent(new TouchEvent('touchmove', at(y)))
    body.dispatchEvent(new TouchEvent('touchend', at(380)))
    await new Promise(r => setTimeout(r, 700))
    body.removeEventListener('click', spy, true)
    return { before, after: drawer.offsetHeight, stray }
  })
  if (!(bodyDrag.after < bodyDrag.before))
    failures.push(`23d-纯线上-拖正文收抽屉: 抽屉没收起（${bodyDrag.before}px → ${bodyDrag.after}px）`)
  if (bodyDrag.stray)
    failures.push(`23d-纯线上-拖正文收抽屉: 拖拽顺手点掉了正文里的东西（${bodyDrag.stray} 次 click）`)
  await shot(pOther, '23d-纯线上-拖正文收抽屉', '.drawer-peek')

  // 25 掷骰 → 走格 → 落点。点数由服务端摇，落到哪一格无法预设，所以反复掷到
  // 停在机会格为止（24 格里 12 个是机会，几轮之内必中），中途的落点顺手处理掉。
  const screen = page => page.evaluate(() => document.getElementById('app')?.innerText ?? '')
  const waitMyTurn = async page => {
    for (let i = 0; i < 20; i++) {
      if ((await screen(page)).includes('轮到你了')) return true
      await sleep(300)
    }
    return false
  }
  let onDeal = false
  let landedShot = false
  let paydayShot = false
  let stubShot = false
  let penaltyShot = false
  for (let i = 0; i < 12 && !onDeal; i++) {
    await clickText(pMe, '.drawer-cta .btn', '掷')
    if (i === 0) {
      await sleep(900)
      await shot(pMe, '24-纯线上-掷骰与走格', '.board-dice .die3d')
      // 演出期间抽屉正文按住：不写「第 N 步 / 3」（那一步还没走到），也不摆卡面
      await expectText(pMe, '24-纯线上-掷骰与走格', { hasNot: ['第 3 步 / 3'] })
      // 演出没播完，「结束回合」不许先变绿——不管这一格最终要不要决策，服务端早把
      // 落点算完了，落点本身不需要决策的格子曾经会在动画播放中途就冒出可点的按钮
      // （骰子还在转 · 结束回合已可点，两句话自相矛盾）
      const endTurnDisabled = await pMe.evaluate(() => {
        const rows = [...document.querySelectorAll('.drawer-cta .cta-row')]
        const last = rows[rows.length - 1]?.querySelector('button')
        return last ? last.disabled : null
      })
      if (endTurnDisabled === false)
        failures.push('24-纯线上-掷骰与走格: 动画还在播，「结束回合」却已经可点')
    }
    // 一整条演出序列（design/09 §5.1 v0.5）：翻滚 1.3 + 读数 0.65 + 最多 6 格 ×0.24
    // + 可能的过站结算 1.7 + 落点 0.62 ≈ 5.8s 封顶。
    // **边等边探发薪帘幕**：它只在场 1.7s，等 sleep 完再看必然错过。
    // 哪一回合过站由服务端点数决定，所以照 24a 的老规矩「走到才截」，不做硬断言——
    // 24 格里一半是机会格，第一次掷骰就撞上的话循环当场就 break 了，这一跑真的一次都不过站。
    // （试过「没截到就把机会卡就地抽掉、继续掷」：结算日那三屏是稳了，25/26 那四屏反过来
    //   饿死了，还把牌局留在半路上害 27e 挂掉——一个循环不该同时扛两个目标。）
    for (let k = 0; k < 40; k++) {
      await sleep(150)
      if (paydayShot || !(await pMe.$('.curtain.payday'))) continue
      paydayShot = true
      // **先取 DOM 再截图**：这一拍只有 1.7s，截完再验就晚了（见 shotNow 的注释）
      const cur = await pMe.evaluate(() => {
        const c = document.querySelector('.curtain.payday')
        return {
          hero: !!c?.querySelector('.cline.hero'),
          text: c?.innerText ?? '',
          // 帘幕背后不该有它自己要揭晓的那个数（同职业卡那条通则，design/09 §5.4）
          dup: document.querySelectorAll('.settle-amt').length,
        }
      })
      // 旁观者同一时刻看到的是座次条上的瞬时金额（当事人被帘幕盖着，两边不重复说这笔钱）
      const chip = await pOther.evaluate(() =>
        document.querySelectorAll('.seat-strip .seat-pay').length)
      // 断言取完了再等一下才截：明细逐行入场要到 ~1.02s 才排完（600ms 错相 + 420ms 动画），
      // 发现即截会拍到一张只显示前两行的半成品。1.7s 的拍里这一等仍有 ~0.6s 余量
      await sleep(850)
      await shotNow(pMe, '24b-纯线上-发薪帘幕')
      await shotNow(pOther, '24c-纯线上-别人过结算日')
      if (!cur.hero) failures.push('24b-纯线上-发薪帘幕: 没有「本月净得」那一行')
      for (const w of ['银行结算日', '工资收入', '非工资收入', '总支出', '银行储蓄'])
        if (!cur.text.includes(w)) failures.push(`24b-纯线上-发薪帘幕: 少了「${w}」`)
      if (cur.dup) failures.push('24b-纯线上-发薪帘幕: 帘幕在场时板上还飘着同一个金额')
      if (!chip) failures.push('24c-纯线上-别人过结算日: 座次条上没有瞬时金额角标')
    }
    // 惩罚帘幕（失业/孩子/税务审计/离婚/官司）——五种里落到哪种全由服务端点数决定，
    // 同 24b 一样「走到才截」，不强求每次跑到、也不强求覆盖全部 5 种
    for (let k = 0; k < 40; k++) {
      await sleep(150)
      if (penaltyShot || !(await pMe.$('.curtain.penalty'))) continue
      penaltyShot = true
      const cur = await pMe.evaluate(() => {
        const c = document.querySelector('.curtain.penalty')
        return { hero: !!c?.querySelector('.cline.hero'), text: c?.innerText ?? '' }
      })
      await sleep(850)
      await shotNow(pMe, '24e-纯线上-惩罚帘幕')
      if (!cur.hero) failures.push('24e-纯线上-惩罚帘幕: 缺少关键数据行')
      if (!cur.text.includes('点一下跳过')) failures.push('24e-纯线上-惩罚帘幕: 缺少跳过提示')
    }
    // 落在不需要任何决定的格子上（结算日/孩子/失业/快车道惩罚格）时给一句交代——
    // 试玩反馈②：什么都没有，回合突然就能结束了，不知道刚发生了什么
    if (!landedShot && await pMe.$('.landing-done')) {
      landedShot = true
      await shot(pMe, '24a-纯线上-自动格的交代', '.landing-done')
    }
    // 帘幕是**仪式**（自动消散、还能被一次点击跳过），存根是**记录**：
    // 「经过」根本不产生 landing，播完零残留就没地方回看了
    if (paydayShot && !stubShot) {
      stubShot = true
      await shot(pMe, '24d-纯线上-结算日存根', '.landing-done')
      await expectText(pMe, '24d-纯线上-结算日存根', { has: ['结算日'] })
    }
    const t = await screen(pMe)
    if (t.includes('抽哪一叠')) { onDeal = true; break }
    // 强制卡/机会失业落点的动作已经摆在别处（cardCta 那一行 / OnlineLandingPanel 正文），
    // 底部不该再复述一句禁用态占位文案（试玩反馈：这三句被读成废话）
    for (const stale of ['先结算这张卡', '先抽一张牌', '先支付失业损失'])
      if (t.includes(stale)) failures.push(`25-纯线上-落点处理: 底部还留着复述的占位文案「${stale}」`)
    // 不是机会格：强制卡付掉、慈善不捐，然后结束回合换人
    await pMe.evaluate(() => {
      const want = ['支付', '确认', '执行', '放弃', '我不买']
      const el = [...document.querySelectorAll('.drawer-cta .btn')]
        .find(b => want.some(w => b.textContent.includes(w)))
      el?.click()
    })
    await sleep(600)
    await clickText(pMe, '.drawer-cta .btn', '结束回合')
    await sleep(400)
    await clickText(pMe, '.modal .btn', '结束回合')
    await sleep(700)
    await send(pOther, 'END_TURN')
    if (!(await waitMyTurn(pMe))) break   // 停赛/出局：不再强求
  }
  if (onDeal) {
    await shot(pMe, '25-纯线上-机会格选大小生意', '.drawer-body .btn-row')
    await expectText(pMe, '25-纯线上-机会格选大小生意', {
      has: ['你停在机会格', '必须抽一张牌'],
    })
    // 「小生意/大买卖」已经摆在正文里了，底部不该再有一行复述的「先抽一张牌」，
    // 而且**整块按钮区都不该在场**：它自带上下内边距，空着渲染就是抽屉底下一条
    // 谁也点不着的死白，还是从棋盘那儿夺来的（design/09 §2.2 v0.20）
    const preDealCta = await pMe.evaluate(() => ({
      rows: document.querySelectorAll('.drawer-cta .cta-row').length,
      box: document.querySelectorAll('.drawer-cta').length,
    }))
    if (preDealCta.rows) failures.push(`25-纯线上-机会格选大小生意: 底部还有 ${preDealCta.rows} 行 CTA，` +
      '「小生意/大买卖」已经摆在正文了，不该再复述')
    if (preDealCta.box) failures.push('25-纯线上-机会格选大小生意: 一行都排不出来，' +
      '`.drawer-cta` 却还在场，白占一截抽屉高度')
    // ── v0.20 这一屏的正主：抽屉贴合内容高度，**内容就必须真的装得下** ──
    // 从前 `--content-h` 是把三个孩子的高度加起来算的，漏了把手（4px + 8px 外边距）
    // 与抽屉自己 1px 的上边框，于是抽屉比内容矮十几像素，`.drawer-body` 一滚动，
    // 最后一行按钮被切掉半截（试玩截图：两个抽牌按钮下半截没了）。
    // 负向对照：把 `measureSheet` 换回「peek + body-inner + cta 三者相加」，这两条当场挂。
    const fitted = await pMe.evaluate(() => {
      const body = document.querySelector('.drawer-body')
      const row = document.querySelector('.drawer-body .btn-row')
      if (!body || !row) return null
      return {
        // 抽屉贴合内容高度的那一档里，正文就不该有滚动条
        over: Math.round(body.scrollHeight - body.clientHeight),
        // 按钮整行必须整个落在正文的可视区里
        cut: Math.round(row.getBoundingClientRect().bottom - body.getBoundingClientRect().bottom),
      }
    })
    if (!fitted) failures.push('25-纯线上-机会格选大小生意: 找不到正文或抽牌按钮行')
    else {
      if (fitted.over > 1) failures.push('25-纯线上-机会格选大小生意: ' +
        `抽屉没贴合内容高度，正文还差 ${fitted.over}px 才装得下`)
      if (fitted.cut > 1) failures.push('25-纯线上-机会格选大小生意: ' +
        `抽牌按钮被切掉 ${fitted.cut}px`)
    }
    // 抽屉只占一百多像素时，棋盘该长回满宽写字版——`compact` 是**板宽的结果**，
    // 不是档位的结果（v0.15 那两档常量把 half 档一律按在 230px 上，格面文字与名牌
    // 跟着一并退场，屏上于是大半是空白 + 一块读不出字的小板）。
    // 负向对照：把 `boardPx` 的上限改回 `compactBoard ? 230 : 332`，这三条当场挂。
    const roomy = await pMe.evaluate(() => ({
      bw: Math.round(document.querySelector('.wheel')?.getBoundingClientRect().width ?? 0),
      labels: document.querySelectorAll('.track-rr .sq-label').length,
      name: document.querySelectorAll('.wheel-name').length,
      slack: Math.round((document.querySelector('.board-stage')?.getBoundingClientRect().bottom ?? 0)
        - (document.querySelector('.wheel')?.getBoundingClientRect().bottom ?? 0)),
    }))
    if (roomy.bw < 300) failures.push('25-纯线上-机会格选大小生意: ' +
      `stage 底下还空着 ${roomy.slack}px，棋盘却只有 ${roomy.bw}px`)
    if (roomy.labels < 12) failures.push('25-纯线上-机会格选大小生意: ' +
      `板宽 ${roomy.bw}px 写得下字，内圈却只有 ${roomy.labels} 个格面文字`)
    if (!roomy.name) failures.push('25-纯线上-机会格选大小生意: 板宽够却没有名牌')
    // ── v0.21 这一屏另加一段：真机反馈棋盘常年卡在 300px 以下（正方形棋盘竖屏里
    // 多半是宽度先顶到 stage 边界收窄），旧阈值 300 把「写字」这个更有用的状态挡在
    // 门外——改窄视口把板宽逼到新旧阈值之间（240~300），验证文字这时候还在。
    // 负向对照：把 `BOARD_TEXT_MIN` 改回 300，这一段当场报「板宽够却没写字」。
    const prevViewport = pMe.viewport()
    await pMe.setViewport({ width: 294, height: 860, deviceScaleFactor: 2 })
    await sleep(400)
    const pinched = await pMe.evaluate(() => ({
      bw: Math.round(document.querySelector('.wheel')?.getBoundingClientRect().width ?? 0),
      compact: !!document.querySelector('.board-wrap.compact'),
      labels: document.querySelectorAll('.track-rr .sq-label').length,
      name: document.querySelectorAll('.wheel-name').length,
    }))
    if (pinched.bw < 240 || pinched.bw >= 300) failures.push('25-纯线上-窄屏仍写字: ' +
      `没能把板宽逼到新旧阈值之间（240~300），实际 ${pinched.bw}px，测试本身需要调窄视口宽度`)
    else {
      if (pinched.compact) failures.push('25-纯线上-窄屏仍写字: ' +
        `板宽 ${pinched.bw}px 已经 ≥ 新阈值 240，却仍判定为 compact`)
      if (pinched.labels < 12) failures.push('25-纯线上-窄屏仍写字: ' +
        `板宽 ${pinched.bw}px 该写字，内圈却只有 ${pinched.labels} 个格面文字`)
      if (!pinched.name) failures.push('25-纯线上-窄屏仍写字: ' +
        `板宽 ${pinched.bw}px 该写字，却没有名牌`)
    }
    if (prevViewport) await pMe.setViewport(prevViewport)
    await sleep(400)
    await clickText(pMe, '.drawer-body .btn', '小生意')
    await sleep(1000)
    await shot(pMe, '26-纯线上-全屏发牌翻牌', '.deal-curtain')
    // 演出没播完，抽屉里不许先摆出卡面与决策按钮：权威状态早就是终态了，
    // 不按住的话卡片会抢在帘幕前面出现，帘幕收起后它还在那儿（试玩反馈④）
    const early = await pMe.evaluate(() => ({
      card: document.querySelectorAll('.drawer-body .gcard').length,
      curtain: document.querySelectorAll('.deal-curtain').length,
    }))
    if (early.curtain && early.card)
      failures.push('26-纯线上-全屏发牌翻牌: 牌还没翻过来，抽屉里已经摆着卡面了')
    // 26d 牌背是**从棋盘那一格**飞出来的（design/09 §5.1 拍 6）。`stage.ts` 一直算着
    // `fromIndex`，v0.12 之前一路没人用，于是屏上只剩一次没有起点的原地放大——
    // 眼睛读不出「牌从哪儿来」，就只能读成「牌背的尺寸变了一下」（第五轮试玩）。
    // 20e 是职业卡那条的同一条断言，这里是牌堆卡这条。
    const deckFly = await pMe.evaluate(() => {
      const el = document.querySelector('.deal-curtain .deal-card')
      const disc = document.querySelector('.board-stage .disc')
      if (!el || !disc) return { err: !el ? '帘幕里没有 .deal-card' : '棋盘不在场' }
      const d = disc.getBoundingClientRect()
      if (d.width < 1) return { skip: true }       // 棋盘被压掉了，锚点本就该退化
      const anim = el.getAnimations()[0]
      if (!anim?.effect) return { err: `牌上没挂飞入动画：class="${el.className}"` }
      const keep = anim.currentTime
      anim.pause()
      const box = t => {
        anim.currentTime = t
        const r = el.getBoundingClientRect()
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width }
      }
      const first = box(0)
      const last = box(anim.effect.getComputedTiming().activeDuration)
      anim.currentTime = keep
      anim.play()
      return {
        first, last,
        // 圆盘的中心与半径：格子在**环带**上，不在盘心也不在盘外
        hub: { x: (d.left + d.right) / 2, y: (d.top + d.bottom) / 2, r: d.width / 2 },
      }
    })
    if (deckFly?.err) failures.push(`26d-飞入: ${deckFly.err}`)
    else if (deckFly && !deckFly.skip) {
      const { first, last, hub } = deckFly
      // 判「在不在某一格上」要用**环带**，不能用圆盘的外接矩形：不带锚点时牌钉在屏心，
      // 而屏心照样落在那个矩形里——负向对照跑过，这条会漏。
      // 环带取 geom.RINGS.RAT_RACE 的 R0/R1 ÷ (V/2)＝94/160 与 134/160，两头各放宽一点。
      const rel = Math.hypot(first.x - hub.x, first.y - hub.y) / hub.r
      const moved = Math.hypot(first.x - last.x, first.y - last.y)
      // **位移才是这一拍的主语**，放大只是随行的。不带锚点时首末两帧的中心一模一样
      // （牌钉在屏心原地放大），这一条专钉它——负向对照下 moved 恒为 0。
      // 只查环带会漏：屏心离盘心正好 0.82 个半径，照样落在带里（实测）。
      if (!(moved > 20)) {
        failures.push(`26d-飞入: 牌背没有位移（首末两帧中心只差 ${moved.toFixed(1)}px），`
          + '是原地放大，不是从格子里飞出来的')
      } else if (!(rel > 0.55 && rel < 0.88)) {
        failures.push(`26d-飞入: 第一帧的中心不在棋盘的格子环上（离盘心 ${rel.toFixed(2)} 个半径，`
          + '应在 0.55~0.88 之间），牌背不是从格子里飞出来的')
      } else if (!(first.w < last.w * 0.7)) {
        failures.push(`26d-飞入: 起飞时不够小（${first.w.toFixed(1)} / 终态 ${last.w.toFixed(1)}px），`
          + '看不出是从一格里飞出来的')
      }
    }
    await sleep(2000)          // 发牌帘幕 2.05s，等它播完再看抽屉
    await shot(pMe, '26a-纯线上-卡面决策（抽屉 half）', '.drawer-cta .btn')
    await expectText(pMe, '26a-纯线上-卡面决策（抽屉 half）', { has: ['第 2 步 / 3'] })
    await shot(pOther, '26b-纯线上-旁观者看到同一张卡', '.gcard-title')

    // 26e 牌桌是**显式内容态**（v0.13）：卡面正占着抽屉，点座次条照样能把牌桌调出来。
    // 修之前这里是 `!isMyTurn && !activeCardInfo` 的兜底渲染，而 activeCard 活到回合结束——
    // 别人一抽卡，牌桌到回合结束都不会再出现（房主：「基本上就没有机会看到」）
    await pOther.evaluate(() => document.querySelector('.drawer-peek .seat-strip')?.click())
    await sleep(600)
    await shot(pOther, '26e-纯线上-牌桌压过卡面', '.drawer-body .ptrow')
    const over = await pOther.evaluate(() => ({
      rows: document.querySelectorAll('.drawer-body .ptrow').length,
      card: document.querySelectorAll('.drawer-body .gcard').length,
    }))
    if (!over.rows) failures.push('26e-纯线上-牌桌压过卡面: 卡面在场时点座次条没调出牌桌')
    if (over.card) failures.push('26e-纯线上-牌桌压过卡面: 牌桌开着，卡面还压在里面')
    // 收回去，别把状态留给后面几屏
    await pOther.evaluate(() => document.querySelector('.drawer-peek .seat-strip')?.click())
    await sleep(500)

    // 决策完 → 第 ③ 步，主 CTA 变成结束回合。
    // 抽到哪一张由服务端牌堆决定，所以按钮文案不能写死。
    // **买得起就买**：这是 26f/26g 那两屏（HUD 资产条）唯一的来料——纯线上抽到哪张牌由服务端
    // 定，没有别的路能让玩家名下确定地长出一项资产。买不了就照旧点「不要 / 付掉」那个
    const decideCard = (buyIfAffordable) => pMe.evaluate((tryBuy) => {
      const money = s => Number((String(s).match(/\$([\d,]+)/)?.[1] ?? '0').replace(/,/g, ''))
      const btns = [...document.querySelectorAll('.drawer-cta .btn')]
        // 「结束回合 / 跳过本回合」那一行永远在，兜底时绝不能点到它
        .filter(b => !/结束回合|跳过本回合/.test(b.textContent))
      const buy = btns.find(b => b.textContent.includes('买入'))
      // **买入按钮从不置灰**（UI 的闸门不许比服务端严，服务端才是权威），
      // 所以「买不买得起」得自己算：拿按钮上那个首付跟 HUD 的银行储蓄比。
      // 拿 `disabled` 当判据的话，就会去撞一个必然被拒的请求，卡片留在原地不结算
      if (tryBuy && buy) {
        const cash = money(document.querySelector('.hud .cash')?.textContent)
        if (money(buy.textContent) <= cash) { buy.click(); return true }
      }
      const want = ['放弃', '我不买', '执行', '支付', '确认']
      const el = btns.find(b => want.some(w => b.textContent.includes(w))) ?? btns[0]
      el?.click()
      return false
    }, buyIfAffordable)

    let bought = await decideCard(true)
    await sleep(900)
    // 买入被服务端拒掉的话（金额读不到、或另有闸门），卡片还杵在那儿——回落到「放弃」，
    // 否则这一回合结束不了，26c 往下全塌
    const stillOpen = await pMe.evaluate(() =>
      [...document.querySelectorAll('.drawer-cta .btn')].some(b => b.textContent.includes('买入')))
    if (bought && stillOpen) {
      bought = false
      await decideCard(false)
      await sleep(900)
    }

    // 26f HUD 资产条（走到才截，同 24a 那一类）：买成了才有家底可报
    if (bought && await pMe.$('.hud-assets')) {
      await shot(pMe, '26f-纯线上-HUD资产条', '.hud-assets')
      const stageH = await pMe.evaluate(() => document.querySelector('.board-stage').offsetHeight)
      await pMe.evaluate(() => document.querySelector('.hud-assets')?.click())
      await sleep(400)
      await shot(pMe, '26g-纯线上-资产明细浮层', '.asset-pop')
      // 展开是**浮层**不是把 HUD 撑高：棋盘 stage 的高度一个像素都不许变
      // （stage 的 flex-basis 是 0，HUD 一长高先被挤没的就是它）
      const after = await pMe.evaluate(() => ({
        h: document.querySelector('.board-stage').offsetHeight,
        pop: document.querySelectorAll('.asset-pop').length,
      }))
      if (!after.pop) failures.push('26f-纯线上-HUD资产条: 点了没展开明细浮层')
      if (Math.abs(after.h - stageH) > 1)
        failures.push(`26f-纯线上-HUD资产条: 展开把棋盘挤了（${stageH}px → ${after.h}px）`)
      await pMe.evaluate(() => document.querySelector('.board-stage')?.click())
      await sleep(400)
    }
    await shot(pMe, '26c-纯线上-结束回合', '.drawer-cta .btn')
    await expectText(pMe, '26c-纯线上-结束回合', { has: ['第 3 步 / 3', '结束回合'] })
  } else {
    await shot(pMe, '25-纯线上-落点处理', '.drawer-body')
  }

  // 27 账本：报表 / 总览 / 日志三分段（full 档抽屉，不是 tabbar）
  await pMe.evaluate(() => {
    const el = [...document.querySelectorAll('.board-float')].find(x => x.textContent.includes('📋'))
    el?.click()
  })
  await shot(pMe, '27-纯线上-账本-报表', '.drawer-body table.fin')
  // 分页控件在内容区顶部、四段等宽一行排开（老排法挤在 peek 条上会折成两行）
  const seg = await pMe.evaluate(() => {
    const el = document.querySelector('.ledger-seg')
    return el ? { n: el.querySelectorAll('button').length, h: el.offsetHeight } : null
  })
  if (!seg || seg.n !== 3) failures.push(`27-纯线上-账本-报表: 分段控件不是三段（${seg?.n ?? '没有'}）`)
  else if (seg.h > 50) failures.push(`27-纯线上-账本-报表: 分段控件折行了（${seg.h}px）`)
  // full 档下 stage 只剩十几个像素（HUD + 88dvh 已超一屏，负空间全由抽屉吸收，而 stage 的
  // flex-basis 是 0）。悬浮圆钮挂在 stage 内部，留着就会被 overflow:hidden 切成一条边，
  // 看着像渲染坏了——所以这一档整列收起，而不是留几枚半截的圆
  const sliced = await pMe.evaluate(() => {
    const stage = document.querySelector('.board-stage').getBoundingClientRect()
    return [...document.querySelectorAll('.board-float')]
      .filter(b => b.getBoundingClientRect().bottom > stage.bottom + 1).length
  })
  if (sliced) failures.push(`27-纯线上-账本-报表: full 档下有 ${sliced} 枚悬浮圆钮被切了一半`)
  await clickText(pMe, '.ledger-seg button', '总览')
  await shot(pMe, '27a-纯线上-账本-总览', '.drawer-body .progress')
  // full 档（88dvh）+ HUD 超过一屏：抽屉必须收缩到剩余空间里。
  // 底端一旦落到屏幕之外，里面滚到底也永远差最后一截（试玩：总览的「退出对局」看不全）
  const drawerCut = await pMe.evaluate(() => {
    const el = document.querySelector('.board-drawer')
    if (!el) return null
    const body = el.querySelector('.drawer-body')
    body.scrollTop = body.scrollHeight
    // .drawer-body 的唯一直接子元素现在是 .drawer-body-inner（内容贴合改动新增的
    // 测量包裹层），要多取一层才能到当年那个「最后一张卡」
    const last = body.lastElementChild?.lastElementChild?.lastElementChild
    return {
      over: Math.round(el.getBoundingClientRect().bottom - window.innerHeight),
      tail: last ? Math.round(last.getBoundingClientRect().bottom - window.innerHeight) : 0,
    }
  })
  if (!drawerCut) failures.push('27a-纯线上-账本-总览: 找不到抽屉')
  else if (drawerCut.over > 1)
    failures.push(`27a-纯线上-账本-总览: 抽屉底端落在屏幕外 ${drawerCut.over}px`)
  else if (drawerCut.tail > 1)
    failures.push(`27a-纯线上-账本-总览: 滚到底了，最后一张卡还差 ${drawerCut.tail}px 露不出来`)
  await clickText(pMe, '.ledger-seg button', '日志')
  await shot(pMe, '27b-纯线上-账本-日志', '.drawer-body .logdot')
  // 纯线上没有「本人更正」这条路径
  await expectText(pMe, '27b-纯线上-账本-日志', { noButtons: ['更正'] })

  // 27c 收起归把手：peek 条上不再有「收起 ✕」那枚按钮，点一下把手账本就该整个关掉
  // （不是退到 half——账本只有 full 一种形态，退一半等于半开着挡路）
  const noCloseBtn = await pMe.evaluate(() =>
    [...document.querySelectorAll('.drawer-peek button')].some(b => b.textContent.includes('收起')))
  if (noCloseBtn) failures.push('27c-纯线上-账本收起: peek 条上还留着「收起」按钮')
  const closed = await pMe.evaluate(async () => {
    const el = document.querySelector('.board-drawer .sheet-grab')
    for (const t of ['pointerdown', 'pointerup'])
      el.dispatchEvent(new PointerEvent(t, { bubbles: true, clientY: 300, pointerId: 1 }))
    await new Promise(r => setTimeout(r, 700))
    return !document.querySelector('.ledger-seg')
  })
  if (!closed) failures.push('27c-纯线上-账本收起: 点把手没有把账本关掉')
  await shot(pMe, '27c-纯线上-账本收起-把手', '.drawer-peek')

  // 27e 三枚圆钮**钉死**（design/09 §3.2.1 v0.15，房主定案）：抽屉拉到任何档位，
  // 它们的屏幕位置一个像素都不许动，也不许消失。
  // stage 的上沿由 HUD 决定、HUD 是 flex:none 的定高条，所以只要圆钮绝对定位在 stage 上、
  // 而不是塞进 `.wheel-name` 那个跟着板走的块里，这条就成立。
  // 负向对照：把 `.board-tools` 挪进 `.board-wrap`，或把 `v-if="detent !== 'full'"` 加回来，
  // 这条当场挂。
  const toolsAt = async (label) => pMe.evaluate(() => {
    const b = [...document.querySelectorAll('.board-float')]
    const stage = document.querySelector('.board-stage')?.getBoundingClientRect()
    const sq = [...document.querySelectorAll('.board-sq path')]
    let hit = null
    for (const x of b) {
      const r = x.getBoundingClientRect()
      for (const p of sq) {
        const q = p.getBoundingClientRect()
        if (r.left < q.right - 1 && r.right > q.left + 1
          && r.top < q.bottom - 1 && r.bottom > q.top + 1) {
          hit = `钮[${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.right)},${Math.round(r.bottom)}]`
            + ` × 格[${Math.round(q.left)},${Math.round(q.top)},${Math.round(q.right)},${Math.round(q.bottom)}]`
          break
        }
      }
      if (hit) break
    }
    return {
      n: b.length,
      top: b.length ? Math.round(b[0].getBoundingClientRect().top) : -1,
      whole: b.filter(x => x.getBoundingClientRect().bottom <= (stage?.bottom ?? 0) + 1).length,
      hit,
      // 抽屉高度一起记：档位没真的切过去时，三个样本会长得一模一样，
      // 光看 top 相等反而会误判成「钉住了」
      dh: Math.round(document.querySelector('.board-drawer')?.getBoundingClientRect().height ?? 0),
    }
  }).then(r => ({ ...r, label }))
  // 先确保回到 peek：27c 那一下把账本关了，但抽屉停在 half
  await pMe.evaluate(async () => {
    const el = document.querySelector('.board-drawer .sheet-grab')
    for (const t of ['pointerdown', 'pointerup'])
      el.dispatchEvent(new PointerEvent(t, { bubbles: true, clientY: 300, pointerId: 1 }))
    await new Promise(r => setTimeout(r, 700))
  })
  const pinned = [await toolsAt('peek')]
  // half：peek 档点把手就是展开（§2.2「向上 = 进一步」）。
  // 这里不能点座次条——轮到我时 peek 条上根本没有它（那一支只写「第 N 步 / 3」）
  const tapGrab = async () => {
    await pMe.evaluate(async () => {
      const el = document.querySelector('.board-drawer .sheet-grab')
      for (const t of ['pointerdown', 'pointerup'])
        el.dispatchEvent(new PointerEvent(t, { bubbles: true, clientY: 300, pointerId: 1 }))
      await new Promise(r => setTimeout(r, 700))
    })
    await sleep(200)
  }
  await tapGrab()
  pinned.push(await toolsAt('half'))
  // full：账本
  await pMe.evaluate(() =>
    [...document.querySelectorAll('.board-float')].find(b => b.textContent.includes('📋'))?.click())
  await sleep(700)
  pinned.push(await toolsAt('full'))
  for (const p of pinned) {
    if (p.n !== 3) failures.push(`27e-圆钮钉死: ${p.label} 档只剩 ${p.n} 枚圆钮`)
    if (p.whole !== 3) failures.push(`27e-圆钮钉死: ${p.label} 档有圆钮被裁（完整 ${p.whole} 枚）`)
    if (p.hit) failures.push(`27e-圆钮钉死: ${p.label} 档圆钮压在格子上了 —— ${p.hit}`)
  }
  if (new Set(pinned.map(p => p.top)).size !== 1)
    failures.push(`27e-圆钮钉死: 三档的 top 不一样（${pinned.map(p => `${p.label} ${p.top}`).join('、')}）`)
  // 三个样本必须真的是三个不同的档位，否则「top 都一样」这句话什么也没证明
  if (new Set(pinned.map(p => p.dh)).size !== 3)
    failures.push(`27e-圆钮钉死: 三档没真的切过去（抽屉高 ${pinned.map(p => `${p.label} ${p.dh}`).join('、')}）`)
  await shot(pMe, '27e-纯线上-圆钮三档钉死', '.board-float')
  // 收回 peek，别把状态留给后面的屏
  await tapGrab()

  // 27d 资金弹层：银行 / 转账 / 破产入口，一枚悬浮圆钮直开。
  // 它就是试玩里那个死局的出口——现金不足既买不了、又结束不了回合，是因为纯线上
  // 根本没有银行；v0.4 之前它埋在「账本 → 更多」第三层，试玩反馈「太深了」
  await pMe.evaluate(() => {
    const el = [...document.querySelectorAll('.board-float')].find(x => x.textContent.includes('🏦'))
    el?.click()
  })
  await shot(pMe, '27d-纯线上-资金弹层', '.modal input[step="1000"]')
  await expectText(pMe, '27d-纯线上-资金弹层', {
    has: ['资金', '🏦 银行', '玩家间转账', '月息 10%'],
    // v0.12 撤销「跳过动画」：这一层只放此刻要动手的三件事。
    // 连 localStorage 的读取也一起停了，所以全仓库不该再有任何一个勾选框
    hasNot: ['跳过动画', '显示设置'],
  })
  const boxes = await pMe.evaluate(() => document.querySelectorAll('input[type="checkbox"]').length)
  if (boxes) failures.push(`27d-纯线上-资金弹层: 还剩 ${boxes} 个勾选框，「跳过动画」没删干净`)
  await pMe.evaluate(() => document.querySelector('.modal-mask')?.click())
  await sleep(400)

  // 结束回合的出口在「没有别的地方已经摆出动作」时必须常驻：这一步已经决策完（第 3 步），
  // 没有强制卡/机会失业落点/未掷骰这三种会把这一行整行收起的情形，所以它必须在（design/09 §2.4）
  await expectText(pMe, '27e-纯线上-结束回合常驻', { has: ['结束回合'] })
  const ctaRows = await pMe.evaluate(() => document.querySelectorAll('.drawer-cta .cta-row').length)
  if (!ctaRows) failures.push('27e-纯线上-结束回合常驻: 底部操作区没有分行')

  // 27 断线：棋盘压暗 + 骰盘禁用并写明不能掷骰
  offlineOnPurpose = true
  await pOther.setOfflineMode(true)
  await pOther.evaluate(() => document.querySelector('#app').__vue_app__
    .config.globalProperties.$pinia.state.value.game.ws?.close())
  await sleep(1200)
  await shot(pOther, '28-纯线上-断线态', '.toast.err')
  await expectText(pOther, '28-纯线上-断线态', {
    has: ['连接断开，正在重连…', '重新连上之前，操作暂不可用'],
  })
  // 断线时 .offline-dim（opacity:.5）正挂在 .wheel 上——这正是骰子 3D 上下文最容易被
  // WebKit 拍平的场景，专门在这里再查一次
  const diceCtxOffline = await checkDice3dContext(pOther)
  if (!diceCtxOffline.ok)
    failures.push(`28-纯线上-断线态: 骰子 3D 上下文结构回归（${diceCtxOffline.reason}）`)
  await pOther.setOfflineMode(false)
  await sleep(1800)
  offlineOnPurpose = false

  // 29 座次条角标的**正例**：谁身上挂着持续状态，同桌一眼看得出。
  // 上面那间房只有 2 个人，把谁标成出局都会立刻判定胜负、整屏换成结算页，
  // 所以另开一间 3 人房专门验这一条——它不掷骰、不走完整回合，只看渲染。
  {
    const sa = await api('/api/rooms', {
      nickname: '阿盯', name: '状态验证局', maxPlayers: 4, password: null, mode: 'ONLINE' })
    const sb = await api(`/api/rooms/${sa.roomCode}/join`, { nickname: '小盯', password: null })
    const sc = await api(`/api/rooms/${sa.roomCode}/join`, { nickname: '丙盯', password: null })
    const [ga, gb, gc] = [
      await openAs({ ...sa, nickname: '阿盯' }),
      await openAs({ ...sb, nickname: '小盯' }),
      await openAs({ ...sc, nickname: '丙盯' }),
    ]
    const dreams = (await (await fetch(`${BASE}/api/board/fasttrack`)).json()).dreams
    for (const [i, g] of [ga, gb, gc].entries()) {
      await send(g, 'SELECT_PROFESSION')
      await sleep(200)
      await send(g, 'SELECT_DREAM', { dreamId: dreams[i].id })
      await sleep(200)
    }
    await send(ga, 'START_GAME')
    await sleep(600)
    for (const g of [ga, gb]) {
      await g.goto(`${BASE}/#/play`, { waitUntil: 'networkidle2' })
      await sleep(400)
    }
    // 房主移除丙盯 → 他 phase=OUT，还剩 2 人所以对局继续（3 人房才有这个余地）
    await send(ga, 'HOST_REMOVE_PLAYER', { playerId: sc.playerId })
    await sleep(900)
    // 牌桌只画给旁观者看，所以站到「不是我回合」的那一台上（先手由服务端摇骰定）
    const gaTurn = await ga.evaluate(() =>
      (document.querySelector('.hud-turn')?.textContent ?? '').includes('轮到你了'))
    const gWatch = gaTurn ? gb : ga
    await gWatch.evaluate(() => document.querySelector('.drawer-peek .seat-strip')?.click())
    await sleep(500)
    await shot(gWatch, '29-纯线上-座次条角标与牌桌状态', '.seat-dot .mark')
    await expectText(gWatch, '29-纯线上-座次条角标与牌桌状态', { has: ['已出局'] })
    const marks = await gWatch.evaluate(() => ({
      hud: document.querySelectorAll('.hud-turn .seat-dot .mark').length,
      badge: [...document.querySelectorAll('.drawer-body .badge')].map(b => b.textContent.trim()),
    }))
    if (marks.hud !== 1)
      failures.push(`29-纯线上-座次条角标与牌桌状态: HUD 座次条应有 1 个角标，实际 ${marks.hud} 个`)
    if (!marks.badge.some(t => t.includes('已出局')))
      failures.push('29-纯线上-座次条角标与牌桌状态: 牌桌那一行没写「已出局」')
  }

  // 30 结局屏必须排在演出队列后面（design/09 §5.0）。
  //
  // **这一屏是唯一一处合成事件的断言**，理由写清楚：胜利与它的掷骰在同一批事件里到达
  // （`_a_ft_business_bought` 买断成功后会 `_check_income_victory`），而掷骰点数与落点
  // 都由服务端定，冒烟局没有确定路径能走到快车道那 5 个掷骰企业格——真机试玩撞上过，
  // 这里撞不上。所以改成：起一局真的纯线上房间，拿页面手上那份**真的**快照，
  // 只把 status 改成 FINISHED、挂一批带骰子的 lastEvents，往 store 自己那条 WS 的
  // `onmessage` 上补发一帧，与服务端那时广播出来的形状同构（批的形状本身由
  // `test_flows.py::test_victory_arrives_in_the_same_batch_as_its_dice_roll` 钉住）。
  //
  // 修之前：结局屏在同一拍就把整棵板子连同刚排上队的两拍骰子一起卸载，
  // 玩家看到的是「点一下就赢了」，中间什么都没发生过。
  {
    const va = await api('/api/rooms', {
      nickname: '阿闸', name: '结局闸门局', maxPlayers: 4, password: null, mode: 'ONLINE' })
    const vb = await api(`/api/rooms/${va.roomCode}/join`, { nickname: '小闸', password: null })
    const [ha, hb] = [
      await openAs({ ...va, nickname: '阿闸' }, true),
      await openAs({ ...vb, nickname: '小闸' }),
    ]
    const dreams = (await (await fetch(`${BASE}/api/board/fasttrack`)).json()).dreams
    for (const [i, g] of [ha, hb].entries()) {
      await send(g, 'SELECT_PROFESSION')
      await sleep(200)
      await send(g, 'SELECT_DREAM', { dreamId: dreams[i].id })
      await sleep(200)
    }
    await send(ha, 'START_GAME')
    await sleep(600)
    await ha.goto(`${BASE}/#/play`, { waitUntil: 'networkidle2' })
    await sleep(800)

    const injected = await ha.evaluate(() => {
      if (!window.__ws || !window.__lastState) return false
      const s = JSON.parse(localStorage.getItem('cashflow.session'))
      const next = JSON.parse(JSON.stringify(window.__lastState))
      next.status = 'FINISHED'
      next.winnerId = s.playerId
      window.__ws.onmessage({
        data: JSON.stringify({
          type: 'state', seq: (window.__lastSeq ?? 0) + 1, state: next,
          lastEvents: [{
            type: 'DICE_GAMBLE_RESOLVED',
            payload: {
              player_id: s.playerId, card_id: 'sd-013', title: '骰子赌局',
              rolls: [3, 4], total: 7, won: true, stake: 5000, payout: 20000,
            },
          }],
        }),
      })
      return true
    })
    if (!injected) failures.push('30-结局屏闸门: 没抓到 store 那条 WS，这一屏没验成')

    // 翻滚拍：帘幕在、结局屏必须还没出现
    await sleep(150)
    const rollingNow = await ha.evaluate(() => ({
      curtain: !!document.querySelector('.curtain.dice'),
      dice: document.querySelectorAll('.curtain.dice .die3d').length,
      result: !!document.querySelector('.result-hero'),
      // 骰子是这一屏的主体：落定拍会多出「达标线 / 收益 / 成功」几行，
      // 主体不许被它们顶得挪位置（§5.4）。这里记下起手的位置，落定后再量一次。
      heroTop: document.querySelector('.curtain.dice .dice-hero')?.getBoundingClientRect().top ?? -1,
    }))
    await shotNow(ha, '30-纯线上-掷骰帘幕-翻滚')
    if (!rollingNow.curtain) failures.push('30-结局屏闸门: 掷骰帘幕没上屏')
    if (rollingNow.dice !== 2)
      failures.push(`30-结局屏闸门: 帘幕里该有 2 颗骰子，实为 ${rollingNow.dice}`)
    if (rollingNow.result)
      failures.push('30-结局屏闸门: 结局屏抢在演出前面出现了（这正是「点一下就赢了」那个 bug）')

    // 落定拍：点数与成败要写出来，结局屏仍然不许出现
    await sleep(1400)
    const settledNow = await ha.evaluate(() => ({
      text: (document.querySelector('.curtain.dice')?.innerText ?? '').replace(/\n/g, ' '),
      result: !!document.querySelector('.result-hero'),
      heroTop: document.querySelector('.curtain.dice .dice-hero')?.getBoundingClientRect().top ?? -1,
    }))
    await shotNow(ha, '30a-纯线上-掷骰帘幕-落定')
    if (settledNow.result) failures.push('30a-结局屏闸门: 落定拍时结局屏就出现了')
    if (Math.abs(settledNow.heroTop - rollingNow.heroTop) > 2)
      failures.push('30a-结局屏闸门: 落定时骰子被新增的几行字顶得挪了位置'
        + `（${rollingNow.heroTop} → ${settledNow.heroTop}）`)
    for (const t of ['掷出', '7 点', '成功'])
      if (!settledNow.text.includes(t))
        failures.push(`30a-结局屏闸门: 落定拍没写出「${t}」（实为「${settledNow.text}」）`)

    // 演出播完：帘幕退场，结局屏这才接上
    await sleep(2200)
    await shot(ha, '30b-纯线上-演出播完才出结局屏', '.result-hero')
    const done = await ha.evaluate(() => !!document.querySelector('.curtain.dice'))
    if (done) failures.push('30b-结局屏闸门: 演出播完了掷骰帘幕还赖着不走')
  }

  // 文字溢出不靠肉眼查：扫一遍撑破容器的元素（跳过可滚容器与 SVG 内部）
  for (const [name, page] of [['纯线上棋盘', pMe], ['线下行动页', pa]]) {
    const bad = await page.evaluate(() => {
      const out = []
      for (const el of document.querySelectorAll('#app *')) {
        if (el.closest('svg')) continue
        const cs = getComputedStyle(el)
        if (/auto|scroll/.test(cs.overflowX + cs.overflowY)) continue
        if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
          if (parseFloat(cs.lineHeight) / parseFloat(cs.fontSize) < 1.2) continue
          out.push(`${el.tagName.toLowerCase()}.${el.className}`.slice(0, 60))
        }
      }
      return [...new Set(out)].slice(0, 8)
    })
    if (bad.length) console.log(`  ⚠ ${name} 可能溢出：${bad.join(' / ')}`)
  }

  await browser.disconnect()

  if (failures.length) {
    console.error('\n发现问题：')
    for (const f of [...new Set(failures)]) console.error('  ✗ ' + f)
    process.exitCode = 1
  } else {
    console.log(`\n全部通过，截图在 ${OUT}`)
  }
}

main()
  .catch(e => { console.error(e); process.exitCode = 1 })
  .finally(() => { server.kill(); for (const k of killers) k() })
