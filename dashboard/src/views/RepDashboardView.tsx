import { useState, useEffect, useMemo } from "react";
import { useAppStore } from "../store";
import { API_BASE, apiFetch } from "../helpers/api";
import {
  STATUSES, FTL_STATUSES, STATUS_COLORS, FTL_STATUS_COLORS, BILLING_STATUSES,
  BILLING_STATUS_COLORS, REP_ACCOUNTS, REP_COLORS, MASTER_REPS, TRUCK_TYPES, Z,
  isFTLShipment, getStatusesForShipment, getStatusColors, resolveStatusLabel,
  isPostDelivery,
} from "../helpers/constants";
import {
  isDateToday, isDateTomorrow, isDatePast, getRepShipments, splitDateTime, parseDate,
  calcMarginPct, formatDDMM, parseDDMM, normalizeTimeInput, parseTerminalNotes,
  COL_FILTER_KEY_MAP, applyColFilters, buildColFilterOptions,
} from "../helpers/utils";
import DocIndicators from "../components/DocIndicators";
import TrackingBadge from "../components/TrackingBadge";
import TerminalBadge from "../components/TerminalBadge";

/**
 * Render a rep-specific dashboard that displays Dray and FTL views with inline editing, column/date filtering, per-account grouping for master reps, inbox/action summary pills, and a per-load delete confirmation flow.
 *
 * @param {Object} props - Component props.
 * @param {string} props.repName - The representative name used to filter and customize the dashboard (e.g., "Boviet", "Tolead", master rep names).
 * @param {Array<Object>} props.shipments - List of shipment objects to display and operate on.
 * @param {function():void} props.onBack - Callback invoked when the Back action is triggered.
 * @param {function(string,string):void} props.handleStatusUpdate - Persist a status change for a shipment; called with (shipmentId, statusKey).
 * @param {function(Object,Object=):void} props.handleLoadClick - Open a shipment slide-over or details view; called with (shipment, options).
 * @param {function(Object,string,string):void} props.handleFieldUpdate - Persist a simple field update on a shipment; called with (shipment, field, value).
 * @param {function(Object,string,any):void} props.handleMetadataUpdate - Persist metadata-level updates (e.g., truckType, customerRate, notes); called with (shipment, key, value).
 * @param {function(Object,string,any):void} props.handleDriverFieldUpdate - Persist driver-related fields (e.g., trailer, driverPhone, carrierEmail); called with (shipment, key, value).
 * @param {function(string):Promise<void>} props.handleDeleteLoad - Delete a load by EFJ identifier; used by the delete confirmation modal.
 * @param {Object<string, Object>} props.repProfiles - Map of rep profile metadata (e.g., avatar_url) keyed by rep name.
 * @param {function():void} [props.onProfileUpdate] - Optional callback invoked after a rep profile/avatar upload completes.
 * @param {Object<string, Object>} props.trackingSummary - Map of EFJ/container -> tracking metadata used for MP/terminal badges.
 * @param {Object<string, Object>} props.docSummary - Map of EFJ -> document metadata (pod presence, etc.) used by indicators and filters.
 * @param {Array<Object>} props.inboxThreads - List of inbox threads used to compute needs-reply and rate-response counts and to link into the inbox.
 * @param {function(string, string=):void} props.onNavigateInbox - Navigate to the inbox; called with (viewKey, filter?).
 * @param {function():void} [props.onAddLoad] - Optional callback to create a new load.
 * @param {function():void} [props.onRefresh] - Optional callback to refresh dashboard data.
 *
 * @returns {JSX.Element} The rendered RepDashboardView React element.
 */
