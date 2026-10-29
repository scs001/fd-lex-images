import { useTranslation } from 'react-i18next'

import HostBadge, { type CapabilityHost } from './HostBadge'

const LAYERS = ['model', 'app', 'data'] as const

const LAYER_HOSTS: Record<(typeof LAYERS)[number], { host: CapabilityHost; key: string }> = {
  model: { host: 'private', key: 'hero.diagram.model.host' },
  app: { host: 'both', key: 'hero.diagram.app.host' },
  data: { host: 'both', key: 'hero.diagram.data.host' },
}

/** 垂直整合栈图：模型 / 应用 / 数据三层，各带宿主标注，底注「同一份交付包 · 双宿主」。 */
function StackDiagram() {
  const { t } = useTranslation()

  return (
    <div className="rounded-2xl border border-white/15 bg-white/[0.04] p-5 sm:p-6">
      <ul>
        {LAYERS.map((layer, index) => (
          <li key={layer}>
            {index > 0 && <div aria-hidden="true" className="mx-auto h-4 w-px bg-white/25" />}
            <div className="flex items-start justify-between gap-4 rounded-lg border border-white/15 bg-white/[0.05] px-4 py-3.5">
              <div>
                <p className="font-display text-base font-semibold text-white">
                  {t(`hero.diagram.${layer}.name`)}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-white/65">
                  {t(`hero.diagram.${layer}.items`)}
                </p>
              </div>
              <HostBadge
                host={LAYER_HOSTS[layer].host}
                variant="dark"
                label={t(LAYER_HOSTS[layer].key)}
                className="shrink-0"
              />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-white/15 pt-4">
        <p className="text-sm font-medium text-white/90">{t('hero.diagram.caption')}</p>
        <p className="text-xs text-white/60">{t('hero.diagram.captionSub')}</p>
      </div>
    </div>
  )
}

export default StackDiagram
