/** 金额成文的唯一一处主人。
 *
 *  单独成模块而不是塞进 `store.ts`，是因为 `store.ts` 已经 import 了 `receipts.ts`，
 *  而 `receipts.ts` 也要用这几个函数——放在 store 里就成环了。
 *  `store.ts` 把这三个再导出一遍，所以既有的 `import { fmt } from './store'` 一行都不用改。
 *
 *  通则（2026-08-15，两处 `+$-100` 换来的）：
 *  **一个数可能为负，就不许在模板里替它写死符号和颜色**，交给 `signed()` + `toneOf()`。
 *  从前 `signed()` 在 `PaydayCurtain`/`PenaltyCurtain`/`OnlineLandingPanel`/`receipts.ts`/
 *  `cardinfo.ts` 各写了一遍逐字相同的实现——没有一处主人，于是新写的地方就自己拼一个 `+`
 *  出来，碰上负现金流的房产（`sd-045`/`sd-051`/`bd-008`/`bd-041`）就成了 `+$-100`。
 */

/** 金额成文。**负号在 `$` 外面**（`-$100`，不是 `$-100`）——负号是这个数的一部分，
 *  货币符号是单位，把单位插进数里读起来就不是一个数了。 */
export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return '0'
  return (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US')
}

/** 带正负号的金额（`+$100` / `−$100`）。
 *  出的是 U+2212 减号，与 `+` 同宽，数字列才对得齐。 */
export function signed(n: number | undefined | null): string {
  const v = n ?? 0
  return (v >= 0 ? '+' : '−') + fmt(Math.abs(v))
}

/** 与 `signed()` 配套的语义色类名（正绿负红，不参与阶段换肤）。 */
export function toneOf(n: number | undefined | null): 'pos' | 'neg' {
  return (n ?? 0) >= 0 ? 'pos' : 'neg'
}
