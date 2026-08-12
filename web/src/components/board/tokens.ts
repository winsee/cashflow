/** 快车道格子上的占位道具与图标（design/09 §3.7）。
 *
 *  实体游戏里：选定的梦想上放一块自己颜色的**奶酪**，买下的企业上放一枚自己颜色的**金币**。
 *  线上照这个来，一枚不多。
 *
 *  **形状先于颜色**——楔形是奶酪、双圈实心是金币；色盲玩家靠形状分道具、靠首字分人。
 *
 *  路径全部以 (0,0) 为中心、10 单位见方，调用方用 `<g transform="translate(x,y)">` 摆位置。
 *  写成常量而不是组件：它们要嵌进 `BoardView` 那只 `<svg>` 的 48 个 `<g>` 里，
 *  一格一个组件实例是 48 个多余的 Vue 组件。
 */

/** 奶酪 = 我选定的梦想（准备阶段就摆上去的那块，跟花钱无关） */
export const CHEESE =
  'M-5 2.4L3.4 -4.2A1.4 1.4 0 0 1 5 -3L5 2.4A1.6 1.6 0 0 1 3.4 4L-3.4 4A1.6 1.6 0 0 1 -5 2.4Z'

/** 奶酪上那三个孔 */
export const CHEESE_HOLES: ReadonlyArray<{ cx: number; cy: number; r: number }> = [
  { cx: 1.2, cy: 1.0, r: 1.05 },
  { cx: -2.1, cy: 2.2, r: 0.75 },
  { cx: 3.0, cy: -1.4, r: 0.6 },
]

/** 一次性收益型企业的金币上多的那道横杠：它跟别的企业的真实差别是
 *  **「有没有月现金流」，不是「有没有主人」**（`ft-b-software` / `ft-b-biotech`：
 *  买成功记进 `ft_sold_squares`，但 `cashflow` 为 0，不进 `businesses`）。 */
export const ONCE_BAR = 'M-6.6 0L-5 0M5 0L6.6 0'

/** 企业：一间店面（雨棚 + 门洞）。不用 emoji——各系统画得不一样，也没法用 currentColor 着色。 */
export const BIZ_ICON: ReadonlyArray<string> = [
  'M-5 -1.6L-3.6 -4.4L3.6 -4.4L5 -1.6Z',
  'M-4.2 -0.8L4.2 -0.8L4.2 4.4L-4.2 4.4Z',
]
export const BIZ_DOOR = { x: -1.3, y: 0.6, w: 2.6, h: 3.8 }

/** 梦想：一面旗。**不用星星**——星形在这套界面里已经是「重点 / 收藏」的语义。 */
export const DREAM_POLE = { x: -3.6, y: -4.6, w: 1.3, h: 9.2 }
export const DREAM_FLAG = 'M-2.3 -4.2L4.6 -1.8L-2.3 0.6Z'

/** 深度分层：一格只有 22.7 × 26 单位，外 5 单位归实心色条，剩下的分给图标与道具。
 *
 *  没有道具时图标居中；有道具时图标缩到 82% 并贴着色条，道具贴内边界，
 *  两者首尾相接、互不压字。**道具在内侧**——视线从盘心往外扫时先看到「这块地有主了」，
 *  那是比「这是什么格」更强的信号。 */
export const DEPTH = { glyph: -1, glyphWithToken: 2.5, token: -7, bump: 9 } as const
