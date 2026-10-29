// 运营后台入口：鉴权探测（Logto 管理员角色 → 内部令牌）+ 嵌套路由。
//
// 如实标注两条路径：
// - 控制台登录态若带管理员角色（ADMIN_ROLES），直接进入，无需令牌；
// - 否则显示内部令牌输入（X-Admin-Token），未配置服务端令牌时后端 fail-closed。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Route, Routes, useNavigate } from 'react-router-dom'

import Layout from '../components/Layout'
import { loadSession } from '../console/auth'
import { AdminLayout, type AdminSection } from './AdminLayout'
import CredentialsPage from './CredentialsPage'
import CustomersPage from './CustomersPage'
import LedgerPage from './LedgerPage'
import PlansPage from './PlansPage'
import UsagePage from './UsagePage'
import {
  AdminApiError,
  type AdminAuth,
  type WhoAmI,
  fetchWhoAmI,
  loadAdminToken,
  saveAdminToken,
} from './api'

type Gate =
  | { kind: 'probing' }
  | { kind: 'ready'; auth: AdminAuth; whoami: WhoAmI }
  | { kind: 'denied'; detail: string; hasSession: boolean }

function sectionFromPath(): AdminSection {
  const path = window.location.pathname
  if (path.startsWith('/admin/plans')) return 'plans'
  if (path.startsWith('/admin/ledger')) return 'ledger'
  if (path.startsWith('/admin/usage')) return 'usage'
  if (path.startsWith('/admin/credentials')) return 'credentials'
  return 'customers'
}

export function AdminApp() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [gate, setGate] = useState<Gate>({ kind: 'probing' })
  const [tokenDraft, setTokenDraft] = useState(loadAdminToken())

  const probe = useCallback(async (token: string) => {
    setGate({ kind: 'probing' })
    const session = loadSession()
    let sessionDenial: string | null = null
    if (session) {
      try {
        const whoami = await fetchWhoAmI({
          kind: 'session',
          idToken: session.idToken,
          identity: session.identity,
        })
        setGate({ kind: 'ready', auth: { kind: 'session', idToken: session.idToken, identity: whoami.identity }, whoami })
        return
      } catch (err) {
        const apiError = err as AdminApiError
        if (apiError.status !== 401 && apiError.status !== 403) {
          setGate({ kind: 'denied', detail: apiError.detail ?? apiError.message, hasSession: true })
          return
        }
        // 401/403 → 落到令牌路径继续尝试（角色不足属预期路径，detail 保留待显示）
        sessionDenial = `${apiError.status ?? ''} ${apiError.detail ?? apiError.message}`.trim()
      }
    }
    const saved = token.trim()
    if (saved) {
      try {
        const whoami = await fetchWhoAmI({ kind: 'token', token: saved })
        setGate({ kind: 'ready', auth: { kind: 'token', token: saved }, whoami })
        return
      } catch (err) {
        const apiError = err as AdminApiError
        setGate({
          kind: 'denied',
          detail: `${apiError.status ?? ''} ${apiError.detail ?? apiError.message}`.trim(),
          hasSession: Boolean(session),
        })
        return
      }
    }
    setGate({
      kind: 'denied',
      detail: sessionDenial ?? t('admin.gate.noCredentials'),
      hasSession: Boolean(session),
    })
  }, [t])

  useEffect(() => {
    void probe(loadAdminToken())
    // 仅首挂载探测；令牌变更走显式提交
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submitToken = () => {
    const normalized = saveAdminToken(tokenDraft)
    setTokenDraft(normalized)
    void probe(normalized)
  }

  const exit = () => {
    saveAdminToken('')
    navigate('/console')
  }

  if (gate.kind === 'probing') {
    return (
      <Layout>
        <p className="mx-auto mt-20 text-sm text-ink-soft" data-testid="admin-loading">
          {t('admin.common.loading')}
        </p>
      </Layout>
    )
  }

  if (gate.kind === 'denied') {
    return (
      <Layout>
        <div
          data-testid="admin-gate"
          className="mx-auto mt-16 max-w-xl rounded-lg border border-line bg-white p-8"
        >
          <h1 className="font-display text-2xl font-semibold text-ink">
            {t('admin.gate.title')}
          </h1>
          <p className="mt-3 text-xs leading-relaxed text-ink-soft" data-testid="admin-gate-detail">
            {gate.detail}
          </p>

          <label className="mt-6 block text-xs text-ink-soft">
            {t('admin.gate.tokenLabel')}
            <input
              data-testid="admin-token-input"
              value={tokenDraft}
              onChange={(event) => setTokenDraft(event.target.value)}
              type="password"
              className="mt-1 block w-full rounded border border-line-strong bg-white px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              data-testid="admin-token-submit"
              onClick={submitToken}
              className="rounded-md bg-field px-4 py-2 text-sm text-white transition-colors hover:bg-field-deep"
            >
              {t('admin.gate.tokenSubmit')}
            </button>
            {gate.hasSession && (
              <span className="text-[11px] text-ink-soft">{t('admin.gate.roleHint')}</span>
            )}
            <Link
              to="/console"
              className="ml-auto text-xs text-field underline-offset-2 hover:underline"
            >
              {t('admin.gate.backToConsole')}
            </Link>
          </div>
          <p className="mt-4 text-[11px] leading-relaxed text-ink-soft">
            {t('admin.gate.hint')}
          </p>
        </div>
      </Layout>
    )
  }

  const { auth, whoami } = gate
  const authLabel =
    whoami.via === 'logto-role'
      ? `${t('admin.auth.viaRole')} · ${whoami.identity} · ${whoami.roles.join(', ')}`
      : t('admin.auth.viaToken')

  return (
    <Layout>
      <AdminLayout active={sectionFromPath()} authLabel={authLabel} onLogout={exit}>
        <Routes>
          <Route index element={<CustomersPage auth={auth} />} />
          <Route path="plans" element={<PlansPage auth={auth} />} />
          <Route path="ledger" element={<LedgerPage auth={auth} />} />
          <Route path="usage" element={<UsagePage auth={auth} />} />
          <Route
            path="credentials"
            element={<CredentialsPage auth={auth} />}
          />
        </Routes>
      </AdminLayout>
    </Layout>
  )
}

export default AdminApp