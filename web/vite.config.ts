import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      // manifest 由 public/manifest.webmanifest 手工维护（图标见 tools/make_pwa_icons.py）
      injectRegister: 'auto',
      registerType: 'autoUpdate',
      manifest: false,
      workbox: {
        // 离线壳：HTML/JS/CSS/图标全部预缓存，断网时至少能打开、看到「重连中…」
        // 而不是浏览器的错误页。识别资源单独走运行时缓存，见下。
        globPatterns: ['**/*.{js,css,html,png,svg,webp,woff2}'],
        globIgnores: ['tesseract/**'],
        navigateFallback: 'index.html',
        // API 与 WebSocket 永远走网络：账目是服务端权威，缓存一份旧的只会骗人
        navigateFallbackDenylist: [/^\/api\//, /^\/ws/, /^\/manual_pages\//],
        runtimeCaching: [
          {
            // 浏览器端 OCR 的模型与 WASM 共 13MB，且一台设备只会用到其中一个 core。
            // 全量预缓存会让首次进房就下 13MB（一桌人同时下，房主的网先垮），
            // 所以改成用到才存、存下就长期可用 —— 扫过一次卡之后即可离线识别。
            // 若确实要开局前一次性备齐，把 'tesseract/**' 从 globIgnores 里删掉即可
            // （还需把 maximumFileSizeToCacheInBytes 提到 5MB，单文件最大 3.9MB）。
            // 2026-08-01 复查设计稿：稿子对 PWA 预缓存没有任何要求，房主定案维持运行时缓存。
            urlPattern: /\/tesseract\/.*/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'ocr-assets',
              expiration: { maxEntries: 8, maxAgeSeconds: 60 * 60 * 24 * 180 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // 说明书分页图：随镜像交付、内容不变，缓存住省得每次翻页都拉
            urlPattern: /\/manual_pages\/.*\.webp$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'manual-pages',
              expiration: { maxEntries: 24, maxAgeSeconds: 60 * 60 * 24 * 180 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    host: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
