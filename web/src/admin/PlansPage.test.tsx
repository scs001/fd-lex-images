// 后台套餐页：编辑器保存（PUT 载荷含按单位配额，调价不发版）+ 列表回显。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import { TEST_ADMIN_TOKEN, installAdminBackend } from './testing'
import { PlansPage } from './PlansPage'
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
      <PlansPage auth={AUTH} />
    </MemoryRouter>,
  )
}

describe('PlansPage', () => {
  it('loads plans and edits an existing one into the form', async () => {
    const backend = installAdminBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByText('standard')).toBeTruthy()
    fireEvent.click(screen.getByTestId('plan-edit-standard'))
    expect((screen.getByTestId('plan-name') as HTMLInputElement).value).toBe('标准版')
    expect((screen.getByTestId('plan-monthly') as HTMLInputElement).value).toBe('2')
  })

  it('saves an upsert with micro-unit conversion for price and quota', async () => {
    const backend = installAdminBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    await screen.findByText('standard')
    fireEvent.click(screen.getByTestId('plan-edit-standard'))
    fireEvent.change(screen.getByTestId('plan-monthly'), { target: { value: '12.5' } })
    fireEvent.change(screen.getByTestId('plan-quota-included-0'), { target: { value: '2000' } })
    fireEvent.change(screen.getByTestId('plan-quota-overage-0'), { target: { value: '0.003' } })
    fireEvent.click(screen.getByTestId('plan-save'))

    await waitFor(() => {
      expect(backend.calls.some((call) => call.method === 'PUT')).toBe(true)
    })
    const putCall = backend.calls.find((call) => call.method === 'PUT')
    expect(putCall?.url.pathname).toBe('/api/admin/plans/standard')
    expect(putCall?.body).toMatchObject({
      name: '标准版',
      monthly_price_micro: 12_500_000,
      is_active: true,
      quotas: [{ unit: 'line', included_quantity: 2000, overage_unit_price_micro: 3000 }],
    })
    expect(await screen.findByTestId('plan-notice')).toBeTruthy()
  })
})