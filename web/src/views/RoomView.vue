<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import { fmt, useGame } from '../store'
import type { CardDto, FtDream } from '../types'
import ConnectingFallback from '../components/ConnectingFallback.vue'
import InviteDialog from '../components/InviteDialog.vue'
import SwipePicker from '../components/SwipePicker.vue'
import BaseButton from '../components/base/BaseButton.vue'
import PageHeader from '../components/base/PageHeader.vue'
import ProfessionCard from '../components/cards/ProfessionCard.vue'
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

const joinUrl = computed(() =>
  `${location.origin}/#/join/${game.session?.roomCode ?? ''}`)

const players = computed(() => game.state?.players ?? [])
const isHost = computed(() => game.me?.isHost ?? false)

// 两步引导：找到手上那张职业卡 → 挑一个梦想。都选完才进到排序/开局。
const step = ref<1 | 2>(1)
watch(() => game.me?.professionId, (p) => { if (p && step.value === 1) step.value = 2 })

const doneSetup = computed(() => !!game.me?.professionId && !!game.me?.dreamId)
const editing = ref(false)
watch(doneSetup, (d) => { if (d) editing.value = false })

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
  if (taken) return `${taken}已经选了这个。同一个梦想不能重复选。`
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
  if (await game.act('SELECT_DREAM', { dreamId: id })) game.flash('准备好了，等其他人')
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
  await saveOrder()
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
      <span class="s" :class="game.me?.professionId ? 'ok' : 'now'">
        <span class="n">{{ game.me?.professionId ? '✓' : '1' }}</span>职业卡</span>
      <span class="ln"></span>
      <span class="s" :class="game.me?.dreamId ? 'ok' : (game.me?.professionId ? 'now' : '')">
        <span class="n">{{ game.me?.dreamId ? '✓' : '2' }}</span>梦想</span>
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
        <h2 style="margin-bottom:2px">找到你手上那张职业卡</h2>
        <p class="muted" style="margin:0">左右滑动，和手里那张核对</p>
        <SwipePicker v-if="professions.length" v-model="curProfession" :items="profItems" :half-width="143">
          <template #default="{ item }">
            <ProfessionCard :card="profById(item.id)!" />
          </template>
          <template #meta>
            <span>
              共 {{ professions.length }} 张
              <template v-if="takenProfessions.get(curProfession)">
                · {{ profById(curProfession)?.title }}已被{{ takenProfessions.get(curProfession) }}选走
              </template>
            </span>
          </template>
        </SwipePicker>
        <p v-else class="muted">正在加载职业卡…</p>
        <button class="btn block" :disabled="!curProfession || takenProfessions.has(curProfession)"
                @click="pickProfession">
          {{ takenProfessions.has(curProfession) ? '这张已被选走' : '选这张，下一步' }}
        </button>
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
        <SwipePicker v-if="dreams.length" v-model="curDream" :items="dreamItems" :half-width="122">
          <template #default="{ item }">
            <div class="fcard dream dreampick">
              <div class="fcard-kind">梦想</div>
              <div class="fcard-name">{{ dreamById(item.id)!.name }}</div>
              <div class="fcard-nums">
                <div><span>价格</span><b>{{ fmt(dreamById(item.id)!.price) }}</b></div>
                <div><span>被加价一次</span><b>{{ fmt(dreamById(item.id)!.price * 2) }}</b></div>
              </div>
              <p class="fcard-tip">{{ dreamTip(dreamById(item.id)!) }}</p>
            </div>
          </template>
          <template #meta><span>共 {{ dreams.length }} 个</span></template>
        </SwipePicker>
        <p v-else class="muted">正在加载梦想…</p>
        <button class="btn block" :disabled="!curDream || takenDreams.has(curDream)" @click="pickDream">
          {{ takenDreams.has(curDream) ? '这个已被选走' : '我准备好了' }}
        </button>
      </template>
    </template>

    <!-- 出牌顺序：线下掷骰后由房主排先后 -->
    <div class="card">
      <div class="row between" style="margin-bottom:9px">
        <h2 style="margin:0">出牌顺序</h2>
        <span class="badge" v-if="isHost">房主</span>
        <span class="badge" v-else>{{ players.length }}/{{ game.state.settings.max_players }} 人</span>
      </div>
      <div v-for="(p, i) in orderedPlayers" :key="p.id" class="card inner">
        <div class="row between">
          <div class="row" style="gap:8px">
            <span class="num" style="width:18px;color:var(--muted)">{{ i + 1 }}</span>
            <div>
              <b style="font-size:13px">{{ p.nickname }}<span v-if="p.id === game.me?.id">（你）</span></b>
              <div class="muted">
                {{ p.professionTitle || '还没选职业' }}<template v-if="p.dreamId"> · 已选梦想</template>
              </div>
            </div>
          </div>
          <div class="row" style="gap:4px" v-if="isHost">
            <button class="btn ghost small" @click="move(i, -1)">↑</button>
            <button class="btn ghost small" @click="move(i, 1)">↓</button>
          </div>
          <span v-else-if="!p.professionId || !p.dreamId" class="badge">等待中</span>
        </div>
      </div>
    </div>

    <!-- 置灰必须给理由：谁没好，写在按钮上 -->
    <button v-if="isHost" class="btn block" :disabled="players.length < 2 || notReady.length > 0" @click="start">
      <template v-if="players.length < 2">开始对局 · 至少还需 1 人</template>
      <template v-else-if="notReady.length">开始对局 · 还有 {{ notReady.length }} 人没准备好</template>
      <template v-else>开始对局（自动发钱）</template>
    </button>
    <p v-else class="muted" style="text-align:center">等待房主开始对局…</p>
    <button class="btn block ghost" @click="leaveGame">退出对局</button>

    <InviteDialog v-if="showInvite" :code="game.state.roomCode" :url="joinUrl"
                  :nickname="game.me?.nickname" @close="showInvite = false" />
  </div>
  <ConnectingFallback v-else />
</template>
