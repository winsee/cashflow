<script setup lang="ts">
/** 非移动掷骰的全屏帘幕（design/09 §5.3 v0.25）：骰子赌局卡（`sd-013`）与
 *  快车道掷骰企业格（`FT_BUY_BUSINESS` 的 `diceRule`）。
 *
 *  **为什么这两种要一屏，而移动掷骰不要**：移动掷骰是玩家自己点轮心那颗骰子换来的，
 *  眼睛本来就在棋盘上；这两种是在**抽屉里**点了一个决策按钮换来的，而那一刻抽屉正被
 *  整张卡面撑高、`.board-stage` 被挤到最小，轮心那颗骰子按 `--bws` 只剩 20~35px，
 *  视线还停在刚点过的按钮上。按 §5.5「一件事该给多大的呈现，看它在游戏机制里有多重」，
 *  一笔六位数买入的成败不该是一颗 20px 的斑点。
 *
 *  交互照抄 `PaydayCurtain`/`PenaltyCurtain`：点任意处跳过，**不给「知道了」按钮**，
 *  **只给当事人**（旁观者维持现状——棋盘轮心那颗骰子照常转，同发薪帘幕的分工）。
 *
 *  屏上的数**全部来自 `store` 里那两份存根**（`catchDiceOutcome` 在换快照之前从事件流
 *  现抓，且本来就只给当事人），不新拉一份 payload：帘幕散场后抽屉里那张存根卡读的是
 *  同一份数据，抄两遍必然抄出两种口径。帘幕是仪式、会散场；存根是散场后还能回看的
 *  那一份（同 v0.9 ⑧ 发薪帘幕与结算日存根的分工）。
 */
import { computed } from 'vue'
import Die3d from './Die3d.vue'
import { fmt, signed, useGame } from '../../store'
import type { StageStep } from '../../stage'

const props = defineProps<{ step: Extract<StageStep, { kind: 'dice' }> }>()
defineEmits<{ (e: 'skip'): void }>()

const game = useGame()

/** 翻滚那一拍 `settling` 为假：骰子还在转，成败先不揭晓 */
const rolling = computed(() => !props.step.settling)
const total = computed(() => props.step.rolls.reduce((a, b) => a + b, 0))

/** 两种来源各给一套文案。`success` 只在落定那一拍才读——翻滚期间揭晓结果，
 *  等于让骰子转给一个已经知道答案的人看。 */
/** 读的是 `lastBiz`/`lastGamble` **原始那两份，不是带回合键的 `bizStub`/`gambleStub` getter**。
 *
 *  那两个 getter 拿 `turnCount@currentPlayerId` 比对，而 `current_player_id` 是服务端的
 *  **派生属性**（`models.py`：`status != PLAYING` 一律返回 None）——这一批正好把对局结束了，
 *  于是键必然对不上、getter 一律返回 null，帘幕上就只剩点数、写不出「需 X 点 / 成功 / 收益」。
 *  这正是房主那一局的形状（买断企业过线当场获胜），`test_flows.py` 里那条测试钉着它。
 *
 *  不用键也是安全的：这一拍与写入那两份的 `catchDiceOutcome` 出自**同一批事件**、
 *  判据逐字相同（`dice_roll != null` + `player_id === 我`），而帘幕的寿命由这一拍圈定，
 *  本来就不需要回合键来兜。抽屉里那两张存根卡照旧走带键的 getter——它们要随回合过期。 */
const biz = computed(() => (props.step.solo === 'FT_BUSINESS' ? game.lastBiz : null))
const gamble = computed(() => (props.step.solo === 'GAMBLE' ? game.lastGamble : null))

const title = computed(() => biz.value?.name || gamble.value?.title || '掷骰')
/** 达标线：企业格是「≥ 阈值」，赌局卡的条件写在卡面上，这里只复述「掷出几点」 */
const need = computed(() => {
  const b = biz.value
  return b?.threshold ? `需 ${b.threshold} 点及以上` : ''
})
/** `null` = 还不知道（翻滚拍还没揭晓，或存根没到）。
 *  **不许退化成 `false`**：那会把「不知道」说成「未达标」——屏上是一句假话，
 *  底色还会跟着转冷。存根与这一拍出自同一批事件、同一道 `player_id` 判据，
 *  正常路径上不会缺；缺了就什么都不断言，点数照旧显示。 */
const success = computed<boolean | null>(() => {
  if (biz.value) return biz.value.success
  if (gamble.value) return gamble.value.won
  return null
})

/** 收益行：企业格成功给月现金流或一次性收益，赌局卡给赔付；失败各写各的代价。 */
const gainLine = computed(() => {
  const b = biz.value
  if (b) {
    if (!b.success) return { label: '首付已支付 · 未获得收益', value: signed(-b.downPayment) }
    if (b.cashflow) return { label: '每月现金流', value: signed(b.cashflow) }
    return { label: '一次性收益', value: signed(b.lumpSum) }
  }
  const g = gamble.value
  if (!g) return null
  return g.won
    ? { label: '赢得', value: signed(g.payout) }
    : { label: '赌注已付', value: signed(-g.stake) }
})
</script>

<template>
  <div class="curtain dice" :class="{ ftx: step.solo === 'FT_BUSINESS', lost: !rolling && success === false }"
       @click="$emit('skip')">
    <div class="curtain-inner">
      <div class="dice-title">{{ title }}</div>

      <!-- 一颗（赌局卡可能两颗）大号骰子。`--d` 在这儿写死，不吃 `--bws`：
           帘幕是全屏的，与棋盘此刻被挤成多大毫无关系。 -->
      <div class="dice-hero" :class="`n${step.rolls.length}`">
        <Die3d v-for="(r, i) in step.rolls" :key="i" :index="i"
               :value="rolling ? null : r" :rolling="rolling" />
      </div>

      <div class="conv">
        <div class="cline hero">
          <span>{{ rolling ? '骰子还在转…' : '掷出' }}</span>
          <b>{{ rolling ? '—' : `${total} 点` }}</b>
        </div>
        <div v-if="!rolling && need" class="cline"><span>达标线</span><b>{{ need }}</b></div>
        <div v-if="!rolling && gainLine" class="cline">
          <span>{{ gainLine.label }}</span><b>{{ gainLine.value }}</b>
        </div>
        <div v-if="!rolling && biz && biz.success" class="cline">
          <span>已支付首付</span><b>{{ fmt(biz.downPayment) }}</b>
        </div>
      </div>

      <h2 v-if="!rolling && success !== null">{{ success ? '成功' : '未达标' }}</h2>

      <p class="fineprint">点一下跳过</p>
    </div>
  </div>
</template>
