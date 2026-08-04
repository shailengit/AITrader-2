import { useEffect, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card } from '../../components/ui/Card';
import { KPICards } from './KPICards';
import { EquityCurve } from './EquityCurve';
import { RegimeAttribution } from './RegimeAttribution';
import { MAEvsMFE } from './MAEvsMFE';
import { WinRateByStrategy } from './WinRateByStrategy';
import { ReportView } from './ReportView';
import { DateRangePicker, presetRange, type DateRange } from './DateRangePicker';
import { coachApi, type ReportDetail, type MAEMFEPoint } from '../../lib/coach';

export default function CoachIndex() {
  const [range, setRange] = useState<DateRange>(presetRange(30));
  const [latest, setLatest] = useState<ReportDetail | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  // The Command Center links here with ?strategy=<strategy_path>. It is a file
  // path (e.g. "strategies/<file>.py"), not a UUID. The overview endpoint only
  // filters by a UUID strategy_id, so we reflect the filter in the query key /
  // header chip but cannot pass the path through without a 422. See task report.
  const strategyFilter = searchParams.get('strategy');

  const overview = useQuery({
    queryKey: ['coach-overview', range, strategyFilter],
    queryFn: () => coachApi.overview({ period_start: range.start, period_end: range.end }),
  });

  const maeMfe = useQuery({
    queryKey: ['coach-mae-mfe', range],
    queryFn: () => coachApi.maeMfe({ period_start: range.start, period_end: range.end }),
  });

  const reports = useQuery({
    queryKey: ['coach-reports'],
    queryFn: () => coachApi.listReports(20),
  });

  useEffect(() => {
    if (reports.data && reports.data.length > 0 && !latest) {
      coachApi.getReport(reports.data[0].id).then(setLatest).catch(() => {});
    }
  }, [reports.data, latest]);

  const generate = useMutation({
    mutationFn: () => coachApi.generateReport({ period_start: range.start, period_end: range.end }),
    onSuccess: (r) => {
      setLatest(r);
      qc.invalidateQueries({ queryKey: ['coach-reports'] });
    },
  });

  useEffect(() => {
    if (!generate.isPending) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 500);
    return () => clearInterval(t);
  }, [generate.isPending]);

  const o = overview.data;
  const isEmpty = o && (o.empty === true || (o.kpis && o.kpis.n_trades === 0 && (!o.win_rate_by_strategy || o.win_rate_by_strategy.length === 0)));

  return (
    <div className="mx-auto max-w-[1280px] space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-zinc-100">Trade Coach</h1>
          {strategyFilter && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 6, background: 'rgba(16,185,129,.1)' }}>
              <span style={{ fontSize: 12 }}>Strategy: {strategyFilter}</span>
              <Link to="/coach" style={{ fontSize: 12, opacity: .7, textDecoration: 'none' }} title="Clear strategy filter">×</Link>
            </div>
          )}
        </div>
        <DateRangePicker value={range} onChange={setRange} />
      </div>

      {isEmpty ? (
        <Card className="p-6">
          <div className="text-zinc-300">
            Run a screener, take a paper trade, and your Coach will start learning from your activity.
          </div>
        </Card>
      ) : o ? (
        <>
          {o.kpis && <KPICards k={o.kpis} />}
          <div className="grid grid-cols-2 gap-4">
            <Card className="p-6">
              <div className="mb-2 text-sm text-zinc-400">Equity Curve</div>
              <EquityCurve data={o.equity_curve ?? []} />
            </Card>
            <Card className="p-6">
              <div className="mb-2 text-sm text-zinc-400">P&L by Regime</div>
              <RegimeAttribution data={o.pnl_by_regime ?? {}} />
            </Card>
            <Card className="p-6">
              <div className="mb-2 text-sm text-zinc-400">MAE vs MFE</div>
              <MAEvsMFE data={(maeMfe.data ?? []) as MAEMFEPoint[]} />
            </Card>
            <Card className="p-6">
              <div className="mb-2 text-sm text-zinc-400">Win Rate by Strategy</div>
              <WinRateByStrategy data={o.win_rate_by_strategy ?? []} />
            </Card>
          </div>
        </>
      ) : (
        <Card className="p-6">
          <div className="text-zinc-500">Loading metrics…</div>
        </Card>
      )}

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-sm text-zinc-400">Latest Coach Report</div>
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="rounded-md border border-emerald-700 px-3 py-1 text-sm text-emerald-400 hover:bg-emerald-900/30 disabled:opacity-50"
          >
            {generate.isPending ? `Generating… (${elapsed}s)` : 'Regenerate ↻'}
          </button>
        </div>
        {generate.isError && (
          <div className="mb-4 rounded-md border border-rose-700 bg-rose-950/30 p-3 text-sm text-rose-300">
            Critique unavailable, metrics are up-to-date.
          </div>
        )}
        {latest ? (
          <ReportView markdown={latest.report_md} />
        ) : (
          <div className="text-zinc-500">No report yet. Click Regenerate.</div>
        )}
      </Card>

      <Card className="p-6">
        <div className="mb-2 text-sm text-zinc-400">Past Reports</div>
        <ul className="space-y-1 text-sm">
          {(reports.data ?? []).length === 0 ? (
            <li className="text-zinc-500">No reports yet.</li>
          ) : (
            (reports.data ?? []).map((r) => (
              <li
                key={r.id}
                className="flex items-center justify-between border-t border-zinc-800 py-2"
              >
                <span>
                  {r.generated_at.slice(0, 10)} · {r.period_start} → {r.period_end} ·{' '}
                  {r.model_id} · {r.duration_ms ?? '?'}ms
                </span>
                <button
                  onClick={() => coachApi.getReport(r.id).then(setLatest)}
                  className="rounded-md border border-zinc-700 px-2 py-1 text-xs hover:bg-zinc-800"
                >
                  View
                </button>
              </li>
            ))
          )}
        </ul>
      </Card>
    </div>
  );
}
