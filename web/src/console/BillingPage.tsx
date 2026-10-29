// 控制台账单：本客户周期账本流水（lex 账本为权威口径）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ConsolePageHeader, ConsoleState, PeriodPicker } from './ConsoleLayout'
import { ConsoleApiError, currentPeriod, fetchBilling, type BillingResponse } from './api'
import type { ConsoleSession } from './auth'

const KIND_KEYS: Record<string, string> = {
  grant: 'console.billing.kind.grant',
  overage: 'console.billing.kind.overage',
  hardstop: 'console.billing.kind.hardstop',
  adjustment: 'console.billing.kind.adjustment',
}

export function BillingPage({ session }: { session: ConsoleSession }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState(currentPeriod())
  const [data, setData] = useState<BillingResponse | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(await fetchBilling(session, period))
    } catch (err) {
      setError(err as ConsoleApiError)
    }
  }, [session, period])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      <ConsolePageHeader
        titleKey="console.billing.title"
        subtitleKey="console.billing.subtitle"
        extra={<PeriodPicker period={period} onChange={setPeriod} />}
      />
      <ConsoleState loading={data === null && error === null} error={error} onRetry={() => void load()}>
        {data && data.customer === null && (
          <div
            data-testid="billing-unbound"
            className="mt-8 rounded-lg border border-dashed border-line-strong p-8 text-center"
          >
            <p className="text-sm text-ink">{t('console.billing.unboundTitle')}</p>
            <p className="mt-2 text-xs leading-relaxed text-ink-soft">
              {t('console.billing.unboundHint')}
            </p>
          </div>
        )}

        {data && data.customer !== null && (
          <>
            <dl className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.billing.customerLabel')}</dt>
                <dd className="mt-1.5 text-sm text-ink">{data.customer.name}</dd>
                <dd className="mt-1 text-xs text-ink-soft">
                  {t('console.overview.planLabel')}：{data.customer.plan_name || '—'}
                  {data.customer.monthly_price_yuan
                    ? ` · ${data.customer.monthly_price_yuan}`
                    : ''}
                </dd>
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.billing.totalLabel')}</dt>
                <dd className="mt-1.5 font-display text-xl tabular-nums text-ink" data-testid="billing-total">
                  {data.totals?.amount_yuan ?? '—'}
                </dd>
                <dd className="mt-1 text-[11px] text-ink-soft">{t('console.billing.totalHint')}</dd>
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.billing.byKindLabel')}</dt>
                <dd className="mt-1.5 space-y-1">
                  {data.totals && Object.keys(data.totals.by_kind).length > 0 ? (
                    Object.entries(data.totals.by_kind).map(([kind, value]) => (
                      <span key={kind} className="block text-xs text-ink">
                        {KIND_KEYS[kind] ? t(KIND_KEYS[kind]) : kind} · {value.amount_yuan}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-ink-soft">{t('console.billing.noEntries')}</span>
                  )}
                </dd>
              </div>
            </dl>

            <section className="mt-8">
              <h2 className="font-display text-base font-semibold text-ink">
                {t('console.billing.entriesTitle')}
              </h2>
              {data.entries.length === 0 ? (
                <p className="mt-3 text-xs text-ink-soft" data-testid="billing-empty">
                  {t('console.billing.noEntries')}
                </p>
              ) : (
                <div className="mt-3 overflow-hidden rounded-lg border border-line bg-white">
                  <table className="w-full text-sm">
                    <thead className="bg-paper text-left text-xs text-ink-soft">
                      <tr>
                        <th className="px-4 py-2.5 font-medium">{t('console.billing.colKind')}</th>
                        <th className="px-4 py-2.5 font-medium">{t('console.common.unit')}</th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          {t('console.common.quantity')}
                        </th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          {t('console.billing.colAmount')}
                        </th>
                        <th className="px-4 py-2.5 font-medium">{t('console.billing.colEntry')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.entries.map((entry) => (
                        <tr key={entry.id} className="border-t border-line" data-testid="billing-row">
                          <td className="px-4 py-2.5 text-xs">
                            {KIND_KEYS[entry.kind] ? t(KIND_KEYS[entry.kind]) : entry.kind}
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs">{entry.unit ?? '—'}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums">
                            {entry.quantity.toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{entry.amount_yuan}</td>
                          <td className="px-4 py-2.5 font-mono text-[11px] text-ink-soft">
                            {entry.idempotency_key}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-ink-soft">
                {t('console.billing.ledgerNote')}
              </p>
            </section>
          </>
        )}
      </ConsoleState>
    </div>
  )
}

export default BillingPage