// 运营后台布局：左侧栏（客户/套餐/账本/用量/凭据）+ 顶栏（鉴权方式与令牌）。
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'

export type AdminSection = 'customers' | 'plans' | 'ledger' | 'usage' | 'credentials'

export const ADMIN_SECTIONS: ReadonlyArray<{ id: AdminSection; to: string; labelKey: string }> = [
  { id: 'customers', to: '/admin', labelKey: 'admin.nav.customers' },
  { id: 'plans', to: '/admin/plans', labelKey: 'admin.nav.plans' },
  { id: 'ledger', to: '/admin/ledger', labelKey: 'admin.nav.ledger' },
  { id: 'usage', to: '/admin/usage', labelKey: 'admin.nav.usage' },
  { id: 'credentials', to: '/admin/credentials', labelKey: 'admin.nav.credentials' },
]

export function AdminLayout({
  active,
  authLabel,
  authHint,
  onLogout,
  children,
}: {
  active: AdminSection
  authLabel: string
  authHint?: string
  onLogout?: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-0 px-6 py-10 lg:grid-cols-12">
      <aside className="lg:col-span-3">
        <div className="rounded-lg border border-line bg-white">
          <div className="border-b border-line px-5 py-4">
            <p className="font-display text-lg font-semibold text-ink">{t('admin.title')}</p>
            <p className="mt-1 break-all text-[11px] text-ink-soft" data-testid="admin-auth-label">
              {authLabel}
            </p>
          </div>
          <nav className="flex flex-col py-2" data-testid="admin-nav">
            {ADMIN_SECTIONS.map((section) => (
              <NavLink
                key={section.id}
                to={section.to}
                end={section.id === 'customers'}
                data-testid={`admin-nav-${section.id}`}
                className={({ isActive }) =>
                  `border-l-2 px-5 py-2.5 text-sm transition-colors ${
                    isActive || active === section.id
                      ? 'border-field bg-mist font-medium text-field'
                      : 'border-transparent text-ink-soft hover:bg-paper hover:text-ink'
                  }`
                }
              >
                {t(section.labelKey)}
              </NavLink>
            ))}
          </nav>
          {onLogout && (
            <div className="border-t border-line px-5 py-4">
              <button
                type="button"
                data-testid="admin-logout"
                onClick={onLogout}
                className="text-xs text-ink-soft underline-offset-2 hover:text-seal hover:underline"
              >
                {t('admin.exit')}
              </button>
            </div>
          )}
        </div>
        {authHint && (
          <p className="mt-4 rounded-md border border-line bg-white/60 p-3 text-[11px] leading-relaxed text-ink-soft">
            {authHint}
          </p>
        )}
      </aside>
      <section className="mt-8 min-w-0 lg:col-span-9 lg:mt-0 lg:pl-8">{children}</section>
    </div>
  )
}

export function AdminPageHeader({
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

export function AdminState({
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
  // 错误优先于加载态：请求失败必须如实呈现，不能永远停在「加载中」。
  if (error) {
    const auth = error.status === 401 || error.status === 403
    return (
      <div
        data-testid={auth ? 'admin-auth-error' : 'admin-error'}
        className="mt-8 rounded-md border border-seal/30 bg-seal-soft/60 p-4"
      >
        <p className="text-sm font-medium text-seal">
          {auth ? t('admin.error.authTitle') : t('admin.error.title')}
        </p>
        <p className="mt-1 break-all text-xs text-ink-soft" data-testid="admin-error-detail">
          {error.detail ?? error.message}
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded border border-seal/40 px-2 py-0.5 text-xs text-seal hover:bg-white"
          >
            {t('admin.error.retry')}
          </button>
        )}
      </div>
    )
  }
  if (loading) {
    return (
      <p className="mt-8 text-xs text-ink-soft" data-testid="admin-loading">
        {t('admin.common.loading')}
      </p>
    )
  }
  if (empty) {
    return (
      <div
        data-testid="admin-empty"
        className="mt-8 rounded-lg border border-dashed border-line-strong p-8 text-center"
      >
        <p className="text-sm text-ink-soft">{t(emptyKey ?? 'admin.common.empty')}</p>
      </div>
    )
  }
  return <>{children}</>
}

export default AdminLayout