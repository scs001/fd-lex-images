// 后台客户页：列表（令牌头）/ 开户 / 身份绑定与计量身份展示。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import { TEST_ADMIN_TOKEN, installAdminBackend } from './testing'
import { CustomersPage } from './CustomersPage'
import type { AdminAuth } from './api'

const AUTH: AdminAuth = { kind: 'token', token: TEST_ADMIN_TOKEN }

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
      <CustomersPage auth={AUTH} />
    </MemoryRouter>,
  )
}

describe('CustomersPage', () => {
  it('lists customers with the admin token header', async () => {
    const backend = installAdminBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByText('识律演示客户')).toBeTruthy()
    const listCall = backend.calls.find((call) => call.url.pathname === '/api/admin/customers')
    expect(listCall?.headers['x-admin-token']).toBe(TEST_ADMIN_TOKEN)
  })

  it('shows the auth error state on 401', async () => {
    const backend = installAdminBackend({ forceStatus: 401, forceDetail: 'admin credentials required' })
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByTestId('admin-auth-error')).toBeTruthy()
    expect(screen.getByTestId('admin-error-detail').textContent).toBe('admin credentials required')
  })

  it('creates a customer and then binds a Logto identity', async () => {
    const backend = installAdminBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    fireEvent.change(await screen.findByTestId('customer-name'), {
      target: { value: '新客户' },
    })
    fireEvent.click(screen.getByTestId('customer-create'))
    expect(await screen.findByTestId('customer-notice')).toBeTruthy()
    const createCall = backend.calls.find((call) => call.method === 'POST')
    expect(createCall?.body).toEqual({ name: '新客户', plan_code: 'standard' })

    fireEvent.click(screen.getByTestId('customer-detail-1'))
    fireEvent.change(await screen.findByTestId('identity-input'), {
      target: { value: 'lexdemocustomer' },
    })
    fireEvent.click(screen.getByTestId('identity-bind'))
    await waitFor(() => {
      expect(backend.identities.length).toBe(1)
    })
    expect(backend.identities[0]!.identity).toBe('lexdemocustomer')
  })
})