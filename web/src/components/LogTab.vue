<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { confirmAction } from '../confirm'
import { COLOR_DREAM, COLOR_FASTTRACK, COLOR_PAYDAY, DECK_COLOR } from '../decks'
import { fmt, useGame } from '../store'
import type { LogEntry } from '../types'

const game = useGame()
const rows = ref<LogEntry[]>([])
const filter = ref('')
const isHost = computed(() => game.me?.isHost ?? false)

// 大厅/系统性事件撤销会破坏对局结构，不提供入口；其余交给服务端重放校验兜底
const NO_REVERT = new Set(['PLAYER_JOINED', 'TURN_ORDER_SET', 'GAME_STARTED', 'HOST_REVERTED', 'PLAYER_CORRECTED', 'GAME_ENDED'])

// FR-29 本人更正：卡牌入账类事件本人可自行撤销后重新选卡（与服务端 CORRECTABLE_TYPES 一致）
const CORRECTABLE = new Set([
  'CARD_DRAWN', 'CARD_RESOLVED', 'CARD_PASSED',
  'ASSET_BOUGHT', 'DOODAD_PAID', 'INSTALLMENT_ADDED',
  'LOSS_PAID', 'EXPENSE_EVENT_PAID',
  'STOCK_BOUGHT', 'STOCK_SOLD', 'SHARES_ADJUSTED',
  'MARKET_SOLD', 'MARKET_DECLINED',
])

function revertable(e: LogEntry): boolean {
  return isHost.value && !e.revoked && !NO_REVERT.has(e.type)
}

/** 语义是「抽错卡当场撤销重选」（设计稿 §04）：回合一结束就只能请房主撤销，
 *  否则谁都能回头翻旧账。服务端 _revert 有同一道校验，这里只是不给按钮。 */
function correctable(e: LogEntry): boolean {
  return !isHost.value && !e.revoked && CORRECTABLE.has(e.type)
      && e.actorId === game.session?.playerId && game.isMyTurn
}

const LABELS: Record<string, string> = {
  PLAYER_JOINED: '加入房间', PROFESSION_SELECTED: '选择职业', DREAM_SELECTED: '选择梦想',
  TURN_ORDER_SET: '排定顺序', GAME_STARTED: '开局发钱', TURN_ENDED: '结束回合',
  PAYDAY: '银行结算日', PAYDAY_UNPAYABLE: '结算日无力支付', CARD_DRAWN: '抽卡',
  CARD_PASSED: '放弃卡牌', CARD_RESOLVED: '卡牌结算完毕',
  ASSET_BOUGHT: '买入资产', RESELL_OFFERED: '发起转卖', RESELL_CONFIRMED: '确认转卖', RESELL_REJECTED: '拒绝转卖',
  STOCK_BOUGHT: '买入股票', STOCK_SOLD: '卖出股票', SHARES_ADJUSTED: '拆并股',
  LOSS_PAID: '损失支出', EXPENSE_EVENT_PAID: '维修支出', DOODAD_PAID: '额外支出', INSTALLMENT_ADDED: '分期购买',
  MARKET_PROMPTED: '市场求购', MARKET_SOLD: '市场卖出', MARKET_DECLINED: '放弃出售', ASSETS_SURRENDERED: '资产被收回',
  LOAN_TAKEN: '银行贷款', LOAN_REPAID: '偿还贷款', DEBT_PAID_OFF: '清偿负债',
  CHILD_ADDED: '生孩子', CHILD_NOOP: '孩子已满3个', CHARITY_DONATED: '慈善捐款', UNEMPLOYMENT_HIT: '失业',
  TRANSFER_REQUESTED: '发起转账', TRANSFER_COMPLETED: '转账完成', TRANSFER_REJECTED: '拒绝转账',
  BANKRUPTCY_STARTED: '进入破产', BANKRUPTCY_ASSET_SOLD: '破产变卖', BANKRUPTCY_RESOLVED: '破产清算完成',
  ENTERED_FASTTRACK: '进入快车道', FT_PAYDAY: '现金流量日', FT_BUSINESS_BOUGHT: '快车道投资',
  FT_DREAM_BOUGHT: '买下梦想', FT_DREAM_DOUBLED: '梦想加价', FT_CHARITY_DONATED: '快车道慈善',
  FT_CASH_HIT: '现金损失', HOST_REVERTED: '房主撤销', PLAYER_CORRECTED: '本人更正', HOST_ADJUSTED: '房主调账',
  GAME_ENDED: '结束对局', PLAYER_REMOVED: '移除玩家', PLAYER_LEFT: '玩家退出',
}

