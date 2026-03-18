import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { REP_ACCOUNTS, ALL_REP_NAMES, ALERT_TYPE_CONFIG } from '../helpers/constants';
import { isDateToday, isDateTomorrow, useIsMobile } from '../helpers/utils';
import { apiFetch, API_BASE } from '../helpers/api';

// ─── Rep avatar colors (spec: RA=cyan, JF=blue, JA=purple, BO=green, TO=amber) ───
const MY_ACTIONS_REP_COLORS = {
  Radka: "#06b6d4",
  "John F": "#3B82F6",
  Janice: "#A855F7",
  Allie: "#F59E0B",
  "John N": "#0891B2",
  Amanda: "#7C3AED",
  Boviet: "#22C55E",
  Tolead: "#F59E0B",
};

// Severity tiers
const SEVERITY = { red: 0, amber: 1, blue: 2, gray: 3 };

// Assignment action types
const ACTION_TYPES = [
  { key: "cover_load", label: "Cover", short: "Cover" },
  { key: "pro_load", label: "PRO", short: "PRO" },
  { key: "close_out", label: "Close", short: "Close" },
  { key: "quote", label: "Quote", short: "Quote" },
];

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

  // ── Assignment state ──
  const [assignments, setAssignments] = useState([]);
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [assignEfjSearch, setAssignEfjSearch] = useState("");
  const [assignSelectedShipment, setAssignSelectedShipment] = useState(null);
  const [assignActionType, setAssignActionType] = useState("cover_load");
  const [assignToRep, setAssignToRep] = useState("");
  const [assignNote, setAssignNote] = useState("");
  const [assignLoading, setAssignLoading] = useState(false);
  const [showEfjDropdown, setShowEfjDropdown] = useState(false);
  const efjInputRef = useRef(null);

  // Fetch assignments for selected rep
  const fetchAssignments = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/rep-tasks?rep=${encodeURIComponent(selectedRep)}`);
      if (res.ok) { const d = await res.json(); setAssignments(d.tasks || []); }
    } catch {}
  }, [selectedRep]);

  useEffect(() => { fetchAssignments(); }, [fetchAssignments]);

  // Auto-clear assignments when shipment data refreshes (not on assignment creation)
  const prevShipmentsRef = useRef(shipments);
  useEffect(() => {
    // Only run auto-clear when shipments data actually changes (API refresh), not on first mount with assignments
    if (prevShipmentsRef.current === shipments) return;
    prevShipmentsRef.current = shipments;
    if (!assignments.length || !shipments.length) return;
    assignments.forEach(async (a) => {
      if (!a.efj) return;
      const ship = shipments.find(s => s.efj === a.efj);
      if (!ship) return;
      let clearType = null;
      if (a.auto_type === "cover_load" && ship.carrier && ship.carrier.trim()) {
        clearType = "driver_assigned";
      } else if (a.auto_type === "close_out" && ["delivered", "billed_closed"].includes(ship.status)) {
        clearType = "delivered";
      }
      if (clearType) {
        try {
          await apiFetch(`${API_BASE}/api/rep-tasks/auto-clear`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ efj: a.efj, clear_type: clearType }),
          });
          setAssignments(prev => prev.filter(t => t.id !== a.id));
        } catch {}
      }
    });
  }, [shipments]);

  const submitAssignment = async () => {
    if (!assignSelectedShipment || !assignToRep) return;
    setAssignLoading(true);
    const actionLabel = ACTION_TYPES.find(t => t.key === assignActionType)?.label || assignActionType;
    const text = assignNote.trim() || `${actionLabel}: ${assignSelectedShipment.efj}`;
    try {
      const res = await apiFetch(`${API_BASE}/api/rep-tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rep: assignToRep,
          text,
          efj: assignSelectedShipment.efj,
          auto_type: assignActionType,
          assigned_by: currentUser?.rep_name || selectedRep,
        }),
      });
      if (res.ok) {
        setShowAssignForm(false);
        setAssignEfjSearch("");
        setAssignSelectedShipment(null);
        setAssignActionType("cover_load");
        setAssignToRep("");
        setAssignNote("");
        await fetchAssignments();
      }
    } catch {}
    setAssignLoading(false);
  };

  const dismissAssignment = async (taskId, e) => {
    e?.stopPropagation();
    try {
      await apiFetch(`${API_BASE}/api/rep-tasks/${taskId}/complete`, { method: "POST" });
      setAssignments(prev => prev.filter(t => t.id !== taskId));
    } catch {}
  };

  // EFJ search results
  const efjMatches = useMemo(() => {
    if (!assignEfjSearch.trim()) return [];
    const q = assignEfjSearch.toLowerCase();
    return shipments
      .filter(s => s.efj?.toLowerCase().includes(q) || s.container?.toLowerCase().includes(q))
      .slice(0, 8);
  }, [assignEfjSearch, shipments]);

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

  // ── Build "Assigned to you" items by enriching with shipment data ──
  const assignedItems = useMemo(() =>
    assignments
      .filter(a => a.auto_type && ["cover_load", "pro_load", "close_out", "quote"].includes(a.auto_type))
      .map(a => {
        const ship = shipments.find(s => s.efj === a.efj);
        return { ...a, shipment: ship || null };
      }),
    [assignments, shipments]
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

    // Assigned to you — blue severity, after urgent groups
    if (assignedItems.length > 0) {
      groups.push({
        id: "assigned_to_you",
        label: "Assigned to you",
        severity: "blue",
        color: "#2979ff",
        dotColor: "#2979ff",
        items: assignedItems,
        isAssignment: true,
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
  }, [needsDriver, behindSchedule, assignedItems, pickupsToday, deliveriesToday, pickupsTomorrow, deliveriesTomorrow, onFilterDate, onFilterStatus]);

  // ── Filter by active pill ──
  const filteredGroups = useMemo(() => {
    switch (activeFilter) {
      case "urgent":
        return actionGroups.filter(g => g.severity === "red" || g.severity === "amber" || g.severity === "blue");
      case "today":
        return actionGroups.filter(g =>
          ["needs_driver", "behind_schedule", "assigned_to_you", "pickups_today", "deliveries_today"].includes(g.id)
        );
      case "tomorrow":
        return actionGroups.filter(g =>
          ["pickups_tomorrow", "deliveries_tomorrow"].includes(g.id)
        );
      default:
        return actionGroups;
    }
  }, [actionGroups, activeFilter]);

  const urgentCount = actionGroups.filter(g => g.severity === "red" || g.severity === "amber" || g.severity === "blue")
    .reduce((sum, g) => sum + g.items.length, 0);

  const toggleSection = (id) => setExpandedSections(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  // ── Account breakdown for a group ──
  const getAccountBreakdown = (items) => {
    const counts = {};
    items.forEach(s => {
      const acct = s.account || s.shipment?.account;
      if (acct) counts[acct] = (counts[acct] || 0) + 1;
    });
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

      {/* Filter pills + Assign button */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
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

        {/* Assign button */}
        <button
          onClick={() => {
            setShowAssignForm(!showAssignForm);
            if (!showAssignForm) setAssignToRep(selectedRep);
          }}
          style={{
            padding: "5px 14px", borderRadius: 20, border: "none",
            fontSize: 11, fontWeight: 600, cursor: "pointer",
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            transition: "all 0.2s ease",
            background: showAssignForm ? "rgba(41,121,255,0.15)" : "rgba(255,255,255,0.04)",
            color: showAssignForm ? "#2979ff" : "#5A6478",
            marginLeft: 2,
          }}
          onMouseEnter={e => { if (!showAssignForm) e.currentTarget.style.background = "rgba(255,255,255,0.07)"; }}
          onMouseLeave={e => { if (!showAssignForm) e.currentTarget.style.background = "rgba(255,255,255,0.04)"; }}
        >
          + Assign
        </button>
      </div>

      {/* ── Inline Assign Form ── */}
      {showAssignForm && (
        <div style={{
          marginBottom: 14, padding: 12, borderRadius: 10,
          background: "rgba(41,121,255,0.04)",
          border: "1px solid rgba(41,121,255,0.12)",
        }}>
          {/* Row 1: EFJ search + Rep selector */}
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <input
                ref={efjInputRef}
                value={assignSelectedShipment ? `${assignSelectedShipment.efj} — ${assignSelectedShipment.account}` : assignEfjSearch}
                onChange={e => {
                  setAssignEfjSearch(e.target.value);
                  setAssignSelectedShipment(null);
                  setShowEfjDropdown(true);
                }}
                onFocus={() => { if (assignEfjSearch && !assignSelectedShipment) setShowEfjDropdown(true); }}
                onClick={() => { if (assignSelectedShipment) { setAssignSelectedShipment(null); setAssignEfjSearch(""); } }}
                placeholder="Search EFJ# or container..."
                style={{
                  width: "100%", padding: "7px 10px", borderRadius: 8,
                  border: "1px solid rgba(255,255,255,0.10)", background: "rgba(255,255,255,0.04)",
                  color: "#F0F2F5", fontSize: 11, outline: "none",
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  boxSizing: "border-box",
                }}
              />
              {showEfjDropdown && efjMatches.length > 0 && !assignSelectedShipment && (
                <div style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50,
                  background: "#1A1F2E", border: "1px solid rgba(255,255,255,0.10)",
                  borderRadius: 8, marginTop: 2, maxHeight: 180, overflowY: "auto",
                  boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                }}>
                  {efjMatches.map(s => (
                    <div
                      key={s.efj}
                      onClick={() => {
                        setAssignSelectedShipment(s);
                        setAssignEfjSearch("");
                        setShowEfjDropdown(false);
                      }}
                      style={{
                        padding: "7px 10px", cursor: "pointer", fontSize: 11,
                        color: "#C8CDD5", transition: "background 0.1s",
                        display: "flex", gap: 8, alignItems: "center",
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.05)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      <span style={{ color: "#F0F2F5", fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>{s.efj}</span>
                      <span style={{ color: "#5A6478" }}>{s.account}</span>
                      {s.container && <span style={{ color: "#3D4557", fontSize: 10 }}>{s.container}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <select
              value={assignToRep}
              onChange={e => setAssignToRep(e.target.value)}
              style={{
                padding: "6px 8px", background: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.10)", borderRadius: 8,
                color: "#F0F2F5", fontSize: 11, fontWeight: 600, cursor: "pointer",
                fontFamily: "'Plus Jakarta Sans', sans-serif", outline: "none",
                minWidth: 90,
              }}
            >
              <option value="" disabled style={{ background: "#0D1119" }}>Rep...</option>
              {ALL_REP_NAMES.map(r => (
                <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>
              ))}
            </select>
          </div>

          {/* Row 2: Action type quick-assign buttons — tap to assign immediately */}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {ACTION_TYPES.map(t => (
              <button
                key={t.key}
                onClick={() => { setAssignActionType(t.key); setTimeout(() => { /* submit with this type */ }, 0); }}
                onClickCapture={() => setAssignActionType(t.key)}
                onDoubleClick={() => {}}
                style={{
                  padding: "5px 14px", borderRadius: 16, border: "none",
                  fontSize: 10, fontWeight: 700, cursor: "pointer",
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  transition: "all 0.15s",
                  background: assignActionType === t.key ? "rgba(41,121,255,0.18)" : "rgba(255,255,255,0.04)",
                  color: assignActionType === t.key ? "#2979ff" : "#5A6478",
                  textTransform: "uppercase", letterSpacing: "0.3px",
                }}
              >
                {t.label}
              </button>
            ))}
            <div style={{ flex: 1 }} />
            <button
              onClick={submitAssignment}
              disabled={assignLoading || !assignSelectedShipment || !assignToRep}
              style={{
                padding: "5px 16px", borderRadius: 16, border: "none",
                background: (!assignSelectedShipment || !assignToRep) ? "rgba(255,255,255,0.04)" : "rgba(0,212,170,0.15)",
                color: (!assignSelectedShipment || !assignToRep) ? "#3D4557" : "#00D4AA",
                fontSize: 10, fontWeight: 700, cursor: "pointer",
                textTransform: "uppercase", letterSpacing: "0.3px",
                transition: "all 0.15s",
              }}
            >
              Assign
            </button>
            <button
              onClick={() => {
                setShowAssignForm(false);
                setAssignEfjSearch("");
                setAssignSelectedShipment(null);
                setAssignNote("");
              }}
              style={{
                background: "none", border: "none", color: "#3D4557",
                fontSize: 11, cursor: "pointer", padding: "4px",
              }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

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
                  boxShadow: group.severity === "red" ? `0 0 8px ${group.dotColor}88` : group.severity === "blue" ? `0 0 6px ${group.dotColor}55` : "none",
                }} />

                {/* Label */}
                <span style={{
                  fontSize: 13, fontWeight: 600,
                  color: group.severity === "gray" ? "#8B95A8" : "#F0F2F5",
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
                  {/* Assignment rows */}
                  {group.isAssignment ? (
                    group.items.slice(0, 20).map((a, i) => {
                      const s = a.shipment;
                      const origin = s?.origin || s?.pickupCity || "";
                      const dest = s?.destination || s?.deliveryCity || "";
                      const lane = origin && dest ? `${origin} \u2192 ${dest}` : "";
                      const typeLabel = ACTION_TYPES.find(t => t.key === a.auto_type)?.short || a.auto_type;

                      return (
                        <div
                          key={a.id || i}
                          onClick={() => s && handleLoadClick(s)}
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            padding: "6px 10px", borderRadius: 8, cursor: s ? "pointer" : "default",
                            transition: "background 0.15s ease",
                          }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                          onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                        >
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 11, color: "#C8CDD5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ color: "#F0F2F5", fontWeight: 600 }}>{s?.account || "—"}</span>
                              <span style={{
                                fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
                                background: "rgba(41,121,255,0.12)", color: "#2979ff",
                                textTransform: "uppercase", letterSpacing: "0.3px",
                              }}>
                                {typeLabel}
                              </span>
                              {a.efj && <span style={{ color: "#5A6478", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>{a.efj}</span>}
                              {lane && <span style={{ color: "#3D4557" }}> · {lane}</span>}
                            </div>
                            {a.text && a.text !== `${ACTION_TYPES.find(t => t.key === a.auto_type)?.label}: ${a.efj}` && (
                              <div style={{ fontSize: 10, color: "#5A6478", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.text}</div>
                            )}
                            {a.assigned_by && (
                              <div style={{ fontSize: 10, color: "#3D4557", marginTop: 1 }}>from {a.assigned_by}</div>
                            )}
                          </div>
                          <button
                            onClick={(e) => dismissAssignment(a.id, e)}
                            title="Dismiss"
                            style={{
                              background: "none", border: "none", color: "#3D4557",
                              fontSize: 13, cursor: "pointer", padding: "2px 4px",
                              lineHeight: 1, flexShrink: 0, transition: "color 0.15s",
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = "#8B95A8"}
                            onMouseLeave={e => e.currentTarget.style.color = "#3D4557"}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })
                  ) : (
                    /* Standard shipment rows */
                    group.items.slice(0, 20).map((s, i) => {
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
                    })
                  )}
                  {group.items.length > 20 && group.filterAction && (
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
