import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import SealMark from './SealMark'
import { persistLanguage } from '../i18n'

const LINE_KEYS = ['base', 'lex', 'wire', 'facet', 'constellation'] as const

/** 站内锚点：本页为 / 时原生平滑滚动；其他路由（/console、/admin）先回到 /。 */
function AnchorLink({
  hash,
  className,
  children,
}: {
  hash: string
  className?: string
  children: ReactNode
}) {
  const { pathname } = useLocation()

  if (pathname === '/') {
    return (
      <a href={`#${hash}`} className={className}>
        {children}
      </a>
    )
  }
  return (
    <Link to={{ pathname: '/', hash: `#${hash}` }} className={className}>
      {children}
    </Link>
  )
}

function Layout({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation()
  const nextLanguage = i18n.language === 'zh' ? 'en' : 'zh'

  const switchLanguage = () => {
    void i18n.changeLanguage(nextLanguage)
    persistLanguage(nextLanguage)
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <header className="sticky top-0 z-40 border-b border-line bg-paper">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6">
          <Link to="/" className="flex items-center gap-2.5" aria-label={t('brand')}>
            <SealMark className="h-8 w-8" />
            <span className="font-display text-lg font-semibold tracking-wide">{t('brand')}</span>
          </Link>
          <div className="flex items-center gap-5 sm:gap-7">
            <nav aria-label={t('nav.label')} className="hidden items-center gap-7 text-sm md:flex">
              <AnchorLink
                hash="capabilities"
                className="text-ink-soft transition-colors hover:text-ink"
              >
                {t('nav.capabilities')}
              </AnchorLink>
              <AnchorLink hash="pricing" className="text-ink-soft transition-colors hover:text-ink">
                {t('nav.pricing')}
              </AnchorLink>
              <NavLink to="/docs" className="text-ink-soft transition-colors hover:text-ink">
                {t('nav.guides')}
              </NavLink>
              <NavLink to="/deploy" className="text-ink-soft transition-colors hover:text-ink">
                {t('nav.docs')}
              </NavLink>
              <NavLink to="/console" className="text-ink-soft transition-colors hover:text-ink">
                {t('nav.console')}
              </NavLink>
            </nav>
            <button
              type="button"
              onClick={switchLanguage}
              aria-label={t('lang.ariaLabel')}
              className="rounded-full border border-line-strong px-3 py-1 text-xs text-ink-soft transition-colors hover:border-ink hover:text-ink"
            >
              {t('lang.switch')}
            </button>
          </div>
        </div>
      </header>

      <main className="flex flex-1 flex-col">{children}</main>

      <footer className="bg-field-deep text-white">
        <div id="contact" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-16 lg:py-20">
          <div className="grid gap-12 lg:grid-cols-12">
            <div className="lg:col-span-5">
              <div className="flex items-center gap-2.5">
                <SealMark className="h-9 w-9" />
                <span className="font-display text-lg font-semibold">{t('brand')}</span>
              </div>
              <p className="mt-5 max-w-sm text-sm leading-relaxed text-white/65">
                {t('footer.tagline')}
              </p>
              <div className="mt-8">
                <h3 className="text-xs font-medium tracking-wider text-white/55">
                  {t('footer.contactLabel')}
                </h3>
                <p className="mt-2 text-sm text-white/80">{t('footer.contactPending')}</p>
              </div>
            </div>

            <div className="lg:col-span-4">
              <h3 className="text-xs font-medium tracking-wider text-white/55">
                {t('footer.linesLabel')}
              </h3>
              <ul className="mt-4 space-y-2.5">
                {LINE_KEYS.map((key) => {
                  const current = key === 'lex'
                  return (
                    <li
                      key={key}
                      className={`flex items-center gap-2.5 text-sm ${current ? 'font-medium text-white' : 'text-white/70'}`}
                    >
                      {t(`footer.lines.${key}`)}
                      {current && (
                        <span className="rounded-full border border-white/35 px-2 py-px text-[10px] font-normal leading-4 text-white/75">
                          {t('footer.lexCurrent')}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
              <p className="mt-6 text-xs text-white/55">{t('footer.brandSentence')}</p>
            </div>

            <div className="lg:col-span-3">
              <h3 className="text-xs font-medium tracking-wider text-white/55">
                {t('footer.entriesLabel')}
              </h3>
              <ul className="mt-4 space-y-2.5 text-sm">
                <li>
                  <Link to="/" className="text-white/75 transition-colors hover:text-white">
                    {t('footer.entries.home')}
                  </Link>
                </li>
                <li>
                  <Link
                    to="/console"
                    className="text-white/75 transition-colors hover:text-white"
                  >
                    {t('footer.entries.console')}
                  </Link>
                </li>
                <li className="flex items-center gap-2 text-white/75">
                  {t('footer.entries.mcp')}
                  <span className="font-mono text-xs text-white/55">/mcp</span>
                </li>
                <li>
                  <Link to="/deploy" className="text-white/75 transition-colors hover:text-white">
                    {t('footer.entries.deploy')}
                  </Link>
                </li>
              </ul>
            </div>
          </div>

          <div className="mt-14 flex flex-wrap items-center justify-between gap-3 border-t border-white/15 pt-6 text-xs text-white/55">
            <p>{t('footer.copyright')}</p>
            <p>{t('footer.icp')}</p>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default Layout
