// 能力目录的电子签条目：保持如实标注——内测态（中性虚线徽标，不占用宿主点、
// 不把未开通说成可用）；已交付条目仍按真实宿主显示。中英两语结构一致。
import { cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import i18n from '../i18n'
import Home from './Home'

beforeEach(() => {
  void i18n.changeLanguage('zh')
})

afterEach(() => {
  cleanup()
})

function bodyText(): string {
  return document.body.textContent ?? ''
}

describe('Home capability catalog', () => {
  it('lists e-signature as in-preview with the honest note (zh)', () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    )
    const text = bodyText()
    expect(text).toContain('合同电子签署')
    expect(text).toContain('内测中 · 即将上线')
    expect(text).toContain('沙箱验证通过后开放云端与私有化签署')
    // esignature 无 host 字段：渲染面不得漏出未解析的 i18n key
    expect(text).not.toContain('capabilities.items.esignature')
  })

  it('lists e-signature as in-preview (en)', async () => {
    await i18n.changeLanguage('en')
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    )
    const text = bodyText()
    expect(text).toContain('Contract e-signature')
    expect(text).toContain('In preview · coming soon')
    expect(text).toContain('licensed e-signature provider')
    expect(text).not.toContain('capabilities.items.esignature')
  })

  it('keeps shipping capabilities with their real host badges', () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    )
    const text = bodyText()
    expect(text).toContain('双宿主') // 检索/合同等已上线能力
    expect(text).toContain('仅私有化') // 自有模型
  })
})
