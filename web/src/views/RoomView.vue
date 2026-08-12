<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import { DECK_COLOR, DECK_LABEL } from '../decks'
import { prefersReducedMotion } from '../stage'
import { fmt, useGame } from '../store'
import type { CardDto, FtDream } from '../types'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import InviteDialog from '../components/InviteDialog.vue'
import SwipePicker from '../components/SwipePicker.vue'
import BaseButton from '../components/base/BaseButton.vue'
import PageHeader from '../components/base/PageHeader.vue'
import ProfessionCard from '../components/cards/ProfessionCard.vue'
import ModeBadge from '../components/ModeBadge.vue'
import DealCurtain from '../components/board/DealCurtain.vue'
import { copyText } from '../share'

const game = useGame()
const router = useRouter()
const professions = ref<CardDto[]>([])
const dreams = ref<FtDream[]>([])
const order = ref<string[]>([])

onMounted(async () => {
  professions.value = await game.fetchCards('PROFESSION')
  const board = await game.fetchFasttrackBoard()
  dreams.value = board.dreams
})

/** 纯线上：职业由服务端随机发（说明书 P.2 步骤 4 写的是「抽」），回合顺序开局自动排。
 *  线下辅助模式那边选职业是**录入你摸到的实体卡**，语义正确，一个字不改。 */
const online = computed(() => game.isOnline)

function showModeLock() {
  game.flash('对局模式在建房时选定，开局后不可更改', 'info')
}

/** 纯线上的职业卡：点牌背 → 服务端随机发 → 翻开整张卡（design/09 §1.4.1）。
 *  `drawing` 期间牌背只做无信息的轻晃；`revealing` 是那 0.95s 的全屏揭牌。
 *  **重连不补播**：`revealing` 只由这次点击置位，刷新回来直接是翻开态。 */
const drawing = ref(false)
const revealing = ref(false)
/** 帘幕里那张牌的**起飞矩形** = 玩家刚点的这张牌背此刻在屏上的位置与大小（design/09 §5.4 v0.12）。
 *  不给锚点的话两张牌背对不上：页内这张是 `76% × (页宽 − 24px)`，帘幕那张是 `76% × 视口宽`
 *  且钉在屏心——390px 手机上是 278px 与 296px，位置也不同，交接时就是一次尺寸突变。 */
const profBackEl = ref<HTMLElement | null>(null)
const profFrom = ref<DOMRect | null>(null)
const myProfession = computed(() =>
  professions.value.find(p => p.id === game.me?.professionId) ?? null)

async function drawProfession() {
  if (drawing.value) return
  drawing.value = true
  // 降级出口与演出层同一条口径（design/09 §5.2 / §5.4）：直接给翻开态，不揭牌
  if (prefersReducedMotion()) {
    await game.act('SELECT_PROFESSION')
    drawing.value = false
    return
  }
  // 起飞矩形要在**帘幕落下之前**量：一落下这张牌背就交班藏起来了
  profFrom.value = profBackEl.value?.getBoundingClientRect() ?? null
  // 帘幕**先落下**再发请求：等 act 返回才置位的话，服务端的状态会抢在帘幕前面到，
  // 页面先把整张职业卡摆出来（`v-if="game.me?.professionId"` 那一支），
  // 帘幕这才盖上去重新翻一遍——试玩里看到的「闪现一下正面」就是这半帧。
  revealing.value = true
  const ok = await game.act('SELECT_PROFESSION')
  drawing.value = false
  if (!ok) { revealing.value = false; return }
  // 翻牌 0.95s + 定格（design/09 §5.4）。卡随后就留在页内，不必在帘幕上读完
  setTimeout(() => { revealing.value = false }, 2200)
}

/** 「谁认领了哪个梦想」写在下面的出牌顺序里，一人一行。
 *  v0.2 那只只读快车道轮盘已撤销：快车道格面按 §3.5 不写字，48 个一模一样的格子里插两个
 *  小圆点，得逐格点开才知道谁是谁——信息密度低于一行字，却占掉整屏（design/09 §1.4.2 v0.3）。 */

const joinUrl = computed(() =>
  `${location.origin}/#/join/${game.session?.roomCode ?? ''}`)

const players = computed(() => game.state?.players ?? [])
const isHost = computed(() => game.me?.isHost ?? false)

