// 控制台凭据页：列表（registry 代理）/ 铸造明文仅一次 / 吊销即时。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import { TEST_SESSION, installConsoleBackend } from './testing'
import { CredentialsPage } from './CredentialsPage'

beforeEach(() => {
  void i18n.changeLanguage('zh')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderPage() {
  return render(
    <MemoryRouter>
      <CredentialsPage session={TEST_SESSION} />
    </MemoryRouter>,
  )
}

describe('CredentialsPage', () => {
  it('lists registry keys and sends both identity and registry tokens', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByText('demo-key')).toBeTruthy()
    expect(screen.getByText(/wgk-Abc123/)).toBeTruthy()
    const listCall = backend.calls.find(
      (call) => call.method === 'GET' && call.url.pathname === '/api/console/credentials',
    )
    expect(listCall?.headers.authorization).toBe(`Bearer ${TEST_SESSION.idToken}`)
    expect(listCall?.headers['x-registry-token']).toBe(TEST_SESSION.accessToken)
  })

  it('shows the minted plaintext once and posts the name', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    const input = await screen.findByTestId('credential-name')
    fireEvent.change(input, { target: { value: '生产环境' } })
    fireEvent.click(screen.getByTestId('credential-mint'))

    const plaintext = await screen.findByTestId('credential-plaintext')
    expect(plaintext.textContent).toContain('wgk-PlaintextOnce123')
    const postCall = backend.calls.find((call) => call.method === 'POST')
    expect(postCall?.body).toEqual({ name: '生产环境' })
  })

  it('surfaces registry mint errors verbatim (429 detail)', async () => {
    const backend = installConsoleBackend({ mintStatus: 429, mintDetail: 'too many active keys' })
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    const input = await screen.findByTestId('credential-name')
    fireEvent.change(input, { target: { value: 'too-many' } })
    fireEvent.click(screen.getByTestId('credential-mint'))

    const error = await screen.findByTestId('console-error-detail')
    expect(error.textContent).toBe('too many active keys')
  })

  it('revokes a key after confirmation', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    vi.stubGlobal('confirm', vi.fn(() => true))
    renderPage()

    const button = await screen.findByTestId('credential-revoke-key-1')
    fireEvent.click(button)
    await waitFor(() => {
      expect(backend.calls.some((item) => item.method === 'DELETE')).toBe(true)
    })
    const deleteCall = backend.calls.find((item) => item.method === 'DELETE')
    expect(deleteCall?.url.pathname).toBe('/api/console/credentials/key-1')
    expect(await screen.findByTestId('credential-notice')).toBeTruthy()
  })
})