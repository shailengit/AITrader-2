import { HTMLAttributes, forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../context/ThemeContext'

// Base Card
interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'base' | 'raised' | 'overlay'
  hover?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ variant = 'base', hover = false, children, className = '', ...props }, ref) => {
    // Theme-aware surfaces from the design tokens.
    const bgColors = {
      base: 'var(--surface)',
      raised: 'var(--surface-raised)',
      overlay: 'var(--surface-overlay)',
    }

    return (
      <div
        ref={ref}
        className={`rounded-xl ${hover ? 'transition-colors' : ''} ${className}`}
        style={{
          backgroundColor: bgColors[variant],
          border: '1px solid var(--border)',
          color: 'var(--foreground)',
        }}
        {...props}
      >
        {children}
      </div>
    )
  }
)
Card.displayName = 'Card'

// Data Card - for stock tickers, metrics
interface DataCardProps extends HTMLAttributes<HTMLDivElement> {
  accentColor?: 'apple' | 'white' | 'muted' | 'red'
  active?: boolean
}

const dataCardAccentColors = {
  apple: '#0071e3',
  white: '#ffffff',
  muted: 'rgba(255,255,255,0.48)',
  red: '#ff3b30',
}

export const DataCard = forwardRef<HTMLDivElement, DataCardProps>(
  ({ accentColor = 'apple', active = false, children, className = '', ...props }, ref) => {

    const accent = accentColor === 'white' ? 'var(--foreground)' : dataCardAccentColors[accentColor]

    return (
      <div
        ref={ref}
        className={`rounded-lg p-6 border ${active ? 'shadow-[rgba(0,0,0,0.22)_3px_5px_30px_0px]' : ''} ${className}`}
        style={{
          backgroundColor: 'var(--surface)',
          borderColor: 'var(--border)',
          color: 'var(--foreground)',
          borderTopColor: accent,
          borderTopWidth: 3,
        }}
        {...props}
      >
        {children}
      </div>
    )
  }
)
DataCard.displayName = 'DataCard'

// Stat Card - for key metrics display
interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  label: string
  value: string | number
  change?: string
  changeType?: 'positive' | 'negative' | 'neutral'
  suffix?: string
}

export const StatCard = forwardRef<HTMLDivElement, StatCardProps>(
  ({ label, value, change, changeType = 'neutral', suffix, className = '', ...props }, ref) => {

    const changeColors = {
      positive: 'text-[var(--good)]',
      negative: 'text-[var(--bad)]',
      neutral: 'text-[var(--muted)]',
    }

    const textColor = 'var(--foreground)'
    const mutedColor = 'var(--muted)'
    const bgColor = 'var(--surface)'
    const hoverBg = 'var(--surface-raised)'

    return (
      <div
        ref={ref}
        className={`rounded-lg p-6 text-center transition-colors border border-[var(--border)] ${className}`}
        style={{
          backgroundColor: bgColor,
          color: textColor,
        }}
        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = hoverBg}
        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = bgColor}
        {...props}
      >
        <p className="text-[28px] font-normal mb-1 tabular-nums leading-[1.14] tracking-[0.196px]" style={{ color: textColor }}>
          {value}{suffix && <span className="text-[17px] ml-1" style={{ color: mutedColor }}>{suffix}</span>}
        </p>
        <p className="text-[14px] mb-1 tracking-[-0.224px]" style={{ color: mutedColor }}>{label}</p>
        {change && <p className={`text-[14px] font-medium tracking-[-0.224px] ${changeColors[changeType]}`}>{change}</p>}
      </div>
    )
  }
)
StatCard.displayName = 'StatCard'

// Feature Card - for landing page tool cards
interface FeatureCardProps {
  title: string
  description: string
  icon: React.ReactNode
  features: string[]
  accentColor: 'emerald' | 'blue' | 'purple'
  linkTo: string
}

const featureCardStyles = {
  emerald: {
    background: 'rgba(255, 255, 255, 0.02)',
    border: 'rgba(255, 255, 255, 0.05)',
    hoverBorder: 'rgba(16, 185, 129, 0.3)',
    hoverShadow: '0 8px 32px rgba(16, 185, 129, 0.15)',
    bullet: '#10B981',
    icon: '#34D399',
  },
  blue: {
    background: 'rgba(255, 255, 255, 0.02)',
    border: 'rgba(255, 255, 255, 0.05)',
    hoverBorder: 'rgba(59, 130, 246, 0.3)',
    hoverShadow: '0 8px 32px rgba(59, 130, 246, 0.15)',
    bullet: '#3B82F6',
    icon: '#60A5FA',
  },
  purple: {
    background: 'rgba(255, 255, 255, 0.02)',
    border: 'rgba(255, 255, 255, 0.05)',
    hoverBorder: 'rgba(168, 85, 247, 0.3)',
    hoverShadow: '0 8px 32px rgba(168, 85, 247, 0.15)',
    bullet: '#A855F7',
    icon: '#C084FC',
  }
}

export function FeatureCard({ title, description, icon, features, accentColor, linkTo }: FeatureCardProps) {
  const { isDarkMode } = useTheme()
  const styles = featureCardStyles[accentColor]

  const colors = {
    iconBg: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : '#f5f5f7',
    iconBorder: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#d2d2d7',
    arrow: isDarkMode ? '#71717A' : '#86868b',
    title: isDarkMode ? '#ffffff' : '#1d1d1f',
    description: isDarkMode ? 'rgba(255,255,255,0.7)' : '#6e6e73',
    featureText: isDarkMode ? '#D4D4D8' : '#1d1d1f',
  }

  return (
    <Link
      to={linkTo}
      className="group relative block rounded-2xl p-12 no-underline cursor-pointer transition-all duration-300"
      style={{
        background: isDarkMode ? styles.background : '#ffffff',
        border: `1px solid ${isDarkMode ? styles.border : '#e5e5ea'}`,
        transform: 'translateY(0)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = isDarkMode ? styles.hoverBorder : 'rgba(0,0,0,0.15)'
        e.currentTarget.style.boxShadow = styles.hoverShadow
        e.currentTarget.style.transform = 'translateY(-4px)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = isDarkMode ? styles.border : '#e5e5ea'
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      <div className="flex items-start justify-between mb-8">
        <div style={{
          padding: 16,
          borderRadius: 16,
          border: `1px solid ${colors.iconBorder}`,
          backgroundColor: colors.iconBg,
          transition: 'all 0.3s ease'
        }}>
          <span style={{ color: styles.icon }}>{icon}</span>
        </div>
        <svg className="w-6 h-6 transition-colors duration-300" style={{ color: colors.arrow }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
      </div>

      <h3 className="text-[28px] font-bold mb-3 transition-colors duration-300" style={{ color: colors.title }}>{title}</h3>
      <p className="text-base mb-8 leading-relaxed transition-colors duration-300" style={{ color: colors.description }}>{description}</p>

      <ul className="list-none p-0 m-0">
        {features.map((feature, i) => (
          <li key={i} className="flex items-center gap-3 text-[15px] mb-4 transition-colors duration-300" style={{ color: colors.featureText }}>
            <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: styles.bullet }} />
            {feature}
          </li>
        ))}
      </ul>
    </Link>
  )
}