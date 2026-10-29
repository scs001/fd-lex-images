// /deploy 页：中英双语结构对等（六个交付板块 + 三通道 + 范围三则），
// 且不残留未翻译的 i18n key。
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import Deploy from './Deploy'

beforeEach(() => {
  void i18n.changeLanguage('zh')
})

afterEach(() => {
  cleanup()
})

function bodyText(): string {
  return document.body.textContent ?? ''
}

describe('Deploy page', () => {
  it('renders the delivery sections in zh without raw keys', () => {
    render(
      <MemoryRouter>
        <Deploy />
      </MemoryRouter>,
    )
    const text = bodyText()
    expect(text).toContain('私有化交付')
    expect(text).toContain('部署形态')
    expect(text).toContain('离线环境')
    expect(text).toContain('数据三档')
    expect(text).toContain('整包安装')
    expect(text).toContain('离线通道')
    expect(text).not.toContain('docs.sections')
    expect(text).not.toContain('deploy.channels')
  })

  it('renders the same structure in en', async () => {
    await i18n.changeLanguage('en')
    render(
      <MemoryRouter>
        <Deploy />
      </MemoryRouter>,
    )
    const text = bodyText()
    expect(text).toContain('On-premise delivery')
    expect(text).toContain('Single bundle install')
    expect(text).toContain('Offline channel')
    expect(text).toContain('Acceptance')
    expect(text).not.toContain('deploy.')
    void i18n.changeLanguage('zh')
  })

  it('keeps the four site entries reachable from the footer', () => {
    render(
      <MemoryRouter>
        <Deploy />
      </MemoryRouter>,
    )
    const consoleLink = screen.getAllByRole('link', { name: '控制台' })[0]
    expect(consoleLink?.getAttribute('href')).toBe('/console')
    expect(screen.getByText('MCP 端点')).toBeTruthy()
    expect(screen.getAllByText('私有化交付').length).toBeGreaterThan(0)
  })
})