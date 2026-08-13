import { useNavigate } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import TickerMetadataPanel, { type TickerDetail } from '../../../../components/shared/TickerMetadataPanel';
import { recordAppReferrer } from '../../../../components/layout/Layout';

interface MetadataRailProps {
  ticker: string;
  data: TickerDetail | null;
  loading: boolean;
  error: string | null;
  fromDate?: string;
}

/**
 * Left-rail content for the standalone chart view. Renders the shared
 * TickerMetadataPanel above a "Export to Lab" action button.
 */
export default function MetadataRail({ ticker, data, loading, error, fromDate }: MetadataRailProps) {
  const navigate = useNavigate();
  const colors = {
    accent: 'var(--accent)',
  };

  return (
    <div>
      <TickerMetadataPanel data={data} loading={loading} error={error} variant="rail" />
      <button
        onClick={() => {
          // Record the referrer first so QuantGen's "Back to Custom
          // Screener" button can return to the chart view (or to the
          // builder via Layout's referrer-based navigation).
          recordAppReferrer('/screener/build', 'Custom Screener');
          const from = fromDate || new Date().toISOString().split('T')[0];
          navigate(`/quantgen/build?tickers=${encodeURIComponent(ticker)}&from_date=${from}`);
        }}
        style={{
          marginTop: 12,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
          width: '100%',
          padding: '10px 14px',
          borderRadius: 8,
          border: 'none',
          backgroundColor: colors.accent,
          color: 'var(--accent-ink)',
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        <ExternalLink size={13} />
        Export to Lab
      </button>
    </div>
  );
}
