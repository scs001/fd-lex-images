// 控制台额度页：硬停判定 + 恢复途径；正常态不显示恢复动作。
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import { TEST_SESSION, installConsoleBackend } from './testing'
import { QuotaPage } from './QuotaPage'

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
      <QuotaPage session={TEST_SESSION} />
    </MemoryRouter>,
  )
}

describe('QuotaPage', () => {
  it('renders hard-stop state with recovery paths', async () => {
    const backend = installConsoleBackend()
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByTestId('quota-denial')).toHaveProperty(
      'textContent',
      'quota_exhausted:call',
    )
    expect(screen.getByTestId('quota-unit-call').textContent).toContain('100')
    // 恢复途径：升级额度 + 联系商务（i18n zh；两条恢复项都提到「联系商务」）
    expect(screen.getByText(/升级套餐/)).toBeTruthy()
    expect(screen.getAllByText(/联系商务/).length).toBeGreaterThan(0)
  })

  it('renders the healthy state without recovery actions', async () => {
    const backend = installConsoleBackend({ quotaAllowed: true })
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByTestId('quota-summary')).toBeTruthy()
    expect(screen.queryByTestId('quota-denial')).toBeNull()
    expect(screen.getByText(/当前无需恢复动作/)).toBeTruthy()
  })

  it('shows the unbound state when no billing customer is attached', async () => {
    const backend = installConsoleBackend({ unbound: true })
    vi.stubGlobal('fetch', backend.fetchImpl)
    renderPage()

    expect(await screen.findByTestId('quota-unbound')).toBeTruthy()
  })
})