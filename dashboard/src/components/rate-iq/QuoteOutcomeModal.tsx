import { useState } from 'react';
import { apiFetch, API_BASE } from '../../helpers/api';
import { fmtDec } from './constants';

type Outcome = 'won' | 'lost_price' | 'lost_capacity' | 'lost_service' | 'no_response' | 'cancelled';

interface QuoteOutcomeModalProps {
  isOpen: boolean;
  onClose: () => void;
  quote: {
    id: number;
    quote_number: string;
    estimated_total: number;
    carrier_name?: string;
    pod?: string;
    final_delivery?: string;
  };
  onSuccess: () => void;
}

const OUTCOMES: { key: Outcome; label: string; icon: string; color: string; activeBg: string; activeBorder: string }[] = [
  { key: 'won',           label: 'Won',             icon: '\u{1F3C6}', color: '#00c853', activeBg: 'rgba(0,200,83,0.15)',  activeBorder: 'rgba(0,200,83,0.5)' },
  { key: 'lost_price',    label: 'Lost (Price)',     icon: '\u{1F4C9}', color: '#ef5350', activeBg: 'rgba(239,83,80,0.15)', activeBorder: 'rgba(239,83,80,0.5)' },
  { key: 'lost_capacity', label: 'Lost (Capacity)',  icon: '\u{1F69A}', color: '#ff9800', activeBg: 'rgba(255,152,0,0.15)', activeBorder: 'rgba(255,152,0,0.5)' },
  { key: 'lost_service',  label: 'Lost (Service)',   icon: '\u{26A0}\u{FE0F}',  color: '#ffc107', activeBg: 'rgba(255,193,7,0.15)', activeBorder: 'rgba(255,193,7,0.5)' },
  { key: 'no_response',   label: 'No Response',      icon: '\u{1F47B}', color: '#8B95A8', activeBg: 'rgba(139,149,168,0.15)', activeBorder: 'rgba(139,149,168,0.5)' },
  { key: 'cancelled',     label: 'Cancelled',        icon: '\u{1F6AB}', color: '#78909c', activeBg: 'rgba(120,144,156,0.15)', activeBorder: 'rgba(120,144,156,0.5)' },
];

export default function QuoteOutcomeModal({ isOpen, onClose, quote, onSuccess }: QuoteOutcomeModalProps) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async () => {
    if (!outcome) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await apiFetch(`${API_BASE}/api/quotes/${quote.id}/outcome`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome, outcome_notes: notes }),
      });
      if (res.ok) {
        onSuccess();
        onClose();
        setOutcome(null);
        setNotes('');
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.error || 'Failed to save outcome');
      }
    } catch (e: any) {
      setError(e.message || 'Network error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleBackdrop = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div onClick={handleBackdrop}
      style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}>
      <div style={{ background: '#0a0d10', border: '1px solid rgba(255,255,255,0.10)', borderRadius: 14,
        width: '100%', maxWidth: 480, padding: 24, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>

        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 18, fontWeight: 800, color: '#F0F2F5', margin: 0 }}>
            Update Outcome
          </h3>
          <div style={{ fontSize: 12, color: '#5A6478', marginTop: 4 }}>
            {quote.quote_number} &middot; {quote.pod || '?'} &rarr; {quote.final_delivery || '?'}
            {quote.estimated_total ? ` \u00B7 ${fmtDec(quote.estimated_total)}` : ''}
          </div>
        </div>

        {/* Outcome buttons */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 20 }}>
          {OUTCOMES.map(o => {
            const active = outcome === o.key;
            return (
              <button key={o.key} onClick={() => setOutcome(o.key)}
                style={{
                  padding: '10px 8px', borderRadius: 10, cursor: 'pointer', fontFamily: 'inherit',
                  fontSize: 11, fontWeight: 700, transition: 'all 0.15s', display: 'flex', flexDirection: 'column',
                  alignItems: 'center', gap: 4, lineHeight: 1.3,
                  background: active ? o.activeBg : 'rgba(255,255,255,0.03)',
                  border: `1px solid ${active ? o.activeBorder : 'rgba(255,255,255,0.06)'}`,
                  color: active ? o.color : '#8B95A8',
                }}>
                <span style={{ fontSize: 18 }}>{o.icon}</span>
                {o.label}
              </button>
            );
          })}
        </div>

        {/* Notes field — always shown when an outcome is selected */}
        {outcome && (
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: '#5A6478',
              textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>
              {outcome === 'won' ? 'Win Notes (optional)' : 'Loss Notes (optional)'}
            </label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              rows={3} placeholder={
                outcome === 'won' ? 'E.g., Carrier confirmed, booked for Monday...'
                : outcome === 'lost_price' ? 'E.g., Customer went with CH Robinson at $50 less...'
                : outcome === 'no_response' ? 'E.g., Followed up 3x, no reply from customer...'
                : 'Any context for this outcome...'
              }
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 14px', borderRadius: 10, fontSize: 13,
                fontFamily: 'inherit', color: '#F0F2F5', resize: 'vertical',
                background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
                outline: 'none',
              }}
              onFocus={e => e.currentTarget.style.borderColor = 'rgba(41,121,255,0.4)'}
              onBlur={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'}
            />
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{ fontSize: 12, color: '#ef5350', marginBottom: 12, padding: '8px 12px',
            background: 'rgba(239,83,80,0.1)', borderRadius: 8 }}>
            {error}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 16 }}>
          <button onClick={onClose}
            style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: 'transparent',
              color: '#8B95A8', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={!outcome || submitting}
            style={{
              padding: '8px 20px', borderRadius: 8, border: 'none', fontFamily: 'inherit',
              fontSize: 13, fontWeight: 700, cursor: outcome && !submitting ? 'pointer' : 'not-allowed',
              background: outcome ? 'linear-gradient(135deg, #2979ff 0%, #00b8d4 100%)' : 'rgba(255,255,255,0.06)',
              color: outcome ? '#fff' : '#5A6478', opacity: submitting ? 0.6 : 1,
              transition: 'all 0.15s',
            }}>
            {submitting ? 'Saving...' : 'Save Outcome'}
          </button>
        </div>
      </div>
    </div>
  );
}
