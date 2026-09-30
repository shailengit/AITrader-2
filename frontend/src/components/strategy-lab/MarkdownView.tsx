// Professional markdown renderer for the Trading Brain chat responses.
// Uses react-markdown + remark-gfm with custom component styling so tables,
// lists, headers, and inline code look clean and readable instead of raw text.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const base = {
  color: "var(--foreground)",
  fontSize: 13,
  lineHeight: 1.6,
};

const components = {
  h1: ({ children }: any) => (
    <div style={{ fontSize: 16, fontWeight: 700, margin: "10px 0 6px", color: "var(--foreground)" }}>{children}</div>
  ),
  h2: ({ children }: any) => (
    <div style={{ fontSize: 14, fontWeight: 700, margin: "10px 0 5px", color: "var(--accent)", letterSpacing: "0.01em" }}>{children}</div>
  ),
  h3: ({ children }: any) => (
    <div style={{ fontSize: 13, fontWeight: 700, margin: "8px 0 4px", color: "var(--foreground)" }}>{children}</div>
  ),
  p: ({ children }: any) => (
    <p style={{ margin: "6px 0", ...base }}>{children}</p>
  ),
  strong: ({ children }: any) => (
    <strong style={{ fontWeight: 700, color: "var(--foreground)" }}>{children}</strong>
  ),
  em: ({ children }: any) => <em style={{ fontStyle: "italic" }}>{children}</em>,
  code: ({ children }: any) => (
    <code style={{
      fontFamily: "var(--font-mono, ui-monospace, monospace)",
      fontSize: "0.9em", background: "var(--surface)", padding: "1px 5px",
      borderRadius: 4, border: "1px solid var(--border)",
    }}>{children}</code>
  ),
  pre: ({ children }: any) => (
    <pre style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: "10px 12px", overflow: "auto",
      fontSize: 12, fontFamily: "var(--font-mono, ui-monospace, monospace)",
      margin: "8px 0",
    }}>{children}</pre>
  ),
  ul: ({ children }: any) => (
    <ul style={{ margin: "6px 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>{children}</ul>
  ),
  ol: ({ children }: any) => (
    <ol style={{ margin: "6px 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 }}>{children}</ol>
  ),
  li: ({ children }: any) => (
    <li style={{ ...base, margin: 0 }}>{children}</li>
  ),
  table: ({ children }: any) => (
    <div style={{ overflowX: "auto", margin: "8px 0", borderRadius: 8, border: "1px solid var(--border)" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>{children}</table>
    </div>
  ),
  thead: ({ children }: any) => (
    <thead style={{ background: "var(--surface)" }}>{children}</thead>
  ),
  th: ({ children }: any) => (
    <th style={{
      textAlign: "left", padding: "6px 10px", fontWeight: 700,
      color: "var(--foreground)", borderBottom: "1px solid var(--border)",
      whiteSpace: "nowrap",
    }}>{children}</th>
  ),
  td: ({ children }: any) => (
    <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", color: "var(--foreground)" }}>{children}</td>
  ),
  blockquote: ({ children }: any) => (
    <blockquote style={{
      margin: "8px 0", padding: "6px 12px", borderLeft: "3px solid var(--accent)",
      background: "var(--surface)", borderRadius: "0 6px 6px 0", color: "var(--subtle)",
    }}>{children}</blockquote>
  ),
  hr: () => <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "10px 0" }} />,
};

export function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <div style={{ ...base }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
