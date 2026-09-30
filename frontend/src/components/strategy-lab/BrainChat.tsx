// Trading Brain chat panel for the Strategy Lab Backtest tab.
// Lets the user ask any question about a strategy's accumulated backtest
// experiment data (per-strategy or global) and get an LLM-backed answer
// grounded in the actual per-trade + run data the Brain has collected.
import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Send, Loader2, Sparkles, MessageSquareWarning } from "lucide-react";
import { brainApi, type BrainChatMessage } from "../../lib/brain";
import { BrainInsights } from "./BrainInsights";
import { MarkdownView } from "./MarkdownView";

interface BrainChatProps {
  strategyClassPath: string;
}

const QUICK_QUESTIONS = [
  "Which exit/losing pattern is most common in this strategy?",
  "How consistent is this strategy across different start dates?",
  "What's the win rate and average P&L across all its runs?",
  "Which strategies in the library perform the best overall?",
];

export function BrainChat({ strategyClassPath }: BrainChatProps) {
  const qc = useQueryClient();
  const [messages, setMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Load past chat history for this strategy
  const { data: history } = useQuery({
    queryKey: ["brain-chat", strategyClassPath],
    queryFn: () => brainApi.listChat(strategyClassPath),
  });

  useEffect(() => {
    if (history && history.length > 0) {
      setMessages(history.map((m: BrainChatMessage) => ({ role: m.role, content: m.content })));
    }
  }, [history]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Brain detail (analyzed insights, best/worst run)
  const { data: brain } = useQuery({
    queryKey: ["brain-detail", strategyClassPath],
    queryFn: () => brainApi.getStrategy(strategyClassPath),
  });

  const analyzeMut = useMutation({
    mutationFn: () => brainApi.analyzeStrategy(strategyClassPath),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["brain-detail", strategyClassPath] });
    },
  });

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const res = await brainApi.chat({ question: q, strategy_class_path: strategyClassPath });
      if (res.error) {
        setError(res.error);
      } else {
        setMessages((m) => [...m, { role: "assistant", content: res.answer }]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach the Brain");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="slab-panel" style={{ maxWidth: 1280 }}>
      <div className="slab-panel__head">
        <span className="slab-eyebrow slab-eyebrow--gold">// Trading Brain</span>
        <span className="slab-mono slab-mono--xs slab-mono--dim">
          answers grounded in this strategy's accumulated experiment data
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            type="button"
            className="slab-btn slab-btn--xs slab-btn--ghost"
            onClick={() => {
              analyzeMut.mutate();
            }}
            disabled={analyzeMut.isPending}
            title="Re-scan all accumulated data and detect patterns"
          >
            <Sparkles size={11} />
            {analyzeMut.isPending ? "Analyzing…" : "Analyze"}
          </button>
        </span>
      </div>

      <div className="slab-panel__body">
        {brain && brain.accumulated_insights?.markdown && (
          <div style={{ marginBottom: 12, padding: 12, borderRadius: 10, background: "var(--surface-raised)", border: "1px solid var(--border)", maxHeight: 320, overflow: "auto" }}>
            <BrainInsights
              markdown={brain.accumulated_insights.markdown}
              strategyName={brain.strategy_name}
              bestRunLabel={brain.best_run?.run_index != null ? `run-${brain.best_run.run_index}` : undefined}
              bestReturnPct={brain.best_run?.total_return_pct}
            />
          </div>
        )}

        <div style={{ maxHeight: 340, overflow: "auto", display: "flex", flexDirection: "column", gap: 10, padding: "4px 0" }}>
          {messages.length === 0 && (
            <div className="slab-mono slab-mono--sm slab-mono--dim" style={{ padding: 12, textAlign: "center" }}>
              Ask the Trading Brain anything about this strategy's performance, patterns, or how runs compare.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "88%",
              padding: "10px 14px",
              borderRadius: 10,
              background: m.role === "user" ? "var(--accent-glow)" : "var(--surface-raised)",
              border: "1px solid var(--border)",
              color: "var(--foreground)",
              wordBreak: "break-word",
            }}>
              {m.role === "user" ? (
                <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{m.content}</div>
              ) : (
                <MarkdownView markdown={m.content} />
              )}
            </div>
          ))}
          {loading && (
            <div style={{ alignSelf: "flex-start", padding: "10px 14px", borderRadius: 10, background: "var(--surface-raised)", border: "1px solid var(--border)", fontSize: 13, color: "var(--subtle)", display: "flex", alignItems: "center", gap: 8 }}>
              <Loader2 size={13} className="spin" style={{ animation: "spin 1s linear infinite" }} />
              Brain is thinking…
            </div>
          )}
          {error && (
            <div style={{ alignSelf: "flex-start", padding: 10, borderRadius: 8, background: "var(--bad-bg, rgba(255,80,80,0.1))", color: "var(--bad)", fontSize: 12 }}>
              <MessageSquareWarning size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
              {error}
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          {QUICK_QUESTIONS.map((qq) => (
            <button key={qq} type="button" className="slab-btn slab-btn--xs slab-btn--ghost" onClick={() => send(qq)} disabled={loading}>
              {qq}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={`Ask about ${strategyClassPath.split("/").pop()?.replace(".py", "")}…`}
            rows={2}
            className="slab-textarea"
            style={{ flex: 1, resize: "vertical" }}
          />
          <button type="button" className="slab-btn slab-btn--terminal" onClick={() => send(input)} disabled={loading || !input.trim()}>
            <Send size={13} />
            Ask
          </button>
        </div>
      </div>
    </div>
  );
}
