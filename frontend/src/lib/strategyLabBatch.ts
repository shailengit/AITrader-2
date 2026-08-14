export const STORAGE_KEY_BATCH = "strategy_lab_active_batch";

export interface ActiveBatchState {
  batchId: string;
  strategyClassPath: string;
  nRuns: number;
  endDate: string;
  startDateMin: string;
  startDateMax: string;
}

export function loadBatchState(): ActiveBatchState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY_BATCH);
    if (!raw) return null;
    return JSON.parse(raw) as ActiveBatchState;
  } catch {
    return null;
  }
}

export function saveBatchState(state: ActiveBatchState) {
  sessionStorage.setItem(STORAGE_KEY_BATCH, JSON.stringify(state));
}

export function clearBatchState() {
  sessionStorage.removeItem(STORAGE_KEY_BATCH);
}
