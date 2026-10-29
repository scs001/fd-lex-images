// /docs 文档区：索引列出文档、未知 slug 给未找到态、文档页随语言切换、
// Markdown 渲染含标题与表格的样例 md、导航含文档入口。
// 文档标题断言取自 registry（内容侧可替换 md 正文，frontmatter 契约不变）。
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Markdown from '../components/Markdown'
import Layout from '../components/Layout'
import i18n from '../i18n'
import { getDoc, listDocs } from '../content/docs/registry'
import DocPage from './DocPage'
import DocsIndex from './DocsIndex'

beforeEach(() => {
  void i18n.changeLanguage('zh')
})

afterEach(() => {
  cleanup()
})

function renderRoutes(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/docs" element={<DocsIndex />} />
        <Route path="/docs/:slug" element={<DocPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const SAMPLE_MD = [
  '# 接入速览',
  '',
  '| 能力 | 宿主 |',
  '| --- | --- |',
  '| 法条语义检索 | 云端 · 私有化 |',
  '| 合同生成 | 私有化 |',
].join('\n')

describe('Docs pages', () => {
  it('lists both known documents on the index with their frontmatter titles', () => {
    renderRoutes('/docs')

    expect(listDocs('zh').length).toBeGreaterThanOrEqual(2)
    for (const slug of ['mcp-guide', 'contract-guide']) {
      const doc = getDoc('zh', slug)
      expect(doc).toBeTruthy()
      expect(screen.getByRole('heading', { name: doc!.title })).toBeTruthy()
      expect(screen.getByRole('link', { name: new RegExp(doc!.title) }).getAttribute('href')).toBe(
        `/docs/${slug}`,
      )
    }
  })

  it('serves the index in the current i18n language', async () => {
    await i18n.changeLanguage('en')
    renderRoutes('/docs')

    expect(screen.getByText('Lex documentation')).toBeTruthy()
    const mcp = getDoc('en', 'mcp-guide')
    expect(mcp).toBeTruthy()
    expect(screen.getByRole('heading', { name: mcp!.title })).toBeTruthy()
  })

  it('renders a document page with frontmatter title and body', () => {
    renderRoutes('/docs/mcp-guide')

    const doc = getDoc('zh', 'mcp-guide')
    expect(doc).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1, name: doc!.title })).toBeTruthy()
    expect(screen.getByText(doc!.description)).toBeTruthy()
    // Markdown 把 body 拆成多个元素（h2/表格/代码块……），整段 getByText 永远匹配不到
    // 单一元素（此断言自 054a6d4 引入即红）。改为：body 的首个 ## 小节标题必须以 h2 渲染。
    const firstHeading = doc!.body.trim().split('\n')[0].replace(/^#{1,6}\s+/, '')
    expect(screen.getByRole('heading', { level: 2, name: firstHeading })).toBeTruthy()
    expect(screen.getByRole('link', { name: /返回文档索引/ }).getAttribute('href')).toBe('/docs')
  })

  it('follows the i18n language for document content', async () => {
    await i18n.changeLanguage('en')
    renderRoutes('/docs/contract-guide')

    const doc = getDoc('en', 'contract-guide')
    expect(doc).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1, name: doc!.title })).toBeTruthy()
    expect(screen.queryByText('合同智能使用指南')).toBeNull()
  })

  it('shows a friendly not-found state for an unknown slug', () => {
    renderRoutes('/docs/no-such-doc')

    expect(screen.getByText('未找到这篇文档')).toBeTruthy()
    expect(screen.getByRole('link', { name: /返回文档索引/ })).toBeTruthy()
    expect(screen.queryByText('MCP 接入指南')).toBeNull()
  })

  it('renders sample markdown with a heading and a GFM table', () => {
    render(<Markdown content={SAMPLE_MD} />)

    expect(screen.getByRole('heading', { level: 1, name: '接入速览' })).toBeTruthy()
    const table = screen.getByRole('table')
    expect(table).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: '宿主' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: '法条语义检索' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: '私有化' })).toBeTruthy()
  })

  it('keeps a docs entry in the site navigation pointing at /docs', () => {
    render(
      <MemoryRouter>
        <Layout>
          <p>正文占位</p>
        </Layout>
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation', { name: '站内导航' })
    const docsLink = Array.from(nav.querySelectorAll('a')).find(
      (a) => a.getAttribute('href') === '/docs',
    )
    expect(docsLink?.textContent).toBe('文档')
  })
})
