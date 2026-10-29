// /deploy 私有化交付独立路由页（lex-platform-v1 3.3 的 /deploy 入口）。
// 内容与首页文档区同源（docs.sections.*），并展开交付通道与验收口径；中英双语。
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Layout from '../components/Layout'

const SECTION_KEYS = ['deploy', 'airgap', 'upgrade', 'updates', 'offline', 'tiers'] as const
const CHANNEL_KEYS = ['single', 'incremental', 'airgap'] as const

function Deploy() {
  const { t } = useTranslation()

  return (
    <Layout>
      <section className="bg-field text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
          <p className="text-xs tracking-wider text-white/60">{t('deploy.eyebrow')}</p>
          <h1 className="mt-3 font-display text-3xl font-semibold sm:text-4xl">
            {t('deploy.title')}
          </h1>
          <p className="mt-5 max-w-3xl text-[15px] leading-loose text-white/75">
            {t('deploy.lede')}
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            <a
              href="#delivery"
              className="rounded-md bg-white px-5 py-2.5 text-sm font-medium text-field transition-colors hover:bg-mist"
            >
              {t('deploy.ctaSections')}
            </a>
            <Link
              to="/console"
              className="rounded-md border border-white/30 px-5 py-2.5 text-sm text-white transition-colors hover:border-white/60"
            >
              {t('hero.ctaConsole')}
            </Link>
          </div>
        </div>
      </section>

      <section id="delivery" className="scroll-mt-20 bg-paper">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
          <h2 className="font-display text-2xl font-semibold text-ink">{t('docs.title')}</h2>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-soft">{t('docs.lede')}</p>

          <div className="mt-10 grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-2">
            {SECTION_KEYS.map((key, index) => (
              <article key={key} className="bg-white p-6">
                <div className="flex items-baseline gap-3">
                  <span className="font-display text-sm text-line-strong">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <h3 className="font-display text-base font-semibold text-ink">
                    {t(`docs.sections.${key}.name`)}
                  </h3>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-ink-soft">
                  {t(`docs.sections.${key}.desc`)}
                </p>
              </article>
            ))}
          </div>

          <h2 className="mt-14 font-display text-2xl font-semibold text-ink">
            {t('deploy.channelsTitle')}
          </h2>
          <div className="mt-6 grid gap-6 md:grid-cols-3">
            {CHANNEL_KEYS.map((key) => (
              <div key={key} className="rounded-lg border border-line bg-white p-5">
                <h3 className="text-sm font-medium text-ink">{t(`deploy.channels.${key}.name`)}</h3>
                <p className="mt-2 text-xs leading-relaxed text-ink-soft">
                  {t(`deploy.channels.${key}.desc`)}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-12 rounded-lg border border-line bg-white p-6">
            <h3 className="font-display text-base font-semibold text-ink">
              {t('deploy.scopeTitle')}
            </h3>
            <ul className="mt-3 space-y-2 text-sm text-ink-soft">
              <li>{t('deploy.scope.cloud')}</li>
              <li>{t('deploy.scope.private')}</li>
              <li>{t('deploy.scope.contract')}</li>
            </ul>
            <p className="mt-4 text-xs leading-relaxed text-ink-soft">{t('docs.note')}</p>
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-5">
            <a
              href="mailto:contact@finddatatech.cloud"
              className="rounded-md bg-field px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-field-deep"
            >
              {t('deploy.contactCta')}
            </a>
            <span className="text-xs text-ink-soft">{t('pricing.contactPending')}</span>
          </div>
        </div>
      </section>
    </Layout>
  )
}

export default Deploy