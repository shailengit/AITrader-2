import { InputHTMLAttributes, TextareaHTMLAttributes, forwardRef } from 'react'

// Input
interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className={className}>
        {label && (
          <label className="block text-sm text-[var(--muted)] uppercase tracking-wider mb-2">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={`w-full bg-[var(--surface)] border border-[var(--border)] rounded-md px-4 py-3 text-[var(--foreground)] placeholder-[var(--subtle)] focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)] transition-colors ${error ? 'border-red-500' : ''}`}
          {...props}
        />
        {error && <p className="text-[var(--bad)] text-sm mt-1">{error}</p>}
      </div>
    )
  }
)
Input.displayName = 'Input'

// Textarea
interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className={className}>
        {label && (
          <label className="block text-sm text-[var(--muted)] uppercase tracking-wider mb-2">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          className={`w-full bg-[var(--surface)] border border-[var(--border)] rounded-md px-4 py-3 text-[var(--foreground)] placeholder-[var(--subtle)] focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)] transition-colors resize-none ${error ? 'border-red-500' : ''}`}
          {...props}
        />
        {error && <p className="text-[var(--bad)] text-sm mt-1">{error}</p>}
      </div>
    )
  }
)
Textarea.displayName = 'Textarea'

// Toggle - Apple Design System
interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  description?: string
  disabled?: boolean
}

export const Toggle = forwardRef<HTMLButtonElement, ToggleProps>(
  ({ checked, onChange, label, description, disabled = false }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex items-center gap-4 p-5 bg-[var(--surface)] border border-[var(--border)] rounded-lg w-full text-left transition-colors ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <div className="flex-1">
          {label && <div className="text-[17px] font-semibold text-[var(--foreground)] tracking-[-0.374px]">{label}</div>}
          {description && <div className="text-[14px] text-[var(--muted)] mt-1 tracking-[-0.224px]">{description}</div>}
        </div>
        <div
          className={`w-12 h-7 rounded-full transition-colors ${checked ? 'bg-[var(--accent)]' : 'bg-[var(--surface-overlay)]'}`}
        >
          <div
            className={`w-5 h-5 mt-1 rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`}
          />
        </div>
      </button>
    )
  }
)
Toggle.displayName = 'Toggle'