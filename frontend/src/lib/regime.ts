export interface SectorRegime {
  etf: string;
  regime: 'BULL' | 'BEAR' | 'UNKNOWN';
  bull_probability: number;
  vol_regime: 'LOW' | 'HIGH' | 'UNKNOWN';
  vol_probability: number;
}

export interface RegimeResponse {
  sector_status: SectorRegime[];
}

export async function fetchRegimes(): Promise<SectorRegime[]> {
  const res = await fetch('/api/markov/regimes');
  if (!res.ok) throw new Error(`regime fetch failed: ${res.status}`);
  const data: RegimeResponse = await res.json();
  return data.sector_status ?? [];
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
