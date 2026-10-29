// API 基址：生产同源（lex 域 Caddy 把 /api/* 原样反代 fd-lex-api，不剥前缀）；
// dev 由 Vite proxy 转发到 127.0.0.1:8000。VITE_API_BASE 可显式覆盖。
const raw = String(import.meta.env.VITE_API_BASE ?? '').trim()

export const API_BASE = (raw || '/api').replace(/\/$/, '')

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}