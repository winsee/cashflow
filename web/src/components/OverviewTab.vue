<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { confirmAction } from '../confirm'
import { fmt, ftWinProgress, FT_WIN_INCREMENT, useGame } from '../store'
import type { Player } from '../types'
import StatementTab from './StatementTab.vue'
import StatusChips from './StatusChips.vue'
import BaseModal from './base/BaseModal.vue'

const game = useGame()
const router = useRouter()
const st = computed(() => game.state!)
const isHost = computed(() => game.me?.isHost ?? false)

const detailPlayer = ref<Player | null>(null)

/** 判据一字未改，只是从卡片上搬到了记录卡弹层里 */
function canRemove(p: Player): boolean {
  return isHost.value && p.id !== game.me?.id && p.phase !== 'OUT' && st.value.status === 'PLAYING'
}

async function removePlayer(p: Player) {
  const ok = await confirmAction({
    title: `移除玩家「${p.nickname}」？`,
    lines: ['用于玩家中途退出：轮转将永久跳过 TA', '误点可由房主在「日志」中撤销'],
    danger: true,
    okText: '移除',
  })
  if (ok && await game.act('HOST_REMOVE_PLAYER', { playerId: p.id })) {
    // 人都移除了，他的记录卡就该退场（否则弹层还开着，底下那枚按钮也还在）
    detailPlayer.value = null
    game.flash(`已移除 ${p.nickname}`)
  }
}

async function endGame() {
  const ok = await confirmAction({
    title: '结束对局？',
    lines: ['所有玩家将退出房间返回首页', '账目日志保留在服务器，可在结束前导出'],
    warning: '此操作不可撤销',
    danger: true,
    okText: '结束对局',
  })
  if (ok) await game.act('END_GAME')
}

async function leaveGame() {
  const ok = await confirmAction({
    title: '退出对局？',
    lines: ['你的回合将被永久跳过，不能自行恢复该座位。', '如误退出，需由房主在日志中撤销退出记录。'],
    warning: '此操作会清除本机对局身份。',
    danger: true,
    okText: '退出对局',
  })
  if (ok && await game.leaveGame()) router.replace('/')
}
</script>

<template>
  <div v-if="st">
    <!-- 出局的人降透明度但不隐藏 —— 他还在桌上 -->
    <div v-for="p in st.players" :key="p.id" class="card"
         :class="{ current: p.id === st.currentPlayerId }"
         :style="{ cursor: 'pointer', opacity: p.phase === 'OUT' ? .55 : 1 }"
         @click="detailPlayer = p">
      <div class="row between">
        <div>
          <b>{{ p.nickname }}</b>
          <span class="muted">· {{ p.professionTitle || '—' }}</span>
          <span v-if="p.id === st.currentPlayerId" class="badge turn" style="margin-left:6px">行动中</span>
        </div>
        <div class="num big">{{ fmt(p.cash) }}</div>
      </div>

      <!-- 持续状态：这一页信息最全，主状态与次要状态（快车道 / 分期收款 / 孩子数）都写出来 -->
      <StatusChips :player="p" minor style="margin-top:6px" />

      <template v-if="p.phase === 'RAT_RACE'">
        <div class="row between muted" style="margin-top:6px">
          <span>月现金流 <b :class="p.derived.monthlyCashflow >= 0 ? 'pos' : 'neg'">{{ fmt(p.derived.monthlyCashflow) }}</b></span>
          <span>非工资 {{ fmt(p.derived.passiveIncome) }} / 支出 {{ fmt(p.derived.totalExpenses) }}</span>
        </div>
        <div class="progress" style="margin-top:4px">
          <div :style="{ width: Math.min(100, p.derived.totalExpenses ? p.derived.passiveIncome / p.derived.totalExpenses * 100 : 0) + '%' }" />
        </div>
      </template>
      <template v-else-if="p.phase === 'FAST_TRACK'">
        <!-- 两个阶段用各自的进度语言，但卡片结构一致，便于横向比较 -->
        <div class="row between muted" style="margin-top:6px">
          <span>现金流量日收入 {{ fmt(p.fasttrack.current_income) }}</span>
          <span>距胜利还差 {{ fmt(Math.max(0, p.fasttrack.initial_income + FT_WIN_INCREMENT - p.fasttrack.current_income)) }}</span>
        </div>
        <div class="progress gold" style="margin-top:4px">
          <div :style="{ width: ftWinProgress(p.fasttrack) + '%' }" />
        </div>
      </template>

      <div class="muted" style="margin-top:6px" v-if="p.realEstates.length || p.businesses.length || p.stocks.length">
        资产：
        <span v-for="r in p.realEstates" :key="r.id">🏠{{ r.asset_type }} </span>
        <span v-for="b in p.businesses" :key="b.id">🏢{{ b.name }} </span>
        <span v-for="s in p.stocks" :key="s.symbol + s.cost_per_share">📈{{ s.symbol }}×{{ s.shares }} </span>
      </div>

      <!-- 卡片到此为止：这一页是读物，整卡可点 = 打开这个人的详情，一个手势一个意思。
           房主的「移除玩家」搬进了那张详情卡的底部（见下面的 BaseModal） -->
      <div class="muted" style="margin-top:6px;font-size:12px">📋 查看记录卡 ›</div>
    </div>

    <!-- 退出 / 结束：**危险画在闸门上，不画在入口上**（design/09 §7）。
         从前这里是一到两块整块红框卡 + 红实心按钮，而二次确认里那句「此操作不可撤销」
         本来就是红的——同一件事说了三遍，屏上最扎眼的颜色给了一局最多点一次的操作。
         入口退回一行安静的文字链：它不需要被找到得很快，只需要找得到。 -->
    <div class="quiet-links">
      <button v-if="!isHost" @click="leaveGame">退出对局</button>
      <button v-else @click="endGame">结束对局</button>
    </div>

    <BaseModal v-if="detailPlayer" :title="`${detailPlayer.nickname} 的记录卡`"
               :source="detailPlayer.professionTitle || '—'" dismissable
               @close="detailPlayer = null">
      <StatementTab :player="detailPlayer" />
      <template #actions>
        <button class="btn ghost grow" @click="detailPlayer = null">关闭</button>
        <!-- 移除某人是**针对这个人**的处置，上下文就是他的记录卡；
             而且它只有房主看得见、一局最多点一次，藏一层正合适 -->
        <button v-if="canRemove(detailPlayer)" class="btn ghost warn"
                @click="removePlayer(detailPlayer)">移除玩家</button>
      </template>
    </BaseModal>
  </div>
</template>
