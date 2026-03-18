import React, { useState } from 'react';
import { fmt } from './constants';

/**
 * Render a Market Benchmark card showing market statistics, trend, comparison to the carrier average, and an optional expandable list of individual rates.
 *
 * @param {object} benchmark - Benchmark data; expected shape:
 *   - stats: { avg: number, min: number, max: number, count: number, trend_pct: number|null, oldest_date?: string, latest_date?: string }
 *   - rates?: Array<{ date?: string, terminal?: string, base?: number, fsc_pct?: number, total?: number }>
 * @param {number} carrierAvg - Carrier average used to compute the delta against `stats.avg`.
 * @returns {JSX.Element|null} A Market Benchmark card element, or `null` when `benchmark.stats` is not provided.
export default function MarketBenchmarkCard({ benchmark, carrierAvg }) {
  if (!benchmark?.stats) return null;
  const { stats, rates } = benchmark;
  const [expanded, setExpanded] = useState(false);
  const delta = carrierAvg > 0 && stats.avg > 0 ? carrierAvg - stats.avg : null;
  const deltaColor = delta === null ? "#5A6478" : delta < 0 ? "#34d399" : delta > 0 ? "#fb923c" : "#5A6478";
  const deltaPct = delta !== null && stats.avg > 0 ? ((delta / stats.avg) * 100).toFixed(1) : null;
  const trendColor = stats.trend_pct > 0 ? "#fb923c" : stats.trend_pct < 0 ? "#34d399" : "#5A6478";

  return (
    <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(251,146,60,0.15)" }}>
      <div style={{ padding: "16px 24px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px" }}>MARKET BENCHMARK</span>
          <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700, background: "rgba(251,146,60,0.12)", color: "#fb923c", border: "1px solid rgba(251,146,60,0.25)" }}>LOADMATCH</span>
        </div>
        <span style={{ fontSize: 11, color: "#5A6478" }}>{stats.count} data point{stats.count !== 1 ? "s" : ""}</span>
      </div>
      <div style={{ padding: "0 24px 16px", display: "flex", alignItems: "flex-end", gap: 32 }}>
        <div>
          <div style={{ fontSize: 42, fontWeight: 800, color: "#fb923c", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>
            {fmt(stats.avg)}
          </div>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 6 }}>
            Range: {fmt(stats.min)} – {fmt(stats.max)}
          </div>
          {stats.trend_pct !== null && (
            <div style={{ fontSize: 11, color: trendColor, marginTop: 2, fontWeight: 600 }}>
              {stats.trend_pct > 0 ? "\u2191" : "\u2193"} {Math.abs(stats.trend_pct)}% trend (recent vs older)
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 4 }}>
          {delta !== null && (
            <div style={{ fontSize: 12, fontWeight: 700, color: deltaColor }}>
              {delta > 0 ? "\u2191" : delta < 0 ? "\u2193" : "="} Your carrier avg is {fmt(Math.abs(delta))} ({deltaPct}%) {delta > 0 ? "above" : delta < 0 ? "below" : "at"} market
            </div>
          )}
          {stats.latest_date && (
            <div style={{ fontSize: 11, color: "#5A6478" }}>
              Data: {stats.oldest_date !== stats.latest_date ? `${stats.oldest_date} \u2192 ${stats.latest_date}` : stats.latest_date}
            </div>
          )}
        </div>
      </div>
      {rates && rates.length > 0 && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
          <div onClick={() => setExpanded(!expanded)}
            style={{ padding: "8px 24px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#5A6478" }}>{expanded ? "Hide" : "Show"} {rates.length} rate{rates.length !== 1 ? "s" : ""}</span>
            <span style={{ fontSize: 10, color: "#5A6478", transform: expanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}>{"\u25BC"}</span>
          </div>
          {expanded && (
            <div style={{ padding: "0 24px 12px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "90px 1fr 80px 50px 80px", gap: 0, fontSize: 11 }}>
                <div style={{ color: "#5A6478", fontWeight: 700, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>Date</div>
                <div style={{ color: "#5A6478", fontWeight: 700, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>Terminal</div>
                <div style={{ color: "#5A6478", fontWeight: 700, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)", textAlign: "right" }}>Base</div>
                <div style={{ color: "#5A6478", fontWeight: 700, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)", textAlign: "right" }}>FSC</div>
                <div style={{ color: "#5A6478", fontWeight: 700, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)", textAlign: "right" }}>Total</div>
                {rates.map((r, i) => (
                  <React.Fragment key={i}>
                    <div style={{ color: "#8B95A8", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>{r.date || "\u2014"}</div>
                    <div style={{ color: "#C8D0DC", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>{r.terminal || "\u2014"}</div>
                    <div style={{ color: "#F0F2F5", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right", fontFamily: "'JetBrains Mono', monospace" }}>{r.base ? fmt(r.base) : "\u2014"}</div>
                    <div style={{ color: "#8B95A8", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right" }}>{r.fsc_pct ? `${r.fsc_pct}%` : "0%"}</div>
                    <div style={{ color: "#fb923c", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{r.total ? fmt(r.total) : "\u2014"}</div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
