// 后台账本：跨客户/单客户流水（周期过滤；金额口径 = lex 权威账本）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AdminPageHeader, AdminState } from './AdminLayout'
import {
  AdminApiError,
  type AdminAuth,
  type AdminLedgerEntry,
  fetchCustomers,
  fetchLedger,
  type AdminCustomer,
} from './api'

const KIND_KEYS: Record<string, string> = {
  grant: 'console.billing.kind.grant',
  overage: 'console.billing.kind.overage',
  hardstop: 'console.billing.kind.hardstop',
  adjustment: 'console.billing.kind.adjustment',
}

function currentPeriod(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function LedgerPage({ auth }: { auth: AdminAuth }) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<AdminLedgerEntry[] | null>(null)
  const [customers, setCustomers] = useState<AdminCustomer[]>([])
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const [customerId, setCustomerId] = useState('')
  const [period, setPeriod] = useState(currentPeriod())

  const load = useCallback(async () => {
    setError(null)
    setEntries(null)
    try {
      const ledger = await fetchLedger(auth, {
        customer_id: customerId ? Number(customerId) : undefined,
        period: period || undefined,
      })
      setEntries(ledger.entries)
    } catch (err) {
      setError(err as AdminApiError)
    }
  }, [auth, customerId, period])

  useEffect(() => {
    void load()
  }, [load])

  // 客户下拉一次加载（与账本过滤解耦，避免重复请求）
  useEffect(() => {
    let cancelled = false
    void fetchCustomers(auth)
      .then((listing) => {
        if (!cancelled) setCustomers(listing.customers)
      })
      .catch(() => {
        /* 下拉失败不阻塞账本主视图；错误由主视图如实呈现 */
      })
    return () => {
      cancelled = true
    }
  }, [auth])

  return (
    <div>
      <AdminPageHeader
        titleKey="admin.ledger.title"
        subtitleKey="admin.ledger.subtitle"
        extra={
          <div className="flex flex-wrap items-center gap-3 text-xs text-ink-soft">
            <label className="flex items-center gap-2">
              {t('admin.ledger.customerLabel')}
              <select
                data-testid="ledger-customer"
                value={customerId}
                onChange={(event) => setCustomerId(event.target.value)}
                className="rounded border border-line-strong bg-white px-2 py-1 text-xs"
              >
                <option value="">{t('admin.ledger.allCustomers')}</option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>
                    {customer.name}（#{customer.id}）
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2">
              {t('console.common.periodLabel')}
              <input
                type="month"
                data-testid="ledger-period"
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                className="rounded border border-line-strong bg-white px-2 py-1 text-xs"
              />
            </label>
          </div>
        }
      />
      <AdminState
        loading={entries === null}
        error={error}
        empty={(entries ?? []).length === 0}
        emptyKey="admin.ledger.empty"
        onRetry={() => void load()}
      >
        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t('admin.ledger.colCustomer')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.billing.colKind')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.common.unit')}</th>
                <th className="px-4 py-2.5 text-right font-medium">
                  {t('console.common.quantity')}
                </th>
                <th className="px-4 py-2.5 text-right font-medium">
                  {t('console.billing.colAmount')}
                </th>
                <th className="px-4 py-2.5 font-medium">{t('admin.ledger.colSettled')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.billing.colEntry')}</th>
              </tr>
            </thead>
            <tbody>
              {(entries ?? []).map((entry) => (
                <tr key={entry.id} className="border-t border-line" data-testid="ledger-row">
                  <td className="px-4 py-2.5 font-mono text-xs">#{entry.customer_id}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {KIND_KEYS[entry.kind] ? t(KIND_KEYS[entry.kind]) : entry.kind}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs">{entry.unit ?? '—'}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {entry.quantity.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{entry.amount_yuan}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-soft">
                    {entry.sub2api_applied ? t('admin.ledger.applied') : t('admin.ledger.notApplied')}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-ink-soft">
                    {entry.idempotency_key}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] text-ink-soft">{t('admin.ledger.footnote')}</p>
      </AdminState>
    </div>
  )
}

export default LedgerPage