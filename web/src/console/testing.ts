// 测试专用：控制台 API 的内存假后端（语义对齐 fd_lex_api/console_api/routes.py）。
// 只用于单测；页面真实数据一律走真接口（生产绝不 mock）。
import type { ConsoleSession } from './auth'

export type FakeResponse = {
  ok: boolean
  status: number
  json: () => Promise<unknown>
}

export type FetchCall = {
  method: string
  url: URL
  headers: Record<string, string>
  body?: unknown
}

function jsonResponse(body: unknown, status = 200): FakeResponse {
  return { ok: status < 400, status, json: () => Promise.resolve(body) }
}

function headersOf(init?: RequestInit): Record<string, string> {
  if (!init?.headers) return {}
  const record: Record<string, string> = {}
  new Headers(init.headers as HeadersInit).forEach((value, key) => {
    record[key.toLowerCase()] = value
  })
  return record
}

export interface ConsoleBackendOptions {
  /** 未登录态：/console/me 返回 401 */
  unauthorized?: boolean
  /** 非 lex 组织：/console/me 返回 403 及 detail */
  forbiddenDetail?: string
  /** registry 代理返回 429（铸造配额） */
  mintStatus?: number
  mintDetail?: string
  /** 额度正常（默认返回硬停态，用于恢复途径渲染） */
  quotaAllowed?: boolean
  /** 未开户/未绑定（quota 与 billing 返回 customer=null） */
  unbound?: boolean
  /** 服务端未配置 Logto（auth/config configured=false） */
  configMissing?: boolean
}

export const TEST_SESSION: ConsoleSession = {
  idToken: 'id-token-test',
  accessToken: 'access-token-test',
  expiresAt: Date.now() + 3_600_000,
  identity: 'lexdemocustomer',
  email: 'lex-demo@findmail.com',
  name: 'Lex Demo',
  roles: ['lex-user'],
  organizations: ['hnrbfpgq2717'],
}