/** 事件点用牌堆色：抬头看棋盘、低头看日志，同一套颜色编码。
 *  取不到牌堆归属的（转账、贷款、房主操作）用中性灰。 */
const DOT: Record<string, string> = {
  CARD_DRAWN: DECK_COLOR.SMALL_DEAL, CARD_PASSED: DECK_COLOR.SMALL_DEAL,
  CARD_RESOLVED: DECK_COLOR.SMALL_DEAL, ASSET_BOUGHT: DECK_COLOR.BIG_DEAL,
  RESELL_OFFERED: DECK_COLOR.BIG_DEAL, RESELL_CONFIRMED: DECK_COLOR.BIG_DEAL,
  RESELL_REJECTED: DECK_COLOR.BIG_DEAL,
  STOCK_BOUGHT: DECK_COLOR.SMALL_DEAL, STOCK_SOLD: DECK_COLOR.SMALL_DEAL,
  SHARES_ADJUSTED: DECK_COLOR.MARKET,
  MARKET_PROMPTED: DECK_COLOR.MARKET, MARKET_SOLD: DECK_COLOR.MARKET,
  MARKET_DECLINED: DECK_COLOR.MARKET, ASSETS_SURRENDERED: DECK_COLOR.MARKET,
  LOSS_PAID: DECK_COLOR.DOODAD, EXPENSE_EVENT_PAID: DECK_COLOR.DOODAD,
  DOODAD_PAID: DECK_COLOR.DOODAD, INSTALLMENT_ADDED: DECK_COLOR.DOODAD,
  PAYDAY: COLOR_PAYDAY, PAYDAY_UNPAYABLE: COLOR_PAYDAY,
  CHARITY_DONATED: COLOR_PAYDAY, FT_CHARITY_DONATED: COLOR_PAYDAY,
  FT_PAYDAY: COLOR_PAYDAY, GAME_STARTED: COLOR_PAYDAY,
  ENTERED_FASTTRACK: COLOR_FASTTRACK, FT_BUSINESS_BOUGHT: COLOR_FASTTRACK,
  FT_DREAM_BOUGHT: COLOR_DREAM, FT_DREAM_DOUBLED: COLOR_DREAM,
  FT_CASH_HIT: 'var(--red)', BANKRUPTCY_STARTED: 'var(--red)',
  BANKRUPTCY_ASSET_SOLD: 'var(--red)', BANKRUPTCY_RESOLVED: 'var(--red)',
  UNEMPLOYMENT_HIT: 'var(--red)',
}
const dotOf = (e: LogEntry) => DOT[e.type] ?? 'var(--muted)'

function amountOf(e: LogEntry): string {
  const p = e.payload
  for (const k of ['amount', 'cashflow', 'down_payment', 'price', 'proceeds', 'cost', 'net', 'delta', 'price_paid', 'fee'])
    if (typeof p[k] === 'number') return fmt(p[k])
  if (p.grants) return Object.values(p.grants as Record<string, number>).map(v => fmt(v)).join(' / ')
  return ''
}

function detailOf(e: LogEntry): string {
  const p = e.payload
  const base = p.title ?? p.name ?? p.symbol ?? p.reason ?? p.liability_name ?? ''
  if (!p.note) return base
  return base ? `${base}（${p.note}）` : p.note   // 如「参加婚礼（无孩子，无需支付）」
}

/** 撤销不占一行：它已经画在被撤销那条上了（划线 +「已被房主撤销」，设计稿 §11）。
 *  这两类审计事件仍在事件流与 /log 接口里，账本的可审计性不受影响。 */
const AUDIT_ONLY = new Set(['HOST_REVERTED', 'PLAYER_CORRECTED'])

/** 被撤销行的副标题：谁撤的、怎么撤的 */
function revokedNote(e: LogEntry): string {
  if (!e.revoked) return ''
  const who = e.revokedByActor ?? ''
  if (e.revokedBy === 'self') return who ? `已被 ${who} 本人更正` : '已被本人更正'
  if (e.revokedBy === 'host') return who ? `已被房主 ${who} 撤销` : '已被房主撤销'
  return '已撤销'
}

