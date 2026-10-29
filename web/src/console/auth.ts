// 控制台登录：Logto SPA authorization code + PKCE（浏览器侧完成，无客户端密钥）。
//
// 跨域凭据方案（lex-platform-v1 4.3 的关键决策）：
// - lex 域页面拿不到 mcp 域的会话 cookie，也没有共享密钥可用；因此控制台自带
//   Logto 登录，拿到 ID token（证明身份）与 access token（aud=registry 接受的
//   API resource，作凭据透传给 registry patch-keys）。
// - 服务端（/api/console/*）只做 ID token 本地校验；access token 仅用于
//   「铸造/吊销凭据」代理，随 X-Registry-Token 头传递，不落库、不写日志。
// - 未配置 LOGTO_*（服务端 /api/console/auth/config 报 configured=false）时
//   前端如实显示阻塞态与缺失项，绝不假登录。

import { apiUrl } from '../api/config'

export interface ConsoleAuthConfig {
  configured: boolean
  issuer: string
  client_id: string
  resource: string
  scopes: string[]
  organization_required: boolean
  missing: string[]
}

export interface ConsoleSession {
  idToken: string
  accessToken: string
  refreshToken?: string
  /** 过期时刻（ms epoch，取 ID/access 较早者） */
  expiresAt: number
  /** 展示身份（来自 ID token claims，仅供显示） */
  identity: string
  email?: string
  name?: string
  roles: string[]
  organizations: string[]
}

export class ConsoleAuthError extends Error {
  readonly status: number | undefined
  readonly detail: string | undefined

  constructor(message: string, status?: number, detail?: string) {
    super(message)
    this.name = 'ConsoleAuthError'
    this.status = status
    this.detail = detail
  }
}

export const SESSION_STORAGE_KEY = 'lex.console.session'
export const PKCE_STORAGE_KEY = 'lex.console.pkce'

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

export async function fetchAuthConfig(): Promise<ConsoleAuthConfig> {
  let response: Response
  try {
    response = await fetch(apiUrl('/console/auth/config'), {
      headers: { Accept: 'application/json' },
    })
  } catch (err) {
    throw new ConsoleAuthError(`network error fetching auth config: ${(err as Error).message}`)
  }
  if (!response.ok) {
    throw new ConsoleAuthError(`auth config ${response.status}`, response.status)
  }
  return (await response.json()) as ConsoleAuthConfig
}

// ---------------------------------------------------------------------------
// 会话存取（sessionStorage：关标签即失效；token 不落 localStorage）
// ---------------------------------------------------------------------------

export function loadSession(): ConsoleSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as ConsoleSession
    if (!parsed.idToken || !parsed.accessToken) return null
    return parsed
  } catch {
    return null
  }
}

export function saveSession(session: ConsoleSession): void {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
  } catch {
    /* 存储不可用时仅本次会话生效 */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export function isExpired(session: ConsoleSession, skewMs = 60_000): boolean {
  return session.expiresAt <= Date.now() + skewMs
}

// ---------------------------------------------------------------------------
// PKCE 工具
// ---------------------------------------------------------------------------

function base64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomString(length = 32): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64Url(bytes)
}

async function sha256(input: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input))
  return new Uint8Array(digest)
}

interface PkceState {
  state: string
  verifier: string
  nonce: string
  returnTo: string
}

