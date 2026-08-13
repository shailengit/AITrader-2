import { ButtonHTMLAttributes, forwardRef } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-[var(--accent)] text-[var(--accent-ink)] font-semibold hover:opacity-90',
  secondary: 'bg-[var(--surface)] text-[var(--foreground)] font-medium hover:bg-[var(--surface-raised)] border border-[var(--border)]',
  ghost: 'bg-transparent text-[var(--muted)] font-medium hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]',
  destructive: 'bg-[var(--bad)] text-white font-semibold hover:opacity-90',
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-sm rounded-md gap-1.5',
  md: 'px-4 py-2.5 text-base rounded-md gap-2',
  lg: 'px-6 py-3 text-lg rounded-lg gap-2.5',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({
    variant = 'primary',
    size = 'md',
    leftIcon,
    rightIcon,
    children,
    className = '',
    disabled,
    ...props
  }, ref) => {
    const baseStyles = 'inline-flex items-center justify-center transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:ring-offset-2 focus:ring-offset-[var(--canvas)] disabled:opacity-50 disabled:cursor-not-allowed'

    return (
      <button
        ref={ref}
        className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
        disabled={disabled}
        {...props}
      >
        {leftIcon && <span className="flex-shrink-0">{leftIcon}</span>}
        {children}
        {rightIcon && <span className="flex-shrink-0">{rightIcon}</span>}
      </button>
    )
  }
)

Button.displayName = 'Button'