/** 按轮分组：行是 seq 倒序、轮次随 seq 单调，所以相邻同轮的合成一组即可。
 *  轮次由服务端重放给出（rooms.log_rows），前端不反推。 */
const groups = computed(() => {
  const out: { turn: number; items: LogEntry[] }[] = []
  for (const e of rows.value) {
    if (AUDIT_ONLY.has(e.type)) continue
    if (filter.value && !(e.actor ?? '').includes(filter.value)) continue
    const last = out[out.length - 1]
    if (last && last.turn === e.turn) last.items.push(e)
    else out.push({ turn: e.turn, items: [e] })
  }
  return out
})

async function refresh() { rows.value = (await game.fetchLog()).reverse() }
onMounted(refresh)
watch(() => game.seq, refresh)

async function revert(e: LogEntry) {
  const ok = await confirmAction({
    title: `撤销 #${e.seq}「${LABELS[e.type] ?? e.type}」？`,
    lines: [`${e.actor ?? '系统'}${detailOf(e) ? ' · ' + detailOf(e) : ''}${amountOf(e) ? ' · ' + amountOf(e) : ''}`,
            '撤销后全员账目立即重算，记录保留划线痕迹',
            '若有后续操作依赖此事件，需先撤销那些操作'],
    danger: true,
  })
  if (ok && await game.act('HOST_REVERT', { eventSeq: e.seq, reason: '房主修正' })) {
    game.flash(`已撤销 #${e.seq}`)
    await refresh()
  }
}

async function correct(e: LogEntry) {
  const ok = await confirmAction({
    title: `更正 #${e.seq}「${LABELS[e.type] ?? e.type}」？`,
    lines: [`${detailOf(e) ? detailOf(e) + ' · ' : ''}${amountOf(e)}`,
            '选错卡时用：撤销这笔入账后，重新抽卡选对的卡',
            '全员账目立即重算，记录保留划线痕迹'],
    danger: true,
  })
  if (ok && await game.act('PLAYER_CORRECT', { eventSeq: e.seq, reason: '选错卡更正' })) {
    game.flash(`已更正 #${e.seq}，请重新选卡入账`)
    await refresh()
  }
}
</script>

<template>
  <div>
    <input v-model="filter" placeholder="按玩家昵称过滤" style="margin-bottom:8px" />
    <p class="muted" style="margin:0 2px 10px">
      这是可审计的账本：被撤销的条目保留划线痕迹，不会悄悄删掉。
    </p>
    <!-- 按轮分组的时间轴：事件点用牌堆色，一眼看出这笔账来自哪种格子 -->
    <template v-for="g in groups" :key="g.turn">
    <div class="section-title" style="margin-top:14px">{{ g.turn ? `第 ${g.turn} 轮` : '开局前' }}</div>
    <div class="logline">
      <div v-for="e in g.items" :key="e.seq"
           class="logitem" :class="{ revoked: e.revoked }">
        <span class="logdot" :style="{ background: dotOf(e) }"></span>
        <div class="row between">
          <div class="grow">
            <b>{{ LABELS[e.type] ?? e.type }}</b>
            <span class="muted"> · {{ e.actor ?? '系统' }}</span>
            <span class="muted" v-if="detailOf(e)"> · {{ detailOf(e) }}</span>
          </div>
          <div class="num">{{ amountOf(e) }}</div>
        </div>
        <div v-if="e.revoked" class="muted">{{ revokedNote(e) }}</div>
        <div class="row between">
          <div class="muted">#{{ e.seq }} · {{ e.at }}</div>
          <button v-if="revertable(e)" class="btn small ghost" @click="revert(e)">撤销</button>
          <button v-else-if="correctable(e)" class="btn small ghost" @click="correct(e)">更正</button>
        </div>
      </div>
    </div>
    </template>
    <p v-if="!rows.length" class="muted">还没有任何记录。</p>
  </div>
</template>

<style scoped>
.logline { border-left: 2px solid var(--line-2); padding-left: 14px; display: flex; flex-direction: column; gap: 14px; }
.logitem { position: relative; }
.logdot { position: absolute; left: -19px; top: 6px; width: 8px; height: 8px; border-radius: 50%; }
/* 被撤销的只给标题划线：金额与时间仍要看得清，账本不能糊 */
.logitem.revoked { opacity: .45; }
.logitem.revoked b { text-decoration: line-through; }
</style>
