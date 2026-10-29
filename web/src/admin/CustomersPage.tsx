// 后台客户管理：列表 / 开户（sub2api 代建）/ 改档位与状态 / 身份绑定（Logto ↔ 客户）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AdminPageHeader, AdminState } from './AdminLayout'
import {
  AdminApiError,
  type AdminAuth,
  type AdminCustomer,
  type AdminPlan,
  type IdentityList,
  bindIdentity,
  createCustomer,
  fetchCustomerQuota,
  fetchCustomers,
  fetchIdentities,
  fetchPlans,
  patchCustomer,
  unbindIdentity,
} from './api'

const STATUS_OPTIONS = ['active', 'suspended', 'closed'] as const

function currentPeriod(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function CustomersPage({ auth }: { auth: AdminAuth }) {
  const { t } = useTranslation()
  const [customers, setCustomers] = useState<AdminCustomer[] | null>(null)
  const [plans, setPlans] = useState<AdminPlan[]>([])
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const [name, setName] = useState('')
  const [planCode, setPlanCode] = useState('')
  const [creating, setCreating] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const [selected, setSelected] = useState<AdminCustomer | null>(null)
  const [identities, setIdentities] = useState<IdentityList | null>(null)
  const [identityDraft, setIdentityDraft] = useState('')
  const [quotaSummary, setQuotaSummary] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    setCustomers(null)
    try {
      const [listing, planListing] = await Promise.all([fetchCustomers(auth), fetchPlans(auth)])
      setCustomers(listing.customers)
      setPlans(planListing.plans)
      setPlanCode((current) => current || (planListing.plans[0]?.code ?? ''))
    } catch (err) {
      setError(err as AdminApiError)
    }
  }, [auth])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = useCallback(
    async (customer: AdminCustomer) => {
      setSelected(customer)
      setIdentities(null)
      setQuotaSummary(null)
      try {
        const [identityList, quota] = await Promise.all([
          fetchIdentities(auth, customer.id),
          fetchCustomerQuota(auth, customer.id, currentPeriod()),
        ])
        setIdentities(identityList)
        const state = quota.status.allowed
          ? t('admin.customers.quotaAllowed')
          : `${t('console.quota.blocked')}: ${quota.status.denial_reason ?? ''}`
        setQuotaSummary(state)
      } catch (err) {
        setError(err as AdminApiError)
      }
    },
    [auth, t],
  )

  const submitCreate = async () => {
    if (!name.trim() || !planCode) return
    setCreating(true)
    setNotice(null)
    try {
      const result = await createCustomer(auth, { name: name.trim(), plan_code: planCode })
      setNotice(
        result.created
          ? t('admin.customers.createdNotice')
          : t('admin.customers.existingNotice'),
      )
      setName('')
      await load()
    } catch (err) {
      setError(err as AdminApiError)
    } finally {
      setCreating(false)
    }
  }

  const changePlan = async (customer: AdminCustomer, nextPlan: string) => {
    setNotice(null)
    try {
      await patchCustomer(auth, customer.id, { plan_code: nextPlan })
      await load()
    } catch (err) {
      setError(err as AdminApiError)
    }
  }

  const changeStatus = async (customer: AdminCustomer, nextStatus: string) => {
    setNotice(null)
    try {
      await patchCustomer(auth, customer.id, { status: nextStatus })
      await load()
    } catch (err) {
      setError(err as AdminApiError)
    }
  }

  const submitBind = async () => {
    if (!selected || !identityDraft.trim()) return
    setNotice(null)
    try {
      await bindIdentity(auth, selected.id, { identity: identityDraft.trim() })
      setIdentityDraft('')
      await openDetail(selected)
    } catch (err) {
      setError(err as AdminApiError)
    }
  }

  const submitUnbind = async (bindingId: number) => {
    setNotice(null)
    try {
      await unbindIdentity(auth, bindingId)
      if (selected) await openDetail(selected)
    } catch (err) {
      setError(err as AdminApiError)
    }
  }

  return (
    <div>
      <AdminPageHeader
        titleKey="admin.customers.title"
        subtitleKey="admin.customers.subtitle"
        extra={
          <span className="rounded-md border border-line bg-paper px-3 py-1.5 text-[11px] text-ink-soft">
            {t('admin.customers.sub2apiNote')}
          </span>
        }
      />

      <div className="mt-6 rounded-lg border border-line bg-white p-5" data-testid="admin-customer-create">
        <h2 className="font-display text-base font-semibold text-ink">
          {t('admin.customers.createTitle')}
        </h2>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-soft">
            {t('admin.customers.nameLabel')}
            <input
              data-testid="customer-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-1 block w-56 rounded border border-line-strong bg-white px-2 py-1.5 text-sm text-ink"
            />
          </label>
          <label className="text-xs text-ink-soft">
            {t('admin.customers.planLabel')}
            <select
              data-testid="customer-plan"
              value={planCode}
              onChange={(event) => setPlanCode(event.target.value)}
              className="mt-1 block w-44 rounded border border-line-strong bg-white px-2 py-1.5 text-sm text-ink"
            >
              {plans.map((plan) => (
                <option key={plan.code} value={plan.code}>
                  {plan.name}（{plan.code}）
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            data-testid="customer-create"
            disabled={creating || !name.trim() || !planCode}
            onClick={() => void submitCreate()}
            className="rounded-md bg-field px-4 py-2 text-sm text-white transition-colors hover:bg-field-deep disabled:opacity-50"
          >
            {creating ? t('admin.customers.creating') : t('admin.customers.create')}
          </button>
          {plans.length === 0 && (
            <span className="text-[11px] text-seal">{t('admin.customers.noPlans')}</span>
          )}
        </div>
        {notice && (
          <p className="mt-3 text-xs text-field" data-testid="customer-notice">
            {notice}
          </p>
        )}
      </div>

      <AdminState loading={customers === null} error={error} onRetry={() => void load()}>
        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t('admin.customers.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.customers.colIdentity')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.customers.colPlan')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.customers.colStatus')}</th>
                <th className="px-4 py-2.5 text-right font-medium">
                  {t('admin.customers.colActions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {(customers ?? []).map((customer) => (
                <tr key={customer.id} className="border-t border-line" data-testid="customer-row">
                  <td className="px-4 py-2.5">
                    {customer.name}
                    <span className="ml-2 font-mono text-[11px] text-ink-soft">#{customer.id}</span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink-soft">
                    {customer.sub2api_user_id ?? '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <select
                      data-testid={`customer-plan-${customer.id}`}
                      value={customer.plan_code}
                      onChange={(event) => void changePlan(customer, event.target.value)}
                      className="rounded border border-line-strong bg-white px-1.5 py-1 text-xs"
                    >
                      {plans.map((plan) => (
                        <option key={plan.code} value={plan.code}>
                          {plan.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-2.5">
                    <select
                      data-testid={`customer-status-${customer.id}`}
                      value={customer.status}
                      onChange={(event) => void changeStatus(customer, event.target.value)}
                      className="rounded border border-line-strong bg-white px-1.5 py-1 text-xs"
                    >
                      {STATUS_OPTIONS.map((status) => (
                        <option key={status} value={status}>
                          {status}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      data-testid={`customer-detail-${customer.id}`}
                      onClick={() => void openDetail(customer)}
                      className="text-xs text-field underline-offset-2 hover:underline"
                    >
                      {t('admin.customers.detail')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(customers ?? []).length === 0 && (
            <p className="px-4 py-8 text-center text-xs text-ink-soft" data-testid="customers-empty">
              {t('admin.customers.empty')}
            </p>
          )}
        </div>

        {selected && (
          <section className="mt-6 rounded-lg border border-line bg-white p-5" data-testid="customer-detail">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-base font-semibold text-ink">
                {t('admin.customers.detailTitle', { name: selected.name })}
              </h2>
              {quotaSummary && (
                <span className="text-xs text-ink-soft" data-testid="customer-quota-state">
                  {t('admin.customers.quotaLabel')}：{quotaSummary}
                </span>
              )}
            </div>

            <h3 className="mt-4 text-xs font-medium text-ink-soft">
              {t('admin.customers.identitiesTitle')}
            </h3>
            <p className="mt-1 text-[11px] leading-relaxed text-ink-soft">
              {t('admin.customers.identitiesHint')}
            </p>
            {identities === null ? (
              <p className="mt-2 text-xs text-ink-soft">{t('admin.common.loading')}</p>
            ) : (
              <ul className="mt-2 divide-y divide-line rounded border border-line">
                {identities.identities.map((binding) => (
                  <li key={binding.id} className="flex items-center gap-3 px-3 py-2 text-xs">
                    <span className="font-mono">{binding.identity}</span>
                    {binding.note && <span className="text-ink-soft">{binding.note}</span>}
                    <button
                      type="button"
                      data-testid={`identity-unbind-${binding.id}`}
                      onClick={() => void submitUnbind(binding.id)}
                      className="ml-auto text-seal underline-offset-2 hover:underline"
                    >
                      {t('admin.customers.unbind')}
                    </button>
                  </li>
                ))}
                {identities.identities.length === 0 && (
                  <li className="px-3 py-2 text-xs text-ink-soft">
                    {t('admin.customers.noIdentities')}
                  </li>
                )}
              </ul>
            )}
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <input
                data-testid="identity-input"
                value={identityDraft}
                onChange={(event) => setIdentityDraft(event.target.value)}
                placeholder={t('admin.customers.identityPlaceholder')}
                className="w-64 rounded border border-line-strong bg-white px-2 py-1.5 text-sm"
              />
              <button
                type="button"
                data-testid="identity-bind"
                disabled={!identityDraft.trim()}
                onClick={() => void submitBind()}
                className="rounded-md border border-field px-3 py-1.5 text-xs text-field hover:bg-mist disabled:opacity-50"
              >
                {t('admin.customers.bind')}
              </button>
              <span className="text-[11px] text-ink-soft">
                {t('admin.customers.meteringIdentities', {
                  identities:
                    identities?.metering_identities.join(', ') ?? selected.sub2api_user_id ?? '—',
                })}
              </span>
            </div>
          </section>
        )}
      </AdminState>
    </div>
  )
}

export default CustomersPage