// 两步引导：找到手上那张职业卡 → 挑一个梦想。都选完才进到排序/开局。
const step = ref<1 | 2>(1)
// 纯线上不自动跳步：翻开的那张卡要停在屏上让人看完，由「下一步 · 挑梦想」推进
watch(() => game.me?.professionId, (p) => {
  if (p && step.value === 1 && !online.value) step.value = 2
})

const doneSetup = computed(() => !!game.me?.professionId && !!game.me?.dreamId)
const editing = ref(false)
watch(doneSetup, (d) => { if (d) editing.value = false })
// 重选期间服务端的旧选择原封不动，画面上得当它没选过 —— 步骤条/出牌顺序都得看这两个，不能只看服务端字段
const profShown = computed(() => !editing.value && !!game.me?.professionId)
const dreamShown = computed(() => !editing.value && !!game.me?.dreamId)

// 卡堆里当前居中那张（滑动时实时变），主按钮固定文案，不跟着卡名变
const curProfession = ref('')
const curDream = ref('')
watch(professions, (list) => { if (!curProfession.value && list.length) curProfession.value = list[0].id })
watch(dreams, (list) => { if (!curDream.value && list.length) curDream.value = list[0].id })

// 其他玩家已占用的职业/梦想（规则：玩家间不可重复）。
// 不从卡堆里删掉，只在状态行写明被谁选走了 —— 玩家手里可能正好是那张，得知道发生了什么。
const takenProfessions = computed(() => {
  const m = new Map<string, string>()
  for (const p of players.value)
    if (p.id !== game.session?.playerId && p.professionId) m.set(p.professionId, p.nickname)
  return m
})
const takenDreams = computed(() => {
  const m = new Map<string, string>()
  for (const p of players.value)
    if (p.id !== game.session?.playerId && p.dreamId) m.set(p.dreamId, p.nickname)
  return m
})

const profItems = computed(() => professions.value.map(p => ({ id: p.id, name: p.title })))
const dreamItems = computed(() => dreams.value.map(d => ({ id: d.id, name: d.name })))
const profById = (id: string) => professions.value.find(p => p.id === id)
const dreamById = (id: string) => dreams.value.find(d => d.id === id)

/** 贵的梦想被加价后代价更高，对手多半不会碰 —— 新玩家看不出这层策略，界面替他说出来 */
function dreamTip(d: FtDream): string {
  const taken = takenDreams.value.get(d.id)
  if (taken) return '同一个梦想不能重复选。'
  const max = Math.max(...dreams.value.map(x => x.price))
  const min = Math.min(...dreams.value.map(x => x.price))
  if (d.price >= max) return `最贵的一档。别人要花 ${fmt(d.price)} 才能加价一次，多半不会碰。`
  if (d.price <= min) return '最便宜的一档。攒够得快，但对手加价的成本也低。'
  return '中间价位。攒钱与被加价的风险都居中。'
}

async function pickProfession() {
  const id = curProfession.value
  if (takenProfessions.value.has(id)) {
    game.flash(`这张已被 ${takenProfessions.value.get(id)} 选走了`, 'err')
    return
  }
  if (await game.act('SELECT_PROFESSION', { professionId: id })) step.value = 2
}

async function pickDream() {
  const id = curDream.value
  if (takenDreams.value.has(id)) {
    game.flash(`这个梦想已被 ${takenDreams.value.get(id)} 选走了`, 'err')
    return
  }
  // doneSetup 在「重选」期间从头到尾都是 true（服务端旧选择原封不动），
  // 那条 watch(doneSetup) 只在 false→true 那一刻才会关 editing，重选走一圈永远等不到这一刻，
  // 必须在这里自己收尾
  if (await game.act('SELECT_DREAM', { dreamId: id })) { editing.value = false; game.flash('准备好了，等其他人') }
}

function syncOrder() {
  if (!order.value.length) order.value = players.value.map(p => p.id)
  for (const p of players.value) if (!order.value.includes(p.id)) order.value.push(p.id)
  order.value = order.value.filter(id => players.value.some(p => p.id === id))
}

function move(idx: number, dir: number) {
  syncOrder()
  const j = idx + dir
  if (j < 0 || j >= order.value.length) return
  ;[order.value[idx], order.value[j]] = [order.value[j], order.value[idx]]
}

const orderedPlayers = computed(() => {
  syncOrder()
  return order.value.map(id => players.value.find(p => p.id === id)!).filter(Boolean)
})

