/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // dev：控制台/后台 API 同源代理到本地 fd-lex-api（127.0.0.1:8000）。
    // 生产同源由 Caddy 承接：https://lex.finddatatech.cloud/api/* → NodePort 31886。
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})