/** 牌堆的颜色与名称。颜色直接取自实体棋盘的格子，玩家低头看屏幕和抬头看棋盘不用换脑子。
 *  这套色**不参与阶段换肤** —— 桌上那张牌不会因为你换了赛道就变色。 */
export const DECK_LABEL: Record<string, string> = {
  SMALL_DEAL: '机会 · 小生意',
  BIG_DEAL: '机会 · 大买卖',
  MARKET: '市场风云',
  DOODAD: '额外支出',
  PROFESSION: '职业卡',
  // 快车道的两种格子卡（design/09 §5.3 v0.23）。它们不是牌堆，但走同一段揭示帘幕，
  // 所以色与名也在这儿一处定义。键名直接用 `landing.type`，不另起一套命名。
  FT_BUSINESS: '快车道 · 企业投资',
  FT_DREAM: '快车道 · 梦想',
}

/** 简短标签，用于弹层右上角的来源色标 */
export const DECK_SHORT: Record<string, string> = {
  SMALL_DEAL: '小生意',
  BIG_DEAL: '大买卖',
  MARKET: '市场风云',
  DOODAD: '额外支出',
  PROFESSION: '职业卡',
  FT_BUSINESS: '企业投资',
  FT_DREAM: '梦想',
}

export const DECK_COLOR: Record<string, string> = {
  SMALL_DEAL: '#8FBF3F',    // 内圈绿格
  BIG_DEAL: '#5E9E20',      // 同族加深
  MARKET: '#4FA8C8',        // 环线青蓝
  DOODAD: '#B07FC0',        // 藕粉格
  PROFESSION: '#4A443A',
  // 与棋盘上那两格逐字同色（BoardView 的 TYPE_COLOR 用的是 --deck-small / --deck-dream）：
  // 牌背从哪一格飞出来，帘幕就是那一格的颜色
  FT_BUSINESS: '#8FBF3F',   // 快车道绿格（企业投资）
  FT_DREAM: '#C9A8CE',      // 快车道粉格（梦想）
}

/** 棋盘上不属于牌堆的两种格子色 */
export const COLOR_PAYDAY = '#E8913C'   // 银行结算日 · 慈善（橙格）
export const COLOR_FASTTRACK = '#6B3FA0' // 快车道外环紫罗兰
export const COLOR_DREAM = '#B07FC0'     // 快车道梦想粉格