const notReady = computed(() => players.value.filter(p => !p.professionId || !p.dreamId))

async function saveOrder() {
  syncOrder()
  await game.act('SET_TURN_ORDER', { order: order.value })
}

async function start() {
  // 纯线上模式的顺序由服务端开局掷骰排定，房主排的那一份会被拒（ONLINE_AUTO_ORDER）
  if (!online.value) await saveOrder()
  await game.act('START_GAME')
}

async function leaveGame() {
  const lines = !isHost.value
    ? ['退出后将释放名额，不能自行恢复该座位。', '如误退出，需由房主在日志中撤销退出记录。']
    : players.value.length > 1
      ? ['退出后房主将自动转让给下一位加入的玩家。', '如误退出，需由新房主在日志中撤销退出记录。']
      : ['房间里没有其他人，退出后房间将直接解散，不能恢复。']
  const ok = await confirmAction({
    title: '退出房间？',
    lines,
    warning: '此操作会清除本机对局身份。',
    danger: true,
    okText: '退出对局',
  })
  if (ok && await game.leaveGame()) router.replace('/')
}

const urlInput = ref<HTMLInputElement | null>(null)
const copyState = ref<'idle' | 'copied' | 'failed'>('idle')
const showInvite = ref(false)

async function copyUrl() {
  const ok = await copyText(joinUrl.value, urlInput.value)
  copyState.value = ok ? 'copied' : 'failed'
  setTimeout(() => { copyState.value = 'idle' }, 2000)
}
</script>

