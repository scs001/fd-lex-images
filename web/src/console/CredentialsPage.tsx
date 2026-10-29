// 控制台凭据管理：铸造 / 列表 / 吊销（经 lex API 代理 registry patch-keys）。
// 明文仅铸造响应中出现一次；吊销即时生效（registry 侧下一次调用 401）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ConsolePageHeader, ConsoleState } from './ConsoleLayout'
import {
  ConsoleApiError,
  fetchCredentialEvents,
  fetchCredentials,
  mintCredential,
  revokeCredential,
  type CredentialEvent,
  type MintedKey,
  type RegistryKey,
} from './api'
import type { ConsoleSession } from './auth'

export function CredentialsPage({ session }: { session: ConsoleSession }) {
  const { t } = useTranslation()
  const [keys, setKeys] = useState<RegistryKey[] | null>(null)
  const [events, setEvents] = useState<CredentialEvent[]>([])
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const [name, setName] = useState('')
  const [minting, setMinting] = useState(false)
  const [minted, setMinted] = useState<MintedKey | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    setKeys(null)
    try {
      const [list, eventResp] = await Promise.all([
        fetchCredentials(session),
        fetchCredentialEvents(session),
      ])
      setKeys(list.items)
      setEvents(eventResp.events)
    } catch (err) {
      setError(err as ConsoleApiError)
    }
  }, [session])

  useEffect(() => {
    void load()
  }, [load])

  const submitMint = async () => {
    if (!name.trim() || minting) return
    setMinting(true)
    setNotice(null)
    try {
      const created = await mintCredential(session, name.trim())
      setMinted(created)
      setCopied(false)
      setName('')
      await load()
    } catch (err) {
      setError(err as ConsoleApiError)
    } finally {
      setMinting(false)
    }
  }

  const submitRevoke = async (key: RegistryKey) => {
    if (!window.confirm(t('console.credentials.revokeConfirm', { name: key.name }))) return
    setNotice(null)
    try {
      await revokeCredential(session, key.key_id)
      setNotice(t('console.credentials.revokedNotice', { name: key.name }))
      await load()
    } catch (err) {
      setError(err as ConsoleApiError)
    }
  }

  const copyKey = async () => {
    if (!minted) return
    try {
      await navigator.clipboard.writeText(minted.key)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div>
      <ConsolePageHeader
        titleKey="console.credentials.title"
        subtitleKey="console.credentials.subtitle"
      />

      <div className="mt-6 rounded-lg border border-line bg-white p-5">
        <h2 className="font-display text-base font-semibold text-ink">
          {t('console.credentials.mintTitle')}
        </h2>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-soft">
            {t('console.credentials.nameLabel')}
            <input
              data-testid="credential-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t('console.credentials.namePlaceholder')}
              className="mt-1 block w-64 rounded border border-line-strong bg-white px-2 py-1.5 text-sm text-ink"
            />
          </label>
          <button
            type="button"
            data-testid="credential-mint"
            disabled={minting || !name.trim()}
            onClick={() => void submitMint()}
            className="rounded-md bg-field px-4 py-2 text-sm text-white transition-colors hover:bg-field-deep disabled:opacity-50"
          >
            {minting ? t('console.credentials.minting') : t('console.credentials.mint')}
          </button>
          <span className="text-[11px] text-ink-soft">{t('console.credentials.mintHint')}</span>
        </div>

        {minted && (
          <div
            data-testid="credential-plaintext"
            className="mt-4 rounded-md border border-seal/30 bg-seal-soft/50 p-4"
          >
            <p className="text-xs font-medium text-seal">{t('console.credentials.plaintextTitle')}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="break-all rounded bg-white px-2 py-1 font-mono text-xs text-ink">
                {minted.key}
              </code>
              <button
                type="button"
                data-testid="credential-copy"
                onClick={() => void copyKey()}
                className="rounded border border-line-strong px-2 py-0.5 text-xs hover:bg-white"
              >
                {copied ? t('console.credentials.copied') : t('console.credentials.copy')}
              </button>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-soft">
              {t('console.credentials.plaintextHint')}
            </p>
          </div>
        )}

        {notice && (
          <p className="mt-3 text-xs text-field" data-testid="credential-notice">
            {notice}
          </p>
        )}
      </div>

      <ConsoleState loading={keys === null} error={error} onRetry={() => void load()}>
        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t('console.credentials.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.credentials.colKey')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.credentials.colGroups')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.credentials.colStatus')}</th>
                <th className="px-4 py-2.5 font-medium">{t('console.credentials.colLastUsed')}</th>
                <th className="px-4 py-2.5 text-right font-medium">
                  {t('console.credentials.colActions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {(keys ?? []).map((key) => (
                <tr key={key.key_id} className="border-t border-line" data-testid="credential-row">
                  <td className="px-4 py-2.5">{key.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{key.key_prefix}…</td>
                  <td className="px-4 py-2.5 text-xs text-ink-soft">{key.groups.join(', ') || '—'}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] ${
                        key.status === 'active'
                          ? 'border-field/30 bg-mist text-field'
                          : 'border-line-strong bg-paper text-ink-soft'
                      }`}
                    >
                      {key.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-soft">
                    {key.last_used_at ? key.last_used_at.replace('T', ' ').slice(0, 16) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {key.status === 'active' && (
                      <button
                        type="button"
                        data-testid={`credential-revoke-${key.key_id}`}
                        onClick={() => void submitRevoke(key)}
                        className="text-xs text-seal underline-offset-2 hover:underline"
                      >
                        {t('console.credentials.revoke')}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(keys ?? []).length === 0 && (
            <p className="px-4 py-8 text-center text-xs text-ink-soft" data-testid="credential-empty">
              {t('console.credentials.empty')}
            </p>
          )}
        </div>

        <section className="mt-8">
          <h2 className="font-display text-base font-semibold text-ink">
            {t('console.credentials.eventsTitle')}
          </h2>
          <p className="mt-1 text-[11px] text-ink-soft">{t('console.credentials.eventsHint')}</p>
          {events.length === 0 ? (
            <p className="mt-3 text-xs text-ink-soft">{t('console.credentials.eventsEmpty')}</p>
          ) : (
            <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-white">
              {events.map((event) => (
                <li key={event.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-xs">
                  <span className="font-mono text-ink-soft">
                    {event.created_at ? event.created_at.replace('T', ' ').slice(0, 16) : '—'}
                  </span>
                  <span className="font-medium text-ink">{event.action}</span>
                  <span>{event.key_name ?? event.key_id}</span>
                  {event.detail && <span className="text-seal">{event.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </ConsoleState>
    </div>
  )
}

export default CredentialsPage