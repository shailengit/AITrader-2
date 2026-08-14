import { useEffect, useState } from "react";
import { strategyLabApi, type ExperimentRow } from "../lib/strategyLab";
import { loadBatchState, type ActiveBatchState } from "../lib/strategyLabBatch";

export interface ActiveBatchInfo {
  batch: ActiveBatchState | null;
  experiments: ExperimentRow[];
  completed: number;
  failed: number;
  total: number;
  /** Sum of completed + failed sell trades across completed runs so far. */
  tradesSoFar: number;
  isRunning: boolean;
}

/**
 * Tracks the currently-active backtest batch (persisted in sessionStorage).
 * Polls its experiments every 2s so any component (Strategy Lab nav, Library,
 * sidebar) can show a live "Backtesting" indicator + progress.
 */
export function useActiveBatch(): ActiveBatchInfo {
  const [batch] = useState<ActiveBatchState | null>(() => loadBatchState());
  const [experiments, setExperiments] = useState<ExperimentRow[]>([]);
  const [progress, setProgress] = useState({ completed: 0, failed: 0 });

  useEffect(() => {
    if (!batch?.batchId) return;
    let active = true;
    const poll = async () => {
      try {
        const rows = await strategyLabApi.listBatchExperiments("_", batch.batchId);
        if (!active) return;
        setExperiments(rows);
        const completed = rows.filter((r) => r.status === "completed").length;
        const failed = rows.filter((r) => r.status === "failed").length;
        setProgress({ completed, failed });
      } catch {
        // ignore transient poll errors
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [batch?.batchId]);

  const total = batch?.nRuns ?? 0;
  const isRunning = !!batch?.batchId && progress.completed + progress.failed < total;
  const tradesSoFar = experiments
    .filter((r) => r.status === "completed")
    .reduce((sum, r) => sum + (r.kpis?.total_trades ?? 0), 0);

  return { batch, experiments, completed: progress.completed, failed: progress.failed, total, tradesSoFar, isRunning };
}
