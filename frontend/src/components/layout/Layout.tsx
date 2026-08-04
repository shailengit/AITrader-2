import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../ui/ThemeToggle";
import { ArrowLeft, BookOpen, Terminal } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import { useEffect, useState } from "react";
import { TerminalHost } from "../terminal/TerminalHost";
import { RegimeBadge } from "../shared/RegimeBadge";

const pageTitles: Record<string, string> = {
  "/sectors": "Sector Rotation Scanner",
  "/screener": "AI Stock Screener",
  "/earnings": "Earnings Calendar",
  "/quantgen": "QuantGen Strategy Builder",
  "/markov": "Markov Chain Trader",
  "/coach": "Trade Coach",
  "/strategy-lab": "AI Strategy Builder",
  "/terminal": "AI Terminal",
  "/hypotheses": "Hypothesis Backlog",
};

const REFERRER_KEY = "tc_last_app_referrer";

interface ReferrerInfo {
  path: string;
  label: string;
}

function getStoredReferrer(): ReferrerInfo | null {
  try {
    const raw = sessionStorage.getItem(REFERRER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.path && parsed?.label) return parsed as ReferrerInfo;
  } catch {}
  return null;
}

export function recordAppReferrer(path: string, label: string) {
  try {
    sessionStorage.setItem(REFERRER_KEY, JSON.stringify({ path, label }));
  } catch {}
}

export function clearAppReferrer() {
  try {
    sessionStorage.removeItem(REFERRER_KEY);
  } catch {}
}

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const isSectorPage = location.pathname === "/sectors";
  const { isDarkMode } = useTheme();
  const [referrer, setReferrer] = useState<ReferrerInfo | null>(null);

  useEffect(() => {
    setReferrer(getStoredReferrer());
  }, [location.pathname]);

  // Theme-aware colors
  const colors = {
    bg: isDarkMode ? "#050505" : "#f5f5f7",
    headerBg: isDarkMode ? "#0a0a0a" : "#ffffff",
    text: isDarkMode ? "#ffffff" : "#1d1d1f",
    muted: isDarkMode ? "rgba(255,255,255,0.7)" : "#6e6e73",
    border: isDarkMode ? "rgba(255,255,255,0.08)" : "#d2d2d7",
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: colors.bg,
        color: colors.text,
        overflow: "hidden",
        transition: "background-color 0.3s ease, color 0.3s ease",
      }}
    >
      {/* Top Bar */}
      <header
        style={{
          height: isSectorPage ? 120 : 64,
          borderBottom: `1px solid ${colors.border}`,
          backgroundColor: colors.headerBg,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          zIndex: 10,
          flexShrink: 0,
          padding: "0 24px",
          transition: "background-color 0.3s ease, border-color 0.3s ease",
        }}
      >
        {location.pathname !== "/" && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexShrink: 0 }}>
            <button
              onClick={() => {
                clearAppReferrer();
                navigate("/");
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 16px",
                borderRadius: "8px",
                border: "none",
                cursor: "pointer",
                backgroundColor: "transparent",
                color: colors.muted,
                fontSize: "14px",
                fontWeight: 500,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = colors.text)}
              onMouseLeave={(e) => (e.currentTarget.style.color = colors.muted)}
            >
              <ArrowLeft size={18} />
              Home
            </button>
            {(location.pathname === "/quantgen/dashboard" || location.pathname === "/quantgen/library") && (
              <button
                onClick={() => {
                  clearAppReferrer();
                  navigate("/quantgen/build");
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  border: `1px solid ${colors.border}`,
                  cursor: "pointer",
                  backgroundColor: "transparent",
                  color: "#10B981",
                  fontSize: "14px",
                  fontWeight: 600,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "rgba(16, 185, 129, 0.1)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <ArrowLeft size={18} />
                Back to Builder
              </button>
            )}
            {(location.pathname === "/quantgen/build" ||
              location.pathname.startsWith("/screener/build/chart/")) &&
              referrer && (
                <button
                  onClick={() => {
                    clearAppReferrer();
                    navigate(referrer.path);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    border: `1px solid ${colors.border}`,
                    cursor: "pointer",
                    backgroundColor: "transparent",
                    color: "#10B981",
                    fontSize: "14px",
                    fontWeight: 600,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = "rgba(16, 185, 129, 0.1)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  <ArrowLeft size={18} />
                  Back to {referrer.label}
                </button>
              )}
            {location.pathname !== "/terminal" && (
              <button
                onClick={() => {
                  clearAppReferrer();
                  navigate("/terminal");
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  border: `1px solid ${colors.border}`,
                  cursor: "pointer",
                  backgroundColor: "transparent",
                  color: "#10B981",
                  fontSize: "14px",
                  fontWeight: 600,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "rgba(16, 185, 129, 0.1)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <Terminal size={18} />
                AI Terminal
              </button>
            )}
          </div>
        )}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
            flex: 1,
            justifyContent: "center",
          }}
        >
          {/* Logo Icon */}
          <div
            style={{
              width: isSectorPage ? 64 : 36,
              height: isSectorPage ? 64 : 36,
              borderRadius: 16,
              background: "linear-gradient(135deg, #10B981 0%, #059669 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 4px 20px rgba(16, 185, 129, 0.3)",
            }}
          >
            <svg
              width={isSectorPage ? 36 : 20}
              height={isSectorPage ? 36 : 20}
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth="2.5"
            >
              <path d="M3 12h18M12 3v18" />
            </svg>
          </div>

          {/* Title */}
          <div>
            <h1
              style={{
                fontSize: isSectorPage ? "48px" : "18px",
                fontWeight: 700,
                color: colors.text,
                letterSpacing: "-0.02em",
                margin: 0,
                transition: "color 0.3s ease",
              }}
            >
              {pageTitles[location.pathname] || (location.pathname.startsWith("/quantgen")
                ? "QuantGen Strategy Builder"
                : "TradeCraft")}
            </h1>
            {isSectorPage && (
              <p
                style={{
                  fontSize: "16px",
                  color: colors.muted,
                  margin: "4px 0 0 0",
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                  transition: "color 0.3s ease",
                }}
              >
                Identify momentum and rotation patterns
              </p>
            )}
          </div>
        </div>

        {/* Regime Badge + Help + Theme Toggle */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <RegimeBadge />
          <a
            href="/user-manual.html"
            target="_blank"
            rel="noopener noreferrer"
            title="User Manual"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 500,
              color: colors.muted,
              textDecoration: "none",
              border: `1px solid ${colors.border}`,
              transition: "all 0.2s ease",
              cursor: "pointer",
            }}
          >
            <BookOpen size={14} />
            Help
          </a>
          <ThemeToggle variant="ghost" size="md" />
        </div>
      </header>

      {/* Page Content */}
      <main
        style={{
          flex: 1,
          overflow: "auto",
          backgroundColor: colors.bg,
          transition: "background-color 0.3s ease",
        }}
      >
        <Outlet />
      </main>

      {/* TerminalHost — sibling of Outlet so route changes inside the
          shell never unmount the terminal. TerminalHost reads
          useLocation and morphs between full-page (when route is
          /terminal) and FloatingPanel (anywhere else inside Layout). */}
      <TerminalHost />
    </div>
  );
}
