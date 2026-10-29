// 控制台用量：按周期查看本客户（含绑定身份）的调用与双单位数量。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ConsolePageHeader, ConsoleState, PeriodPicker } from './ConsoleLayout'
import { ConsoleApiError, currentPeriod, fetchUsage, type UsageResponse } from './api'
import type { ConsoleSession } from './auth'

export function UsagePage({ session }: { session: ConsoleSession }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState(currentPeriod())
  const [data, setData] = useState<UsageResponse | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(await fetchUsage(session, period))
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
        titleKey="console.usagePage.title"
        subtitleKey="console.usagePage.subtitle"
        extra={<PeriodPicker period={period} onChange={setPeriod} />}
      />
      <ConsoleState loading={data === null && error === null} error={error} onRetry={() => void load()}>
        {data && (
          <>
            <dl className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('console.usagePage.totalCalls')}</dt>
                <dd className="mt-1.5 font-display text-xl tabular-nums text-ink" data-testid="usage-calls">
                  {data.totals.calls.toLocaleString()}
                </dd>
              </div>
              {Object.entries(data.totals.by_unit).map(([unit, quantity]) => (
                <div key={unit} className="rounded-lg border border-line bg-white p-4">
                  <dt className="text-xs text-ink-soft">
                    {t('console.usagePage.quantityOf', { unit })}
                  </dt>
                  <dd className="mt-1.5 font-display text-xl tabular-nums text-ink">
                    {quantity.toLocaleString()}
                  </dd>
                </div>
              ))}
            </dl>

            <section className="mt-8">
              <h2 className="font-display text-base font-semibold text-ink">
                {t('console.usagePage.breakdownTitle')}
              </h2>
              {data.breakdown.length === 0 ? (
                <p className="mt-3 text-xs text-ink-soft" data-testid="usage-empty">
                  {t('console.usagePage.empty')}
                </p>
              ) : (
                <div className="mt-3 overflow-hidden rounded-lg border border-line bg-white">
                  <table className="w-full text-sm">
                    <thead className="bg-paper text-left text-xs text-ink-soft">
                      <tr>
                        <th className="px-4 py-2.5 font-medium">{t('console.common.unit')}</th>
                        <th className="px-4 py-2.5 font-medium">{t('console.usagePage.colServer')}</th>
                        <th className="px-4 py-2.5 font-medium">{t('console.usagePage.colTool')}</th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          {t('console.usagePage.colCalls')}
                        </th>
                        <th className="px-4 py-2.5 text-right font-medium">
                          {t('console.common.quantity')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.breakdown.map((row) => (
                        <tr
                          key={`${row.unit}:${row.server_name}:${row.tool_name ?? ''}`}
                          className="border-t border-line"
                          data-testid="usage-row"
                        >
                          <td className="px-4 py-2.5 font-mono text-xs">{row.unit}</td>
                          <td className="px-4 py-2.5 text-xs">{row.server_name}</td>
                          <td className="px-4 py-2.5 font-mono text-xs text-ink-soft">
                            {row.tool_name ?? '—'}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">
                            {row.calls.toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">
                            {row.quantity.toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="mt-8">
              <h2 className="font-display text-base font-semibold text-ink">
                {t('console.usagePage.recentTitle')}
              </h2>
              {data.recent.length === 0 ? (
                <p className="mt-3 text-xs text-ink-soft">{t('console.usagePage.empty')}</p>
              ) : (
                <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-white">
                  {data.recent.map((row, index) => (
                    <li
                      key={`${row.event_timestamp}:${index}`}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-xs"
                    >
                      <span className="font-mono text-ink-soft">
                        {row.event_timestamp.replace('T', ' ').slice(0, 16)}
                      </span>
                      <span>{row.server_name}</span>
                      <span className="font-mono text-ink-soft">{row.tool_name ?? '—'}</span>
                      <span className="ml-auto tabular-nums">
                        {row.quantity.toLocaleString()} {row.unit}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <p className="mt-6 text-[11px] leading-relaxed text-ink-soft">
              {t('console.usagePage.identitiesNote', { identities: data.identities.join(', ') })}
            </p>
          </>
        )}
      </ConsoleState>
    </div>
  )
}

export default UsagePage