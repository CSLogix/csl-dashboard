import { useState, useEffect, useMemo } from 'react';
import { useAppStore } from '../store';
import { apiFetch, API_BASE } from '../helpers/api';
import { STATUSES, FTL_STATUSES, STATUS_COLORS, FTL_STATUS_COLORS, BILLING_STATUS_COLORS, BILLING_STATUSES, ACCOUNT_COLORS, ALERT_TYPES, REP_ACCOUNTS, REP_COLORS, ALL_REP_NAMES, MASTER_REPS, ALERT_TYPE_CONFIG, Z, NAV_ITEMS, DOC_TYPE_LABELS } from '../helpers/constants';
import { isFTLShipment, resolveStatusLabel, resolveStatusColor, resolveRepForShipment, isDateToday, isDateTomorrow, isDateYesterday, isDatePast, isDateFuture, getRepShipments, timeAgo, calcMarginPct, getBillingReadiness, useIsMobile } from '../helpers/utils';

export default function OverviewView({ loaded, shipments, apiStats, accountOverview, apiError, onSelectRep, onNavigateDispatch, onFilterStatus, onFilterDate, onFilterAccount, unbilledStats, onNavigateUnbilled, onAddLoad, onNavigateBilling, repProfiles, repScoreboard, accountHealth, trackingSummary, docSummary, handleLoadClick, alerts, onDismissAlert, onDismissAll, onNavigateInbox, onFilterRepDispatch }) {
  const [alertFilter, setAlertFilter] = useState("all");
  const [acctSortMode, setAcctSortMode] = useState("health"); // health | revenue | friction

  // Status pipeline data
  const statusGroups = {};
  STATUSES.filter(s => s.key !== "all").forEach(s => {
    statusGroups[s.key] = shipments.filter(sh => sh.status === s.key).length;
  });
  const total = shipments.length || 1;

  // Today's action items
  const pickupsToday = shipments.filter(s => isDateToday(s.pickupDate) && s.status !== "delivered");
  const pickupsTomorrow = shipments.filter(s => isDateTomorrow(s.pickupDate) && s.status !== "delivered");
  const deliveriesToday = shipments.filter(s => isDateToday(s.deliveryDate));
  const deliveriesTomorrow = shipments.filter(s => isDateTomorrow(s.deliveryDate) && s.status !== "delivered");

  // Tracking Behind — FTL loads behind on Macropoint
  const trackingBehind = shipments.filter(s => {
    const efjBare = s.efj?.replace(/^EFJ\s*/i, "");
    const t = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
    return t && (t.behindSchedule || t.cantMakeIt);
  });

  // Loads to Cover — unassigned status (Boviet, Tolead, etc.)
  const loadsToCover = shipments.filter(s =>
    s.rawStatus?.toLowerCase() === "unassigned" && !["delivered", "empty_return"].includes(s.status)
  );

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

  // Team data
  const repData = ALL_REP_NAMES.map(name => {
    const repShips = getRepShipments(shipments, name);
    const incoming = repShips.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length;
    const active = repShips.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length;
    const behindSchedule = repShips.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status)).length;
    const delivered = repShips.filter(s => s.status === "delivered").length;
    const invoiced = repShips.filter(s => s._invoiced).length;
    const onSchedule = repShips.filter(s =>
      !["delivered", "empty_return"].includes(s.status) &&
      !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))
    ).length;
    const unbilled = (unbilledStats?.by_rep || []).find(r => r.rep === name)?.cnt || 0;
    return {
      name, color: REP_COLORS[name] || "#94a3b8",
      total: repShips.length, incoming, active, onSchedule, behindSchedule, delivered, invoiced, unbilled,
    };
  });

  // Alert filtering by rep
  const alertReps = [...new Set((alerts || []).map(a => a.rep).filter(Boolean))];
  const filteredAlerts = alertFilter === "all" ? (alerts || []) : (alerts || []).filter(a => a.rep === alertFilter);
  const alertTabs = [
    { id: "all", label: "All", count: (alerts || []).length },
    ...alertReps.map(name => ({
      id: name, label: name, count: (alerts || []).filter(a => a.rep === name).length, color: REP_COLORS[name] || "#94a3b8",
    })),
  ];


  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none", width: "100%" }}>
      {/* Title */}
      <div style={{ padding: "16px 0 10px", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em", margin: 0, lineHeight: 1.2 }}>
            <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>LOADBOARD </span>
            <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>OVERVIEW</span>
          </h1>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2, letterSpacing: "0.01em" }}>Real-time logistics across all sheets</div>
        </div>
        <button onClick={onAddLoad} className="btn-primary" style={{ border: "none", borderRadius: 10, padding: "9px 20px", fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#fff", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Load
        </button>
      </div>

      {/* Status Pipeline Bar */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: "flex", height: 6, borderRadius: 100, gap: 2, background: "rgba(255,255,255,0.04)" }}>
          {STATUSES.filter(s => s.key !== "all").map(s => {
            const count = statusGroups[s.key] || 0;
            if (count === 0) return null;
            return (
              <div key={s.key} title={`${s.label}: ${count}`}
                style={{ width: `${(count / total) * 100}%`, background: STATUS_COLORS[s.key]?.main, cursor: "pointer", transition: "all 0.5s ease", borderRadius: 100 }}
                onMouseEnter={e => e.currentTarget.style.filter = "brightness(1.2)"}
                onMouseLeave={e => e.currentTarget.style.filter = "none"}
                onClick={() => onFilterStatus(s.key)} />
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
          {STATUSES.filter(s => s.key !== "all").map(s => {
            const count = statusGroups[s.key] || 0;
            if (count === 0) return null;
            return (
              <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }} onClick={() => onFilterStatus(s.key)}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_COLORS[s.key]?.main }} />
                <span style={{ fontSize: 10, color: "#8B95A8", fontWeight: 500 }}>{s.label}</span>
                <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{count}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Operational Stats Row — clickable stat cards */}
      <div className="dash-stat-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {[
          { label: "Active", value: activeCount, color: "#F0F2F5", indicator: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", action: () => onFilterStatus("all"), emphasis: true },
          { label: "Picking Up", value: pickingUpCount, color: "#3B82F6", indicator: "#3B82F6", action: () => onFilterDate("pickup_today") },
          { label: "Delivering", value: deliveringCount, color: "#22C55E", indicator: "#22C55E", action: () => onFilterDate("delivery_today") },
          { label: "In Transit", value: inTransitCount, color: "#60A5FA", indicator: "#60A5FA", action: () => onFilterStatus("in_transit") },
          { label: "Upcoming", value: upcomingCount, color: "#F59E0B", indicator: "#F59E0B", action: () => onFilterDate("upcoming") },
          { label: "Yesterday", value: yesterdayCount, color: "#A78BFA", indicator: "#A78BFA", action: () => onFilterDate("yesterday") },
          { label: "Unbilled", value: unbilledStats?.count || 0, color: "#F97316", indicator: "#F97316", action: onNavigateUnbilled, emphasis: true, pulse: true },
        ].map((s, i) => {
          const isUnbilledPulsing = s.pulse && s.value > 0;
          return (
          <div key={i} onClick={s.action}
            style={{ flex: s.emphasis ? 1.4 : 1, minWidth: s.emphasis ? 100 : 0, background: isUnbilledPulsing ? "rgba(249,115,22,0.06)" : "#141A28", border: `1px solid ${isUnbilledPulsing ? "rgba(249,115,22,0.4)" : "rgba(255,255,255,0.10)"}`, borderRadius: 14, padding: "16px 16px", cursor: "pointer", position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)", transition: "border-color 0.2s, box-shadow 0.2s", animation: isUnbilledPulsing ? "unbilled-pulse 2.5s ease infinite" : "none" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.7)" : "rgba(255,255,255,0.16)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.4), 0 8px 32px rgba(0,0,0,0.2)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.4)" : "rgba(255,255,255,0.10)"; e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)"; }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: s.emphasis ? 3 : 2, background: s.indicator, borderRadius: "0 0 2px 2px" }} />
            <div className="stat-value" style={{ fontSize: s.emphasis ? 32 : 24, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1, color: s.color, marginBottom: 2 }}>{s.value}</div>
            <div className="stat-label" style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
          </div>
          );
        })}
      </div>

      {/* Row 1: Rep Scoreboard + Account Health */}
      <div className="dash-grid-2" style={{ display: "grid", gridTemplateColumns: "6fr 4fr", gap: 24, marginBottom: 14, animation: loaded ? "slide-up 0.4s ease 0.1s both" : "none" }}>
        {/* Rep Scoreboard v2 — Offense + Defense */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              Rep Scoreboard
              {repScoreboard.length > 0 && (
                <span style={{ fontSize: 8, color: "#22C55E", fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "rgba(34,197,94,0.1)", letterSpacing: "0.08em" }}>LIVE</span>
              )}
            </div>
          </div>
          {/* Column headers — Offense | Defense divider */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(120px, 1fr) 56px 68px 1px 64px 52px 52px", gap: 4, marginBottom: 6, padding: "0 10px", alignItems: "center" }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Rep</div>
            <div style={{ fontSize: 9, color: "#3B82F6", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active loads (not archived)">Loads</div>
            <div style={{ fontSize: 9, color: "#3B82F6", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active revenue (all priced loads)">Rev</div>
            <div style={{ background: "rgba(255,255,255,0.06)", width: 1, height: 16, justifySelf: "center" }} />
            <div style={{ fontSize: 9, color: "#F59E0B", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Unreplied threads + avg response speed">Comms</div>
            <div style={{ fontSize: 9, color: "#F59E0B", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Delivered loads missing POD or carrier invoice">Docs</div>
            <div style={{ fontSize: 9, color: "#F59E0B", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Loads with no update > 24h">Stale</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {repData.map(r => {
              const score = (repScoreboard || []).find(s => s.rep === r.name) || {};
              const loads7d = score.loads_7d || 0;
              const revenue7d = score.revenue_7d || 0;
              const revenueLoads = score.margin_loads || 0;
              const unreplied = score.unreplied_threads || 0;
              const avgResp = score.avg_response_min;
              const docsNeeded = score.docs_needed || 0;
              const neglected = score.neglected_loads || 0;
              const worstAcct = score.worst_account;

              // COMMS composite: green if unreplied=0 AND speed<30m, yellow if either moderate, red if either bad
              const commsLevel = unreplied >= 5 || (avgResp != null && avgResp > 120) ? "red"
                : unreplied >= 3 || (avgResp != null && avgResp > 60) ? "yellow"
                : (unreplied === 0 && (avgResp == null || avgResp <= 30)) ? "green" : "neutral";
              const commsColor = { red: "#EF4444", yellow: "#F59E0B", green: "#22C55E", neutral: "#8B95A8" }[commsLevel];
              const commsBg = { red: "rgba(239,68,68,0.08)", yellow: "rgba(245,158,11,0.08)", green: "rgba(34,197,94,0.06)", neutral: "transparent" }[commsLevel];

              const formatSpeed = (min) => {
                if (min == null) return "";
                if (min < 60) return `${Math.round(min)}m`;
                return `${(min / 60).toFixed(1)}h`;
              };
              const formatRev = (val) => {
                if (!val || val === 0) return "--";
                if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`;
                return `$${Math.round(val)}`;
              };

              const docsColor = docsNeeded >= 5 ? "#EF4444" : docsNeeded >= 2 ? "#F59E0B" : docsNeeded > 0 ? "#F0F2F5" : "#3D4557";
              const neglectedColor = neglected >= 3 ? "#EF4444" : neglected > 0 ? "#F59E0B" : "#3D4557";
              const loadsColor = loads7d >= 5 ? "#F0F2F5" : loads7d > 0 ? "#8B95A8" : "#3D4557";
              const revColor = revenue7d > 0 ? "#F0F2F5" : "#3D4557";

              const onFire = unreplied >= 5 || neglected >= 3 || docsNeeded >= 5;

              return (
                <div key={r.name} className="rep-card"
                  onClick={() => onSelectRep(r.name)}
                  style={{ display: "grid", gridTemplateColumns: "minmax(120px, 1fr) 56px 68px 1px 64px 52px 52px", gap: 4, alignItems: "center", padding: "7px 10px", borderRadius: 10,
                    background: onFire ? "rgba(239,68,68,0.04)" : "rgba(255,255,255,0.02)",
                    border: `1px solid ${onFire ? "rgba(239,68,68,0.15)" : "rgba(255,255,255,0.06)"}`, cursor: "pointer",
                    transition: "border-color 0.15s" }}>
                  {/* Rep identity */}
                  <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
                    {repProfiles[r.name]?.avatar_url ? (
                      <img src={`${API_BASE}${repProfiles[r.name].avatar_url}`} alt={r.name}
                        style={{ width: 26, height: 26, borderRadius: "50%", objectFit: "cover", flexShrink: 0, border: `2px solid ${r.color}55` }} />
                    ) : (
                      <div style={{ width: 26, height: 26, borderRadius: "50%", background: `linear-gradient(135deg, ${r.color}33, ${r.color}66)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>
                        {r.name.slice(0, 2).toUpperCase()}
                      </div>
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "#F0F2F5" }}>{r.name}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>{r.total}</span>
                      </div>
                      {worstAcct && unreplied > 0 && (
                        <div style={{ fontSize: 8, color: "#5A6478", marginTop: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {worstAcct.account}: {worstAcct.count} waiting
                        </div>
                      )}
                    </div>
                  </div>

                  {/* LOADS (offense) */}
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 14, fontWeight: 800, color: loadsColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {loads7d}
                    </div>
                  </div>

                  {/* REVENUE (offense) */}
                  <div style={{ textAlign: "center" }} title={revenueLoads > 0 ? `$${Math.round(score.total_margin || 0).toLocaleString()} margin from ${revenueLoads} priced loads` : "No priced loads"}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: revColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {formatRev(revenue7d)}
                    </div>
                  </div>

                  {/* Divider */}
                  <div style={{ background: "rgba(255,255,255,0.06)", width: 1, height: 28, justifySelf: "center" }} />

                  {/* COMMS (defense — merged unreplied + speed) */}
                  <div style={{ textAlign: "center", cursor: unreplied > 0 ? "pointer" : "default", borderRadius: 6, padding: "3px 2px", background: commsBg, transition: "background 0.15s" }}
                    onClick={(e) => { if (unreplied > 0 && onNavigateInbox) { e.stopPropagation(); onNavigateInbox("needs_reply", null, r.name); } else if (unreplied > 0) { e.stopPropagation(); onSelectRep(r.name); } }}
                    onMouseEnter={e => { if (unreplied > 0) e.currentTarget.style.background = "rgba(255,255,255,0.08)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = commsBg; }}
                    title={`${unreplied} unreplied${avgResp != null ? ` | avg ${formatSpeed(avgResp)}` : ""}`}>
                    <div style={{ fontSize: 13, fontWeight: 800, color: commsColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>
                      {unreplied > 0 ? unreplied : commsLevel === "green" ? "\u2713" : "--"}
                    </div>
                    {avgResp != null && (
                      <div style={{ fontSize: 8, color: commsColor, opacity: 0.7, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", marginTop: 1 }}>
                        {formatSpeed(avgResp)}
                      </div>
                    )}
                  </div>

                  {/* DOCS (defense) */}
                  <div style={{ textAlign: "center", cursor: docsNeeded > 0 ? "pointer" : "default", borderRadius: 6, padding: "2px 0" }}
                    onClick={(e) => { if (docsNeeded > 0) { e.stopPropagation(); onSelectRep(r.name); } }}
                    onMouseEnter={e => { if (docsNeeded > 0) e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
                    title={docsNeeded > 0 ? `${docsNeeded} delivered loads missing POD or carrier invoice` : "All docs received"}>
                    <div style={{ fontSize: 14, fontWeight: 800, color: docsColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {docsNeeded}
                    </div>
                  </div>

                  {/* STALE (defense) */}
                  <div style={{ textAlign: "center", cursor: neglected > 0 ? "pointer" : "default", borderRadius: 6, padding: "2px 0" }}
                    onClick={(e) => { if (neglected > 0 && onFilterRepDispatch) { e.stopPropagation(); onFilterRepDispatch(r.name); } else if (neglected > 0) { e.stopPropagation(); onSelectRep(r.name); } }}
                    onMouseEnter={e => { if (neglected > 0) e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
                    title={neglected > 0 ? `${neglected} loads with no update in 24h` : "All loads current"}>
                    <div style={{ fontSize: 14, fontWeight: 800, color: neglectedColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.2 }}>
                      {neglected}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Account Health View — margin-to-friction ratio per customer */}
        {(() => {
          const sortedAccounts = [...(accountHealth || [])].sort((a, b) => {
            if (acctSortMode === "revenue") return (b.revenue || 0) - (a.revenue || 0);
            if (acctSortMode === "friction") return (b.friction_score || 0) - (a.friction_score || 0);
            return (b.health_score || 0) - (a.health_score || 0);
          });
          const sortLabels = { health: "Health", revenue: "Revenue", friction: "Friction" };
          const nextSort = { health: "revenue", revenue: "friction", friction: "health" };

          const formatRev = (val) => {
            if (!val || val === 0) return "--";
            if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
            if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`;
            return `$${Math.round(val)}`;
          };

          const mgnColor = (pct) => pct >= 15 ? "#22C55E" : pct >= 8 ? "#F59E0B" : pct > 0 ? "#EF4444" : "#3D4557";
          const fricColor = (f) => f >= 5 ? "#EF4444" : f > 0 ? "#F59E0B" : "#3D4557";
          const hsBg = (hs) => hs >= 10 ? "rgba(34,197,94,0.06)" : hs < 0 ? "rgba(239,68,68,0.06)" : "transparent";
          const hsColor = (hs) => hs >= 10 ? "#22C55E" : hs >= 0 ? "#8B95A8" : "#EF4444";
          const hsBorder = (hs) => hs >= 10 ? "rgba(34,197,94,0.15)" : hs < 0 ? "rgba(239,68,68,0.15)" : "rgba(255,255,255,0.06)";

          // Fallback to old Account Overview if no account health data
          if (!accountHealth || accountHealth.length === 0) {
            return (
              <div className="dash-panel" style={{ padding: 16 }}>
                <div className="dash-panel-title" style={{ marginBottom: 10 }}>Account Overview</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {accountOverview.slice(0, 10).map((acct, i) => {
                  const maxLoads = accountOverview.length > 0 ? accountOverview[0].loads : 1;
                  const pct = maxLoads > 0 ? (acct.loads / maxLoads) * 100 : 0;
                  return (
                    <div key={i} onClick={() => onFilterAccount && onFilterAccount(acct.name)}
                      style={{ display: "grid", gridTemplateColumns: "24px 1fr 40px 36px", gap: 10, alignItems: "center", padding: "6px 10px", borderRadius: 8, transition: "background 0.15s ease", cursor: "pointer" }}
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
                      <span style={{ minWidth: 36, textAlign: "center" }}>{acct.alerts > 0 ? <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 6, background: "#EF444418", color: "#F87171", fontWeight: 700, border: "1px solid #EF444422", fontFamily: "'JetBrains Mono', monospace" }}>{acct.alerts}</span> : null}</span>
                    </div>
                  );
                })}
                </div>
              </div>
            );
          }

          return (
            <div className="dash-panel" style={{ padding: 16 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  Account Health
                  <span style={{ fontSize: 8, color: "#22C55E", fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "rgba(34,197,94,0.1)", letterSpacing: "0.08em" }}>LIVE</span>
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
              <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 52px 42px 48px", gap: 4, marginBottom: 4, padding: "0 10px", alignItems: "center" }}>
                <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>Account</div>
                <div style={{ fontSize: 9, color: "#3B82F6", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Active loads">Lds</div>
                <div style={{ fontSize: 9, color: "#3B82F6", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Revenue">Rev</div>
                <div style={{ fontSize: 9, color: "#F59E0B", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Friction score (unreplied×2 + docs×1.5 + neglected×1)">Fric</div>
                <div style={{ fontSize: 9, color: "#10B981", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }} title="Health score (loads − friction)">HS</div>
              </div>
              {/* Account rows */}
              <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 340, overflowY: "auto", scrollbarGutter: "stable" }}>
                {sortedAccounts.map(a => (
                  <div key={a.account}
                    onClick={() => onFilterAccount && onFilterAccount(a.account)}
                    style={{ display: "grid", gridTemplateColumns: "1fr 44px 52px 42px 48px", gap: 4, alignItems: "center", padding: "6px 10px", borderRadius: 8,
                      background: hsBg(a.health_score), border: `1px solid ${hsBorder(a.health_score)}`, cursor: "pointer", transition: "border-color 0.15s" }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.15)"; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = hsBorder(a.health_score); }}>
                    {/* Account + Rep */}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.account}</div>
                      {a.rep && <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 500, marginTop: 0 }}>{a.rep}</div>}
                    </div>
                    {/* Loads */}
                    <div style={{ textAlign: "center" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: a.active_loads > 0 ? "#8B95A8" : "#3D4557", fontFamily: "'JetBrains Mono', monospace" }}>{a.active_loads}</span>
                    </div>
                    {/* Revenue */}
                    <div style={{ textAlign: "center" }} title={`$${Math.round(a.revenue || 0).toLocaleString()} revenue`}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: a.revenue > 0 ? "#8B95A8" : "#3D4557", fontFamily: "'JetBrains Mono', monospace" }}>{formatRev(a.revenue)}</span>
                    </div>
                    {/* Friction */}
                    <div style={{ textAlign: "center", cursor: a.friction_score > 0 ? "pointer" : "default", borderRadius: 6, padding: "2px 0" }}
                      title={a.friction_score > 0 ? `${a.unreplied_threads} unreplied × 2 + ${a.docs_needed} docs × 1.5 + ${a.neglected_loads} neglected × 1` : "No friction"}>
                      <span style={{ fontSize: 12, fontWeight: 800, color: fricColor(a.friction_score), fontFamily: "'JetBrains Mono', monospace" }}>
                        {a.friction_score > 0 ? a.friction_score : "0"}
                      </span>
                    </div>
                    {/* Health Score */}
                    <div style={{ textAlign: "center", borderRadius: 6, padding: "2px 4px", background: a.health_score >= 10 ? "rgba(34,197,94,0.12)" : a.health_score < 0 ? "rgba(239,68,68,0.12)" : "rgba(255,255,255,0.03)" }}>
                      <span style={{ fontSize: 12, fontWeight: 800, color: hsColor(a.health_score), fontFamily: "'JetBrains Mono', monospace" }}>
                        {a.health_score > 0 ? "+" : ""}{a.health_score}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
      </div>

      {/* Row 2: Today's Actions + Live Alerts */}
      <div className="dash-grid-2" style={{ display: "grid", gridTemplateColumns: "6fr 4fr", gap: 24, animation: loaded ? "slide-up 0.4s ease 0.2s both" : "none" }}>
        {/* Today's Action Items */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14 }}>📋</span> Today's Actions
            </div>
            <span style={{ fontSize: 11, color: "#00D4AA", cursor: "pointer", fontWeight: 600 }} onClick={onNavigateDispatch}>View all →</span>
          </div>
          {[
            { label: "Pickups Today", items: pickupsToday, color: "#3B82F6", icon: "↑", filterKey: "pickup_today" },
            { label: "Pickups Tomorrow", items: pickupsTomorrow, color: "#00A8CC", icon: "↗", filterKey: "pickup_tomorrow" },
            { label: "Deliveries Today", items: deliveriesToday, color: "#22C55E", icon: "↓", filterKey: "delivery_today" },
            { label: "Deliveries Tomorrow", items: deliveriesTomorrow, color: "#10B981", icon: "↘", filterKey: "delivery_tomorrow" },
            { label: "Tracking Behind", items: trackingBehind, color: "#F97316", icon: "📡", statusKey: "issue" },
            { label: "Loads to Cover", items: loadsToCover, color: "#EF4444", icon: "🔴", statusKey: "pending" },
          ].map((group, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ fontSize: 10, color: group.color }}>{group.icon}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8" }}>{group.label}</span>
                </div>
                <span style={{ fontSize: 13, fontWeight: 800, color: group.items.length > 0 ? group.color : "#334155", fontFamily: "'JetBrains Mono', monospace" }}>
                  {group.items.length}
                </span>
              </div>
              {group.items.length > 0 && (() => {
                const acctCounts = {};
                group.items.forEach(s => { acctCounts[s.account] = (acctCounts[s.account] || 0) + 1; });
                const sorted = Object.entries(acctCounts).sort((a, b) => b[1] - a[1]);
                return (
                <div style={{ marginLeft: 15, marginBottom: 4 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px" }}>
                    {sorted.map(([acct, cnt]) => (
                      <div key={acct} style={{ fontSize: 10, color: "#5A6478", padding: "2px 0", display: "flex", gap: 4, alignItems: "center" }}>
                        <span style={{ color: "#F0F2F5", fontWeight: 600 }}>{acct}</span>
                        <span style={{ color: group.color, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700 }}>{cnt}</span>
                      </div>
                    ))}
                  </div>
                  <div onClick={() => group.filterKey ? onFilterDate && onFilterDate(group.filterKey) : group.statusKey ? onFilterStatus && onFilterStatus(group.statusKey) : null}
                    style={{ fontSize: 9, color: group.color, padding: "2px 0", cursor: "pointer", fontWeight: 600, marginTop: 2 }}
                    onMouseEnter={e => e.currentTarget.style.opacity = "0.7"}
                    onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                    View all →
                  </div>
                </div>
                );
              })()}
            </div>
          ))}
          {pickupsToday.length === 0 && pickupsTomorrow.length === 0 && deliveriesToday.length === 0 && deliveriesTomorrow.length === 0 && trackingBehind.length === 0 && loadsToCover.length === 0 && (
            <div style={{ textAlign: "center", padding: 20, color: "#3D4557", fontSize: 11 }}>No action items for today</div>
          )}
        </div>

        {/* Live Alerts */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14 }}>{"\u26A1"}</span> Live Alerts
              {filteredAlerts.length > 0 && <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#00D4AA", fontWeight: 700 }}>{filteredAlerts.length}</span>}
            </div>
            {filteredAlerts.length > 0 && (
              <button onClick={onDismissAll}
                style={{ padding: "4px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#5A6478", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s ease" }}
                onMouseEnter={e => { e.currentTarget.style.color = "#8B95A8"; }}
                onMouseLeave={e => { e.currentTarget.style.color = "#5A6478"; }}>
                Clear All
              </button>
            )}
          </div>
          {/* Rep filter tabs */}
          <div style={{ display: "flex", gap: 2, marginBottom: 12, background: "#0D1119", borderRadius: 10, padding: 3, width: "fit-content", flexWrap: "wrap" }}>
            {alertTabs.map(t => (
              <button key={t.id} onClick={() => setAlertFilter(t.id)}
                style={{ padding: "6px 12px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 500, cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s ease",
                  background: alertFilter === t.id ? "#1E2738" : "transparent",
                  boxShadow: alertFilter === t.id ? "0 1px 4px rgba(0,0,0,0.3)" : "none",
                  color: alertFilter === t.id ? "#F0F2F5" : "#8B95A8" }}>
                {t.label}{t.count > 0 && <span style={{ marginLeft: 4, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: alertFilter === t.id ? (t.color || "#00D4AA") : "#5A6478" }}>{t.count}</span>}
              </button>
            ))}
          </div>
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            {filteredAlerts.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "#3D4557", fontSize: 12 }}>No active alerts</div>}
            {filteredAlerts.map(alert => {
              const config = ALERT_TYPE_CONFIG[alert.type] || ALERT_TYPE_CONFIG.status_change;
              const alertShipment = alert.shipmentId ? shipments.find(s => s.id === alert.shipmentId) : null;
              return (
                <div key={alert.id} style={{ padding: "8px 10px", borderRadius: 8, marginBottom: 2, display: "flex", alignItems: "center", gap: 8, cursor: alertShipment ? "pointer" : "default", transition: "background 0.15s ease" }}
                  onClick={() => alertShipment && handleLoadClick(alertShipment)}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <span style={{ fontSize: 12, width: 20, textAlign: "center", flexShrink: 0, color: config.color }}>{config.icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{alert.message}</div>
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 1 }}>{alert.detail}{alert.timestamp ? ` \u00B7 ${timeAgo(alert.timestamp)}` : ""}</div>
                  </div>
                  <span style={{ fontSize: 8, fontWeight: 600, padding: "2px 6px", borderRadius: 6, background: `${config.color}18`, color: config.color, border: `1px solid ${config.color}33`, flexShrink: 0, whiteSpace: "nowrap" }}>{config.label}</span>
                  <button onClick={(e) => { e.stopPropagation(); onDismissAlert(alert.id); }}
                    aria-label="Dismiss alert"
                    style={{ background: "none", border: "none", fontSize: 12, color: "#3D4557", cursor: "pointer", flexShrink: 0, padding: "0 2px", transition: "color 0.15s ease" }}
                    onMouseEnter={e => e.currentTarget.style.color = "#8B95A8"}
                    onMouseLeave={e => e.currentTarget.style.color = "#3D4557"}>&times;</button>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Billing Pipeline removed — lives in Billing tab now */}
    </div>
  );
}
