import type { CardDto } from './types'

/** 卡面关键数值摘要（选卡列表与抽卡确认弹窗共用） */
export function keyNumbers(c: CardDto): string {
  const d = c.data
  const parts: string[] = []
  if (d.cost != null) parts.push(`成本 $${d.cost.toLocaleString()}`)
  if (d.downPayment != null) parts.push(`首付 $${d.downPayment.toLocaleString()}`)
  if (d.cashflow != null) parts.push(`现金流 +$${d.cashflow.toLocaleString()}`)
  if (d.price != null) parts.push(`今日价 $${d.price.toLocaleString()}`)
  if (d.amount != null) parts.push(`$${d.amount.toLocaleString()}`)
  if (d.monthly != null) parts.push(`月供 $${d.monthly.toLocaleString()}`)
  return parts.join(' · ')
}
