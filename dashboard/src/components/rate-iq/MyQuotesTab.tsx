import { useState, useEffect, useCallback } from 'react';
import { apiFetch, API_BASE } from '../../helpers/api';
import { fmtDec } from './constants';
import LaneName from './LaneName';
import QuoteOutcomeModal from './QuoteOutcomeModal';

// ── Status styling ──
const STATUS_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  draft:    { bg: 'rgba(139,149,168,0.12)', color: '#8B95A8', label: 'Draft' },
  sent:     { bg: 'rgba(41,121,255,0.12)',   color: '#2979ff', label: 'Sent' },
  accepted: { bg: 'rgba(0,200,83,0.12)',     color: '#00c853', label: 'Won' },
  lost:     { bg: 'rgba(239,83,80,0.12)',    color: '#ef5350', label: 'Lost' },
  expired:  { bg: 'rgba(120,144,156,0.12)',  color: '#78909c', label: 'Expired' },
};

const OUTCOME_BADGE: Record<string, { color: string; label: string }> = {
  won:           { color: '#00c853', label: 'Won' },
  lost_price:    { color: '#ef5350', label: 'Lost (Price)' },
  lost_capacity: { color: '#ff9800', label: 'Lost (Capacity)' },
  lost_service:  { color: '#ffc107', label: 'Lost (Service)' },
  no_response:   { color: '#8B95A8', label: 'No Response' },
  cancelled:     { color: '#78909c', label: 'Cancelled' },
};

interface Quote {
  id: number;
  quote_number: string;
  created_at: string;
  updated_at?: string;
  created_by?: string;
  status: string;
  outcome?: string;
  outcome_notes?: string;
  pod: string;
  final_delivery: string;
  shipment_type: string;
  carrier_name: string;
  margin_pct: number;
  estimated_total: number;
  carrier_total?: number;
  customer_name?: string;
  source_type?: string;
}

