import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../ui/ThemeToggle";
import {
  ArrowLeft, BookOpen, LayoutGrid, PieChart, Filter, Braces, CalendarDays,
  Activity, MessageSquare, FlaskConical, Lightbulb, Terminal,
} from "lucide-react";
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

interface NavItem { to: string; label: string; icon: React.ElementType; match: string; }
interface NavGroup { label: string; items: NavItem[]; }

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { to: "/",            label: "Overview",          icon: LayoutGrid,     match: "/" },
      { to: "/sectors",     label: "Sector Rotation",   icon: PieChart,       match: "/sectors" },
      { to: "/screener/build", label: "AI Screener",    icon: Filter,         match: "/screener" },
      { to: "/quantgen/build", label: "QuantGen",       icon: Braces,         match: "/quantgen" },
      { to: "/earnings",    label: "Earnings Calendar", icon: CalendarDays,   match: "/earnings" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/markov",      label: "Markov Trader",     icon: Activity,       match: "/markov" },
      { to: "/coach",       label: "Trade Coach",       icon: MessageSquare,  match: "/coach" },
      { to: "/strategy-lab",label: "Strategy Lab",      icon: FlaskConical,   match: "/strategy-lab" },
      { to: "/hypotheses",  label: "Hypotheses",        icon: Lightbulb,      match: "/hypotheses" },
      { to: "/terminal",    label: "AI Terminal",       icon: Terminal,       match: "/terminal" },
    ],
  },
];

function isActive(path: string, match: string): boolean {
  if (match === "/") return path === "/" || path === "/screener";
  return path === match || path.startsWith(match + "/");
}

function currentTitle(path: string): string {
  const exact = pageTitles[path];
  if (exact) return exact;
  if (path.startsWith("/screener")) return "AI Stock Screener";
  if (path.startsWith("/quantgen")) return "QuantGen Strategy Builder";
  return "TradeCraft";
}

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [referrer, setReferrer] = useState<ReferrerInfo | null>(null);

  useEffect(() => {
    setReferrer(getStoredReferrer());
  }, [location.pathname]);

  const border = "1px solid var(--border)";

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        overflow: "hidden",
        backgroundColor: "var(--canvas)",
        color: "var(--foreground)",
      }}
    >
      {/* ===================== Sidebar ===================== */}
      <aside
        style={{
          width: 236,
          flexShrink: 0,
          borderRight: border,
          background: "var(--surface)",
          display: "flex",
          flexDirection: "column",
          gap: 18,
          padding: "18px 12px",
        }}
      >
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "2px 8px 4px" }}>
          <div
            style={{
              width: 32, height: 32, borderRadius: 9, flexShrink: 0,
              background: "linear-gradient(135deg, var(--accent), var(--accent-dark))",
              display: "grid", placeItems: "center",
              fontWeight: 800, fontSize: 12, color: "#06231a",
              boxShadow: "0 6px 20px var(--accent-glow)",
            }}
          >
            TC
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-.02em" }}>TradeCraft</div>
            <div style={{ fontSize: 9, color: "var(--subtle)", fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", marginTop: 1 }}>
              Platform
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div style={{
                fontSize: 9, letterSpacing: ".14em", textTransform: "uppercase",
                color: "var(--subtle)", fontWeight: 600, padding: "2px 10px 6px",
              }}>
                {group.label}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(location.pathname, item.match);
                  return (
                    <button
                      key={item.to}
                      onClick={() => navigate(item.to)}
                      style={{
                        display: "flex", alignItems: "center", gap: 11,
                        padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                        fontFamily: "var(--font-sf-text)", fontSize: 13, fontWeight: active ? 600 : 500,
                        border: "none", textAlign: "left", width: "100%",
                        color: active ? "var(--foreground)" : "var(--muted)",
                        background: active
                          ? "linear-gradient(90deg, var(--accent-glow), transparent)"
                          : "transparent",
                        boxShadow: active ? "inset 0 0 0 1px var(--border)" : "none",
                      }}
                      onMouseEnter={(e) => {
                        if (!active) { e.currentTarget.style.background = "var(--surface-raised)"; e.currentTarget.style.color = "var(--foreground)"; }
                      }}
                      onMouseLeave={(e) => {
                        if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--muted)"; }
                      }}
                    >
                      <Icon size={16} style={{ color: active ? "var(--accent)" : "inherit", flexShrink: 0 }} />
                      <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
                      {active && (
                        <span style={{
                          width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                          background: "var(--accent)", boxShadow: "0 0 10px var(--accent)",
                        }} />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User */}
        <div
          style={{
            marginTop: "auto", display: "flex", alignItems: "center", gap: 11,
            padding: 10, borderRadius: 10, background: "var(--surface-raised)", border,
          }}
        >
          <div
            style={{
              width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
              background: "linear-gradient(135deg, #4f7dff, #8b5cf6)",
              display: "grid", placeItems: "center", fontWeight: 700, fontSize: 11, color: "#fff",
            }}
          >
            AK
          </div>
          <div style={{ overflow: "hidden" }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>Shailendra Kaushik</div>
            <div style={{ fontSize: 10, color: "var(--subtle)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              shailendra@tradecraft.io
            </div>
          </div>
        </div>
      </aside>

      {/* ===================== Main column ===================== */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {/* Top bar */}
        <header
          style={{
            height: 60, flexShrink: 0, borderBottom: border,
            background: "var(--canvas)",
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
            padding: "0 24px", zIndex: 10,
          }}
        >
          {/* Left: back + title */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
            {location.pathname !== "/" && (
              <button
                onClick={() => { clearAppReferrer(); navigate("/"); }}
                title="Back to Command Center"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                  fontFamily: "var(--font-sf-text)", fontSize: 12.5, fontWeight: 600,
                  background: "transparent", color: "var(--muted)", border: "none",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--foreground)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
              >
                <ArrowLeft size={16} /> Home
              </button>
            )}
            {((location.pathname === "/quantgen/dashboard" || location.pathname === "/quantgen/library") ||
              location.pathname.startsWith("/screener/build/chart/")) && referrer && (
              <button
                onClick={() => { clearAppReferrer(); navigate(referrer.path); }}
                title={`Back to ${referrer.label}`}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                  fontFamily: "var(--font-sf-text)", fontSize: 12.5, fontWeight: 600,
                  background: "transparent", color: "var(--accent)", border,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--accent-glow)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <ArrowLeft size={16} /> {referrer.label}
              </button>
            )}
            <h1 style={{
              fontSize: 17, fontWeight: 700, letterSpacing: "-.02em", margin: 0,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {currentTitle(location.pathname)}
            </h1>
          </div>

          {/* Right: regime + help + theme */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <RegimeBadge />
            <a
              href="/user-manual.html" target="_blank" rel="noopener noreferrer" title="User Manual"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "7px 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 500,
                color: "var(--muted)", textDecoration: "none", border,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-raised)"; e.currentTarget.style.color = "var(--foreground)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--muted)"; }}
            >
              <BookOpen size={14} /> Help
            </a>
            <ThemeToggle variant="ghost" size="md" />
          </div>
        </header>

        {/* Content */}
        <main style={{ flex: 1, overflow: "auto", backgroundColor: "var(--canvas)" }}>
          <Outlet />
        </main>
      </div>

      {/* TerminalHost — sibling of Outlet so route changes inside the shell
          never unmount the terminal. */}
      <TerminalHost />
    </div>
  );
}
