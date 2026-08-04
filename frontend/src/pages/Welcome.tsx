import { Link } from 'react-router-dom'
import { Database, ArrowRight, Sparkles, TrendingUp, Code, Gauge, Calendar, BookOpen, FlaskConical, Terminal } from 'lucide-react'
import { ThemeToggle } from '../components/ui'
import { useTheme } from '../context/ThemeContext'

const tools = [
  {
    id: 'sectors',
    title: 'Sector Rotation',
    description: 'Identify momentum leaders across 11 sector ETFs with acceleration metrics and squeeze detection.',
    icon: TrendingUp,
    accent: '#10B981',
    link: '/sectors',
    stat: '11 ETFs tracked',
    detail: 'S&P 500 sector breakdown with leading stocks per sector',
  },
  {
    id: 'screener',
    title: 'AI Stock Screener',
    description: 'Multi-agent AI that finds dormant giants before they break out. OBV, Bollinger squeeze, EPS.',
    icon: Sparkles,
    accent: '#10B981',
    link: '/screener',
    stat: '1,500 stocks',
    detail: 'Two screening modes with Agno-powered multi-agent analysis',
  },
  {
    id: 'earnings',
    title: 'Earnings Calendar',
    description: 'Track upcoming earnings dates, EPS estimates, and revenue surprises for your watchlist and the full S&P 1500.',
    icon: Calendar,
    accent: '#10B981',
    link: '/earnings',
    stat: 'S&P 1500',
    detail: 'Earnings dates with EPS estimates and BMO/AMC timing',
  },
  {
    id: 'markov',
    title: 'Markov Chain Trader',
    description: 'Regime-aware trading signals using statistical jump models and AI pattern recognition across 11 sector ETFs.',
    icon: Gauge,
    accent: '#10B981',
    link: '/markov',
    stat: '11 ETF regimes',
    detail: 'XGBoost + regime detection with convergent signal engine',
  },
  {
    id: 'quantgen',
    title: 'Strategy Builder',
    description: 'Write, backtest, and optimize quant strategies with AI-assisted code generation and VectorBT.',
    icon: Code,
    accent: '#10B981',
    link: '/quantgen',
    stat: 'VectorBT engine',
    detail: 'True walk-forward optimization with position-aware tracking',
  },
  {
    id: 'strategy-lab',
    title: 'AI Strategy Builder',
    description: 'Describe a strategy in natural language; the LLM plans, codes, and runs 100s of backtests. Deploy the winner to Alpaca paper.',
    icon: FlaskConical,
    accent: '#10B981',
    link: '/strategy-lab',
    stat: '5-step workflow',
    detail: 'Auto-generated strategy code with OOS-validated deploy',
  },
  {
    id: 'terminal',
    title: 'AI Terminal',
    description: 'Full Claude Code CLI in your browser. Read, write, run code, git, and more.',
    icon: Terminal,
    accent: '#10B981',
    link: '/terminal',
    stat: 'Claude Code',
    detail: 'Direct project access with all tools and skills',
  },
]

