import { useState, useMemo } from 'react';
import { useAppStore } from '../store';
import { apiFetch, API_BASE } from '../helpers/api';
import { STATUSES, STATUS_COLORS, REP_ACCOUNTS, ALL_REP_NAMES } from '../helpers/constants';
import { isDateToday, isDateTomorrow, isDateYesterday, isDatePast, isDateFuture, getRepShipments, useIsMobile } from '../helpers/utils';
import MyActions from '../components/MyActions';

// ─── Rep avatar colors (spec: RA=cyan, JF=blue, JA=purple, BO=green, TO=amber) ───
const OVERVIEW_REP_COLORS = {
  Radka: "#06b6d4",
  "John F": "#3B82F6",
  Janice: "#A855F7",
  Boviet: "#22C55E",
  Tolead: "#F59E0B",
};

export default function OverviewView({ loaded, shipments, apiStats, accountOverview, apiError, onSelectRep, onNavigateDispatch, onFilterStatus, onFilterDate, onFilterAccount, unbilledStats, onNavigateUnbilled, onAddLoad, onNavigateBilling, repProfiles, repScoreboard, accountHealth, trackingSummary, docSummary, handleLoadClick, alerts, onDismissAlert, onDismissAll, onNavigateInbox, onFilterRepDispatch }) {
  const [acctSortMode, setAcctSortMode] = useState("loads");
  const { currentUser } = useAppStore();

  // Operational stat card counts
  const isNonTerminal = (s) => !["delivered", "empty_return"].includes(s.status);
  const activeCount = shipments.filter(isNonTerminal).length;
  const pickingUpCount = shipments.filter(s => isNonTerminal(s) && (isDateToday(s.pickupDate) || isDateTomorrow(s.pickupDate))).length;
  const deliveringCount = shipments.filter(s => isDateToday(s.deliveryDate) && s.status !== "empty_return").length;
  const inTransitCount = shipments.filter(s => isNonTerminal(s) && s.pickupDate && !s.deliveryDate && !isDateToday(s.pickupDate) && !isDateTomorrow(s.pickupDate)).length;
  const upcomingCount = shipments.filter(s => {
    if (!isNonTerminal(s)) return false;
    if (s.moveType === "FTL") return s.pickupDate && isDateFuture(s.pickupDate);
    return s.eta && !isDatePast(s.eta);
  }).length;
  const yesterdayCount = shipments.filter(s => isDateYesterday(s.pickupDate) || isDateYesterday(s.deliveryDate)).length;

  // Team data — use spec avatar colors
  const repData = ALL_REP_NAMES.map(name => {
    const repShips = getRepShipments(shipments, name);
    const unbilled = (unbilledStats?.by_rep || []).find(r => r.rep === name)?.cnt || 0;
    return {
      name, color: OVERVIEW_REP_COLORS[name] || "#94a3b8",
      total: repShips.length, unbilled,
    };
  });

  // Helper to extract solid color from indicator (which may be a gradient string)
  const getGlowColor = (indicator) => {
    if (indicator.startsWith("linear-gradient")) return "#00D4AA";
    return indicator;
  };

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none", width: "100%" }}>
      {/* Title + gradient bar */}
      <div style={{ padding: "16px 0 6px", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.03em", margin: 0, lineHeight: 1.2 }}>
            <span style={{ background: "linear-gradient(135deg, #F0F2F5, #C8CDD5)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>LOADBOARD </span>
            <span style={{ background: "linear-gradient(135deg, #00c853, #00b8d4, #2979ff)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>OVERVIEW</span>
          </h1>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2, letterSpacing: "0.01em" }}>Real-time logistics across all sheets</div>
        </div>
        <button onClick={onAddLoad} className="btn-primary" style={{ border: "none", borderRadius: 10, padding: "9px 20px", fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#fff", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Load
        </button>
      </div>

      {/* Gradient accent bar — full opacity, thicker */}
      <div style={{ height: 3, borderRadius: 100, background: "linear-gradient(90deg, #00c853, #00b8d4, #2979ff)", marginBottom: 16 }} />

      {/* Operational Stats Row — clickable stat cards with color-coded values */}
      <div className="dash-stat-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {[
          { label: "Active", value: activeCount, color: "#F0F2F5", indicator: "linear-gradient(135deg, #00c853, #00b8d4, #2979ff)", glowColor: "#00D4AA", action: () => onFilterStatus("all"), emphasis: true },
          { label: "Picking Up", value: pickingUpCount, color: "#3B82F6", indicator: "#3B82F6", glowColor: "#3B82F6", action: () => onFilterDate("pickup_today") },
          { label: "Delivering", value: deliveringCount, color: "#22C55E", indicator: "#22C55E", glowColor: "#22C55E", action: () => onFilterDate("delivery_today") },
          { label: "In Transit", value: inTransitCount, color: "#60A5FA", indicator: "#60A5FA", glowColor: "#60A5FA", action: () => onFilterStatus("in_transit") },
          { label: "Upcoming", value: upcomingCount, color: "#F59E0B", indicator: "#F59E0B", glowColor: "#F59E0B", action: () => onFilterDate("upcoming") },
          { label: "Yesterday", value: yesterdayCount, color: "#A78BFA", indicator: "#A78BFA", glowColor: "#A78BFA", action: () => onFilterDate("yesterday") },
          { label: "Unbilled", value: unbilledStats?.count || 0, color: "#F97316", indicator: "#F97316", glowColor: "#F97316", action: onNavigateUnbilled, emphasis: true, pulse: true },
        ].map((s, i) => {
          const isUnbilledPulsing = s.pulse && s.value > 0;
          return (
          <div key={i} onClick={s.action}
            style={{
              flex: s.emphasis ? 1.4 : 1, minWidth: s.emphasis ? 100 : 0,
              background: isUnbilledPulsing ? "rgba(249,115,22,0.08)" : "#111827",
              border: `1px solid ${isUnbilledPulsing ? "rgba(249,115,22,0.5)" : "rgba(255,255,255,0.08)"}`,
              borderRadius: 14, padding: "16px 16px", cursor: "pointer", position: "relative", overflow: "hidden",
              boxShadow: isUnbilledPulsing
                ? "0 0 20px rgba(249,115,22,0.15), 0 4px 12px rgba(0,0,0,0.3)"
                : "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)",
              transition: "all 0.25s ease",
              animation: isUnbilledPulsing ? "unbilled-pulse 2.5s ease infinite" : "none",
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.8)" : `${s.glowColor}44`;
              e.currentTarget.style.boxShadow = `0 0 24px ${s.glowColor}22, 0 8px 32px rgba(0,0,0,0.3)`;
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.5)" : "rgba(255,255,255,0.08)";
              e.currentTarget.style.boxShadow = isUnbilledPulsing
                ? "0 0 20px rgba(249,115,22,0.15), 0 4px 12px rgba(0,0,0,0.3)"
                : "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)";
              e.currentTarget.style.transform = "translateY(0)";
            }}>
            {/* Colored top accent — thicker */}
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: s.emphasis ? 3 : 3, background: s.indicator, borderRadius: "0 0 2px 2px" }} />
            {/* Value in accent color */}
            <div className="stat-value" style={{ fontSize: s.emphasis ? 34 : 26, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1, color: s.color, marginBottom: 2 }}>{s.value}</div>
            <div className="stat-label" style={{ fontSize: 10, fontWeight: 700, color: "#6B7A90", textTransform: "uppercase", letterSpacing: "0.08em" }}>{s.label}</div>
          </div>
          );
        })}
      </div>

      {/* Row 1: Rep Overview + Accounts */}
      <div className="dash-grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 14, animation: loaded ? "slide-up 0.4s ease 0.1s both" : "none" }}>
        {/* Rep Overview — loads + revenue with gradient left border */}
        <div className="dash-panel" style={{ padding: 16, borderLeft: "3px solid transparent", borderImage: "linear-gradient(180deg, #00c853, #00b8d4, #2979ff) 1" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              Rep Overview
              {repScoreboard.length > 0 && (
                <span style={{ fontSize: 8, color: "#00D4AA", fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "rgba(0,212,170,0.12)", letterSpacing: "0.08em", animation: "pulse-glow 2s ease infinite" }}>LIVE</span>
              )}
            </div>
          </div>
          {/* Column headers */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(120px, 1fr) 56px 68px", gap: 4, marginBottom: 6, padding: "0 10px", alignItems: "center" }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Rep</div>
            <div style={{ fontSize: 9, color: "#00b8d4", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active loads (not archived)">Loads</div>
            <div style={{ fontSize: 9, color: "#00b8d4", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active revenue (all priced loads)">Rev</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {repData.map(r => {
              const score = (repScoreboard || []).find(s => s.rep === r.name) || {};
              const loads7d = score.loads_7d || 0;
              const revenue7d = score.revenue_7d || 0;
              const revenueLoads = score.margin_loads || 0;

              const formatRev = (val) => {
                if (!val || val === 0) return "\u2014";
                if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`;
                return `$${Math.round(val)}`;
              };

              const loadsColor = loads7d >= 5 ? "#F0F2F5" : loads7d > 0 ? "#8B95A8" : "#3D4557";
              // Revenue in green when positive
              const revColor = revenue7d > 0 ? "#00D4AA" : "#3D4557";

              return (
                <div key={r.name} className="rep-card"
                  onClick={() => onSelectRep(r.name)}
                  style={{ display: "grid", gridTemplateColumns: "minmax(120px, 1fr) 56px 68px", gap: 4, alignItems: "center", padding: "7px 10px", borderRadius: 10,
                    background: "rgba(255,255,255,0.02)",
                    border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer",
                    transition: "border-color 0.15s" }}>
                  {/* Rep identity */}
                  <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
                    {repProfiles[r.name]?.avatar_url ? (
                      <img src={`${API_BASE}${repProfiles[r.name].avatar_url}`} alt={r.name}
                        style={{ width: 28, height: 28, borderRadius: "50%", objectFit: "cover", flexShrink: 0, border: `2px solid ${r.color}66`, boxShadow: `0 0 8px ${r.color}33` }} />
                    ) : (
                      <div style={{ width: 28, height: 28, borderRadius: "50%", background: `linear-gradient(135deg, ${r.color}44, ${r.color}99)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700, color: "#fff", flexShrink: 0, border: `2px solid ${r.color}55`, boxShadow: `0 0 10px ${r.color}22` }}>
                        {r.name.slice(0, 2).toUpperCase()}
                      </div>
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "#F0F2F5" }}>{r.name}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>{r.total}</span>
                      </div>
                    </div>
                  </div>

                  {/* LOADS */}
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 15, fontWeight: 800, color: loadsColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {loads7d}
                    </div>
                  </div>

                  {/* REVENUE — green when positive */}
                  <div style={{ textAlign: "center" }} title={revenueLoads > 0 ? `$${Math.round(score.total_margin || 0).toLocaleString()} margin from ${revenueLoads} priced loads` : "No priced loads"}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: revColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {formatRev(revenue7d)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Accounts — load totals + revenue per customer */}
        {(() => {
          const sortedAccounts = [...(accountHealth || [])].sort((a, b) => {
            if (acctSortMode === "revenue") return (b.revenue || 0) - (a.revenue || 0);
            return (b.active_loads || 0) - (a.active_loads || 0);
          });
          const sortLabels = { loads: "Loads", revenue: "Revenue" };
          const nextSort = { loads: "revenue", revenue: "loads" };

          const formatRev = (val) => {
            if (!val || val === 0) return "\u2014";
            if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
            if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`;
            return `$${Math.round(val)}`;
          };

          // Fallback to old Account Overview if no account health data
          if (!accountHealth || accountHealth.length === 0) {
            return (
              <div className="dash-panel" style={{ padding: 16 }}>
                <div className="dash-panel-title" style={{ marginBottom: 10 }}>Accounts</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {accountOverview.slice(0, 10).map((acct, i) => {
                  const maxLoads = accountOverview.length > 0 ? accountOverview[0].loads : 1;
                  const pct = maxLoads > 0 ? (acct.loads / maxLoads) * 100 : 0;
                  return (
                    <div key={i} onClick={() => onFilterAccount && onFilterAccount(acct.name)}
                      style={{ display: "grid", gridTemplateColumns: "24px 1fr 40px", gap: 10, alignItems: "center", padding: "6px 10px", borderRadius: 8, transition: "background 0.15s ease", cursor: "pointer" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div style={{ width: 24, height: 24, borderRadius: 6, background: `linear-gradient(135deg, ${acct.color}33, ${acct.color}66)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{acct.name[0]}</div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, color: "#F0F2F5", fontWeight: 600, marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{acct.name}</div>
                        <div style={{ height: 3, borderRadius: 100, background: "rgba(255,255,255,0.04)", overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${pct}%`, borderRadius: 100, background: `linear-gradient(90deg, ${acct.color}, ${acct.color}88)`, transition: "width 0.8s ease" }} />
                        </div>
                      </div>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 13, textAlign: "right" }}>{acct.loads}</span>
                    </div>
                  );
                })}
                </div>
              </div>
            );
          }

          return (
            <div className="dash-panel" style={{ padding: 16, borderLeft: "3px solid transparent", borderImage: "linear-gradient(180deg, #2979ff, #00b8d4, #00c853) 1" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  Accounts
                  <span style={{ fontSize: 8, color: "#00D4AA", fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "rgba(0,212,170,0.12)", letterSpacing: "0.08em", animation: "pulse-glow 2s ease infinite" }}>LIVE</span>
                </div>
                <span onClick={() => setAcctSortMode(nextSort[acctSortMode])}
                  style={{ fontSize: 9, color: "#5A6478", cursor: "pointer", fontWeight: 600, padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", transition: "all 0.15s", userSelect: "none" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "#8B95A8"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#5A6478"; }}
                  title={`Sort by ${nextSort[acctSortMode]}`}>
                  {sortLabels[acctSortMode]} ▼
                </span>
              </div>
              {/* Column headers */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 56px", gap: 4, marginBottom: 4, padding: "0 10px", alignItems: "center" }}>
                <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>Account</div>
                <div style={{ fontSize: 9, color: "#00b8d4", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active loads">Loads</div>
                <div style={{ fontSize: 9, color: "#00b8d4", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Revenue">Rev</div>
              </div>
              {/* Account rows */}
              <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 340, overflowY: "auto", scrollbarGutter: "stable" }}>
                {sortedAccounts.map(a => (
                  <div key={a.account}
                    onClick={() => onFilterAccount && onFilterAccount(a.account)}
                    style={{ display: "grid", gridTemplateColumns: "1fr 44px 56px", gap: 4, alignItems: "center", padding: "6px 10px", borderRadius: 8,
                      background: "transparent", border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer", transition: "all 0.15s" }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = "rgba(0,212,170,0.2)"; e.currentTarget.style.background = "rgba(0,212,170,0.03)"; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; e.currentTarget.style.background = "transparent"; }}>
                    {/* Account + Rep */}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.account}</div>
                      {a.rep && <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 500, marginTop: 0 }}>{a.rep}</div>}
                    </div>
                    {/* Loads */}
                    <div style={{ textAlign: "center" }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: a.active_loads > 0 ? "#F0F2F5" : "#3D4557", fontFamily: "'JetBrains Mono', monospace" }}>{a.active_loads}</span>
                    </div>
                    {/* Revenue — green when positive */}
                    <div style={{ textAlign: "center" }} title={`$${Math.round(a.revenue || 0).toLocaleString()} revenue`}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: a.revenue > 0 ? "#00D4AA" : "#3D4557", fontFamily: "'JetBrains Mono', monospace" }}>{formatRev(a.revenue)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
      </div>

      {/* Row 2: My Actions — full width */}
      <MyActions
        shipments={shipments}
        trackingSummary={trackingSummary}
        alerts={alerts}
        currentUser={currentUser}
        repProfiles={repProfiles}
        onFilterDate={onFilterDate}
        onFilterStatus={onFilterStatus}
        onFilterAccount={onFilterAccount}
        handleLoadClick={handleLoadClick}
        onDismissAlert={onDismissAlert}
      />
    </div>
  );
}
