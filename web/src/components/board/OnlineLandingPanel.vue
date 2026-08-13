<script setup lang="ts">
/** 第 ② 步：处理落点（design/09 §4.3）。
 *
 *  「你停在哪」由服务端派发，这里只负责翻译成「你现在要决定什么」。
 *  只有机会格需要玩家做子选择（大 / 小生意），其余落点要么是「发牌 → 决策」，
 *  要么是「自动 → 回执」。
 */
import { computed } from 'vue'
import { askBankLoan } from '../../bankrequest'
import { confirmAction } from '../../confirm'
import { fmt, ftBizNums, useGame } from '../../store'
import FtSquareCard from '../cards/FtSquareCard.vue'

const game = useGame()
const me = computed(() => game.me)
const landing = computed(() => game.state?.landing ?? null)
const board = computed(() => game.board)

const biz = computed(() => {
  if (landing.value?.type !== 'FT_BUSINESS') return null
  return board.value?.fastTrack.businesses.find(b => b.id === landing.value!.ref_id) ?? null
})
const dream = computed(() => {
  if (landing.value?.type !== 'FT_DREAM') return null
  return board.value?.fastTrack.dreams.find(d => d.id === landing.value!.ref_id) ?? null
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

/** 慈善捐款额 = 总收入 10%（与引擎同一口径，四舍五入到美元） */
const charityCost = computed(() =>
  Math.round((me.value?.derived.totalIncome ?? 0) / 10))

/** 失业要付一次总支出，付不出可以先贷款（老鼠赛跑阶段银行一直在） */
const unemploymentShort = computed(() =>
  Math.max(0, (me.value?.derived.totalExpenses ?? 0) - (me.value?.cash ?? 0)))

/** 快车道上现金不够就是买不了：这一段**没有**银行贷款（说明书第 6 页），
 *  不能给一个指向不存在入口的按钮 —— 如实说清楚比给假出口好。 */
const ftShort = computed(() => {
  const cash = me.value?.cash ?? 0
  if (landing.value?.type === 'FT_BUSINESS' && biz.value)
    return Math.max(0, biz.value.down_payment - cash)
  if (landing.value?.type === 'FT_DREAM') return Math.max(0, dreamPrice.value - cash)
  return 0
})

async function pay(action: string, payload: Record<string, any>, title: string, lines: string[]) {
  if (!await confirmAction({ title, lines, okText: '确认' })) return
  await game.act(action, payload)
}

/** 落点已处理、且**从头到尾没问过我**的那些格子（design/09 §4.3）。
 *
 *  试玩反馈：停在银行结算日，屏幕上什么都没有，回合就突然可以结束了 —— 玩家不知道刚发生了什么。
 *  这张卡是「交代」，不是「待办」：不弹层、不提档、没有按钮，回合一换自然消失。
 *  金额一律取**已经算好的权威状态**，不在客户端重算（钱早在走格那一拍就入账了）。
 */
/** 金额在模板里用不了 `Math.abs`（不在表达式白名单），在这儿就带上正负号成文 */
function signed(n: number): string {
  return (n >= 0 ? '+' : '−') + fmt(n < 0 ? -n : n)
}

const FT_HIT_TEXT: Record<string, { icon: string; title: string; why: string }> = {
  FT_TAX_AUDIT: { icon: '🧾', title: '税务审计', why: '现金减半上缴' },
  FT_LAWSUIT: { icon: '⚖️', title: '官司', why: '现金减半赔付' },
  FT_DIVORCE: { icon: '💔', title: '离婚', why: '失去全部现金' },
}

/** 结算日存根：全屏发薪帘幕（PaydayCurtain）散场后留在抽屉里的那张摘要卡。
 *
 *  帘幕是**仪式**——自动消散、还能被一次点击跳过，播完零残留；而「经过」根本不产生
 *  landing，下面那张落点结果卡只认「停在」。所以没看清就没有任何回看的地方，
 *  这张卡补的就是这一段（同发牌那条老规矩：帘幕落下，卡片落进抽屉可以慢慢看）。
 *
 *  金额取**事件**（store.catchStub）而不是快照：一次移动可能连过两个结算格，
 *  快照里只有单月值，×2 在那儿看不出来。
 */
const stub = computed(() => {
  const s = game.settlementStub
  if (!s || s.playerId !== me.value?.id) return null
  const ft = s.track === 'FAST_TRACK'
  const name = ft ? '现金流量日' : '银行结算日'
  // 停在这一格 vs 只是路过：两句话不一样，而 landing 正好分得清
  const stopped = landing.value?.type === (ft ? 'FT_PAYDAY' : 'PAYDAY')
  return {
    icon: ft ? '💰' : '🏦',
    title: `${stopped ? '停在' : '本回合经过'}${name}${s.times > 1 ? ` ×${s.times}` : ''}`,
    why: s.times > 1
      ? `${ft ? '现金流量日收入' : '月现金流'} ${signed(s.cashflow)} × ${s.times}`
      : (ft ? '非工资收入已自动入账' : '本月收入已自动入账'),
    amount: s.amount,
  }
})

/** 与惩罚帘幕的分工按**频次**切（和结算日存根同一条规矩）：
 *
 *  - 每回合都可能发生的（银行结算日 / 现金流量日）走上面那张存根卡：它随回合自然消失，
 *    不要求任何确认，所以**金额写在那儿**——没有回执替它说钱。
 *  - 一局只撞上几次的重击（孩子 / 失业 / 快车道三个惩罚格）现在有全屏惩罚帘幕
 *    （`PenaltyCurtain`）负责报数，这儿的 `done` 不再重复；帘幕散场后的回看
 *    交给下面的 `hitStub`（同 `stub` 的先例：帘幕是仪式、自动消散，没看清就没地方回看）。
 */
const done = computed<{ icon: string; title: string; why: string; amount?: number } | null>(() => {
  const lg = landing.value
  const m = me.value
  if (!lg || !lg.resolved || !m) return null
  switch (lg.type) {
    // PAYDAY / FT_PAYDAY 不在这儿——**结算日归结算日存根管**（见下面的 stub）。
    // CHILD / UNEMPLOYMENT / FT_TAX_AUDIT / FT_DIVORCE / FT_LAWSUIT 也不在这儿——
    // 全屏惩罚帘幕 + hitStub 管，一个位置只有一个主人，两处都画就会把同一笔钱说两遍。
    default:
      // 服务端已经把话写好了（已被买断的绿格、就地破产）就照搬，没写就不作声——
      // 机会/市场/额外支出这些落点的交代由卡面本身承担，这里再补一句是重复。
      return lg.note ? { icon: '📍', title: lg.note, why: '' } : null
  }
})

/** 惩罚帘幕存根：`PenaltyCurtain` 散场后留在抽屉里的摘要卡，供点太快跳过帘幕的人回看。 */
const hitStub = computed(() => {
  const s = game.penaltyStub
  if (!s || s.playerId !== me.value?.id) return null
  if (s.hitKind === 'CHILD') {
    return {
      icon: '👶', title: '喜添一名孩子',
      why: `现在共 ${s.childCount} 个孩子，每月孩子支出 ${fmt(s.childExpense)}`,
      amount: undefined as number | undefined,
    }
  }
  if (s.hitKind === 'UNEMPLOYMENT') {
    return { icon: '💼', title: '停在失业格', why: '已支付一次总支出，并停赛 2 轮', amount: -s.amount }
  }
  const t = FT_HIT_TEXT[`FT_${s.hitKind}`]
  return { icon: t.icon, title: `停在${t.title}格`, why: t.why, amount: -s.amount }
})
</script>

<template>
  <!-- 结算日存根：可以和「还欠一个决定」的落点同时出现
       （经过结算日之后落在机会格上，两件事都得说） -->
  <div v-if="stub" class="card inner landing-done">
    <span class="ic">{{ stub.icon }}</span>
    <div class="tx">
      <div class="t1">{{ stub.title }}</div>
      <div class="t2">{{ stub.why }}</div>
    </div>
    <span class="amt money" :class="stub.amount >= 0 ? 'pos' : 'neg'">{{ signed(stub.amount) }}</span>
  </div>

  <!-- 惩罚帘幕（失业/孩子/税务审计/离婚/官司）散场后的存根：帘幕已经报过数，
       这儿是给点太快跳过的人回看，可以和结算日存根同时出现 -->
  <div v-if="hitStub" class="card inner landing-done">
    <span class="ic">{{ hitStub.icon }}</span>
    <div class="tx">
      <div class="t1">{{ hitStub.title }}</div>
      <div class="t2">{{ hitStub.why }}</div>
    </div>
    <span v-if="hitStub.amount !== undefined" class="amt money"
          :class="hitStub.amount >= 0 ? 'pos' : 'neg'">{{ signed(hitStub.amount) }}</span>
  </div>

  <div v-if="landing && !landing.resolved" class="stack" style="gap:10px">
    <!-- 机会格：唯一需要玩家做子选择的落点 -->
    <template v-if="landing.type === 'OPPORTUNITY'">
      <b style="font-size:13px">你停在机会格 · 抽哪一叠？</b>
      <p class="muted" style="margin:0">停在机会格必须抽一张牌，两叠只能选一叠。</p>
      <div class="btn-row">
        <button class="btn grow" @click="game.chooseDealSize('SMALL')">小生意</button>
        <button class="btn ghost grow" @click="game.chooseDealSize('BIG')">大买卖</button>
      </div>
    </template>

    <template v-else-if="landing.type === 'CHARITY'">
      <b style="font-size:13px">慈善事业</b>
      <p class="muted" style="margin:0">
        捐出总收入的 10%（{{ fmt(charityCost) }}），此后 3 轮可自选掷 1 或 2 粒骰。不捐也可以直接结束回合。
      </p>
      <button class="btn block" @click="pay('CHARITY', {}, '捐款做慈善？',
        [`将支付 ${fmt(charityCost)}`, '此后 3 轮内可自选掷 1 或 2 粒骰'])">
        捐 {{ fmt(charityCost) }}
      </button>
    </template>

    <template v-else-if="landing.type === 'UNEMPLOYMENT'">
      <b style="font-size:13px">失业</b>
      <p class="muted" style="margin:0">
        需支付一次总支出 {{ fmt(me?.derived.totalExpenses) }}，并停赛 2 轮。现金不够可先向银行贷款。
      </p>
      <div v-if="unemploymentShort > 0" class="card inner danger" style="background:var(--red-soft)">
        <div class="row between">
          <span style="font-size:12.5px;font-weight:700;color:var(--red)">
            现金还差 {{ fmt(unemploymentShort) }}</span>
          <button class="btn small gold" @click="askBankLoan(unemploymentShort)">去贷款</button>
        </div>
      </div>
      <button class="btn block warn" @click="pay('UNEMPLOYMENT', {}, '支付失业损失？',
        [`将支付 ${fmt(me?.derived.totalExpenses)}`, '随后停赛 2 轮'])">
        支付 {{ fmt(me?.derived.totalExpenses) }}
      </button>
    </template>

    <!-- 快车道绿格 -->
    <template v-else-if="landing.type === 'FT_BUSINESS' && biz">
      <FtSquareCard kind="biz" :kind-label="biz.dice_rule ? '企业投资 · 需掷骰' : '企业投资'"
                    :name="biz.name" :taken="bizSold" :nums="ftBizNums(biz)"
                    :tip="biz.dice_rule ? `掷 1 粒骰，${biz.dice_rule.threshold} 点及以上才成功（骰子由服务端摇）` : ''" />
      <p v-if="!bizSold && ftShort > 0" class="muted" style="color:var(--red);margin:0">
        现金还差 {{ fmt(ftShort) }}。快车道没有银行贷款，现金不够就买不了，可以直接结束回合。
      </p>
      <button v-if="!bizSold" class="btn block"
              @click="pay('FT_BUY_BUSINESS', { squareId: biz.id }, '买下这项企业投资？',
                [`将支付 ${fmt(biz.down_payment)}`])">
        买入 {{ fmt(biz.down_payment) }}
      </button>
    </template>

    <!-- 快车道粉格：自己的直接买下即获胜；别人的可加价；无主的可原价占位 -->
    <template v-else-if="landing.type === 'FT_DREAM' && dream">
      <FtSquareCard kind="dream" :kind-label="isMyDream ? '梦想 · 这是你的' : '梦想'"
                    :name="dream.name" :mine="isMyDream"
                    :nums="[{ label: '价格', value: fmt(dreamPrice) }]"
                    :tip="dreamOwner && !isMyDream ? `${dreamOwner.nickname} 选定的梦想，你只能加价` : ''" />
      <p v-if="ftShort > 0" class="muted" style="color:var(--red);margin:0">
        现金还差 {{ fmt(ftShort) }}。快车道没有银行贷款，现金不够就买不了，可以直接结束回合。
      </p>
      <button v-if="isMyDream" class="btn block gold"
              @click="pay('FT_BUY_DREAM', { squareId: dream.id }, '买下你的梦想？',
                [`将支付 ${fmt(dreamPrice)}`, '买下即获胜'])">
        买下我的梦想 {{ fmt(dreamPrice) }}
      </button>
      <button v-else-if="dreamOwner" class="btn block"
              @click="pay('FT_DOUBLE_DREAM', { squareId: dream.id }, '给这个梦想加价？',
                [`将支付 ${fmt(dreamPrice)}`, '此后该梦想的价格翻一倍'])">
        加价 {{ fmt(dreamPrice) }}
      </button>
      <button v-else class="btn block"
              @click="pay('FT_CLAIM_DREAM', { squareId: dream.id }, '原价买下占位？',
                [`将支付 ${fmt(dreamPrice)}`, '纯粹占位：不获胜、不加价、不改任何人的现金流'])">
        买下占位 {{ fmt(dreamPrice) }}
      </button>
    </template>

    <template v-else-if="landing.type === 'FT_CHARITY'">
      <b style="font-size:13px">慈善事业</b>
      <p class="muted" style="margin:0">
        捐 {{ fmt(board?.fastTrack.charityCost) }}，此后**永久**可自选掷 1、2 或 3 粒骰。
      </p>
      <button class="btn block"
              @click="pay('FT_CHARITY', {}, '捐款做慈善？',
                [`将支付 ${fmt(board?.fastTrack.charityCost)}`, '此后永久可自选掷 1–3 粒骰'])">
        捐 {{ fmt(board?.fastTrack.charityCost) }}
      </button>
    </template>
  </div>

  <!-- 这一格没问过我就处理完了：给一句交代，不是待办，所以没有按钮、也不提档 -->
  <div v-else-if="done" class="card inner landing-done">
    <span class="ic">{{ done.icon }}</span>
    <div class="tx">
      <div class="t1">{{ done.title }}</div>
      <div v-if="done.why" class="t2">{{ done.why }}</div>
    </div>
    <span v-if="done.amount" class="amt money"
          :class="done.amount >= 0 ? 'pos' : 'neg'">{{ signed(done.amount) }}</span>
  </div>
</template>
