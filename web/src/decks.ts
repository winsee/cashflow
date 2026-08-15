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
}

/** 棋盘上不属于牌堆的三种格子色 */
export const COLOR_PAYDAY = '#E8913C'   // 银行结算日 · 慈善（橙格）
export const COLOR_FASTTRACK = '#6B3FA0' // 快车道外环紫罗兰
export const COLOR_DREAM = '#B07FC0'     // 快车道梦想粉格

export const DECK_COLOR: Record<string, string> = {
  SMALL_DEAL: '#8FBF3F',    // 内圈绿格
  BIG_DEAL: '#5E9E20',      // 同族加深
  MARKET: '#4FA8C8',        // 环线青蓝
  DOODAD: '#B07FC0',        // 藕粉格
  PROFESSION: '#4A443A',
  // 快车道那两种格子卡（v0.23）。企业格与内圈绿格本来就同一个绿（`--deck-small`）；
  // 梦想格取上面那个 `COLOR_DREAM`，**不是**棋盘上的 `--deck-dream`（`#C9A8CE`）——
  // 后者是格子的**填充**色，浅到几乎和纸底一样，而这里要拿它当**墨色**用
  // （牌背的双线边框与宋体牌堆名都是 `currentColor`），浅填充色印上去等于没印。
  FT_BUSINESS: '#8FBF3F',
  FT_DREAM: COLOR_DREAM,
}
