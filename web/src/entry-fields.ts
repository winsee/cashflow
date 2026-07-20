// 录入/核对共用的牌叠、子类型与字段模板（design/04 §3）
import type { CardDto } from './types'

export const DECKS: Record<string, string> = {
  SMALL_DEAL: '小生意', BIG_DEAL: '大买卖', MARKET: '市场风云',
  DOODAD: '额外支出', PROFESSION: '职业卡',
}

export const SUBTYPES: Record<string, string[]> = {
  SMALL_DEAL: ['REALESTATE', 'STOCK_OFFER', 'STOCK_EVENT', 'LOSS_EVENT'],
  BIG_DEAL: ['REALESTATE', 'BUSINESS', 'EXPENSE_EVENT'],
  MARKET: ['BUYER_OFFER', 'MULTIPLE_OFFER', 'ECONOMY_EVENT'],
  DOODAD: ['CASH', 'CREDIT_OPTION', 'INSTALLMENT'],
  PROFESSION: ['PROFESSION'],
}

export const SUBTYPE_NAMES: Record<string, string> = {
  REALESTATE: '房地产', STOCK_OFFER: '股票报价', STOCK_EVENT: '拆并股', LOSS_EVENT: '损失事件',
  BUSINESS: '企业投资', EXPENSE_EVENT: '维修支出', BUYER_OFFER: '定价求购',
  MULTIPLE_OFFER: '倍数收购', ECONOMY_EVENT: '经济事件', CASH: '现金支出',
  CREDIT_OPTION: '可信用卡', INSTALLMENT: '分期负债', PROFESSION: '职业',
}

// 字段模板：n=数字 s=文本。嵌套键：liabilities.* 与 priceRange.0/1
export const FIELDS: Record<string, [string, string, 'n' | 's'][]> = {
  REALESTATE: [['assetType', '资产类型(如 3室2厅 / 土地)', 's'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '抵押贷款', 'n'], ['cashflow', '月现金流', 'n'], ['roiPct', '收益率%', 'n'], ['priceRange.0', '价格区间低(选填)', 'n'], ['priceRange.1', '价格区间高(选填)', 'n']],
  BUSINESS: [['assetType', '资产类型', 's'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '负债', 'n'], ['cashflow', '月现金流', 'n']],
  STOCK_OFFER: [['symbol', '代码', 's'], ['price', '今日价格', 'n'], ['dividendPerShare', '每股红利', 'n'], ['priceRange.0', '价格区间低(选填)', 'n'], ['priceRange.1', '价格区间高(选填)', 'n']],
  STOCK_EVENT: [['symbol', '代码', 's'], ['ratio', '比例(如 2:1)', 's']],
  LOSS_EVENT: [['condition', '条件(hasRentalProperty/hasChildren/空)', 's'], ['amount', '金额', 'n']],
  EXPENSE_EVENT: [['targetAssetType', '目标资产类型', 's'], ['amountPerUnit', '每套金额', 'n']],
  BUYER_OFFER: [['targetAssetType', '目标资产类型', 's'], ['pricePerUnit', '每套价格', 'n']],
  MULTIPLE_OFFER: [['targetAssetType', '目标资产类型', 's'], ['multiple', '倍数', 'n']],
  ECONOMY_EVENT: [['kind', '类型(FORCED_SURRENDER)', 's'], ['targetAssetType', '目标资产类型', 's']],
  CASH: [['amount', '金额', 'n'], ['condition', '条件(hasChildren/空)', 's']],
  CREDIT_OPTION: [['amount', '金额', 'n'], ['creditMonthly', '信用卡月供', 'n']],
  INSTALLMENT: [['downPayment', '首付', 'n'], ['liability', '负债', 'n'], ['liabilityName', '负债名称', 's'], ['monthly', '月供', 'n']],
  PROFESSION: [['salary', '工资', 'n'], ['taxes', '税金', 'n'], ['mortgagePayment', '住房抵押支出', 'n'], ['schoolLoanPayment', '教育贷款支出', 'n'], ['carLoanPayment', '购车贷款支出', 'n'], ['creditCardPayment', '信用卡支出', 'n'], ['extraExpenses', '额外支出', 'n'], ['otherExpenses', '其他支出', 'n'], ['perChildExpense', '每孩支出', 'n'], ['savings', '储蓄', 'n'], ['liabilities.mortgage', '负债·住房抵押', 'n'], ['liabilities.schoolLoan', '负债·教育贷款', 'n'], ['liabilities.carLoan', '负债·购车贷款', 'n'], ['liabilities.creditCard', '负债·信用卡', 'n'], ['liabilities.extra', '负债·额外', 'n']],
}

// 按嵌套键读卡牌 data（liabilities.x / priceRange.0）
export function readField(data: Record<string, any>, key: string): any {
  if (key.includes('.')) {
    const [head, tail] = key.split('.')
    return data[head]?.[tail]
  }
  return data[key]
}

// 核对/清单展示用：一张卡的全部 [字段名, 值] 行（跳过未填的选填项）
export function fieldRows(card: CardDto): [string, string][] {
  const rows: [string, string][] = []
  for (const [key, label] of FIELDS[card.subtype] ?? []) {
    const v = readField(card.data, key)
    if (v === undefined || v === null || v === '') continue
    rows.push([label, typeof v === 'number' ? v.toLocaleString('en-US') : String(v)])
  }
  return rows
}
