import { useEffect, useState } from 'react';
import { Card } from '../../components/ui/Card';
import { TradeTable } from './TradeTable';
import { TradeForm } from './TradeForm';
import { coachApi, type Trade } from '../../lib/coach';

export default function CoachTrades() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const data = await coachApi.listTrades({ limit: 200 });
      setTrades(data.rows);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="mx-auto max-w-[1280px] space-y-6 p-6">
      <h1 className="text-2xl font-semibold text-[color:var(--foreground)]">Trades</h1>
      <Card className="p-6">
        <div className="text-sm text-[color:var(--muted)] mb-3">Add a paper trade</div>
        <TradeForm onCreated={load} />
      </Card>
      <Card className="p-6">
        <div className="text-sm text-[color:var(--muted)] mb-3">
          {loading ? 'Loading…' : `${total} trade(s) on record`}
        </div>
        <TradeTable rows={trades} onChanged={load} />
      </Card>
    </div>
  );
}
