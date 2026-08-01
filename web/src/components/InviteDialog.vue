<script setup lang="ts">
import { ref } from 'vue'
import QrCode from './QrCode.vue'
import BaseModal from './base/BaseModal.vue'
import { useGame } from '../store'
import { canWebShare, copyText, isLocalOrigin, isWeixin, shareInvite } from '../share'

const props = defineProps<{ code: string; url: string; nickname?: string }>()
const emit = defineEmits<{ close: [] }>()

const game = useGame()
const fallbackInput = ref<HTMLInputElement | null>(null)
const weixin = isWeixin()
const shareable = canWebShare()
const localOnly = isLocalOrigin()
const host = location.host   // 模板里拿不到全局 URL/location，先取好

async function share() {
  const r = await shareInvite({ url: props.url, code: props.code, nickname: props.nickname },
                              fallbackInput.value)
  if (r === 'copied') game.flash('已复制链接，去微信粘贴发送给朋友')
  else if (r === 'failed') game.lastError = '复制失败，请长按下方链接手动复制'
  // 'shared' 由系统面板自己给反馈，'cancelled' 是用户主动取消 —— 都不提示
}

async function copy() {
  if (await copyText(props.url, fallbackInput.value)) game.flash('链接已复制')
  else game.lastError = '复制失败，请长按下方链接手动复制'
}
</script>

<template>
  <BaseModal title="邀请朋友" source="扫码或输码都能进，不需要装应用" dismissable @close="emit('close')">
    <div class="invite">
      <div class="qr-wrap">
        <QrCode :text="url" :size="260" />
      </div>

      <div class="room-code">
        <span class="muted">房间码</span>
        <b>{{ code }}</b>
      </div>

      <p class="join-url">{{ url }}</p>

      <p v-if="localOnly" class="hint-warn">
        ⚠️ 当前是本机地址（{{ host }}），别人扫了打不开。
        请房主改用局域网 IP 或线上域名打开本页，再邀请。
      </p>
      <p v-else-if="weixin" class="hint">
        微信内打不开系统分享面板，请复制链接后粘贴发给朋友（或让他们直接扫上方二维码）。
      </p>

      <button v-if="shareable && !weixin" class="btn block" @click="share">📤 分享链接</button>

      <!-- 非安全上下文没有 clipboard API，execCommand 需要一个真实可选中的输入框 -->
      <input ref="fallbackInput" class="offscreen" readonly :value="url" tabindex="-1" aria-hidden="true" />
    </div>

    <template #actions>
      <button class="btn ghost grow" @click="copy">复制链接</button>
      <button class="btn ghost grow" @click="emit('close')">关闭</button>
    </template>
  </BaseModal>
</template>

<style scoped>
.invite { text-align: center; }
.qr-wrap {
  display: flex; justify-content: center;
  padding: 14px; margin: 4px 0 12px;
  background: #fff; border: 1px solid var(--line-2); border-radius: var(--r);
  box-shadow: var(--shadow-sm);
}
.room-code { display: flex; align-items: baseline; justify-content: center; gap: 10px; }
.room-code b { font-size: 30px; font-weight: 800; letter-spacing: 8px; padding-left: 8px; }
.join-url {
  margin: 8px 0 4px; font-size: 12px; color: var(--muted);
  word-break: break-all; user-select: all;
}
.hint, .hint-warn { font-size: 12px; margin: 8px 0; line-height: 1.5; }
.hint { color: var(--muted); }
.hint-warn { color: var(--red); }
.offscreen { position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }
</style>
