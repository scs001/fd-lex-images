// 控制台入口：登录门禁（Logto PKCE）+ 嵌套路由 + 会话生命周期。
//
// 门禁三态如实呈现：
// - 服务端未配 Logto（/api/console/auth/config configured=false）→ 显示缺失项；
// - 未登录 → Logto 登录/注册按钮（注册在 Logto 托管页完成）；
// - 已登录但非 lex 客户组织（403）→ 原样显示 detail 与退出入口。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Route, Routes, useNavigate } from 'react-router-dom'

import Layout from '../components/Layout'
import { ConsoleLayout, type ConsoleTab } from './ConsoleLayout'
import BillingPage from './BillingPage'
import CredentialsPage from './CredentialsPage'
import OverviewPage from './OverviewPage'
import QuotaPage from './QuotaPage'
import UsagePage from './UsagePage'
import { ConsoleApiError, fetchMe, type MeResponse } from './api'
import {
  ConsoleAuthError,
  beginLogin,
  clearSession,
  completeLogin,
  fetchAuthConfig,
  isExpired,
  loadSession,
  logoutLocal,
  refreshSession,
  type ConsoleAuthConfig,
  type ConsoleSession,
} from './auth'

type Phase =
  | { kind: 'loading' }
  | { kind: 'no-config'; config: ConsoleAuthConfig }
  | { kind: 'config-error'; detail: string }
  | { kind: 'logged-out'; config: ConsoleAuthConfig | null }
  | { kind: 'auth-error'; detail: string; session: ConsoleSession }
  | { kind: 'ready'; session: ConsoleSession; me: MeResponse }

function ErrorPanel({ detail, testId }: { detail: string; testId: string }) {
  const { t } = useTranslation()
  return (
    <div
      data-testid={testId}
      className="mx-auto mt-16 max-w-xl rounded-lg border border-seal/30 bg-seal-soft/50 p-6"
    >
      <p className="font-display text-base font-semibold text-seal">{t('console.gate.errorTitle')}</p>
      <p className="mt-2 break-all text-xs leading-relaxed text-ink-soft">{detail}</p>
    </div>
  )
}

