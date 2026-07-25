// 复制链接 / 调起系统分享面板。
// 两个环境限制决定了这里的降级链：
//   1. navigator.share 与 navigator.clipboard 都只在安全上下文（HTTPS / localhost）存在，
//      局域网 http://192.168.x.x 部署下两者皆为 undefined，得靠 execCommand 与二维码兜底；
//   2. 微信内置浏览器不支持 Web Share API（其 JS-SDK 分享要公众号认证 + 域名备案，本项目不做），
//      所以在微信里只能引导「复制链接后粘贴」。

/** 剪贴板复制：navigator.clipboard → 隐藏 input + execCommand 两级兜底 */
export async function copyText(text: string, fallbackEl?: HTMLInputElement | null): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 落到 execCommand */ }
  if (fallbackEl) {
    try {
      fallbackEl.value = text
      fallbackEl.select()
      fallbackEl.setSelectionRange(0, text.length)
      return document.execCommand('copy')
    } catch { /* 两条路都断了 */ }
  }
  return false
}

/** 当前环境能否调起系统分享面板 */
export function canWebShare(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}

/** 是否在微信内置浏览器里 */
export function isWeixin(): boolean {
  return /micromessenger/i.test(navigator.userAgent)
}

export type ShareResult = 'shared' | 'cancelled' | 'copied' | 'failed'

/**
 * 邀请好友：优先调起系统分享面板（面板里可选微信/QQ 等），不行就退回复制链接。
 * 'cancelled' = 用户在面板里点了取消，调用方不要提示失败。
 */
export async function shareInvite(
  opts: { url: string; code: string; nickname?: string },
  fallbackEl?: HTMLInputElement | null,
): Promise<ShareResult> {
  const who = opts.nickname?.trim()
  const text = `${who ? who + ' ' : ''}邀你玩现金流，房间码 ${opts.code}`
  if (canWebShare()) {
    try {
      await navigator.share({ title: '现金流对局', text, url: opts.url })
      return 'shared'
    } catch (e: any) {
      // 用户主动取消分享，不是错误
      if (e?.name === 'AbortError') return 'cancelled'
      // 其余（浏览器拒绝、无可用目标等）继续走复制
    }
  }
  return (await copyText(opts.url, fallbackEl)) ? 'copied' : 'failed'
}

/** 二维码里的地址是不是只有本机能打开（房主在电脑上生成、别人扫了打不开的经典坑） */
export function isLocalOrigin(): boolean {
  const h = location.hostname
  return h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === ''
}
