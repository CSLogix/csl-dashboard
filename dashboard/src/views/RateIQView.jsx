import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';
import QuoteBuilder from '../QuoteBuilder';
import OOGQuoteBuilder from '../OOGQuoteBuilder';

// ═══════════════════════════════════════════════════════════════
// RATE IQ VIEW — Lane-centric redesign (DrayRates.ai-inspired)
// Views: browse | detail | quote | scorecard | directory | history | oog
// ═══════════════════════════════════════════════════════════════

const grad = "linear-gradient(135deg, #00c853 0%, #00b8d4 50%, #2979ff 100%)";
const fmt = (n) => { const num = parseFloat(n); return isNaN(num) ? "$0" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 }); };
const fmtDec = (n) => { const num = parseFloat(n); return isNaN(num) ? "$0.00" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };

// ── History Tab Content (rate history by port group) ──
function HistoryTabContent({ rateHistory, historyLoading, onLoad }) {
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
        <div key={group} className="glass" style={{ borderRadius: 10, marginBottom: 8, overflow: "hidden", border: "1px solid rgba(255,255,255,0.04)" }}>
          <div style={{ padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#00D4AA" }}>{group}</span>
            <span style={{ fontSize: 11, color: "#5A6478" }}>{rates.length} rate{rates.length !== 1 ? "s" : ""}</span>
          </div>
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "8px 16px" }}>
            {rates.map((r, ri) => (
              <div key={ri} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", borderBottom: ri < rates.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none" }}>
                <span style={{ fontSize: 11, color: "#C8D0DC", flex: 1 }}>{r.origin} → {r.destination}</span>
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

// ── Market Rate Card (DrayRates-inspired) ──
function MarketRateCard({ laneGroup, carrierCapMap }) {
  if (!laneGroup) return null;
  const { carriers, minRate, maxRate, total, count, port, destination, miles, origin_zip, dest_zip, move_type } = laneGroup;
  const avgRate = count > 0 ? Math.round(total / count) : 0;
  const range = minRate !== Infinity && maxRate > 0 ? `${fmt(minRate)} – ${fmt(maxRate)}` : "—";

  // Calculate confidence based on data points
  const confidence = count >= 10 ? 99 : count >= 5 ? 85 : count >= 3 ? 70 : count >= 1 ? 50 : 0;
  const confColor = confidence >= 85 ? "#34d399" : confidence >= 60 ? "#FBBF24" : "#fb923c";

  // Rate per mile — dray is round-trip, FTL/other is one-way
  const isDray = (move_type || "dray").toLowerCase() === "dray";
  const effectiveMiles = miles ? (isDray ? miles * 2 : miles) : null;
  const milesForCalc = effectiveMiles || 250;
  const ratePerMile = avgRate > 0 ? (avgRate / milesForCalc).toFixed(2) : "—";

  // Activity level based on carrier count and data freshness
  const activity = carriers.length >= 5 ? "high" : carriers.length >= 3 ? "medium" : "low";
  const actColor = { high: "#34d399", medium: "#FBBF24", low: "#fb923c" }[activity];

  // Source breakdown
  const sources = {};
  carriers.forEach(cr => { const s = cr.source || "import"; sources[s] = (sources[s] || 0) + 1; });

  return (
    <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)" }}>
      {/* Header */}
      <div style={{ padding: "20px 24px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px" }}>MARKET RATE</span>
          {confidence > 0 && (
            <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: confColor + "18", color: confColor, border: `1px solid ${confColor}30` }}>
              ✓ {confidence}% Confidence
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(52,211,153,0.3)", background: "rgba(52,211,153,0.08)", color: "#34d399", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
            👍 Accurate
          </button>
          <button style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(248,113,113,0.3)", background: "rgba(248,113,113,0.08)", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
            👎 Inaccurate
          </button>
        </div>
      </div>

      {/* Main rate display */}
      <div style={{ padding: "0 24px 20px", display: "flex", alignItems: "flex-end", gap: 40 }}>
        {/* Big number */}
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
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>${ratePerMile}{!effectiveMiles && <span style={{ fontSize: 11, color: "#5A6478", fontWeight: 500 }}> est</span>}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Miles{isDray ? " (RT)" : ""}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: effectiveMiles ? "#F0F2F5" : "#3D4654", fontFamily: "'JetBrains Mono', monospace" }}>{effectiveMiles ? effectiveMiles.toLocaleString() : "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Activity</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: actColor }}>{activity}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Data Points</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{count}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Carriers</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{carriers.length}</div>
          </div>
          {(origin_zip || dest_zip) && (
            <div>
              <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 2 }}>Zip Codes</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{origin_zip || "—"} → {dest_zip || "—"}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Market Benchmark Card (LoadMatch data — no carrier) ──
function MarketBenchmarkCard({ benchmark, carrierAvg }) {
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
              {stats.trend_pct > 0 ? "↑" : "↓"} {Math.abs(stats.trend_pct)}% trend (recent vs older)
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 4 }}>
          {delta !== null && (
            <div style={{ fontSize: 12, fontWeight: 700, color: deltaColor }}>
              {delta > 0 ? "↑" : delta < 0 ? "↓" : "="} Your carrier avg is {fmt(Math.abs(delta))} ({deltaPct}%) {delta > 0 ? "above" : delta < 0 ? "below" : "at"} market
            </div>
          )}
          {stats.latest_date && (
            <div style={{ fontSize: 11, color: "#5A6478" }}>
              Data: {stats.oldest_date !== stats.latest_date ? `${stats.oldest_date} → ${stats.latest_date}` : stats.latest_date}
            </div>
          )}
        </div>
      </div>
      {rates && rates.length > 0 && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
          <div onClick={() => setExpanded(!expanded)}
            style={{ padding: "8px 24px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#5A6478" }}>{expanded ? "Hide" : "Show"} {rates.length} rate{rates.length !== 1 ? "s" : ""}</span>
            <span style={{ fontSize: 10, color: "#5A6478", transform: expanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}>▼</span>
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
                    <div style={{ color: "#8B95A8", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>{r.date || "—"}</div>
                    <div style={{ color: "#C8D0DC", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>{r.terminal || "—"}</div>
                    <div style={{ color: "#F0F2F5", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right", fontFamily: "'JetBrains Mono', monospace" }}>{r.base ? fmt(r.base) : "—"}</div>
                    <div style={{ color: "#8B95A8", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right" }}>{r.fsc_pct ? `${r.fsc_pct}%` : "0%"}</div>
                    <div style={{ color: "#fb923c", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.03)", textAlign: "right", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{r.total ? fmt(r.total) : "—"}</div>
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

// ── Carrier Rate Table (simplified — key columns visible, rest expandable) ──
function CarrierRateTable({ carriers, carrierCapMap, editingLaneRateId, editingLaneField, editingLaneValue, setEditingLaneRateId, setEditingLaneField, setEditingLaneValue, handleLaneRateUpdate, laneOrigin, laneDestination }) {
  const [showAllCols, setShowAllCols] = useState(false);
  const [copiedMC, setCopiedMC] = useState(null);
  const [hoveredRow, setHoveredRow] = useState(null);
  const primaryCols = ["Carrier", "Linehaul", "FSC", "Total", "Chassis/day", "Prepull", "OW", ""];
  const secondaryCols = ["Storage/day", "Detention", "Split", "Tolls", "HAZ", "Triaxle", "Reefer", "Bond"];
  const visibleCols = showAllCols ? ["Carrier", "Linehaul", "FSC", "Total", "Chassis/day", "Prepull", "OW", ...secondaryCols, ""] : primaryCols;

  const fieldMap = {
    "Linehaul": "dray_rate", "FSC": "fsc", "Total": "total", "Chassis/day": "chassis_per_day",
    "Prepull": "prepull", "OW": "overweight", "Storage/day": "storage_per_day", "Detention": "detention",
    "Split": "chassis_split", "Tolls": "tolls", "HAZ": "hazmat", "Triaxle": "triaxle", "Reefer": "reefer", "Bond": "bond_fee",
  };

  const copyMC = (mc) => {
    navigator.clipboard.writeText(mc).then(() => { setCopiedMC(mc); setTimeout(() => setCopiedMC(null), 1500); });
  };

  const emailRC = (carrier) => {
    const caps = carrierCapMap[(carrier.carrier_name || "").toLowerCase()] || {};
    const email = caps.contact_email || carrier.contact_email;
    if (!email) return;
    const total = carrier.total || carrier.dray_rate || "";
    const subject = encodeURIComponent(`Rate Confirmation — ${laneOrigin || ""} → ${laneDestination || ""}`);
    const body = encodeURIComponent(
      `Hi,\n\nPlease confirm the following rate:\n\nLane: ${laneOrigin || ""} → ${laneDestination || ""}\nCarrier: ${carrier.carrier_name}\nRate: $${total}\n\nThank you`
    );
    window.open(`mailto:${email}?subject=${subject}&body=${body}`, "_self");
  };

  return (
    <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ padding: "14px 20px 10px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px" }}>CARRIER RATES</span>
        <button onClick={() => setShowAllCols(!showAllCols)}
          style={{ padding: "3px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: showAllCols ? "rgba(0,212,170,0.08)" : "transparent", color: showAllCols ? "#00D4AA" : "#5A6478", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
          {showAllCols ? "Show Less" : `+${secondaryCols.length} More Columns`}
        </button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
              {visibleCols.map(h => (
                <th key={h} style={{ padding: "8px 10px", textAlign: h === "Carrier" ? "left" : "center", color: "#5A6478", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.03em", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {carriers.map((cr, ci) => {
              const caps = carrierCapMap[(cr.carrier_name || "").toLowerCase()] || {};
              const capBadges = [
                caps.can_hazmat && { label: "\uD83D\uDD25", title: "Hazmat", color: "#f87171" },
                caps.can_overweight && { label: "\u2696", title: "Overweight", color: "#FBBF24" },
                caps.can_reefer && { label: "\u2744", title: "Reefer", color: "#60a5fa" },
                caps.can_bonded && { label: "\uD83D\uDD12", title: "Bonded", color: "#a78bfa" },
                caps.can_transload && { label: "\uD83D\uDD04", title: "Transload", color: "#38bdf8" },
              ].filter(Boolean);
              const tierColor = caps.tier_rank === 1 ? "#22c55e" : caps.tier_rank === 2 ? "#FBBF24" : caps.tier_rank === 3 ? "#fb923c" : null;
              const daysSince = cr.created_at ? Math.floor((Date.now() - new Date(cr.created_at).getTime()) / 86400000) : null;
              const isAged = daysSince !== null && daysSince > 30;
              const mcNumber = caps.mc_number || cr.mc_number;
              const dispatchEmail = caps.contact_email || cr.carrier_email || cr.contact_email;
              const isHovered = hoveredRow === ci;

              return (
                <tr key={ci} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)", transition: "background 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; setHoveredRow(ci); }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; setHoveredRow(null); }}>
                  {/* Enhanced Carrier Cell — multi-line info hub */}
                  <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
                    {/* Line 1: Name + Tier + Capability badges + Age */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: mcNumber || dispatchEmail ? 2 : 0 }}>
                      {tierColor && <span title={`Tier ${caps.tier_rank}`} style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: tierColor, flexShrink: 0 }} />}
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{cr.carrier_name}</span>
                      {capBadges.map((b, bi) => <span key={bi} title={b.title} style={{ fontSize: 11, opacity: 0.8 }}>{b.label}</span>)}
                      {daysSince !== null && (
                        <span style={{ fontSize: 11, color: isAged ? "#FBBF24" : "#5A6478", fontStyle: "italic" }}>
                          {isAged ? "\u26A0 " : ""}{daysSince === 0 ? "today" : daysSince < 7 ? `${daysSince}d` : daysSince < 30 ? `${Math.floor(daysSince / 7)}w` : `${Math.floor(daysSince / 30)}mo`}
                        </span>
                      )}
                    </div>
                    {/* Line 2: MC Number + copy */}
                    {mcNumber && (
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <span style={{ fontSize: 11, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{mcNumber}</span>
                        <span onClick={e => { e.stopPropagation(); copyMC(mcNumber); }}
                          title="Copy MC#" style={{ fontSize: 11, cursor: "pointer", color: copiedMC === mcNumber ? "#34d399" : "#3D4654", transition: "color 0.15s" }}>
                          {copiedMC === mcNumber ? "\u2713" : "\u2398"}
                        </span>
                      </div>
                    )}
                    {/* Line 3: Dispatch email */}
                    {dispatchEmail && (
                      <a href={`mailto:${dispatchEmail}`} onClick={e => e.stopPropagation()}
                        style={{ fontSize: 11, color: "#60a5fa", textDecoration: "none", display: "block", marginTop: 1, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                        onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
                        {dispatchEmail}
                      </a>
                    )}
                  </td>
                  {visibleCols.slice(1, -1).map((col, vi) => {
                    const f = fieldMap[col];
                    const v = cr[f];
                    const isEditingThis = editingLaneRateId === cr.id && editingLaneField === f;
                    return (
                      <td key={vi} onClick={e => { e.stopPropagation(); setEditingLaneRateId(cr.id); setEditingLaneField(f); setEditingLaneValue(v != null && v !== "" ? String(v) : ""); }}
                        style={{ padding: "10px 8px", textAlign: "center", cursor: "text", fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
                          color: isEditingThis ? "#F0F2F5" : v ? "#C8D0DC" : "#2D3340", verticalAlign: "middle" }}>
                        {isEditingThis ? (
                          <input autoFocus type="number" step="0.01" value={editingLaneValue}
                            onChange={e => setEditingLaneValue(e.target.value)}
                            onBlur={() => handleLaneRateUpdate(cr.id, f, editingLaneValue)}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setEditingLaneRateId(null); setEditingLaneField(null); } }}
                            onClick={e => e.stopPropagation()}
                            style={{ width: 60, padding: "3px 4px", textAlign: "center", borderRadius: 4, border: "1px solid rgba(0,212,170,0.4)", background: "rgba(0,212,170,0.06)", color: "#F0F2F5", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none" }} />
                        ) : (
                          v ? (typeof v === "number" || !isNaN(v) ? `$${parseFloat(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}` : v) : "\u2014"
                        )}
                      </td>
                    );
                  })}
                  {/* Email RC action column */}
                  <td style={{ padding: "10px 8px", textAlign: "center", verticalAlign: "middle", width: 36 }}>
                    {isHovered && dispatchEmail && (
                      <button onClick={e => { e.stopPropagation(); emailRC(cr); }}
                        title={`Email rate confirmation to ${dispatchEmail}`}
                        style={{ padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(59,130,246,0.3)", background: "rgba(59,130,246,0.08)", color: "#60a5fa", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap", transition: "all 0.15s" }}
                        onMouseEnter={e => { e.currentTarget.style.background = "rgba(59,130,246,0.15)"; }}
                        onMouseLeave={e => { e.currentTarget.style.background = "rgba(59,130,246,0.08)"; }}>
                        \u2709 RC
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Lane Card (for browse view) ──
const MOVE_TYPE_STYLES = {
  dray: { label: "Dray", color: "#60a5fa", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.25)" },
  ftl: { label: "FTL", color: "#FBBF24", bg: "rgba(251,191,36,0.12)", border: "rgba(251,191,36,0.25)" },
  transload: { label: "Transload", color: "#a78bfa", bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.25)" },
};

function LaneCard({ lane, onClick, onQuickQuote, onReclassify, rateIds }) {
  const [hovered, setHovered] = useState(false);
  const [showMtPicker, setShowMtPicker] = useState(false);
  const volume = lane.load_count || 0;
  const mtStyle = MOVE_TYPE_STYLES[(lane.move_type || "dray").toLowerCase()] || MOVE_TYPE_STYLES.dray;
  const volTag = volume >= 20 ? { label: "High Volume", color: "#00D4AA", bg: "rgba(0,212,170,0.15)", border: "rgba(0,212,170,0.35)" }
    : volume >= 5 ? { label: "Active", color: "#3B82F6", bg: "rgba(59,130,246,0.15)", border: "rgba(59,130,246,0.35)" }
    : { label: "Low Volume", color: "#5A6478", bg: "rgba(90,100,120,0.08)", border: "rgba(90,100,120,0.15)" };
  const avgRate = lane.avg_rate || lane.average || 0;
  const isDray = (lane.move_type || "dray").toLowerCase() === "dray";
  const miles = lane.miles ? (isDray ? lane.miles * 2 : lane.miles) : null;
  const rpm = (avgRate > 0 && miles > 0) ? (avgRate / miles).toFixed(2) : null;

  return (
    <div onClick={onClick} draggable className="glass" style={{ borderRadius: 12, padding: "18px 20px", cursor: "pointer", border: "1px solid rgba(255,255,255,0.06)", transition: "all 0.2s", position: "relative" }}
      onDragStart={e => { e.dataTransfer.setData("application/json", JSON.stringify({ port: lane.port || lane.origin_city, destination: lane.destination || lane.dest_city, rateIds: rateIds || [] })); e.dataTransfer.effectAllowed = "move"; }}
      onMouseEnter={e => { setHovered(true); e.currentTarget.style.borderColor = "rgba(0,212,170,0.25)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={e => { setHovered(false); e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; e.currentTarget.style.transform = "translateY(0)"; }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5" }}>
            {lane.origin_city || lane.port || "—"} <span style={{ color: "#5A6478" }}>→</span> {lane.dest_city || lane.destination || "—"}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
            <span style={{ fontSize: 11, color: "#5A6478" }}>{volume} rate{volume !== 1 ? "s" : ""} on file</span>
            {miles && <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{miles.toLocaleString()} mi{isDray ? " RT" : ""}</span>}
            {rpm && <span style={{ fontSize: 11, fontWeight: 700, color: "#60a5fa", fontFamily: "'JetBrains Mono', monospace" }}>${rpm}/mi</span>}
          </div>
          {(lane.origin_zip || lane.dest_zip) && (
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
              {lane.origin_zip || "—"} → {lane.dest_zip || "—"}
            </div>
          )}
        </div>
        {avgRate > 0 && (
          <div style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, justifyContent: "flex-end" }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(avgRate)}</div>
              {lane.trend_pct != null && Math.abs(lane.trend_pct) > 2 && (
                <span style={{ fontSize: 11, fontWeight: 700, color: lane.trend_pct > 0 ? "#f87171" : "#34d399" }}>
                  {lane.trend_pct > 0 ? "↑" : "↓"} {Math.abs(lane.trend_pct).toFixed(1)}%
                </span>
              )}
            </div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600 }}>avg rate</div>
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", gap: 6 }}>
          <span onClick={e => { e.stopPropagation(); if (onReclassify) setShowMtPicker(!showMtPicker); }}
            style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: mtStyle.bg, color: mtStyle.color, border: `1px solid ${mtStyle.border}`, cursor: onReclassify ? "pointer" : "default", position: "relative" }}
            title={onReclassify ? "Click to reclassify move type" : ""}>
            {mtStyle.label}
            {showMtPicker && onReclassify && (
              <div onClick={e => e.stopPropagation()} style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, zIndex: 60, background: "#151922", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 8px 24px rgba(0,0,0,0.5)", overflow: "hidden", minWidth: 100 }}>
                {["dray", "ftl", "transload"].filter(mt => mt !== (lane.move_type || "dray").toLowerCase()).map(mt => {
                  const s = MOVE_TYPE_STYLES[mt];
                  return (
                    <div key={mt} onClick={() => { onReclassify(mt); setShowMtPicker(false); }}
                      style={{ padding: "6px 14px", cursor: "pointer", fontSize: 11, fontWeight: 700, color: s.color, transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.05)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      {s.label}
                    </div>
                  );
                })}
              </div>
            )}
          </span>
          <span style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: volTag.bg, color: volTag.color, border: `1px solid ${volTag.border}` }}>
            {volTag.label}
          </span>
          {lane.carrier_count > 0 && (
            <span style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: "rgba(255,255,255,0.04)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.08)" }}>
              {lane.carrier_count} carrier{lane.carrier_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        {/* Hover actions */}
        {hovered && (
          <div style={{ display: "flex", gap: 4 }}>
            <button onClick={e => { e.stopPropagation(); onQuickQuote && onQuickQuote(); }}
              style={{ padding: "3px 10px", borderRadius: 6, border: "none", background: grad, color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
              Quick Quote →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// MAIN: RATE IQ VIEW
// ═══════════════════════════════════════════════════════════════
export default function RateIQView() {
  // ── View state ──
  const [view, setView] = useState("browse"); // browse | detail | intake | build-quote | scorecard | directory | history | oog
  const [selectedLane, setSelectedLane] = useState(null); // { origin, destination }

  // ── Data state ──
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [laneStats, setLaneStats] = useState([]);
  const [rateLaneSummaries, setRateLaneSummaries] = useState([]); // from lane-rates (actual rate data)
  const [expandedOrigins, setExpandedOrigins] = useState({}); // { "Chicago": true, ... }
  const [scorecardPerf, setScorecardPerf] = useState([]);
  const [expandedCarrier, setExpandedCarrier] = useState(null);
  const [dirCarriers, setDirCarriers] = useState([]);
  const [portGroups, setPortGroups] = useState([]);
  const [rateHistory, setRateHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ── Manual intake state ──
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [intakeText, setIntakeText] = useState("");
  const [intakeMoveType, setIntakeMoveType] = useState("dray");
  const [intakeProcessing, setIntakeProcessing] = useState(false);
  const [intakeResult, setIntakeResult] = useState(null); // { ok, extracted } or { error }
  const [intakeFile, setIntakeFile] = useState(null);
  const [intakeDragOver, setIntakeDragOver] = useState(false);
  const intakeFileRef = useRef(null);

  // ── Market rates paste state ──
  const [marketRateOpen, setMarketRateOpen] = useState(false);
  const [marketRateOrigin, setMarketRateOrigin] = useState("");
  const [marketRateDest, setMarketRateDest] = useState("");
  const [marketRateText, setMarketRateText] = useState("");
  const [marketRateFile, setMarketRateFile] = useState(null);
  const [marketRateDragOver, setMarketRateDragOver] = useState(false);
  const marketRateFileRef = useRef(null);
  const [marketRateMoveType, setMarketRateMoveType] = useState("dray");
  const [marketRateProcessing, setMarketRateProcessing] = useState(false);
  const [marketRateResult, setMarketRateResult] = useState(null);
  const [marketBenchmark, setMarketBenchmark] = useState(null);

  // ── Lane Search state ──
  const [searchOrigin, setSearchOrigin] = useState("");
  const [searchDest, setSearchDest] = useState("");
  const [laneResults, setLaneResults] = useState([]);
  const [laneSearching, setLaneSearching] = useState(false);
  const [moveTypeFilter, setMoveTypeFilter] = useState("dray"); // all | dray | ftl | transload
  const [editingLaneRateId, setEditingLaneRateId] = useState(null);
  const [editingLaneField, setEditingLaneField] = useState(null);
  const [editingLaneValue, setEditingLaneValue] = useState("");

  // ── Autocomplete + recent searches ──
  const [originFocused, setOriginFocused] = useState(false);
  const [destFocused, setDestFocused] = useState(false);
  const originRef = useRef(null);
  const destRef = useRef(null);
  const [recentSearches, setRecentSearches] = useState(() => {
    try { return JSON.parse(localStorage.getItem("rateiq_recent") || "[]"); } catch { return []; }
  });
  const saveRecent = useCallback((origin, destination) => {
    setRecentSearches(prev => {
      const key = `${origin}→${destination}`;
      const next = [{ origin, destination, key }, ...prev.filter(r => r.key !== key)].slice(0, 5);
      localStorage.setItem("rateiq_recent", JSON.stringify(next));
      return next;
    });
  }, []);
  const originSuggestions = useMemo(() => {
    if (!searchOrigin || searchOrigin.length < 2) return [];
    const q = searchOrigin.toLowerCase();
    const seen = new Set();
    return rateLaneSummaries
      .filter(ls => {
        const p = (ls.port || "").toLowerCase();
        if (!p.includes(q) || seen.has(p)) return false;
        seen.add(p);
        return true;
      })
      .slice(0, 6)
      .map(ls => {
        const matching = rateLaneSummaries.filter(l => (l.port || "").toLowerCase() === (ls.port || "").toLowerCase());
        const totalRates = matching.reduce((s, l) => s + l.load_count, 0);
        const avgAll = matching.length > 0 ? Math.round(matching.reduce((s, l) => s + l.avg_rate * l.load_count, 0) / totalRates) : 0;
        return { port: ls.port, lanes: matching.length, avg: avgAll };
      });
  }, [searchOrigin, rateLaneSummaries]);
  const destSuggestions = useMemo(() => {
    if (!searchDest || searchDest.length < 2) return [];
    const q = searchDest.toLowerCase();
    const seen = new Set();
    return rateLaneSummaries
      .filter(ls => {
        const d = (ls.destination || "").toLowerCase();
        if (!d.includes(q) || seen.has(d)) return false;
        seen.add(d);
        return true;
      })
      .slice(0, 6)
      .map(ls => {
        const matching = rateLaneSummaries.filter(l => (l.destination || "").toLowerCase() === (ls.destination || "").toLowerCase());
        const totalRates = matching.reduce((s, l) => s + l.load_count, 0);
        const avgAll = matching.length > 0 ? Math.round(matching.reduce((s, l) => s + l.avg_rate * l.load_count, 0) / totalRates) : 0;
        return { destination: ls.destination, lanes: matching.length, avg: avgAll, origin: searchOrigin || matching[0]?.port || "" };
      });
  }, [searchDest, searchOrigin, rateLaneSummaries]);

  // ── Directory state ──
  const [dirSearch, setDirSearch] = useState("");
  const [dirMarket, setDirMarket] = useState("all");
  const [dirCaps, setDirCaps] = useState([]);
  const [dirHideDnu, setDirHideDnu] = useState(true);
  const [dirPort, setDirPort] = useState("all");
  const [dirExpanded, setDirExpanded] = useState(null);
  const [editingCarrierId, setEditingCarrierId] = useState(null);
  const [showAddCarrier, setShowAddCarrier] = useState(false);
  const [newCarrier, setNewCarrier] = useState({ carrier_name: "", mc_number: "", pickup_area: "" });
  const [addCarrierSaving, setAddCarrierSaving] = useState(false);
  const [dirScreenshotFile, setDirScreenshotFile] = useState(null);
  const [dirScreenshotResult, setDirScreenshotResult] = useState(null);
  const [dirScreenshotProcessing, setDirScreenshotProcessing] = useState(false);
  const dirScreenshotRef = useRef(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  // ── Detail navigation ──
  const [laneIndex, setLaneIndex] = useState(0); // for prev/next within grouped results

  const CAP_OPTIONS = [
    { key: "can_hazmat", label: "HAZ", color: "#f87171" },
    { key: "can_overweight", label: "OWT", color: "#FBBF24" },
    { key: "can_reefer", label: "Reefer", color: "#60a5fa" },
    { key: "can_bonded", label: "Bonded", color: "#a78bfa" },
    { key: "can_oog", label: "OOG", color: "#fb923c" },
    { key: "can_transload", label: "Transload", color: "#38bdf8", sync: "can_warehousing" },
  ];

  // ── Carrier capability lookup ──
  const carrierCapMap = useMemo(() => {
    const m = {};
    dirCarriers.forEach(c => {
      m[(c.carrier_name || "").toLowerCase()] = {
        can_hazmat: c.can_hazmat, can_overweight: c.can_overweight, can_reefer: c.can_reefer,
        can_bonded: c.can_bonded, can_oog: c.can_oog, can_warehousing: c.can_warehousing,
        can_transload: c.can_transload, tier_rank: c.tier_rank, dnu: c.dnu, mc_number: c.mc_number,
        contact_email: c.contact_email || c.email, contact_phone: c.contact_phone || c.phone,
      };
    });
    return m;
  }, [dirCarriers]);

  // ── Directory filtering ──
  const allMarkets = useMemo(() => {
    const s = new Set();
    dirCarriers.forEach(c => (c.markets || []).forEach(m => s.add(m)));
    return [...s].sort();
  }, [dirCarriers]);

  const filteredDir = useMemo(() => {
    return dirCarriers.filter(c => {
      if (dirHideDnu && c.dnu) return false;
      if (dirSearch) {
        const q = dirSearch.toLowerCase();
        if (!(c.carrier_name || "").toLowerCase().includes(q) && !(c.mc_number || "").toLowerCase().includes(q) && !(c.contact_email || "").toLowerCase().includes(q)) return false;
      }
      if (dirMarket !== "all" && !(c.markets || []).includes(dirMarket)) return false;
      if (dirPort !== "all") {
        const pg = portGroups.find(g => g.name === dirPort);
        if (pg) {
          const members = pg.members.map(m => m.toLowerCase());
          const areas = ((c.pickup_area || "") + " " + (c.ports || "") + " " + (c.regions || "")).toLowerCase();
          if (!members.some(m => areas.includes(m.split(",")[0]))) return false;
        }
      }
      for (const cap of dirCaps) { if (!c[cap]) return false; }
      return true;
    });
  }, [dirCarriers, dirSearch, dirMarket, dirCaps, dirHideDnu, dirPort, portGroups]);

  // ── Group lane results by origin → destination ──
  const groupedLanes = useMemo(() => {
    const map = {};
    (Array.isArray(laneResults) ? laneResults : []).forEach(r => {
      const key = `${r.port || ""} → ${r.destination || ""}`;
      if (!map[key]) map[key] = { port: r.port, destination: r.destination, carriers: [], minRate: Infinity, maxRate: 0, total: 0, count: 0, miles: null, origin_zip: null, dest_zip: null, moveTypes: {} };
      map[key].carriers.push(r);
      if (!map[key].miles && r.miles) map[key].miles = r.miles;
      if (!map[key].origin_zip && r.origin_zip) map[key].origin_zip = r.origin_zip;
      if (!map[key].dest_zip && r.dest_zip) map[key].dest_zip = r.dest_zip;
      const rate = parseFloat(r.total || r.dray_rate || 0);
      if (rate > 0) { map[key].minRate = Math.min(map[key].minRate, rate); map[key].maxRate = Math.max(map[key].maxRate, rate); map[key].total += rate; map[key].count++; }
      const mt = (r.move_type || "dray").toLowerCase();
      map[key].moveTypes[mt] = (map[key].moveTypes[mt] || 0) + 1;
    });
    return Object.values(map).map(g => {
      const mtEntries = Object.entries(g.moveTypes);
      g.move_type = mtEntries.length > 0 ? mtEntries.sort((a, b) => b[1] - a[1])[0][0] : "dray";
      return g;
    }).sort((a, b) => b.count - a.count);
  }, [laneResults]);

  // ── Group rateLaneSummaries by origin city for collapsible browse view ──
  const originGroups = useMemo(() => {
    const filtered = rateLaneSummaries.filter(ls => moveTypeFilter === "all" || ls.move_type === moveTypeFilter);
    const map = {};
    filtered.forEach(ls => {
      const origin = ls.port || ls.origin_city || "Unknown";
      if (!map[origin]) map[origin] = { origin, lanes: [], totalRate: 0, rateCount: 0, totalLoads: 0 };
      map[origin].lanes.push(ls);
      map[origin].totalLoads += (ls.load_count || 0);
      if (ls.avg_rate > 0) { map[origin].totalRate += ls.avg_rate * (ls.load_count || 1); map[origin].rateCount += (ls.load_count || 1); }
    });
    return Object.values(map)
      .map(g => ({ ...g, avgRate: g.rateCount > 0 ? Math.round(g.totalRate / g.rateCount) : 0 }))
      .sort((a, b) => b.totalLoads - a.totalLoads);
  }, [rateLaneSummaries, moveTypeFilter]);

  // ── API: Manual intake — paste email text, AI extracts rate ──
  // ── API: Carrier update ──
  const handleCarrierUpdate = async (carrierId, field, value) => {
    // Sync WHS/Transload — treat as synonyms
    const capDef = CAP_OPTIONS.find(c => c.key === field);
    const updates = { [field]: value };
    if (capDef?.sync) updates[capDef.sync] = value;
    setDirCarriers(prev => prev.map(c => c.id === carrierId ? { ...c, ...updates } : c));
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers/${carrierId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) { console.error("Carrier update failed:", e); }
  };

  // ── API: Add carrier ──
  const handleAddCarrier = async () => {
    if (!newCarrier.carrier_name.trim()) return;
    setAddCarrierSaving(true);
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newCarrier, source: "manual" }),
      });
      if (r.ok) {
        const data = await r.json();
        setDirCarriers(prev => [data.carrier || data, ...prev]);
        setNewCarrier({ carrier_name: "", mc_number: "", pickup_area: "" });
        setShowAddCarrier(false);
      }
    } catch (e) { console.error("Add carrier failed:", e); }
    setAddCarrierSaving(false);
  };

  // ── API: Delete carrier ──
  const handleDeleteCarrier = async (carrierId) => {
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers/${carrierId}`, { method: "DELETE" });
      if (r.ok) {
        setDirCarriers(prev => prev.filter(c => c.id !== carrierId));
        setDeleteConfirm(null);
        setEditingCarrierId(null);
      }
    } catch (e) { console.error("Delete carrier failed:", e); }
  };

  // ── API: LoadMatch screenshot import ──
  const handleDirScreenshot = async () => {
    if (!dirScreenshotFile) return;
    setDirScreenshotProcessing(true);
    setDirScreenshotResult(null);
    try {
      const formData = new FormData();
      formData.append("file", dirScreenshotFile);
      const r = await apiFetch(`${API_BASE}/api/carriers/extract`, { method: "POST", body: formData });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setDirScreenshotResult(data);
      // If carriers were extracted and saved, refresh directory
      if (data.carriers?.length > 0 || data.saved?.length > 0) {
        const res = await apiFetch(`${API_BASE}/api/carriers?exclude_dnu=false`);
        if (res.ok) { const d = await res.json(); setDirCarriers(d.carriers || d || []); }
      }
    } catch (e) {
      setDirScreenshotResult({ error: e.message || "Screenshot extraction failed" });
    }
    setDirScreenshotProcessing(false);
  };

  // ── API: Lane rate update ──
  const handleLaneRateUpdate = async (rateId, field, value) => {
    const numVal = value === "" || value === null ? null : parseFloat(value);
    setLaneResults(prev => prev.map(r => ({
      ...r, carriers: (r.carriers || []).map(cr => cr.id === rateId ? { ...cr, [field]: numVal } : cr),
    })));
    try {
      const r = await apiFetch(`${API_BASE}/api/lane-rates/${rateId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: numVal }),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) { console.error("Lane rate update failed:", e); }
    setEditingLaneRateId(null);
    setEditingLaneField(null);
  };

  // ── API: Fetch all data ──
  const fetchData = useCallback(async () => {
    try {
      const [rateRes, perfRes, laneRes, carrierRes, pgRes, laneRatesRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/rate-iq`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/carriers/scorecard`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/lane-stats`).then(r => r.json()).catch(() => ({ lanes: [] })),
        apiFetch(`${API_BASE}/api/carriers?include_lanes=true`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/port-groups`).then(r => r.json()).catch(() => ({ groups: [] })),
        apiFetch(`${API_BASE}/api/lane-rates${moveTypeFilter && moveTypeFilter !== "all" ? `?move_type=${moveTypeFilter}` : ""}`).then(r => r.json()).catch(() => ({ lane_rates: [] })),
      ]);
      setData(rateRes);
      setScorecardPerf(perfRes.carriers || []);
      setLaneStats(laneRes.lanes || []);
      setDirCarriers(carrierRes.carriers || carrierRes || []);
      setPortGroups(pgRes.groups || []);

      // Build lane summaries from rate data (with trend detection)
      const allRates = laneRatesRes.lane_rates || (Array.isArray(laneRatesRes) ? laneRatesRes : []);
      const now = Date.now();
      const thirtyDaysAgo = now - 30 * 86400000;
      const laneMap = {};
      allRates.forEach(r => {
        const key = `${r.port || ""}|${r.destination || ""}`;
        if (!laneMap[key]) laneMap[key] = { port: r.port, destination: r.destination, count: 0, totalRate: 0, carriers: new Set(), recentTotal: 0, recentCount: 0, olderTotal: 0, olderCount: 0, miles: null, origin_zip: null, dest_zip: null, moveTypes: {} };
        if (!laneMap[key].miles && r.miles) laneMap[key].miles = r.miles;
        if (!laneMap[key].origin_zip && r.origin_zip) laneMap[key].origin_zip = r.origin_zip;
        if (!laneMap[key].dest_zip && r.dest_zip) laneMap[key].dest_zip = r.dest_zip;
        laneMap[key].count++;
        const rate = parseFloat(r.total || r.dray_rate || 0);
        if (rate > 0) {
          laneMap[key].totalRate += rate;
          const ts = r.created_at ? new Date(r.created_at).getTime() : 0;
          if (ts >= thirtyDaysAgo) { laneMap[key].recentTotal += rate; laneMap[key].recentCount++; }
          else { laneMap[key].olderTotal += rate; laneMap[key].olderCount++; }
        }
        if (r.carrier_name) laneMap[key].carriers.add(r.carrier_name);
        const mt = (r.move_type || "dray").toLowerCase();
        laneMap[key].moveTypes[mt] = (laneMap[key].moveTypes[mt] || 0) + 1;
      });
      const summaries = Object.values(laneMap)
        .filter(l => l.port && l.destination)
        .map(l => {
          const avg_rate = l.count > 0 ? Math.round(l.totalRate / l.count) : 0;
          const recentAvg = l.recentCount > 0 ? l.recentTotal / l.recentCount : null;
          const olderAvg = l.olderCount > 0 ? l.olderTotal / l.olderCount : null;
          const trend_pct = (recentAvg && olderAvg && olderAvg > 0) ? ((recentAvg - olderAvg) / olderAvg) * 100 : null;
          // Determine primary move type (most common across rates for this lane)
          const mtEntries = Object.entries(l.moveTypes);
          const primary_move_type = mtEntries.length > 0 ? mtEntries.sort((a, b) => b[1] - a[1])[0][0] : "dray";
          return { port: l.port, destination: l.destination, load_count: l.count, avg_rate, carrier_count: l.carriers.size, trend_pct, miles: l.miles, origin_zip: l.origin_zip, dest_zip: l.dest_zip, move_type: primary_move_type };
        })
        .sort((a, b) => b.load_count - a.load_count);
      setRateLaneSummaries(summaries);
    } catch (e) { console.error("Rate IQ fetch:", e); }
    setLoading(false);
  }, [moveTypeFilter]);

  useEffect(() => { fetchData(); const iv = setInterval(fetchData, 60000); return () => clearInterval(iv); }, [fetchData]);

  // ── Fetch market benchmark for current lane search ──
  const fetchMarketBenchmark = useCallback(async (o, d) => {
    if (!o && !d) { setMarketBenchmark(null); return; }
    try {
      const params = new URLSearchParams();
      if (o) params.set("origin", o);
      if (d) params.set("destination", d);
      const res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates?${params.toString()}`).then(r => r.json());
      setMarketBenchmark(res.stats ? { stats: res.stats, rates: res.rates } : null);
    } catch { setMarketBenchmark(null); }
  }, []);

  // ── Lane search ──
  const searchLanes = useCallback(async (origin, dest) => {
    const o = origin ?? searchOrigin;
    const d = dest ?? searchDest;
    if (!o && !d) return;
    setLaneSearching(true);
    try {
      const params = new URLSearchParams();
      if (o) params.set("port", o);
      if (d) params.set("destination", d);
      if (moveTypeFilter && moveTypeFilter !== "all") params.set("move_type", moveTypeFilter);
      const res = await apiFetch(`${API_BASE}/api/lane-rates?${params.toString()}`).then(r => r.json());
      setLaneResults(res.lane_rates || (Array.isArray(res) ? res : []));
      fetchMarketBenchmark(o, d);
    } catch (e) { console.error("Lane search:", e); setLaneResults([]); }
    setLaneSearching(false);
  }, [searchOrigin, searchDest, moveTypeFilter, fetchMarketBenchmark]);

  // Re-search when move type filter changes (if there's an active search)
  useEffect(() => { if (searchOrigin || searchDest) searchLanes(); }, [moveTypeFilter, searchLanes]);

  // ── API: Manual intake — paste email text OR upload file, AI extracts rate ──
  const handleManualIntake = useCallback(async (file) => {
    const f = file || intakeFile;
    if (!intakeText.trim() && !f) return;
    setIntakeProcessing(true);
    setIntakeResult(null);
    try {
      let res;
      if (f) {
        const formData = new FormData();
        formData.append("file", f);
        formData.append("move_type", intakeMoveType);
        if (intakeText.trim()) formData.append("text", intakeText);
        res = await apiFetch(`${API_BASE}/api/rate-iq/manual-intake`, { method: "POST", body: formData });
      } else {
        res = await apiFetch(`${API_BASE}/api/rate-iq/manual-intake`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: intakeText, move_type: intakeMoveType }),
        });
      }
      const data = await res.json();
      if (res.ok && data.ok) {
        setIntakeResult({ ok: true, extracted: data.extracted });
        setIntakeText("");
        setIntakeFile(null);
        fetchData();
      } else {
        setIntakeResult({ error: data.error || "Extraction failed", extracted: data.extracted });
      }
    } catch (e) {
      setIntakeResult({ error: e.message });
    }
    setIntakeProcessing(false);
  }, [intakeText, intakeFile, intakeMoveType, fetchData]);

  // ── API: Market rates — paste text OR upload screenshot ──
  const handleMarketRatePaste = useCallback(async (file) => {
    const f = file || marketRateFile;
    if (!marketRateText.trim() && !f) return;
    if (!f && (!marketRateOrigin.trim() || !marketRateDest.trim())) return;
    setMarketRateProcessing(true);
    setMarketRateResult(null);
    try {
      let res;
      if (f) {
        const formData = new FormData();
        formData.append("file", f);
        if (marketRateOrigin.trim()) formData.append("origin", marketRateOrigin);
        if (marketRateDest.trim()) formData.append("destination", marketRateDest);
        formData.append("move_type", marketRateMoveType);
        if (marketRateText.trim()) formData.append("text", marketRateText);
        res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates`, { method: "POST", body: formData });
      } else {
        res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ origin: marketRateOrigin, destination: marketRateDest, move_type: marketRateMoveType, text: marketRateText }),
        });
      }
      const data = await res.json();
      if (res.ok && data.ok) {
        setMarketRateResult({ ok: true, inserted: data.inserted, skipped: data.skipped });
        setMarketRateText("");
        setMarketRateFile(null);
        // Auto-refresh benchmark if we have an active lane search
        if (searchOrigin || searchDest) fetchMarketBenchmark(searchOrigin, searchDest);
      } else {
        setMarketRateResult({ error: data.error || "Parse failed", errors: data.errors });
      }
    } catch (e) {
      setMarketRateResult({ error: e.message });
    }
    setMarketRateProcessing(false);
  }, [marketRateOrigin, marketRateDest, marketRateMoveType, marketRateText, marketRateFile, searchOrigin, searchDest, fetchMarketBenchmark]);

  // ── API: Reclassify lane move type (bulk update all rates in a lane) ──
  const [dragOverType, setDragOverType] = useState(null);
  const handleReclassifyLane = useCallback(async (port, destination, rateIds, newMoveType) => {
    if (!rateIds?.length && !port) return;
    if (rateIds?.length) {
      await Promise.all(rateIds.map(id =>
        apiFetch(`${API_BASE}/api/lane-rates/${id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ move_type: newMoveType }),
        }).catch(e => console.error("Reclassify failed for", id, e))
      ));
    } else {
      const res = await apiFetch(`${API_BASE}/api/lane-rates?port=${encodeURIComponent(port)}&destination=${encodeURIComponent(destination)}`).then(r => r.json());
      const ids = (res.lane_rates || []).map(r => r.id);
      await Promise.all(ids.map(id =>
        apiFetch(`${API_BASE}/api/lane-rates/${id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ move_type: newMoveType }),
        }).catch(e => console.error("Reclassify failed for", id, e))
      ));
    }
    fetchData();
    if (searchOrigin || searchDest) searchLanes();
  }, [fetchData, searchLanes, searchOrigin, searchDest]);

  const handleMoveTypeDrop = useCallback((e, targetType) => {
    e.preventDefault();
    setDragOverType(null);
    try {
      const data = JSON.parse(e.dataTransfer.getData("application/json"));
      if (data.port || data.destination) {
        handleReclassifyLane(data.port, data.destination, data.rateIds, targetType);
      }
    } catch (err) { console.error("Drop parse error:", err); }
  }, [handleReclassifyLane]);

  // ── Navigate to lane detail ──
  const openLaneDetail = useCallback(async (origin, destination, idx = 0) => {
    setSelectedLane({ origin, destination });
    setSearchOrigin(origin || "");
    setSearchDest(destination || "");
    setLaneIndex(idx);
    setView("detail");
    if (origin && destination) saveRecent(origin, destination);
    // Trigger lane search for detail view
    setLaneSearching(true);
    try {
      const params = new URLSearchParams();
      if (origin) params.set("port", origin);
      if (destination) params.set("destination", destination);
      if (moveTypeFilter && moveTypeFilter !== "all") params.set("move_type", moveTypeFilter);
      const res = await apiFetch(`${API_BASE}/api/lane-rates?${params.toString()}`).then(r => r.json());
      setLaneResults(res.lane_rates || (Array.isArray(res) ? res : []));
      fetchMarketBenchmark(origin, destination);
    } catch (e) { console.error("Lane search:", e); setLaneResults([]); }
    setLaneSearching(false);
  }, [moveTypeFilter, fetchMarketBenchmark]);

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#8B95A8" }}>Loading Rate IQ...</div>;

  // ═════════════════════════════════════════════════════════════
  // BROWSE VIEW — Lane search landing page
  // ═════════════════════════════════════════════════════════════
  if (view === "browse") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate IQ</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
              {data?.total_rate_quotes || 0} quotes | {data?.total_carrier_quotes || 0} carrier emails | {rateLaneSummaries.length} lanes with rates
            </div>
          </div>
          {/* Secondary nav */}
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { key: "intake", label: "Rate Intake", icon: "📥" },
              { key: "oog", label: "OOG IQ", icon: "📦" },
              { key: "directory", label: `Directory (${dirCarriers.length})`, icon: "📖" },
              { key: "scorecard", label: "Scorecard", icon: "🏆" },
              { key: "history", label: "History", icon: "📊" },
            ].map(t => (
              <button key={t.key} onClick={() => setView(t.key)}
                style={{ padding: "6px 14px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#8B95A8", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 4 }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = "rgba(0,212,170,0.3)"; e.currentTarget.style.color = "#F0F2F5"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; e.currentTarget.style.color = "#8B95A8"; }}>
                <span style={{ fontSize: 12 }}>{t.icon}</span> {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Search Bar */}
        <div className="glass" style={{ borderRadius: 14, padding: "20px 24px", marginBottom: 24, border: "1px solid rgba(255,255,255,0.06)" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12 }}>SEARCH LANES</div>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
            <div style={{ flex: 1, position: "relative" }} ref={originRef}>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Origin / Port</label>
              <input value={searchOrigin} onChange={e => setSearchOrigin(e.target.value)} placeholder="e.g. Houston, NYNJ, Savannah..."
                style={{ width: "100%", padding: "10px 16px", borderRadius: 10, border: `1px solid ${originFocused ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 13, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onFocus={() => setOriginFocused(true)} onBlur={() => setTimeout(() => setOriginFocused(false), 150)}
                onKeyDown={e => e.key === "Enter" && searchLanes()} />
              {originFocused && originSuggestions.length > 0 && (
                <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, marginTop: 4, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "#151922", boxShadow: "0 12px 32px rgba(0,0,0,0.5)", overflow: "hidden" }}>
                  {originSuggestions.map((s, i) => (
                    <div key={i} onClick={() => { setSearchOrigin(s.port); setOriginFocused(false); }}
                      style={{ padding: "10px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: i < originSuggestions.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none", transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "#F0F2F5" }}>{s.port}</span>
                      <span style={{ fontSize: 11, color: "#5A6478" }}>{s.lanes} lane{s.lanes !== 1 ? "s" : ""} · {fmt(s.avg)} avg</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ fontSize: 18, color: "#5A6478", padding: "0 4px 10px" }}>→</div>
            <div style={{ flex: 1, position: "relative" }} ref={destRef}>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Destination</label>
              <input value={searchDest} onChange={e => setSearchDest(e.target.value)} placeholder="e.g. Dallas, Chicago..."
                style={{ width: "100%", padding: "10px 16px", borderRadius: 10, border: `1px solid ${destFocused ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 13, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onFocus={() => setDestFocused(true)} onBlur={() => setTimeout(() => setDestFocused(false), 150)}
                onKeyDown={e => e.key === "Enter" && searchLanes()} />
              {destFocused && destSuggestions.length > 0 && (
                <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, marginTop: 4, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "#151922", boxShadow: "0 12px 32px rgba(0,0,0,0.5)", overflow: "hidden" }}>
                  {destSuggestions.map((s, i) => (
                    <div key={i} onClick={() => { setSearchDest(s.destination); setDestFocused(false); }}
                      style={{ padding: "10px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: i < destSuggestions.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none", transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div>
                        <span style={{ fontSize: 13, fontWeight: 600, color: "#F0F2F5" }}>{searchOrigin || "•"} → {s.destination}</span>
                      </div>
                      <span style={{ fontSize: 11, color: "#5A6478" }}>{fmt(s.avg)} avg</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <button onClick={() => { searchLanes(); if (searchOrigin && searchDest) saveRecent(searchOrigin, searchDest); }} disabled={laneSearching}
              style={{ padding: "10px 28px", borderRadius: 10, border: "none", background: grad, color: "#0A0F1C", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", opacity: laneSearching ? 0.6 : 1, whiteSpace: "nowrap" }}>
              {laneSearching ? "Searching..." : "Search"}
            </button>
          </div>

          {/* Recent Searches */}
          {recentSearches.length > 0 && !searchOrigin && !searchDest && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12, alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", marginRight: 4 }}>Recent:</span>
              {recentSearches.map((r, i) => (
                <button key={i} onClick={() => { setSearchOrigin(r.origin); setSearchDest(r.destination); setTimeout(() => searchLanes(r.origin, r.destination), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(59,130,246,0.15)", background: "rgba(59,130,246,0.06)", color: "#60a5fa", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(59,130,246,0.12)"; e.currentTarget.style.borderColor = "rgba(59,130,246,0.3)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "rgba(59,130,246,0.06)"; e.currentTarget.style.borderColor = "rgba(59,130,246,0.15)"; }}>
                  {r.origin} → {r.destination}
                </button>
              ))}
            </div>
          )}

          {/* Port Group Quick Filters */}
          {portGroups.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", marginRight: 4 }}>Quick:</span>
              {portGroups.filter(g => !g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setSearchOrigin(g.name); setSearchDest(""); setTimeout(() => searchLanes(g.name, ""), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(0,212,170,0.15)", background: searchOrigin === g.name ? "rgba(0,212,170,0.10)" : "rgba(255,255,255,0.02)", color: searchOrigin === g.name ? "#00D4AA" : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
              {portGroups.filter(g => g.is_rail).length > 0 && <span style={{ color: "#2D3340", margin: "0 4px" }}>|</span>}
              {portGroups.filter(g => g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setSearchOrigin(g.name); setSearchDest(""); setTimeout(() => searchLanes(g.name, ""), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(167,139,250,0.15)", background: searchOrigin === g.name ? "rgba(167,139,250,0.10)" : "rgba(255,255,255,0.02)", color: searchOrigin === g.name ? "#A78BFA" : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Move Type Filter */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {[
            { key: "all", label: "All Types" },
            { key: "dray", label: "Dray", color: "#60a5fa" },
            { key: "ftl", label: "FTL", color: "#FBBF24" },
            { key: "transload", label: "Transload", color: "#a78bfa" },
          ].map(t => {
            const active = moveTypeFilter === t.key;
            const c = t.color || "#8B95A8";
            const isDropTarget = t.key !== "all" && dragOverType === t.key;
            return (
              <button key={t.key} onClick={() => setMoveTypeFilter(t.key)}
                onDragOver={t.key !== "all" ? (e => { e.preventDefault(); setDragOverType(t.key); }) : undefined}
                onDragLeave={t.key !== "all" ? (() => setDragOverType(null)) : undefined}
                onDrop={t.key !== "all" ? (e => handleMoveTypeDrop(e, t.key)) : undefined}
                style={{ padding: "5px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8,
                  border: `1px solid ${isDropTarget ? (t.color || "#00D4AA") : active ? (t.color ? t.color + "55" : "rgba(0,212,170,0.3)") : "rgba(255,255,255,0.06)"}`,
                  background: isDropTarget ? (t.color ? t.color + "30" : "rgba(0,212,170,0.20)") : active ? (t.color ? t.color + "18" : "rgba(0,212,170,0.08)") : "transparent",
                  color: active || isDropTarget ? (t.color || "#00D4AA") : "#5A6478", cursor: "pointer", fontFamily: "inherit",
                  transition: "all 0.15s", transform: isDropTarget ? "scale(1.08)" : "scale(1)" }}>
                {isDropTarget ? `→ ${t.label}` : t.label}
              </button>
            );
          })}
        </div>

        {/* Search Results */}
        {groupedLanes.filter(g => moveTypeFilter === "all" || g.move_type === moveTypeFilter).length > 0 && (
          <div style={{ marginBottom: 24 }}>
            {(() => { const filtered = groupedLanes.filter(g => moveTypeFilter === "all" || g.move_type === moveTypeFilter); return <>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12 }}>
              SEARCH RESULTS — {filtered.length} lane{filtered.length !== 1 ? "s" : ""}{moveTypeFilter !== "all" ? ` (${moveTypeFilter.toUpperCase()})` : ""}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 12 }}>
              {filtered.map((group, gi) => (
                <LaneCard key={gi} lane={{
                  origin_city: group.port, dest_city: group.destination, port: group.port, destination: group.destination,
                  load_count: group.count, avg_rate: group.count > 0 ? Math.round(group.total / group.count) : 0,
                  carrier_count: group.carriers.length,
                  miles: group.miles, origin_zip: group.origin_zip, dest_zip: group.dest_zip,
                  move_type: group.move_type,
                }} onClick={() => openLaneDetail(group.port, group.destination, gi)}
                  rateIds={(group.carriers || []).map(c => c.id).filter(Boolean)}
                  onReclassify={mt => handleReclassifyLane(group.port, group.destination, (group.carriers || []).map(c => c.id).filter(Boolean), mt)}
                  onQuickQuote={() => { setSelectedLane({ origin: group.port, destination: group.destination }); setView("build-quote"); }} />
              ))}
            </div>
            </>; })()}
          </div>
        )}

        {/* Lane Analysis — grouped by origin, collapsible */}
        {originGroups.length > 0 && groupedLanes.length === 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
              LANE ANALYSIS
              <span style={{ fontSize: 11, color: "#5A6478", fontWeight: 500 }}>— {originGroups.length} origin{originGroups.length !== 1 ? "s" : ""}, {originGroups.reduce((s, g) => s + g.lanes.length, 0)} lanes{moveTypeFilter !== "all" ? ` (${moveTypeFilter.toUpperCase()})` : ""}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {originGroups.map(group => {
                const isOpen = !!expandedOrigins[group.origin];
                return (
                  <div key={group.origin} className="glass" style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", overflow: "hidden" }}>
                    {/* Origin header row */}
                    <div onClick={() => setExpandedOrigins(prev => ({ ...prev, [group.origin]: !prev[group.origin] }))}
                      style={{ padding: "14px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", transition: "background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <span style={{ fontSize: 12, color: "#5A6478", transform: isOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s", display: "inline-block" }}>▼</span>
                        <div>
                          <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5" }}>{group.origin}</div>
                          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 1 }}>
                            {group.lanes.length} lane{group.lanes.length !== 1 ? "s" : ""} · {group.totalLoads} rate{group.totalLoads !== 1 ? "s" : ""} on file
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                        {group.avgRate > 0 && (
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 18, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(group.avgRate)}</div>
                            <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 600 }}>avg rate</div>
                          </div>
                        )}
                      </div>
                    </div>
                    {/* Expanded lanes */}
                    {isOpen && (
                      <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                        {group.lanes
                          .sort((a, b) => (b.load_count || 0) - (a.load_count || 0))
                          .map((ls, li) => {
                            const avgRate = ls.avg_rate || ls.average || 0;
                            const mtStyle = MOVE_TYPE_STYLES[(ls.move_type || "dray").toLowerCase()] || MOVE_TYPE_STYLES.dray;
                            return (
                              <div key={li} onClick={() => openLaneDetail(ls.port, ls.destination, 0)}
                                style={{ padding: "12px 20px 12px 44px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.03)", transition: "background 0.1s" }}
                                onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                  <span style={{ fontSize: 13, color: "#C8D0DC", fontWeight: 600 }}>→ {ls.destination || ls.dest_city || "—"}</span>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: mtStyle.bg, color: mtStyle.color, border: `1px solid ${mtStyle.border}` }}>{mtStyle.label}</span>
                                  <span style={{ fontSize: 11, color: "#5A6478" }}>{ls.load_count || 0} rate{(ls.load_count || 0) !== 1 ? "s" : ""}</span>
                                  {ls.carrier_count > 0 && <span style={{ fontSize: 11, color: "#5A6478" }}>{ls.carrier_count} carrier{ls.carrier_count !== 1 ? "s" : ""}</span>}
                                  {ls.miles > 0 && <span style={{ fontSize: 11, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{(ls.miles * ((ls.move_type || "dray") === "dray" ? 2 : 1)).toLocaleString()} mi</span>}
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                  {ls.trend_pct != null && Math.abs(ls.trend_pct) > 2 && (
                                    <span style={{ fontSize: 11, fontWeight: 700, color: ls.trend_pct > 0 ? "#f87171" : "#34d399" }}>
                                      {ls.trend_pct > 0 ? "↑" : "↓"} {Math.abs(ls.trend_pct).toFixed(1)}%
                                    </span>
                                  )}
                                  {avgRate > 0 && (
                                    <span style={{ fontSize: 15, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(avgRate)}</span>
                                  )}
                                  <span style={{ fontSize: 11, color: "#5A6478" }}>→</span>
                                </div>
                              </div>
                            );
                          })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {rateLaneSummaries.length === 0 && groupedLanes.length === 0 && !laneSearching && (
          <div style={{ padding: 60, textAlign: "center", color: "#5A6478" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#F0F2F5" }}>Search for a lane to get started</div>
            <div style={{ fontSize: 12, marginTop: 6 }}>Enter an origin and destination above, or click a port quick filter</div>
          </div>
        )}
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // DETAIL VIEW — Lane rate intelligence (DrayRates-inspired)
  // ═════════════════════════════════════════════════════════════
  if (view === "detail") {
    const currentGroup = groupedLanes[laneIndex] || groupedLanes[0] || null;
    const laneName = selectedLane ? `${selectedLane.origin || "—"} → ${selectedLane.destination || "—"}` : "—";

    return (
      <div style={{ padding: "0 24px 24px" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <button onClick={() => setView("browse")}
              style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}
              onMouseEnter={e => e.currentTarget.style.color = "#F0F2F5"} onMouseLeave={e => e.currentTarget.style.color = "#8B95A8"}>
              ←
            </button>
            <div>
              <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>{laneName}</h2>
              {currentGroup && (
                <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
                  {currentGroup.carriers.length} carrier rate{currentGroup.carriers.length !== 1 ? "s" : ""} on file
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {/* Prev / Next */}
            {groupedLanes.length > 1 && (
              <div style={{ display: "flex", gap: 4, marginRight: 8 }}>
                <button disabled={laneIndex <= 0} onClick={() => { const ni = laneIndex - 1; setLaneIndex(ni); const g = groupedLanes[ni]; if (g) setSelectedLane({ origin: g.port, destination: g.destination }); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: laneIndex > 0 ? "#F0F2F5" : "#2D3340", fontSize: 11, fontWeight: 600, cursor: laneIndex > 0 ? "pointer" : "default", fontFamily: "inherit" }}>
                  ← Previous
                </button>
                <button disabled={laneIndex >= groupedLanes.length - 1} onClick={() => { const ni = laneIndex + 1; setLaneIndex(ni); const g = groupedLanes[ni]; if (g) setSelectedLane({ origin: g.port, destination: g.destination }); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: laneIndex < groupedLanes.length - 1 ? "#F0F2F5" : "#2D3340", fontSize: 11, fontWeight: 600, cursor: laneIndex < groupedLanes.length - 1 ? "pointer" : "default", fontFamily: "inherit" }}>
                  Next →
                </button>
              </div>
            )}
            <button onClick={() => setView("build-quote")}
              style={{ padding: "8px 20px", borderRadius: 10, border: "none", background: grad, color: "#0A0F1C", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 6 }}>
              Build Quote
            </button>
          </div>
        </div>

        {laneSearching && <div style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>Searching lane rates...</div>}

        {!laneSearching && currentGroup && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20 }}>
            {/* Left column — Market Rate + Carrier Table */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <MarketRateCard laneGroup={currentGroup} carrierCapMap={carrierCapMap} />

              {marketBenchmark && <MarketBenchmarkCard benchmark={marketBenchmark} carrierAvg={currentGroup.count > 0 ? Math.round(currentGroup.total / currentGroup.count) : 0} />}

              {/* Cost Analysis */}
              <div className="glass" style={{ borderRadius: 14, padding: "18px 24px", border: "1px solid rgba(255,255,255,0.06)" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 16 }}>COST ANALYSIS</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Avg Carrier Cost</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>
                      {fmt(currentGroup.count > 0 ? Math.round(currentGroup.total / currentGroup.count) : 0)}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>based on {currentGroup.count} data point{currentGroup.count !== 1 ? "s" : ""}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Floor Rate</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#60a5fa", fontFamily: "'JetBrains Mono', monospace" }}>
                      {currentGroup.minRate !== Infinity ? fmt(currentGroup.minRate) : "—"}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>lowest on file</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Ceiling Rate</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#fb923c", fontFamily: "'JetBrains Mono', monospace" }}>
                      {currentGroup.maxRate > 0 ? fmt(currentGroup.maxRate) : "—"}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>highest on file</div>
                  </div>
                </div>
              </div>

              <CarrierRateTable
                carriers={currentGroup.carriers}
                carrierCapMap={carrierCapMap}
                editingLaneRateId={editingLaneRateId} editingLaneField={editingLaneField} editingLaneValue={editingLaneValue}
                setEditingLaneRateId={setEditingLaneRateId} setEditingLaneField={setEditingLaneField} setEditingLaneValue={setEditingLaneValue}
                handleLaneRateUpdate={handleLaneRateUpdate}
                laneOrigin={currentGroup.port} laneDestination={currentGroup.destination}
              />
            </div>

            {/* Right column — AI Rate Assistant */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="glass" style={{ borderRadius: 14, border: "1px solid rgba(255,255,255,0.06)", flex: 1, display: "flex", flexDirection: "column" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 32, height: 32, borderRadius: "50%", background: "rgba(0,212,170,0.12)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🤖</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>AI Rate Assistant</div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>Lane intelligence for {selectedLane?.origin || "—"}</div>
                  </div>
                </div>
                <div style={{ padding: "16px 20px", flex: 1, overflowY: "auto" }}>
                  {/* Rate Insights */}
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", marginBottom: 10 }}>Rate Insights</div>

                  {/* Trend analysis */}
                  {currentGroup.count >= 3 && (() => {
                    const sorted = [...currentGroup.carriers].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
                    const recentAvg = sorted.slice(-3).reduce((s, c) => s + parseFloat(c.total || c.dray_rate || 0), 0) / Math.min(sorted.length, 3);
                    const oldAvg = sorted.slice(0, 3).reduce((s, c) => s + parseFloat(c.total || c.dray_rate || 0), 0) / Math.min(sorted.length, 3);
                    const trend = recentAvg > oldAvg ? "rising" : recentAvg < oldAvg ? "falling" : "stable";
                    const trendColor = trend === "rising" ? "#f87171" : trend === "falling" ? "#34d399" : "#8B95A8";
                    const pctChange = oldAvg > 0 ? Math.abs(((recentAvg - oldAvg) / oldAvg) * 100).toFixed(0) : 0;
                    return (
                      <div style={{ padding: "10px 14px", borderRadius: 10, background: trendColor + "08", border: `1px solid ${trendColor}20`, marginBottom: 12 }}>
                        <div style={{ fontSize: 11, color: "#C8D0DC", lineHeight: 1.5 }}>
                          Rates on this lane are <span style={{ fontWeight: 700, color: trendColor }}>{trend}</span>
                          {pctChange > 2 && <span> ({pctChange}% {trend === "rising" ? "increase" : "decrease"})</span>}.
                          {trend === "rising" && " Consider locking in rates soon."}
                          {trend === "falling" && " Good opportunity to negotiate."}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Potential accessorial charges */}
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#C8D0DC", marginTop: 8, marginBottom: 8 }}>Potential Accessorial Charges</div>
                  {[
                    { icon: "📦", label: "Chassis fee", desc: "$35-55/day — check carrier terms" },
                    { icon: "⏱", label: "Detention", desc: "$75-100/hr after free time" },
                    { icon: "🏗", label: "Pre-pull", desc: "$125-200 if required" },
                    { icon: "📋", label: "Storage", desc: "$35-55/day at terminal" },
                    { icon: "⚖", label: "Overweight surcharge", desc: "$100-200 flat" },
                  ].map((item, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <span style={{ fontSize: 12, marginTop: 1 }}>{item.icon}</span>
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#C8D0DC" }}>{item.label}</div>
                        <div style={{ fontSize: 11, color: "#5A6478" }}>{item.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* AI Chat Input */}
                <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input placeholder="Ask me anything about this lane..."
                      onKeyDown={e => {
                        if (e.key === "Enter" && e.target.value.trim()) {
                          // Dispatch Ask AI with lane context
                          const query = e.target.value.trim();
                          e.target.value = "";
                          document.dispatchEvent(new CustomEvent("openAskAI", { detail: { query: `[Lane: ${laneName}] ${query}` } }));
                          document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
                        }
                      }}
                      style={{ flex: 1, padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                    <button style={{ padding: "8px 14px", borderRadius: 8, border: "none", background: "rgba(0,212,170,0.12)", color: "#00D4AA", fontSize: 13, cursor: "pointer" }}>→</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {!laneSearching && !currentGroup && (
          <div style={{ padding: 60, textAlign: "center", color: "#5A6478" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>📭</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#F0F2F5" }}>No rate data found for this lane</div>
            <div style={{ fontSize: 12, marginTop: 6 }}>Try a different origin or destination</div>
          </div>
        )}
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // RATE INTAKE VIEW (unified carrier rates + market rates)
  // ═════════════════════════════════════════════════════════════
  if (view === "intake") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate Intake</h2>
          <span style={{ fontSize: 11, color: "#5A6478" }}>Drop carrier rate emails, screenshots, or paste rate data</span>
        </div>

        {/* Hidden file inputs */}
        <input ref={intakeFileRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.msg,.eml,.html,.htm,.txt" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setIntakeFile(f); setIntakeResult(null); } e.target.value = ""; }} />
        <input ref={marketRateFileRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setIntakeFile(f); setIntakeResult(null); } e.target.value = ""; }} />

        {/* Unified Drag-Drop Zone */}
        <div className="glass" style={{ borderRadius: 14, padding: 32, marginBottom: 20,
          border: `2px dashed ${intakeDragOver ? "rgba(0,212,170,0.5)" : "rgba(255,255,255,0.1)"}`,
          background: intakeDragOver ? "rgba(0,212,170,0.04)" : "rgba(255,255,255,0.01)",
          textAlign: "center", transition: "all 0.2s", cursor: "pointer" }}
          onClick={() => intakeFileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIntakeDragOver(true); }}
          onDragLeave={() => setIntakeDragOver(false)}
          onDrop={e => {
            e.preventDefault(); e.stopPropagation(); setIntakeDragOver(false);
            const file = e.dataTransfer.files?.[0];
            if (file) { setIntakeFile(file); setIntakeResult(null); setMarketRateResult(null); return; }
            const text = e.dataTransfer.getData("text/plain");
            if (text) { setIntakeText(text); }
          }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.4 }}>&#128206;</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#8B95A8", marginBottom: 4 }}>
            Drop carrier quote or rate screenshot here
          </div>
          <div style={{ fontSize: 11, color: "#5A6478" }}>
            .msg / .eml emails, screenshots, PDFs, or paste text below
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <button onClick={e => { e.stopPropagation(); intakeFileRef.current?.click(); }}
              style={{ padding: "6px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#34d399", cursor: "pointer", fontFamily: "inherit" }}>
              Browse Files
            </button>
          </div>
        </div>

        {/* File badge */}
        {intakeFile && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", marginBottom: 12, borderRadius: 10, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}>
            <span style={{ fontSize: 11, color: "#34d399", fontWeight: 700 }}>File:</span>
            <span style={{ fontSize: 11, color: "#C8D0DC", fontFamily: "'JetBrains Mono', monospace" }}>{intakeFile.name}</span>
            <span style={{ fontSize: 10, color: "#5A6478" }}>({(intakeFile.size / 1024).toFixed(1)} KB)</span>
            <button onClick={() => setIntakeFile(null)} style={{ marginLeft: "auto", fontSize: 10, color: "#f87171", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}>Remove</button>
          </div>
        )}

        {/* Text paste area */}
        {!intakeFile && (
          <textarea value={intakeText} onChange={e => setIntakeText(e.target.value)}
            onPaste={e => {
              const items = e.clipboardData?.items;
              if (items) {
                for (const item of items) {
                  if (item.type.startsWith("image/")) {
                    e.preventDefault();
                    const file = item.getAsFile();
                    if (file) { setIntakeFile(file); setIntakeResult(null); }
                    return;
                  }
                }
              }
              const text = e.clipboardData.getData("text/plain");
              if (text && !intakeText) { e.preventDefault(); setIntakeText(text); }
            }}
            placeholder={"Paste carrier rate email, or tab-separated market rate data:\n\n2026-Mar-14\tLong Beach Container\t$2,600\t0%\t$2,600\n2026-Mar-12\tAPM Los Angeles\t$2,250\t0%\t$2,250"}
            style={{ width: "100%", minHeight: 120, maxHeight: 240, padding: 14, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)", color: "#F0F2F5", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", outline: "none", resize: "vertical", boxSizing: "border-box", marginBottom: 12 }} />
        )}

        {/* Controls row */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          {/* Move type */}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Type:</span>
            {["dray", "transload", "ftl"].map(mt => {
              const active = intakeMoveType === mt;
              const s = MOVE_TYPE_STYLES[mt];
              return (
                <button key={mt} onClick={() => setIntakeMoveType(mt)}
                  style={{ padding: "4px 12px", fontSize: 11, fontWeight: 700, borderRadius: 6, border: `1px solid ${active ? s.color + "55" : "rgba(255,255,255,0.06)"}`, background: active ? s.color + "18" : "transparent", color: active ? s.color : "#5A6478", cursor: "pointer", fontFamily: "inherit" }}>
                  {s.label}
                </button>
              );
            })}
          </div>

          {/* Optional origin/dest for market rates */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
            <input value={marketRateOrigin} onChange={e => setMarketRateOrigin(e.target.value)} placeholder="Origin (optional)"
              style={{ width: 140, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
            <span style={{ color: "#5A6478", fontSize: 11 }}>→</span>
            <input value={marketRateDest} onChange={e => setMarketRateDest(e.target.value)} placeholder="Destination (optional)"
              style={{ width: 140, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
          </div>
        </div>

        {/* Results / Actions */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
          <div style={{ fontSize: 11, color: "#5A6478" }}>
            {intakeFile ? "Ready to extract from file" : intakeText.length > 0 ? `${intakeText.length.toLocaleString()} chars` : ""}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {intakeResult?.ok && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#34d399" }}>
                ✓ {intakeResult.extracted ? `Added: ${intakeResult.extracted.carrier_name} — ${intakeResult.extracted.origin} → ${intakeResult.extracted.destination}${intakeResult.extracted.rate_amount ? ` @ $${intakeResult.extracted.rate_amount}` : ""}` : `Saved ${intakeResult.inserted || 0} rate(s)`}
              </span>
            )}
            {intakeResult?.error && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#f87171" }}>✗ {intakeResult.error}</span>
            )}
            {marketRateResult?.ok && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#34d399" }}>
                ✓ Saved {marketRateResult.inserted} rate{marketRateResult.inserted !== 1 ? "s" : ""}{marketRateResult.skipped > 0 ? ` (${marketRateResult.skipped} skipped)` : ""}
              </span>
            )}
            {marketRateResult?.error && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#f87171" }}>✗ {marketRateResult.error}</span>
            )}
            {(intakeText.trim() || intakeFile) && (
              <button onClick={() => {
                // Auto-detect: if text looks like tab-separated market data and has origin/dest, use market rate handler
                const isTabSeparated = intakeText && intakeText.includes("\t") && marketRateOrigin.trim() && marketRateDest.trim();
                if (isTabSeparated && !intakeFile) {
                  setMarketRateText(intakeText);
                  setMarketRateMoveType(intakeMoveType);
                  handleMarketRatePaste();
                } else {
                  handleManualIntake();
                }
              }} disabled={intakeProcessing || marketRateProcessing}
                style={{ padding: "8px 24px", borderRadius: 8, border: "none", background: grad, color: "#0A0F1C", fontSize: 12, fontWeight: 700, cursor: (intakeProcessing || marketRateProcessing) ? "wait" : "pointer", fontFamily: "inherit", opacity: (intakeProcessing || marketRateProcessing) ? 0.6 : 1 }}>
                {(intakeProcessing || marketRateProcessing) ? "Extracting..." : "Extract & Save"}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // BUILD QUOTE VIEW (from lane detail)
  // ═════════════════════════════════════════════════════════════
  if (view === "build-quote") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView(selectedLane ? "detail" : "browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Build Quote</h2>
          {selectedLane && <span style={{ fontSize: 12, color: "#5A6478" }}>{selectedLane.origin} → {selectedLane.destination}</span>}
        </div>
        <div style={{ height: "calc(100vh - 180px)" }}>
          <QuoteBuilder prefill={selectedLane || undefined} />
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // OOG IQ VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "oog") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>OOG IQ — Oversize Quote Builder</h2>
        </div>
        <OOGQuoteBuilder />
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // SCORECARD VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "scorecard") {
    return (
      <div style={{ padding: "0 24px 24px", maxWidth: 1200 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Carrier Scorecard</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>{scorecardPerf.length} carriers with performance data</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {scorecardPerf.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>
              No carrier performance data yet — data populates from completed loads.
            </div>
          )}
          {scorecardPerf.map((c, i) => {
            const isExpanded = expandedCarrier === c.carrier;
            const otColor = c.on_time_pct >= 90 ? "#34d399" : c.on_time_pct >= 70 ? "#FBBF24" : c.on_time_pct > 0 ? "#f87171" : "#8B95A8";
            const otBg = c.on_time_pct >= 90 ? "rgba(34,197,94,0.12)" : c.on_time_pct >= 70 ? "rgba(245,158,11,0.12)" : c.on_time_pct > 0 ? "rgba(239,68,68,0.12)" : "rgba(107,114,128,0.12)";
            return (
              <div key={i} className="glass" style={{ borderRadius: 12, overflow: "hidden", border: isExpanded ? "1px solid rgba(0,212,170,0.2)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setExpandedCarrier(isExpanded ? null : c.carrier)}
                  style={{ padding: "12px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: 16, transition: "background 0.15s ease" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.carrier}</div>
                    <div style={{ fontSize: 11, color: "#5A6478", marginTop: 1 }}>{c.primary_move_type || "—"}{c.last_delivery ? ` · Last: ${c.last_delivery}` : ""}</div>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center", flexShrink: 0 }}>
                    <div style={{ textAlign: "center", minWidth: 44 }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.total_loads}</div>
                      <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600, letterSpacing: "0.5px" }}>LOADS</div>
                    </div>
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: otBg, color: otColor, border: `1px solid ${otColor}30` }}>{c.on_time_pct}% OT</span>
                    {c.avg_transit_days != null && (
                      <div style={{ textAlign: "center", minWidth: 44 }}>
                        <div style={{ fontSize: 14, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.avg_transit_days}</div>
                        <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600 }}>AVG DAYS</div>
                      </div>
                    )}
                    <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60a5fa", fontSize: 11, fontWeight: 700 }}>{c.lanes_served} lane{c.lanes_served !== 1 ? "s" : ""}</span>
                    <span style={{ color: "#5A6478", fontSize: 14, transition: "transform 0.2s", transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}>▼</span>
                  </div>
                </div>
                {isExpanded && c.top_lanes?.length > 0 && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "10px 16px 14px" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Top Lanes</div>
                    {c.top_lanes.map((tl, li) => (
                      <div key={li} onClick={() => openLaneDetail(tl.lane?.split("→")[0]?.trim(), tl.lane?.split("→")[1]?.trim(), 0)}
                        style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(255,255,255,0.02)", marginBottom: 3, cursor: "pointer", transition: "background 0.15s" }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"} onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#00D4AA", flex: 1 }}>{tl.lane}</div>
                        <div style={{ fontSize: 12, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{tl.count}</div>
                        <div style={{ fontSize: 8, color: "#5A6478" }}>loads</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // DIRECTORY VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "directory") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Carrier Directory</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>{dirCarriers.length} carriers</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button onClick={() => setShowAddCarrier(!showAddCarrier)}
              style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(0,212,170,0.3)", background: showAddCarrier ? "rgba(0,212,170,0.1)" : "transparent", color: "#34d399", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
              + Add Carrier
            </button>
          </div>
        </div>

        {/* LoadMatch Screenshot Import */}
        <input ref={dirScreenshotRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setDirScreenshotFile(f); setDirScreenshotResult(null); } e.target.value = ""; }} />
        <div style={{ borderRadius: 10, padding: "12px 16px", marginBottom: 12,
          border: "1px dashed rgba(251,146,60,0.25)", background: "rgba(251,146,60,0.02)",
          display: "flex", alignItems: "center", gap: 12, cursor: "pointer" }}
          onClick={() => dirScreenshotRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) { setDirScreenshotFile(f); setDirScreenshotResult(null); } }}>
          <span style={{ fontSize: 11, color: "#fb923c", fontWeight: 700 }}>LOADMATCH IMPORT</span>
          <span style={{ fontSize: 11, color: "#5A6478" }}>— drop screenshot to extract carriers + capabilities</span>
          {dirScreenshotFile && (
            <span style={{ fontSize: 11, color: "#C8D0DC", fontFamily: "'JetBrains Mono', monospace", marginLeft: 8 }}>
              {dirScreenshotFile.name}
              <button onClick={e => { e.stopPropagation(); setDirScreenshotFile(null); setDirScreenshotResult(null); }} style={{ marginLeft: 6, fontSize: 10, color: "#f87171", background: "none", border: "none", cursor: "pointer" }}>×</button>
            </span>
          )}
          {dirScreenshotFile && !dirScreenshotProcessing && (
            <button onClick={e => { e.stopPropagation(); handleDirScreenshot(); }}
              style={{ marginLeft: "auto", padding: "4px 14px", borderRadius: 6, border: "none", background: "linear-gradient(135deg, #fb923c, #f59e0b)", color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
              Extract & Import
            </button>
          )}
          {dirScreenshotProcessing && <span style={{ marginLeft: "auto", fontSize: 11, color: "#fb923c" }}>Extracting...</span>}
          {dirScreenshotResult?.error && <span style={{ fontSize: 11, color: "#f87171", marginLeft: "auto" }}>✗ {dirScreenshotResult.error}</span>}
          {dirScreenshotResult?.carriers && <span style={{ fontSize: 11, color: "#34d399", marginLeft: "auto" }}>✓ Imported {dirScreenshotResult.carriers.length} carriers</span>}
          {dirScreenshotResult?.saved && <span style={{ fontSize: 11, color: "#34d399", marginLeft: "auto" }}>✓ Imported {dirScreenshotResult.saved.length} carriers</span>}
        </div>

        {/* Add Carrier Form */}
        {showAddCarrier && (
          <div className="glass" style={{ borderRadius: 10, padding: 16, marginBottom: 12, border: "1px solid rgba(0,212,170,0.2)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 180px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>Carrier Name *</label>
                <input value={newCarrier.carrier_name} onChange={e => setNewCarrier(p => ({ ...p, carrier_name: e.target.value }))} placeholder="Carrier name"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <div style={{ flex: "0 0 120px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>MC#</label>
                <input value={newCarrier.mc_number} onChange={e => setNewCarrier(p => ({ ...p, mc_number: e.target.value }))} placeholder="MC number"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <div style={{ flex: "1 1 140px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>City / State</label>
                <input value={newCarrier.pickup_area} onChange={e => setNewCarrier(p => ({ ...p, pickup_area: e.target.value }))} placeholder="e.g. Los Angeles, CA"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <button onClick={handleAddCarrier} disabled={addCarrierSaving || !newCarrier.carrier_name.trim()}
                style={{ padding: "6px 16px", borderRadius: 6, border: "none", background: grad, color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: (addCarrierSaving || !newCarrier.carrier_name.trim()) ? "default" : "pointer", fontFamily: "inherit", opacity: (addCarrierSaving || !newCarrier.carrier_name.trim()) ? 0.5 : 1 }}>
                {addCarrierSaving ? "Saving..." : "Add"}
              </button>
              <button onClick={() => setShowAddCarrier(false)}
                style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
          <input value={dirSearch} onChange={e => setDirSearch(e.target.value)} placeholder="Search carrier, MC#, email..."
            style={{ flex: "1 1 200px", minWidth: 200, padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
          <select value={dirMarket} onChange={e => setDirMarket(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#151926", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
            <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Markets</option>
            {allMarkets.map(m => <option key={m} value={m} style={{ background: "#151926", color: "#F0F2F5" }}>{m}</option>)}
          </select>
          <select value={dirPort} onChange={e => setDirPort(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${dirPort !== "all" ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: dirPort !== "all" ? "rgba(0,212,170,0.06)" : "#151926", color: dirPort !== "all" ? "#00D4AA" : "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
            <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Ports/Rails</option>
            {portGroups.filter(g => !g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
            <option disabled style={{ background: "#151926", color: "#5A6478" }}>── Rail ──</option>
            {portGroups.filter(g => g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
          </select>
          {CAP_OPTIONS.map(cap => {
            const active = dirCaps.includes(cap.key);
            return <button key={cap.key} onClick={() => setDirCaps(prev => active ? prev.filter(c => c !== cap.key) : [...prev, cap.key])}
              style={{ padding: "5px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", border: `1px solid ${active ? cap.color + "60" : "rgba(255,255,255,0.06)"}`, background: active ? cap.color + "18" : "transparent", color: active ? cap.color : "#8B95A8", fontFamily: "inherit", transition: "all 0.15s" }}>
              {cap.label}
            </button>;
          })}
          <button onClick={() => setDirHideDnu(!dirHideDnu)}
            style={{ padding: "5px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", border: `1px solid ${dirHideDnu ? "rgba(255,255,255,0.06)" : "rgba(239,68,68,0.4)"}`, background: dirHideDnu ? "transparent" : "rgba(239,68,68,0.1)", color: dirHideDnu ? "#8B95A8" : "#f87171", fontFamily: "inherit" }}>
            {dirHideDnu ? "Show DNU" : "Hide DNU"}
          </button>
        </div>
        <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 12 }}>{filteredDir.length} carriers · {allMarkets.length} markets</div>

        {/* Carrier Cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {filteredDir.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>No carriers match your filters.</div>}
          {filteredDir.slice(0, 100).map((c, i) => {
            const isExp = dirExpanded === (c.id || i);
            const tierColors = { 1: { bg: "rgba(34,197,94,0.12)", color: "#34d399", label: "Tier 1" }, 2: { bg: "rgba(245,158,11,0.12)", color: "#FBBF24", label: "Tier 2" }, 3: { bg: "rgba(251,146,60,0.12)", color: "#fb923c", label: "Tier 3" }, 0: { bg: "rgba(239,68,68,0.12)", color: "#f87171", label: "DNU" } };
            const tier = tierColors[c.tier_rank] || { bg: "rgba(107,114,128,0.08)", color: "#6B7280", label: "Unranked" };
            const isEdit = editingCarrierId === c.id;
            return (
              <div key={c.id || i} className="glass" style={{ borderRadius: 10, overflow: "hidden", border: isExp ? "1px solid rgba(0,212,170,0.2)" : c.dnu ? "1px solid rgba(239,68,68,0.15)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setDirExpanded(isExp ? null : (c.id || i))} style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12, transition: "background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: c.dnu ? "#f87171" : "#F0F2F5", textDecoration: c.dnu ? "line-through" : "none" }}>{c.carrier_name}</span>
                      {c.mc_number && <span style={{ fontSize: 11, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{c.mc_number}</span>}
                    </div>
                    <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
                      {isEdit ? (
                        CAP_OPTIONS.map(cap => (
                          <span key={cap.key} onClick={e => { e.stopPropagation(); handleCarrierUpdate(c.id, cap.key, !c[cap.key]); }}
                            style={{ padding: "1px 7px", borderRadius: 4, fontSize: 8, fontWeight: 700, cursor: "pointer", transition: "all 0.15s",
                              background: c[cap.key] ? cap.color + "18" : "rgba(255,255,255,0.02)", color: c[cap.key] ? cap.color : "#3D4557",
                              border: `1px solid ${c[cap.key] ? cap.color + "30" : "rgba(255,255,255,0.06)"}` }}>{cap.label}</span>
                        ))
                      ) : (
                        CAP_OPTIONS.filter(cap => c[cap.key]).map(cap => (
                          <span key={cap.key} style={{ padding: "1px 7px", borderRadius: 4, fontSize: 8, fontWeight: 700, background: cap.color + "18", color: cap.color, border: `1px solid ${cap.color}30` }}>{cap.label}</span>
                        ))
                      )}
                    </div>
                  </div>
                  <button onClick={e => { e.stopPropagation(); setEditingCarrierId(isEdit ? null : c.id); if (!isExp) setDirExpanded(c.id || i); }}
                    title="Edit carrier" style={{ padding: "3px 8px", borderRadius: 6, border: isEdit ? "1px solid rgba(0,212,170,0.4)" : "1px solid rgba(255,255,255,0.06)", background: isEdit ? "rgba(0,212,170,0.1)" : "transparent", color: isEdit ? "#00D4AA" : "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit", flexShrink: 0, transition: "all 0.15s" }}>
                    {isEdit ? "Done" : "✏️"}
                  </button>
                  {isEdit ? (
                    <select value={c.tier_rank ?? ""} onClick={e => e.stopPropagation()}
                      onChange={e => { const v = e.target.value === "" ? null : parseInt(e.target.value); handleCarrierUpdate(c.id, "tier_rank", v); if (v === 0) handleCarrierUpdate(c.id, "dnu", true); else if (c.dnu) handleCarrierUpdate(c.id, "dnu", false); }}
                      style={{ padding: "3px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: "#151926", color: tier.color, border: `1px solid ${tier.color}30`, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 }}>
                      <option value="" style={{ background: "#151926", color: "#6B7280" }}>Unranked</option>
                      <option value="1" style={{ background: "#151926", color: "#34d399" }}>Tier 1</option>
                      <option value="2" style={{ background: "#151926", color: "#FBBF24" }}>Tier 2</option>
                      <option value="3" style={{ background: "#151926", color: "#fb923c" }}>Tier 3</option>
                      <option value="0" style={{ background: "#151926", color: "#f87171" }}>DNU</option>
                    </select>
                  ) : (
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: tier.bg, color: tier.color, border: `1px solid ${tier.color}30`, flexShrink: 0 }}>{tier.label}</span>
                  )}
                  <div style={{ display: "flex", gap: 3, flexShrink: 0, flexWrap: "wrap", maxWidth: 200 }}>
                    {(c.markets || []).slice(0, 4).map(m => (
                      <span key={m} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 600, background: "rgba(59,130,246,0.1)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.2)" }}>{m}</span>
                    ))}
                    {(c.markets || []).length > 4 && <span style={{ fontSize: 8, color: "#5A6478" }}>+{c.markets.length - 4}</span>}
                  </div>
                  {c.trucks && <div style={{ textAlign: "center", minWidth: 36, flexShrink: 0 }}><div style={{ fontSize: 13, fontWeight: 800, color: "#F0F2F5" }}>{c.trucks}</div><div style={{ fontSize: 7, color: "#5A6478", fontWeight: 600 }}>TRUCKS</div></div>}
                  <span style={{ color: "#5A6478", fontSize: 12, transition: "transform 0.2s", transform: isExp ? "rotate(180deg)" : "rotate(0)", flexShrink: 0 }}>▼</span>
                </div>
                {isExp && (() => {
                  const editInput = (label, field, opts = {}) => {
                    const val = c[field] || "";
                    if (!isEdit && !val) return null;
                    const iStyle = { width: "100%", padding: "3px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
                    return (
                      <div style={{ fontSize: 11, marginBottom: 4 }}>
                        <span style={{ color: "#5A6478" }}>{label}: </span>
                        {isEdit ? (
                          <input defaultValue={val} key={val} onClick={e => e.stopPropagation()}
                            onBlur={e => { const v = e.target.value.trim(); if (v !== (c[field] || "")) handleCarrierUpdate(c.id, field, v || null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                            placeholder={opts.placeholder || ""} style={iStyle} />
                        ) : (
                          <span style={{ color: opts.color || "#C8D0DC", cursor: opts.copyable ? "pointer" : "default" }}
                            onClick={opts.copyable ? (e => { e.stopPropagation(); navigator.clipboard.writeText(val); }) : undefined}>
                            {val}{opts.copyable ? " 📋" : ""}
                          </span>
                        )}
                      </div>
                    );
                  };
                  return (
                    <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "12px 14px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <div>
                        {editInput("Email", "contact_email", { color: "#00D4AA", copyable: true, placeholder: "carrier@email.com" })}
                        {editInput("Phone", "contact_phone", { placeholder: "555-123-4567" })}
                        {editInput("MC#", "mc_number", { placeholder: "MC number" })}
                        {editInput("Equipment", "equipment_types", { placeholder: "Dry Van, Flatbed..." })}
                        {editInput("Insurance", "insurance_info", { placeholder: "Insurance details" })}
                        {isEdit && (
                          <div style={{ fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: "#5A6478" }}>Trucks: </span>
                            <input type="number" defaultValue={c.trucks || ""} key={c.trucks} onClick={e => e.stopPropagation()}
                              onBlur={e => { const v = e.target.value.trim(); const n = v ? parseInt(v) : null; if (n !== c.trucks) handleCarrierUpdate(c.id, "trucks", n); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                              placeholder="0" style={{ width: 60, padding: "3px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                          </div>
                        )}
                      </div>
                      <div>
                        {editInput("Feedback", "service_feedback", { placeholder: "Good Rates, Reliable..." })}
                        {editInput("Notes", "service_notes", { placeholder: "Operational notes" })}
                        {editInput("Record", "service_record", { placeholder: "Worked with Previously" })}
                        {editInput("Comments", "comments", { color: c.dnu ? "#f87171" : "#C8D0DC", placeholder: "General comments" })}
                      </div>
                      {isEdit && (
                        <div style={{ gridColumn: "1 / -1", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 8, display: "flex", justifyContent: "flex-end" }}>
                          {deleteConfirm === c.id ? (
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <span style={{ fontSize: 11, color: "#f87171" }}>Delete this carrier?</span>
                              <button onClick={e => { e.stopPropagation(); handleDeleteCarrier(c.id); }}
                                style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.15)", color: "#f87171", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                Confirm Delete
                              </button>
                              <button onClick={e => { e.stopPropagation(); setDeleteConfirm(null); }}
                                style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button onClick={e => { e.stopPropagation(); setDeleteConfirm(c.id); }}
                              style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.2)", background: "transparent", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", opacity: 0.7 }}>
                              Delete Carrier
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            );
          })}
          {filteredDir.length > 100 && <div style={{ padding: 12, textAlign: "center", color: "#5A6478", fontSize: 11 }}>Showing 100 of {filteredDir.length} carriers. Refine your search.</div>}
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // HISTORY VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "history") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate History</h2>
        </div>
        <HistoryTabContent rateHistory={rateHistory} historyLoading={historyLoading}
          onLoad={async () => {
            if (rateHistory.length > 0) return;
            setHistoryLoading(true);
            try {
              const res = await apiFetch(`${API_BASE}/api/rate-history?limit=200`);
              const data = await res.json();
              setRateHistory(data.history || []);
            } catch (e) { console.error("Rate history fetch:", e); }
            setHistoryLoading(false);
          }} />
      </div>
    );
  }

  return null;
}