export function ConsoleApp() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })

  const startLogin = useCallback(async (config: ConsoleAuthConfig, returnTo = '/console') => {
    try {
      await beginLogin(config, returnTo)
    } catch (err) {
      setPhase({ kind: 'config-error', detail: (err as Error).message })
    }
  }, [])

  const boot = useCallback(async () => {
    let config: ConsoleAuthConfig
    try {
      config = await fetchAuthConfig()
    } catch (err) {
      setPhase({ kind: 'config-error', detail: (err as Error).message })
      return
    }
    if (!config.configured) {
      setPhase({ kind: 'no-config', config })
      return
    }

    // 回调路径：兑换 code → 落会话 → 回 returnTo
    if (window.location.pathname === '/console/callback') {
      try {
        const query = new URLSearchParams(window.location.search)
        const { returnTo } = await completeLogin(config, query)
        navigate(returnTo, { replace: true })
        return
      } catch (err) {
        const detail =
          err instanceof ConsoleAuthError
            ? `${err.message}${err.detail ? `：${err.detail}` : ''}`
            : (err as Error).message
        setPhase({ kind: 'logged-out', config })
        window.history.replaceState(null, '', '/console')
        setPhase({ kind: 'config-error', detail })
        return
      }
    }

    let session = loadSession()
    if (session && isExpired(session)) {
      session = await refreshSession(config, session)
      if (!session) clearSession()
    }
    if (!session) {
      setPhase({ kind: 'logged-out', config })
      return
    }
    try {
      const me = await fetchMe(session)
      setPhase({ kind: 'ready', session, me })
    } catch (err) {
      const apiError = err as ConsoleApiError
      setPhase({
        kind: 'auth-error',
        detail: `${apiError.status ?? ''} ${apiError.detail ?? apiError.message}`.trim(),
        session,
      })
    }
  }, [navigate])

  useEffect(() => {
    void boot()
  }, [boot])

  const logout = () => {
    logoutLocal()
    setPhase((current) =>
      current.kind === 'ready' || current.kind === 'auth-error'
        ? { kind: 'logged-out', config: null }
        : current,
    )
    // 重新拉配置恢复登录按钮
    void fetchAuthConfig()
      .then((config) => setPhase({ kind: 'logged-out', config }))
      .catch(() => setPhase({ kind: 'logged-out', config: null }))
  }

  if (phase.kind === 'loading') {
    return (
      <Layout>
        <p className="mx-auto mt-20 text-sm text-ink-soft" data-testid="console-loading">
          {t('console.common.loading')}
        </p>
      </Layout>
    )
  }

  if (phase.kind === 'config-error') {
    return (
      <Layout>
        <ErrorPanel detail={phase.detail} testId="console-config-error" />
      </Layout>
    )
  }

  if (phase.kind === 'no-config') {
    return (
      <Layout>
        <div
          data-testid="console-login-blocked"
          className="mx-auto mt-16 max-w-xl rounded-lg border border-line bg-white p-8"
        >
          <h1 className="font-display text-xl font-semibold text-ink">
            {t('console.gate.blockedTitle')}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">
            {t('console.gate.blockedBody')}
          </p>
          <ul className="mt-3 space-y-1 font-mono text-xs text-seal">
            {phase.config.missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-4 text-[11px] leading-relaxed text-ink-soft">
            {t('console.gate.blockedConfigHint')}
          </p>
        </div>
      </Layout>
    )
  }

  if (phase.kind === 'logged-out') {
    return (
      <Layout>
        <div
          data-testid="console-login"
          className="mx-auto mt-16 max-w-xl rounded-lg border border-line bg-white p-8"
        >
          <h1 className="font-display text-2xl font-semibold text-ink">
            {t('console.gate.loginTitle')}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">{t('console.gate.loginBody')}</p>
          {phase.config ? (
            <button
              type="button"
              data-testid="console-login-button"
              onClick={() => void startLogin(phase.config as ConsoleAuthConfig)}
              className="mt-6 rounded-md bg-field px-5 py-2.5 text-sm text-white transition-colors hover:bg-field-deep"
            >
              {t('console.gate.loginButton')}
            </button>
          ) : (
            <p className="mt-4 text-xs text-seal">{t('console.gate.loginUnavailable')}</p>
          )}
          <p className="mt-4 text-[11px] leading-relaxed text-ink-soft">
            {t('console.gate.loginHint')}
          </p>
        </div>
      </Layout>
    )
  }

  if (phase.kind === 'auth-error') {
    return (
      <Layout>
        <ErrorPanel detail={phase.detail} testId="console-auth-error" />
        <div className="mx-auto mt-4 max-w-xl text-center">
          <button
            type="button"
            onClick={logout}
            className="text-xs text-ink-soft underline-offset-2 hover:text-seal hover:underline"
          >
            {t('console.logout')}
          </button>
        </div>
      </Layout>
    )
  }

  const tabFromPath = (): ConsoleTab => {
    const path = window.location.pathname
    if (path.startsWith('/console/credentials')) return 'credentials'
    if (path.startsWith('/console/usage')) return 'usage'
    if (path.startsWith('/console/billing')) return 'billing'
    if (path.startsWith('/console/quota')) return 'quota'
    return 'overview'
  }

  return (
    <Layout>
      <ConsoleLayout
        active={tabFromPath()}
        identity={phase.me.identity}
        organization={phase.me.organizations[0] ?? null}
        isAdmin={phase.me.is_admin}
        onLogout={logout}
      >
        <Routes>
          <Route index element={<OverviewPage session={phase.session} />} />
          <Route
            path="credentials"
            element={<CredentialsPage session={phase.session} />}
          />
          <Route path="usage" element={<UsagePage session={phase.session} />} />
          <Route path="billing" element={<BillingPage session={phase.session} />} />
          <Route path="quota" element={<QuotaPage session={phase.session} />} />
        </Routes>
      </ConsoleLayout>
    </Layout>
  )
}

export default ConsoleApp