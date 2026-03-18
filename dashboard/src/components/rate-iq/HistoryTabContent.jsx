import React, { useEffect } from 'react';
import { fmtDec } from './constants';
import LaneName from './LaneName';

export default function HistoryTabContent({ rateHistory, historyLoading, onLoad }) {
  useEffect(() => { onLoad(); }, []);
  if (historyLoading) return <div style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>Loading rate history...</div>;
  if (rateHistory.length === 0) return (
    <div style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>
      <div style={{ fontSize: 48, marginBottom: 12 }}>{"\uD83D\uDCCA"}</div>
      <h2 style={{ color: "#F0F2F5", fontWeight: 800, fontSize: 20, margin: "0 0 8px" }}>Rate History</h2>
      <div style={{ fontSize: 13 }}>No applied rates yet. Rates appear here when quotes are accepted and applied to loads.</div>
    </div>
  );
  const grouped = {};
  rateHistory.forEach(r => { const key = r.port_group || r.origin || "Unknown"; if (!grouped[key]) grouped[key] = []; grouped[key].push(r); });
  return (
    <div>
      <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 12 }}>{rateHistory.length} applied rates across {Object.keys(grouped).length} markets</div>
      {Object.entries(grouped).sort((a, b) => b[1].length - a[1].length).map(([group, rates]) => (
        <div key={group} className="glass" style={{ borderRadius: 10, marginBottom: 8, overflow: "hidden", border: "1px solid rgba(255,255,255,0.10)" }}>
          <div style={{ padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#00D4AA" }}>{group}</span>
            <span style={{ fontSize: 11, color: "#5A6478" }}>{rates.length} rate{rates.length !== 1 ? "s" : ""}</span>
          </div>
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "8px 16px" }}>
            {rates.map((r, ri) => (
              <div key={ri} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", borderBottom: ri < rates.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none" }}>
                <span style={{ fontSize: 11, color: "#C8D0DC", flex: 1 }}>
                  <LaneName raw={r.origin} bold={false} stateSize={10} /> <span style={{ color: "#5A6478" }}>{"\u2192"}</span> <LaneName raw={r.destination} bold={false} stateSize={10} />
                </span>
                <span style={{ fontSize: 11, color: "#8B95A8" }}>{r.carrier_name}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmtDec(r.rate_amount)}</span>
                <span style={{ fontSize: 11, color: "#5A6478" }}>{r.date ? new Date(r.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
