import { useTranslation } from 'react-i18next'

export type CapabilityHost = 'both' | 'private'

type HostBadgeProps = {
  host: CapabilityHost
  /** 'dark' 用于深蓝场地（hero / 页脚） */
  variant?: 'light' | 'dark'
  /** 覆盖默认文案（如 hero 栈图中的宿主小注） */
  label?: string
  className?: string
}

/**
 * 宿主徽标：双点图形标注云端 / 私有化可用性——
 * 双实点 = 双宿主；虚点（云端）+ 实点 = 仅私有化。标注口径必须与能力目录一致。
 */
function HostBadge({ host, variant = 'light', label, className = '' }: HostBadgeProps) {
  const { t } = useTranslation()
  const text = label ?? t(host === 'both' ? 'badge.both' : 'badge.privateOnly')

  const tone =
    host === 'both'
      ? variant === 'light'
        ? 'border-line-strong text-ink-soft'
        : 'border-white/30 text-white/80'
      : variant === 'light'
        ? 'border-seal/40 bg-seal-soft text-seal'
        : 'border-[#d98a76]/40 bg-seal/25 text-[#f0c3b6]'

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone} ${className}`}
    >
      <svg aria-hidden="true" width="14" height="8" viewBox="0 0 14 8">
        {host === 'both' ? (
          <>
            <circle cx="3.5" cy="4" r="2.6" fill="currentColor" />
            <circle cx="10.5" cy="4" r="2.6" fill="currentColor" />
          </>
        ) : (
          <>
            <circle
              cx="3.5"
              cy="4"
              r="2.1"
              fill="none"
              stroke="currentColor"
              strokeWidth="1"
              strokeDasharray="1.6 1.4"
            />
            <circle cx="10.5" cy="4" r="2.6" fill="currentColor" />
          </>
        )}
      </svg>
      {text}
    </span>
  )
}

/**
 * 内测状态徽标：尚未在任一宿主开通、但已有明确路径的能力（如电子签正在接入持牌服务商）。
 * 朱红仅用于「仅私有化」与品牌印章两种语义，故内测态用中性的虚线描边，不复用 seal。
 */
export function PreviewBadge() {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line-strong px-2.5 py-0.5 text-xs font-medium text-ink-soft">
      <svg aria-hidden="true" width="14" height="8" viewBox="0 0 14 8">
        <circle cx="3.5" cy="4" r="2.1" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="1.6 1.4" />
        <circle cx="10.5" cy="4" r="2.6" fill="currentColor" />
      </svg>
      {t('badge.preview')}
    </span>
  )
}

export default HostBadge
