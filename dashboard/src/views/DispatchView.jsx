import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../store";
import { apiFetch, API_BASE } from "../helpers/api";
import {
  STATUSES, FTL_STATUSES, BILLING_STATUSES, STATUS_COLORS, FTL_STATUS_COLORS,
  BILLING_STATUS_COLORS, ALL_STATUSES_COMBINED, ALL_REP_NAMES, MASTER_REPS,
  DOC_TYPE_LABELS, Z, REP_COLORS, TRUCK_TYPES,
} from "../helpers/constants";
import {
  isFTLShipment, getStatusesForShipment, getStatusColors, resolveStatusLabel, resolveStatusColor,
  calcMarginPct, formatDDMM, fmtDateDisplay, splitDateTime, parseDDMM,
  isDateToday, isDateTomorrow, isDatePast, getBillingReadiness,
  applyColFilters, buildColFilterOptions, useIsMobile, resolveRepForShipment,
  parseTerminalNotes, COL_FILTER_KEY_MAP,
} from "../helpers/utils";
import TerminalBadge from "../components/TerminalBadge";
import DocIndicators from "../components/DocIndicators";
import TrackingBadge from "../components/TrackingBadge";

export default function DispatchView({
  loaded, shipments, filtered, accounts,
  activeStatus, setActiveStatus, activeAccount, setActiveAccount,
  activeRep, setActiveRep, searchQuery, setSearchQuery, statusCounts,
  selectedShipment, setSelectedShipment,
  editField, setEditField, editValue, setEditValue,
  sheetLog, handleStatusUpdate, handleFieldEdit, handleLoadClick,
  activeLoads, inTransit, deliveredCount, issueCount, onAddLoad, addSheetLog, setShipments,
  podUploading, setPodUploading, podUploadMsg, setPodUploadMsg,
  trackingSummary, docSummary,
  dateFilter, setDateFilter,
  moveTypeFilter, setMoveTypeFilter,
  dateRangeField, setDateRangeField, dateRangeStart, setDateRangeStart,
  dateRangeEnd, setDateRangeEnd,
  handleFieldUpdate,
  handleMetadataUpdate,
  handleDriverFieldUpdate,
  onBack,
}) {
  const highlightedEfj = useAppStore(s => s.highlightedEfj);
  const ACCOUNTS = accounts || ["All Accounts"];
  const podInputRef = useRef(null);
  const docInputRef = useRef(null);
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [inlineEditId, setInlineEditId] = useState(null);
  const [inlineEditField, setInlineEditField] = useState(null);
  const [inlineEditValue, setInlineEditValue] = useState("");

  // Close inline status dropdown on click outside
  useEffect(() => {
    if (!inlineEditId || inlineEditField !== "status") return;
    const handler = (e) => {
      if (!e.target.closest('.inline-status-dd')) setInlineEditId(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [inlineEditId, inlineEditField]);

  // Spreadsheet-like Tab/Enter navigation — ordered list of editable columns
  const EDITABLE_COLS = useMemo(() => ["efj", "container", "pickup", "origin", "destination", "delivery", "truckType", "trailer", "driverPhone", "carrierEmail", "customerRate", "notes"], []);
  const sortedRef = useRef([]);
  const [showDatePopover, setShowDatePopover] = useState(false);
  const [zebraStripe, setZebraStripe] = useState(true);
  const [columnFilters, setColumnFilters] = useState({});
  const [openFilterCol, setOpenFilterCol] = useState(null);
  const [showColPicker, setShowColPicker] = useState(false);

  // Column visibility — persisted to localStorage
  const DEFAULT_HIDDEN = ["carrierEmail", "trailer", "margin"];
  const [hiddenCols, setHiddenCols] = useState(() => {
    try { const s = localStorage.getItem("dispatch_hidden_cols"); return s ? JSON.parse(s) : DEFAULT_HIDDEN; }
    catch { return DEFAULT_HIDDEN; }
  });
  const toggleCol = (key) => {
    setHiddenCols(prev => {
      const next = prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key];
      localStorage.setItem("dispatch_hidden_cols", JSON.stringify(next));
      return next;
    });
  };
  const isColVisible = (key) => !hiddenCols.includes(key);

  // Close column filter dropdown on outside click
  useEffect(() => {
    if (!openFilterCol) return;
    const handler = (e) => { if (!e.target.closest('.col-filter-dd')) setOpenFilterCol(null); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [openFilterCol]);

  // Close column picker on outside click
  useEffect(() => {
    if (!showColPicker) return;
    const handler = (e) => { if (!e.target.closest('.col-picker-dd')) setShowColPicker(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showColPicker]);

  const activeStatusList = useMemo(() => {
    if (moveTypeFilter === "ftl") return FTL_STATUSES;
    if (moveTypeFilter === "dray") return STATUSES;
    return ALL_STATUSES_COMBINED;
  }, [moveTypeFilter]);

  // FTL tracking preview state (kept for dead code compatibility)
  const [trackingData, setTrackingData] = useState(null);
  const [trackingScreenshot, setTrackingScreenshot] = useState(null);
  const [trackingLoading, setTrackingLoading] = useState(false);

  // Document hub state (kept for dead code compatibility)
  const [loadDocs, setLoadDocs] = useState([]);
  const [docFilter, setDocFilter] = useState("all");
  const [docUploading, setDocUploading] = useState(false);
  const [docType, setDocType] = useState("other");
  const [docUploadMsg, setDocUploadMsg] = useState(null);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [reclassDocId, setReclassDocId] = useState(null);
  const [loadEmails, setLoadEmails] = useState([]);

  // Driver contact state (kept for dead code compatibility)
  const [driverInfo, setDriverInfo] = useState({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
  const [driverEditing, setDriverEditing] = useState(null);
  const [driverEditVal, setDriverEditVal] = useState("");
  const [driverSaving, setDriverSaving] = useState(false);

  const hasFTL = filtered.some(s => s.moveType === "FTL");
  const DISPATCH_COLS = [
    { key: "account", label: "Account", w: 80, sortFn: (a, b) => a.account.localeCompare(b.account) },
    { key: "status", label: "Status", w: 100, sortFn: (a, b) => a.status.localeCompare(b.status) },
    { key: "efj", label: "EFJ #", w: 90, sortFn: (a, b) => a.loadNumber.localeCompare(b.loadNumber) },
    { key: "container", label: "Container/Load #", w: 120, sortFn: (a, b) => a.container.localeCompare(b.container) },
    ...(hasFTL ? [{ key: "mpStatus", label: "MP Status", w: 110, sortFn: (a, b) => {
      const efjA = (a.efj || "").replace(/^EFJ\s*/i, ""); const efjB = (b.efj || "").replace(/^EFJ\s*/i, "");
      const aS = (a.mpDisplayStatus || trackingSummary?.[efjA]?.mpDisplayStatus || "").toLowerCase();
      const bS = (b.mpDisplayStatus || trackingSummary?.[efjB]?.mpDisplayStatus || "").toLowerCase();
      const pri = s => s === "behind schedule" ? 5 : s === "no signal" ? 4 : s === "awaiting update" ? 3 : s === "at delivery" ? 2 : s === "at pickup" ? 1 : 0;
      return pri(bS) - pri(aS);
    }}] : []),
    { key: "pickup", label: "Pickup", w: 110, sortFn: (a, b) => (a.pickupDate || "").localeCompare(b.pickupDate || "") },
    { key: "origin", label: "Origin", w: 120, sortFn: (a, b) => (a.origin || "").localeCompare(b.origin || "") },
    { key: "destination", label: "Destination", w: 120, sortFn: (a, b) => (a.destination || "").localeCompare(b.destination || "") },
    { key: "delivery", label: "Delivery", w: 110, sortFn: (a, b) => (a.deliveryDate || "").localeCompare(b.deliveryDate || "") },
    { key: "truckType", label: "Truck", w: 75, sortFn: (a, b) => (a.truckType || "").localeCompare(b.truckType || "") },
    { key: "trailer", label: "Trailer #", w: 70, sortFn: (a, b) => (a.trailerNumber || "").localeCompare(b.trailerNumber || "") },
    { key: "driverPhone", label: "Driver Phone", w: 100, sortFn: (a, b) => (a.driverPhone || "").localeCompare(b.driverPhone || "") },
    { key: "carrierEmail", label: "Carrier Email", w: 130, sortFn: (a, b) => (a.carrierEmail || "").localeCompare(b.carrierEmail || "") },
    { key: "customerRate", label: "Rate", w: 70, sortFn: (a, b) => (a.customerRate || "").localeCompare(b.customerRate || "") },
    { key: "margin", label: "MGN", w: 55, sortFn: (a, b) => { const ma = calcMarginPct(a.customerRate, a.carrierPay); const mb = calcMarginPct(b.customerRate, b.carrierPay); return (ma ?? -999) - (mb ?? -999); }},
    { key: "notes", label: "Notes", w: 140, sortFn: (a, b) => (a.notes || "").localeCompare(b.notes || "") },
  ];

  // Column filter: compute unique options + apply filters
  const FILTERABLE_KEYS = useMemo(() => ["account", "status", "mpStatus", "origin", "destination", "pickup", "delivery"], []);
  const colFilterOpts = useMemo(() => buildColFilterOptions(filtered, trackingSummary), [filtered, trackingSummary]);
  const columnFiltered = useMemo(() => applyColFilters(filtered, columnFilters, trackingSummary), [filtered, columnFilters, trackingSummary]);

  const sorted = useMemo(() => {
    if (!sortCol) return columnFiltered;
    const col = DISPATCH_COLS.find(c => c.key === sortCol);
    if (!col) return columnFiltered;
    return [...columnFiltered].sort((a, b) => {
      const result = col.sortFn(a, b);
      return sortDir === "asc" ? result : -result;
    });
  }, [columnFiltered, sortCol, sortDir]);
  sortedRef.current = sorted;

  // Navigate to adjacent cell (Tab/Shift+Tab/Enter)
  const getShipValue = (ship, field) => {
    const map = { efj: ship.efj, account: ship.account, container: ship.container, origin: ship.origin, destination: ship.destination, trailer: ship.trailerNumber, driverPhone: ship.driverPhone, carrierEmail: ship.carrierEmail, customerRate: ship.customerRate, notes: ship.notes, truckType: ship.truckType };
    return map[field] || "";
  };
  const navigateCell = (currentField, shipmentId, direction) => {
    const visibleEditable = EDITABLE_COLS.filter(k => !hiddenCols.includes(k));
    const colIdx = visibleEditable.indexOf(currentField);
    if (direction === "right" || direction === "left") {
      const nextIdx = direction === "right" ? colIdx + 1 : colIdx - 1;
      if (nextIdx >= 0 && nextIdx < visibleEditable.length) {
        const nextField = visibleEditable[nextIdx];
        setInlineEditField(nextField);
        const ship = sortedRef.current.find(s => s.id === shipmentId);
        if (ship) setInlineEditValue(getShipValue(ship, nextField));
        return true;
      }
    }
    if (direction === "down") {
      const rows = sortedRef.current;
      const rowIdx = rows.findIndex(s => s.id === shipmentId);
      if (rowIdx >= 0 && rowIdx < rows.length - 1) {
        const nextShip = rows[rowIdx + 1];
        setInlineEditId(nextShip.id);
        setInlineEditField(currentField);
        setInlineEditValue(getShipValue(nextShip, currentField));
        return true;
      }
    }
    return false;
  };

  // Shared keyDown handler for spreadsheet navigation
  const inlineKeyDown = (e, field, shipId, onCommit) => {
    if (e.key === "Tab") {
      e.preventDefault();
      onCommit();
      navigateCell(field, shipId, e.shiftKey ? "left" : "right");
    } else if (e.key === "Enter") {
      e.preventDefault();
      onCommit();
      if (!navigateCell(field, shipId, "down")) setInlineEditId(null);
    } else if (e.key === "Escape") {
      setInlineEditId(null);
    }
  };

  const hasActiveFilters = activeStatus !== "all" || activeAccount !== "All Accounts" || activeRep !== "All Reps" || searchQuery !== "" || !!dateFilter || moveTypeFilter !== "all" || !!dateRangeField || Object.keys(columnFilters).length > 0;

  const exportCSV = () => {
    const headers = ["Account", "Status", "EFJ #", "Container/Load #", "MP Status", "Pickup Date/Time", "Origin", "Destination", "Delivery Date/Time", "Truck Type", "Trailer #", "Driver Phone", "Carrier Email", "Customer Rate", "Notes", "Move Type", "Carrier"];
    const rows = sorted.map(s => {
      const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
      const t = trackingSummary?.[efjBare];
      return [s.account,
        [...FTL_STATUSES, ...STATUSES].find(st => st.key === s.status)?.label || s.status,
        s.loadNumber, s.container, s.mpDisplayStatus || t?.mpDisplayStatus || s.mpStatus || t?.mpStatus || "",
        s.pickupDate || "", s.origin, s.destination, s.deliveryDate || "",
        s.truckType || "", s.trailerNumber || "", s.driverPhone || "", s.carrierEmail || "",
        s.customerRate || "", (s.notes || "").replace(/"/g, '""'),
        s.moveType, s.carrier];
    });
    const csv = [headers.join(","), ...rows.map(r => r.map(v => `"${v}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `loadboard-export-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePodUpload = async (file) => {
    if (!selectedShipment?.efj || !file) return;
    setPodUploading(true); setPodUploadMsg(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/upload`, { method: "POST", body: fd });
      if (r.ok) { setPodUploadMsg("Upload successful"); addSheetLog(`POD uploaded | ${selectedShipment.loadNumber}`); }
      else { setPodUploadMsg(`Upload failed (${r.status})`); }
    } catch (e) { setPodUploadMsg("Upload error"); }
    setPodUploading(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 60px)", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 0 10px", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {onBack && <button onClick={onBack} style={{ background: "none", border: "none", color: "#8B95A8", fontSize: 13, cursor: "pointer", padding: "4px 8px", fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 600, transition: "color 0.15s" }} onMouseEnter={e => e.currentTarget.style.color = "#00D4AA"} onMouseLeave={e => e.currentTarget.style.color = "#8B95A8"}>{"\u2190"} Overview</button>}
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Loadboard</h2>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div className="col-picker-dd" style={{ position: "relative" }}>
            <button onClick={() => setShowColPicker(p => !p)} style={{ border: `1px solid ${hiddenCols.length > 0 ? "rgba(59,130,246,0.3)" : "rgba(255,255,255,0.08)"}`, background: hiddenCols.length > 0 ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: hiddenCols.length > 0 ? "#60A5FA" : "#8B95A8", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {"\u2637"} Columns {hiddenCols.length > 0 && `(${DISPATCH_COLS.length - hiddenCols.length}/${DISPATCH_COLS.length})`}
            </button>
            {showColPicker && (
              <div className="col-picker-dd" style={{ position: "absolute", top: "100%", right: 0, marginTop: 4, zIndex: 40, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, padding: 8, minWidth: 200, boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", letterSpacing: "1px", textTransform: "uppercase", padding: "4px 8px", marginBottom: 4 }}>Toggle Columns</div>
                {DISPATCH_COLS.map(col => (
                  <label key={col.key} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px", borderRadius: 5, cursor: "pointer", fontSize: 11, fontWeight: 500, color: isColVisible(col.key) ? "#F0F2F5" : "#5A6478", background: isColVisible(col.key) ? "rgba(255,255,255,0.03)" : "transparent" }}
                    onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
                    onMouseLeave={e => e.currentTarget.style.background = isColVisible(col.key) ? "rgba(255,255,255,0.03)" : "transparent"}>
                    <input type="checkbox" checked={isColVisible(col.key)} onChange={() => toggleCol(col.key)}
                      style={{ accentColor: "#00D4AA", width: 14, height: 14, cursor: "pointer" }} />
                    {col.label}
                  </label>
                ))}
                <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", marginTop: 6, paddingTop: 6, display: "flex", gap: 6 }}>
                  <button onClick={() => { setHiddenCols([]); localStorage.setItem("dispatch_hidden_cols", "[]"); }}
                    style={{ flex: 1, padding: "4px 8px", borderRadius: 5, border: "none", background: "rgba(0,212,170,0.1)", color: "#00D4AA", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>Show All</button>
                  <button onClick={() => { setHiddenCols(DEFAULT_HIDDEN); localStorage.setItem("dispatch_hidden_cols", JSON.stringify(DEFAULT_HIDDEN)); }}
                    style={{ flex: 1, padding: "4px 8px", borderRadius: 5, border: "none", background: "rgba(255,255,255,0.05)", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>Reset</button>
                </div>
              </div>
            )}
          </div>
          <button onClick={() => setZebraStripe(z => !z)} style={{ border: `1px solid ${zebraStripe ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: zebraStripe ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: zebraStripe ? "#00D4AA" : "#8B95A8", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{zebraStripe ? "\u2630 Striped" : "\u2630 Flat"}</button>
          <button onClick={exportCSV} style={{ border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: "#8B95A8", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{"\u2193"} CSV</button>
          <button onClick={onAddLoad} className="btn-primary" style={{ border: "none", borderRadius: 8, padding: "8px 18px", fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#fff" }}>+ New Load</button>
        </div>
      </div>

      {/* Metrics Strip */}
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexShrink: 0, animation: loaded ? "slide-up 0.5s ease 0.1s both" : "none" }}>
        {[
          { label: "Active Loads", value: activeLoads, color: "#60a5fa", icon: "\u25C8" },
          { label: "In Transit", value: inTransit, color: "#34d399", icon: "\u25B8" },
          { label: "Delivered", value: deliveredCount, color: "#fbbf24", icon: "\u2726" },
          { label: "Exceptions", value: issueCount, color: "#f87171", icon: "\u26A0" },
        ].map((m, i) => (
          <div key={i} className="glass metric-card" style={{ flex: 1, padding: "12px 14px", borderRadius: 12, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 34, height: 34, borderRadius: 8, background: `${m.color}15`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: m.color }}>{m.icon}</div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>{m.value}</div>
              <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 500, letterSpacing: "1px", textTransform: "uppercase" }}>{m.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Move Type Toggle + Status Cards */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 2, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, flexShrink: 0 }}>
          {[{ key: "all", label: "All" }, { key: "dray", label: "Dray" }, { key: "ftl", label: "FTL" }].map(t => (
            <button key={t.key} onClick={() => { setMoveTypeFilter(t.key); setActiveStatus("all"); }}
              style={{ padding: "5px 12px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                background: moveTypeFilter === t.key ? "rgba(0,212,170,0.15)" : "transparent",
                color: moveTypeFilter === t.key ? "#00D4AA" : "#8B95A8", letterSpacing: "0.5px" }}>
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, overflowX: "auto", flex: 1, paddingBottom: 2 }}>
          {statusCounts.map((s) => {
            const isActive = activeStatus === s.key;
            const allColors = { ...STATUS_COLORS, ...FTL_STATUS_COLORS };
            const sc = allColors[s.key] || { main: "#64748b" };
            return (
              <button key={s.key} className={`status-card ${isActive ? "active" : ""}`}
                onClick={() => setActiveStatus(s.key)}
                style={{ flex: "0 0 auto", minWidth: 80, padding: "8px 12px",
                  background: isActive ? `linear-gradient(135deg, ${sc.main}12, ${sc.main}08)` : "rgba(255,255,255,0.02)",
                  border: `1px solid ${isActive ? sc.main + "44" : "rgba(255,255,255,0.04)"}`,
                  borderRadius: 10, cursor: "pointer", textAlign: "left", position: "relative", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
                  <span style={{ fontSize: 11, opacity: 0.7 }}>{s.icon}</span>
                  <span style={{ fontSize: 20, fontWeight: 900, color: isActive ? sc.main : "#64748b" }}>{s.count}</span>
                </div>
                <div style={{ fontSize: 11, fontWeight: 600, color: isActive ? "#F0F2F5" : "#8B95A8", whiteSpace: "nowrap" }}>{s.label}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Filter Bar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap", flexShrink: 0 }}>
        <div style={{ position: "relative", flex: 1, maxWidth: 300, minWidth: 180 }}>
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search EFJ#, containers, carriers..."
            style={{ width: "100%", padding: "9px 14px 9px 34px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: "#8B95A8" }}>{"\u2315"}</span>
        </div>
        <select value={activeAccount} onChange={e => setActiveAccount(e.target.value)}
          style={{ padding: "9px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {ACCOUNTS.map(a => <option key={a} value={a} style={{ background: "#0D1119" }}>{a}</option>)}
        </select>
        <select value={activeRep} onChange={e => setActiveRep(e.target.value)}
          style={{ padding: "9px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {["All Reps", ...ALL_REP_NAMES].map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
        </select>
        <select value={activeStatus} onChange={e => setActiveStatus(e.target.value)}
          style={{ padding: "9px 12px", background: activeStatus !== "all" ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${activeStatus !== "all" ? "rgba(59,130,246,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 10, color: activeStatus !== "all" ? "#60A5FA" : "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {activeStatusList.map(s => <option key={s.key} value={s.key} style={{ background: "#0D1119" }}>{s.key === "all" ? "All Statuses" : s.label}</option>)}
        </select>
        {/* Date Range Popover */}
        <div style={{ position: "relative" }}>
          <button onClick={() => setShowDatePopover(!showDatePopover)}
            style={{ padding: "9px 12px", background: dateRangeField ? "rgba(59,130,246,0.1)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${dateRangeField ? "rgba(59,130,246,0.3)" : "rgba(255,255,255,0.06)"}`,
              borderRadius: 10, color: dateRangeField ? "#60A5FA" : "#F0F2F5", fontSize: 12, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            {"\u{1F4C5}"} Dates
          </button>
          {showDatePopover && (
            <div style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, zIndex: 30, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, padding: 14, width: 280, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Filter by Date</div>
              <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
                {[{ k: "pickup", l: "Pickup" }, { k: "delivery", l: "Delivery" }].map(f => (
                  <button key={f.k} onClick={() => setDateRangeField(dateRangeField === f.k ? null : f.k)}
                    style={{ flex: 1, padding: "5px 10px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                      background: dateRangeField === f.k ? "rgba(59,130,246,0.15)" : "rgba(255,255,255,0.05)",
                      color: dateRangeField === f.k ? "#60A5FA" : "#8B95A8" }}>
                    {f.l} Date
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 3 }}>From</div>
                  <input type="date" value={dateRangeStart} onChange={e => { setDateRangeStart(e.target.value); if (!dateRangeField) setDateRangeField("pickup"); }}
                    style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "inherit" }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 3 }}>To</div>
                  <input type="date" value={dateRangeEnd} onChange={e => setDateRangeEnd(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "inherit" }} />
                </div>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
                {[
                  { label: "Today", fn: () => { const d = new Date().toISOString().slice(0,10); setDateRangeStart(d); setDateRangeEnd(d); }},
                  { label: "Tomorrow", fn: () => { const d = new Date(Date.now() + 86400000).toISOString().slice(0,10); setDateRangeStart(d); setDateRangeEnd(d); }},
                  { label: "This Week", fn: () => {
                    const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? -6 : 1);
                    const mon = new Date(now); mon.setDate(diff); const fri = new Date(mon); fri.setDate(fri.getDate() + 4);
                    setDateRangeStart(mon.toISOString().slice(0,10)); setDateRangeEnd(fri.toISOString().slice(0,10));
                  }},
                  { label: "Next Week", fn: () => {
                    const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? 1 : 8);
                    const mon = new Date(now); mon.setDate(diff); const fri = new Date(mon); fri.setDate(fri.getDate() + 4);
                    setDateRangeStart(mon.toISOString().slice(0,10)); setDateRangeEnd(fri.toISOString().slice(0,10));
                  }},
                  { label: "Past Due", fn: () => {
                    setDateRangeStart("2020-01-01"); setDateRangeEnd(new Date(Date.now() - 86400000).toISOString().slice(0,10));
                  }},
                ].map(p => (
                  <button key={p.label} onClick={() => { p.fn(); if (!dateRangeField) setDateRangeField("pickup"); setDateFilter(null); setShowDatePopover(false); }}
                    style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.03)", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                    {p.label}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                <button onClick={() => { setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); setShowDatePopover(false); }}
                  style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                  Clear
                </button>
                <button onClick={() => setShowDatePopover(false)}
                  style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: "rgba(0,212,170,0.15)", color: "#00D4AA", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#8B95A8" }}>
          <span><span style={{ color: "#8B95A8", fontWeight: 700 }}>{filtered.length}</span> of {shipments.length}</span>
          {hasActiveFilters && (
            <button onClick={() => { setActiveStatus("all"); setActiveAccount("All Accounts"); setActiveRep("All Reps"); setSearchQuery(""); if (setDateFilter) setDateFilter(null); setMoveTypeFilter("all"); setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); setColumnFilters({}); setOpenFilterCol(null); }}
              style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)", borderRadius: 6, padding: "4px 10px", fontSize: 11, fontWeight: 600, color: "#f87171", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              &#x2715; Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Active filter chips */}
      {(dateFilter || dateRangeField) && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {dateFilter && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60A5FA" }}>
              {{ pickup_today: "Pickups Today", pickup_tomorrow: "Pickups Tomorrow", delivery_today: "Deliveries Today", delivery_tomorrow: "Deliveries Tomorrow", yesterday: "Yesterday's Activity" }[dateFilter] || dateFilter}
              <span onClick={() => setDateFilter(null)} style={{ cursor: "pointer", marginLeft: 4, color: "#60A5FA", fontSize: 12, lineHeight: 1 }}>&#x2715;</span>
            </span>
          )}
          {dateRangeField && dateRangeStart && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: "rgba(6,182,212,0.1)", border: "1px solid rgba(6,182,212,0.25)", color: "#22D3EE" }}>
              {dateRangeField === "pickup" ? "PU" : "DEL"}: {dateRangeStart}{dateRangeEnd && dateRangeEnd !== dateRangeStart ? ` \u2014 ${dateRangeEnd}` : ""}
              <span onClick={() => { setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); }} style={{ cursor: "pointer", marginLeft: 4, color: "#22D3EE", fontSize: 12, lineHeight: 1 }}>&#x2715;</span>
            </span>
          )}
        </div>
      )}

      {/* Mobile Card View */}
      <div className="mobile-card-view" style={{ display: "none", flex: 1, overflowY: "auto", padding: "0 2px 60px" }}>
        {filtered.slice(0, 100).map(s => {
          const sc = (isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS)[s.status] || { main: "#94a3b8" };
          const mgn = calcMarginPct(s.customerRate, s.carrierPay);
          return (
            <div key={s.id} className={highlightedEfj === s.efj ? "row-highlight-pulse" : ""} onClick={() => handleLoadClick(s)}
              style={{ padding: "12px 14px", marginBottom: 8, borderRadius: 10, cursor: "pointer",
                background: highlightedEfj === s.efj ? undefined : ((mgn !== null && mgn < 10) ? "rgba(239,68,68,0.06)" : "rgba(255,255,255,0.02)"),
                border: "1px solid rgba(255,255,255,0.06)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: "#00D4AA", fontSize: 13 }}>{s.loadNumber}</span>
                  {s.playbookLaneCode && <span title={`Playbook: ${s.playbookLaneCode}`} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 14, height: 14, borderRadius: 3, background: "rgba(0,212,170,0.15)" }}><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#00D4AA" strokeWidth="2.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span>}
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#F0F2F5" }}>{s.account}</span>
                </div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 10, fontSize: 8, fontWeight: 700,
                  color: sc.main, background: `${sc.main}0D`, border: `1px solid ${sc.main}18`, textTransform: "uppercase" }}>
                  <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                  {resolveStatusLabel(s)}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "#8B95A8", marginBottom: 4 }}>
                {s.origin || "\u2014"} {"\u2192"} {s.destination || "\u2014"}
              </div>
              <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#5A6478", flexWrap: "wrap" }}>
                {s.pickupDate && <span>PU: {formatDDMM(s.pickupDate)}</span>}
                {s.deliveryDate && <span>DEL: {formatDDMM(s.deliveryDate)}</span>}
                {s.carrier && <span>{s.carrier}</span>}
                {s.customerRate && <span style={{ color: "#22C55E", fontWeight: 600 }}>${s.customerRate}</span>}
                {mgn !== null && <span style={{ fontWeight: 700, color: mgn < 0 ? "#EF4444" : mgn < 10 ? "#F59E0B" : "#22C55E" }}>{mgn}%</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Full-width Table */}
      <div className="dispatch-table-wrap desktop-table-view" style={{ flex: 1, minHeight: 0, overflowX: "scroll", overflowY: "auto", borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.01)" }}>
        <table style={{ width: "100%", minWidth: 1600, borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr>
              <th style={{ padding: "7px 4px", width: 24, borderBottom: "1px solid rgba(255,255,255,0.08)" }} />
              {DISPATCH_COLS.filter(c => isColVisible(c.key)).map((col, ci) => {
                const isFilterable = FILTERABLE_KEYS.includes(col.key);
                const hasColFilter = !!columnFilters[col.key];
                const isOpen = openFilterCol === col.key;
                const opts = colFilterOpts[col.key] || [];
                return (
                  <th key={col.key}
                    style={{ padding: "7px 8px", textAlign: "left", fontSize: 11, fontWeight: 700,
                      color: hasColFilter ? "#00D4AA" : sortCol === col.key ? "#00D4AA" : "#8B95A8",
                      letterSpacing: "0.8px", textTransform: "uppercase",
                      borderBottom: hasColFilter ? "2px solid rgba(0,212,170,0.4)" : "1px solid rgba(255,255,255,0.08)",
                      borderRight: ci < DISPATCH_COLS.filter(c => isColVisible(c.key)).length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
                      background: hasColFilter ? "rgba(0,212,170,0.04)" : "#0D1119",
                      position: "sticky", top: 0, zIndex: isOpen ? Z.panelBackdrop : Z.table, cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", maxWidth: col.w }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                      <span style={{ flex: 1 }} onClick={() => {
                        if (sortCol === col.key) setSortDir(d => d === "asc" ? "desc" : "asc");
                        else { setSortCol(col.key); setSortDir("asc"); }
                      }}>
                        {col.label} {sortCol === col.key ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}
                      </span>
                      {isFilterable && (
                        <span className="col-filter-dd"
                          onClick={(e) => { e.stopPropagation(); setOpenFilterCol(isOpen ? null : col.key); }}
                          style={{ fontSize: 8, color: hasColFilter ? "#00D4AA" : "#5A6478", cursor: "pointer",
                            padding: "2px 3px", borderRadius: 3, background: hasColFilter ? "rgba(0,212,170,0.12)" : "transparent", lineHeight: 1 }}>
                          {hasColFilter ? "\u2726" : "\u25BE"}
                        </span>
                      )}
                    </div>
                    {isOpen && (
                      <div className="col-filter-dd" onClick={e => e.stopPropagation()}
                        style={{ position: "absolute", top: "100%", left: 0, marginTop: 2, zIndex: Z.dropdown, background: "#1A2236",
                          border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, minWidth: 150,
                          maxHeight: 300, overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
                        <div onClick={() => { setColumnFilters(f => { const n = {...f}; delete n[col.key]; return n; }); setOpenFilterCol(null); }}
                          style={{ padding: "6px 10px", fontSize: 11, color: !hasColFilter ? "#00D4AA" : "#8B95A8",
                            cursor: "pointer", borderRadius: 4, background: !hasColFilter ? "rgba(0,212,170,0.06)" : "transparent", fontWeight: 600 }}>
                          All
                        </div>
                        {opts.map(opt => {
                          const val = typeof opt === "object" ? opt.value : opt;
                          const label = typeof opt === "object" ? opt.label : opt;
                          const isActive = columnFilters[col.key] === val;
                          return (
                            <div key={val} onClick={() => { setColumnFilters(f => ({ ...f, [col.key]: val })); setOpenFilterCol(null); }}
                              style={{ padding: "6px 10px", fontSize: 11, color: isActive ? "#00D4AA" : "#F0F2F5",
                                cursor: "pointer", borderRadius: 4, background: isActive ? "rgba(0,212,170,0.08)" : "transparent",
                                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                              {label}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, rowIdx) => {
              const sc = resolveStatusColor(s);
              const isSelected = selectedShipment?.id === s.id;
              const isFTL = s.moveType === "FTL";
              const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
              const tracking = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
              const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
              const pu = splitDateTime(s.pickupDate);
              const del = splitDateTime(s.deliveryDate);
              const isInlineEditing = inlineEditId === s.id;
              const inlineInputStyle = { background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 4, color: "#F0F2F5", padding: "2px 5px", fontSize: 11, width: 90, outline: "none", fontFamily: "'JetBrains Mono', monospace" };
              const visCols = DISPATCH_COLS.filter(c => isColVisible(c.key));
              const visColKeys = visCols.map(c => c.key);
              const cellStyleFor = (key) => { const ci = visColKeys.indexOf(key); return { padding: "5px 8px", borderBottom: "1px solid rgba(255,255,255,0.06)", borderRight: ci < visCols.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none" }; };
              const zebraBg = zebraStripe && rowIdx % 2 === 1 ? "rgba(255,255,255,0.025)" : "transparent";
              const dispTermInfo = parseTerminalNotes(s.botAlert);
              const termBg = dispTermInfo?.isReady ? "rgba(34,197,94,0.06)" : dispTermInfo?.hasHolds ? "rgba(239,68,68,0.05)" : null;
              const rowBg = isSelected ? `${sc.main}10` : termBg || zebraBg;
              return (
                <tr key={s.id} className={`row-hover${highlightedEfj === s.efj ? " row-highlight-pulse" : ""}`}
                  style={{ cursor: "default", background: highlightedEfj === s.efj ? undefined : rowBg }}>
                  <td style={{ padding: "5px 4px", width: 24, textAlign: "center", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                    <button onClick={() => handleLoadClick(s)} title="Open details"
                      style={{ background: "none", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 13, padding: "2px 4px", borderRadius: 4, lineHeight: 1, fontFamily: "inherit" }}
                      onMouseEnter={e => e.currentTarget.style.color = "#00D4AA"} onMouseLeave={e => e.currentTarget.style.color = "#5A6478"}>{"\u203A"}</button>
                  </td>
                  {isColVisible("account") && <td style={{ ...cellStyleFor("account"), color: "#F0F2F5", fontSize: 11, fontWeight: 600 }}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("account"); setInlineEditValue(s.account || ""); }}>
                    {isInlineEditing && inlineEditField === "account" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleFieldUpdate(s, "account", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "account", s.id, () => handleFieldUpdate(s, "account", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 75, fontWeight: 600 }} onClick={e => e.stopPropagation()} />
                    ) : (
                      <span style={{ cursor: "text" }}>{s.account || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("status") && <td style={{ ...cellStyleFor("status"), position: "relative" }}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                    {isInlineEditing && inlineEditField === "status" ? (
                      <div className="inline-status-dd" style={{ position: "absolute", top: "100%", left: 0, zIndex: Z.inlineEdit, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 280, overflowY: "auto", minWidth: 120 }}>
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
                  </td>}
                  {isColVisible("efj") && <td style={cellStyleFor("efj")}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("efj"); setInlineEditValue(s.efj || ""); }}>
                    {isInlineEditing && inlineEditField === "efj" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleFieldUpdate(s, "efj", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "efj", s.id, () => handleFieldUpdate(s, "efj", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 85, fontWeight: 600, color: "#00D4AA" }} onClick={e => e.stopPropagation()} />
                    ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11, cursor: "text" }}>{s.loadNumber}</span>
                      {s.playbookLaneCode && <span title={`Playbook: ${s.playbookLaneCode}`} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 14, height: 14, borderRadius: 3, background: "rgba(0,212,170,0.15)", flexShrink: 0, cursor: "default" }}><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#00D4AA" strokeWidth="2.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span>}
                      {!s.synced && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fbbf24", display: "inline-block", animation: "pulse-glow 1s ease infinite" }} />}
                      <DocIndicators docs={docs} />
                      {dispTermInfo?.hasHolds && (
                        <span title={s.botAlert} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 14, height: 14, background: "#EF4444", borderRadius: 3, animation: "alert-pulse 1.8s ease-in-out infinite", flexShrink: 0, cursor: "default" }}>
                          <svg viewBox="0 0 24 24" fill="white" style={{ width: 9, height: 9 }}><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>
                        </span>
                      )}
                      {s.email_count > 0 && (
                        <span title={`${s.email_count} email${s.email_count > 1 ? "s" : ""}${s.email_max_priority >= 4 ? " (urgent)" : ""}`}
                          style={{ fontSize: 8, padding: "0 4px", borderRadius: 8, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
                            background: s.email_max_priority >= 4 ? "rgba(249,115,22,0.15)" : "rgba(139,149,168,0.10)",
                            color: s.email_max_priority >= 4 ? "#F97316" : "#5A6478",
                            border: s.email_max_priority >= 4 ? "1px solid rgba(249,115,22,0.20)" : "none" }}>
                          &#9993;{s.email_count}
                        </span>
                      )}
                    </div>
                    )}
                  </td>}
                  {isColVisible("container") && <td style={{ ...cellStyleFor("container"), fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#F0F2F5" }}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("container"); setInlineEditValue(s.container || ""); }}>
                    {isInlineEditing && inlineEditField === "container" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleFieldUpdate(s, "container", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "container", s.id, () => handleFieldUpdate(s, "container", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                    ) : (
                      <span style={{ cursor: "text" }}>{s.container || "\u2014"}</span>
                    )}
                  </td>}
                  {hasFTL && isColVisible("mpStatus") && <td style={cellStyleFor("mpStatus")}>
                    {(isFTL || s.mpStatus) ? <TrackingBadge tracking={tracking} mpStatus={s.mpStatus || tracking?.mpStatus} mpDisplayStatus={s.mpDisplayStatus || tracking?.mpDisplayStatus} mpDisplayDetail={s.mpDisplayDetail || tracking?.mpDisplayDetail} mpLastUpdated={s.mpLastUpdated} /> : <span style={{ color: "#5A6478", fontSize: 11, fontStyle: "italic" }}>No MP</span>}
                  </td>}
                  {isColVisible("pickup") && <td style={cellStyleFor("pickup")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                    {isInlineEditing && inlineEditField === "pickup" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                          onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                          onKeyDown={e => inlineKeyDown(e, "pickup", s.id, () => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } })}
                          style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                      </div>
                    ) : isInlineEditing && inlineEditField === "pickupTime" ? (
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
                  </td>}
                  {isColVisible("origin") && <td style={{ ...cellStyleFor("origin"), fontSize: 11, color: "#F0F2F5", fontWeight: 500, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.origin}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("origin"); setInlineEditValue(s.origin || ""); }}>
                    {isInlineEditing && inlineEditField === "origin" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleFieldUpdate(s, "origin", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "origin", s.id, () => handleFieldUpdate(s, "origin", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                    ) : (
                      <span style={{ cursor: "text" }}>{s.origin || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("destination") && <td style={{ ...cellStyleFor("destination"), fontSize: 11, color: "#F0F2F5", fontWeight: 500, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.destination}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("destination"); setInlineEditValue(s.destination || ""); }}>
                    {isInlineEditing && inlineEditField === "destination" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleFieldUpdate(s, "destination", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "destination", s.id, () => handleFieldUpdate(s, "destination", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 110 }} onClick={e => e.stopPropagation()} />
                    ) : (
                      <span style={{ cursor: "text" }}>{s.destination || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("delivery") && <td style={cellStyleFor("delivery")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                    {isInlineEditing && inlineEditField === "delivery" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                          onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                          onKeyDown={e => inlineKeyDown(e, "delivery", s.id, () => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } })}
                          style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                      </div>
                    ) : isInlineEditing && inlineEditField === "deliveryTime" ? (
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
                  </td>}
                  {isColVisible("truckType") && <td style={cellStyleFor("truckType")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("truckType"); setInlineEditValue(s.truckType || ""); }}>
                    {isInlineEditing && inlineEditField === "truckType" ? (
                      <select autoFocus value={inlineEditValue}
                        onChange={e => { const v = e.target.value; setInlineEditValue(v); handleMetadataUpdate(s, "truckType", v); setInlineEditId(null); }}
                        onBlur={() => setInlineEditId(null)}
                        onKeyDown={e => { if (e.key === "Escape") setInlineEditId(null); }}
                        onClick={e => e.stopPropagation()}
                        style={{ ...inlineInputStyle, width: 80, cursor: "pointer" }}>
                        {TRUCK_TYPES.map(t => <option key={t} value={t}>{t || "\u2014"}</option>)}
                      </select>
                    ) : (
                      <span style={{ fontSize: 11, color: s.truckType ? "#F0F2F5" : "#3D4557", cursor: "pointer" }}>{s.truckType || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("trailer") && <td style={cellStyleFor("trailer")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("trailer"); setInlineEditValue(s.trailerNumber || tracking?.trailer || ""); }}>
                    {isInlineEditing && inlineEditField === "trailer" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "trailer", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "trailer", s.id, () => handleDriverFieldUpdate(s, "trailer", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 70 }} onClick={e => e.stopPropagation()} placeholder="Trailer" />
                    ) : (
                      <span style={{ fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>{s.trailerNumber || tracking?.trailer || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("driverPhone") && <td style={cellStyleFor("driverPhone")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("driverPhone"); setInlineEditValue(s.driverPhone || tracking?.driverPhone || ""); }}>
                    {isInlineEditing && inlineEditField === "driverPhone" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "driverPhone", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "driverPhone", s.id, () => handleDriverFieldUpdate(s, "driverPhone", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} placeholder="Phone" />
                    ) : (
                      <span style={{ fontSize: 11, color: (s.driverPhone || tracking?.driverPhone) ? "#F0F2F5" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>{s.driverPhone || tracking?.driverPhone || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("carrierEmail") && <td style={cellStyleFor("carrierEmail")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrierEmail"); setInlineEditValue(s.carrierEmail || ""); }}>
                    {isInlineEditing && inlineEditField === "carrierEmail" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "carrierEmail", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "carrierEmail", s.id, () => handleDriverFieldUpdate(s, "carrierEmail", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="email@carrier.com" />
                    ) : (
                      <span style={{ fontSize: 11, color: s.carrierEmail ? "#8B95A8" : "#3D4557", maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.carrierEmail || ""}>{s.carrierEmail || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("customerRate") && <td style={cellStyleFor("customerRate")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("customerRate"); setInlineEditValue(s.customerRate || ""); }}>
                    {isInlineEditing && inlineEditField === "customerRate" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleMetadataUpdate(s, "customerRate", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "customerRate", s.id, () => handleMetadataUpdate(s, "customerRate", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 65 }} onClick={e => e.stopPropagation()} placeholder="$0.00" />
                    ) : (
                      <span style={{ fontSize: 11, color: s.customerRate ? "#22C55E" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", fontWeight: s.customerRate ? 600 : 400 }}>{s.customerRate || "\u2014"}</span>
                    )}
                  </td>}
                  {isColVisible("margin") && <td style={cellStyleFor("margin")}>
                    {(() => { const mgn = calcMarginPct(s.customerRate, s.carrierPay); return mgn !== null ? <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: mgn < 0 ? "#EF4444" : mgn < 10 ? "#F59E0B" : "#22C55E" }}>{mgn}%</span> : <span style={{ color: "#3D4557", fontSize: 11 }}>{"\u2014"}</span>; })()}
                  </td>}
                  {isColVisible("notes") && <td style={cellStyleFor("notes")} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("notes"); setInlineEditValue(s.notes || ""); }}>
                    {isInlineEditing && inlineEditField === "notes" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleMetadataUpdate(s, "notes", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => inlineKeyDown(e, "notes", s.id, () => handleMetadataUpdate(s, "notes", inlineEditValue))}
                        style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="Add note..." />
                    ) : parseTerminalNotes(s.botAlert) ? (
                      <TerminalBadge notes={s.notes} />
                    ) : (
                      <span style={{ fontSize: 11, color: s.notes ? "#F0F2F5" : "#3D4557", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.notes || ""}>{s.notes || "\u2014"}</span>
                    )}
                  </td>}
                </tr>
              );
            })}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
            <div style={{ fontSize: 30, marginBottom: 8, opacity: 0.3 }}>{"\u25CE"}</div>
            <div style={{ fontSize: 12, fontWeight: 600 }}>No loads match filters</div>
          </div>
        )}
      </div>

      {/* Dead code blocks — old slide-over and preview modal now handled by LoadSlideOver */}
      {false && selectedShipment && (<></>)}
      {false && previewDoc && (<></>)}
    </div>
  );
}
