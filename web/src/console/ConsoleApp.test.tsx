// 控制台门禁：登录未配置时的阻塞态、未登录时的登录入口、已登录时的导航。
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import i18n from '../i18n'
import { ConsoleApp } from './ConsoleApp'
import { SESSION_STORAGE_KEY } from './auth'
import { TEST_SESSION, installConsoleBackend } from './testing'

beforeEach(() => {
  void i18n.changeLanguage('zh')
  sessionStorage.clear()
  window.history.replaceState(null, '', '/console')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
})

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/console']}>
      <Routes>
        <Route path="/console/*" element={<ConsoleApp />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ConsoleApp gate', () => {
  it('shows the blocking panel with missing env vars when Logto is not configured', async () => {
    const backend = installConsoleBackend({ configMissing: true })
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderApp()

    expect(await screen.findByTestId('console-login-blocked')).toBeTruthy()
    expect(screen.getByText('LOGTO_ISSUER')).toBeTruthy()
    expect(screen.getByText('LOGTO_CLIENT_ID')).toBeTruthy()
  })

  it('shows the login entry when a session is absent', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderApp()

    expect(await screen.findByTestId('console-login')).toBeTruthy()
    expect(screen.getByTestId('console-login-button')).toBeTruthy()
  })

  it('renders the console shell with nav when a valid session exists', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(TEST_SESSION))
    renderApp()

    expect(await screen.findByTestId('console-nav')).toBeTruthy()
    expect(screen.getByTestId('console-identity').textContent).toBe('lexdemocustomer')
    expect((await screen.findByTestId('overview-customer')).textContent).toBe('识律演示客户')
  })

  it('surfaces a 403 organization denial verbatim', async () => {
    const backend = installConsoleBackend({ forbiddenDetail: 'not a lex customer: organization membership required' })
    vi.stubGlobal('fetch', backend.fetchImpl)
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(TEST_SESSION))
    renderApp()

    const panel = await screen.findByTestId('console-auth-error')
    expect(panel.textContent).toContain('not a lex customer')
  })
})