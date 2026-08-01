/** 牌堆的颜色与名称。颜色直接取自实体棋盘的格子，玩家低头看屏幕和抬头看棋盘不用换脑子。
 *  这套色**不参与阶段换肤** —— 桌上那张牌不会因为你换了赛道就变色。 */
export const DECK_LABEL: Record<string, string> = {
  SMALL_DEAL: '机会 · 小生意',
  BIG_DEAL: '机会 · 大买卖',
  MARKET: '市场风云',
  DOODAD: '额外支出',
  PROFESSION: '职业卡',
}

/** 简短标签，用于弹层右上角的来源色标 */
export const DECK_SHORT: Record<string, string> = {
  SMALL_DEAL: '小生意',
  BIG_DEAL: '大买卖',
  MARKET: '市场风云',
  DOODAD: '额外支出',
  PROFESSION: '职业卡',
}

export const DECK_COLOR: Record<string, string> = {
  SMALL_DEAL: '#8FBF3F',    // 内圈绿格
  BIG_DEAL: '#5E9E20',      // 同族加深
  MARKET: '#4FA8C8',        // 环线青蓝
  DOODAD: '#B07FC0',        // 藕粉格
  PROFESSION: '#4A443A',
}

/** 棋盘上不属于牌堆的两种格子色 */
export const COLOR_PAYDAY = '#E8913C'   // 银行结算日 · 慈善（橙格）
export const COLOR_FASTTRACK = '#6B3FA0' // 快车道外环紫罗兰
export const COLOR_DREAM = '#B07FC0'     // 快车道梦想粉格