export default function RepDashboardView({ repName, shipments, onBack, handleStatusUpdate, handleLoadClick, handleFieldUpdate, handleMetadataUpdate, handleDriverFieldUpdate, handleDeleteLoad, repProfiles, onProfileUpdate, trackingSummary, docSummary, inboxThreads, onNavigateInbox, onAddLoad, onRefresh }) {
  const highlightedEfj = useAppStore(s => s.highlightedEfj);
  const [expandedAccount, setExpandedAccount] = useState(null);
  const [bovietTab, setBovietTab] = useState("All");
  const [toleadHub, setToleadHub] = useState("All");
  const [opsTableFilter, setOpsTableFilter] = useState("all");
  const [masterTableFilter, setMasterTableFilter] = useState("all");
  const [repViewMode, setRepViewMode] = useState("dray"); // "dray" | "ftl"
  const [inlineEditId, setInlineEditId] = useState(null);
  const [inlineEditField, setInlineEditField] = useState(null);
  const [inlineEditValue, setInlineEditValue] = useState("");
  const [repColumnFilters, setRepColumnFilters] = useState({});
  const [repOpenFilterCol, setRepOpenFilterCol] = useState(null);
  const [filterDropdownPos, setFilterDropdownPos] = useState({ top: 0, left: 0 });
  const [sortOldestFirst, setSortOldestFirst] = useState(true);
  const [needsReplyOpen, setNeedsReplyOpen] = useState(false);
  const [puDateFilter, setPuDateFilter] = useState("");
  const [delDateFilter, setDelDateFilter] = useState("");
  const [deleteConfirmEfj, setDeleteConfirmEfj] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Auto-default to FTL view for Boviet/Tolead
  useEffect(() => {
    if (repName === "Boviet" || repName === "Tolead") {
      setRepViewMode("ftl");
    } else {
      setRepViewMode("dray");
    }
  }, [repName]);

  // Close column filter dropdown on outside click
  useEffect(() => {
    if (!repOpenFilterCol) return;
    const handler = (e) => { if (!e.target.closest('.col-filter-dd')) setRepOpenFilterCol(null); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [repOpenFilterCol]);

  // Close inline status dropdown on outside click
  useEffect(() => {
    if (!inlineEditId || inlineEditField !== "status") return;
    const handler = (e) => {
      if (!e.target.closest('.inline-status-dd')) setInlineEditId(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [inlineEditId, inlineEditField]);

  const isMaster = MASTER_REPS.includes(repName);
  const isBoviet = repName === "Boviet";
  const isTolead = repName === "Tolead";
  const color = REP_COLORS[repName] || "#94a3b8";

  const repShipments = getRepShipments(shipments, repName);
  const incoming = repShipments.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length;
  const activeCount = repShipments.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length;
  const onSchedule = repShipments.filter(s => !isPostDelivery(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))).length;
  const behindSchedule = repShipments.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !isPostDelivery(s.status)).length;
  const delivered = repShipments.filter(s => isPostDelivery(s.status)).length;
  const invoiced = repShipments.filter(s => s._invoiced).length;

  // For master reps: group by account
  const accountGroups = isMaster ? (REP_ACCOUNTS[repName] || []).map(acctName => {
    const acctShips = repShipments.filter(s => s.account.toLowerCase() === acctName.toLowerCase());
    return {
      name: acctName,
      ships: acctShips,
      incoming: acctShips.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length,
      active: acctShips.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length,
      onSchedule: acctShips.filter(s => !isPostDelivery(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))).length,
      behind: acctShips.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !isPostDelivery(s.status)).length,
      delivered: acctShips.filter(s => isPostDelivery(s.status)).length,
      invoiced: acctShips.filter(s => s._invoiced).length,
    };
  }) : [];

  // For Boviet: filter by hub (sheet tab name = Piedra/Hanson/Other)
  const bovietShips = isBoviet ? (bovietTab === "All" ? repShipments : repShipments.filter(s => {
    const hub = (s.hub || "").toLowerCase();
    if (bovietTab === "Other") return !hub || (hub !== "piedra" && hub !== "hanson");
    return hub === bovietTab.toLowerCase();
  })) : [];

  // For Tolead: filter by hub field from backend
  const toleadShips = isTolead ? (toleadHub === "All" ? repShipments : repShipments.filter(s => {
    return (s.hub || "ORD") === toleadHub;
  })) : [];

  // Which shipments to show in the table
  const displayShipsBase = isMaster
    ? (expandedAccount ? repShipments.filter(s => s.account.toLowerCase() === expandedAccount.toLowerCase()) : repShipments)
    : isBoviet ? bovietShips : toleadShips;

  // Apply master rep table filter
  const displayShipsFiltered = isMaster && masterTableFilter !== "all" ? displayShipsBase.filter(s => {
    if (masterTableFilter === "incoming") return ["at_port", "on_vessel", "pending"].includes(s.status);
    if (masterTableFilter === "active") return !isPostDelivery(s.status);
    if (masterTableFilter === "on_schedule") return !isPostDelivery(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)));
    if (masterTableFilter === "behind") return (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !isPostDelivery(s.status);
    if (masterTableFilter === "delivered") return isPostDelivery(s.status);
    if (masterTableFilter === "invoiced") return s._invoiced;
    if (masterTableFilter === "pu_today") return isDateToday(s.pickupDate) && !isPostDelivery(s.status);
    if (masterTableFilter === "pu_tomorrow") return isDateTomorrow(s.pickupDate) && !isPostDelivery(s.status);
    if (masterTableFilter === "del_today") return isDateToday(s.deliveryDate);
    if (masterTableFilter === "del_tomorrow") return isDateTomorrow(s.deliveryDate) && !isPostDelivery(s.status);
    if (masterTableFilter === "needs_driver") return s.rawStatus?.toLowerCase() === "unassigned" && !isPostDelivery(s.status);
    if (masterTableFilter === "awaiting_pod") { if (s.status !== "delivered") return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); const ebNS = (s.efj || "").replace(/\s/g, ""); return !(docSummary?.[eb] || docSummary?.[s.efj] || docSummary?.[ebNS])?.pod; }
    if (masterTableFilter === "ftl_only") return s.moveType === "FTL";
    if (masterTableFilter === "ready_billing") { if (!isPostDelivery(s.status)) return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); const ebNS = (s.efj || "").replace(/\s/g, ""); return !!(docSummary?.[eb] || docSummary?.[s.efj] || docSummary?.[ebNS])?.pod; }
    if (masterTableFilter === "driver_paid_pending") return s.status === "driver_paid";
    // Status key filter (from dropdown)
    if ([...STATUSES, ...FTL_STATUSES].some(st => st.key === masterTableFilter && st.key !== "all")) return s.status === masterTableFilter;
    return true;
  }) : displayShipsBase;

  // Apply date picker filters — compare parsed dates since pickupDate can be "03/15", "3/15 0800", etc.
  const displayShipsDateFiltered = displayShipsFiltered.filter(s => {
    if (puDateFilter) {
      const pu = parseDate(s.pickupDate);
      const target = new Date(puDateFilter + "T00:00:00");
      if (!pu || pu.getFullYear() !== target.getFullYear() || pu.getMonth() !== target.getMonth() || pu.getDate() !== target.getDate()) return false;
    }
    if (delDateFilter) {
      const del = parseDate(s.deliveryDate);
      const target = new Date(delDateFilter + "T00:00:00");
      if (!del || del.getFullYear() !== target.getFullYear() || del.getMonth() !== target.getMonth() || del.getDate() !== target.getDate()) return false;
    }
    return true;
  });

  // Both views show the same data — only the grid layout changes
  const displayShips = displayShipsDateFiltered;

  // Action summary data (shared across all rep views)
  const isOps = isBoviet || isTolead;
  const actionBase = displayShipsBase; // unfiltered for pill counts
  const actionPuToday = actionBase.filter(s => isDateToday(s.pickupDate) && !isPostDelivery(s.status));
  const actionPuTmrw = actionBase.filter(s => isDateTomorrow(s.pickupDate) && !isPostDelivery(s.status));
  const actionDelToday = actionBase.filter(s => isDateToday(s.deliveryDate));
  const actionDelTmrw = actionBase.filter(s => isDateTomorrow(s.deliveryDate) && !isPostDelivery(s.status));
  const actionNoDriver = actionBase.filter(s => s.rawStatus?.toLowerCase() === "unassigned" && !isPostDelivery(s.status));
  const actionBehind = actionBase.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !isPostDelivery(s.status));
  const actionNoPod = actionBase.filter(s => { if (!["delivered", "need_pod"].includes(s.status)) return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); const ebNS = (s.efj || "").replace(/\s/g, ""); return !(docSummary?.[eb] || docSummary?.[s.efj] || docSummary?.[ebNS])?.pod; });
  const actionActive = actionBase.filter(s => !isPostDelivery(s.status));
  const actionFtlOnly = actionBase.filter(s => s.moveType === "FTL");
  const actionReadyBilling = actionBase.filter(s => { if (!isPostDelivery(s.status)) return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); const ebNS = (s.efj || "").replace(/\s/g, ""); return !!(docSummary?.[eb] || docSummary?.[s.efj] || docSummary?.[ebNS])?.pod; });
  const actionDriverPaidPending = actionBase.filter(s => s.status === "driver_paid");

  // Inbox-derived pill data for this rep
  const repAccts = (REP_ACCOUNTS[repName] || []).map(a => a.toLowerCase());
  const repInboxThreads = useMemo(() => {
    if (!inboxThreads?.length) return [];
    return inboxThreads.filter(t => {
      const threadAcct = (t.account || "").toLowerCase();
      if (repAccts.some(a => threadAcct.includes(a))) return true;
      // For Boviet/Tolead, match on account name
      if (repName === "Boviet" && threadAcct.includes("boviet")) return true;
      if (repName === "Tolead" && threadAcct.includes("tolead")) return true;
      // Match by rep name in suggested_rep
      const tRep = (t.suggested_rep || "").toLowerCase();
      if (tRep && tRep === repName.toLowerCase()) return true;
      // Match by EFJ — check if any of the rep's shipments match the thread EFJ
      if (t.efj) {
        const tEfj = t.efj.replace(/^EFJ\s*/i, "").toLowerCase();
        return actionBase.some(s => (s.efj || "").replace(/^EFJ\s*/i, "").toLowerCase() === tEfj);
      }
      return false;
    });
  }, [inboxThreads, repName, actionBase]);
  const inboxNeedsReply = repInboxThreads.filter(t => t.needs_reply && t.email_type !== "rate_outreach").length;
  const inboxRateResponses = repInboxThreads.filter(t => t.email_type === "carrier_rate_response").length;

  const opsBase = displayShipsFiltered;
  const opsPickupsToday = opsBase.filter(s => isDateToday(s.pickupDate) && !isPostDelivery(s.status));
  const opsPickupsTomorrow = opsBase.filter(s => isDateTomorrow(s.pickupDate) && !isPostDelivery(s.status));
  const opsDeliveriesToday = opsBase.filter(s => isDateToday(s.deliveryDate));
  const opsDeliveriesTomorrow = opsBase.filter(s => isDateTomorrow(s.deliveryDate) && !isPostDelivery(s.status));
  const needsDriver = opsBase.filter(s => s.rawStatus?.toLowerCase() === "unassigned" && !isPostDelivery(s.status));
  const opsBehind = opsBase.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !isPostDelivery(s.status));
  const awaitingPod = opsBase.filter(s => {
    if (!["delivered", "need_pod"].includes(s.status)) return false;
    const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
    const efjNS = (s.efj || "").replace(/\s/g, "");
    const docs = docSummary?.[efjBare] || docSummary?.[s.efj] || docSummary?.[efjNS];
    return !docs?.pod;
  });
  const opsActive = opsBase.filter(s => !isPostDelivery(s.status));
  const opsTableShips = !isOps ? [] :
    opsTableFilter === "active" ? opsActive :
    opsTableFilter === "behind" ? opsBehind :
    opsTableFilter === "on_schedule" ? opsBase.filter(s => !isPostDelivery(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))) :
    opsTableFilter === "in_transit" ? opsBase.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)) :
    opsTableFilter === "pu_today" ? opsPickupsToday :
    opsTableFilter === "pu_tomorrow" ? opsPickupsTomorrow :
    opsTableFilter === "del_today" ? opsDeliveriesToday :
    opsTableFilter === "del_tomorrow" ? opsDeliveriesTomorrow :
    opsTableFilter === "needs_driver" ? needsDriver :
    opsTableFilter === "awaiting_pod" ? awaitingPod :
    opsTableFilter === "ftl_only" ? opsBase.filter(s => s.moveType === "FTL") :
    opsTableFilter === "ready_billing" ? opsBase.filter(s => { if (!isPostDelivery(s.status)) return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); const ebNS = (s.efj || "").replace(/\s/g, ""); return !!(docSummary?.[eb] || docSummary?.[s.efj] || docSummary?.[ebNS])?.pod; }) :
    opsTableFilter === "driver_paid_pending" ? opsBase.filter(s => s.status === "driver_paid") :
    [...STATUSES, ...FTL_STATUSES].some(st => st.key === opsTableFilter && st.key !== "all") ? opsBase.filter(s => s.status === opsTableFilter) :
    opsBase;
  // Apply date picker filters to ops table
  const opsTableShipsDateFiltered = opsTableShips.filter(s => {
    if (puDateFilter) {
      const pu = parseDate(s.pickupDate);
      const target = new Date(puDateFilter + "T00:00:00");
      if (!pu || pu.getFullYear() !== target.getFullYear() || pu.getMonth() !== target.getMonth() || pu.getDate() !== target.getDate()) return false;
    }
    if (delDateFilter) {
      const del = parseDate(s.deliveryDate);
      const target = new Date(delDateFilter + "T00:00:00");
      if (!del || del.getFullYear() !== target.getFullYear() || del.getMonth() !== target.getMonth() || del.getDate() !== target.getDate()) return false;
    }
    return true;
  });

  // Inline edit styles (reuse dispatch pattern)
  const inlineInputStyle = { background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 4, color: "#F0F2F5", padding: "2px 5px", fontSize: 11, width: 90, outline: "none", fontFamily: "'JetBrains Mono', monospace" };
  const thStyle = { padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: Z.table };

  // Total count for toggle badges (both views show same data, different layout)
  const totalCount = displayShipsFiltered.length;

  // Column filter: filtered data + options
  const repColFilterOpts = useMemo(() => buildColFilterOptions(isOps ? opsTableShips : displayShips, trackingSummary), [isOps, opsTableShips, displayShips, trackingSummary]);
  const _applyOldestSort = (arr) => {
    if (!sortOldestFirst) return arr;
    return [...arr].sort((a, b) => {
      const da = a.eta || a.pickupDate || a.deliveryDate || a.efj || "";
      const db = b.eta || b.pickupDate || b.deliveryDate || b.efj || "";
      return da.localeCompare(db);
    });
  };
  const opsDataFiltered = useMemo(() => _applyOldestSort(applyColFilters(opsTableShipsDateFiltered, repColumnFilters, trackingSummary)), [opsTableShipsDateFiltered, repColumnFilters, trackingSummary, sortOldestFirst]);
  const displayDataFiltered = useMemo(() => _applyOldestSort(applyColFilters(displayShips, repColumnFilters, trackingSummary)), [displayShips, repColumnFilters, trackingSummary, sortOldestFirst]);

  // Render a filterable <th> with column dropdown
  const renderFilterTh = (label, extraStyle) => {
    const filterKey = COL_FILTER_KEY_MAP[label];
    const isFilterable = !!filterKey;
    const hasFilter = isFilterable && !!repColumnFilters[filterKey];
    const isOpen = repOpenFilterCol === label;
    const opts = isFilterable ? (repColFilterOpts[filterKey] || []) : [];
    return (
      <th key={label} style={{ ...thStyle, ...extraStyle, position: "relative", zIndex: isOpen ? Z.panelBackdrop : Z.table,
        borderBottom: hasFilter ? "2px solid rgba(0,212,170,0.4)" : thStyle.borderBottom,
        background: hasFilter ? "rgba(0,212,170,0.04)" : thStyle.background,
        color: hasFilter ? "#00D4AA" : thStyle.color }}>
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          <span style={{ flex: 1 }}>{label}</span>
          {isFilterable && (
            <span className="col-filter-dd"
              onClick={e => { e.stopPropagation(); if (isOpen) { setRepOpenFilterCol(null); } else { const rect = e.currentTarget.closest('th').getBoundingClientRect(); setFilterDropdownPos({ top: rect.bottom + 2, left: rect.left }); setRepOpenFilterCol(label); } }}
              style={{ fontSize: 8, color: hasFilter ? "#00D4AA" : "#5A6478", cursor: "pointer",
                padding: "2px 3px", borderRadius: 3, background: hasFilter ? "rgba(0,212,170,0.12)" : "transparent", lineHeight: 1 }}>
              {hasFilter ? "✦" : "▾"}
            </span>
          )}
        </div>
        {isOpen && isFilterable && (
          <div className="col-filter-dd" onClick={e => e.stopPropagation()}
            style={{ position: "fixed", top: filterDropdownPos.top, left: filterDropdownPos.left, zIndex: Z.dropdown, background: "#1A2236",
              border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, minWidth: 150,
              maxHeight: 300, overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
            <div onClick={() => { setRepColumnFilters(f => { const n = {...f}; delete n[filterKey]; return n; }); setRepOpenFilterCol(null); }}
              style={{ padding: "6px 10px", fontSize: 11, color: !hasFilter ? "#00D4AA" : "#8B95A8",
                cursor: "pointer", borderRadius: 4, background: !hasFilter ? "rgba(0,212,170,0.06)" : "transparent", fontWeight: 600 }}>
              All
            </div>
            {opts.map(opt => {
              const val = typeof opt === "object" ? opt.value : opt;
              const lbl = typeof opt === "object" ? opt.label : opt;
              const isActive = repColumnFilters[filterKey] === val;
              return (
                <div key={val} onClick={() => { setRepColumnFilters(f => ({ ...f, [filterKey]: val })); setRepOpenFilterCol(null); }}
                  style={{ padding: "6px 10px", fontSize: 11, color: isActive ? "#00D4AA" : "#F0F2F5",
                    cursor: "pointer", borderRadius: 4, background: isActive ? "rgba(0,212,170,0.08)" : "transparent",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {lbl}
                </div>
              );
            })}
          </div>
        )}
      </th>
    );
  };

  // ── FTL Dispatch Table (shared by master + ops in FTL view) ──
  const renderRowActions = (s, extraTdStyle) => (
    <td style={{ padding: "5px 4px", width: 52, textAlign: "center", ...extraTdStyle }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "center" }}>
        <button onClick={() => handleLoadClick(s)} title="Open details"
          style={{ background: "rgba(0,184,212,0.06)", border: "1px solid rgba(0,184,212,0.12)", color: "#00b8d4", cursor: "pointer", padding: "3px 5px", borderRadius: 6, lineHeight: 1, transition: "all 0.15s", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,184,212,0.18)"; e.currentTarget.style.borderColor = "rgba(0,184,212,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,184,212,0.06)"; e.currentTarget.style.borderColor = "rgba(0,184,212,0.12)"; }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /><path d="M14 9l3 3-3 3" />
          </svg>
        </button>
        <button onClick={(e) => { e.stopPropagation(); setDeleteConfirmEfj(s.efj); }} title="Delete load"
          style={{ background: "transparent", border: "1px solid transparent", color: "#EF4444", cursor: "pointer", padding: "3px 4px", borderRadius: 6, lineHeight: 1, opacity: 0.35, transition: "all 0.15s", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(239,68,68,0.1)"; e.currentTarget.style.borderColor = "rgba(239,68,68,0.3)"; e.currentTarget.style.opacity = "1"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "transparent"; e.currentTarget.style.opacity = "0.35"; }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      </div>
    </td>
  );

  const renderFTLTable = (ships) => {
    const ftlCols = ["", "EFJ #", "Status", "Container/Load #", "MP Status", "Pickup", "Origin", "Destination", "Delivery", "Truck", "Trailer #", "Driver Phone", "Carrier Email", "Rate", "Notes"];
    const filteredShips = applyColFilters(ships, repColumnFilters, trackingSummary);
    return (
      <div className="dash-panel" style={{ overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="dash-panel-title">FTL Dispatch — {filteredShips.length} loads</span>
        </div>
        <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>{ftlCols.map(h => renderFilterTh(h))}</tr>
            </thead>
            <tbody>
              {filteredShips.map((s) => {
                const sc = (isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS)[s.status] || { main: "#94a3b8" };
                const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                const tracking = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
                const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                const pu = splitDateTime(s.pickupDate);
                const del = splitDateTime(s.deliveryDate);
                const isEditing = inlineEditId === s.id;
                const cellBorder = "1px solid rgba(255,255,255,0.04)";
                const tdBase = { padding: "5px 8px", borderBottom: "1px solid rgba(255,255,255,0.06)", borderRight: cellBorder };
                const repTermInfo = parseTerminalNotes(s.botAlert);
                const repTermBg = repTermInfo?.isReady ? "rgba(34,197,94,0.06)" : repTermInfo?.hasHolds ? "rgba(239,68,68,0.05)" : undefined;
                const dispMarginPct = calcMarginPct(s.customerRate, s.carrierPay);
                const rowBg = (dispMarginPct !== null && dispMarginPct < 10) ? "rgba(239,68,68,0.10)" : repTermBg;
                return (
                  <tr key={s.id} className={`row-hover${highlightedEfj === s.efj ? " row-highlight-pulse" : ""}`}
                    style={{ cursor: "default", borderBottom: "1px solid rgba(255,255,255,0.02)", background: highlightedEfj === s.efj ? undefined : rowBg }}>
                    {renderRowActions(s, { borderBottom: tdBase.borderBottom, borderRight: tdBase.borderRight })}
                    {/* EFJ # (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("efj"); setInlineEditValue(s.efj || ""); }}>
                      {isEditing && inlineEditField === "efj" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleFieldUpdate(s, "efj", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 85, fontWeight: 600, color: "#00D4AA" }} onClick={e => e.stopPropagation()} />
                      ) : (
                      <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11, cursor: "text" }}>{s.loadNumber}</span>
                        <DocIndicators docs={docs} />
                        {parseTerminalNotes(s.botAlert)?.hasHolds && (
                          <span title={s.botAlert} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 14, height: 14, background: "#EF4444", borderRadius: 3, animation: "alert-pulse 1.8s ease-in-out infinite", flexShrink: 0, cursor: "default" }}>
                            <svg viewBox="0 0 24 24" fill="white" style={{ width: 9, height: 9 }}><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>
                          </span>
                        )}
                      </div>
                      )}
                    </td>
                    {/* Status (inline-editable) */}
                    <td style={{ ...tdBase, position: "relative" }}
                      onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                      {isEditing && inlineEditField === "status" ? (
                        <div style={{ position: "absolute", top: "100%", left: 0, zIndex: Z.inlineEdit, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 280, overflowY: "auto", minWidth: 120 }} className="inline-status-dd">
                          {getStatusesForShipment(s).filter(st => st.key !== "all").map(st => {
                            const stc = getStatusColors(s)[st.key] || { main: "#94a3b8" };
                            return (
                              <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                  background: s.status === st.key ? `${stc.main}18` : "transparent",
                                  color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                {st.label}
                              </button>
                            );
                          })}
                          <div style={{ height: 1, background: "rgba(255,255,255,0.08)", margin: "4px 0" }} />
                          <div style={{ fontSize: 8, fontWeight: 700, color: "#5A6478", letterSpacing: "1.5px", padding: "2px 7px", textTransform: "uppercase" }}>Billing</div>
                          {BILLING_STATUSES.map(st => {
                            const stc = BILLING_STATUS_COLORS[st.key] || { main: "#94a3b8" };
                            return (
                              <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                  background: s.status === st.key ? `${stc.main}18` : "transparent",
                                  color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                {st.label}
                              </button>
                            );
                          })}
                          <button onClick={(e) => { e.stopPropagation(); setInlineEditId(null); }}
                            style={{ display: "block", width: "100%", padding: "3px 7px", marginTop: 2, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.03)", color: "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                        </div>
                      ) : null}
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700,
                        color: sc.main, background: `${sc.main}0D`, border: `1px solid ${sc.main}18`, textTransform: "uppercase", cursor: "pointer", whiteSpace: "nowrap" }}>
                        <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                        {resolveStatusLabel(s)}
                      </span>
                    </td>
                    {/* Container/Load # (inline-editable) */}
                    <td style={{ ...tdBase, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#F0F2F5" }}
                      onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("container"); setInlineEditValue(s.container || ""); }}>
                      {isEditing && inlineEditField === "container" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleFieldUpdate(s, "container", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                      ) : (
                        <span style={{ cursor: "text" }}>{s.container || "\u2014"}</span>
                      )}
                    </td>
                    {/* MP Status */}
                    <td style={tdBase}>
                      {(s.moveType === "FTL" || s.mpStatus || s.mpDisplayStatus || tracking?.mpDisplayStatus || tracking?.status) ? <TrackingBadge tracking={tracking} mpStatus={s.mpStatus || tracking?.mpStatus} mpDisplayStatus={s.mpDisplayStatus || tracking?.mpDisplayStatus} mpDisplayDetail={s.mpDisplayDetail || tracking?.mpDisplayDetail} mpLastUpdated={s.mpLastUpdated} /> : <span style={{ color: "#5A6478", fontSize: 11, fontStyle: "italic" }}>No MP</span>}
                    </td>
                    {/* Pickup (inline-editable, DD-MM + time) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                      {isEditing && inlineEditField === "pickup" ? (
                        <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : isEditing && inlineEditField === "pickupTime" ? (
                        <div onClick={e => e.stopPropagation()}>
                          <input type="text" autoFocus placeholder="1400" maxLength={7} value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const norm = normalizeTimeInput(inlineEditValue); const v = (pu.date || "") + " " + norm; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 58, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                          <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                          {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                        </span>
                      )}
                    </td>
                    {/* Origin (inline-editable) */}
                    <td style={{ ...tdBase, fontSize: 11, color: "#F0F2F5", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.origin}
                      onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("origin"); setInlineEditValue(s.origin || ""); }}>
                      {isEditing && inlineEditField === "origin" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleFieldUpdate(s, "origin", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                      ) : (
                        <span style={{ cursor: "text" }}>{s.origin || "\u2014"}</span>
                      )}
                    </td>
                    {/* Destination (inline-editable) */}
                    <td style={{ ...tdBase, fontSize: 11, color: "#F0F2F5", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.destination}
                      onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("destination"); setInlineEditValue(s.destination || ""); }}>
                      {isEditing && inlineEditField === "destination" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleFieldUpdate(s, "destination", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                      ) : (
                        <span style={{ cursor: "text" }}>{s.destination || "\u2014"}</span>
                      )}
                    </td>
                    {/* Delivery (inline-editable, DD-MM + time) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                      {isEditing && inlineEditField === "delivery" ? (
                        <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : isEditing && inlineEditField === "deliveryTime" ? (
                        <div onClick={e => e.stopPropagation()}>
                          <input type="text" autoFocus placeholder="1400" maxLength={7} value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const norm = normalizeTimeInput(inlineEditValue); const v = (del.date || "") + " " + norm; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 58, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                          <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                          {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                        </span>
                      )}
                    </td>
                    {/* Truck Type (inline-editable dropdown) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("truckType"); setInlineEditValue(s.truckType || ""); }}>
                      {isEditing && inlineEditField === "truckType" ? (
                        <select autoFocus value={inlineEditValue}
                          onChange={e => { const v = e.target.value; setInlineEditValue(v); handleMetadataUpdate(s, "truckType", v); setInlineEditId(null); }}
                          onBlur={() => setInlineEditId(null)} onKeyDown={e => { if (e.key === "Escape") setInlineEditId(null); }}
                          onClick={e => e.stopPropagation()} style={{ ...inlineInputStyle, width: 80, cursor: "pointer" }}>
                          {TRUCK_TYPES.map(t => <option key={t} value={t}>{t || "\u2014"}</option>)}
                        </select>
                      ) : (
                        <span style={{ fontSize: 11, color: s.truckType ? "#F0F2F5" : "#3D4557", cursor: "pointer" }}>{s.truckType || "\u2014"}</span>
                      )}
                    </td>
                    {/* Trailer # (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("trailer"); setInlineEditValue(s.trailerNumber || tracking?.trailer || ""); }}>
                      {isEditing && inlineEditField === "trailer" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "trailer", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 70 }} onClick={e => e.stopPropagation()} placeholder="Trailer" />
                      ) : (
                        <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>{s.trailerNumber || tracking?.trailer || "\u2014"}</span>
                      )}
                    </td>
                    {/* Driver Phone (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("driverPhone"); setInlineEditValue(s.driverPhone || tracking?.driverPhone || ""); }}>
                      {isEditing && inlineEditField === "driverPhone" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "driverPhone", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} placeholder="Phone" />
                      ) : (
                        <span style={{ fontSize: 11, color: (s.driverPhone || tracking?.driverPhone) ? "#F0F2F5" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>{s.driverPhone || tracking?.driverPhone || "\u2014"}</span>
                      )}
                    </td>
                    {/* Carrier Email (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrierEmail"); setInlineEditValue(s.carrierEmail || ""); }}>
                      {isEditing && inlineEditField === "carrierEmail" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "carrierEmail", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="email@carrier.com" />
                      ) : (
                        <span style={{ fontSize: 11, color: s.carrierEmail ? "#8B95A8" : "#3D4557", maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.carrierEmail || ""}>{s.carrierEmail || "\u2014"}</span>
                      )}
                    </td>
                    {/* Rate (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("customerRate"); setInlineEditValue(s.customerRate || ""); }}>
                      {isEditing && inlineEditField === "customerRate" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleMetadataUpdate(s, "customerRate", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 65 }} onClick={e => e.stopPropagation()} placeholder="$0.00" />
                      ) : (
                        <span style={{ fontSize: 11, color: s.customerRate ? "#22C55E" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", fontWeight: s.customerRate ? 600 : 400 }}>{s.customerRate || "\u2014"}</span>
                      )}
                    </td>
                    {/* Margin (MGN) — color-coded */}
                    <td style={{ ...tdBase, textAlign: "center" }}>
                      {dispMarginPct !== null ? (
                        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
                          color: dispMarginPct < 0 ? "#EF4444" : dispMarginPct < 10 ? "#F59E0B" : "#22C55E" }}
                          title={`$${Math.round(parseFloat(s.customerRate) - parseFloat(s.carrierPay))} margin`}>
                          {dispMarginPct}%
                        </span>
                      ) : <span style={{ color: "#3D4557", fontSize: 11 }}>{"\u2014"}</span>}
                    </td>
                    {/* Notes (inline-editable) */}
                    <td style={{ ...tdBase, borderRight: "none" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("notes"); setInlineEditValue(s.notes || ""); }}>
                      {isEditing && inlineEditField === "notes" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleMetadataUpdate(s, "notes", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="Add note..." />
                      ) : parseTerminalNotes(s.botAlert) ? (
                        <TerminalBadge notes={s.notes} />
                      ) : (
                        <span style={{ fontSize: 11, color: s.notes ? "#F0F2F5" : "#3D4557", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.notes || ""}>{s.notes || "\u2014"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filteredShips.length === 0 && (
            <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>No FTL loads found</div>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div style={{ animation: "fade-in 0.4s ease" }}>
      {/* Back button + View toggle + header */}
      <div style={{ padding: "16px 0 8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <button onClick={onBack} style={{ background: "none", border: "1px solid rgba(255,255,255,0.06)", color: "#8B95A8", padding: "6px 10px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>{"\u2190"}</button>
          <div style={{ display: "flex", background: "#0D1119", borderRadius: 10, padding: 3, gap: 2, border: "1px solid rgba(255,255,255,0.06)" }}>
            <button onClick={() => setRepViewMode("dray")}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: repViewMode === "dray" ? "#1E2738" : "transparent", color: repViewMode === "dray" ? "#00D4AA" : "#5A6478",
                boxShadow: repViewMode === "dray" ? "0 1px 4px rgba(0,0,0,0.3)" : "none", transition: "all 0.15s" }}>
              Dray View <span style={{ fontSize: 11, opacity: 0.6, marginLeft: 3 }}>{totalCount}</span>
            </button>
            <button onClick={() => setRepViewMode("ftl")}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: repViewMode === "ftl" ? "#1E2738" : "transparent", color: repViewMode === "ftl" ? "#3B82F6" : "#5A6478",
                boxShadow: repViewMode === "ftl" ? "0 1px 4px rgba(0,0,0,0.3)" : "none", transition: "all 0.15s" }}>
              FTL View <span style={{ fontSize: 11, opacity: 0.6, marginLeft: 3 }}>{totalCount}</span>
            </button>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
          <div style={{ position: "relative", cursor: "pointer" }} onClick={() => { const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*,.pdf"; inp.onchange = async (e) => { const file = e.target.files[0]; if (!file) return; const fd = new FormData(); fd.append("file", file); try { const res = await apiFetch(`${API_BASE}/api/team/${repName}/avatar`, { method: "POST", body: fd }); if (res.ok) { if (onProfileUpdate) onProfileUpdate(); } else { const err = await res.json().catch(() => ({})); alert(err.error || "Upload failed"); } } catch (ex) { console.error("Avatar upload error:", ex); alert("Upload failed \u2014 check connection"); } }; inp.click(); }}>
            {repProfiles?.[repName]?.avatar_url ? (
              <img src={`${API_BASE}${repProfiles[repName].avatar_url}?t=${Date.now()}`} alt={repName}
                style={{ width: 56, height: 56, borderRadius: "50%", objectFit: "cover", border: `2px solid ${color}44` }} />
            ) : (
              <div style={{ width: 56, height: 56, borderRadius: "50%", background: `${color}18`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 800, color, border: `2px solid ${color}44` }}>
                {repName.slice(0, 2).toUpperCase()}
              </div>
            )}
            <div style={{ position: "absolute", bottom: 0, right: 0, width: 18, height: 18, borderRadius: "50%", background: "#1A2236", border: "1px solid rgba(255,255,255,0.15)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#8B95A8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>{repName}</h2>
            <div style={{ fontSize: 11, color: "#8B95A8" }}>
              {isMaster ? `Track/Tracing Master \u2014 ${(REP_ACCOUNTS[repName] || []).length} accounts` : isBoviet ? "Boviet Solar Projects" : "Tolead Operations"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
            {onRefresh && (
              <button onClick={onRefresh} title="Refresh data"
                style={{ background: "none", border: "1px solid rgba(255,255,255,0.06)", color: "#8B95A8", padding: "7px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 4 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
              </button>
            )}
            {onAddLoad && (
              <button onClick={onAddLoad} className="btn-primary"
                style={{ border: "none", borderRadius: 10, padding: "9px 20px", fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#fff", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
                <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Load
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Action Summary — unified pills for all views (Active first) */}
      {(() => {
        const filterState = isOps ? opsTableFilter : masterTableFilter;
        const setFilter = isOps ? setOpsTableFilter : (f) => setMasterTableFilter(masterTableFilter === f ? "all" : f);
        const pills = [
          { label: "Active", value: actionActive.length, c: "#3B82F6", filter: "active" },
          { label: "PU Today", value: actionPuToday.length, c: "#F59E0B", filter: "pu_today" },
          { label: "PU Tmrw", value: actionPuTmrw.length, c: "#00A8CC", filter: "pu_tomorrow" },
          { label: "DEL Today", value: actionDelToday.length, c: "#22C55E", filter: "del_today" },
          { label: "DEL Tmrw", value: actionDelTmrw.length, c: "#10B981", filter: "del_tomorrow" },
          { label: "No Driver", value: actionNoDriver.length, c: "#EF4444", filter: "needs_driver" },
          { label: "Behind", value: actionBehind.length, c: "#F97316", filter: "behind" },
          { label: "No POD", value: actionNoPod.length, c: "#A855F7", filter: "awaiting_pod" },
          { label: "FTL Only", value: actionFtlOnly.length, c: "#60A5FA", filter: "ftl_only" },
          { label: "Ready to Bill", value: actionReadyBilling.length, c: "#F59E0B", filter: "ready_billing" },
          { label: "Paid Pending CX", value: actionDriverPaidPending.length, c: "#06B6D4", filter: "driver_paid_pending" },
          { label: "Rate Responses", value: inboxRateResponses, c: "#00D4AA", filter: null, action: () => onNavigateInbox("rates", "carrier_rate_response") },
        ];
        const repNeedsReplyThreads = repInboxThreads.filter(t => t.needs_reply && t.email_type !== "rate_outreach");
        return (
        <div style={{ display: "flex", gap: 6, marginBottom: 14, marginTop: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
          {pills.map((s, i) => (
            <button key={i} onClick={() => { if (s.filter) setFilter(s.filter); else if (s.action) s.action(); }}
              style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${filterState === s.filter && s.filter ? `${s.c}44` : "rgba(255,255,255,0.06)"}`,
                background: filterState === s.filter && s.filter ? `${s.c}15` : "rgba(255,255,255,0.03)",
                cursor: s.filter || s.action ? "pointer" : "default", display: "flex", alignItems: "center", gap: 6, fontFamily: "inherit" }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: s.value > 0 ? s.c : "#334155", fontFamily: "'JetBrains Mono', monospace" }}>{s.value}</span>
              <span style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase" }}>{s.label}</span>
            </button>
          ))}
          {/* Needs Reply — special popover pill */}
          <div style={{ position: "relative" }}>
            <button onClick={() => setNeedsReplyOpen(v => !v)}
              style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${needsReplyOpen ? "rgba(239,68,68,0.4)" : inboxNeedsReply > 0 ? "rgba(239,68,68,0.25)" : "rgba(255,255,255,0.06)"}`,
                background: needsReplyOpen ? "rgba(239,68,68,0.12)" : inboxNeedsReply > 0 ? "rgba(239,68,68,0.06)" : "rgba(255,255,255,0.03)",
                cursor: "pointer", display: "flex", alignItems: "center", gap: 6, fontFamily: "inherit" }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: inboxNeedsReply > 0 ? "#EF4444" : "#334155", fontFamily: "'JetBrains Mono', monospace" }}>{inboxNeedsReply}</span>
              <span style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase" }}>Needs Reply</span>
              <span style={{ fontSize: 8, color: "#5A6478" }}>{needsReplyOpen ? "▲" : "▼"}</span>
            </button>
            {needsReplyOpen && (
              <div onMouseLeave={() => setNeedsReplyOpen(false)}
                style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 999, background: "#141A28", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 10, padding: 6, minWidth: 320, maxWidth: 400, boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
                {repNeedsReplyThreads.length === 0 ? (
                  <div style={{ padding: "8px 10px", fontSize: 11, color: "#5A6478" }}>No threads need reply</div>
                ) : repNeedsReplyThreads.map((t, ti) => {
                  const matchShip = shipments.find(sh => {
                    if (!t.efj) return false;
                    const te = t.efj.replace(/^EFJ\s*/i, "");
                    return sh.efj === t.efj || sh.efj?.replace(/^EFJ\s*/i, "") === te;
                  });
                  return (
                    <div key={ti}
                      onClick={() => { if (matchShip) { handleLoadClick(matchShip, { expandEmails: true, highlight: true }); setNeedsReplyOpen(false); } else { onNavigateInbox("needs_reply"); setNeedsReplyOpen(false); } }}
                      style={{ padding: "7px 10px", borderRadius: 7, cursor: "pointer", display: "flex", alignItems: "center", gap: 8, marginBottom: 2,
                        background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.04)" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(239,68,68,0.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}>
                      {t.efj ? (
                        <span style={{ padding: "1px 5px", borderRadius: 3, background: "rgba(0,212,170,0.10)", color: "#00D4AA", fontWeight: 700, fontSize: 11, fontFamily: "JetBrains Mono, monospace", flexShrink: 0 }}>{t.efj}</span>
                      ) : (
                        <span style={{ padding: "1px 5px", borderRadius: 3, background: "rgba(249,115,22,0.10)", color: "#F97316", fontWeight: 700, fontSize: 11, flexShrink: 0 }}>UNMATCHED</span>
                      )}
                      <span style={{ fontSize: 11, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }} title={t.latest_subject}>{t.latest_subject || "(no subject)"}</span>
                      <span style={{ fontSize: 11, color: "#5A6478", flexShrink: 0 }}>{(t.latest_sender || "").replace(/<[^>]+>/g, "").split("@")[0]}</span>
                    </div>
                  );
                })}
                <div onClick={() => { onNavigateInbox("needs_reply"); setNeedsReplyOpen(false); }}
                  style={{ padding: "6px 10px", borderRadius: 6, cursor: "pointer", marginTop: 4, fontSize: 11, color: "#8B95A8", fontWeight: 600, display: "flex", alignItems: "center", gap: 4, borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 8 }}
                  onMouseEnter={e => e.currentTarget.style.color = "#F0F2F5"}
                  onMouseLeave={e => e.currentTarget.style.color = "#8B95A8"}>
                  → View all in Inbox
                </div>
              </div>
            )}
          </div>
        </div>
        );
      })()}

      {/* Status Filter Dropdown */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
        {(() => {
          const filterState = isOps ? opsTableFilter : masterTableFilter;
          const setFilter = isOps ? setOpsTableFilter : setMasterTableFilter;
          const statusList = repViewMode === "ftl" ? FTL_STATUSES : (isOps ? FTL_STATUSES : STATUSES);
          const isStatusFilter = [...STATUSES, ...FTL_STATUSES].some(st => st.key === filterState && st.key !== "all");
          return (
            <select value={isStatusFilter ? filterState : ""} onChange={e => setFilter(e.target.value || "all")}
              style={{ padding: "7px 12px", background: isStatusFilter ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${isStatusFilter ? "rgba(59,130,246,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 10, color: isStatusFilter ? "#60A5FA" : "#8B95A8", fontSize: 11, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 600 }}>
              <option value="" style={{ background: "#0D1119" }}>Filter by Status</option>
              {statusList.filter(s => s.key !== "all").map(s => <option key={s.key} value={s.key} style={{ background: "#0D1119" }}>{s.label}</option>)}
            </select>
          );
        })()}
        {(() => {
          const filterState = isOps ? opsTableFilter : masterTableFilter;
          const setFilter = isOps ? setOpsTableFilter : setMasterTableFilter;
          if (filterState === "all" && Object.keys(repColumnFilters).length === 0) return null;
          return (
            <button onClick={() => { setFilter("all"); setRepColumnFilters({}); setRepOpenFilterCol(null); }}
              style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.15)", background: "rgba(239,68,68,0.08)", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              ✕ Clear
            </button>
          );
        })()}
        <button onClick={() => setSortOldestFirst(v => !v)}
          title={sortOldestFirst ? "Sorted: oldest ETA first" : "Sort: oldest first"}
          style={{ padding: "5px 10px", borderRadius: 6, border: `1px solid ${sortOldestFirst ? "rgba(245,158,11,0.3)" : "rgba(255,255,255,0.06)"}`, background: sortOldestFirst ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.03)", color: sortOldestFirst ? "#F59E0B" : "#5A6478", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", display: "flex", alignItems: "center", gap: 4 }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M7 12h10M11 18h2"/></svg>
          {sortOldestFirst ? "Oldest First" : "Sort"}
        </button>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginLeft: 8 }}>
          <label style={{ fontSize: 11, color: "#5A6478", fontWeight: 600 }}>PU:</label>
          <input type="date" value={puDateFilter} onChange={e => setPuDateFilter(e.target.value)}
            style={{ padding: "5px 8px", background: puDateFilter ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${puDateFilter ? "rgba(245,158,11,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 6, color: puDateFilter ? "#F59E0B" : "#8B95A8", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", cursor: "pointer", colorScheme: "dark" }} />
          <label style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginLeft: 4 }}>DEL:</label>
          <input type="date" value={delDateFilter} onChange={e => setDelDateFilter(e.target.value)}
            style={{ padding: "5px 8px", background: delDateFilter ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${delDateFilter ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 6, color: delDateFilter ? "#22C55E" : "#8B95A8", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", cursor: "pointer", colorScheme: "dark" }} />
          {(puDateFilter || delDateFilter) && (
            <button onClick={() => { setPuDateFilter(""); setDelDateFilter(""); }}
              style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid rgba(239,68,68,0.15)", background: "rgba(239,68,68,0.08)", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              Clear dates
            </button>
          )}
        </div>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#8B95A8", fontWeight: 600 }}>
          {(isOps ? opsDataFiltered : displayDataFiltered).length} {(isOps ? opsDataFiltered : displayDataFiltered).length === 1 ? "load" : "loads"}
        </span>
      </div>

      {/* Boviet project tabs */}
      {isBoviet && (
        <div style={{ display: "flex", gap: 2, marginBottom: 14, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, width: "fit-content" }}>
          {["All", "Piedra", "Hanson", "Other"].map(t => (
            <button key={t} onClick={() => setBovietTab(t)}
              style={{ padding: "6px 16px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: bovietTab === t ? "rgba(139,92,246,0.15)" : "transparent",
                color: bovietTab === t ? "#a78bfa" : "#8B95A8" }}>
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Boviet Project Cards — summary stats per project */}
      {isBoviet && (() => {
        const projects = ["Piedra", "Hanson", "Other"];
        return (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10, marginBottom: 14 }}>
            {projects.map(proj => {
              const projShips = repShipments.filter(s => {
                const hub = (s.hub || "").toLowerCase();
                if (proj === "Other") return !hub || (hub !== "piedra" && hub !== "hanson");
                return hub === proj.toLowerCase();
              });
              const active = projShips.filter(s => !isPostDelivery(s.status) && s.status !== "cancelled").length;
              const delivered = projShips.filter(s => isPostDelivery(s.status)).length;
              const pending = projShips.filter(s => ["pending", "booked", "confirmed"].includes(s.status)).length;
              const today = new Date().toISOString().slice(0, 10);
              const pickupsToday = projShips.filter(s => (s.pickupDate || "").startsWith(today)).length;
              const carriers = new Set(projShips.map(s => s.carrier).filter(Boolean)).size;
              const lastDel = projShips.filter(s => s.deliveryDate).sort((a, b) => b.deliveryDate.localeCompare(a.deliveryDate))[0];
              const isSel = bovietTab === proj;
              return (
                <div key={proj} onClick={() => setBovietTab(proj)}
                  style={{ padding: "14px 16px", borderRadius: 10, cursor: "pointer",
                    background: isSel ? "rgba(139,92,246,0.06)" : "rgba(255,255,255,0.02)",
                    border: `1px solid ${isSel ? "rgba(139,92,246,0.20)" : "rgba(255,255,255,0.06)"}`,
                    transition: "all 0.15s" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 800, color: isSel ? "#A78BFA" : "#F0F2F5" }}>{proj}</span>
                    <span style={{ fontSize: 18, fontWeight: 900, color: "#A78BFA", fontFamily: "'JetBrains Mono', monospace" }}>{projShips.length}</span>
                  </div>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 11 }}><span style={{ fontWeight: 700, color: "#3B82F6" }}>{active}</span> <span style={{ color: "#5A6478" }}>active</span></div>
                    <div style={{ fontSize: 11 }}><span style={{ fontWeight: 700, color: "#22C55E" }}>{delivered}</span> <span style={{ color: "#5A6478" }}>delivered</span></div>
                    <div style={{ fontSize: 11 }}><span style={{ fontWeight: 700, color: "#F59E0B" }}>{pending}</span> <span style={{ color: "#5A6478" }}>pending</span></div>
                  </div>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6 }}>
                    {pickupsToday > 0 && <div style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: "rgba(59,130,246,0.10)", color: "#3B82F6", fontWeight: 700 }}>{pickupsToday} pickup{pickupsToday > 1 ? "s" : ""} today</div>}
                    <div style={{ fontSize: 11, color: "#5A6478" }}>{carriers} carrier{carriers !== 1 ? "s" : ""}</div>
                    {lastDel && <div style={{ fontSize: 11, color: "#5A6478" }}>Last delivery: {lastDel.deliveryDate?.slice(0, 10)}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* Tolead hub tabs */}
      {isTolead && (
        <div style={{ display: "flex", gap: 2, marginBottom: 14, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, width: "fit-content" }}>
          {["All", "ORD", "JFK", "LAX", "DFW"].map(h => {
            const hubCount = h === "All" ? repShipments.length : repShipments.filter(s => (s.hub || "ORD") === h).length;
            return (
              <button key={h} onClick={() => setToleadHub(h)}
                style={{ padding: "6px 16px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                  background: toleadHub === h ? "rgba(6,182,212,0.15)" : "transparent",
                  color: toleadHub === h ? "#22d3ee" : "#8B95A8" }}>
                {h} <span style={{ fontSize: 11, opacity: 0.6, marginLeft: 2 }}>{hubCount}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Master reps: Account cards (only in dray view) */}
      {isMaster && repViewMode === "dray" && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Accounts</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
            {accountGroups.map(ag => (
              <div key={ag.name} className="acct-card"
                onClick={() => setExpandedAccount(expandedAccount === ag.name ? null : ag.name)}
                style={{ padding: "10px 14px", borderRadius: 10, background: expandedAccount === ag.name ? "rgba(0,212,170,0.06)" : "rgba(255,255,255,0.02)",
                  border: `1px solid ${expandedAccount === ag.name ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.04)"}` }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", marginBottom: 6 }}>{ag.name}</div>
                <div style={{ display: "flex", gap: 8, fontSize: 11, flexWrap: "wrap" }}>
                  {ag.incoming > 0 && <span style={{ color: "#F59E0B" }}>{ag.incoming} <span style={{ color: "#8B95A8" }}>in</span></span>}
                  {ag.active > 0 && <span style={{ color: "#3B82F6" }}>{ag.active} <span style={{ color: "#8B95A8" }}>active</span></span>}
                  {ag.behind > 0 && <span style={{ color: "#EF4444" }}>{ag.behind} <span style={{ color: "#8B95A8" }}>behind</span></span>}
                  <span style={{ color: "#22C55E" }}>{ag.delivered} <span style={{ color: "#8B95A8" }}>done</span></span>
                </div>
              </div>
            ))}
          </div>
          {expandedAccount && (
            <div style={{ fontSize: 11, color: "#00D4AA", fontWeight: 600, marginTop: 8, padding: "4px 0" }}>
              Showing: {expandedAccount} <span style={{ cursor: "pointer", color: "#8B95A8", marginLeft: 8 }} onClick={() => setExpandedAccount(null)}>{"\u00d7"} clear</span>
            </div>
          )}
        </div>
      )}

      {/* ── FTL View: full dispatch table ── */}
      {repViewMode === "ftl" && renderFTLTable(isOps ? opsTableShipsDateFiltered : displayShips)}

      {/* ── Dray View: Operations Dashboard — Boviet/Tolead ── */}
      {repViewMode === "dray" && isOps && (<>
        {/* FTL loads use the same FTL dispatch table as FTL view for uniform columns */}
        {(() => { const ftlLoads = opsDataFiltered.filter(s => s.moveType === "FTL"); return ftlLoads.length > 0 ? renderFTLTable(ftlLoads) : null; })()}

        {/* Non-FTL (dray) loads use dray-oriented columns */}
        {(() => { const drayLoads = opsDataFiltered.filter(s => s.moveType !== "FTL"); return drayLoads.length > 0 ? (
        <div className="dash-panel" style={{ overflow: "hidden", marginTop: opsDataFiltered.some(s => s.moveType === "FTL") ? 14 : 0 }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="dash-panel-title">
              {isBoviet ? (bovietTab === "All" ? "All Projects" : bovietTab) : (toleadHub === "All" ? "All Hubs" : `${toleadHub} Hub`)} {"\u2014"} {drayLoads.length} Dray {drayLoads.length === 1 ? "Load" : "Loads"}
            </span>
            {opsTableFilter !== "all" && (
              <button onClick={() => setOpsTableFilter("all")}
                style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", color: "#8B95A8" }}>
                Show All
              </button>
            )}
          </div>
          <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["", "EFJ #", "Container/Load #", "Type", "Carrier", "Origin \u2192 Dest", "ETA/ERD", "PU", "DEL", "Driver", "Status"].map(h => renderFilterTh(h))}
                </tr>
              </thead>
              <tbody>
                {drayLoads.map((s) => {
                  const sc = STATUS_COLORS[s.status] || { main: "#94a3b8" };
                  const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                  const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                  const isFTL = s.moveType === "FTL";
                  const pu = splitDateTime(s.pickupDate);
                  const del = splitDateTime(s.deliveryDate);
                  const isEditing = inlineEditId === s.id;
                  const repDrayMarginPct = calcMarginPct(s.customerRate, s.carrierPay);
                  return (
                    <tr key={s.id} className={`row-hover${highlightedEfj === s.efj ? " row-highlight-pulse" : ""}`}
                      style={{ cursor: "default", borderBottom: "1px solid rgba(255,255,255,0.02)", background: highlightedEfj === s.efj ? undefined : (repDrayMarginPct !== null && repDrayMarginPct < 10 ? "rgba(239,68,68,0.10)" : undefined) }}>
                      {renderRowActions(s)}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("efj"); setInlineEditValue(s.efj || ""); }}>
                        {isEditing && inlineEditField === "efj" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "efj", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 85, fontWeight: 600, color: "#00D4AA" }} onClick={e => e.stopPropagation()} />
                        ) : (
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11, cursor: "text" }}>{s.loadNumber}</span>
                          <DocIndicators docs={docs} />
                          {s.botAlert && s.botAlert.includes("HOLD") && (
                            <span title={s.botAlert} style={{ fontSize: 8, fontWeight: 700, padding: "1px 4px", borderRadius: 3, background: "rgba(239,68,68,0.15)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.35)", letterSpacing: "0.3px", animation: "alert-pulse 1.8s ease-in-out infinite", cursor: "default" }}>HOLD</span>
                          )}
                        </div>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#F0F2F5" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("container"); setInlineEditValue(s.container || ""); }}>
                        {isEditing && inlineEditField === "container" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "container", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ cursor: "text" }}>{s.container || "\u2014"}</span>
                        )}
                      </td>
                      {/* Move Type */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          color: isFTL ? "#60A5FA" : "#F59E0B", background: isFTL ? "#60A5FA12" : "#F59E0B12",
                          border: `1px solid ${isFTL ? "#60A5FA22" : "#F59E0B22"}`, textTransform: "uppercase" }}>
                          {s.moveType || "Dray"}
                        </span>
                      </td>
                      <td style={{ padding: "8px 14px", fontSize: 11, color: "#F0F2F5" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrier"); setInlineEditValue(s.carrier || ""); }}>
                        {isEditing && inlineEditField === "carrier" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "carrier", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 90 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ cursor: "text" }}>{s.carrier || "\u2014"}</span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px", fontSize: 11 }}>
                        <span style={{ color: "#F0F2F5", cursor: "text" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("origin"); setInlineEditValue(s.origin || ""); }}>
                          {isEditing && inlineEditField === "origin" ? (
                            <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { handleFieldUpdate(s, "origin", inlineEditValue); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} />
                          ) : (s.origin || "\u2014")}
                        </span>
                        <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                        <span style={{ color: "#F0F2F5", cursor: "text" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("destination"); setInlineEditValue(s.destination || ""); }}>
                          {isEditing && inlineEditField === "destination" ? (
                            <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { handleFieldUpdate(s, "destination", inlineEditValue); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} />
                          ) : (s.destination || "\u2014")}
                        </span>
                      </td>
                      {/* ETA/ERD (inline-editable) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("eta"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "eta" ? (
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "eta", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) handleFieldUpdate(s, "eta", parsed); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>
                            {formatDDMM(s.eta || s.lfd) || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}
                          </span>
                        )}
                      </td>
                      {/* PU Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "pickup" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "pickupTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                            {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                          </span>
                        )}
                      </td>
                      {/* DEL Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "delivery" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "deliveryTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                            {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px", fontSize: 11, color: "#8B95A8", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("driver"); setInlineEditValue(s.driver || ""); }}>
                        {isEditing && inlineEditField === "driver" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "driver", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 90 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ cursor: "text" }}>{s.driver || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}</span>
                        )}
                      </td>
                      {/* Status (inline-editable dropdown) */}
                      <td style={{ padding: "8px 14px", position: "relative" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                        {isEditing && inlineEditField === "status" ? (
                          <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 9999, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 280, overflowY: "auto", minWidth: 120 }} className="inline-status-dd">
                            {getStatusesForShipment(s).filter(st => st.key !== "all").map(st => {
                              const stc = getStatusColors(s)[st.key] || { main: "#94a3b8" };
                              return (
                                <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                  style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                    background: s.status === st.key ? `${stc.main}18` : "transparent",
                                    color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                  <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                  {st.label}
                                </button>
                              );
                            })}
                            <button onClick={(e) => { e.stopPropagation(); setInlineEditId(null); }}
                              style={{ display: "block", width: "100%", padding: "3px 7px", marginTop: 2, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.03)", color: "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                          </div>
                        ) : null}
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 11, fontWeight: 700,
                          color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase", cursor: "pointer" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                          {STATUSES.find(st => st.key === s.status)?.label || s.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {drayLoads.length === 0 && (
              <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
                <div style={{ fontSize: 11, fontWeight: 600 }}>No dray loads found</div>
              </div>
            )}
          </div>
        </div>
        ) : null; })()}
        {/* Show empty state only when no loads at all */}
        {opsDataFiltered.length === 0 && (
          <div className="dash-panel" style={{ overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              <span className="dash-panel-title">
                {isBoviet ? (bovietTab === "All" ? "All Projects" : bovietTab) : (toleadHub === "All" ? "All Hubs" : `${toleadHub} Hub`)} {"\u2014"} 0 Loads
              </span>
            </div>
            <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>No loads found</div>
            </div>
          </div>
        )}
      </>)}

      {/* ── Dray View: Shipment table — master reps ── */}
      {repViewMode === "dray" && isMaster && (<>
      {/* FTL loads use uniform FTL dispatch table */}
      {(() => { const masterFtlLoads = displayDataFiltered.filter(s => s.moveType === "FTL"); return masterFtlLoads.length > 0 ? renderFTLTable(masterFtlLoads) : null; })()}

      {/* Non-FTL (dray) loads */}
      {(() => { const masterDrayLoads = displayDataFiltered.filter(s => s.moveType !== "FTL"); return masterDrayLoads.length > 0 ? (
      <div className="dash-panel" style={{ overflow: "hidden", marginTop: displayDataFiltered.some(s => s.moveType === "FTL") ? 14 : 0 }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="dash-panel-title">
            {expandedAccount || "All Accounts"} {"\u2014"} {masterDrayLoads.length} Dray {masterDrayLoads.length === 1 ? "Load" : "Loads"}
          </span>
          {masterTableFilter !== "all" && (
            <button onClick={() => setMasterTableFilter("all")}
              style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", color: "#8B95A8" }}>
              Show All
            </button>
          )}
        </div>
        <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
          {(() => {
            const repCols = ["", "EFJ #", "Container/Load #", "Type", "Carrier", "Origin \u2192 Dest", "ETA/ERD", "PU", "DEL", "Status"];
            return (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {repCols.map(h => renderFilterTh(h))}
                </tr>
              </thead>
              <tbody>
                {masterDrayLoads.map((s) => {
                  const sc = STATUS_COLORS[s.status] || { main: "#94a3b8" };
                  const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                  const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                  const isFTL = s.moveType === "FTL";
                  const pu = splitDateTime(s.pickupDate);
                  const del = splitDateTime(s.deliveryDate);
                  const isEditing = inlineEditId === s.id;
                  const repFtlMarginPct = calcMarginPct(s.customerRate, s.carrierPay);
                  return (
                    <tr key={s.id} className={`row-hover${highlightedEfj === s.efj ? " row-highlight-pulse" : ""}`}
                      style={{ cursor: "default", borderBottom: "1px solid rgba(255,255,255,0.02)", background: highlightedEfj === s.efj ? undefined : (repFtlMarginPct !== null && repFtlMarginPct < 10 ? "rgba(239,68,68,0.10)" : undefined) }}>
                      {renderRowActions(s)}
                      {/* EFJ (inline-editable) */}
                      <td style={{ padding: "8px 14px" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("efj"); setInlineEditValue(s.efj || ""); }}>
                        {isEditing && inlineEditField === "efj" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "efj", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 85, fontWeight: 600, color: "#00D4AA" }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <div style={{ display: "flex", alignItems: "center", gap: 4, cursor: "text" }}>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{s.loadNumber}</span>
                            <DocIndicators docs={docs} />
                            {s.botAlert && s.botAlert.includes("HOLD") && (
                              <span title={s.botAlert} style={{ fontSize: 8, fontWeight: 700, padding: "1px 4px", borderRadius: 3, background: "rgba(239,68,68,0.15)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.35)", letterSpacing: "0.3px", animation: "alert-pulse 1.8s ease-in-out infinite", cursor: "default" }}>HOLD</span>
                            )}
                          </div>
                        )}
                      </td>
                      {/* Container (inline-editable) */}
                      <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#F0F2F5" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("container"); setInlineEditValue(s.container || ""); }}>
                        {isEditing && inlineEditField === "container" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "container", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ cursor: "text" }}>{s.container || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}</span>
                        )}
                      </td>
                      {/* Move Type */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          color: isFTL ? "#60A5FA" : "#F59E0B", background: isFTL ? "#60A5FA12" : "#F59E0B12",
                          border: `1px solid ${isFTL ? "#60A5FA22" : "#F59E0B22"}`, textTransform: "uppercase" }}>
                          {s.moveType || "Dray"}
                        </span>
                      </td>
                      {/* Carrier (inline-editable) */}
                      <td style={{ padding: "8px 14px", fontSize: 11, color: "#F0F2F5", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrier"); setInlineEditValue(s.carrier || ""); }}>
                        {isEditing && inlineEditField === "carrier" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "carrier", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ cursor: "text" }}>{s.carrier || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}</span>
                        )}
                      </td>
                      {/* Origin → Dest (inline-editable, split) */}
                      <td style={{ padding: "8px 14px", fontSize: 11 }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("origin"); setInlineEditValue(s.origin || ""); }}>
                        {isEditing && inlineEditField === "origin" ? (
                          <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { handleFieldUpdate(s, "origin", inlineEditValue); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 80 }} onClick={e => e.stopPropagation()} />
                        ) : isEditing && inlineEditField === "destination" ? (
                          <span style={{ cursor: "text" }}>
                            <span style={{ color: "#F0F2F5" }}>{s.origin}</span>
                            <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                            <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { handleFieldUpdate(s, "destination", inlineEditValue); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 80 }} onClick={e => e.stopPropagation()} />
                          </span>
                        ) : (
                          <span style={{ cursor: "text" }}>
                            <span style={{ color: "#F0F2F5" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("origin"); setInlineEditValue(s.origin || ""); }}>{s.origin}</span>
                            <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                            <span style={{ color: "#F0F2F5" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("destination"); setInlineEditValue(s.destination || ""); }}>{s.destination}</span>
                          </span>
                        )}
                      </td>
                      {/* ETA/ERD (inline-editable) */}
                      <td style={{ padding: "8px 14px" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("eta"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "eta" ? (
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "eta", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) handleFieldUpdate(s, "eta", parsed); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} onClick={e => e.stopPropagation()} />
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>
                            {formatDDMM(s.eta || s.lfd) || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}
                          </span>
                        )}
                      </td>
                      {/* PU Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "pickup" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "pickupTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                            {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                          </span>
                        )}
                      </td>
                      {/* DEL Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "delivery" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "deliveryTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                            {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                          </span>
                        )}
                      </td>
                      {/* Status (inline-editable dropdown) */}
                      <td style={{ padding: "8px 14px", position: "relative" }}
                        onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                        {isEditing && inlineEditField === "status" ? (
                          <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 9999, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 280, overflowY: "auto", minWidth: 120 }} className="inline-status-dd">
                            {getStatusesForShipment(s).filter(st => st.key !== "all").map(st => {
                              const stc = getStatusColors(s)[st.key] || { main: "#94a3b8" };
                              return (
                                <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                  style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                    background: s.status === st.key ? `${stc.main}18` : "transparent",
                                    color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                  <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                  {st.label}
                                </button>
                              );
                            })}
                            <div style={{ height: 1, background: "rgba(255,255,255,0.08)", margin: "4px 0" }} />
                            <div style={{ fontSize: 8, fontWeight: 700, color: "#5A6478", letterSpacing: "1.5px", padding: "2px 7px", textTransform: "uppercase" }}>Billing</div>
                            {BILLING_STATUSES.map(st => {
                              const stc = BILLING_STATUS_COLORS[st.key] || { main: "#94a3b8" };
                              return (
                                <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                  style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                    background: s.status === st.key ? `${stc.main}18` : "transparent",
                                    color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                  <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                  {st.label}
                                </button>
                              );
                            })}
                            <button onClick={(e) => { e.stopPropagation(); setInlineEditId(null); }}
                              style={{ display: "block", width: "100%", padding: "3px 7px", marginTop: 2, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.03)", color: "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                          </div>
                        ) : null}
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 11, fontWeight: 700,
                          color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase", cursor: "pointer" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                          {STATUSES.find(st => st.key === s.status)?.label || s.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            );
          })()}
          {masterDrayLoads.length === 0 && (
            <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>No dray loads found</div>
            </div>
          )}
        </div>
      </div>
      ) : null; })()}
      {displayDataFiltered.length === 0 && (
        <div className="dash-panel" style={{ overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <span className="dash-panel-title">{expandedAccount || "All Accounts"} {"\u2014"} 0 Loads</span>
          </div>
          <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
            <div style={{ fontSize: 11, fontWeight: 600 }}>No loads found</div>
          </div>
        </div>
      )}
      </>)}

      {/* Delete confirmation modal */}
      {deleteConfirmEfj && (
        <div style={{ position: "fixed", inset: 0, zIndex: Z.panel + 20, display: "flex", alignItems: "center", justifyContent: "center" }}
          onKeyDown={e => { if (e.key === "Escape") setDeleteConfirmEfj(null); }}>
          <div onClick={() => setDeleteConfirmEfj(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)" }} aria-hidden="true" />
          <div role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-desc"
            style={{ position: "relative", background: "#1A2236", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 14, padding: "24px 28px", maxWidth: 380, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.5)" }}>
            <div id="delete-dialog-title" style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", marginBottom: 8 }}>Delete Load?</div>
            <div id="delete-dialog-desc" style={{ fontSize: 12, color: "#8B95A8", marginBottom: 18, lineHeight: 1.5 }}>
              Are you sure you want to delete <span style={{ color: "#F0F2F5", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{deleteConfirmEfj}</span>? This will remove it from the dashboard and Google Sheet.
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button autoFocus onClick={() => setDeleteConfirmEfj(null)} disabled={deleteLoading}
                style={{ flex: 1, padding: "9px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.04)", color: "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                Cancel
              </button>
              <button onClick={async () => { setDeleteLoading(true); try { await handleDeleteLoad(deleteConfirmEfj); setDeleteConfirmEfj(null); } catch (err) { alert(`Delete failed: ${err.message}`); } setDeleteLoading(false); }} disabled={deleteLoading}
                style={{ flex: 1, padding: "9px", borderRadius: 8, border: "none", background: deleteLoading ? "#7f1d1d" : "#EF4444", color: "#fff", fontSize: 12, fontWeight: 700, cursor: deleteLoading ? "wait" : "pointer", fontFamily: "inherit" }}>
                {deleteLoading ? "Deleting..." : "Yes, Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

