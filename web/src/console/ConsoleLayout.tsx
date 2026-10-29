// 控制台布局：左侧栏（总览/凭据/用量/账单/额度）+ 顶栏（登录身份 + 退出）。
// 设计语言沿用识律法典蓝/纸色/台账行式；标题用宋体 display 字体。
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink } from 'react-router-dom'
import { WanxingCopilot } from './WanxingCopilot'

export type ConsoleTab = 'overview' | 'credentials' | 'usage' | 'billing' | 'quota'

export const CONSOLE_TABS: ReadonlyArray<{ id: ConsoleTab; to: string; labelKey: string }> = [
  { id: 'overview', to: '/console', labelKey: 'console.nav.overview' },
  { id: 'credentials', to: '/console/credentials', labelKey: 'console.nav.credentials' },
  { id: 'usage', to: '/console/usage', labelKey: 'console.nav.usage' },
  { id: 'billing', to: '/console/billing', labelKey: 'console.nav.billing' },
  { id: 'quota', to: '/console/quota', labelKey: 'console.nav.quota' },
]

export function ConsoleLayout({
  active,
  identity,
  organization,
  isAdmin,
  onLogout,
  children,
}: {
  active: ConsoleTab
  identity: string
  organization: string | null
  isAdmin: boolean
  onLogout: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-0 px-6 py-10 lg:grid-cols-12">
      <aside className="lg:col-span-3">
        <div className="rounded-lg border border-line bg-white">
          <div className="border-b border-line px-5 py-4">
            <p className="font-display text-lg font-semibold text-ink">{t('console.title')}</p>
            <p className="mt-1 font-mono text-xs text-ink-soft" data-testid="console-identity">
              {identity}
            </p>
            {organization && (
              <p className="mt-0.5 text-[11px] text-ink-soft">{organization}</p>
            )}
          </div>
          <nav className="flex flex-col py-2" data-testid="console-nav">
            {CONSOLE_TABS.map((tab) => (
              <NavLink
                key={tab.id}
                to={tab.to}
                end={tab.id === 'overview'}
                data-testid={`console-nav-${tab.id}`}
                className={({ isActive }) =>
                  `border-l-2 px-5 py-2.5 text-sm transition-colors ${
                    isActive || active === tab.id
                      ? 'border-field bg-mist font-medium text-field'
                      : 'border-transparent text-ink-soft hover:bg-paper hover:text-ink'
                  }`
                }
              >
                {t(tab.labelKey)}
              </NavLink>
            ))}
          </nav>
          <div className="border-t border-line px-5 py-4">
            {isAdmin && (
              <Link
                to="/admin"
                data-testid="console-admin-link"
                className="block text-xs text-field underline-offset-2 hover:underline"
              >
                {t('console.adminLink')}
              </Link>
            )}
            <button
              type="button"
              data-testid="console-logout"
              onClick={onLogout}
              className="mt-2 text-xs text-ink-soft underline-offset-2 hover:text-seal hover:underline"
            >
              {t('console.logout')}
            </button>
          </div>
        </div>

        <p className="mt-4 rounded-md border border-line bg-white/60 p-3 text-[11px] leading-relaxed text-ink-soft">
          {t('console.credentialProxyNote')}
        </p>
      </aside>

      <section className="mt-8 min-w-0 lg:col-span-9 lg:mt-0 lg:pl-8">{children}</section>
      <WanxingCopilot />
    </div>
  )
}

/** 页面标题 + 说明（台账页统一头）。 */
export function ConsolePageHeader({
  titleKey,
  subtitleKey,
  extra,
}: {
  titleKey: string
  subtitleKey?: string
  extra?: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-5">
      <div>
        <h1 className="font-display text-2xl font-semibold text-ink">{t(titleKey)}</h1>
        {subtitleKey && (
          <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-ink-soft">
            {t(subtitleKey)}
          </p>
        )}
      </div>
      {extra}
    </div>
  )
}

/** 统一加载 / 空态 / 错误（错误如实呈现 status 与 detail，不吞）。 */
export function ConsoleState({
  loading,
  error,
  empty,
  emptyKey,
  onRetry,
  children,
}: {
  loading: boolean
  error: { status?: number; message: string; detail?: string } | null
  empty?: boolean
  emptyKey?: string
  onRetry?: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  // 错误优先于加载态：请求失败必须如实呈现，不能停在「加载中」。
  if (error) {
    const auth = error.status === 401 || error.status === 403
    return (
      <div
        data-testid={auth ? 'console-auth-error' : 'console-error'}
        className="mt-8 rounded-md border border-seal/30 bg-seal-soft/60 p-4"
      >
        <p className="text-sm font-medium text-seal">
          {auth ? t('console.error.authTitle') : t('console.error.title')}
        </p>
        <p className="mt-1 break-all text-xs text-ink-soft" data-testid="console-error-detail">
          {error.detail ?? error.message}
        </p>
        {auth && <p className="mt-1 text-xs text-ink-soft">{t('console.error.authHint')}</p>}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded border border-seal/40 px-2 py-0.5 text-xs text-seal hover:bg-white"
          >
            {t('console.error.retry')}
          </button>
        )}
      </div>
    )
  }
  if (loading) {
    return (
      <p className="mt-8 text-xs text-ink-soft" data-testid="console-loading">
        {t('console.common.loading')}
      </p>
    )
  }
  if (empty) {
    return (
      <div
        data-testid="console-empty"
        className="mt-8 rounded-lg border border-dashed border-line-strong p-8 text-center"
      >
        <p className="text-sm text-ink-soft">{t(emptyKey ?? 'console.common.empty')}</p>
      </div>
    )
  }
  return <>{children}</>
}

/** 周期选择（YYYY-MM，默认当月）。 */
export function PeriodPicker({
  period,
  onChange,
}: {
  period: string
  onChange: (next: string) => void
}) {
  const { t } = useTranslation()
  return (
    <label className="flex items-center gap-2 text-xs text-ink-soft">
      {t('console.common.periodLabel')}
      <input
        type="month"
        data-testid="console-period"
        value={period}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-line-strong bg-white px-2 py-1 text-xs text-ink"
      />
    </label>
  )
}

export default ConsoleLayout