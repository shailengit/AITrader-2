// Professional renderer for the Trading Brain's "Learned Insights".
// Parses the LLM's markdown into structured, styled section cards instead of
// dumping raw markdown text. Handles ## sections, bullet/numbered lists, bold,
// and inline code.
import { useMemo } from "react";
import { CheckCircle2, XCircle, Lightbulb, Wrench, TrendingUp, Sparkles } from "lucide-react";

interface BrainInsightsProps {
  markdown: string;
  strategyName: string;
  bestRunLabel?: string;
  bestReturnPct?: number | null;
}

interface Section {
  title: string;
  items: string[];
  kind: "works" | "doesnt" | "patterns" | "tweaks" | "other";
}

const SECTION_META: Record<Section["kind"], { icon: React.ReactNode; accent: string; label: string }> = {
  works: { icon: <CheckCircle2 size={14} />, accent: "var(--good)", label: "What Works" },
  doesnt: { icon: <XCircle size={14} />, accent: "var(--bad)", label: "What Doesn't Work" },
  patterns: { icon: <Lightbulb size={14} />, accent: "var(--accent)", label: "Pattern Insights" },
  tweaks: { icon: <Wrench size={14} />, accent: "var(--gold, #e8b84b)", label: "Concrete Tweaks" },
  other: { icon: <Sparkles size={14} />, accent: "var(--subtle)", label: "" },
};

function classifyTitle(title: string): Section["kind"] {
  const t = title.toLowerCase();
  if (t.includes("works")) return "works";
  if (t.includes("doesn") || t.includes("does not")) return "doesnt";
  if (t.includes("pattern")) return "patterns";
  if (t.includes("tweak") || t.includes("suggest") || t.includes("recommend")) return "tweaks";
  return "other";
}

// Render inline markdown: **bold**, `code`, *italic*
function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**") && tok.endsWith("**")) {
      parts.push(<strong key={key++} style={{ fontWeight: 700 }}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`") && tok.endsWith("`")) {
      parts.push(
        <code key={key++} style={{
          fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: "0.92em",
          background: "var(--surface)", padding: "1px 5px", borderRadius: 4,
          border: "1px solid var(--border)",
        }}>{tok.slice(1, -1)}</code>
      );
    } else if (tok.startsWith("*") && tok.endsWith("*")) {
      parts.push(<em key={key++} style={{ fontStyle: "italic" }}>{tok.slice(1, -1)}</em>);
    } else {
      parts.push(tok);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function parseSections(markdown: string): Section[] {
  const lines = markdown.split("\n");
  const sections: Section[] = [];
  let current: Section | null = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const h = line.match(/^#{1,3}\s+(.*)$/);
    if (h) {
      const title = h[1].trim();
      current = { title, items: [], kind: classifyTitle(title) };
      sections.push(current);
      continue;
    }
    if (!current) continue;
    // bullet or numbered item
    const item = line.match(/^[-*]\s+(.*)$/) || line.match(/^\d+[.)]\s+(.*)$/);
    if (item) {
      current.items.push(item[1].trim());
    } else if (line.startsWith("|")) {
      // table row — skip for now (insights are list-based)
      continue;
    } else {
      // plain paragraph — treat as a single item
      current.items.push(line);
    }
  }
  return sections.filter((s) => s.items.length > 0);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function BrainInsights({ markdown, strategyName, bestRunLabel, bestReturnPct }: BrainInsightsProps) {
  const sections = useMemo(() => parseSections(markdown), [markdown]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 2 }}>
        <TrendingUp size={14} style={{ color: "var(--accent)" }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>
          Learned Insights
        </span>
        <span style={{ fontSize: 12, color: "var(--subtle)" }}>
          {strategyName}
          {bestRunLabel ? ` · best ${bestRunLabel}` : ""}
          {bestReturnPct != null ? ` (${fmtPct(bestReturnPct)})` : ""}
        </span>
      </div>

      {sections.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--subtle)" }}>{markdown}</div>
      ) : (
        sections.map((s, i) => {
          const meta = SECTION_META[s.kind];
          return (
            <div key={i} style={{
              borderRadius: 10, border: "1px solid var(--border)",
              background: "var(--surface-raised)", overflow: "hidden",
            }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 12px", borderBottom: "1px solid var(--border)",
                background: "var(--surface)",
              }}>
                <span style={{ color: meta.accent, display: "flex", alignItems: "center" }}>{meta.icon}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: "var(--foreground)", letterSpacing: "0.02em" }}>
                  {s.title}
                </span>
              </div>
              <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
                {s.items.map((item, j) => (
                  <div key={j} style={{ display: "flex", gap: 8, fontSize: 12.5, lineHeight: 1.55, color: "var(--foreground)" }}>
                    <span style={{
                      flexShrink: 0, marginTop: 6, width: 5, height: 5, borderRadius: "50%",
                      background: meta.accent, opacity: 0.7,
                    }} />
                    <span style={{ flex: 1 }}>{renderInline(item)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
