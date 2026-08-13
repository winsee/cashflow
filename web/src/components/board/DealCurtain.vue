<script setup lang="ts">
/** 全屏发牌翻牌（design/09 §5.3）：牌背飞向屏心 → Y 轴 3D 翻转 → 定格 → 收进抽屉。
 *
 *  **全员同步播放**——说明书要求把卡「大声读出来」，线上就该人人看见同一张牌翻过来。
 *  帘幕底色 = 该牌堆色降到 12% 叠在纸底上：牌翻过来之前就知道面对的是机会还是额外支出。
 *  牌背是米白卡纸 + 该牌堆色双线边框 + 宋体牌堆名，和 GameCard 的正面同一套材质。
 *
 *  点击任意处**终止**整条演出序列并刷到终态（不是加速）。
 *
 *  **卡面由调用方决定**：默认插槽不传就照旧渲染 `GameCard`，职业卡场景传 `ProfessionCard`
 *  （design/09 §1.4.1）。发牌组件不该认识职业卡——那是调用方的知识；
 *  而翻牌的 3D 结构、牌背材质、帘幕基座只该有一份。
 *
 *  **两条节拍表由 `variant` 分开**（design/09 §5.4 v1.0）：牌堆发牌有「飞入放大」那一拍，
 *  职业卡揭牌没有（牌已经在屏上被点了）。共用一段 keyframes 的代价是职业卡白演 0.43s 缩放。
 *
 *  **卡面没到就不起翻**（design/09 §5.4 v0.5）：牌背是 `inset:0` 贴着牌面的，牌面高度一变
 *  牌背跟着变。职业卡那条路径是「帘幕先落下、请求还在路上」，卡面会在翻转途中换进来——
 *  于是一条扁扁的牌背忽然长成一整张。所以卡没到就停在拍 1「牌背待命」，到了才加 `.flipping`。
 *
 *  **飞入要有锚点**（design/09 §5.4 v0.12，`deal` 变体）：第一帧必须压在玩家上一眼看的
 *  那个东西上（棋盘上的落点格），否则「放大」就成了一次没有来由的尺寸突变——
 *  试玩说的「牌背突然变一下大小，然后又翻转」正是这个。见 `from`。
 *
 *  **职业卡揭牌（`reveal` 变体）v0.18 起不再飞入**：v0.12–v0.17 四轮都在修「测量矩形 →
 *  写入 CSS 变量 → 等两帧 → 起播」这条链路本身的边角，每轮都在开发机 + `ui-smoke` 上验证
 *  通过，但真机上依然能看到翻转前的一次尺寸突变——页内 `.prof-back`（父容器有 `max-width`
 *  的 `.page`）与帘幕里 `.deal-card`（父容器铺满视口的 `.curtain`）本来就不是同一个宽度，
 *  这条链路每多一环运行时测量就多一次在真实设备上出现时序错位的机会，问题始终没有断根。
 *  索性砍掉飞入这一拍：`reveal` 变体的 `.deal-card` 从第一帧起就是它自己样式表里写死的
 *  终态尺寸（76%/max 300px、无 translate、scale 恒为 1），不存在依赖矩形测量的中间态，
 *  代价是职业卡不再「从你点的那个位置飞过来」，直接原地淡入 + 翻转。`from`/矩形测量只留给
 *  `deal` 变体（牌堆抽卡，从棋盘格子飞出来）。
 *
 *  **起播要等一帧「结算」**（design/09 §5.4 v0.16）：v0.12 把几何钉对了，但没管**时机**——
 *  `ready()` 从 false 变 true 的那一帧，正好是「新卡面第一次真正挂进 DOM（一次实打实的
 *  布局/绘制）」与「`.flying`/`.flipping` 两个 class 一起挂上、动画开始播」撞在同一帧的时刻。
 *  牌堆卡这支还伴随一轮偏重的响应式重渲染（`fetchCards` 不带缓存，见 style.css:1319），
 *  浏览器要在同一帧里既排新内容的版又要起播 transform 动画，读起来是「卡一下」；
 *  职业卡这支即使内容轻，动画头几帧也会被这次绘制吃掉，读起来是「先跳一下再翻」。
 *  两支症状同源，不是几何数值错了（`--fs/--fx/--fy` 仍是对的）。
 *  修法是标准的「双 `requestAnimationFrame`」：内容到齐后先只让它挂载、自然画一帧
 *  （仍停在飞入前的静止姿态，`--fs` 还很小，v0.12 那条「几何不会跳」原封不动），
 *  下一帧才把 `animate` 置真、真正起播——两次绘制之间隔着至少一次真实的浏览器绘制，
 *  动画起播那一帧不用再扛新内容的布局成本。`<slot>` 里内容什么时候换、`ready()` 什么时候
 *  求值这两条不动，改的只是「什么时候允许动画 class 生效」。 */
