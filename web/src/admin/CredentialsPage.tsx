// 后台凭据留痕：经 lex 控制台代理发生的铸造/吊销事件（明文与哈希均不落库）。
// 实时权威列表在 registry /api/patch-keys（以持钥人身份查询）；本页如实标注边界。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AdminPageHeader, AdminState } from './AdminLayout'
import {
  AdminApiError,
  type AdminAuth,
  type AdminCredentialEvent,
  fetchCredentialEvents,
} from './api'

export function CredentialsPage({ auth }: { auth: AdminAuth }) {
  const { t } = useTranslation()
  const [events, setEvents] = useState<AdminCredentialEvent[] | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const [username, setUsername] = useState('')

  const load = useCallback(async () => {
    setError(null)
    setEvents(null)
    try {
      const body = await fetchCredentialEvents(auth, {
        username: username.trim() || undefined,
      })
      setEvents(body.events)
      setNote(body.note)
    } catch (err) {
      setError(err as AdminApiError)
    }
  }, [auth, username])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      <AdminPageHeader
        titleKey="admin.credentials.title"
        subtitleKey="admin.credentials.subtitle"
        extra={
          <label className="flex items-center gap-2 text-xs text-ink-soft">
            {t('admin.credentials.usernameLabel')}
            <input
              data-testid="credential-events-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="lexdemocustomer"
              className="rounded border border-line-strong bg-white px-2 py-1 font-mono text-xs"
            />
          </label>
        }
      />
      <AdminState
        loading={events === null}
        error={error}
        empty={(events ?? []).length === 0}
        emptyKey="admin.credentials.empty"
        onRetry={() => void load()}
      >
        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colTime')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colAction')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colUser')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colKey')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colGroups')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.credentials.colDetail')}</th>
              </tr>
            </thead>
            <tbody>
              {(events ?? []).map((event) => (
                <tr key={event.id} className="border-t border-line" data-testid="credential-event-row">
                  <td className="px-4 py-2.5 font-mono text-[11px] text-ink-soft">
                    {event.created_at ? event.created_at.replace('T', ' ').slice(0, 19) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-xs">{event.action}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{event.username}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {event.key_name ?? '—'}
                    {event.key_prefix && (
                      <span className="ml-1 font-mono text-[11px] text-ink-soft">
                        {event.key_prefix}…
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-soft">
                    {event.groups.join(', ') || '—'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-seal">{event.detail ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {note && <p className="mt-3 text-[11px] leading-relaxed text-ink-soft">{note}</p>}
      </AdminState>
    </div>
  )
}

export default CredentialsPage