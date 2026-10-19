/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

// Production-build CSP, injected as a <meta> tag. (Send the same policy as an HTTP header in deployment, where
// frame-ancestors can also be set.) Dev keeps it off because Vite's HMR needs inline scripts.
function csp(apiOrigin: string): Plugin {
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    `connect-src 'self' ${apiOrigin}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
  return {
    name: 'inject-csp',
    apply: 'build',
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' },
    ],
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiUrl = env.VITE_API_URL || '/api/v1'
  const apiOrigin = /^https?:\/\//.test(apiUrl) ? new URL(apiUrl).origin : ''
  return {
    plugins: [react(), csp(apiOrigin)],
    server: {
      port: 5173,
      // Same-origin in dev: no CORS needed. Override with VITE_DEV_PROXY_TARGET.
      proxy: { '/api': { target: env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } },
    },
    build: { sourcemap: false },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
      env: { VITE_API_URL: 'http://api.test/api/v1' },
    },
  }
})
