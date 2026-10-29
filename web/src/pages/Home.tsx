import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { TFunction } from 'i18next'

import HostBadge, { type CapabilityHost, PreviewBadge } from '../components/HostBadge'
import Layout from '../components/Layout'
import StackDiagram from '../components/StackDiagram'

const CAPABILITY_KEYS = ['retrieval', 'contract', 'esignature', 'models', 'distribution', 'api'] as const
const STAT_KEYS = ['wenshu', 'catalog', 'tools'] as const
const PRICING_DIMENSIONS = ['units', 'quota', 'overage', 'updates', 'deploy'] as const
const DOC_SECTIONS = ['deploy', 'airgap', 'upgrade', 'updates', 'offline', 'tiers'] as const

function tArray(t: TFunction, key: string): string[] {
  const value = t(key, { returnObjects: true })
  return Array.isArray(value) ? (value as string[]) : []
}

function Hero() {
  const { t } = useTranslation()

  return (
    <section className="bg-field text-white">
      <div className="mx-auto grid max-w-6xl gap-14 px-6 py-20 lg:grid-cols-12 lg:gap-12 lg:py-28">
        <div className="lg:col-span-7">
          <h1 className="font-display font-semibold">
            <span className="reveal block text-4xl leading-tight tracking-tight sm:text-5xl">
              {t('hero.titleLine1')}
            </span>
            <span className="reveal reveal-1 mt-4 block text-2xl leading-snug text-white/85 sm:text-3xl">
              {t('hero.titleLine2')}
            </span>
          </h1>
          <p className="reveal reveal-2 mt-7 max-w-[36rem] text-[15px] leading-loose text-white/75">
            {t('hero.lede')}
          </p>

          <dl className="reveal reveal-3 mt-9 flex flex-wrap gap-x-10 gap-y-5">
            {STAT_KEYS.map((key) => (
              <div key={key} className="flex flex-col">
                <dt className="order-2 mt-1 text-xs text-white/65">
                  {t(`hero.stats.${key}.label`)}
                </dt>
                <dd className="order-1 font-display text-2xl tabular-nums text-white">
                  {t(`hero.stats.${key}.value`)}
                </dd>
              </div>
            ))}
          </dl>

          <div className="reveal reveal-4 mt-10 flex flex-wrap items-center gap-4">
            <a
              href="#capabilities"
              className="rounded-md bg-white px-5 py-2.5 text-sm font-medium text-field transition-colors hover:bg-mist"
            >
              {t('hero.ctaCatalog')}
            </a>
            <Link
              to="/console"
              className="rounded-md border border-white/30 px-5 py-2.5 text-sm text-white transition-colors hover:border-white/60"
            >
              {t('hero.ctaConsole')}
            </Link>
          </div>
        </div>

        <div className="reveal reveal-3 self-center lg:col-span-5">
          <StackDiagram />
        </div>
      </div>
    </section>
  )
}

