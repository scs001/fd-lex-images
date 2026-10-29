// /docs/:slug 文档页：按当前 i18n 语言选 zh/en 目录渲染对应 Markdown。
// slug 未命中时给友好的「未找到」态，并保留返回文档索引的出口。
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import Markdown from '../components/Markdown'
import Layout from '../components/Layout'
import { docLanguage, getDoc } from '../content/docs/registry'

function DocPage() {
  const { slug } = useParams()
  const { t, i18n } = useTranslation()
  const doc = getDoc(docLanguage(i18n.language), slug ?? '')

  if (!doc) {
    return (
      <Layout>
        <section className="bg-paper">
          <div className="mx-auto max-w-3xl px-6 py-24 text-center">
            <p className="font-display text-5xl font-semibold text-line-strong">404</p>
            <h1 className="mt-4 font-display text-2xl font-semibold text-ink">
              {t('docHub.notFound.title')}
            </h1>
            <p className="mx-auto mt-4 max-w-md text-sm leading-relaxed text-ink-soft">
              {t('docHub.notFound.lede')}
            </p>
            <Link
              to="/docs"
              className="mt-8 inline-block rounded-md bg-field px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-field-deep"
            >
              {t('docHub.backToIndex')}
            </Link>
          </div>
        </section>
      </Layout>
    )
  }

  return (
    <Layout>
      <article className="bg-paper">
        <div className="mx-auto max-w-3xl px-6 py-16 lg:py-20">
          <Link to="/docs" className="text-xs text-ink-soft transition-colors hover:text-ink">
            ← {t('docHub.backToIndex')}
          </Link>
          <header className="mt-6 border-b-2 border-ink pb-8">
            <h1 className="font-display text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
              {doc.title}
            </h1>
            {doc.description !== '' && (
              <p className="mt-4 text-[15px] leading-loose text-ink-soft">{doc.description}</p>
            )}
          </header>
          <Markdown content={doc.body} />
        </div>
      </article>
    </Layout>
  )
}

export default DocPage
