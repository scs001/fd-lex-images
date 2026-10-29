// 控制台 API 客户端（/api/console/*；服务端见 fd_lex_api/console_api/routes.py）。
//
// - 身份：Authorization: Bearer <Logto ID token>（服务端本地校验 JWKS/iss/aud）。
// - 凭据写操作：额外 X-Registry-Token: <Logto access token>——registry 面
//   承认的凭据，经服务端透传给 /api/patch-keys（跨域难题绕行方案）。
// - 错误如实：非 2xx 一律抛 ConsoleApiError（status + 后端 detail），
//   UI 原样呈现（401=登录态失效、403=非 lex 客户组织、502=registry 不可达）。

import { apiUrl } from '../api/config'
import type { ConsoleSession } from './auth'

export class ConsoleApiError extends Error {
  readonly status: number | undefined
  readonly detail: string | undefined

  constructor(message: string, status?: number, detail?: string) {
    super(message)
    this.name = 'ConsoleApiError'
    this.status = status
    this.detail = detail
  }
}

interface RequestOptions {
  method: 'GET' | 'POST' | 'DELETE'
  idToken: string
  registryToken?: string
  body?: unknown
}

async function requestJson(path: string, options: RequestOptions): Promise<unknown> {
  const url = apiUrl(path)
  const headers: Record<string, string> = {
    Accept: 'application/json',
    Authorization: `Bearer ${options.idToken}`,
  }
  if (options.registryToken) headers['X-Registry-Token'] = options.registryToken
  let response: Response
  try {
    response = await fetch(url, {
      method: options.method,
      headers: {
        ...headers,
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    })
  } catch (err) {
    throw new ConsoleApiError(`network error fetching ${url}: ${(err as Error).message}`)
  }
  if (!response.ok) {
    let detail: string | undefined
    try {
      const data: unknown = await response.json()
      if (data && typeof data === 'object' && typeof (data as { detail?: unknown }).detail === 'string') {
        detail = (data as { detail: string }).detail
      }
    } catch {
      /* 无 JSON body：保留 undefined */
    }
    throw new ConsoleApiError(`console api ${response.status} for ${url}`, response.status, detail)
  }
  try {
    return await response.json()
  } catch (err) {
    throw new ConsoleApiError(`invalid json from ${url}: ${(err as Error).message}`)
  }
}

// ---------------------------------------------------------------------------
// 响应类型（对齐服务端字典）
// ---------------------------------------------------------------------------

export interface ConsoleCustomer {
  id: number
  name: string
  sub2api_user_id: string | null
  plan_code: string
  plan_name: string
  monthly_price_micro: number
  monthly_price_yuan: string | null
  status: string
  created_at: string | null
}

export interface MeResponse {
  identity: string
  username: string | null
  email: string | null
  sub: string | null
  roles: string[]
  organizations: string[]
  is_admin: boolean
  customer: ConsoleCustomer | null
  identities: string[]
  bindings: Array<{ id: number; customer_id: number; identity: string; note: string | null }>
}

export interface UsageRow {
  unit: string
  server_name: string
  tool_name: string | null
  calls: number
  quantity: number
}

export interface UsageResponse {
  period: string
  unit_catalog: string[]
  customer: ConsoleCustomer | null
  identities: string[]
  totals: { calls: number; by_unit: Record<string, number> }
  breakdown: UsageRow[]
  recent: Array<{
    event_timestamp: string
    server_name: string
    tool_name: string | null
    unit: string
    quantity: number
  }>
}

export interface LedgerEntryView {
  id: number
  kind: string
  unit: string | null
  quantity: number
  amount_micro: number
  amount_yuan: string
  period: string
  idempotency_key: string
  source_ref: string | null
  sub2api_applied: boolean
  created_at: string | null
}

export interface BillingResponse {
  period: string
  customer: ConsoleCustomer | null
  entries: LedgerEntryView[]
  totals: {
    amount_micro: number
    amount_yuan: string
    by_kind: Record<string, { amount_micro: number; amount_yuan: string }>
  } | null
}

export interface UnitQuotaView {
  unit: string
  included_quantity: number
  used_quantity: number
  remaining_quantity: number
  used_pct: number
  tiers_hit: number[]
  overage_priced: boolean
  configured: boolean
}

export interface QuotaResponse {
  period: string
  customer: ConsoleCustomer | null
  status: {
    customer_id: number
    customer_name: string
    period: string
    allowed: boolean
    denial_reason: string | null
    units: UnitQuotaView[]
    balance: {
      reachable: boolean
      balance_micro: number | null
      min_balance_micro: number
      sufficient: boolean
      error: string | null
    } | null
  } | null
  identities: string[]
  recovery: string[]
}

export interface RegistryKey {
  key_id: string
  name: string
  key_prefix: string
  username: string
  email: string | null
  provider: string | null
  egress_user: string | null
  groups: string[]
  status: string
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface RegistryKeyList {
  total: number
  items: RegistryKey[]
}

export interface MintedKey {
  key: string
  info: RegistryKey
}

export interface CredentialEvent {
  id: number
  action: string
  key_id: string
  key_name: string | null
  key_prefix: string | null
  username: string
  groups: string[]
  detail: string | null
  created_at: string | null
}

// ---------------------------------------------------------------------------
// 端点
// ---------------------------------------------------------------------------

export function fetchMe(session: ConsoleSession): Promise<MeResponse> {
  return requestJson('/console/me', {
    method: 'GET',
    idToken: session.idToken,
  }) as Promise<MeResponse>
}

export function fetchUsage(session: ConsoleSession, period: string): Promise<UsageResponse> {
  return requestJson(`/console/usage?period=${encodeURIComponent(period)}`, {
    method: 'GET',
    idToken: session.idToken,
  }) as Promise<UsageResponse>
}

export function fetchBilling(session: ConsoleSession, period: string): Promise<BillingResponse> {
  return requestJson(`/console/billing?period=${encodeURIComponent(period)}`, {
    method: 'GET',
    idToken: session.idToken,
  }) as Promise<BillingResponse>
}

export function fetchQuota(session: ConsoleSession, period: string): Promise<QuotaResponse> {
  return requestJson(`/console/quota?period=${encodeURIComponent(period)}`, {
    method: 'GET',
    idToken: session.idToken,
  }) as Promise<QuotaResponse>
}

export function fetchCredentials(session: ConsoleSession): Promise<RegistryKeyList> {
  return requestJson('/console/credentials', {
    method: 'GET',
    idToken: session.idToken,
    registryToken: session.accessToken,
  }) as Promise<RegistryKeyList>
}

export function mintCredential(session: ConsoleSession, name: string): Promise<MintedKey> {
  return requestJson('/console/credentials', {
    method: 'POST',
    idToken: session.idToken,
    registryToken: session.accessToken,
    body: { name },
  }) as Promise<MintedKey>
}

export function revokeCredential(session: ConsoleSession, keyId: string): Promise<RegistryKey> {
  return requestJson(`/console/credentials/${encodeURIComponent(keyId)}`, {
    method: 'DELETE',
    idToken: session.idToken,
    registryToken: session.accessToken,
  }) as Promise<RegistryKey>
}

export function fetchCredentialEvents(session: ConsoleSession): Promise<{
  identity: string
  events: CredentialEvent[]
  note: string
}> {
  return requestJson('/console/credentials/events', {
    method: 'GET',
    idToken: session.idToken,
  }) as Promise<{ identity: string; events: CredentialEvent[]; note: string }>
}

// ---------------------------------------------------------------------------
// 展示工具
// ---------------------------------------------------------------------------

/** 当前周期（YYYY-MM，本地时区）。 */
export function currentPeriod(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/** 微元 → 元字符串（最多四位小数，单价等细粒度场景用）。 */
export function formatMicro(micro: number, maxFractionDigits = 4): string {
  const yuan = micro / 1_000_000
  return `¥${yuan.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.min(maxFractionDigits, 6),
  })}`
}