export default function MyQuotesTab() {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [outcomeQuote, setOutcomeQuote] = useState<Quote | null>(null);

  const loadQuotes = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100', offset: '0' });
      if (filter !== 'all') params.set('status', filter);
      if (search) params.set('search', search);
      const res = await apiFetch(`${API_BASE}/api/quotes?${params}`);
      const data = await res.json();
      setQuotes(data.quotes || []);
    } catch (e) {
      console.error('Failed to load quotes:', e);
    }
    setLoading(false);
  }, [filter, search]);

  useEffect(() => { loadQuotes(); }, [loadQuotes]);

  // Margin calc
  const margin = (q: Quote) => {
    const sell = parseFloat(String(q.estimated_total)) || 0;
    const buy = parseFloat(String(q.carrier_total)) || 0;
    if (!sell || !buy) return null;
    return { dollars: sell - buy, pct: ((sell - buy) / sell) * 100 };
  };

  // Summary stats
  const total = quotes.length;
  const wonCount = quotes.filter(q => q.outcome === 'won' || q.status === 'accepted').length;
  const lostCount = quotes.filter(q => q.outcome?.startsWith('lost_') || q.status === 'lost').length;
  const pendingCount = quotes.filter(q => !q.outcome && q.status !== 'accepted' && q.status !== 'lost' && q.status !== 'expired').length;
  const winRate = (wonCount + lostCount) > 0 ? ((wonCount / (wonCount + lostCount)) * 100).toFixed(0) : '--';

  const FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'draft', label: 'Draft' },
    { key: 'sent', label: 'Sent' },
    { key: 'accepted', label: 'Won' },
    { key: 'lost', label: 'Lost' },
  ];

  if (loading && quotes.length === 0) {
    return <div style={{ padding: 40, textAlign: 'center', color: '#5A6478' }}>Loading quotes...</div>;
  }

  return (
    <div>
      {/* Summary pills */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Total', value: total, color: '#8B95A8' },
          { label: 'Pending', value: pendingCount, color: '#2979ff' },
          { label: 'Won', value: wonCount, color: '#00c853' },
          { label: 'Lost', value: lostCount, color: '#ef5350' },
          { label: 'Win Rate', value: `${winRate}%`, color: '#00D4AA' },
        ].map(p => (
          <div key={p.label} style={{
            padding: '8px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)', flex: 1, textAlign: 'center',
          }}>
            <div style={{ fontSize: 18, fontWeight: 800, color: p.color, fontFamily: "'JetBrains Mono', monospace" }}>
              {p.value}
            </div>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#5A6478', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              {p.label}
            </div>
          </div>
        ))}
      </div>

      {/* Filters + search */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
        {FILTERS.map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            style={{
              padding: '5px 14px', borderRadius: 8, fontSize: 11, fontWeight: 700, fontFamily: 'inherit',
              cursor: 'pointer', transition: 'all 0.15s',
              background: filter === f.key ? 'rgba(41,121,255,0.15)' : 'transparent',
              border: `1px solid ${filter === f.key ? 'rgba(41,121,255,0.4)' : 'rgba(255,255,255,0.06)'}`,
              color: filter === f.key ? '#2979ff' : '#8B95A8',
            }}>
            {f.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search quotes..."
          style={{
            padding: '6px 14px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit',
            width: 200, background: 'rgba(255,255,255,0.03)', color: '#F0F2F5',
            border: '1px solid rgba(255,255,255,0.08)', outline: 'none',
          }}
          onFocus={e => e.currentTarget.style.borderColor = 'rgba(0,212,170,0.3)'}
          onBlur={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'}
        />
      </div>

      {/* Empty state */}
      {quotes.length === 0 && !loading && (
        <div style={{ padding: 40, textAlign: 'center', color: '#5A6478' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>{"\uD83D\uDCDD"}</div>
          <h3 style={{ color: '#F0F2F5', fontWeight: 800, fontSize: 18, margin: '0 0 8px' }}>No Quotes Yet</h3>
          <div style={{ fontSize: 13 }}>Create quotes from the Quote Builder. They'll appear here for tracking.</div>
        </div>
      )}

      {/* Quote rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {quotes.map(q => {
          const m = margin(q);
          const statusInfo = STATUS_STYLE[q.status] || STATUS_STYLE.draft;
          const outcomeBadge = q.outcome ? OUTCOME_BADGE[q.outcome] : null;
          const needsOutcome = q.status === 'sent' || (q.status === 'draft' && !q.outcome);
          const isDecided = !!q.outcome;

          return (
            <div key={q.id} className="glass" style={{
              borderRadius: 10, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 14,
              border: '1px solid rgba(255,255,255,0.06)', transition: 'border-color 0.15s',
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)')}>

              {/* Quote number + date */}
              <div style={{ minWidth: 100 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#F0F2F5' }}>{q.quote_number}</div>
                <div style={{ fontSize: 10, color: '#5A6478' }}>
                  {q.created_at ? new Date(q.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''}
                </div>
              </div>

              {/* Lane */}
              <div style={{ flex: 1, fontSize: 12, color: '#C8D0DC' }}>
                <LaneName raw={q.pod || ''} bold={false} stateSize={10} />
                <span style={{ color: '#5A6478', margin: '0 6px' }}>{'\u2192'}</span>
                <LaneName raw={q.final_delivery || ''} bold={false} stateSize={10} />
              </div>

              {/* Type */}
              <div style={{ fontSize: 10, fontWeight: 700, color: '#5A6478', minWidth: 50 }}>
                {q.shipment_type || ''}
              </div>

              {/* Carrier */}
              <div style={{ fontSize: 11, color: '#8B95A8', minWidth: 100, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                {q.carrier_name || ''}
              </div>

              {/* Sell rate */}
              <div style={{ minWidth: 80, textAlign: 'right' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#F0F2F5', fontFamily: "'JetBrains Mono', monospace" }}>
                  {q.estimated_total ? fmtDec(q.estimated_total) : '--'}
                </div>
                {m && (
                  <div style={{ fontSize: 10, color: m.dollars >= 0 ? '#00c853' : '#ef5350', fontFamily: "'JetBrains Mono', monospace" }}>
                    {m.dollars >= 0 ? '+' : ''}{fmtDec(m.dollars)} ({m.pct.toFixed(0)}%)
                  </div>
                )}
              </div>

              {/* Status / Outcome badge */}
              <div style={{ minWidth: 90, textAlign: 'center' }}>
                {outcomeBadge ? (
                  <span style={{
                    display: 'inline-block', padding: '3px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700,
                    background: `${outcomeBadge.color}18`, color: outcomeBadge.color,
                    border: `1px solid ${outcomeBadge.color}30`,
                  }}>
                    {outcomeBadge.label}
                  </span>
                ) : (
                  <span style={{
                    display: 'inline-block', padding: '3px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700,
                    background: statusInfo.bg, color: statusInfo.color,
                  }}>
                    {statusInfo.label}
                  </span>
                )}
              </div>

              {/* Action button */}
              <div style={{ minWidth: 36 }}>
                {!isDecided && (
                  <button onClick={() => setOutcomeQuote(q)} title="Record outcome"
                    style={{
                      width: 32, height: 32, borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)',
                      background: 'transparent', color: '#8B95A8', cursor: 'pointer', fontSize: 14,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'inherit',
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(0,212,170,0.4)'; e.currentTarget.style.color = '#00D4AA'; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#8B95A8'; }}>
                    {'\u270E'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Outcome Modal */}
      {outcomeQuote && (
        <QuoteOutcomeModal
          isOpen={!!outcomeQuote}
          onClose={() => setOutcomeQuote(null)}
          quote={outcomeQuote}
          onSuccess={loadQuotes}
        />
      )}
    </div>
  );
}
