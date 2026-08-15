import { fmt as money, signed as signedMoney } from './money'
import type { CardDto } from './types'

const PRICE_BASIS_UNIT: Record<string, string> = {
  PER_UNIT: '/套',
  PER_ROOM: '/间房',
  PER_PIECE: '/枚',
}

const PAYER_CONDITION_LABEL: Record<string, string> = {
  hasChildren: '需有孩子',
  hasRentalProperty: '需持有出租房产',
  hasRealEstate: '需持有房地产',
}

/** 目标资产描述：targetRooms 存在时并入「N间房的X」，否则就是 targetAssetType/targetBusinessKind 本身 */
function targetLabel(d: Record<string, any>): string | null {
  const target = d.targetAssetType ?? d.targetBusinessKind
  if (target == null) return null
  return d.targetRooms != null ? `${d.targetRooms}间房的${target}` : target
}

/** 卡面关键数值摘要（选卡列表与抽卡确认弹窗共用）：按 subtype 覆盖 schema 里该分支的必要字段。
 *  title 统一等于卡面原文、不再靠括号消歧（2026-07-22 与房主定案），所以这里要把
 *  「资产类型/企业细分类型/目标资产/限定条件」这些原先只活在标题括号里的真实信息
 *  也覆盖到，否则会丢信息（纯氛围词如"低利率"不在此列，两张卡数值相同则视为等价）。*/
export function keyNumbers(c: CardDto): string {
  const d = c.data
  const parts: string[] = []

  switch (c.subtype) {
    case 'REALESTATE':
    case 'BUSINESS':
    case 'COLLECTIBLE':
    case 'DICE_GAMBLE':
      if (d.assetType != null) parts.push(d.assetType)
      if (d.businessKind != null) parts.push(d.businessKind)
      if (d.rooms != null) parts.push(`${d.rooms}间房`)
      if (d.units != null) parts.push(`${d.units}套`)
      if (d.quantity != null) parts.push(`${d.quantity}件`)
      if (d.cost != null) parts.push(`成本 ${money(d.cost)}`)
      if (d.downPayment != null) parts.push(`首付 ${money(d.downPayment)}`)
      if (d.mortgage != null) parts.push(`抵押贷款 ${money(d.mortgage)}`)
      if (d.cashflow != null) parts.push(`现金流 ${signedMoney(d.cashflow)}`)
      if (d.diceCount != null) parts.push(`掷${d.diceCount}粒骰子`)
      if (d.winCondition != null) parts.push(`${d.winCondition}中奖`)
      if (d.payout != null) parts.push(`奖金 ${money(d.payout)}`)
      break

    case 'STOCK_OFFER':
      if (d.price != null) parts.push(`今日价 ${money(d.price)}`)
      if (d.dividendPerShare) parts.push(`每股分红 ${money(d.dividendPerShare)}`)
      if (d.roiPct != null) parts.push(`投资收益率 ${d.roiPct}%`)
      break

    case 'STOCK_EVENT':
      if (d.ratio != null) parts.push(`比例 ${d.ratio}`)
      break

    case 'BUYER_OFFER': {
      const target = targetLabel(d)
      if (target != null) parts.push(target)
      const unit = d.priceBasis ? PRICE_BASIS_UNIT[d.priceBasis] ?? '' : ''
      if (d.price != null) parts.push(`求购价 ${money(d.price)}${unit}`)
      if (d.minUnits != null) parts.push(`至少${d.minUnits}套`)
      break
    }

    case 'MULTIPLE_OFFER': {
      const target = targetLabel(d)
      if (target != null) parts.push(target)
      if (d.multiple != null) parts.push(`按现金流 ${d.multiple} 倍成交`)
      break
    }

    case 'PREMIUM_OFFER': {
      const target = targetLabel(d)
      if (target != null) parts.push(`目标：${target}`)
      if (d.premiumOverCost != null) parts.push(`原价 + ${money(d.premiumOverCost)}`)
      break
    }

    case 'INSTALLMENT_SALE': {
      const target = targetLabel(d)
      if (target != null) parts.push(target)
      if (d.totalPrice != null) parts.push(`总价 ${money(d.totalPrice)}`)
      if (d.downPayment != null) parts.push(`首付 ${money(d.downPayment)}`)
      if (d.monthlyCashflowDelta != null) parts.push(`月现金流 ${signedMoney(d.monthlyCashflowDelta)}`)
      if (d.durationMonths != null) parts.push(`分${d.durationMonths}个月收清`)
      break
    }

    case 'CASHFLOW_MODIFIER': {
      const target = targetLabel(d)
      if (target != null) parts.push(`目标：${target}`)
      if (d.cashflowDelta != null) parts.push(`现金流 ${signedMoney(d.cashflowDelta)}`)
      break
    }

    case 'EXPENSE_EVENT':
    case 'CASH': {
      const target = targetLabel(d)
      if (target != null) parts.push(`目标：${target}`)
      if (d.amount != null) parts.push(money(d.amount))
      if (d.amountPerUnit != null) parts.push(`${money(d.amountPerUnit)}/套`)
      if (d.amountPerChild != null) parts.push(`${money(d.amountPerChild)}/孩`)
      if (d.chargeOnce) parts.push('限收一次')
      if (d.payerCondition != null) parts.push(PAYER_CONDITION_LABEL[d.payerCondition] ?? d.payerCondition)
      break
    }

    case 'CREDIT_OPTION':
      if (d.amount != null) parts.push(`额度 ${money(d.amount)}`)
      if (d.creditMonthly != null) parts.push(`月供 ${money(d.creditMonthly)}`)
      break

    case 'INSTALLMENT':
      if (d.downPayment != null) parts.push(`首付 ${money(d.downPayment)}`)
      if (d.liabilityName != null) parts.push(`${d.liabilityName} ${money(d.liability ?? 0)}`)
      if (d.monthly != null) parts.push(`月供 ${money(d.monthly)}`)
      break

    case 'ECONOMY_EVENT': {
      const target = targetLabel(d)
      if (target != null) parts.push(`目标：${target}`)
      parts.push(d.kind === 'FORCED_SURRENDER' ? '强制没收资产' : '修改支出')
      break
    }

    default:
      if (d.cost != null) parts.push(`成本 ${money(d.cost)}`)
      if (d.downPayment != null) parts.push(`首付 ${money(d.downPayment)}`)
      if (d.mortgage != null) parts.push(`抵押贷款 ${money(d.mortgage)}`)
      if (d.cashflow != null) parts.push(`现金流 ${signedMoney(d.cashflow)}`)
      if (d.price != null) parts.push(`今日价 ${money(d.price)}`)
      if (d.amount != null) parts.push(money(d.amount))
      if (d.monthly != null) parts.push(`月供 ${money(d.monthly)}`)
  }

  return parts.join(' · ')
}
