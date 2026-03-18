import React, { useState } from 'react';
import { apiFetch, API_BASE } from '../../helpers/api';
import { fmt, grad } from './constants';

export default function MarketRateCard({ laneGroup, carrierCapMap }) {
  const [feedback, setFeedback] = useState(null);
  if (!laneGroup) return null;
  const { carriers, minRate, maxRate, total, count, port, destination, miles, origin_zip, dest_zip, move_type } = laneGroup;
  const avgRate = count > 0 ? Math.round(total / count) : 0;
  const range = minRate !== Infinity && maxRate > 0 ? `${fmt(minRate)} \u2013 ${fmt(maxRate)}` : "\u2014";

  const confidence = count >= 10 ? 99 : count >= 5 ? 85 : count >= 3 ? 70 : count >= 1 ? 50 : 0;
  const confColor = confidence >= 85 ? "#34d399" : confidence >= 60 ? "#FBBF24" : "#fb923c";

  // Rate per mile — dray is round-trip, FTL/other is one-way
  const isDray = (move_type || "dray").toLowerCase() === "dray";
  const effectiveMiles = miles ? (isDray ? miles * 2 : miles) : null;
  const milesForCalc = effectiveMiles || 250;
  const ratePerMile = avgRate > 0 ? (avgRate / milesForCalc).toFixed(2) : "\u2014";

  const activity = carriers.length >= 5 ? "high" : carriers.length >= 3 ? "medium" : "low";
  const actColor = { high: "#34d399", medium: "#FBBF24", low: "#fb923c" }[activity];

  const sources = {};
  carriers.forEach(cr => { const s = cr.source || "import"; sources[s] = (sources[s] || 0) + 1; });

  return (
    <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.10)" }}>
      {/* Gradient accent bar */}
      <div style={{ height: 2, background: grad }} />
      {/* Header */}
      <div style={{ padding: "20px 24px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px" }}>MARKET RATE</span>
          {confidence > 0 && (
            <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: confColor + "18", color: confColor, border: `1px solid ${confColor}30` }}>
              {"\u2713"} {confidence}% Confidence
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => { setFeedback(f => f === "accurate" ? null : "accurate"); apiFetch(`${API_BASE}/api/rate-iq/feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lane: `${port} \u2192 ${destination}`, rating: "accurate", avg_rate: avgRate, count }) }).catch(() => {}); }}
            style={{ padding: "4px 12px", borderRadius: 6, border: `1px solid ${feedback === "accurate" ? "rgba(52,211,153,0.6)" : "rgba(52,211,153,0.3)"}`, background: feedback === "accurate" ? "rgba(52,211,153,0.2)" : "rgba(52,211,153,0.08)", color: "#34d399", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
            {"\uD83D\uDC4D"} Accurate
          </button>
          <button onClick={() => { setFeedback(f => f === "inaccurate" ? null : "inaccurate"); apiFetch(`${API_BASE}/api/rate-iq/feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lane: `${port} \u2192 ${destination}`, rating: "inaccurate", avg_rate: avgRate, count }) }).catch(() => {}); }}
            style={{ padding: "4px 12px", borderRadius: 6, border: `1px solid ${feedback === "inaccurate" ? "rgba(248,113,113,0.6)" : "rgba(248,113,113,0.3)"}`, background: feedback === "inaccurate" ? "rgba(248,113,113,0.2)" : "rgba(248,113,113,0.08)", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
            {"\uD83D\uDC4E"} Inaccurate
          </button>
        </div>
      </div>

      {/* Main rate display */}
      <div style={{ padding: "0 24px 20px", display: "flex", alignItems: "flex-end", gap: 40 }}>
        <div>
          <div style={{ fontSize: 52, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>
            {fmt(avgRate)}
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
            {sources.email && <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "rgba(59,130,246,0.12)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.2)" }}>EMAIL</span>}
            {sources.import && <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "rgba(167,139,250,0.12)", color: "#a78bfa", border: "1px solid rgba(167,139,250,0.2)" }}>IMPORT</span>}
            {sources.quote && <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "rgba(0,212,170,0.12)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.2)" }}>QUOTE</span>}
          </div>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 6 }}>Range: {range}</div>
        </div>

        {/* Metrics grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px 32px", paddingBottom: 4 }}>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Rate Per Mile</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: "'tnum'" }}>${ratePerMile}{!effectiveMiles && <span style={{ fontSize: 11, color: "#5A6478", fontWeight: 500 }}> est</span>}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Miles{isDray ? " (RT)" : ""}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: effectiveMiles ? "#F0F2F5" : "#3D4654", fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: "'tnum'" }}>{effectiveMiles ? effectiveMiles.toLocaleString() : "\u2014"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Activity</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: actColor }}>{activity}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Data Points</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: "'tnum'" }}>{count}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Carriers</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: "'tnum'" }}>{carriers.length}</div>
          </div>
          {(origin_zip || dest_zip) && (
            <div>
              <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Zip Codes</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{origin_zip || "\u2014"} {"\u2192"} {dest_zip || "\u2014"}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
