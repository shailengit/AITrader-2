export interface SectorRegime {
  etf: string;
  regime: 'BULL' | 'BEAR' | 'UNKNOWN';
  bull_probability: number;
  vol_regime: 'LOW' | 'HIGH' | 'UNKNOWN';
  vol_probability: number;
}

export interface RegimeResponse {
  sector_status: SectorRegime[];
  // Latest bar the fitted regimes cover ("YYYY-MM-DD"). Absent on older backends.
  as_of?: string | null;
}

export interface RegimeSnapshot {
  sectors: SectorRegime[];
  asOf: string | null;
}

import { request } from "@/lib/api";

export async function fetchRegimeSnapshot(): Promise<RegimeSnapshot> {
  const data = await request<RegimeResponse>('/markov/regimes');
  return { sectors: data.sector_status ?? [], asOf: data.as_of ?? null };
}

export async function fetchRegimes(): Promise<SectorRegime[]> {
  return (await fetchRegimeSnapshot()).sectors;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * "2026-11-13" -> "13 Nov".
 *
 * The regime is computed from daily bars and is smoothed, so it must be shown
 * with its as-of date; without one it reads like an intraday market call.
 */
export function formatAsOf(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  const month = MONTHS[Number(m[2]) - 1];
  const day = Number(m[3]);
  if (!month || !Number.isFinite(day) || day < 1 || day > 31) return null;
  return `${day} ${month}`;
}

export function summarizeRegimes(sectors: SectorRegime[]): {
  overall: 'BULL' | 'BEAR' | 'UNKNOWN';
  vol: 'LOW' | 'HIGH' | 'UNKNOWN';
} {
  if (sectors.length === 0) return { overall: 'UNKNOWN', vol: 'UNKNOWN' };
  const bullCount = sectors.filter(s => s.regime === 'BULL').length;
  const bearCount = sectors.filter(s => s.regime === 'BEAR').length;
  const highVolCount = sectors.filter(s => s.vol_regime === 'HIGH').length;
  return {
    overall: bullCount > bearCount ? 'BULL' : (bearCount > bullCount ? 'BEAR' : 'UNKNOWN'),
    vol: highVolCount > sectors.length / 2 ? 'HIGH' : 'LOW',
  };
}
