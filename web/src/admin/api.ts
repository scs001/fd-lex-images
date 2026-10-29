// 运营后台 API 客户端（/api/admin/*；服务端见 fd_lex_api/admin_api/routes.py）。
//
// 鉴权两条路径（与后端一致，UI 如实标注）：
// - 内部令牌：X-Admin-Token = INTERNAL_API_TOKEN（wire admin 的占位模式；
//   localStorage 保存，仅内部运营使用）；
// - Logto 角色：控制台登录态（ID token）且 roles 命中 ADMIN_ROLES。
//
// 错误如实：非 2xx 抛 AdminApiError（status + 后端 detail），UI 原样呈现。
import { apiUrl } from '../api/config'

export class AdminApiError extends Error {
  readonly status: number | undefined
  readonly detail: string | undefined

  constructor(message: string, status?: number, detail?: string) {
    super(message)
    this.name = 'AdminApiError'
    this.status = status
    this.detail = detail
  }
}

export type AdminAuth =
  | { kind: 'token'; token: string }
  | { kind: 'session'; idToken: string; identity: string }

export const ADMIN_TOKEN_STORAGE_KEY = 'lex.admin.token'

export function loadAdminToken(): string {
  try {
    return localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveAdminToken(raw: string): string {
  const normalized = raw.trim()
  try {
    if (normalized) localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, normalized)
    else localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
  } catch {
    /* localStorage 不可用时仅本次会话生效 */
  }
  return normalized
}

export function authHeaders(auth: AdminAuth): Record<string, string> {
  if (auth.kind === 'token') return { 'X-Admin-Token': auth.token }
  return { Authorization: `Bearer ${auth.idToken}` }
}

interface RequestOptions {
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  auth: AdminAuth
  body?: unknown
}

async function requestJson(path: string, options: RequestOptions): Promise<unknown> {
  const url = apiUrl(path)
  let response: Response
  try {
    response = await fetch(url, {
      method: options.method,
      headers: {
        Accept: 'application/json',
        ...authHeaders(options.auth),
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    })
  } catch (err) {
    throw new AdminApiError(`network error fetching ${url}: ${(err as Error).message}`)
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
    throw new AdminApiError(`admin api ${response.status} for ${url}`, response.status, detail)
  }
  try {
    return await response.json()
  } catch (err) {
    throw new AdminApiError(`invalid json from ${url}: ${(err as Error).message}`)
  }
}

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

export interface WhoAmI {
  via: string
  identity: string
  roles: string[]
}

export interface AdminPlanQuota {
  unit: string
  included_quantity: number
  overage_unit_price_micro: number
  overage_unit_price_yuan: string
}

export interface AdminPlan {
  id: number
  code: string
  name: string
  monthly_price_micro: number
  monthly_price_yuan: string
  is_active: boolean
  quotas: AdminPlanQuota[]
}

export interface AdminCustomer {
  id: number
  name: string
  sub2api_user_id: string | null
  plan_id: number
  plan_code: string
  plan_name: string
  status: string
  created_at: string | null
}

export interface IdentityBinding {
  id: number
  customer_id: number
  identity: string
  note: string | null
  created_at: string | null
}

export interface IdentityList {
  customer_id: number
  identities: IdentityBinding[]
  sub2api_user_id: string | null
  metering_identities: string[]
}

export interface AdminLedgerEntry {
  id: number
  customer_id: number
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

export interface AdminUsageOverview {
  period: string
  credential_track: string | null
  breakdown: Array<{
    credential_track: string
    caller: string
    unit: string
    calls: number
    quantity: number
  }>
  totals: { calls: number; by_track: Record<string, number>; by_unit: Record<string, number> }
}

export interface AdminQuotaResponse {
  customer: AdminCustomer
  period: string
  identities: string[]
  status: {
    customer_id: number
    customer_name: string
    period: string
    allowed: boolean
    denial_reason: string | null
    units: Array<{
      unit: string
      included_quantity: number
      used_quantity: number
      remaining_quantity: number
      used_pct: number
      tiers_hit: number[]
      overage_priced: boolean
      configured: boolean
    }>
    balance: {
      reachable: boolean
      balance_micro: number | null
      sufficient: boolean
      error: string | null
    } | null
  }
}

export interface AdminCredentialEvent {
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

export function fetchWhoAmI(auth: AdminAuth): Promise<WhoAmI> {
  return requestJson('/admin/whoami', { method: 'GET', auth }) as Promise<WhoAmI>
}

export function fetchCustomers(auth: AdminAuth): Promise<{ customers: AdminCustomer[]; count: number }> {
  return requestJson('/admin/customers', { method: 'GET', auth }) as Promise<{
    customers: AdminCustomer[]
    count: number
  }>
}

export function createCustomer(
  auth: AdminAuth,
  payload: { name: string; plan_code: string },
): Promise<{ created: boolean; customer: AdminCustomer }> {
  return requestJson('/admin/customers', {
    method: 'POST',
    auth,
    body: payload,
  }) as Promise<{ created: boolean; customer: AdminCustomer }>
}

export function patchCustomer(
  auth: AdminAuth,
  customerId: number,
  payload: { plan_code?: string; status?: string },
): Promise<{ customer: AdminCustomer }> {
  return requestJson(`/admin/customers/${customerId}`, {
    method: 'PATCH',
    auth,
    body: payload,
  }) as Promise<{ customer: AdminCustomer }>
}

export function fetchIdentities(auth: AdminAuth, customerId: number): Promise<IdentityList> {
  return requestJson(`/admin/customers/${customerId}/identities`, {
    method: 'GET',
    auth,
  }) as Promise<IdentityList>
}

export function bindIdentity(
  auth: AdminAuth,
  customerId: number,
  payload: { identity: string; note?: string },
): Promise<{ binding: IdentityBinding }> {
  return requestJson(`/admin/customers/${customerId}/identities`, {
    method: 'POST',
    auth,
    body: payload,
  }) as Promise<{ binding: IdentityBinding }>
}

export function unbindIdentity(auth: AdminAuth, bindingId: number): Promise<{ deleted: boolean }> {
  return requestJson(`/admin/identities/${bindingId}`, {
    method: 'DELETE',
    auth,
  }) as Promise<{ deleted: boolean }>
}

export function fetchCustomerQuota(
  auth: AdminAuth,
  customerId: number,
  period: string,
): Promise<AdminQuotaResponse> {
  return requestJson(
    `/admin/customers/${customerId}/quota?period=${encodeURIComponent(period)}`,
    { method: 'GET', auth },
  ) as Promise<AdminQuotaResponse>
}

export function fetchPlans(auth: AdminAuth): Promise<{ plans: AdminPlan[]; count: number }> {
  return requestJson('/admin/plans', { method: 'GET', auth }) as Promise<{
    plans: AdminPlan[]
    count: number
  }>
}

export function putPlan(
  auth: AdminAuth,
  code: string,
  payload: {
    name: string
    monthly_price_micro: number
    is_active: boolean
    quotas: Array<{ unit: string; included_quantity: number; overage_unit_price_micro: number }>
  },
): Promise<{ plan: AdminPlan }> {
  return requestJson(`/admin/plans/${encodeURIComponent(code)}`, {
    method: 'PUT',
    auth,
    body: payload,
  }) as Promise<{ plan: AdminPlan }>
}

export function fetchLedger(
  auth: AdminAuth,
  params: { customer_id?: number; period?: string; limit?: number } = {},
): Promise<{ entries: AdminLedgerEntry[]; count: number; totals: { amount_yuan: string } }> {
  const qs = new URLSearchParams()
  if (params.customer_id != null) qs.set('customer_id', String(params.customer_id))
  if (params.period) qs.set('period', params.period)
  if (params.limit != null) qs.set('limit', String(params.limit))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return requestJson(`/admin/ledger${suffix}`, { method: 'GET', auth }) as Promise<{
    entries: AdminLedgerEntry[]
    count: number
    totals: { amount_yuan: string }
  }>
}

export function fetchUsageOverview(
  auth: AdminAuth,
  params: { period: string; credential_track?: string },
): Promise<AdminUsageOverview> {
  const qs = new URLSearchParams({ period: params.period })
  if (params.credential_track) qs.set('credential_track', params.credential_track)
  return requestJson(`/admin/usage/overview?${qs.toString()}`, {
    method: 'GET',
    auth,
  }) as Promise<AdminUsageOverview>
}

export function fetchCredentialEvents(
  auth: AdminAuth,
  params: { username?: string; limit?: number } = {},
): Promise<{ events: AdminCredentialEvent[]; count: number; note: string }> {
  const qs = new URLSearchParams()
  if (params.username) qs.set('username', params.username)
  if (params.limit != null) qs.set('limit', String(params.limit))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return requestJson(`/admin/credentials/events${suffix}`, { method: 'GET', auth }) as Promise<{
    events: AdminCredentialEvent[]
    count: number
    note: string
  }>
}