export default function Welcome() {
  const { isDarkMode } = useTheme()

  const colors = {
    bg: isDarkMode ? '#050505' : '#fafaf8',
    surface: isDarkMode ? '#0a0a0a' : '#ffffff',
    text: isDarkMode ? '#ffffff' : '#1a1a18',
    muted: isDarkMode ? 'rgba(255,255,255,0.55)' : '#6b6b65',
    subtle: isDarkMode ? 'rgba(255,255,255,0.32)' : '#8e8e88',
    border: isDarkMode ? 'rgba(255,255,255,0.07)' : '#e5e5e0',
    accent: '#10B981',
    accentHover: '#059669',
    accentMuted: isDarkMode ? 'rgba(16,185,129,0.08)' : 'rgba(16,185,129,0.06)',
    btnText: isDarkMode ? '#050505' : '#ffffff',
    cardBg: isDarkMode ? 'rgba(255,255,255,0.02)' : '#ffffff',
    cardBorder: isDarkMode ? 'rgba(255,255,255,0.06)' : '#e5e5e0',
    featureBg: isDarkMode ? 'rgba(16,185,129,0.04)' : 'rgba(16,185,129,0.03)',
    featureBorder: isDarkMode ? 'rgba(16,185,129,0.12)' : 'rgba(16,185,129,0.15)',
    featureText: isDarkMode ? '#6EE7B7' : '#059669',
    numberColor: isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.04)',
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: colors.bg,
      transition: 'background-color 0.3s ease',
      color: colors.text,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '32px 40px',
        maxWidth: 1280,
        margin: '0 auto',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <div style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            backgroundColor: '#10B981',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 12,
            fontWeight: 800,
            color: '#050505',
          }}>
            TC
          </div>
          <span style={{ fontWeight: 600, fontSize: 15, letterSpacing: '-0.01em' }}>TradeCraft</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <a
              href="/user-manual.html"
              target="_blank"
              rel="noopener noreferrer"
              title="User Manual"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 14px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 500,
                color: colors.muted,
                textDecoration: 'none',
                border: `1px solid ${colors.border}`,
                transition: 'all 0.2s ease',
                cursor: 'pointer',
              }}
            >
              <BookOpen style={{ width: 14, height: 14 }} />
              Help
            </a>
            <ThemeToggle variant="ghost" size="md" />
          </div>
      </div>

      {/* Hero */}
      <div style={{ maxWidth: 880, margin: '0 auto', padding: '80px 40px 100px', textAlign: 'center' }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 20px',
          backgroundColor: colors.featureBg,
          borderRadius: 8,
          border: `1px solid ${colors.featureBorder}`,
          color: colors.featureText,
          fontSize: 13,
          fontWeight: 500,
          marginBottom: 40,
          transition: 'all 0.3s ease',
        }}>
          <Database style={{ width: 16, height: 16 }} />
          S&P 1500 · PostgreSQL · Agno AI
        </div>

        <h1 style={{
          fontSize: 64,
          fontWeight: 700,
          marginBottom: 28,
          letterSpacing: '-0.04em',
          lineHeight: 1.06,
          transition: 'color 0.3s ease',
        }}>
          Trading research,<br />
          <span style={{ color: '#10B981' }}>crafted for precision</span>
        </h1>

        <p style={{
          fontSize: 18,
          color: colors.muted,
          maxWidth: 600,
          margin: '0 auto 48px',
          lineHeight: 1.7,
          transition: 'color 0.3s ease',
        }}>
          Screen stocks with AI agents, analyze sector rotation patterns, detect market regimes, and build backtested quantitative strategies — five tools, one platform, zero compromises.
        </p>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 16,
          marginBottom: 80,
        }}>
          <Link
            to="/sectors"
            style={{
              backgroundColor: colors.accent,
              color: colors.btnText,
              padding: '14px 32px',
              borderRadius: 10,
              fontSize: 15,
              fontWeight: 600,
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              transition: 'all 0.2s ease',
              boxShadow: isDarkMode
                ? '0 0 32px rgba(16,185,129,0.3)'
                : '0 4px 16px rgba(16,185,129,0.2)',
            }}
          >
            Get started
            <ArrowRight style={{ width: 16, height: 16 }} />
          </Link>
          <a
            href="#tools-section"
            style={{
              backgroundColor: 'transparent',
              color: colors.text,
              padding: '14px 32px',
              borderRadius: 10,
              fontSize: 15,
              fontWeight: 500,
              textDecoration: 'none',
              border: `1px solid ${colors.border}`,
              display: 'inline-flex',
              alignItems: 'center',
              transition: 'all 0.2s ease',
            }}
          >
            See what's included
          </a>
        </div>

        {/* Dashboard Mockup */}
        <div style={{
          borderRadius: 16,
          padding: 8,
          backgroundColor: isDarkMode ? 'rgba(255,255,255,0.015)' : 'rgba(0,0,0,0.015)',
          border: `1px solid ${colors.border}`,
          boxShadow: isDarkMode
            ? '0 24px 48px rgba(0,0,0,0.4)'
            : '0 16px 32px rgba(0,0,0,0.06)',
          overflow: 'hidden',
        }}>
          <img
            src="/dashboard-mockup.png"
            alt="TradeCraft platform interface"
            style={{ width: '100%', height: 'auto', borderRadius: 10, display: 'block' }}
          />
        </div>
      </div>

      {/* Tools section */}
      <div id="tools-section" style={{
        maxWidth: 1000,
        margin: '0 auto',
        padding: '0 40px 100px',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 56 }}>
          <h2 style={{
            fontSize: 32,
            fontWeight: 700,
            marginBottom: 12,
            letterSpacing: '-0.03em',
          }}>
            Five tools, one workflow
          </h2>
          <p style={{ fontSize: 16, color: colors.muted }}>
            Each tool is purpose-built and works standalone or together.
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {tools.map((tool, i) => (
            <Link
              key={tool.id}
              to={tool.link}
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                gap: 32,
                alignItems: 'center',
                padding: '36px 40px',
                backgroundColor: colors.cardBg,
                border: `1px solid ${colors.cardBorder}`,
                borderRadius: 16,
                textDecoration: 'none',
                color: 'inherit',
                transition: 'all 0.25s ease',
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                  <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 10,
                    backgroundColor: colors.accentMuted,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: colors.accent,
                  }}>
                    <tool.icon style={{ width: 18, height: 18 }} />
                  </div>
                  <span style={{ fontSize: 13, color: colors.subtle, fontWeight: 500 }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </div>
                <h3 style={{
                  fontSize: 22,
                  fontWeight: 700,
                  marginBottom: 8,
                  letterSpacing: '-0.02em',
                }}>
                  {tool.title}
                </h3>
                <p style={{ fontSize: 15, color: colors.muted, lineHeight: 1.6, maxWidth: 540 }}>
                  {tool.description}
                </p>
                <p style={{ fontSize: 13, color: colors.subtle, marginTop: 12 }}>
                  {tool.detail}
                </p>
              </div>
              <div style={{
                padding: '16px 24px',
                backgroundColor: colors.accentMuted,
                borderRadius: 10,
                border: `1px solid ${isDarkMode ? 'rgba(16,185,129,0.1)' : 'rgba(16,185,129,0.12)'}`,
                color: colors.featureText,
                fontSize: 14,
                fontWeight: 600,
                whiteSpace: 'nowrap',
                textAlign: 'center',
              }}>
                {tool.stat}
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Bottom CTA */}
      <div style={{
        textAlign: 'center',
        padding: '0 40px 100px',
        maxWidth: 600,
        margin: '0 auto',
      }}>
        <div style={{
          padding: '56px 48px',
          backgroundColor: colors.cardBg,
          border: `1px solid ${colors.cardBorder}`,
          borderRadius: 20,
        }}>
          <Gauge style={{ width: 32, height: 32, color: '#10B981', marginBottom: 20 }} />
          <h2 style={{
            fontSize: 28,
            fontWeight: 700,
            marginBottom: 12,
            letterSpacing: '-0.03em',
          }}>
            Ready to start?
          </h2>
          <p style={{ fontSize: 15, color: colors.muted, marginBottom: 28, lineHeight: 1.6 }}>
            Jump into the Sector Rotation Scanner and see what's leading the market today.
          </p>
          <Link
            to="/sectors"
            style={{
              backgroundColor: colors.accent,
              color: colors.btnText,
              padding: '14px 36px',
              borderRadius: 10,
              fontSize: 15,
              fontWeight: 600,
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              transition: 'all 0.2s ease',
              boxShadow: isDarkMode
                ? '0 0 28px rgba(16,185,129,0.25)'
                : '0 4px 12px rgba(16,185,129,0.18)',
            }}
          >
            Launch Scanner
            <ArrowRight style={{ width: 16, height: 16 }} />
          </Link>
        </div>
      </div>

      {/* Footer */}
      <div style={{
        textAlign: 'center',
        padding: '32px 40px',
        borderTop: `1px solid ${colors.border}`,
        transition: 'border-color 0.3s ease',
      }}>
        <p style={{ fontSize: 13, color: colors.subtle }}>
          TradeCraft
        </p>
      </div>
    </div>
  )
}
