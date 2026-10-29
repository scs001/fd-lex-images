// 萬星副驾宿主片段（add-embed-copilot-lane 试点接入；
// add-copilot-control-surface 增意图执行器）：
// 控制台右下角嵌入萬星 embed widget（#/embed/<slug>），四件事——
//   ① init 握手（声明可执行意图动词 navigate/refresh）+ 页面上下文推送
//      （wx-copilot-context，随路由更新）
//   ② 身份递送（wx-copilot-identity-request → 把控制台 ID token 按回合递给
//      widget，widget 不持久化；未登录回 null，widget 自动落匿名档）
//   ③ iframe 透明 + 固定右下，收展由 widget 内部自管（wx-copilot-state）
//   ④ 意图执行（wx-copilot-intent）：白名单动词，navigate 只接受控制台
//      五个固定路由（拒绝 /admin 与任意查询串），refresh 重拉当前路由数据；
//      其余动词/路径一律 ok:false——widget 把拒绝原因答回给 agent。
// 挂在 ConsoleLayout（每页一份）。换正式识律 copilot agent 时只改 WIDGET_SLUG。
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CONSOLE_TABS } from './ConsoleLayout'
import { loadSession } from './auth'

const WANXING_ORIGIN = 'https://wanxing.finddatatech.cloud'
export const WIDGET_SLUG = 'packs-xfyxvzonqfelnfigm0djvw-lex-console-copilot'

// 意图白名单：navigate 只认 CONSOLE_TABS 的路由本身（无查询串、无 /admin），
// refresh 无参数。动词表在 init 里声明给 widget——widget 只渲染已声明的动词。
// （CONSOLE_TABS 惰性求值：本组件与 ConsoleLayout 互为循环引用，模块顶层
// 取值会踩 TDZ；意图只会在页面跑起来之后到达，届时早已初始化。）
let navigateTargets: Set<string> | null = null
const navTargets = () => (navigateTargets ??= new Set(CONSOLE_TABS.map((t) => t.to)))
const INTENT_VERBS = ['navigate', 'refresh'] as const

export function WanxingCopilot() {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const navigateRef = useRef<((to: string) => void) | null>(null)
  const [open, setOpen] = useState(true)

  const src = `${WANXING_ORIGIN}/#/embed/${WIDGET_SLUG}?accent=%231d4ed8&open=1`

  const post = (msg: Record<string, unknown>) => {
    frameRef.current?.contentWindow?.postMessage({ slug: WIDGET_SLUG, ...msg }, WANXING_ORIGIN)
  }

  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== WANXING_ORIGIN) return
      const d = ev.data as {
        type?: string
        slug?: string
        open?: boolean
        askId?: string
        questionId?: string
        verb?: string
        arg?: string
      }
      if (d?.slug !== WIDGET_SLUG) return
      if (d.type === 'wx-copilot-ready' || d.type === 'wx-copilot-state') {
        // ready/state 只是姿态同步；收展态用于宿主侧高度适配（当前固定框足够）
        if (typeof d.open === 'boolean') setOpen(d.open)
        if (d.type === 'wx-copilot-ready') post({ type: 'wx-copilot-init', intents: INTENT_VERBS })
      }
      if (d.type === 'wx-copilot-identity-request') {
        const session = loadSession()
        post({ type: 'wx-copilot-identity', token: session?.idToken ?? null })
      }
      if (d.type === 'wx-copilot-intent') {
        const reply = (ok: boolean, message = '') =>
          post({ type: 'wx-copilot-intent-result', askId: d.askId, questionId: d.questionId, ok, ...(message ? { message } : {}) })
        if (d.verb === 'navigate') {
          const to = String(d.arg ?? '')
          if (!navTargets().has(to)) {
            reply(false, `not allowed: navigate 只接受控制台页面路由（${[...navTargets()].join(' ')}）`)
          } else {
            navigateRef.current?.(to)
            reply(true)
          }
        } else if (d.verb === 'refresh') {
          // 当前路由整页重载——最朴素且必然正确的「重拉本页数据」
          window.location.reload()
          reply(true)
        } else {
          reply(false, `not allowed: 未声明的动词 ${String(d.verb ?? '')}`)
        }
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // navigate 经 ref 透传：消息监听只挂一次，路由器实例却随布局渲染
  const navigate = useNavigate()
  useEffect(() => {
    navigateRef.current = (to) => navigate(to)
  }, [navigate])

  // 页面上下文随路由推送（首帧后与每次 pathname 变化）
  useEffect(() => {
    post({
      type: 'wx-copilot-context',
      line: '识律',
      page: window.location.pathname,
      intent: '控制台操作伴随',
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window.location.pathname])

  return (
    <iframe
      ref={frameRef}
      src={src}
      title="助手"
      data-testid="wanxing-copilot"
      allow="clipboard-write"
      style={{
        position: 'fixed',
        bottom: 0,
        right: 0,
        width: '420px',
        height: open ? '640px' : '80px',
        border: 0,
        background: 'transparent',
        zIndex: 2147483000,
        transition: 'height 0.2s ease',
      }}
    />
  )
}
