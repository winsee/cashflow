/** 快车道落点（绿格 · 粉格）的取数：**一处定义，三处引用**。
 *
 *  这七个 computed 原本只长在 `OnlineLandingPanel` 里。v0.23 把决策按钮从抽屉正文搬到了
 *  `.drawer-cta`（design/09 §4.4：决策在上一行、结束回合在下一行且降为 ghost），于是
 *  `OnlineRoomView` 也要同一份数——按钮上写「加价 $200,000」，卡面上写的必须是同一个价。
 *  再加上全屏揭示帘幕里那张卡面（§5.3）也要同一份 props，抄第二遍就必然出现第二种口径。
 *
 *  **只读不算权威**：梦想加价、企业是否已被买断，权威都在服务端状态里
 *  （`dreamPriceBumps` / `ftSoldSquares`），这里只做展示换算。
 */
import { computed } from 'vue'
import { fmt, ftBizNums, useGame } from './store'

export function useFtLanding() {
  const game = useGame()
  const me = computed(() => game.me)
  const landing = computed(() => game.state?.landing ?? null)

  const biz = computed(() => {
    if (landing.value?.type !== 'FT_BUSINESS') return null
    return game.board?.fastTrack.businesses.find(b => b.id === landing.value!.ref_id) ?? null
  })
  const dream = computed(() => {
    if (landing.value?.type !== 'FT_DREAM') return null
    return game.board?.fastTrack.dreams.find(d => d.id === landing.value!.ref_id) ?? null
  })
  /** 梦想被加价过就翻倍累加（服务端的 dreamPriceBumps 是权威，这里只作展示） */
  const dreamPrice = computed(() => {
    const d = dream.value
    if (!d) return 0
    return d.price * (1 + (game.state?.dreamPriceBumps[d.id] ?? 0))
  })
  const dreamOwner = computed(() =>
    game.state?.players.find(p => p.dreamId === dream.value?.id) ?? null)
  const isMyDream = computed(() => dreamOwner.value?.id === me.value?.id)
  const bizSold = computed(() =>
    !!biz.value && !!(game.state?.ftSoldSquares ?? {})[biz.value.id])

  /** 这一格要付的钱还差多少。快车道上现金不够就是买不了：这一段**没有**银行贷款
   *  （说明书第 6 页），不能给一个指向不存在入口的按钮 —— 如实说清楚比给假出口好。
   *
   *  三种花钱的落点（买企业 / 买梦想·加价·占位 / 捐慈善）**同一个口径**，服务端也是同一道
   *  `_require_cash(..., loan_hint=False)`。大于 0 时按钮直接置灰：这不是「UI 的闸门比服务端严」
   *  ——两边读的是同一个 `cash`、同一个价，服务端此刻必然拒绝，让人点一下换一条红字
   *  只是把「买不了」说得更晚。老鼠赛跑那边按钮照旧可点，因为那儿的缺口**是可以补的**
   *  （旁边就是「去贷款」），快车道没有那条路。 */
  const ftShort = computed(() => {
    const cash = me.value?.cash ?? 0
    switch (landing.value?.type) {
      case 'FT_BUSINESS': return biz.value ? Math.max(0, biz.value.down_payment - cash) : 0
      case 'FT_DREAM': return Math.max(0, dreamPrice.value - cash)
      case 'FT_CHARITY':
        return Math.max(0, (game.board?.fastTrack.charityCost ?? 0) - cash)
      default: return 0
    }
  })

  /** 这一格的卡面（`FtSquareCard` 的整套 props）。**三处共用同一份**：揭示帘幕里那张、
   *  抽屉里当事人那张、旁观者那张——抄三遍必然抄出三种写法。
   *
   *  文案一律写成**与看的人无关**的事实（「小雨选定的梦想」而不是「你只能加价」）：
   *  同一张卡面此刻正摆在全场的屏幕上，「你」是谁并不一致；而「我现在能做什么」
   *  从 v0.23 起由底部那一行按钮说（按钮上就写着「加价 $200,000」）。
   *  唯一的例外是「这是你的」——它对每个人都成立且都有用（别人踩了我的梦想格，我也想知道）。 */
  const ftCard = computed(() => {
    const b = biz.value
    if (b) {
      return {
        kind: 'biz' as const,
        kindLabel: b.dice_rule ? '企业投资 · 需掷骰' : '企业投资',
        name: b.name,
        nums: bizSold.value ? [{ label: '状态', value: '已被买断' }] : ftBizNums(b),
        taken: bizSold.value,
        mine: false,
        tip: b.dice_rule
          ? `掷 1 粒骰，${b.dice_rule.threshold} 点及以上才成功（骰子由服务端摇）` : '',
      }
    }
    const d = dream.value
    if (d) {
      const owner = dreamOwner.value
      return {
        kind: 'dream' as const,
        kindLabel: isMyDream.value ? '梦想 · 这是你的'
          : (owner ? `梦想 · ${owner.nickname}选定` : '梦想 · 无人选定'),
        name: d.name,
        nums: [{ label: '价格', value: fmt(dreamPrice.value) }],
        taken: false,
        mine: isMyDream.value,
        tip: '',
      }
    }
    return null
  })

  return { landing, biz, dream, dreamPrice, dreamOwner, isMyDream, bizSold, ftShort, ftCard }
}
