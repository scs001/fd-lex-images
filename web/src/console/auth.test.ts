// 控制台登录（Logto SPA + PKCE）关键路径单测：state 校验、code 兑换载荷、
// 会话落 sessionStorage、刷新令牌缺失时不发请求。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ConsoleAuthError,
  PKCE_STORAGE_KEY,
  SESSION_STORAGE_KEY,
  completeLogin,
  decodeJwtClaims,
  isExpired,
  loadSession,
  refreshSession,
  type ConsoleAuthConfig,
  type ConsoleSession,
} from './auth'

const CONFIG: ConsoleAuthConfig = {
  configured: true,
  issuer: 'https://auth.test.example',
  client_id: 'lex-console',
  resource: 'https://mcp.test.example/api',
  scopes: ['openid'],
  organization_required: true,
  missing: [],
}

function b64url(value: string): string {
  return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fakeIdToken(claims: Record<string, unknown>): string {
  return `header.${b64url(JSON.stringify(claims))}.signature`
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('decodeJwtClaims', () => {
  it('decodes the base64url payload', () => {
    const token = fakeIdToken({ username: 'lexdemocustomer', roles: ['lex-admin'] })
    expect(decodeJwtClaims(token)).toMatchObject({
      username: 'lexdemocustomer',
      roles: ['lex-admin'],
    })
  })

  it('returns empty claims on a malformed token', () => {
    expect(decodeJwtClaims('not-a-jwt')).toEqual({})
  })
})

describe('completeLogin', () => {
  it('rejects on state mismatch (CSRF guard)', async () => {
    sessionStorage.setItem(
      PKCE_STORAGE_KEY,
      JSON.stringify({ state: 'state-a', verifier: 'verifier', nonce: 'n', returnTo: '/console' }),
    )
    await expect(
      completeLogin(CONFIG, new URLSearchParams({ code: 'code-1', state: 'state-b' })),
    ).rejects.toBeInstanceOf(ConsoleAuthError)
  })

  it('exchanges the code with PKCE verifier and stores the session', async () => {
    sessionStorage.setItem(
      PKCE_STORAGE_KEY,
      JSON.stringify({ state: 'state-a', verifier: 'verifier-1', nonce: 'n', returnTo: '/console/quota' }),
    )
    const calls: Array<{ url: string; body: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), body: String(init?.body ?? '') })
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id_token: fakeIdToken({
              username: 'lexdemocustomer',
              email: 'lex-demo@findmail.com',
              roles: ['lex-user'],
              organizations: ['hnrbfpgq2717'],
            }),
            access_token: 'access-token-real',
            refresh_token: 'refresh-token-real',
            expires_in: 3600,
          }),
        } as Response
      }),
    )

    const result = await completeLogin(
      CONFIG,
      new URLSearchParams({ code: 'code-1', state: 'state-a' }),
    )
    expect(result.returnTo).toBe('/console/quota')
    expect(calls).toHaveLength(1)
    expect(calls[0]!.url).toBe('https://auth.test.example/oidc/token')
    expect(calls[0]!.body).toContain('grant_type=authorization_code')
    expect(calls[0]!.body).toContain('code_verifier=verifier-1')
    expect(calls[0]!.body).toContain('client_id=lex-console')
    expect(calls[0]!.body).toContain('resource=https%3A%2F%2Fmcp.test.example%2Fapi')

    const stored = loadSession()
    expect(stored?.identity).toBe('lexdemocustomer')
    expect(stored?.accessToken).toBe('access-token-real')
    expect(stored?.organizations).toEqual(['hnrbfpgq2717'])
    expect(isExpired(stored as ConsoleSession)).toBe(false)
  })
})

describe('refreshSession', () => {
  it('returns null when no refresh token is present', async () => {
    const session: ConsoleSession = {
      idToken: 'id',
      accessToken: 'access',
      expiresAt: Date.now() - 1000,
      identity: 'lexdemocustomer',
      roles: [],
      organizations: [],
    }
    expect(await refreshSession(CONFIG, session)).toBeNull()
  })
})

describe('loadSession', () => {
  it('rejects a session without tokens', () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ identity: 'x' }))
    expect(loadSession()).toBeNull()
  })
})