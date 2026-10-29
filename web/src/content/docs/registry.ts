// /docs 文档注册表：以 Vite eager raw glob 装载 zh/en 两个语言目录的全部 Markdown，
// 轻量解析 frontmatter（title/description），供文档索引页与文档页按 i18n 语言取用。
// 文档源文件由内容侧维护；本模块只读装载，不参与内容写作。

export interface DocEntry {
  slug: string
  title: string
  description: string
  body: string
}

export type DocLanguage = 'zh' | 'en'

const ZH_MODULES = import.meta.glob('./zh/*.md', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>

const EN_MODULES = import.meta.glob('./en/*.md', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>

const MODULES: Record<DocLanguage, Record<string, string>> = {
  zh: ZH_MODULES,
  en: EN_MODULES,
}

/** i18n 语言 -> 文档目录语言（未知语言回退中文，与 i18n.ts 的 fallbackLng 一致）。 */
export function docLanguage(language: string): DocLanguage {
  return language === 'en' ? 'en' : 'zh'
}

export interface ParsedDoc {
  title: string
  description: string
  body: string
}

/** 轻量 frontmatter 解析：仅取顶层 `key: value` 的 title/description，其余为正文。 */
export function parseDoc(raw: string): ParsedDoc {
  const normalized = raw.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
  const match = /^---\n([\s\S]*?)\n---(?:\n|$)/.exec(normalized)
  if (!match) return { title: '', description: '', body: normalized }

  const fields: Record<string, string> = {}
  for (const line of match[1].split('\n')) {
    const separator = line.indexOf(':')
    if (separator === -1) continue
    const key = line.slice(0, separator).trim()
    let value = line.slice(separator + 1).trim()
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1)
    }
    if (key !== '') fields[key] = value
  }

  return {
    title: fields.title ?? '',
    description: fields.description ?? '',
    body: normalized.slice(match[0].length),
  }
}

function slugOf(path: string): string {
  return path.replace(/^\.\/(?:zh|en)\//, '').replace(/\.md$/, '')
}

function loadDocs(language: DocLanguage): DocEntry[] {
  return Object.entries(MODULES[language])
    .map(([path, raw]) => ({ slug: slugOf(path), ...parseDoc(raw) }))
    .sort((a, b) => a.slug.localeCompare(b.slug))
}

const CACHE = new Map<DocLanguage, DocEntry[]>()

/** 当前语言下的全部文档（按 slug 稳定排序），供 /docs 索引页使用。 */
export function listDocs(language: DocLanguage): DocEntry[] {
  let docs = CACHE.get(language)
  if (!docs) {
    docs = loadDocs(language)
    CACHE.set(language, docs)
  }
  return docs
}

/** 按语言与 slug 精确取一篇文档；未命中返回 undefined（由页面给出未找到态）。 */
export function getDoc(language: DocLanguage, slug: string): DocEntry | undefined {
  return listDocs(language).find((doc) => doc.slug === slug)
}
