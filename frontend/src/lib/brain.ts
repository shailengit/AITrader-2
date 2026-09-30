// Typed client for /api/brain/* (Trading Brain)

import { request } from "@/lib/api";

export interface BrainStrategyStat {
  strategy_name: string;
  strategy_class_path: string;
  n_runs: number;
  n_trades: number;
  win_rate: number;
  avg_pnl: number;
  best_return_pct: number | null;
  first_run_date: string | null;
  last_run_date: string | null;
}

export interface BrainChatMessage {
  id: string;
  strategy_name: string | null;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface BrainChatResponse {
  answer: string;
  model_id: string;
  duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  bundle?: unknown;
  error?: string;
}

export interface BrainInsights {
  markdown?: string;
  generated_at?: string;
}

export interface BrainDetail {
  strategy_name: string;
  strategy_class_path: string;
  n_runs: number;
  n_trades: number;
  first_run_date: string | null;
  last_run_date: string | null;
  best_run?: Record<string, any> | null;
  worst_run?: Record<string, any> | null;
  accumulated_insights?: BrainInsights | null;
  analyzed?: boolean;
  runs?: Array<Record<string, any>>;
  aggregate?: Record<string, any>;
}

export interface ChatParams {
  question: string;
  strategy_class_path?: string;
  run_ids?: string[];
  compare_strategy?: string;
}

export const brainApi = {
  listStrategies: () =>
    request<BrainStrategyStat[]>("/brain/strategies"),

  getStrategy: (strategyClassPath: string) =>
    request<BrainDetail>(`/brain/strategy/${encodeURIComponent(strategyClassPath)}`),

  analyzeStrategy: (strategyClassPath: string) =>
    request<BrainDetail>(`/brain/strategy/${encodeURIComponent(strategyClassPath)}/analyze`, { method: "POST" }),

  chat: (params: ChatParams) =>
    request<BrainChatResponse>("/brain/chat", { method: "POST", body: params }),

  listChat: (strategyClassPath?: string) =>
    request<BrainChatMessage[]>(
      `/brain/chat${strategyClassPath ? `?strategy_class_path=${encodeURIComponent(strategyClassPath)}` : ""}`
    ),
};
