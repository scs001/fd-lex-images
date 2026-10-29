import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en/translation.json'
import zh from './locales/zh/translation.json'

// i18next 双语骨架：zh/en 各一个 namespace（translation）。
// 语言探测顺序：localStorage -> 默认中文。切换时同步 <html lang>。
export const SUPPORTED_LANGUAGES = ['zh', 'en'] as const
export const LANGUAGE_STORAGE_KEY = 'lex.lang'

function initialLanguage(): (typeof SUPPORTED_LANGUAGES)[number] {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (stored === 'zh' || stored === 'en') return stored
  } catch {
    // localStorage 不可用（如隐私模式）时回退中文
  }
  return 'zh'
}

function syncDocumentLanguage(lng: string) {
  document.documentElement.lang = lng === 'zh' ? 'zh-CN' : 'en'
}

void i18n.use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
  },
  lng: initialLanguage(),
  fallbackLng: 'zh',
  supportedLngs: [...SUPPORTED_LANGUAGES],
  interpolation: { escapeValue: false },
})

i18n.on('languageChanged', syncDocumentLanguage)
syncDocumentLanguage(i18n.language)

export function persistLanguage(lng: string) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, lng)
  } catch {
    // 存储不可用时静默：本次会话内切换仍生效
  }
}

export default i18n
