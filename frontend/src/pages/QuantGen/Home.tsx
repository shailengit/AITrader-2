import { motion } from 'framer-motion';
import {
  Terminal,
  BarChart2,
  Library,
  Layers,
  Sparkles,
  ChevronRight,
  TrendingUp,
  Target,
  Code2,
  ArrowRight,
  MessageSquare,
  Cpu,
  LineChart,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';

const fadeInUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
};

const stagger = {
  animate: { transition: { staggerChildren: 0.08 } },
};

const workflowSteps = [
  {
    icon: MessageSquare,
    title: 'Describe Your Idea',
    description: 'Tell QuantGen your strategy in plain English. Any concept works: from simple moving average crossovers to complex multi-factor models.',
    step: '01',
  },
  {
    icon: Cpu,
    title: 'AI Generates the Code',
    description: 'Your description is transformed into optimized VectorBT Python code, ready for backtesting against real market data.',
    step: '02',
  },
  {
    icon: LineChart,
    title: 'Backtest & Optimize',
    description: 'Run historical backtests, analyze equity curves, and apply walk-forward optimization to validate robustness.',
    step: '03',
  },
];

export default function QuantGenHome() {
  return (
    <div className="min-h-full" style={{ backgroundColor: 'var(--canvas)' }}>
      <div style={{ padding: '64px 80px' }}>
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          style={{ maxWidth: '1200px', margin: '0 auto' }}
        >
          {/* Hero — centered, tighter internal grouping, generous bottom margin */}
          <motion.div
            variants={fadeInUp}
            style={{
              marginBottom: '80px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '6px 16px',
                borderRadius: '999px',
                fontSize: '13px',
                fontWeight: 600,
                letterSpacing: '0.02em',
                marginBottom: '20px',
                backgroundColor: 'var(--accent)',
                color: 'var(--accent-ink)',
              }}
            >
              <Code2 size={14} />
              AI-Powered Strategy Builder
            </div>

            <h1
              style={{
                fontSize: '42px',
                fontWeight: 700,
                letterSpacing: '-0.03em',
                lineHeight: 1.1,
                color: 'var(--foreground)',
                marginBottom: '16px',
                maxWidth: '640px',
                textAlign: 'center',
                marginLeft: 'auto',
                marginRight: 'auto',
              }}
            >
              Generate Trading Strategies<br />
              <span style={{ color: 'var(--accent)' }}>with Natural Language</span>
            </h1>

            <p
              style={{
                fontSize: '17px',
                lineHeight: 1.6,
                color: 'var(--muted)',
                maxWidth: '520px',
                marginBottom: 0,
                textAlign: 'center',
                marginLeft: 'auto',
                marginRight: 'auto',
              }}
            >
              Describe your trading idea in plain English. QuantGen transforms it into backtested
              VectorBT code using real market data.
            </p>
          </motion.div>

          {/* Bento Grid: Builder hero + Dashboard/Library side stack — refined internal spacing */}
          <motion.div
            variants={fadeInUp}
            style={{
              display: 'grid',
              gridTemplateColumns: '1.6fr 1fr',
              gap: '16px',
              marginBottom: '64px',
            }}
          >
            {/* Builder — primary action, larger */}
            <NavLink
              to="/quantgen/build"
              style={{ textDecoration: 'none' }}
            >
              <div
                className="hover-lift"
                style={{
                  borderRadius: '24px',
                  padding: '40px',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--accent)',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  position: 'relative',
                  overflow: 'hidden',
                  cursor: 'pointer',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    right: 0,
                    width: '180px',
                    height: '180px',
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    opacity: 0.04,
                    pointerEvents: 'none',
                  }}
                />
                <div>
                  <div
                    style={{
                      width: '48px',
                      height: '48px',
                      borderRadius: '14px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginBottom: '20px',
                      backgroundColor: 'var(--accent-glow)',
                      color: 'var(--accent)',
                    }}
                  >
                    <Terminal size={22} />
                  </div>
                  <h2
                    style={{
                      fontSize: '22px',
                      fontWeight: 600,
                      color: 'var(--foreground)',
                      marginBottom: '8px',
                    }}
                  >
                    Strategy Builder
                  </h2>
                  <p style={{ fontSize: '14px', color: 'var(--muted)', lineHeight: 1.5, maxWidth: '360px' }}>
                    Generate trading strategies using natural language prompts with AI-powered code generation and VectorBT backtesting.
                  </p>
                </div>
                <div
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginTop: '24px',
                    padding: '10px 24px',
                    borderRadius: '999px',
                    backgroundColor: 'var(--accent)',
                    color: 'var(--accent-ink)',
                    fontSize: '14px',
                    fontWeight: 600,
                    width: 'fit-content',
                  }}
                >
                  <Sparkles size={16} />
                  Start Building
                  <ArrowRight size={16} />
                </div>
              </div>
            </NavLink>

            {/* Right column: Dashboard + Library stacked */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <NavLink to="/quantgen/dashboard" style={{ textDecoration: 'none', flex: 1 }}>
                <div
                  className="hover-lift"
                  style={{
                    borderRadius: '24px',
                    padding: '28px',
                    backgroundColor: 'var(--surface)',
                    border: '1px solid var(--border)',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                  }}
                >
                  <div
                    style={{
                      width: '40px',
                      height: '40px',
                      borderRadius: '12px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginBottom: '16px',
                      backgroundColor: 'var(--accent-glow)',
                      color: 'var(--accent)',
                    }}
                  >
                    <BarChart2 size={18} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '17px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '4px' }}>
                      Dashboard
                    </h3>
                    <p style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
                      View backtest results, equity curves, and performance metrics.
                    </p>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      marginTop: '16px',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--accent)',
                    }}
                  >
                    View Results <ChevronRight size={14} />
                  </div>
                </div>
              </NavLink>

              <NavLink to="/quantgen/library" style={{ textDecoration: 'none', flex: 1 }}>
                <div
                  className="hover-lift"
                  style={{
                    borderRadius: '24px',
                    padding: '28px',
                    backgroundColor: 'var(--surface)',
                    border: '1px solid var(--border)',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                  }}
                >
                  <div
                    style={{
                      width: '40px',
                      height: '40px',
                      borderRadius: '12px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginBottom: '16px',
                      backgroundColor: 'var(--accent-glow)',
                      color: 'var(--accent)',
                    }}
                  >
                    <Library size={18} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '17px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '4px' }}>
                      Library
                    </h3>
                    <p style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
                      Manage saved strategies, organized by performance.
                    </p>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      marginTop: '16px',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--accent)',
                    }}
                  >
                    Browse Library <ChevronRight size={14} />
                  </div>
                </div>
              </NavLink>
            </div>
          </motion.div>

          {/* Features — compact chip row */}
          <motion.div variants={fadeInUp} style={{ marginBottom: '80px' }}>
            <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
              {[
                { icon: Code2, label: 'AI Code Generation' },
                { icon: TrendingUp, label: 'VectorBT Backtesting' },
                { icon: Target, label: 'Walk-Forward Optimization' },
                { icon: Layers, label: 'Real Market Data' },
              ].map((f, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '8px 16px 8px 12px',
                    borderRadius: '999px',
                    backgroundColor: 'var(--surface)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div
                    style={{
                      width: '28px',
                      height: '28px',
                      borderRadius: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor: 'var(--accent-glow)',
                      color: 'var(--accent)',
                      flexShrink: 0,
                    }}
                  >
                    <f.icon size={13} />
                  </div>
                  <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--foreground)' }}>
                    {f.label}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>

          {/* Workflow — replaces hero-metric stats with a meaningful process section */}
          <motion.div variants={fadeInUp}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '16px',
                borderRadius: '24px',
                overflow: 'hidden',
                border: '1px solid var(--border)',
                backgroundColor: 'var(--border)',
              }}
            >
              {workflowSteps.map((step, i) => (
                <div
                  key={i}
                  style={{
                    padding: '32px',
                    backgroundColor: 'var(--surface)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '16px',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <div
                      style={{
                        width: '44px',
                        height: '44px',
                        borderRadius: '12px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: 'var(--accent-glow)',
                        color: 'var(--accent)',
                      }}
                    >
                      <step.icon size={20} />
                    </div>
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        letterSpacing: '0.1em',
                        color: 'var(--subtle)',
                      }}
                    >
                      {step.step}
                    </span>
                  </div>
                  <h3
                    style={{
                      fontSize: '18px',
                      fontWeight: 600,
                      color: 'var(--foreground)',
                      lineHeight: 1.3,
                      margin: 0,
                    }}
                  >
                    {step.title}
                  </h3>
                  <p
                    style={{
                      fontSize: '14px',
                      lineHeight: 1.6,
                      color: 'var(--muted)',
                      margin: 0,
                    }}
                  >
                    {step.description}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}
