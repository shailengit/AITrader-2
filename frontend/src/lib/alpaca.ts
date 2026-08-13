export interface LivePosition {
  ticker: string;
  qty: number;
  market_value: number;
  cost_basis: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  current_price: number;
  avg_entry_price: number;
}

export interface LiveAccount {
  equity: number;
  cash: number;
  buying_power: number;
}

export interface LivePnl {
  configured: boolean;
  reason?: string;
  paper?: boolean;
  strategy_name?: string;
  account?: LiveAccount;
  n_positions?: number;
  positions?: LivePosition[];
  total_unrealized_pl?: number;
  total_unrealized_pl_pct?: number;
}

export interface EquityCurve {
  configured: boolean;
  reason?: string;
  period?: string;
  dates?: string[];
  equity?: number[];
  start_equity?: number | null;
  end_equity?: number | null;
  change?: number | null;
  change_pct?: number | null;
}

import { request } from "@/lib/api";

export async function fetchLivePnl(): Promise<LivePnl> {
  return request<LivePnl>('/alpaca/live');
}

export async function fetchEquityCurve(
  period: string = "3M",
  timeframe: string = "1D",
): Promise<EquityCurve> {
  return request<EquityCurve>(`/alpaca/equity-curve?period=${period}&timeframe=${timeframe}`);
}
