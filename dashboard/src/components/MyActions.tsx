import { useState, useMemo } from 'react';
import { REP_ACCOUNTS, ALL_REP_NAMES, ALERT_TYPE_CONFIG } from '../helpers/constants';
import { isDateToday, isDateTomorrow, useIsMobile } from '../helpers/utils';

// ─── Rep avatar colors (spec: RA=cyan, JF=blue, JA=purple, BO=green, TO=amber) ───
const MY_ACTIONS_REP_COLORS = {
  Radka: "#06b6d4",
  "John F": "#3B82F6",
  Janice: "#A855F7",
  Boviet: "#22C55E",
  Tolead: "#F59E0B",
};

// Severity tiers
const SEVERITY = { red: 0, amber: 1, gray: 2 };

export default function MyActions({
  shipments, trackingSummary, alerts,
  currentUser, repProfiles,
  onFilterDate, onFilterStatus, onFilterAccount,
  handleLoadClick, onDismissAlert,
}) {
  const [activeFilter, setActiveFilter] = useState("urgent");
  const [selectedRep, setSelectedRep] = useState(
    currentUser?.rep_name || "John F"
  );
  const [expandedSections, setExpandedSections] = useState(new Set());
  const isMobile = useIsMobile();

  // Scope shipments to selected rep's accounts
  const repAccounts = REP_ACCOUNTS[selectedRep] || [];
  const repShipments = useMemo(() =>
    shipments.filter(s => repAccounts.includes(s.account)),
    [shipments, repAccounts]
  );

  // ── Compute action groups ──
  const needsDriver = useMemo(() =>
    repShipments.filter(s => {
      const hasPickupSoon = isDateToday(s.pickupDate) || isDateTomorrow(s.pickupDate);
      const noCarrier = !s.carrier || s.carrier.trim() === "";
      return hasPickupSoon && noCarrier && !["delivered", "empty_return", "cancelled", "cancelled_tonu", "billed_closed"].includes(s.status);
    }),
    [repShipments]
  );

  const behindSchedule = useMemo(() =>
    repShipments.filter(s => {
      const efjBare = s.efj?.replace(/^EFJ\s*/i, "");
      const t = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
      return t && (t.behindSchedule || t.cantMakeIt);
    }),
    [repShipments, trackingSummary]
  );

  const pickupsToday = useMemo(() =>
    repShipments.filter(s => isDateToday(s.pickupDate) && !["delivered", "empty_return", "cancelled", "cancelled_tonu", "billed_closed"].includes(s.status)),
    [repShipments]
  );

  const pickupsTomorrow = useMemo(() =>
    repShipments.filter(s => isDateTomorrow(s.pickupDate) && !["delivered", "empty_return", "cancelled", "cancelled_tonu", "billed_closed"].includes(s.status)),
    [repShipments]
  );

  const deliveriesToday = useMemo(() =>
    repShipments.filter(s => isDateToday(s.deliveryDate)),
    [repShipments]
  );

  const deliveriesTomorrow = useMemo(() =>
    repShipments.filter(s => isDateTomorrow(s.deliveryDate) && !["delivered", "empty_return"].includes(s.status)),
    [repShipments]
  );

  // ── Build unified action list ──
  const actionGroups = useMemo(() => {
    const groups = [];

    if (needsDriver.length > 0) {
      groups.push({
        id: "needs_driver",
        label: "Needs driver",
        severity: "red",
        color: "#ff5252",
        dotColor: "#ff5252",
        items: needsDriver,
        filterAction: () => onFilterStatus("pending"),
      });
    }

    if (behindSchedule.length > 0) {
      groups.push({
        id: "behind_schedule",
        label: "Behind schedule",
        severity: "amber",
        color: "#ffab00",
        dotColor: "#ffab00",
        items: behindSchedule,
        filterAction: () => onFilterStatus("issue"),
        showCheckCall: true,
      });
    }

    if (pickupsToday.length > 0) {
      groups.push({
        id: "pickups_today",
        label: "Pickups today",
        severity: "gray",
        color: "#8B95A8",
        dotColor: "#5A6478",
        items: pickupsToday,
        filterAction: () => onFilterDate("pickup_today"),
      });
    }

    if (deliveriesToday.length > 0) {
      groups.push({
        id: "deliveries_today",
        label: "Deliveries today",
        severity: "gray",
        color: "#8B95A8",
        dotColor: "#5A6478",
        items: deliveriesToday,
        filterAction: () => onFilterDate("delivery_today"),
      });
    }

    if (pickupsTomorrow.length > 0) {
      groups.push({
        id: "pickups_tomorrow",
        label: "Pickups tomorrow",
        severity: "gray",
        color: "#8B95A8",
        dotColor: "#5A6478",
        items: pickupsTomorrow,
        filterAction: () => onFilterDate("pickup_tomorrow"),
      });
    }

    if (deliveriesTomorrow.length > 0) {
      groups.push({
        id: "deliveries_tomorrow",
        label: "Deliveries tomorrow",
        severity: "gray",
        color: "#8B95A8",
        dotColor: "#5A6478",
        items: deliveriesTomorrow,
        filterAction: () => onFilterDate("delivery_tomorrow"),
      });
    }

    return groups;
  }, [needsDriver, behindSchedule, pickupsToday, deliveriesToday, pickupsTomorrow, deliveriesTomorrow, onFilterDate, onFilterStatus]);

  // ── Filter by active pill ──
  const filteredGroups = useMemo(() => {
    switch (activeFilter) {
      case "urgent":
        return actionGroups.filter(g => g.severity === "red" || g.severity === "amber");
      case "today":
        return actionGroups.filter(g =>
          ["needs_driver", "behind_schedule", "pickups_today", "deliveries_today"].includes(g.id)
        );
      case "tomorrow":
        return actionGroups.filter(g =>
          ["pickups_tomorrow", "deliveries_tomorrow"].includes(g.id)
        );
      default:
        return actionGroups;
    }
  }, [actionGroups, activeFilter]);

  const urgentCount = actionGroups.filter(g => g.severity === "red" || g.severity === "amber")
    .reduce((sum, g) => sum + g.items.length, 0);

  const toggleSection = (id) => setExpandedSections(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  // ── Account breakdown for a group ──
  const getAccountBreakdown = (items) => {
    const counts = {};
    items.forEach(s => { counts[s.account] = (counts[s.account] || 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  };

  // ── Overdue time calc ──
  const getOverdue = (s) => {
    const target = s.deliveryDate || s.pickupDate;
    if (!target) return null;
    const ms = Date.now() - new Date(target).getTime();
    if (ms <= 0) return null;
    const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
    return h > 0 ? `${h}h overdue` : `${m}m overdue`;
  };

  const repColor = MY_ACTIONS_REP_COLORS[selectedRep] || "#8B95A8";
  const repInitials = selectedRep.slice(0, 2).toUpperCase();

  const filters = [
    { key: "urgent", label: "Urgent only" },
    { key: "today", label: "Due today" },
    { key: "tomorrow", label: "Tomorrow" },
    { key: "all", label: "All" },
  ];

  return (
    <div className="dash-panel" style={{ padding: isMobile ? 12 : 16, animation: "slide-up 0.4s ease 0.2s both", borderLeft: "3px solid transparent", borderImage: urgentCount > 0 ? "linear-gradient(180deg, #ff5252, #ffab00, #2979ff) 1" : "linear-gradient(180deg, #00c853, #00b8d4, #2979ff) 1" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="dash-panel-title">My Actions</span>
          {urgentCount > 0 && (
            <span style={{
              fontSize: 11, fontWeight: 700, color: "#fff",
              background: "#ff5252", borderRadius: 10, padding: "2px 10px",
              fontFamily: "'JetBrains Mono', monospace",
              animation: "alert-pulse 2s ease infinite",
            }}>
              {urgentCount} urgent
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 28, height: 28, borderRadius: "50%",
            background: `linear-gradient(135deg, ${repColor}44, ${repColor}88)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0,
            border: `2px solid ${repColor}66`,
          }}>
            {repInitials}
          </div>
          <select
            value={selectedRep}
            onChange={e => setSelectedRep(e.target.value)}
            style={{
              padding: "5px 10px", background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8,
              color: "#F0F2F5", fontSize: 12, fontWeight: 600, cursor: "pointer",
              fontFamily: "'Plus Jakarta Sans', sans-serif", outline: "none",
            }}
          >
            {ALL_REP_NAMES.map(r => (
              <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Filter pills */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {filters.map(f => {
          const isActive = activeFilter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setActiveFilter(f.key)}
              style={{
                padding: "5px 14px", borderRadius: 20, border: "none",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
                fontFamily: "'Plus Jakarta Sans', sans-serif",
                transition: "all 0.2s ease",
                background: isActive
                  ? (f.key === "urgent" ? "linear-gradient(135deg, #ff5252, #ff1744)" : "rgba(255,255,255,0.10)")
                  : "rgba(255,255,255,0.04)",
                color: isActive ? "#fff" : "#8B95A8",
                boxShadow: isActive && f.key === "urgent" ? "0 2px 8px rgba(255,82,82,0.3)" : "none",
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = "rgba(255,255,255,0.07)"; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = "rgba(255,255,255,0.04)"; }}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Action rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {filteredGroups.length === 0 && (
          <div style={{ padding: 24, textAlign: "center", color: "#3D4557", fontSize: 12 }}>
            {activeFilter === "urgent" ? "No urgent actions right now" : "No actions to show"}
          </div>
        )}

        {filteredGroups.map(group => {
          const isExpanded = expandedSections.has(group.id);
          const breakdown = getAccountBreakdown(group.items);

          return (
            <div key={group.id}>
              {/* Group header row */}
              <div
                onClick={() => toggleSection(group.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 12px", borderRadius: 10, cursor: "pointer",
                  background: isExpanded ? "rgba(255,255,255,0.03)" : "transparent",
                  transition: "background 0.15s ease",
                }}
                onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                onMouseLeave={e => { if (!isExpanded) e.currentTarget.style.background = isExpanded ? "rgba(255,255,255,0.03)" : "transparent"; }}
              >
                {/* Severity dot */}
                <span style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                  background: group.dotColor,
                  boxShadow: group.severity === "red" ? `0 0 8px ${group.dotColor}88` : "none",
                }} />

                {/* Label */}
                <span style={{
                  fontSize: 13, fontWeight: 600,
                  color: group.severity === "red" ? "#F0F2F5" : group.severity === "amber" ? "#F0F2F5" : "#8B95A8",
                }}>
                  {group.label}
                </span>

                {/* Count badge */}
                <span style={{
                  fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
                  color: group.color, padding: "1px 8px", borderRadius: 6,
                  background: `${group.color}18`, border: `1px solid ${group.color}33`,
                }}>
                  {group.items.length} {group.items.length === 1 ? "load" : "loads"}
                </span>

                {/* Account breakdown pills (collapsed view) */}
                <div style={{ flex: 1, display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {breakdown.slice(0, 3).map(([acct, cnt]) => (
                    <span key={acct} style={{
                      fontSize: 11, color: "#5A6478", fontWeight: 500,
                    }}>
                      {acct}{cnt > 1 ? ` ${cnt}` : ""}
                    </span>
                  ))}
                  {breakdown.length > 3 && (
                    <span style={{ fontSize: 11, color: "#3D4557" }}>+{breakdown.length - 3}</span>
                  )}
                </div>

                {/* Expand arrow */}
                <span style={{ fontSize: 11, color: "#5A6478", width: 12, textAlign: "center", flexShrink: 0 }}>
                  {isExpanded ? "\u25B2" : "\u25BC"}
                </span>
              </div>

              {/* Expanded detail rows */}
              {isExpanded && (
                <div style={{
                  marginLeft: 18, borderLeft: `2px solid ${group.color}33`,
                  paddingLeft: 12, marginBottom: 4, marginTop: 2,
                }}>
                  {group.items.slice(0, 20).map((s, i) => {
                    const overdue = group.showCheckCall ? getOverdue(s) : null;
                    const origin = s.origin || s.pickupCity || "";
                    const dest = s.destination || s.deliveryCity || "";
                    const lane = origin && dest ? `${origin} \u2192 ${dest}` : "";

                    return (
                      <div
                        key={s.id || i}
                        onClick={() => handleLoadClick(s)}
                        style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 10px", borderRadius: 8, cursor: "pointer",
                          transition: "background 0.15s ease",
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, color: "#C8CDD5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            <span style={{ color: "#F0F2F5", fontWeight: 600 }}>{s.account}</span>
                            {isDateToday(s.pickupDate) && <span style={{ color: "#5A6478" }}> · PU today</span>}
                            {isDateToday(s.deliveryDate) && <span style={{ color: "#5A6478" }}> · DEL today</span>}
                            {isDateTomorrow(s.pickupDate) && <span style={{ color: "#5A6478" }}> · PU tomorrow</span>}
                            {lane && <span style={{ color: "#5A6478" }}> · {lane}</span>}
                          </div>
                          {overdue && (
                            <div style={{ fontSize: 11, color: "#ffab00", fontWeight: 600, marginTop: 1 }}>{overdue}</div>
                          )}
                        </div>
                        {group.showCheckCall && (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleLoadClick(s); }}
                            style={{
                              padding: "4px 12px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                              border: `1px solid ${group.color}44`, background: `${group.color}12`,
                              color: group.color, cursor: "pointer", fontFamily: "inherit",
                              transition: "all 0.15s", whiteSpace: "nowrap",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = `${group.color}25`; }}
                            onMouseLeave={e => { e.currentTarget.style.background = `${group.color}12`; }}
                          >
                            Check call
                          </button>
                        )}
                      </div>
                    );
                  })}
                  {group.items.length > 20 && (
                    <div
                      onClick={group.filterAction}
                      style={{ fontSize: 11, color: group.color, padding: "4px 10px", cursor: "pointer", fontWeight: 600 }}
                    >
                      View all {group.items.length} →
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
