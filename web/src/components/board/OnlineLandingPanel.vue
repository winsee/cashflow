<script setup lang="ts">
/** 第 ② 步：处理落点（design/09 §4.3）。
 *
 *  「你停在哪」由服务端派发，这里只负责翻译成「你现在要决定什么」。
 *  只有机会格需要玩家做子选择（大 / 小生意），其余落点要么是「发牌 → 决策」，
 *  要么是「自动 → 回执」。
 *
 *  **快车道那两种格子（绿格 · 粉格）从 v0.23 起只剩卡面**：决策按钮搬去了 `.drawer-cta`
 *  的上一行，与牌堆卡的「买入 / 放弃」同一处（design/09 §4.4 那张表本来就是这么画的，
 *  只是当初实现成了「按钮长在正文里」——于是「结束回合」永远是一块与买入同重的主按钮）。
 *  分工从此与 `OnlineCardPanel` 一致：**卡面纯呈现，决策按钮钉在抽屉底**。
 *
 *  **`spectator` = 我不是当前玩家**：只渲染快车道那张卡面 + 一句「谁正在决定」。
 *  说明书要求把卡「大声读出来」，线上就该人人看见同一张卡——而此前这个组件整个只挂在
 *  `isMyTurn` 上，同桌其他人一个字都看不到。个人账目（现金缺口、三张存根）**不对旁观者广播**，
 *  同 `OnlineCardPanel` 里 `gambleStub` 那条既有规矩。
 */
import { computed } from 'vue'
import { askBankLoan } from '../../bankrequest'
import { confirmAction } from '../../confirm'
import { useFtLanding } from '../../ftlanding'
import { charityCost, fmt, useGame } from '../../store'
import FtSquareCard from '../cards/FtSquareCard.vue'

const props = defineProps<{ spectator?: boolean }>()

const game = useGame()
const me = computed(() => game.me)
const board = computed(() => game.board)
// 取数在 `ftlanding.ts` 一处定义：底部按钮区与揭示帘幕上的卡面要的是同一份数
const { landing, bizSold, ftShort, ftCard } = useFtLanding()

/** 慈善捐款额 = 总收入 10%（公式在 store 一处定义，按钮上写多少这里就得是多少） */
const charity = computed(() => charityCost(me.value))

/** 失业要付一次总支出，付不出可以先贷款（老鼠赛跑阶段银行一直在） */
const unemploymentShort = computed(() =>
  Math.max(0, (me.value?.derived.totalExpenses ?? 0) - (me.value?.cash ?? 0)))

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

/** 快车道掷骰企业格结算存根：棋盘中央的骰子落定之后，交代掷了几点、有没有达标、
 *  拿到了什么——`FtSquareCard` 结算后只会标「已买断」，这句话原来无处可说（design/09 遗留项）。 */
const bizStub = computed(() => {
  const s = game.bizStub
  if (!s || s.playerId !== me.value?.id) return null
  // `.amt` 这个槽位在 stub/hitStub 里一贯是「此刻实际发生的现金变动」，不是「这笔交易划不划算」——
  // 掷骰企业格成功后拿到的要么是月现金流（往后每个月才到账，此刻没有这笔现金），
  // 要么是一次性收益（此刻就到账）。前者是速率、后者是金额，不能相加减；
  // 月现金流只在 `why` 里说清楚，`.amt` 只算「首付付出 + 一次性收益到账」这一次的净现金。
  const immediateGain = s.success ? s.lumpSum : 0
  return {
    icon: '🎲',
    title: `掷出 ${s.roll} 点 · 需 ${s.threshold} 点及以上 · ${s.success ? '成功' : '未达标'}`,
    why: s.success
      ? (s.cashflow ? `每月现金流 +${fmt(s.cashflow)}` : `一次性收益 +${fmt(s.lumpSum)}`)
      : '首付已支付，未获得收益',
    amount: immediateGain - s.downPayment,
  }
})
</script>

<template>
  <!-- 旁观者：只看得到快车道那张卡面 + 一句「谁正在决定」。
       个人账目（现金缺口、三张存根）不对旁观者广播，所以这一支彻底走另一条路。 -->
  <div v-if="props.spectator" class="stack" style="gap:10px">
    <!-- 不给 `.deck-chip`：卡面自己第一行就是「企业投资」/「梦想 · 谁选定」，
         而且是同一个颜色。牌堆卡要那枚色标是因为 `GameCard` 的来源只是一条细色带。 -->
    <b style="font-size:13px">{{ game.currentPlayer?.nickname ?? '对手' }} 正在决定</b>
    <FtSquareCard v-if="ftCard" v-bind="ftCard" />
  </div>

  <template v-else>
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

    <!-- 快车道掷骰企业格结算存根：可以和上面两张同时出现（同一回合先经过结算日再买断企业） -->
    <div v-if="bizStub" class="card inner landing-done">
      <span class="ic">{{ bizStub.icon }}</span>
      <div class="tx">
        <div class="t1">{{ bizStub.title }}</div>
        <div class="t2">{{ bizStub.why }}</div>
      </div>
      <span class="amt money" :class="bizStub.amount >= 0 ? 'pos' : 'neg'">{{ signed(bizStub.amount) }}</span>
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

      <!-- 慈善（两条赛道各一个格）：与快车道绿格粉格同一条规矩，**只剩说明**，
           「捐」按钮在 `.drawer-cta` 上一行（design/09 §4.4 的「可选落点」一行）。 -->
      <template v-else-if="landing.type === 'CHARITY'">
        <b style="font-size:13px">慈善事业</b>
        <p class="muted" style="margin:0">
          捐出总收入的 10%（{{ fmt(charity) }}），此后 3 轮可自选掷 1 或 2 粒骰。不捐也可以直接结束回合。
        </p>
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

      <!-- 快车道绿格 / 粉格：**只剩卡面与一句解释**，买入/加价/占位的按钮在 `.drawer-cta`
           上一行（design/09 §4.4）。现金缺口留在这儿——它是解释不是动作，而正文的下沿
           正好紧贴按钮区，读完这句话眼睛就落在按钮上。 -->
      <template v-else-if="ftCard">
        <FtSquareCard v-bind="ftCard" />
        <p v-if="!bizSold && ftShort > 0" class="muted" style="color:var(--red);margin:0">
          现金还差 {{ fmt(ftShort) }}。快车道没有银行贷款，现金不够就买不了，可以直接结束回合。
        </p>
      </template>

      <template v-else-if="landing.type === 'FT_CHARITY'">
        <b style="font-size:13px">慈善事业</b>
        <p class="muted" style="margin:0">
          捐 {{ fmt(board?.fastTrack.charityCost) }}，此后<b>永久</b>可自选掷 1、2 或 3 粒骰。
        </p>
        <p v-if="ftShort > 0" class="muted" style="color:var(--red);margin:0">
          现金还差 {{ fmt(ftShort) }}。快车道没有银行贷款，现金不够就捐不了，可以直接结束回合。
        </p>
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
</template>
