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
import { existsSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(root, '..')
const OUT = join(repo, 'build', 'ui-smoke')
const PORT = 8391
const BASE = `http://127.0.0.1:${PORT}`

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
]
const browserPath = BROWSERS.find(existsSync)
if (!browserPath) { console.error('找不到 Edge/Chrome'); process.exit(1) }
if (!existsSync(join(root, 'dist', 'index.html'))) {
  console.error('缺少 dist/，先跑 npm run build'); process.exit(1)
}

rmSync(OUT, { recursive: true, force: true })
mkdirSync(OUT, { recursive: true })

const py = join(repo, 'server', '.venv', 'Scripts', 'python.exe')
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
  async function openAs(session) {
    const ctx = await browser.createBrowserContext()
    const page = await ctx.newPage()
    await page.setViewport({ width: 400, height: 860, deviceScaleFactor: 2 })
    page.on('pageerror', e => failures.push(`控制台异常: ${e.message}`))
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
  await sleep(400)
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

  // 市场求购：阿明名下两套 2 室公寓 → 小雨抽到求购卡 → 阿明这边应弹出逐套勾选的弹层
  await send(pa, 'HOST_ADJUST', { playerId: a.playerId, delta: 100000, reason: '冒烟：买房本金' })
  for (let i = 0; i < 2; i++) {
    await send(pa, 'DRAW_CARD', { cardId: 'bd-001' })
    await send(pa, 'CARD_DECISION', { decision: 'buy' })
    await send(pa, 'END_TURN')
    await send(pb, 'END_TURN')
    await sleep(250)          // 每条动作各开一条 WS，别让下一轮抢在广播前面
  }
  await send(pa, 'END_TURN')
  await send(pb, 'DRAW_CARD', { cardId: 'mk-020' })   // 求购公寓，按间计价
  await sleep(800)
  await shot(pa, '08c-市场求购-逐套勾选', '.apick')
  // 抽卡人侧：写清通知了谁、谁还没决定；不该出现那个按下会报 BAD_CARD 的「结算」
  await shot(pb, '08d-市场求购-抽卡人侧', '.badge')
  await expectText(pb, '08d-市场求购-抽卡人侧', {
    has: ['已通知 1 位持有该资产的玩家', '待决定'],
    hasNot: ['强制卡'],
    noButtons: ['结算'],
  })
  await pa.evaluate(() => {
    const el = [...document.querySelectorAll('.modal .btn')].find(x => x.textContent.includes('都不卖'))
    if (el) el.click()
  })
  await sleep(600)
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
  await clickText(pa, '.bigbtn', '创建房间')
  await shot(pa, '17-大厅-创建房间弹层', '.modal input')

  // ===== 纯线上模式（design/09 §10 的屏幕清单） =====
  // 18 建房选模式：两张卡二选一，各写清「你需要准备什么」
  await shot(pa, '18-建房-模式二选一', '.mode-pick .bigbtn')
  await expectText(pa, '18-建房-模式二选一', {
    has: ['线下辅助', '纯线上', '一台手机'],
  })
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

  // 20 准备页：模式锁 + 抽职业卡（不是挑）
  await qa.goto(`${BASE}/#/room`, { waitUntil: 'networkidle2' })
  await shot(qa, '20-纯线上准备页-模式锁与抽职业卡', '.badge.turn')
  await expectText(qa, '20-纯线上准备页-模式锁与抽职业卡', {
    has: ['抽一张职业卡', '不能重抽'],
    hasNot: ['找到你手上那张职业卡'],
  })

  await clickText(qa, '.btn', '抽职业卡')
  await sleep(600)
  // 21 抽过之后不留任何看着能换一张的控件
  await expectText(qa, '20a-抽过职业卡-无重抽入口', { noButtons: ['🎴 抽职业卡'] })

  // 22 在快车道棋盘上点粉格选梦想。小上先选，阿线的棋盘上应当看得见那枚圆点
  //（就是实体那块奶酪，全员可见谁选了哪个）
  await send(qb, 'SELECT_PROFESSION')
  await sleep(300)
  await send(qb, 'SELECT_DREAM', { dreamId: 'ft-d-jet' })
  await sleep(500)
  await shot(qa, '21-纯线上准备页-棋盘选梦想', '.wheel .disc circle')
  const dots = await qa.evaluate(() =>
    document.querySelectorAll('.board-sq circle').length)
  if (dots < 1) failures.push('21-纯线上准备页-棋盘选梦想: 别人选走的梦想没插上圆点')

  await qa.evaluate(() => {
    // 只有粉格（梦想格）可点：取第一个可点的格子
    const g = [...document.querySelectorAll('.board-sq.tappable')][0]
    g?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await sleep(700)
  await shot(qa, '21a-梦想已选-收成摘要', '.steps .s.ok')
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

  await shot(pMe, '22-纯线上-棋盘待掷骰', '.wheel .die')
  await expectText(pMe, '22-纯线上-棋盘待掷骰', {
    has: ['第 1 步 / 3', '掷骰'],
    hasNot: ['你停在哪种格子', '手动选卡'],
  })
  const tabbars = await pMe.evaluate(() => document.querySelectorAll('.tabbar').length)
  if (tabbars) failures.push('22-纯线上-棋盘待掷骰: 纯线上不该有常驻标签栏')

  // 24 观战：别人的回合是只读骰盘 + 一行「他走到哪一步」
  await shot(pOther, '23-纯线上-观战', '.drawer-peek')

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
  for (let i = 0; i < 12 && !onDeal; i++) {
    await clickText(pMe, '.drawer-cta .btn', '掷')
    if (i === 0) {
      await sleep(900)
      await shot(pMe, '24-纯线上-掷骰与走格', '.wheel .die')
    }
    await sleep(3200)
    const t = await screen(pMe)
    if (t.includes('抽哪一叠')) { onDeal = true; break }
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
    await clickText(pMe, '.drawer-body .btn', '小生意')
    await sleep(1000)
    await shot(pMe, '26-纯线上-全屏发牌翻牌', '.deal-curtain')
    await sleep(2200)
    await shot(pMe, '26a-纯线上-卡面决策（抽屉 half）', '.drawer-cta .btn')
    await expectText(pMe, '26a-纯线上-卡面决策（抽屉 half）', { has: ['第 2 步 / 3'] })
    await shot(pOther, '26b-纯线上-旁观者看到同一张卡', '.gcard-title')
    // 决策完 → 第 ③ 步，主 CTA 变成结束回合。
    // 抽到哪一张由服务端牌堆决定，所以按钮文案不能写死——点掉那一排里的「不要 / 付掉」那个
    await pMe.evaluate(() => {
      const want = ['放弃', '我不买', '执行', '支付', '确认']
      const btns = [...document.querySelectorAll('.drawer-cta .btn')]
      const el = btns.find(b => want.some(w => b.textContent.includes(w))) ?? btns[0]
      el?.click()
    })
    await sleep(900)
    await shot(pMe, '26c-纯线上-结束回合', '.drawer-cta .btn')
    await expectText(pMe, '26c-纯线上-结束回合', { has: ['第 3 步 / 3', '结束回合'] })
  } else {
    await shot(pMe, '25-纯线上-落点处理', '.drawer-body')
  }

  // 26 账本：报表 / 总览 / 日志三分段（full 档抽屉，不是 tabbar）
  await pMe.evaluate(() => {
    const el = [...document.querySelectorAll('.board-float')].find(x => x.textContent.includes('📋'))
    el?.click()
  })
  await shot(pMe, '27-纯线上-账本-报表', '.drawer-body table.fin')
  await clickText(pMe, '.drawer-peek .btn', '总览')
  await shot(pMe, '27a-纯线上-账本-总览', '.drawer-body .progress')
  await clickText(pMe, '.drawer-peek .btn', '日志')
  await shot(pMe, '27b-纯线上-账本-日志', '.drawer-body .logdot')
  // 纯线上没有「本人更正」这条路径
  await expectText(pMe, '27b-纯线上-账本-日志', { noButtons: ['更正'] })
  await clickText(pMe, '.drawer-peek .btn', '收起')

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
  await pOther.setOfflineMode(false)
  await sleep(1800)
  offlineOnPurpose = false

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
