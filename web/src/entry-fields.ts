// 录入/核对共用的牌叠、子类型与字段模板（design/04 §3）
import type { CardDto } from './types'

export const DECKS: Record<string, string> = {
  SMALL_DEAL: '小生意', BIG_DEAL: '大买卖', MARKET: '市场风云',
  DOODAD: '额外支出', PROFESSION: '职业卡',
}

// v3：17 个 subtype（LOSS_EVENT 已并入 EXPENSE_EVENT，另新增 5 个，design/06 §3.1）
export const SUBTYPES: Record<string, string[]> = {
  SMALL_DEAL: ['REALESTATE', 'BUSINESS', 'COLLECTIBLE', 'DICE_GAMBLE', 'STOCK_OFFER', 'STOCK_EVENT', 'EXPENSE_EVENT'],
  BIG_DEAL: ['REALESTATE', 'BUSINESS', 'EXPENSE_EVENT'],
  MARKET: ['BUYER_OFFER', 'MULTIPLE_OFFER', 'PREMIUM_OFFER', 'INSTALLMENT_SALE', 'CASHFLOW_MODIFIER', 'ECONOMY_EVENT'],
  DOODAD: ['CASH', 'CREDIT_OPTION', 'INSTALLMENT'],
  PROFESSION: ['PROFESSION'],
}

export const SUBTYPE_NAMES: Record<string, string> = {
  REALESTATE: '房地产', STOCK_OFFER: '股票报价', STOCK_EVENT: '拆并股',
  BUSINESS: '企业投资', COLLECTIBLE: '收藏品', DICE_GAMBLE: '骰子赌局',
  EXPENSE_EVENT: '强制支出', BUYER_OFFER: '定价求购',
  MULTIPLE_OFFER: '倍数收购', PREMIUM_OFFER: '溢价收购',
  INSTALLMENT_SALE: '分期收款', CASHFLOW_MODIFIER: '现金流调整',
  ECONOMY_EVENT: '经济事件', CASH: '现金支出',
  CREDIT_OPTION: '可信用卡', INSTALLMENT: '分期负债', PROFESSION: '职业',
}

// 字段模板：n=数字 s=文本。嵌套键：liabilities.* 与 priceRange.0/1
export const FIELDS: Record<string, [string, string, 'n' | 's'][]> = {
  REALESTATE: [['assetType', '资产类型(如 3室2厅 / 公寓)', 's'], ['rooms', '房间数(公寓 2/4/8，选填)', 'n'], ['units', '套数(公寓楼 12/24/60，选填)', 'n'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '抵押贷款', 'n'], ['cashflow', '月现金流(可为负)', 'n'], ['incomeCategory', '收入栏(REAL_ESTATE)', 's'], ['roiPct', '收益率%', 'n'], ['priceRange.0', '价格区间低(选填)', 'n'], ['priceRange.1', '价格区间高(选填)', 'n']],
  BUSINESS: [['assetType', '资产类型', 's'], ['businessKind', '企业细分类型(选填)', 's'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '负债', 'n'], ['cashflow', '月现金流(可为负)', 'n'], ['incomeCategory', '收入栏(BUSINESS)', 's']],
  COLLECTIBLE: [['assetType', '资产类型(如 克鲁格金币)', 's'], ['quantity', '件数/枚数', 'n'], ['cost', '成本', 'n'], ['downPayment', '首期支付', 'n'], ['mortgage', '抵押贷款', 'n'], ['cashflow', '月现金流', 'n']],
  DICE_GAMBLE: [['cost', '成本', 'n'], ['downPayment', '投入金额', 'n'], ['mortgage', '抵押贷款', 'n'], ['cashflow', '月现金流', 'n'], ['diceCount', '骰子数', 'n'], ['winCondition', '获胜条件(如 >3)', 's'], ['payout', '赔付金额', 'n']],
  STOCK_OFFER: [['symbol', '代码', 's'], ['price', '今日价格', 'n'], ['dividendPerShare', '每股红利', 'n'], ['incomeCategory', '收入栏(DIVIDEND/INTEREST)', 's'], ['buyerScope', '买家范围(DRAWER_ONLY/ALL)', 's'], ['roiPct', '收益率%', 'n'], ['priceRange.0', '价格区间低(选填)', 'n'], ['priceRange.1', '价格区间高(选填)', 'n']],
  STOCK_EVENT: [['symbol', '代码', 's'], ['ratio', '比例(如 2:1)', 's']],
  EXPENSE_EVENT: [['payerCondition', '玩家条件(hasChildren/hasRentalProperty/hasRealEstate/空)', 's'], ['targetAssetType', '目标资产类型', 's'], ['targetRooms', '限定房间数(选填)', 'n'], ['amount', '固定金额', 'n'], ['amountPerUnit', '每套金额', 'n'], ['chargeOnce', '只付一套(true/空)', 's'], ['appliesTo', '波及范围(DRAWER_ONLY/ALL)', 's']],
  BUYER_OFFER: [['targetAssetType', '目标资产类型', 's'], ['targetBusinessKind', '目标企业类型(选填)', 's'], ['priceBasis', '计价基准(PER_UNIT/PER_ROOM/PER_PIECE)', 's'], ['price', '单价', 'n'], ['minUnits', '套数门槛(选填)', 'n'], ['assetCondition', '资产条件(cashflowPositive/空)', 's']],
  MULTIPLE_OFFER: [['targetAssetType', '目标资产类型', 's'], ['multiple', '倍数', 'n']],
  PREMIUM_OFFER: [['targetAssetType', '目标资产类型', 's'], ['premiumOverCost', '高于原价的溢价', 'n']],
  INSTALLMENT_SALE: [['targetAssetType', '目标资产类型', 's'], ['totalPrice', '总价', 'n'], ['downPayment', '首付', 'n'], ['monthlyCashflowDelta', '月现金流变化(负数)', 'n'], ['durationMonths', '期数(月)', 'n'], ['onCompletion', '期满处理', 's']],
  CASHFLOW_MODIFIER: [['targetAssetType', '目标资产类型', 's'], ['cashflowDelta', '月现金流增减', 'n'], ['appliesTo', '波及范围(DRAWER_ONLY/ALL)', 's']],
  ECONOMY_EVENT: [['kind', '类型(FORCED_SURRENDER/MODIFY_EXPENSE)', 's'], ['targetAssetType', '目标资产类型', 's']],
  CASH: [['amount', '金额', 'n'], ['amountPerChild', '每孩金额(选填)', 'n'], ['payerCondition', '玩家条件(hasChildren/空)', 's']],
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
