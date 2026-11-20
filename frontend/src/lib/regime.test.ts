import { describe, it, expect } from 'vitest';
import { formatAsOf, summarizeRegimes, type SectorRegime } from './regime';

const sector = (etf: string, regime: SectorRegime['regime'], vol: SectorRegime['vol_regime'] = 'LOW'): SectorRegime => ({
  etf,
  regime,
  bull_probability: regime === 'BULL' ? 0.9 : 0.1,
  vol_regime: vol,
  vol_probability: vol === 'HIGH' ? 0.8 : 0.2,
});

describe('formatAsOf', () => {
  it('renders an ISO date as "13 Nov"', () => {
    expect(formatAsOf('2026-11-13')).toBe('13 Nov');
  });

  it('drops the day zero-padding', () => {
    expect(formatAsOf('2026-01-05')).toBe('5 Jan');
  });

  it('returns null for missing or malformed input', () => {
    expect(formatAsOf(null)).toBeNull();
    expect(formatAsOf(undefined)).toBeNull();
    expect(formatAsOf('')).toBeNull();
    expect(formatAsOf('13/11/2026')).toBeNull();
  });
});

describe('summarizeRegimes', () => {
  it('reports the majority sector regime', () => {
    const s = [sector('XLK', 'BULL'), sector('XLF', 'BULL'), sector('XLE', 'BEAR')];
    expect(summarizeRegimes(s).overall).toBe('BULL');
  });

  it('is UNKNOWN when the vote is tied', () => {
    expect(summarizeRegimes([sector('XLK', 'BULL'), sector('XLE', 'BEAR')]).overall).toBe('UNKNOWN');
  });

  it('is UNKNOWN with no sectors', () => {
    expect(summarizeRegimes([])).toEqual({ overall: 'UNKNOWN', vol: 'UNKNOWN' });
  });

  it('marks volatility HIGH only above half the sectors', () => {
    const s = [sector('XLK', 'BULL', 'HIGH'), sector('XLF', 'BULL', 'HIGH'), sector('XLE', 'BEAR', 'LOW')];
    expect(summarizeRegimes(s).vol).toBe('HIGH');
  });
});