export interface FakeKey {
  key_id: string
  name: string
  key_prefix: string
  username: string
  email: string | null
  provider: string | null
  egress_user: string | null
  groups: string[]
  status: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export function installConsoleBackend(
  options: ConsoleBackendOptions = {},
): {
  calls: FetchCall[]
  fetchImpl: typeof fetch
  keys: FakeKey[]
} {
  const calls: FetchCall[] = []
  const keys: FakeKey[] = [
    {
      key_id: 'key-1',
      name: 'demo-key',
      key_prefix: 'wgk-Abc123',
      username: 'lexdemocustomer',
      email: 'lex-demo@findmail.com',
      provider: 'oauth2',
      egress_user: '8tajhoprelg0',
      groups: ['lex-customers'],
      status: 'active',
      created_at: '2026-10-05T09:31:37',
      last_used_at: '2026-10-05T09:37:39',
      revoked_at: null,
    },
  ]

  const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit): Promise<FakeResponse> => {
    const url = new URL(String(input), 'http://console.test')
    const method = (init?.method ?? 'GET').toUpperCase()
    const headers = headersOf(init)
    calls.push({
      method,
      url,
      headers,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    })

    const path = url.pathname

    if (path === '/api/console/auth/config') {
      if (options.configMissing) {
        return Promise.resolve(
          jsonResponse({
            configured: false,
            issuer: '',
            client_id: '',
            resource: '',
            scopes: [],
            organization_required: false,
            missing: ['LOGTO_ISSUER', 'LOGTO_CLIENT_ID'],
          }),
        )
      }
      return Promise.resolve(
        jsonResponse({
          configured: true,
          issuer: 'https://auth.test.example',
          client_id: 'lex-console',
          resource: 'https://mcp.test.example/api',
          scopes: ['openid'],
          organization_required: true,
          missing: [],
        }),
      )
    }

    if (headers.authorization !== `Bearer ${TEST_SESSION.idToken}`) {
      return Promise.resolve(jsonResponse({ detail: 'missing bearer token' }, 401))
    }
    if (options.unauthorized) {
      return Promise.resolve(jsonResponse({ detail: 'invalid console token' }, 401))
    }
    if (options.forbiddenDetail) {
      return Promise.resolve(jsonResponse({ detail: options.forbiddenDetail }, 403))
    }

    if (path === '/api/console/me') {
      return Promise.resolve(
        jsonResponse({
          identity: TEST_SESSION.identity,
          username: TEST_SESSION.identity,
          email: TEST_SESSION.email,
          sub: 'sub-1',
          roles: TEST_SESSION.roles,
          organizations: TEST_SESSION.organizations,
          is_admin: false,
          customer: {
            id: 1,
            name: '识律演示客户',
            sub2api_user_id: '8tajhoprelg0',
            plan_code: 'standard',
            plan_name: '标准版',
            monthly_price_micro: 2_000_000,
            monthly_price_yuan: '¥2.00',
            status: 'active',
            created_at: '2026-10-01T00:00:00',
          },
          identities: ['lexdemocustomer', '8tajhoprelg0'],
          bindings: [{ id: 1, customer_id: 1, identity: 'lexdemocustomer', note: null }],
        }),
      )
    }

    if (path === '/api/console/usage') {
      const period = url.searchParams.get('period') ?? '2026-10'
      return Promise.resolve(
        jsonResponse({
          period,
          unit_catalog: ['line', 'call', 'token'],
          customer: { id: 1, name: '识律演示客户' },
          identities: ['lexdemocustomer'],
          totals: { calls: 3, by_unit: { line: 42, call: 1 } },
          breakdown: [
            {
              unit: 'line',
              server_name: 'fd-legal-search-mcp',
              tool_name: 'law_reference',
              calls: 1,
              quantity: 42,
            },
            {
              unit: 'call',
              server_name: 'fd-legal-search-mcp',
              tool_name: 'contract_draft',
              calls: 2,
              quantity: 1,
            },
          ],
          recent: [
            {
              event_timestamp: '2026-10-03T09:00:00+00:00',
              server_name: 'fd-legal-search-mcp',
              tool_name: 'contract_draft',
              unit: 'call',
              quantity: 1,
            },
          ],
        }),
      )
    }

    if (path === '/api/console/billing') {
      const period = url.searchParams.get('period') ?? '2026-10'
      if (options.unbound) {
        return Promise.resolve(
          jsonResponse({ period, customer: null, entries: [], totals: null }),
        )
      }
      return Promise.resolve(
        jsonResponse({
          period,
          customer: { id: 1, name: '识律演示客户', plan_name: '标准版', monthly_price_yuan: '¥2.00' },
          entries: [
            {
              id: 1,
              kind: 'overage',
              unit: 'line',
              quantity: 10,
              amount_micro: 40_000,
              amount_yuan: '¥0.04',
              period,
              idempotency_key: 'settle:1:line',
              source_ref: null,
              sub2api_applied: true,
              created_at: '2026-10-31T00:00:00',
            },
          ],
          totals: {
            amount_micro: 40_000,
            amount_yuan: '¥0.04',
            by_kind: { overage: { amount_micro: 40_000, amount_yuan: '¥0.04' } },
          },
        }),
      )
    }

    if (path === '/api/console/quota') {
      const period = url.searchParams.get('period') ?? '2026-10'
      if (options.unbound) {
        return Promise.resolve(
          jsonResponse({
            period,
            customer: null,
            status: null,
            identities: ['lexdemocustomer'],
            recovery: ['not_provisioned'],
          }),
        )
      }
      const allowed = options.quotaAllowed === true
      return Promise.resolve(
        jsonResponse({
          period,
          customer: { id: 1, name: '识律演示客户' },
          status: {
            customer_id: 1,
            customer_name: '识律演示客户',
            period,
            allowed,
            denial_reason: allowed ? null : 'quota_exhausted:call',
            units: [
              {
                unit: 'line',
                included_quantity: 1000,
                used_quantity: 42,
                remaining_quantity: 958,
                used_pct: 5,
                tiers_hit: [],
                overage_priced: true,
                configured: true,
              },
              {
                unit: 'call',
                included_quantity: 100,
                used_quantity: allowed ? 40 : 100,
                remaining_quantity: allowed ? 60 : 0,
                used_pct: allowed ? 40 : 100,
                tiers_hit: allowed ? [] : [80, 95],
                overage_priced: false,
                configured: true,
              },
            ],
            balance: {
              reachable: true,
              balance_micro: 50_000_000,
              min_balance_micro: 0,
              sufficient: true,
              error: null,
            },
          },
          identities: ['lexdemocustomer'],
          recovery: allowed ? [] : ['upgrade_quota', 'contact_sales'],
        }),
      )
    }

    if (path === '/api/console/credentials' && method === 'GET') {
      return Promise.resolve(jsonResponse({ total: keys.length, items: keys }))
    }

    if (path === '/api/console/credentials' && method === 'POST') {
      if (options.mintStatus && options.mintStatus >= 400) {
        return Promise.resolve(
          jsonResponse({ detail: options.mintDetail ?? `registry ${options.mintStatus}` }, options.mintStatus),
        )
      }
      const payload = (calls[calls.length - 1]!.body ?? {}) as { name?: string }
      const created: FakeKey = {
        key_id: 'key-2',
        name: payload.name ?? 'new-key',
        key_prefix: 'wgk-NewKey',
        username: 'lexdemocustomer',
        email: 'lex-demo@findmail.com',
        provider: 'oauth2',
        egress_user: '8tajhoprelg0',
        groups: ['lex-customers'],
        status: 'active',
        created_at: '2026-10-05T10:00:00',
        last_used_at: null,
        revoked_at: null,
      }
      keys.push(created)
      return Promise.resolve(
        jsonResponse({ key: 'wgk-PlaintextOnce123', info: created }, 201),
      )
    }

    const revoke = path.match(/^\/api\/console\/credentials\/([^/]+)$/)
    if (revoke && method === 'DELETE') {
      const keyId = decodeURIComponent(revoke[1]!)
      const target = keys.find((key) => key.key_id === keyId)
      if (!target) return Promise.resolve(jsonResponse({ detail: 'Key not found' }, 404))
      target.status = 'revoked'
      target.revoked_at = '2026-10-05T10:05:00'
      return Promise.resolve(jsonResponse(target))
    }

    if (path === '/api/console/credentials/events') {
      return Promise.resolve(
        jsonResponse({
          identity: 'lexdemocustomer',
          events: [
            {
              id: 1,
              action: 'mint',
              key_id: 'key-2',
              key_name: 'new-key',
              key_prefix: 'wgk-NewKey',
              username: 'lexdemocustomer',
              groups: ['lex-customers'],
              detail: null,
              created_at: '2026-10-05T10:00:00',
            },
          ],
          note: 'lex-console only',
        }),
      )
    }

    return Promise.resolve(jsonResponse({ detail: 'not found' }, 404))
  }) as unknown as typeof fetch

  return { calls, fetchImpl, keys }
}