<template>
  <div class="page no-tabbar" v-if="game.state">
    <PageHeader :title="`${game.state.settings.name} · ${game.state.roomCode}`"
                back="📤 邀请" @back="showInvite = true">
      <template #actions>
        <!-- 模式在建房时选定：带一把锁，让它看起来就是不可改的，而不是点了报错的控件 -->
        <ModeBadge :mode="game.state.mode" locked @lock="showModeLock" />
        <BaseButton variant="ghost" small @click="copyUrl">
          {{ copyState === 'copied' ? '已复制' : '复制链接' }}
        </BaseButton>
      </template>
    </PageHeader>
    <p v-if="copyState === 'failed'" class="muted" style="color:var(--red)">
      复制失败，请在「邀请」里长按地址手动复制
    </p>
    <!-- 非安全上下文没有 clipboard API，execCommand 需要一个真实可选中的输入框 -->
    <input ref="urlInput" readonly :value="joinUrl" tabindex="-1" aria-hidden="true"
           style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0" />

    <!-- 两步：职业卡 → 梦想。选完后整块收成一行摘要，把版面让给出牌顺序。 -->
    <div class="steps">
      <span class="s" :class="profShown ? 'ok' : 'now'">
        <span class="n">{{ profShown ? '✓' : '1' }}</span>职业卡</span>
      <span class="ln"></span>
      <span class="s" :class="dreamShown ? 'ok' : (profShown ? 'now' : '')">
        <span class="n">{{ dreamShown ? '✓' : '2' }}</span>梦想</span>
    </div>

    <!-- 都选好了就收成一行摘要，把版面让给出牌顺序；想改随时展开 -->
    <div v-if="doneSetup && !editing" class="card">
      <div class="row between">
        <div>
          <b>{{ game.me?.professionTitle }}</b>
          <div class="muted">梦想：{{ dreamById(game.me?.dreamId ?? '')?.name ?? '已选' }}</div>
        </div>
        <button class="btn ghost small" @click="editing = true; step = 1">重选</button>
      </div>
    </div>

    <template v-else>
      <!-- 步骤 1：职业卡。挤成网格每张只剩两三个数字，而玩家要核对的是整张卡 -->
      <template v-if="step === 1">
        <!-- 纯线上：说明书写的是「抽」一张职业卡，不是挑。抽过之后界面上不留任何
             看着能换一张的控件——那会让人以为随机是可以刷的 -->
        <template v-if="online">
          <h2 style="margin-bottom:2px">抽一张职业卡</h2>
          <p class="muted" style="margin:0">说明书里职业是抽的，不是挑的。抽到哪张就是哪张，不能重抽。</p>
          <!-- 抽过了：摆出整张卡，页面上不留任何看着能换一张的控件
               （没有「重抽」、没有第二张牌背），否则玩家会以为随机是可以刷的。
               **揭牌期间这一支不渲染**：`.curtain` 是 420ms 淡入的，帘幕还没变实之前
               页内这张正面会**从半透明的帘幕底下透出来**——这才是「点了先闪一下正面」
               的真正来源（上一轮只把置位顺序调对了，没管透出来这件事）。
               揭牌期间背后留着牌背（走下面那一支），和点击前是同一幅画面。 -->
          <template v-if="game.me?.professionId && !revealing">
            <p class="muted" style="text-align:center;margin:10px 0 0">这就是你这一局的身份</p>
            <ProfessionCard v-if="myProfession" :card="myProfession" />
            <button class="btn block" @click="step = 2">下一步 · 挑梦想</button>
          </template>
          <!-- 还没抽：一张牌背。不做「进页自动发」——进页那一瞬 WS 可能还没连上，
               会先闪一屏空白再蹦出一张卡；让玩家自己揭这一下，也把"这张是我抽的"落到实处 -->
          <template v-else>
            <!-- `waiting` 的轻晃是「请求还在路上」的提示，**帘幕落下就没有观众了**。
                 `handoff` 则是把这张牌背整个交班给帘幕里那张（v0.12）：帘幕里那张此刻正好
                 压在这张的位置、这张的大小上（`profFrom` 锚点），两张同时在场只会在 180ms
                 淡入里叠成重影。**藏用 visibility 不用 v-if**——留着占位，页面才不会在帘幕
                 底下重排一次。 -->
            <div ref="profBackEl" class="prof-back card-back"
                 :class="{ waiting: drawing && !revealing, handoff: revealing }"
                 :style="{ color: DECK_COLOR.PROFESSION }" @click="drawProfession">
              {{ DECK_LABEL.PROFESSION }}
            </div>
            <p class="muted" style="text-align:center">
              {{ drawing ? '正在发牌…' : '点一下，抽你的职业' }}
            </p>
          </template>
        </template>
        <template v-else>
        <h2 style="margin-bottom:2px">找到你手上那张职业卡</h2>
        <p class="muted" style="margin:0">左右滑动，和手里那张核对</p>
        <SwipePicker v-if="professions.length" v-model="curProfession" :items="profItems" :half-width="143">
          <template #default="{ item }">
            <ProfessionCard :card="profById(item.id)!" :taken-by="takenProfessions.get(item.id)" />
          </template>
          <template #meta>共 {{ professions.length }} 张</template>
        </SwipePicker>
        <p v-else class="muted">正在加载职业卡…</p>
        <button class="btn block" :disabled="!curProfession || takenProfessions.has(curProfession)"
                @click="pickProfession">
          {{ takenProfessions.has(curProfession) ? '这张已被选走' : '选这张，下一步' }}
        </button>
        </template>
        <button v-if="game.me?.dreamId" class="btn ghost block small" @click="step = 2">跳到梦想</button>
      </template>

      <!-- 步骤 2：梦想 -->
      <template v-else>
        <div class="row between">
          <button class="btn ghost small" @click="step = 1">上一步</button>
          <span class="muted">已选 {{ game.me?.professionTitle || '—' }}</span>
        </div>
        <h2 style="margin-bottom:2px">挑一个梦想</h2>
        <p class="muted" style="margin:0">在快车道上买下它就赢了。别人踩到可以加价，选贵的更保险。</p>
        <!-- 两种模式**同一段模板**：快车道格面按 §3.5 不写字，在棋盘上选等于面对 23 个
             一模一样的粉格；价格、被加价一次的代价、「已被选走」的图章全在卡片上 -->
        <SwipePicker v-if="dreams.length" v-model="curDream" :items="dreamItems" :half-width="122">
          <template #default="{ item }">
            <div class="fcard dream dreampick" :class="{ taken: !!takenDreams.get(item.id) }">
              <div v-if="takenDreams.get(item.id)" class="taken-overlay">
                <div class="taken-mark">
                  <span class="taken-mark-label">已被选走</span>
                  <span class="taken-mark-who">{{ takenDreams.get(item.id) }}</span>
                </div>
              </div>
              <div class="fcard-kind">梦想</div>
              <div class="fcard-name">{{ dreamById(item.id)!.name }}</div>
              <div class="fcard-nums">
                <div><span>价格</span><b>{{ fmt(dreamById(item.id)!.price) }}</b></div>
                <div><span>被加价一次</span><b>{{ fmt(dreamById(item.id)!.price * 2) }}</b></div>
              </div>
              <p class="fcard-tip">{{ dreamTip(dreamById(item.id)!) }}</p>
            </div>
          </template>
          <template #meta>共 {{ dreams.length }} 个</template>
        </SwipePicker>
        <p v-else class="muted">正在加载梦想…</p>
        <button class="btn block" :disabled="!curDream || takenDreams.has(curDream)" @click="pickDream">
          {{ takenDreams.has(curDream) ? '这个已被选走' : '我准备好了' }}
        </button>
      </template>
    </template>

    <!-- 出牌顺序：选完梦想后才出现，线下掷骰后由房主排先后；重选期间跟摘要卡一起收起 -->
    <div v-if="doneSetup && !editing" class="card">
      <div class="row between" style="margin-bottom:9px">
        <h2 style="margin:0">出牌顺序</h2>
        <span class="badge" v-if="isHost">房主</span>
        <span class="badge" v-else>{{ players.length }}/{{ game.state.settings.max_players }} 人</span>
      </div>
      <!-- 纯线上：说明书 P.2「开始游戏」1 是每人掷骰比大小，骰子在服务端，顺序也归服务端 -->
      <p v-if="online" class="muted" style="margin:0 0 9px">
        开局时系统会替每个人各摇一次骰，点数最大者先行（平局重摇），无需手排。
      </p>
      <div v-for="(p, i) in orderedPlayers" :key="p.id" class="card inner">
        <div class="row between">
          <div class="row" style="gap:8px">
            <span class="num" style="width:18px;color:var(--muted)">{{ i + 1 }}</span>
            <div>
              <b style="font-size:13px">{{ p.nickname }}<span v-if="p.id === game.me?.id">（你）</span></b>
              <!-- 梦想归属就公示在这儿：一人一行、写出名字。
                   「已选梦想」四个字等于没说，而这里正是玩家会看的地方 -->
              <div class="muted">
                {{ p.professionTitle || '还没选职业'
                }}<template v-if="p.dreamId"> · {{ dreamById(p.dreamId)?.name ?? '已选梦想' }}</template>
              </div>
            </div>
          </div>
          <div class="row" style="gap:4px" v-if="isHost && !online">
            <button class="btn ghost small" @click="move(i, -1)">↑</button>
            <button class="btn ghost small" @click="move(i, 1)">↓</button>
          </div>
          <span v-else-if="!p.professionId || !p.dreamId" class="badge">等待中</span>
        </div>
      </div>
    </div>

    <!-- 开局：只在自己也选完了才出现，其它时候页面停在步骤 1/2 -->
    <template v-if="doneSetup && !editing">
      <!-- 置灰必须给理由：谁没好，写在按钮上 -->
      <button v-if="isHost" class="btn block" :disabled="players.length < 2 || notReady.length > 0" @click="start">
        <template v-if="players.length < 2">开始对局 · 至少还需 1 人</template>
        <template v-else-if="notReady.length">开始对局 · 还有 {{ notReady.length }} 人没准备好</template>
        <template v-else>开始对局（自动发钱）</template>
      </button>
      <p v-else class="muted" style="text-align:center">等待房主开始对局…</p>
    </template>
    <button class="btn block ghost" @click="leaveGame">退出对局</button>

    <InviteDialog v-if="showInvite" :code="game.state.roomCode" :url="joinUrl"
                  :nickname="game.me?.nickname" @close="showInvite = false" />

    <!-- 揭牌：牌背飞到屏心 → Y 轴翻转 → 露出整张职业卡。与发牌共用 3D 结构与牌背材质，
         但**节拍表不同**（`variant="reveal"`，design/09 §5.4 v1.0）：牌已经在屏上被点了，
         没有「飞入放大」那一拍，整 0.95s 都给旋转，尺寸从头到尾不变 -->
    <!-- 卡还没到（帘幕先落下、请求还在路上）时**不给默认插槽**，让 DealCurtain 用它自己的
         占位卡面兜住高度——插槽给了但内容为空的话，牌面高度塌成 0，连牌背都看不见了 -->
    <DealCurtain v-if="revealing" variant="reveal" deck="PROFESSION" title="职业卡"
                 :from="profFrom" @skip="revealing = false">
      <template v-if="myProfession" #default>
        <ProfessionCard :card="myProfession" />
      </template>
    </DealCurtain>
  </div>
  <ConnectingFallback v-else />
</template>