function savePkce(value: PkceState): void {
  try {
    sessionStorage.setItem(PKCE_STORAGE_KEY, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

function loadPkce(): PkceState | null {
  try {
    const raw = sessionStorage.getItem(PKCE_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as PkceState) : null
  } catch {
    return null
  }
}

function dropPkce(): void {
  try {
    sessionStorage.removeItem(PKCE_STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

/** 登录回跳地址（必须与 Logto 应用登记的 redirect URI 完全一致）。 */
export function consoleCallbackUrl(): string {
  return `${window.location.origin}/console/callback`
}

/** 发起登录：生成 PKCE 参数并跳转 Logto authorize。 */
export async function beginLogin(
  config: ConsoleAuthConfig,
  returnTo = '/console',
): Promise<void> {
  if (!config.configured) {
    throw new ConsoleAuthError('login not configured on server', 503)
  }
  const verifier = randomString(48)
  const challenge = base64Url(await sha256(verifier))
  const state = randomString(16)
  const nonce = randomString(16)
  savePkce({ state, verifier, nonce, returnTo })
  const params = new URLSearchParams({
    client_id: config.client_id,
    response_type: 'code',
    scope: config.scopes.join(' '),
    redirect_uri: consoleCallbackUrl(),
    state,
    nonce,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  if (config.resource) params.set('resource', config.resource)
  window.location.assign(`${config.issuer}/oidc/auth?${params.toString()}`)
}

function claimString(claims: Record<string, unknown>, key: string): string | undefined {
  const value = claims[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

function claimList(claims: Record<string, unknown>, key: string): string[] {
  const value = claims[key]
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.map((item) => String(item))
  return []
}

/** base64url 解码 JWT payload（仅展示用；校验在服务端）。 */
export function decodeJwtClaims(token: string): Record<string, unknown> {
  try {
    const payload = token.split('.')[1]
    if (!payload) return {}
    const padded = payload.replace(/-/g, '+').replace(/_/g, '/')
    const binary = atob(padded.padEnd(padded.length + ((4 - (padded.length % 4)) % 4), '='))
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
    return JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>
  } catch {
    return {}
  }
}

interface TokenResponse {
  id_token: string
  access_token: string
  refresh_token?: string
  expires_in?: number
}

function sessionFromTokens(tokens: TokenResponse): ConsoleSession {
  const claims = decodeJwtClaims(tokens.id_token)
  const identity =
    claimString(claims, 'username') ??
    claimString(claims, 'email') ??
    claimString(claims, 'sub') ??
    'unknown'
  const expiresIn = typeof tokens.expires_in === 'number' ? tokens.expires_in : 3600
  return {
    idToken: tokens.id_token,
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + expiresIn * 1000,
    identity,
    email: claimString(claims, 'email'),
    name: claimString(claims, 'name'),
    roles: claimList(claims, 'roles'),
    organizations: claimList(claims, 'organizations'),
  }
}

async function tokenRequest(config: ConsoleAuthConfig, body: URLSearchParams): Promise<TokenResponse> {
  let response: Response
  try {
    response = await fetch(`${config.issuer}/oidc/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
  } catch (err) {
    throw new ConsoleAuthError(`token endpoint unreachable: ${(err as Error).message}`)
  }
  if (!response.ok) {
    let detail: string | undefined
    try {
      const payload = (await response.json()) as { error_description?: string; error?: string }
      detail = payload.error_description ?? payload.error
    } catch {
      /* ignore */
    }
    throw new ConsoleAuthError(`token exchange failed (${response.status})`, response.status, detail)
  }
  return (await response.json()) as TokenResponse
}

/** 回调页：校验 state、兑换 code、落会话；返回 returnTo 路径。 */
export async function completeLogin(
  config: ConsoleAuthConfig,
  query: URLSearchParams,
): Promise<{ returnTo: string; session: ConsoleSession }> {
  const error = query.get('error')
  if (error) {
    throw new ConsoleAuthError(
      `login failed: ${error}`,
      400,
      query.get('error_description') ?? undefined,
    )
  }
  const code = query.get('code')
  const state = query.get('state')
  const pkce = loadPkce()
  if (!code || !state || !pkce || pkce.state !== state) {
    throw new ConsoleAuthError('login state mismatch or missing PKCE state', 400)
  }
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    client_id: config.client_id,
    redirect_uri: consoleCallbackUrl(),
    code_verifier: pkce.verifier,
  })
  if (config.resource) body.set('resource', config.resource)
  const tokens = await tokenRequest(config, body)
  dropPkce()
  const session = sessionFromTokens(tokens)
  saveSession(session)
  return { returnTo: pkce.returnTo || '/console', session }
}

/** 过期前用 refresh token 静默续期；失败返回 null（前端显示重新登录）。 */
export async function refreshSession(
  config: ConsoleAuthConfig,
  session: ConsoleSession,
): Promise<ConsoleSession | null> {
  if (!session.refreshToken) return null
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: session.refreshToken,
    client_id: config.client_id,
  })
  if (config.resource) body.set('resource', config.resource)
  try {
    const tokens = await tokenRequest(config, body)
    const next = sessionFromTokens({
      refresh_token: session.refreshToken,
      ...tokens,
    })
    saveSession(next)
    return next
  } catch {
    return null
  }
}

export function logoutLocal(): void {
  clearSession()
}