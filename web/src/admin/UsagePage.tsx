// 后台用量视图：metering_records 按（轨道×调用者×单位）聚合（周期过滤）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AdminPageHeader, AdminState } from './AdminLayout'
import {
  AdminApiError,
  type AdminAuth,
  type AdminUsageOverview,
  fetchUsageOverview,
} from './api'

function currentPeriod(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function UsagePage({ auth }: { auth: AdminAuth }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState(currentPeriod())
  const [track, setTrack] = useState('')
  const [data, setData] = useState<AdminUsageOverview | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(
        await fetchUsageOverview(auth, {
          period,
          credential_track: track || undefined,
        }),
      )
    } catch (err) {
      setError(err as AdminApiError)
    }
  }, [auth, period, track])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      <AdminPageHeader
        titleKey="admin.usage.title"
        subtitleKey="admin.usage.subtitle"
        extra={
          <div className="flex flex-wrap items-center gap-3 text-xs text-ink-soft">
            <label className="flex items-center gap-2">
              {t('admin.usage.trackLabel')}
              <select
                data-testid="usage-track"
                value={track}
                onChange={(event) => setTrack(event.target.value)}
                className="rounded border border-line-strong bg-white px-2 py-1 text-xs"
              >
                <option value="">{t('admin.usage.allTracks')}</option>
                <option value="customer">customer</option>
                <option value="platform">platform</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              {t('console.common.periodLabel')}
              <input
                type="month"
                data-testid="usage-period"
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                className="rounded border border-line-strong bg-white px-2 py-1 text-xs"
              />
            </label>
          </div>
        }
      />
      <AdminState
        loading={data === null && error === null}
        error={error}
        onRetry={() => void load()}
      >
        {data && (
          <>
            <dl className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('admin.usage.totalCalls')}</dt>
                <dd className="mt-1.5 font-display text-xl tabular-nums text-ink" data-testid="admin-usage-calls">
                  {data.totals.calls.toLocaleString()}
                </dd>
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('admin.usage.byTrack')}</dt>
                <dd className="mt-1.5 space-y-1 text-xs text-ink">
                  {Object.entries(data.totals.by_track).map(([key, value]) => (
                    <span key={key} className="block">
                      {key} · {value.toLocaleString()}
                    </span>
                  ))}
                  {Object.keys(data.totals.by_track).length === 0 && '—'}
                </dd>
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <dt className="text-xs text-ink-soft">{t('admin.usage.byUnit')}</dt>
                <dd className="mt-1.5 space-y-1 text-xs text-ink">
                  {Object.entries(data.totals.by_unit).map(([unit, quantity]) => (
                    <span key={unit} className="block">
                      {unit} · {quantity.toLocaleString()}
                    </span>
                  ))}
                  {Object.keys(data.totals.by_unit).length === 0 && '—'}
                </dd>
              </div>
            </dl>

            <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
              <table className="w-full text-sm">
                <thead className="bg-paper text-left text-xs text-ink-soft">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">{t('admin.usage.colTrack')}</th>
                    <th className="px-4 py-2.5 font-medium">{t('admin.usage.colCaller')}</th>
                    <th className="px-4 py-2.5 font-medium">{t('console.common.unit')}</th>
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
                      key={`${row.credential_track}:${row.caller}:${row.unit}`}
                      className="border-t border-line"
                      data-testid="admin-usage-row"
                    >
                      <td className="px-4 py-2.5 text-xs">{row.credential_track}</td>
                      <td className="px-4 py-2.5 font-mono text-xs">{row.caller}</td>
                      <td className="px-4 py-2.5 font-mono text-xs">{row.unit}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {row.calls.toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {row.quantity.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {data.breakdown.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-xs text-ink-soft">
                        {t('admin.usage.empty')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[11px] text-ink-soft">{t('admin.usage.footnote')}</p>
          </>
        )}
      </AdminState>
    </div>
  )
}

export default UsagePage