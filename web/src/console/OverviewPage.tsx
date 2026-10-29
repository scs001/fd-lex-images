// 控制台总览：客户档案 + 本期用量摘要 + 额度状态（登录后首屏）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ConsolePageHeader, ConsoleState } from './ConsoleLayout'
import {
  ConsoleApiError,
  currentPeriod,
  fetchMe,
  fetchQuota,
  fetchUsage,
  type MeResponse,
  type QuotaResponse,
  type UsageResponse,
} from './api'
import type { ConsoleSession } from './auth'

interface OverviewData {
  me: MeResponse
  usage: UsageResponse
  quota: QuotaResponse
}

export function OverviewPage({ session }: { session: ConsoleSession }) {
  const { t } = useTranslation()
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const period = currentPeriod()

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      const [me, usage, quota] = await Promise.all([
        fetchMe(session),
        fetchUsage(session, period),
        fetchQuota(session, period),
      ])
      setData({ me, usage, quota })
    } catch (err) {
      setError(err as ConsoleApiError)
    }
  }, [session, period])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      <ConsolePageHeader titleKey="console.overview.title" subtitleKey="console.overview.subtitle" />
      <ConsoleState
        loading={data === null && error === null}
        error={error}
        onRetry={() => void load()}
      >
        {data && (
          <div className="space-y-8">
            <dl className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.overview.customerLabel')}</dt>
                <dd className="mt-1.5 font-display text-lg text-ink" data-testid="overview-customer">
                  {data.me.customer ? data.me.customer.name : t('console.overview.noCustomer')}
                </dd>
                {data.me.customer && (
                  <dd className="mt-1 text-xs text-ink-soft">
                    {t('console.overview.planLabel')}：{data.me.customer.plan_name || '—'}
                  </dd>
                )}
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.overview.callsLabel')}</dt>
                <dd className="mt-1.5 font-display text-lg tabular-nums text-ink" data-testid="overview-calls">
                  {data.usage.totals.calls.toLocaleString()}
                </dd>
                <dd className="mt-1 text-xs text-ink-soft">{period}</dd>
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.overview.quotaLabel')}</dt>
                <dd
                  className={`mt-1.5 font-display text-lg ${data.quota.status?.allowed === false ? 'text-seal' : 'text-ink'}`}
                  data-testid="overview-quota"
                >
                  {data.quota.status
                    ? data.quota.status.allowed
                      ? t('console.quota.allowed')
                      : t('console.quota.blocked')
                    : t('console.overview.noCustomer')}
                </dd>
                {data.quota.status?.denial_reason && (
                  <dd className="mt-1 break-all font-mono text-[11px] text-seal">
                    {data.quota.status.denial_reason}
                  </dd>
                )}
              </div>
            </dl>

            <div className="grid gap-6 lg:grid-cols-2">
              <section className="rounded-lg border border-line bg-white p-5">
                <h2 className="font-display text-base font-semibold text-ink">
                  {t('console.overview.usageByUnit')}
                </h2>
                {Object.keys(data.usage.totals.by_unit).length === 0 ? (
                  <p className="mt-3 text-xs text-ink-soft">{t('console.overview.noUsage')}</p>
                ) : (
                  <table className="mt-3 w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-xs text-ink-soft">
                        <th className="py-2 font-medium">{t('console.common.unit')}</th>
                        <th className="py-2 text-right font-medium">
                          {t('console.common.quantity')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.usage.totals.by_unit).map(([unit, quantity]) => (
                        <tr key={unit} className="border-b border-line/70">
                          <td className="py-2 font-mono text-xs">{unit}</td>
                          <td className="py-2 text-right tabular-nums">
                            {quantity.toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <Link
                  to="/console/usage"
                  className="mt-3 inline-block text-xs text-field underline-offset-2 hover:underline"
                >
                  {t('console.overview.moreUsage')}
                </Link>
              </section>

              <section className="rounded-lg border border-line bg-white p-5">
                <h2 className="font-display text-base font-semibold text-ink">
                  {t('console.overview.quickLinks')}
                </h2>
                <ul className="mt-3 space-y-2 text-sm">
                  <li>
                    <Link
                      to="/console/credentials"
                      className="text-field underline-offset-2 hover:underline"
                    >
                      {t('console.overview.linkCredentials')}
                    </Link>
                  </li>
                  <li>
                    <Link
                      to="/console/billing"
                      className="text-field underline-offset-2 hover:underline"
                    >
                      {t('console.overview.linkBilling')}
                    </Link>
                  </li>
                  <li>
                    <Link
                      to="/console/quota"
                      className="text-field underline-offset-2 hover:underline"
                    >
                      {t('console.overview.linkQuota')}
                    </Link>
                  </li>
                </ul>
                {!data.me.customer && (
                  <p className="mt-3 rounded border border-line bg-paper p-2 text-[11px] leading-relaxed text-ink-soft">
                    {t('console.overview.unboundHint')}
                  </p>
                )}
              </section>
            </div>
          </div>
        )}
      </ConsoleState>
    </div>
  )
}

export default OverviewPage