import { computed, onMounted, onUpdated, ref, useSlots } from 'vue'
import { DECK_COLOR, DECK_LABEL } from '../../decks'
import type { CardDto } from '../../types'
import GameCard from '../cards/GameCard.vue'

const props = defineProps<{
  deck: string
  title: string
  /** 卡面原文；还没拉到就只显示牌背与标题，不阻塞演出 */
  card?: CardDto | null
  /** 哪一条节拍表。两条路径的拍子本来就不同，**不该共用一段 keyframes**：
   *  - `deal`（默认）= 牌堆发牌，§5.1 拍 6–7：牌背飞向屏心并放大 0.43s + 翻牌 0.52s；
   *  - `reveal` = 职业卡揭牌，§5.4 v0.18：没有飞入这一拍，`.deal-card` 从第一帧起就钉在
   *    终态尺寸，整 0.95s 全部给纯翻牌。
   *
   *  职业卡是玩家点了**页内那张牌背**才起的，它已经在屏上了；v0.12–v0.17 试过让它对齐
   *  那张牌背的矩形飞过来，但这条测量链路在真机上反复出现翻转前的尺寸突变，v0.18 起
   *  索性不飞了，直接原地翻转。 */
  variant?: 'deal' | 'reveal'
  /** 飞入拍的**起点**：源元素在视口坐标里的矩形（棋盘上的落点格）。牌背的第一帧压在它
   *  上面，然后飞到屏心并放大——**位移是这一拍的主语，放大只是随行的**。
   *  **只对 `deal` 变体生效**（v0.18 起）：`reveal` 变体不再飞入，这个 prop 对它是死的，
   *  见文件头「职业卡揭牌 v0.18 起不再飞入」。不给（或量不到）就退回不带锚点的原地放大，
   *  见下面的 `fly`。 */
  from?: DOMRect | null
}>()
const emit = defineEmits<{ (e: 'skip'): void }>()

const slots = useSlots()
const cardEl = ref<HTMLElement | null>(null)
/** 飞入的三个量，挂到 `.deal-card` 上：`.deal-card` 的**基础 transform 就是起飞姿态**
 *  （同「静止态就是牌背」那条路子），动画只负责把它送回原位。
 *  `null` = 没有锚点，CSS 侧的 `var(--fs, .55)` 兜底回原地放大。 */
const fly = ref<Record<string, string> | null>(null)
/** 量过了没有。**量完才允许起播**——否则第一帧会用兜底值（屏心、.55）画一下再跳到起点。
 *  代价只有一帧，而那一帧画的正好是拍 1「牌背待命」的正确姿态。 */
const measured = ref(false)
/** 动画 class（`.flying`/`.flipping`）是否已经获准生效。与「内容到齐了没有」
 *  （`ready()`）故意隔了一帧——见文件头「起播要等一帧结算」。 */
const animate = ref(false)
let animateScheduled = false
function scheduleAnimate() {
  if (animate.value || animateScheduled) return
  animateScheduled = true
  requestAnimationFrame(() => {
    requestAnimationFrame(() => { animate.value = true })
  })
}

