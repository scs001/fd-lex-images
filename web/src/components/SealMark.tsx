function SealMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="识律">
      <rect width="32" height="32" rx="4" fill="#A6402F" />
      <text
        x="16"
        y="10"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="11.5"
        fontWeight="600"
        fill="#FFFFFF"
        fontFamily="'Noto Serif SC', 'Songti SC', 'SimSun', serif"
      >
        识
      </text>
      <text
        x="16"
        y="22"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="11.5"
        fontWeight="600"
        fill="#FFFFFF"
        fontFamily="'Noto Serif SC', 'Songti SC', 'SimSun', serif"
      >
        律
      </text>
    </svg>
  )
}

export default SealMark
