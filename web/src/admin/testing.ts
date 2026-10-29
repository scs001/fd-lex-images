// 测试专用：运营后台 API 的内存假后端（语义对齐 fd_lex_api/admin_api/routes.py）。
import type { AdminCustomer, AdminPlan } from './api'

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

export const TEST_ADMIN_TOKEN = 'test-admin-token'

export interface AdminBackendOptions {
  /** 强制所有请求返回该状态（鉴权失败态测试） */
  forceStatus?: number
  forceDetail?: string
}

export function installAdminBackend(options: AdminBackendOptions = {}): {
  calls: FetchCall[]
  fetchImpl: typeof fetch
  customers: AdminCustomer[]
  plans: AdminPlan[]
  identities: Array<{ id: number; customer_id: number; identity: string; note: string | null; created_at: string }>
} {
  const calls: FetchCall[] = []

  const plans: AdminPlan[] = [
    {
      id: 1,
      code: 'standard',
      name: '标准版',
      monthly_price_micro: 2_000_000,
      monthly_price_yuan: '¥2.00',
      is_active: true,
      quotas: [
        {
          unit: 'line',
          included_quantity: 1000,
          overage_unit_price_micro: 4000,
          overage_unit_price_yuan: '¥0.00',
        },
      ],
    },
  ]

  const customers: AdminCustomer[] = [
    {
      id: 1,
      name: '识律演示客户',
      sub2api_user_id: '8tajhoprelg0',
      plan_id: 1,
      plan_code: 'standard',
      plan_name: '标准版',
      status: 'active',
      created_at: '2026-10-01T00:00:00',
    },
  ]

  const identities: Array<{
    id: number
    customer_id: number
    identity: string
    note: string | null
    created_at: string
  }> = []

  const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit): Promise<FakeResponse> => {
    const url = new URL(String(input), 'http://admin.test')
    const method = (init?.method ?? 'GET').toUpperCase()
    const headers = headersOf(init)
    calls.push({
      method,
      url,
      headers,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    })

    if (options.forceStatus && options.forceStatus >= 400) {
      return Promise.resolve(
        jsonResponse({ detail: options.forceDetail ?? `admin api ${options.forceStatus}` }, options.forceStatus),
      )
    }

    const authorized =
      headers['x-admin-token'] === TEST_ADMIN_TOKEN ||
      headers.authorization === 'Bearer test-session-token'
    if (!authorized) {
      return Promise.resolve(jsonResponse({ detail: 'admin credentials required' }, 401))
    }

    const path = url.pathname

    if (path === '/api/admin/whoami') {
      return Promise.resolve(
        jsonResponse({ via: 'internal-token', identity: 'internal', roles: [] }),
      )
    }

    if (path === '/api/admin/customers' && method === 'GET') {
      return Promise.resolve(jsonResponse({ customers, count: customers.length }))
    }

    if (path === '/api/admin/customers' && method === 'POST') {
      const payload = (calls[calls.length - 1]!.body ?? {}) as { name: string; plan_code: string }
      const created: AdminCustomer = {
        id: customers.length + 1,
        name: payload.name,
        sub2api_user_id: 'sub2api-new',
        plan_id: 1,
        plan_code: payload.plan_code,
        plan_name: '标准版',
        status: 'active',
        created_at: '2026-10-05T10:00:00',
      }
      customers.push(created)
      return Promise.resolve(jsonResponse({ created: true, customer: created }, 201))
    }

    const patch = path.match(/^\/api\/admin\/customers\/(\d+)$/)
    if (patch && method === 'PATCH') {
      const customer = customers.find((item) => item.id === Number(patch[1]))
      if (!customer) return Promise.resolve(jsonResponse({ detail: 'no such customer' }, 404))
      const payload = (calls[calls.length - 1]!.body ?? {}) as {
        plan_code?: string
        status?: string
      }
      if (payload.status) customer.status = payload.status
      if (payload.plan_code) customer.plan_code = payload.plan_code
      return Promise.resolve(jsonResponse({ customer }))
    }

    const identityList = path.match(/^\/api\/admin\/customers\/(\d+)\/identities$/)
    if (identityList && method === 'GET') {
      const customerId = Number(identityList[1])
      return Promise.resolve(
        jsonResponse({
          customer_id: customerId,
          identities: identities.filter((item) => item.customer_id === customerId),
          sub2api_user_id: customers.find((c) => c.id === customerId)?.sub2api_user_id ?? null,
          metering_identities: identities
            .filter((item) => item.customer_id === customerId)
            .map((item) => item.identity),
        }),
      )
    }
    if (identityList && method === 'POST') {
      const customerId = Number(identityList[1])
      const payload = (calls[calls.length - 1]!.body ?? {}) as { identity: string; note?: string }
      const binding = {
        id: identities.length + 1,
        customer_id: customerId,
        identity: payload.identity,
        note: payload.note ?? null,
        created_at: '2026-10-05T10:00:00',
      }
      identities.push(binding)
      return Promise.resolve(jsonResponse({ binding }, 201))
    }

    const unbind = path.match(/^\/api\/admin\/identities\/(\d+)$/)
    if (unbind && method === 'DELETE') {
      const index = identities.findIndex((item) => item.id === Number(unbind[1]))
      if (index >= 0) identities.splice(index, 1)
      return Promise.resolve(jsonResponse({ deleted: true }))
    }

    const quota = path.match(/^\/api\/admin\/customers\/(\d+)\/quota$/)
    if (quota) {
      const customer = customers.find((item) => item.id === Number(quota[1]))!
      return Promise.resolve(
        jsonResponse({
          customer,
          period: url.searchParams.get('period') ?? '2026-10',
          identities: ['lexdemocustomer'],
          status: {
            customer_id: customer.id,
            customer_name: customer.name,
            period: url.searchParams.get('period') ?? '2026-10',
            allowed: true,
            denial_reason: null,
            units: [],
            balance: null,
          },
        }),
      )
    }

    if (path === '/api/admin/plans' && method === 'GET') {
      return Promise.resolve(jsonResponse({ plans, count: plans.length }))
    }

    const putPlan = path.match(/^\/api\/admin\/plans\/([^/]+)$/)
    if (putPlan && method === 'PUT') {
      const code = decodeURIComponent(putPlan[1]!)
      const payload = (calls[calls.length - 1]!.body ?? {}) as {
        name: string
        monthly_price_micro: number
        is_active: boolean
        quotas: Array<{ unit: string; included_quantity: number; overage_unit_price_micro: number }>
      }
      let plan = plans.find((item) => item.code === code)
      if (!plan) {
        plan = {
          id: plans.length + 1,
          code,
          name: payload.name,
          monthly_price_micro: payload.monthly_price_micro,
          monthly_price_yuan: `¥${(payload.monthly_price_micro / 1_000_000).toFixed(2)}`,
          is_active: payload.is_active,
          quotas: [],
        }
        plans.push(plan)
      }
      plan.name = payload.name
      plan.monthly_price_micro = payload.monthly_price_micro
      plan.monthly_price_yuan = `¥${(payload.monthly_price_micro / 1_000_000).toFixed(2)}`
      plan.quotas = payload.quotas.map((quota) => ({
        unit: quota.unit,
        included_quantity: quota.included_quantity,
        overage_unit_price_micro: quota.overage_unit_price_micro,
        overage_unit_price_yuan: `¥${(quota.overage_unit_price_micro / 1_000_000).toFixed(2)}`,
      }))
      return Promise.resolve(jsonResponse({ plan }))
    }

    if (path === '/api/admin/ledger') {
      return Promise.resolve(
        jsonResponse({
          customer_id: null,
          period: null,
          entries: [
            {
              id: 1,
              customer_id: 1,
              kind: 'grant',
              unit: null,
              quantity: 0,
              amount_micro: 2_000_000,
              amount_yuan: '¥2.00',
              period: '2026-10',
              idempotency_key: 'grant:1:2026-10',
              source_ref: null,
              sub2api_applied: false,
              created_at: '2026-10-01T00:00:00',
            },
          ],
          count: 1,
          totals: { amount_micro: 2_000_000, amount_yuan: '¥2.00' },
        }),
      )
    }

    if (path === '/api/admin/usage/overview') {
      return Promise.resolve(
        jsonResponse({
          period: url.searchParams.get('period') ?? '2026-10',
          credential_track: null,
          breakdown: [
            {
              credential_track: 'customer',
              caller: 'lexdemocustomer',
              unit: 'line',
              calls: 1,
              quantity: 1250,
            },
          ],
          totals: { calls: 1, by_track: { customer: 1 }, by_unit: { line: 1250 } },
        }),
      )
    }

    if (path === '/api/admin/credentials/events') {
      return Promise.resolve(
        jsonResponse({
          events: [
            {
              id: 1,
              action: 'mint',
              key_id: 'k-9',
              key_name: 'console-key',
              key_prefix: 'wgk-Abc',
              username: 'lexdemocustomer',
              groups: ['lex-customers'],
              detail: null,
              created_at: '2026-10-05T10:00:00',
            },
          ],
          count: 1,
          note: 'issuance audit of the lex console proxy only',
        }),
      )
    }

    return Promise.resolve(jsonResponse({ detail: 'not found' }, 404))
  }) as unknown as typeof fetch

  return { calls, fetchImpl, customers, plans, identities }
}