/** 在**挂载那一帧**量。量的是自己的**终态**几何——`transform` 不进布局，所以这就是
 *  「飞完之后停在哪儿、多大」；源矩形减它即得起点的偏移与缩放。
 *  **只对 `deal` 变体做这套测量**——`reveal` 变体没有飞入这一拍，`fly` 全程留 `null`，
 *  `.deal-card.reveal` 的 CSS 会把 transform 钉成 `none`（见 style.css），不吃这里的
 *  `var(--fs, .55)` 兜底值。
 *
 *  **宽度只能取 `offsetWidth`，不能取 rect 的宽**：此刻基础 transform 里的 `scale(var(--fs,.55))`
 *  已经生效了，`getBoundingClientRect()` 给的是缩过的框，拿它当分母算出来的 `--fs`
 *  会大出 1/.55 倍。中心点不受影响（`transform-origin` 在正中，缩放不挪中心），照旧取 rect。 */
onMounted(() => {
  if (props.variant !== 'reveal') {
    const el = cardEl.value
    const self = el?.getBoundingClientRect()
    const width = el?.offsetWidth ?? 0
    const src = props.from
    if (self && src && width >= 1 && src.width >= 1) {
      // 棋盘一格只有二十几像素，按原大小起飞是个看不清的点；夹住下限让它仍是「一张牌」。
      const raw = src.width / width
      const scale = Math.min(Math.max(raw, 0.26), 0.6)
      fly.value = {
        '--fx': `${(src.left + src.width / 2) - (self.left + self.width / 2)}px`,
        '--fy': `${(src.top + src.height / 2) - (self.top + self.height / 2)}px`,
        '--fs': `${scale}`,
      }
    }
  }
  measured.value = true
  if (ready()) scheduleAnimate()
})
/** 内容多半是稍后才到（牌堆卡等 `fetchCards`、职业卡等 `SELECT_PROFESSION` 往返）——
 *  这个组件本来就只会因为 `props.card`/插槽内容变化而重渲染，`onUpdated` 恰好是
 *  「内容刚挂进 DOM」之后的第一个钩子。`ready()` 在渲染期求值这条 v1.0 定下的铁律不变。 */
onUpdated(() => { if (ready()) scheduleAnimate() })
const color = computed(() => DECK_COLOR[props.deck] ?? 'var(--line-2)')
const label = computed(() => DECK_LABEL[props.deck] ?? '牌堆')
/** 卡面到齐了没有。两条路径都可能要经历一段待命拍——牌堆发牌（§5.3）的 `card` 来自
 *  一次不带缓存的 `fetchCards`（style.css:1319），职业卡（§5.4）等的是服务端往返；
 *  `ready()` 变 true 之后动画还要再等一帧才起播，见文件头「起播要等一帧结算」。
 *
 *  **必须在渲染时求值，不能写成 `computed`**（v1.0 修）：`useSlots()` 拿到的是组件实例上
 *  那个**普通对象**，父组件重渲染时它被就地改写，没有任何响应式依赖可以追踪。
 *  写成 computed 的话，职业卡这条路径上 `props.card` 恒为 undefined、永远不会让它失效——
 *  第一次算出 `false` 就永远是 `false`，`.flipping` 一辈子加不上，
 *  **整段翻牌动画一次都没播过**（第四轮试玩「怎么没有翻面的动画」的真正根因：
 *  屏上只剩基础 transform 那张缩小的牌背，帘幕一撤，页内的正面直接顶上来）。 */
const ready = () => !!slots.default || !!props.card
</script>

<template>
  <div class="curtain deal-curtain"
       :style="{ '--deck': color, background: `color-mix(in srgb, ${color} 12%, var(--bg))` }"
       @click="emit('skip')">
    <div ref="cardEl" class="deal-card"
         :class="{ flying: animate && measured && props.variant !== 'reveal', reveal: props.variant === 'reveal' }"
         :style="fly ?? undefined">
      <div class="deal-inner" :class="{ flipping: animate && measured, reveal: props.variant === 'reveal' }">
        <div class="deal-face">
          <slot>
            <GameCard v-if="props.card" :card="props.card" />
            <!-- 占位卡面撑住 3:4（与页内 `.prof-back` 同一比例），牌背才有个稳定的尺寸可跟 -->
            <div v-else class="gcard hold"><div class="gcard-title">{{ props.title }}</div></div>
          </slot>
        </div>
        <div class="deal-back card-back" :style="{ color }">{{ label }}</div>
      </div>
    </div>
    <p class="muted" style="margin-top:14px">点一下跳过</p>
  </div>
</template>
