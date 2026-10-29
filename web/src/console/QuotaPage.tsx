// 控制台额度状态：逐单位水位 + 硬停判定 + 恢复途径。
// 状态语义与 registry 侧 402 预检同源（quota_status，fail-closed）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ConsolePageHeader, ConsoleState, PeriodPicker } from './ConsoleLayout'
import { ConsoleApiError, currentPeriod, fetchQuota, type QuotaResponse } from './api'
import type { ConsoleSession } from './auth'

const RECOVERY_KEYS: Record<string, string> = {
  upgrade_quota: 'console.quota.recovery.upgrade',
  top_up_balance: 'console.quota.recovery.topUp',
  billing_plane_unreachable: 'console.quota.recovery.unreachable',
  contact_sales: 'console.quota.recovery.contact',
  not_provisioned: 'console.quota.recovery.notProvisioned',
}

export function QuotaPage({ session }: { session: ConsoleSession }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState(currentPeriod())
  const [data, setData] = useState<QuotaResponse | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(await fetchQuota(session, period))
    } catch (err) {
      setError(err as ConsoleApiError)
    }
  }, [session, period])

  useEffect(() => {
    void load()
  }, [load])

  const status = data?.status ?? null

  return (
    <div>
      <ConsolePageHeader
        titleKey="console.quota.title"
        subtitleKey="console.quota.subtitle"
        extra={<PeriodPicker period={period} onChange={setPeriod} />}
      />
      <ConsoleState loading={data === null && error === null} error={error} onRetry={() => void load()}>
        {data && !status && (
          <div
            data-testid="quota-unbound"
            className="mt-8 rounded-lg border border-dashed border-line-strong p-8 text-center"
          >
            <p className="text-sm text-ink">{t('console.quota.unboundTitle')}</p>
            <p className="mt-2 text-xs leading-relaxed text-ink-soft">
              {t('console.quota.unboundHint')}
            </p>
          </div>
        )}

        {data && status && (
          <>
            <div
              data-testid="quota-summary"
              className={`mt-6 rounded-lg border p-4 ${
                status.allowed ? 'border-line bg-white' : 'border-seal/40 bg-seal-soft/60'
              }`}
            >
              <p className={`font-display text-lg ${status.allowed ? 'text-ink' : 'text-seal'}`}>
                {status.allowed ? t('console.quota.allowed') : t('console.quota.blocked')}
              </p>
              {status.denial_reason && (
                <p className="mt-1 break-all font-mono text-xs text-seal" data-testid="quota-denial">
                  {status.denial_reason}
                </p>
              )}
              {status.balance && (
                <p className="mt-2 text-xs text-ink-soft">
                  {t('console.quota.balanceLabel')}：
                  {status.balance.reachable
                    ? `¥${((status.balance.balance_micro ?? 0) / 1_000_000).toFixed(2)}`
                    : t('console.quota.balanceUnreachable')}
                  {status.balance.error ? `（${status.balance.error}）` : ''}
                </p>
              )}
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              {status.units.map((unit) => {
                const pct = Math.min(100, unit.used_pct)
                return (
                  <div
                    key={unit.unit}
                    data-testid={`quota-unit-${unit.unit}`}
                    className="rounded-lg border border-line bg-white p-4"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm text-ink">{unit.unit}</span>
                      {!unit.configured && (
                        <span className="rounded-full border border-line-strong px-2 py-0.5 text-[11px] text-ink-soft">
                          {t('console.quota.notConfigured')}
                        </span>
                      )}
                    </div>
                    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-mist">
                      <div
                        className={`h-full ${unit.used_pct >= 95 ? 'bg-seal' : unit.used_pct >= 80 ? 'bg-field' : 'bg-field/60'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <dl className="mt-3 grid grid-cols-3 gap-2 text-xs text-ink-soft">
                      <div>
                        <dt>{t('console.quota.used')}</dt>
                        <dd className="mt-0.5 tabular-nums text-ink">
                          {unit.used_quantity.toLocaleString()}
                        </dd>
                      </div>
                      <div>
                        <dt>{t('console.quota.included')}</dt>
                        <dd className="mt-0.5 tabular-nums text-ink">
                          {unit.included_quantity.toLocaleString()}
                        </dd>
                      </div>
                      <div>
                        <dt>{t('console.quota.remaining')}</dt>
                        <dd className="mt-0.5 tabular-nums text-ink">
                          {unit.remaining_quantity.toLocaleString()}
                        </dd>
                      </div>
                    </dl>
                    <p className="mt-2 text-[11px] text-ink-soft">
                      {t('console.quota.tiers', {
                        tiers: unit.tiers_hit.length ? unit.tiers_hit.join('% / ') + '%' : '—',
                      })}
                      {unit.overage_priced ? ` · ${t('console.quota.overagePriced')}` : ''}
                    </p>
                  </div>
                )
              })}
            </div>

            <section className="mt-8 rounded-lg border border-line bg-white p-5">
              <h2 className="font-display text-base font-semibold text-ink">
                {t('console.quota.recoveryTitle')}
              </h2>
              {data.recovery.length === 0 ? (
                <p className="mt-2 text-xs text-ink-soft">{t('console.quota.recoveryNone')}</p>
              ) : (
                <ul className="mt-3 space-y-2 text-sm text-ink">
                  {data.recovery.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-seal" />
                      <span>{RECOVERY_KEYS[item] ? t(RECOVERY_KEYS[item]) : item}</span>
                    </li>
                  ))}
                </ul>
              )}
              <Link
                to="/console/usage"
                className="mt-3 inline-block text-xs text-field underline-offset-2 hover:underline"
              >
                {t('console.overview.moreUsage')}
              </Link>
            </section>

            <p className="mt-4 text-[11px] leading-relaxed text-ink-soft">
              {t('console.quota.identitiesNote', { identities: data.identities.join(', ') })}
            </p>
          </>
        )}
      </ConsoleState>
    </div>
  )
}

export default QuotaPage