function Capabilities() {
  const { t } = useTranslation()

  return (
    <section id="capabilities" className="scroll-mt-20 bg-paper">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-24">
        <div className="max-w-[40rem]">
          <h2 className="font-display text-3xl font-semibold tracking-tight">
            {t('capabilities.title')}
          </h2>
          <p className="mt-4 text-[15px] leading-loose text-ink-soft">
            {t('capabilities.lede')}
          </p>
        </div>

        <div className="mt-12">
          <div className="hidden grid-cols-12 gap-6 border-b-2 border-ink pb-3 text-xs font-medium tracking-wider text-ink-soft lg:grid">
            <div className="col-span-4">{t('capabilities.columnCapability')}</div>
            <div className="col-span-5">{t('capabilities.columnPoints')}</div>
            <div className="col-span-3">{t('capabilities.columnHost')}</div>
          </div>

          <ul className="divide-y divide-line border-b-2 border-ink">
            {CAPABILITY_KEYS.map((key) => {
              const host = t(`capabilities.items.${key}.host`) as CapabilityHost
              const status = t(`capabilities.items.${key}.status`, {
                defaultValue: '',
              })
              const points = tArray(t, `capabilities.items.${key}.points`)
              const note = t(`capabilities.items.${key}.note`)
              return (
                <li key={key} className="grid gap-5 py-8 lg:grid-cols-12 lg:gap-6">
                  <div className="lg:col-span-4">
                    <h3 className="font-display text-xl font-semibold">
                      {t(`capabilities.items.${key}.name`)}
                    </h3>
                    <p className="mt-1 text-xs font-medium uppercase tracking-[0.14em] text-ink-soft">
                      {t(`capabilities.items.${key}.latin`)}
                    </p>
                    <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-soft">
                      {t(`capabilities.items.${key}.desc`)}
                    </p>
                  </div>
                  <div className="lg:col-span-5">
                    <ul className="space-y-2.5">
                      {points.map((point) => (
                        <li key={point} className="flex gap-2.5 text-sm leading-relaxed">
                          <span
                            aria-hidden="true"
                            className="mt-[0.6em] h-1 w-1 shrink-0 rounded-[1px] bg-line-strong"
                          />
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="lg:col-span-3">
                    {status === 'preview' ? <PreviewBadge /> : <HostBadge host={host} />}
                    {note !== '' && (host === 'private' || status === 'preview') && (
                      <p
                        className={`mt-2.5 max-w-[16rem] text-xs leading-relaxed ${
                          status === 'preview' ? 'text-ink-soft' : 'text-seal'
                        }`}
                      >
                        {note}
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>

          <p className="mt-5 text-xs leading-relaxed text-ink-soft">
            {t('capabilities.footnote')}
          </p>
        </div>
      </div>
    </section>
  )
}

function Pricing() {
  const { t } = useTranslation()

  return (
    <section id="pricing" className="scroll-mt-20 bg-mist">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-24">
        <div className="max-w-[40rem]">
          <h2 className="font-display text-3xl font-semibold tracking-tight">
            {t('pricing.title')}
          </h2>
          <p className="mt-4 text-[15px] leading-loose text-ink-soft">{t('pricing.lede')}</p>
        </div>

        <div className="mt-12 max-w-3xl">
          <h3 className="text-sm font-medium">{t('pricing.subtitle')}</h3>
          <dl className="mt-4 border-t-2 border-ink">
            {PRICING_DIMENSIONS.map((key) => {
              const name = t(`pricing.dimensions.${key}.name`)
              const value = t(`pricing.dimensions.${key}.value`)
              const quoted = key !== 'units'
              return (
                <div
                  key={key}
                  className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1.5 border-b border-line py-4"
                >
                  <dt className="text-[15px]">{name}</dt>
                  <dd className="text-right">
                    {quoted ? (
                      <span className="inline-block rounded-full border border-line-strong px-2.5 py-0.5 text-xs text-ink-soft">
                        {value}
                      </span>
                    ) : (
                      <span className="text-sm text-ink-soft">{value}</span>
                    )}
                  </dd>
                </div>
              )
            })}
          </dl>

          <p className="mt-5 text-xs leading-relaxed text-ink-soft">{t('pricing.note')}</p>

          <div className="mt-8 flex flex-wrap items-center gap-4">
            <a
              href="#contact"
              className="rounded-md bg-field px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-field-deep"
            >
              {t('pricing.cta')}
            </a>
            <span className="text-xs text-ink-soft">{t('pricing.contactPending')}</span>
          </div>
        </div>
      </div>
    </section>
  )
}

function Docs() {
  const { t } = useTranslation()

  return (
    <section id="docs" className="scroll-mt-20 bg-paper">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-24">
        <div className="max-w-[40rem]">
          <h2 className="font-display text-3xl font-semibold tracking-tight">{t('docs.title')}</h2>
          <p className="mt-4 text-[15px] leading-loose text-ink-soft">{t('docs.lede')}</p>
        </div>

        <div className="mt-12 grid gap-x-12 border-t-2 border-ink md:grid-cols-2">
          {DOC_SECTIONS.map((key) => (
            <div key={key} className="border-b border-line py-6">
              <h3 className="text-[15px] font-medium">{t(`docs.sections.${key}.name`)}</h3>
              <p className="mt-2.5 text-sm leading-relaxed text-ink-soft">
                {t(`docs.sections.${key}.desc`)}
              </p>
            </div>
          ))}
        </div>

        <p className="mt-5 text-xs leading-relaxed text-ink-soft">{t('docs.note')}</p>
      </div>
    </section>
  )
}

function Home() {
  return (
    <Layout>
      <Hero />
      <Capabilities />
      <Pricing />
      <Docs />
    </Layout>
  )
}

export default Home
