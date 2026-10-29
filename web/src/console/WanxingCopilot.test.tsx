// 萬星副驾宿主片段——意图执行器（add-copilot-control-surface 3.1/3.2）：
// init 声明 navigate/refresh；navigate 只认 CONSOLE_TABS 五路由（拒 /admin、
// 拒查询串、拒未知动词），异源消息一律忽略。行为级断言（不测内部形状）。
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { CONSOLE_TABS } from './ConsoleLayout'
import { WanxingCopilot, WIDGET_SLUG } from './WanxingCopilot'

const WANXING_ORIGIN = 'https://wanxing.finddatatech.cloud'

beforeEach(() => {
  window.location.pathname = '/console'
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

type Reply = { slug: string; type: string; askId?: string; questionId?: string; ok?: boolean; message?: string }

function mountCopilot() {
  const replies: Reply[] = []
  const locPath: string[] = ['/console']
  const postSpy = vi.fn((msg: Record<string, unknown>) => { replies.push(msg as Reply) })
  const LocProbe = () => {
    const loc = useLocation()
    locPath[0] = loc.pathname
    return null
  }
  const { container } = render(
    <MemoryRouter initialEntries={['/console']}>
      <LocProbe />
      <WanxingCopilot />
    </MemoryRouter>,
  )
  const frame = container.querySelector('iframe[data-testid="wanxing-copilot"]') as HTMLIFrameElement
  expect(frame).toBeTruthy()
  // jsdom 的 iframe 没有真实 contentWindow——替换为可断言的假窗口
  Object.defineProperty(frame, 'contentWindow', { value: { postMessage: postSpy }, configurable: true })
  const fromWidget = (data: Record<string, unknown>, origin = WANXING_ORIGIN) =>
    window.dispatchEvent(new MessageEvent('message', { origin, data: { slug: WIDGET_SLUG, ...data } }))
  const results = () => replies.filter((r) => r.type === 'wx-copilot-intent-result')
  return { replies, locPath, fromWidget, results }
}

describe('WanxingCopilot 意图执行器', () => {
  it('init 握手声明 navigate/refresh 动词', () => {
    const h = mountCopilot()
    h.fromWidget({ type: 'wx-copilot-ready' })
    const init = h.replies.find((r) => r.type === 'wx-copilot-init')
    expect(init).toBeTruthy()
    expect((init as { intents?: string[] }).intents).toEqual(['navigate', 'refresh'])
  })

  it('navigate 到每个控制台路由都 ok 且真的切了路由', async () => {
    const h = mountCopilot()
    for (const tab of CONSOLE_TABS) {
      await act(async () => {
        h.fromWidget({ type: 'wx-copilot-intent', askId: `a-${tab.id}`, questionId: 'q', verb: 'navigate', arg: tab.to })
      })
      const r = h.results().at(-1)
      expect(r?.ok).toBe(true)
      expect(h.locPath[0]).toBe(tab.to)
    }
  })

  it('navigate 拒绝 /admin、带查询串与未知动词，且原因答回', () => {
    const h = mountCopilot()
    h.fromWidget({ type: 'wx-copilot-intent', askId: 'a1', questionId: 'q', verb: 'navigate', arg: '/admin' })
    expect(h.results().at(-1)?.ok).toBe(false)
    expect(h.results().at(-1)?.message).toContain('not allowed')
    h.fromWidget({ type: 'wx-copilot-intent', askId: 'a2', questionId: 'q', verb: 'navigate', arg: '/console/usage?x=1' })
    expect(h.results().at(-1)?.ok).toBe(false)
    h.fromWidget({ type: 'wx-copilot-intent', askId: 'a3', questionId: 'q', verb: 'highlight', arg: '#x' })
    expect(h.results().at(-1)?.ok).toBe(false)
    expect(h.results().at(-1)?.message).toContain('未声明的动词')
    expect(h.locPath[0]).toBe('/console') // 一次都没动
  })

  it('refresh 回 ok；异源消息一律忽略（不回任何结果）', () => {
    const h = mountCopilot()
    h.fromWidget({ type: 'wx-copilot-intent', askId: 'a4', questionId: 'q', verb: 'refresh', arg: '' })
    expect(h.results().at(-1)?.ok).toBe(true)
    // window.location.reload 会被 jsdom 忽略/告警，不影响断言
    const before = h.results().length
    h.fromWidget({ type: 'wx-copilot-intent', askId: 'a5', questionId: 'q', verb: 'navigate', arg: '/admin' }, 'https://evil.example')
    expect(h.results().length).toBe(before)
  })
})
