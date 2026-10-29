// /docs 文档索引：列出当前语言目录下的全部文档（标题/副文取自 frontmatter）。
// 语言切换时列表内容跟随切换（沿用 i18next 语言机制）。
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Layout from '../components/Layout'
import { docLanguage, listDocs } from '../content/docs/registry'

function DocsIndex() {
  const { t, i18n } = useTranslation()
  const docs = listDocs(docLanguage(i18n.language))

  return (
    <Layout>
      <section className="bg-field text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
          <p className="text-xs tracking-wider text-white/60">{t('docHub.eyebrow')}</p>
          <h1 className="mt-3 font-display text-3xl font-semibold sm:text-4xl">
            {t('docHub.indexTitle')}
          </h1>
          <p className="mt-5 max-w-3xl text-[15px] leading-loose text-white/75">
            {t('docHub.indexLede')}
          </p>
        </div>
      </section>

      <section className="bg-paper">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
          <ul className="grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-2">
            {docs.map((doc) => (
              <li key={doc.slug}>
                <Link
                  to={`/docs/${doc.slug}`}
                  className="block h-full bg-white p-6 transition-colors hover:bg-mist"
                >
                  <h2 className="font-display text-lg font-semibold text-ink">{doc.title}</h2>
                  <p className="mt-3 text-sm leading-relaxed text-ink-soft">{doc.description}</p>
                  <span className="mt-4 inline-block text-xs text-ink-soft">
                    {t('docHub.read')}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {docs.length === 0 && <p className="text-sm text-ink-soft">{t('docHub.empty')}</p>}
        </div>
      </section>
    </Layout>
  )
}

export default DocsIndex
