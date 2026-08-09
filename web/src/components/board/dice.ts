/** 骰子的两张表（design/09 §3.4.2）——**一处写死**，别在别处再算一遍。 */

/** 「把点数 n 转到正面」需要的 cube 旋转。
 *
 *  六个面照实物排布，**对面之和为 7**：1 前 / 6 后、2 右 / 5 左、3 上 / 4 下
 *  （面本身的朝向见 style.css 的 `.f1`–`.f6`）。这里是它的逆：把那一面转到镜头前。
 */
export const DIE_FACE: Record<number, string> = {
  1: 'rotateX(0deg) rotateY(0deg)',
  2: 'rotateY(-90deg)',
  3: 'rotateX(-90deg)',
  4: 'rotateX(90deg)',
  5: 'rotateY(90deg)',
  6: 'rotateY(180deg)',
}

export const DIE_FACES = [1, 2, 3, 4, 5, 6]

/** 每一面的点子在 3×3 网格里的位置（[行, 列]，均为 1-based） */
export const PIPS: Record<number, [number, number][]> = {
  1: [[2, 2]],
  2: [[1, 1], [3, 3]],
  3: [[1, 1], [2, 2], [3, 3]],
  4: [[1, 1], [1, 3], [3, 1], [3, 3]],
  5: [[1, 1], [1, 3], [2, 2], [3, 1], [3, 3]],
  6: [[1, 1], [1, 3], [2, 1], [2, 3], [3, 1], [3, 3]],
}
