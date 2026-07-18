<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { fmt, useGame } from '../store'
import type { LogEntry } from '../types'

const game = useGame()
const rows = ref<LogEntry[]>([])
const filter = ref('')

const LABELS: Record<string, string> = {
  PLAYER_JOINED: '加入房间', PROFESSION_SELECTED: '选择职业', DREAM_SELECTED: '选择梦想',
  TURN_ORDER_SET: '排定顺序', GAME_STARTED: '开局发钱', TURN_ENDED: '结束回合',
  PAYDAY: '银行结算日', CARD_DRAWN: '抽卡', CARD_PASSED: '放弃卡牌', CARD_RESOLVED: '卡牌结算完毕',
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
  FT_CASH_HIT: '现金损失', HOST_REVERTED: '房主撤销', HOST_ADJUSTED: '房主调账',
}

function amountOf(e: LogEntry): string {
  const p = e.payload
  for (const k of ['amount', 'cashflow', 'down_payment', 'price', 'proceeds', 'cost', 'net', 'delta', 'price_paid', 'fee'])
    if (typeof p[k] === 'number') return fmt(p[k])
  if (p.grants) return Object.values(p.grants as Record<string, number>).map(v => fmt(v)).join(' / ')
  return ''
}

function detailOf(e: LogEntry): string {
  const p = e.payload
  return p.title ?? p.name ?? p.symbol ?? p.reason ?? p.liability_name ?? ''
}

async function refresh() { rows.value = (await game.fetchLog()).reverse() }
onMounted(refresh)
watch(() => game.seq, refresh)
</script>

<template>
  <div>
    <input v-model="filter" placeholder="按玩家昵称过滤" style="margin-bottom:8px" />
    <div v-for="e in rows.filter(r => !filter || (r.actor ?? '').includes(filter))" :key="e.seq"
         class="card" :style="e.revoked ? 'opacity:0.45;text-decoration:line-through' : ''" >
      <div class="row between">
        <div>
          <b>{{ LABELS[e.type] ?? e.type }}</b>
          <span class="muted"> · {{ e.actor ?? '系统' }}</span>
          <span class="muted" v-if="detailOf(e)"> · {{ detailOf(e) }}</span>
        </div>
        <div class="num">{{ amountOf(e) }}</div>
      </div>
      <div class="muted">#{{ e.seq }} · {{ e.at }}<span v-if="e.revoked">（已撤销）</span></div>
    </div>
  </div>
</template>
