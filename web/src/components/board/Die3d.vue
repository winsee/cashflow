<script setup lang="ts">
/** 一颗骰子（design/09 §3.4.2）。四态：可掷 / 摇动中 / 落定 / 还没掷。
 *
 *  **为什么是立方体而不是平面方块换数字**：跳变的数字**看着像结果**，而结果只能来自服务端，
 *  玩家会觉得刚才那个 4 是被改掉的。立方体天生没有这个问题——滚动中看见的是各个面掠过。
 *  这是 §4.2「客户端不预演」在视觉上的落实，不是它的例外。
 *
 *  **「还没掷」故意保留平面 `?`**：立方体总有一面朝前，而没有点数可显示时不该摆一颗
 *  看似有结果的骰子。这是两种呈现共存的**唯一**理由，别把它们「统一」掉。
 */
import { computed } from 'vue'
import { DIE_FACE, DIE_FACES, PIPS } from './dice'
import { prefersReducedMotion } from '../../stage'

const props = defineProps<{
  /** 服务端摇出的点数；null = 还没有结果 */
  value?: number | null
  rolling?: boolean
  /** 我此刻能不能掷（能掷才是主色实心的那一颗） */
  rollable?: boolean
  /** 第几粒（0-based）：多粒靠它错开相位，同步转会看成一个整体在晃 */
  index?: number
}>()
const emit = defineEmits<{ (e: 'roll'): void }>()

/** 降级：直接显示终值，不翻滚也不回弹（点数照样是服务端那个） */
const still = computed(() => prefersReducedMotion())

const i = computed(() => props.index ?? 0)
const flat = computed(() => !props.rolling && !props.value && !props.rollable)
const landed = computed(() => !props.rolling && !!props.value && !still.value)

/** 静止时的斜置：正对镜头的立方体看着就是个平面方块，点数那一面朝前、其余五面全被它挡住。
 *  先在**屏幕空间**里斜一点（写在点数旋转的左边，所以不影响哪一面朝前），
 *  顶面与侧面各露一条，加上 `.face` 的受光，它才像一颗放在桌上的骰子（第三轮试玩）。
 *
 *  **角度要小**：斜到 14°/16° 就成了摆拍，点数那一面明显歪着。10°/12° 配柔一档的透视，
 *  只露很薄的一条边——像正面拍的一颗真骰子，点数几乎不歪，仍看得出是立方体。
 *  `scale(.9)` 是找补：斜过去之后投影比正面那一面宽一些，不缩回来 3 粒骰在轮心里会压边。 */
const REST_TILT = 'rotateX(-10deg) rotateY(12deg) scale(.9)'

const cubeStyle = computed(() => {
  if (props.rolling) return undefined
  // 落定：转到那一面，各粒多转的圈数不同，免得几颗看着像一个整体
  if (props.value)
    return { transform: `${REST_TILT} ${DIE_FACE[props.value]} rotateZ(${360 * (1 + i.value)}deg)` }
  return { transform: `${REST_TILT} ${DIE_FACE[1]}` }        // 可掷：1 点朝前
})

/** 摇动：负 delay + 略不同的周期，让几粒各滚各的 */
const tumbleStyle = computed(() => ({
  animationDelay: `${-0.19 * i.value}s`,
  animationDuration: `${0.78 + 0.06 * i.value}s`,
}))
const tossStyle = computed(() => ({
  animationDelay: `${-0.11 * i.value}s`,
  animationDuration: `${0.52 + 0.04 * i.value}s`,
}))
</script>

<template>
  <!-- 还没掷（别人的回合）：平面骰 + 一个 `?`，不可点 -->
  <div v-if="flat" class="die">?</div>
  <button v-else class="die3d" :class="{ rollable, rolling, landed }"
          :disabled="!rollable" :style="rolling ? tossStyle : undefined"
          @click="emit('roll')">
    <span class="cube" :style="rolling ? tumbleStyle : cubeStyle">
      <span v-for="f in DIE_FACES" :key="f" class="face" :class="`f${f}`">
        <i v-for="(p, k) in PIPS[f]" :key="k" :style="{ gridArea: `${p[0]} / ${p[1]}` }"></i>
      </span>
    </span>
  </button>
</template>
