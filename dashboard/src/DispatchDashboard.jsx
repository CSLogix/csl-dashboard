import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "./store";

// Helpers
import { apiFetch, API_BASE } from "./helpers/api";
import { GLOBAL_STYLES } from "./styles";
import {
  STATUSES, FTL_STATUSES, BILLING_STATUSES,
  STATUS_COLORS, FTL_STATUS_COLORS, BILLING_STATUS_COLORS,
  ACCOUNT_COLORS, NAV_ITEMS, REP_ACCOUNTS, ALL_REP_NAMES,
  ALERT_TYPES, Z, ALL_STATUSES_COMBINED,
} from "./helpers/constants";
import {
  normalizeStatus, mapShipment, isFTLShipment,
  resolveStatusLabel, resolveStatusColor, resolveRepForShipment,
  isDateToday, isDateTomorrow, isDateYesterday, isDatePast,
  parseDate, loadDismissedAlerts, saveDismissedAlerts,
  generateSnapshotAlerts, useIsMobile,
} from "./helpers/utils";

// Components
import ClockDisplay from "./components/ClockDisplay";
import CommandPalette from "./components/CommandPalette";
import AskAIOverlay from "./components/AskAIOverlay";

// Views
import OverviewView from "./views/OverviewView";
import RepDashboardView from "./views/RepDashboardView";
import DispatchView from "./views/DispatchView";
import LoadSlideOver from "./views/LoadSlideOver";
import HistoryView from "./views/HistoryView";
import InboxView from "./views/InboxView";
import AnalyticsView from "./views/AnalyticsView";
import BillingView from "./views/BillingView";
import RateIQView from "./views/RateIQView";
import BOLGeneratorView from "./views/BOLGeneratorView";
import PlaybooksView from "./views/PlaybooksView";
import UserManagementView from "./views/UserManagementView";
import AddForm from "./views/AddForm";

export default function DispatchDashboard() {
  // ── Core state from Zustand store (shared across components) ──
  const {
    shipments, setShipments, accounts, setAccounts,
    botStatus, setBotStatus, botHealth, setBotHealth, cronStatus, setCronStatus,
    apiStats, setApiStats, accountOverview, setAccountOverview,
    trackingSummary, setTrackingSummary, docSummary, setDocSummary,
    unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats,
    repProfiles, setRepProfiles, eventAlerts, setEventAlerts,
    sheetLog, setSheetLog, lastSyncTime, setLastSyncTime,
    loaded, setLoaded, apiError, setApiError,
    activeView, setActiveView, selectedRep, setSelectedRep,
    selectedShipment, setSelectedShipment,
    expandEmailsOnOpen, setExpandEmailsOnOpen,
    highlightedEfj, setHighlightedEfj,
    activeStatus, setActiveStatus, activeAccount, setActiveAccount,
    activeRep, setActiveRep, searchQuery, setSearchQuery,
    moveTypeFilter, setMoveTypeFilter, dateFilter, setDateFilter,
    dateRangeField, setDateRangeField, dateRangeStart, setDateRangeStart,
    dateRangeEnd, setDateRangeEnd,
    dataSource, setDataSource, systemHealth, setSystemHealth,
    currentUser, setCurrentUser,
  } = useAppStore();

  const isMobile = useIsMobile();

  // Clean up stale localStorage keys from old builds
  useState(() => { try { localStorage.removeItem("csl_preferred_rep"); } catch {} });

  // ── Local-only UI state (not shared) ──
  const [dismissedAlertIds, setDismissedAlertIds] = useState(() => loadDismissedAlerts());
  const prevStatusMapRef = useRef({});
  const prevDocMapRef = useRef({});
  const prevRateAlertsRef = useRef(new Set());
  const [inboxThreads, setInboxThreads] = useState([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showParseModal, setShowParseModal] = useState(false);
  const [parseText, setParseText] = useState("");
  const [isParsing, setIsParsing] = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [parseError, setParseError] = useState(null);
  const [editField, setEditField] = useState(null);
  const [editValue, setEditValue] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [podUploading, setPodUploading] = useState(false);
  const [podUploadMsg, setPodUploadMsg] = useState(null);
  const [carrierDirectory, setCarrierDirectory] = useState([]);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [cmdkQuery, setCmdkQuery] = useState("");
  const [cmdkIndex, setCmdkIndex] = useState(0);
  const { askAIOpen, setAskAIOpen, askAIInitialQuery, setAskAIInitialQuery, askAIInitialFiles, setAskAIInitialFiles } = useAppStore();
  const [askAIDragOver, setAskAIDragOver] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [pwForm, setPwForm] = useState({ current: "", newPw: "", confirm: "" });
  const [pwError, setPwError] = useState(null);
  const [pwSuccess, setPwSuccess] = useState(false);
  const [repScoreboard, setRepScoreboard] = useState([]);
  const { accountHealth, setAccountHealth } = useAppStore();
  const { emailDrafts, setEmailDrafts, draftToast, setDraftToast } = useAppStore();
  const [showDraftModal, setShowDraftModal] = useState(false);
  const [activeDraft, setActiveDraft] = useState(null);  // full draft being reviewed
  const [draftSending, setDraftSending] = useState(false);

  // Fetch rep scoreboard
  const fetchScoreboard = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/rep-scoreboard`);
      if (res.ok) { const data = await res.json(); setRepScoreboard(Array.isArray(data) ? data : data.scoreboard || []); }
    } catch {}
  }, []);

  // Fetch account health
  const fetchAccountHealth = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/account-health`);
      if (res.ok) { const data = await res.json(); setAccountHealth(Array.isArray(data) ? data : data.accounts || []); }
    } catch {}
  }, []);

  // Fetch pending email drafts
  const fetchEmailDrafts = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/email-drafts?status=draft`);
      if (res.ok) { const data = await res.json(); setEmailDrafts(Array.isArray(data) ? data : data.drafts || []); }
    } catch {}
  }, []);

  // Fetch team profiles (avatars)
  const fetchProfiles = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/team/profiles`);
      if (res.ok) { const data = await res.json(); setRepProfiles(data.profiles || {}); }
    } catch {}
  }, []);

  const fetchData = useCallback(async () => {
    const src = useAppStore.getState().dataSource;
    const isSheets = src === "sheets";
    try {
      const [shipmentsRes, statsRes, botRes, accountsRes, trackRes, docRes] = await Promise.allSettled([
        apiFetch(`${API_BASE}/api/${isSheets ? "shipments" : "v2/shipments"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/${isSheets ? "stats" : "v2/stats"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/bot-status`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/${isSheets ? "accounts" : "v2/accounts"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/shipments/tracking-summary`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/shipments/document-summary`).then(r => r.json()),
      ]);
      if (shipmentsRes.status === "fulfilled") {
        const mapped = shipmentsRes.value.shipments.map(mapShipment);
        setShipments(prev => {
          const prevMap = new Map(prev.map(s => [s.efj, s]));
          return mapped.map(s => {
            const existing = prevMap.get(s.efj);
            if (existing && !existing.synced) return { ...existing, id: s.id };
            return s;
          });
        });
        const acctNames = [...new Set(mapped.map(s => s.account).filter(Boolean))].sort();
        setAccounts(["All Accounts", ...acctNames]);
      }
      if (statsRes.status === "fulfilled") setApiStats(statsRes.value);
      if (botRes.status === "fulfilled") {
        const bots = Array.isArray(botRes.value) ? botRes.value : (botRes.value.services || []);
        setBotStatus(bots);
      }
      if (accountsRes.status === "fulfilled") {
        const accts = accountsRes.value.accounts || [];
        setAccountOverview(accts.map((a, i) => ({ name: a.name, loads: a.active, alerts: a.alerts || 0, color: ACCOUNT_COLORS[i % ACCOUNT_COLORS.length] })));
      }
      if (trackRes.status === "fulfilled") setTrackingSummary(trackRes.value.tracking || {});
      if (docRes.status === "fulfilled") setDocSummary(docRes.value.documents || {});
      // Detect status changes from backend
      if (shipmentsRes.status === "fulfilled") {
        const mapped2 = shipmentsRes.value.shipments.map(mapShipment);
        const newStatusMap = {};
        mapped2.forEach(s => { if (s.id) newStatusMap[s.id] = s.status; });
        const prev = prevStatusMapRef.current;
        if (Object.keys(prev).length > 0) {
          const changeAlerts = [];
          for (const s of mapped2) {
            if (!s.id) continue;
            const old = prev[s.id];
            if (old && old !== s.status) {
              const sList2 = isFTLShipment(s) ? FTL_STATUSES : STATUSES;
              const label = sList2.find(st => st.key === s.status)?.label || BILLING_STATUSES.find(st => st.key === s.status)?.label || s.rawStatus || s.status;
              changeAlerts.push({ id: `status_change-${s.id}-${s.status}-${Date.now()}`, type: ALERT_TYPES.STATUS_CHANGE,
                efj: s.efj, account: s.account, rep: resolveRepForShipment(s),
                message: `${s.loadNumber || s.efj} \u2192 ${label}`,
                detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
            }
          }
          if (changeAlerts.length > 0) setEventAlerts(p => [...changeAlerts, ...p].slice(0, 200));
        }
        prevStatusMapRef.current = newStatusMap;
      }
      // Detect new documents indexed
      if (docRes.status === "fulfilled") {
        const newDocs = docRes.value.documents || {};
        const prevDocs = prevDocMapRef.current;
        if (Object.keys(prevDocs).length > 0 && shipmentsRes.status === "fulfilled") {
          const mapped3 = shipmentsRes.value.shipments.map(mapShipment);
          const docAlerts = [];
          for (const [efj, docs] of Object.entries(newDocs)) {
            const oldDoc = prevDocs[efj] || {};
            for (const [docType, val] of Object.entries(docs)) {
              if (val && !oldDoc[docType]) {
                const s = mapped3.find(sh => sh.efj === efj || sh.efj?.replace(/^EFJ\s*/i, "") === efj);
                if (s) {
                  const typeLabel = docType.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                  docAlerts.push({ id: `doc_indexed-${efj}-${docType}-${Date.now()}`, type: ALERT_TYPES.DOC_INDEXED,
                    efj: s.efj, account: s.account, rep: resolveRepForShipment(s),
                    message: `${typeLabel} indexed for ${s.loadNumber || s.efj}`,
                    detail: s.account, timestamp: Date.now(), shipmentId: s.id });
                }
              }
            }
          }
          if (docAlerts.length > 0) setEventAlerts(p => [...docAlerts, ...p].slice(0, 200));
        }
        prevDocMapRef.current = newDocs;
      }
      // Fetch unbilled stats (silently fail if endpoint not ready)
      try {
        const ubRes = await apiFetch(`${API_BASE}/api/unbilled/stats`);
        if (ubRes.ok) setUnbilledStats(await ubRes.json());
      } catch {}
      // Fetch bot health metrics + cron status
      try {
        const [bhRes, csRes] = await Promise.allSettled([
          apiFetch(`${API_BASE}/api/bot-health`).then(r => r.ok ? r.json() : null),
          apiFetch(`${API_BASE}/api/cron-status`).then(r => r.ok ? r.json() : null),
        ]);
        if (bhRes.status === "fulfilled" && bhRes.value) setBotHealth(bhRes.value);
        if (csRes.status === "fulfilled" && csRes.value) setCronStatus(csRes.value);
      } catch {}
      // Fetch carrier directory for dray slide-over carrier info
      try {
        const crRes = await apiFetch(`${API_BASE}/api/carriers`);
        if (crRes.ok) { const crData = await crRes.json(); setCarrierDirectory(crData.carriers || []); }
      } catch {}
      // Fetch rate response alerts + inbox threads for email integration
      try {
        const [rateRes, inboxRes] = await Promise.allSettled([
          apiFetch(`${API_BASE}/api/rate-response-alerts`).then(r => r.ok ? r.json() : null),
          apiFetch(`${API_BASE}/api/inbox?days=3`).then(r => r.ok ? r.json() : null),
        ]);
        if (rateRes.status === "fulfilled" && rateRes.value) {
          const alerts = rateRes.value.alerts || [];
          const prev = prevRateAlertsRef.current;
          const newAlerts = [];
          for (const a of alerts) {
            const key = `${a.id}`;
            if (!prev.has(key)) {
              const alertType = a.email_type === "payment_escalation" ? ALERT_TYPES.PAYMENT_ESCALATION
                : (a.email_type === "carrier_invoice" || a.email_type === "carrier_rate_confirmation") ? ALERT_TYPES.SEND_FINAL_CHARGES
                : ALERT_TYPES.RATE_RESPONSE;
              newAlerts.push({
                id: `${alertType}-${a.id}-${Date.now()}`, type: alertType,
                efj: a.efj, account: "", rep: a.rep || "",
                message: alertType === ALERT_TYPES.PAYMENT_ESCALATION ? `Payment alert: ${a.efj || "Unknown"} \u2014 ${a.subject || ""}`
                  : alertType === ALERT_TYPES.SEND_FINAL_CHARGES ? `Send final charges: ${a.efj || "Unknown"}`
                  : `Rate response: ${a.sender || "Carrier"} on ${a.lane || a.efj || ""}`,
                detail: a.summary || a.subject || "", timestamp: new Date(a.sent_at || Date.now()).getTime(),
              });
            }
          }
          if (prev.size > 0 && newAlerts.length > 0) setEventAlerts(p => [...newAlerts, ...p].slice(0, 200));
          prevRateAlertsRef.current = new Set(alerts.map(a => `${a.id}`));
        }
        if (inboxRes.status === "fulfilled" && inboxRes.value) {
          setInboxThreads(inboxRes.value.threads || []);
        }
      } catch {}
      setLastSyncTime(new Date());
      setApiError(null);
    } catch (err) { console.error("API fetch error:", err); setApiError(err.message); }
  }, []);

  const refreshDocSummary = useCallback(async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/shipments/document-summary`);
      if (r.ok) { const data = await r.json(); setDocSummary(data.documents || {}); }
    } catch {}
  }, []);

  useEffect(() => {
    // Fetch current user identity
    apiFetch(`${API_BASE}/api/me`).then(r => r.ok ? r.json() : null).then(u => { if (u) setCurrentUser(u); }).catch(() => {});
    fetchData().then(() => setLoaded(true));
    fetchProfiles();
    fetchScoreboard();
    fetchAccountHealth();
    fetchEmailDrafts();
    const fallback = setTimeout(() => setLoaded(true), 10000);
    return () => clearTimeout(fallback);
  }, [fetchData, fetchProfiles, fetchScoreboard, fetchAccountHealth, fetchEmailDrafts]);
  useEffect(() => { const i = setInterval(fetchData, 90000); return () => clearInterval(i); }, [fetchData]);
  // Fast-poll tracking summary (30s) so MP webhook updates appear quickly in dispatch table
  useEffect(() => {
    const i = setInterval(async () => {
      try {
        const r = await apiFetch(`${API_BASE}/api/shipments/tracking-summary`);
        if (r.ok) { const d = await r.json(); setTrackingSummary(d.tracking || {}); }
      } catch {}
    }, 30000);
    return () => clearInterval(i);
  }, [setTrackingSummary]);
  useEffect(() => { const i = setInterval(fetchScoreboard, 120000); return () => clearInterval(i); }, [fetchScoreboard]);
  useEffect(() => { const i = setInterval(fetchAccountHealth, 120000); return () => clearInterval(i); }, [fetchAccountHealth]);
  useEffect(() => { const i = setInterval(fetchEmailDrafts, 30000); return () => clearInterval(i); }, [fetchEmailDrafts]);

  // Deep link support: ?view=billing&load=EFJ-XXXX
  useEffect(() => {
    if (!loaded || !shipments.length) return;
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view");
    const loadEfj = params.get("load");
    if (view) {
      setActiveView(view);
      if (loadEfj) {
        const match = shipments.find(s => s.efj === loadEfj);
        if (match) setSelectedShipment(match);
      }
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [loaded, shipments.length]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const handler = (e) => setSidebarCollapsed(e.matches);
    handler(mq); mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Global keyboard shortcuts: Ctrl+K Ask AI, Ctrl+F search, ESC close modals
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+K / Cmd+K → toggle Ask AI overlay
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setAskAIOpen(prev => !prev);
        return;
      }
      // Ctrl+F / Cmd+F → toggle command palette (shipment search)
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setCmdkOpen(prev => !prev);
        setCmdkQuery("");
        setCmdkIndex(0);
        return;
      }
      if (e.key === "Escape") {
        if (askAIOpen) { setAskAIOpen(false); return; }
        if (cmdkOpen) { setCmdkOpen(false); return; }
        if (selectedShipment) { setSelectedShipment(null); return; }
        if (showParseModal) { setShowParseModal(false); setParseResult(null); setParseError(null); return; }
        if (showAddForm) { setShowAddForm(false); return; }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedShipment, showAddForm, showParseModal, cmdkOpen, askAIOpen]);

  const addSheetLog = useCallback((msg) => {
    setSheetLog(prev => [{ time: new Date().toLocaleTimeString(), msg }, ...prev].slice(0, 25));
  }, []);

  const filtered = useMemo(() => (Array.isArray(shipments) ? shipments : []).filter(s => {
    // Move type filter
    if (moveTypeFilter === "ftl" && !isFTLShipment(s)) return false;
    if (moveTypeFilter === "dray" && isFTLShipment(s)) return false;
    if (activeStatus !== "all" && s.status !== activeStatus) return false;
    if (activeAccount !== "All Accounts" && s.account !== activeAccount) return false;
    if (activeRep !== "All Reps") {
      const repMatch = (s.rep || "").toLowerCase() === activeRep.toLowerCase() ||
        s.account.toLowerCase() === activeRep.toLowerCase();
      if (!repMatch) return false;
    }
    if (dateFilter) {
      if (dateFilter === "pickup_today" && (!isDateToday(s.pickupDate) || s.status === "delivered")) return false;
      if (dateFilter === "pickup_tomorrow" && (!isDateTomorrow(s.pickupDate) || s.status === "delivered")) return false;
      if (dateFilter === "delivery_today" && !isDateToday(s.deliveryDate)) return false;
      if (dateFilter === "delivery_tomorrow" && (!isDateTomorrow(s.deliveryDate) || s.status === "delivered")) return false;
      if (dateFilter === "yesterday" && !isDateYesterday(s.pickupDate) && !isDateYesterday(s.deliveryDate)) return false;
    }
    // Date range filter
    if (dateRangeField && dateRangeStart) {
      const fieldKey = dateRangeField === "pickup" ? "pickupDate" : "deliveryDate";
      const val = parseDate(s[fieldKey]);
      if (!val) return false;
      const start = new Date(dateRangeStart + "T00:00:00");
      const end = dateRangeEnd ? new Date(dateRangeEnd + "T23:59:59") : new Date(dateRangeStart + "T23:59:59");
      const d = new Date(val.getFullYear(), val.getMonth(), val.getDate());
      if (d < start || d > end) return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return s.loadNumber.toLowerCase().includes(q) || s.carrier.toLowerCase().includes(q) ||
        s.origin.toLowerCase().includes(q) || s.destination.toLowerCase().includes(q) ||
        s.container.toLowerCase().includes(q) || s.account.toLowerCase().includes(q) ||
        (s.notes || "").toLowerCase().includes(q) || (s.truckType || "").toLowerCase().includes(q);
    }
    return true;
  }), [shipments, activeStatus, activeAccount, activeRep, searchQuery, dateFilter, moveTypeFilter, dateRangeField, dateRangeStart, dateRangeEnd]);

  // Dynamic status counts based on move type filter
  const activeStatusList = useMemo(() => {
    if (moveTypeFilter === "ftl") return FTL_STATUSES;
    if (moveTypeFilter === "dray") return STATUSES;
    return ALL_STATUSES_COMBINED;
  }, [moveTypeFilter]);

  const statusCounts = useMemo(() => {
    // Apply all filters EXCEPT status so counts show per-status within current filter context
    const base = (Array.isArray(shipments) ? shipments : []).filter(s => {
      if (moveTypeFilter === "ftl" && !isFTLShipment(s)) return false;
      if (moveTypeFilter === "dray" && isFTLShipment(s)) return false;
      if (activeAccount !== "All Accounts" && s.account !== activeAccount) return false;
      if (activeRep !== "All Reps") {
        const repMatch = (s.rep || "").toLowerCase() === activeRep.toLowerCase() ||
          s.account.toLowerCase() === activeRep.toLowerCase();
        if (!repMatch) return false;
      }
      if (dateRangeField && dateRangeStart) {
        const fieldKey = dateRangeField === "pickup" ? "pickupDate" : "deliveryDate";
        const val = parseDate(s[fieldKey]);
        if (!val) return false;
        const start = new Date(dateRangeStart + "T00:00:00");
        const end = dateRangeEnd ? new Date(dateRangeEnd + "T23:59:59") : new Date(dateRangeStart + "T23:59:59");
        const d = new Date(val.getFullYear(), val.getMonth(), val.getDate());
        if (d < start || d > end) return false;
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return s.loadNumber.toLowerCase().includes(q) || s.carrier.toLowerCase().includes(q) ||
          s.origin.toLowerCase().includes(q) || s.destination.toLowerCase().includes(q) ||
          s.container.toLowerCase().includes(q) || s.account.toLowerCase().includes(q) ||
          (s.notes || "").toLowerCase().includes(q) || (s.truckType || "").toLowerCase().includes(q);
      }
      return true;
    });
    return activeStatusList.map(s => ({
      ...s, count: s.key === "all" ? base.length : base.filter(sh => sh.status === s.key).length,
    }));
  }, [shipments, activeStatusList, moveTypeFilter, activeAccount, activeRep, searchQuery, dateRangeField, dateRangeStart, dateRangeEnd]);

  const handleStatusUpdate = (shipmentId, newStatus) => {
    const ship = shipments.find(s => s.id === shipmentId);
    if (!ship) return;
    const shipEfj = ship.efj;
    const sList = isFTLShipment(ship) ? FTL_STATUSES : STATUSES;
    const statusLabel = sList.find(st => st.key === newStatus)?.label || BILLING_STATUSES.find(st => st.key === newStatus)?.label || newStatus;
    // Generate event alert
    setEventAlerts(prev => [{ id: `status_change-${shipEfj}-${newStatus}-${Date.now()}`, type: ALERT_TYPES.STATUS_CHANGE,
      efj: shipEfj, account: ship.account, rep: resolveRepForShipment(ship),
      message: `${ship.loadNumber || shipEfj} \u2192 ${statusLabel}`,
      detail: `${ship.account}${ship.carrier ? " | " + ship.carrier : ""}`, timestamp: Date.now(), shipmentId: ship.id,
    }, ...prev].slice(0, 200));
    // Update local state immediately
    setShipments(prev => prev.map(s => s.efj === shipEfj ? { ...s, status: newStatus, rawStatus: statusLabel, synced: false } : s));
    setSelectedShipment(prev => prev && prev.efj === shipEfj ? { ...prev, status: newStatus, rawStatus: statusLabel, synced: false } : prev);
    addSheetLog(`Status -> ${statusLabel} | ${ship.loadNumber}`);
    // Persist to backend
    if (shipEfj) {
      apiFetch(`${API_BASE}/api/v2/load/${shipEfj}/status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      }).then(async r => {
        if (r.ok) {
          const resp = await r.json().catch(() => ({}));
          setShipments(p => p.map(x => x.efj === shipEfj ? { ...x, synced: true } : x));
          setSelectedShipment(prev => prev && prev.efj === shipEfj ? { ...prev, synced: true } : prev);
          addSheetLog(`Synced -> Postgres | ${ship.loadNumber}`);
          if (resp.draft_id) {
            setDraftToast({ id: resp.draft_id, efj: shipEfj, loadNumber: ship.loadNumber });
            fetchEmailDrafts();
            setTimeout(() => setDraftToast(null), 8000);
          }
          // Delivered → auto-transition to Ready to Close Out
          if (newStatus === "delivered") {
            setTimeout(() => handleStatusUpdate(ship.id, "ready_to_close"), 1500);
          }
          // Billed & Closed → remove from active view
          if (newStatus === "billed_closed") {
            setTimeout(() => {
              setShipments(p => p.filter(x => x.efj !== shipEfj));
              setSelectedShipment(null);
            }, 2000);
          }
        } else {
          addSheetLog(`Sync failed (${r.status}) | ${ship.loadNumber}`);
          setShipments(p => p.map(x => x.efj === shipEfj ? { ...x, synced: true } : x));
          setSelectedShipment(prev => prev && prev.efj === shipEfj ? { ...prev, synced: true } : prev);
        }
      }).catch(() => {
        addSheetLog(`Sync error | ${ship.loadNumber}`);
        setShipments(p => p.map(x => x.efj === shipEfj ? { ...x, synced: true } : x));
        setSelectedShipment(prev => prev && prev.efj === shipEfj ? { ...prev, synced: true } : prev);
      });
    }
  };

  const handleFieldEdit = (shipmentId, field, value) => {
    setShipments(prev => prev.map(s => {
      if (s.id === shipmentId) {
        addSheetLog(`${field} updated | ${s.loadNumber}`);
        setTimeout(() => { setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x)); addSheetLog(`Synced | ${s.loadNumber}`); }, 800);
        return { ...s, [field]: value, synced: false };
      }
      return s;
    }));
    setEditField(null);
  };

  // Inline field update — writes to Postgres via POST /api/v2/load/{efj}/update
  const FIELD_TO_PG = { pickup: "pickup_date", delivery: "delivery_date", eta: "eta", lfd: "lfd", carrier: "carrier", driver: "driver", origin: "origin", destination: "destination", status: "status", vessel: "vessel", bol: "bol", return_date: "return_date", ssl: "vessel", container: "container" };
  const handleFieldUpdate = async (shipment, field, value, { toast } = {}) => {
    const stateKey = field === "pickup" ? "pickupDate" : field === "delivery" ? "deliveryDate" : field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    setSelectedShipment(prev => prev && prev.id === shipment.id ? { ...prev, [stateKey]: value, synced: false } : prev);
    if (shipment.efj) {
      const pgField = FIELD_TO_PG[field] || field;
      try {
        const r = await apiFetch(`${API_BASE}/api/v2/load/${shipment.efj}/update`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [pgField]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
          toast?.(`${field.charAt(0).toUpperCase() + field.slice(1)} saved`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); toast?.(`Failed to save ${field}`, "error"); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); toast?.(`Failed to save ${field}`, "error"); }
    } else {
      setTimeout(() => setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s)), 800);
    }
  };

  // Inline metadata update — writes to Postgres via POST /api/v2/load/{efj}/update
  const META_TO_PG = { truckType: "equipment_type", customerRate: "customer_rate", carrierPay: "carrier_pay", notes: "notes" };
  const FIELD_LABELS = { customerRate: "Customer Rate", carrierPay: "Carrier Pay", notes: "Notes", truckType: "Equipment" };
  const handleMetadataUpdate = async (shipment, field, value, { toast } = {}) => {
    const stateKey = field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    setSelectedShipment(prev => prev && prev.id === shipment.id ? { ...prev, [stateKey]: value, synced: false } : prev);
    if (shipment.efj) {
      const pgField = META_TO_PG[field] || field;
      try {
        const r = await apiFetch(`${API_BASE}/api/v2/load/${shipment.efj}/update`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [pgField]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
          toast?.(`${FIELD_LABELS[field] || field} saved`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); toast?.(`Failed to save ${FIELD_LABELS[field] || field}`, "error"); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); toast?.(`Failed to save ${FIELD_LABELS[field] || field}`, "error"); }
    } else {
      setTimeout(() => setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s)), 800);
    }
  };

  // Apply extracted rate quote to shipment (Margin Bridge)
  const handleApplyRate = async (quote, { onApplied } = {}) => {
    if (!selectedShipment?.efj || !quote?.id) return;
    const field = quote._field || "carrier_pay";
    const stateKey = field === "customer_rate" ? "customerRate" : "carrierPay";
    try {
      const res = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/apply-rate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quote_id: quote.id, field }),
      });
      if (res.ok) {
        const data = await res.json();
        setShipments(prev => prev.map(s => s.efj === selectedShipment.efj ? { ...s, [stateKey]: String(data.applied) } : s));
        setSelectedShipment(prev => prev ? { ...prev, [stateKey]: String(data.applied) } : prev);
        onApplied?.();
        addSheetLog(`Rate applied: $${data.applied} (${field}) from ${quote.carrier_name || "carrier"} | ${selectedShipment.efj}`);
      }
    } catch (e) {
      addSheetLog(`Rate apply error | ${selectedShipment.efj}`);
    }
  };

  // Inline driver field update — writes to backend via POST /api/load/{efj}/driver
  const handleDriverFieldUpdate = async (shipment, field, value) => {
    const driverFieldMap = { trailer: "trailerNumber", driverPhone: "driverPhone", carrierEmail: "carrierEmail" };
    const apiFieldMap = { trailer: "trailerNumber", driverPhone: "driverPhone", carrierEmail: "carrierEmail" };
    const stateKey = driverFieldMap[field] || field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    if (shipment.efj) {
      try {
        const r = await apiFetch(`${API_BASE}/api/load/${shipment.efj}/driver`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [apiFieldMap[field] || field]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); }
    }
  };

  const handleQuickParse = async () => {
    if (!parseText.trim()) return;
    setIsParsing(true);
    setParseResult(null);
    setParseError(null);
    try {
      const res = await apiFetch("/api/quick-parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: parseText.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setParseError(err.error || `Parse failed (${res.status})`);
        return;
      }
      const data = await res.json();
      setParseResult(data);
    } catch (e) {
      setParseError("Network error — try again");
    } finally {
      setIsParsing(false);
    }
  };

  const handleAddShipment = async (data) => {
    const { pendingDocs, ...loadData } = data;
    try {
      const res = await apiFetch(`${API_BASE}/api/v2/load/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loadData),
      });
      if (!res.ok) {
        const txt = await res.text();
        addSheetLog(`Add failed (${res.status}) | ${data.efj}`);
        throw new Error(txt);
      }
      const result = await res.json();
      addSheetLog(`New row → Sheet | ${result.efj} (${result.tab})`);
      if (result.playbook_match) {
        addSheetLog(`Playbook matched | ${result.playbook_match.lane_code} → ${result.efj} (carrier: ${result.playbook_match.carrier || "—"})`);
      }

      // Upload pending documents after load creation
      if (pendingDocs && pendingDocs.length > 0) {
        for (const doc of pendingDocs) {
          try {
            const fd = new FormData();
            fd.append("file", doc.file);
            fd.append("doc_type", doc.docType);
            await apiFetch(`${API_BASE}/api/load/${result.efj}/documents`, { method: "POST", body: fd });
            addSheetLog(`Doc uploaded | ${doc.file.name} → ${result.efj}`);
          } catch (docErr) {
            addSheetLog(`Doc upload failed | ${doc.file.name}: ${docErr.message}`);
          }
        }
      }

      setShowAddForm(false);
      fetchData();
    } catch (err) {
      addSheetLog(`Add error: ${err.message}`);
    }
  };

  const handleLoadClick = (s, opts) => {
    setSelectedShipment(s);
    if (opts?.expandEmails) setExpandEmailsOnOpen(true);
    if (opts?.highlight) {
      setHighlightedEfj(s.efj);
      setTimeout(() => setHighlightedEfj(null), 3000);
    }
  };

  const activeLoads = useMemo(() => filtered.filter(s => !["delivered", "issue", "cancelled", "cancelled_tonu", "empty_return", "driver_paid"].includes(s.status)).length, [filtered]);
  const inTransit = useMemo(() => filtered.filter(s => s.status === "in_transit").length, [filtered]);
  const deliveredCount = useMemo(() => filtered.filter(s => s.status === "delivered").length, [filtered]);
  const issueCount = useMemo(() => filtered.filter(s => s.status === "issue").length, [filtered]);
  const sidebarW = sidebarCollapsed ? 56 : 72;

  // Alert system
  const snapshotAlerts = useMemo(() => generateSnapshotAlerts(shipments, trackingSummary, docSummary), [shipments, trackingSummary, docSummary]);
  const allAlerts = useMemo(() => [...eventAlerts, ...snapshotAlerts].filter(a => !dismissedAlertIds.includes(a.id)), [eventAlerts, snapshotAlerts, dismissedAlertIds]);
  const handleDismissAlert = useCallback((id) => {
    setDismissedAlertIds(prev => { const next = [...prev, id]; saveDismissedAlerts(next); return next; });
  }, []);
  const handleDismissAllAlerts = useCallback(() => {
    const ids = allAlerts.map(a => a.id);
    setDismissedAlertIds(prev => { const next = [...new Set([...prev, ...ids])]; saveDismissedAlerts(next); return next; });
  }, [allAlerts]);

  const goToRepDashboard = (repName) => { setSelectedRep(repName); };
  const goBackFromRep = () => { setSelectedRep(null); };

  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", background: "#0A0E17", color: "#F0F2F5", minHeight: "100vh", display: "flex", position: "relative", overflow: "hidden" }}>
      <style>{GLOBAL_STYLES}</style>

      {/* Ambient BG */}
      <div aria-hidden="true" style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: Z.base }}>
        <div style={{ position: "absolute", top: "-20%", left: "-10%", width: "50%", height: "50%", background: "radial-gradient(circle, #00D4AA06 0%, transparent 70%)" }} />
        <div style={{ position: "absolute", bottom: "-20%", right: "-10%", width: "60%", height: "60%", background: "radial-gradient(circle, #0088E806 0%, transparent 70%)" }} />
      </div>

      {/* ═══ SIDEBAR ═══ */}
      <div className="dash-sidebar" style={{ width: sidebarW, minHeight: "100vh", background: "#0D1119", borderRight: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 16, gap: 4, position: "relative", zIndex: Z.sidebar, flexShrink: 0 }}>
        <div style={{ width: 52, height: 52, borderRadius: 12, background: "#0F1A14", border: "1px solid rgba(0,222,180,0.25)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, animation: "glow-pulse 3s ease infinite", cursor: "pointer", overflow: "hidden", padding: 2, boxShadow: "0 0 20px rgba(0,212,170,0.15)" }}
          onClick={() => { setActiveView("dashboard"); setSelectedRep(null); }}>
          <img src="/logo.svg" alt="CSL" style={{ width: 44, height: 44, objectFit: "contain", filter: "hue-rotate(-15deg) saturate(1.3)" }} />
        </div>
        {NAV_ITEMS.map(item => {
          const isActive = activeView === item.key;
          return (
            <button key={item.key} className="nav-item"
              aria-label={item.label}
              aria-current={isActive ? "page" : undefined}
              onClick={() => { setActiveView(item.key); setSelectedRep(null); }}
              style={{ width: sidebarW - 12, padding: "10px 0", borderRadius: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
                background: isActive ? "rgba(0,212,170,0.10)" : "transparent",
                borderLeft: isActive ? "3px solid #00D4AA" : "3px solid transparent",
                color: isActive ? "#00D4AA" : "#8B95A8" }}>
              <svg aria-hidden="true" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d={item.icon} /></svg>
              {!sidebarCollapsed && <span aria-hidden="true" style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.5px" }}>{item.label}</span>}
            </button>
          );
        })}
      </div>

      {/* ═══ COMMAND PALETTE ═══ */}
      <CommandPalette open={cmdkOpen} query={cmdkQuery} setQuery={setCmdkQuery}
        index={cmdkIndex} setIndex={setCmdkIndex} shipments={shipments}
        onSelect={(s) => handleLoadClick(s)} onClose={() => setCmdkOpen(false)} />

      <AskAIOverlay open={askAIOpen} onClose={() => { setAskAIOpen(false); setAskAIInitialQuery(null); setAskAIInitialFiles(null); }}
        API_BASE={API_BASE} apiFetchFn={apiFetch}
        initialQuery={askAIInitialQuery} onConsumeInitialQuery={() => setAskAIInitialQuery(null)}
        initialFiles={askAIInitialFiles} onConsumeInitialFiles={() => setAskAIInitialFiles(null)}
        onBulkCreated={() => fetchData()} />

      {/* ═══ MAIN CONTENT ═══ */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: Z.main }}>
        {/* Top Bar */}
        <div className="dash-topbar" style={{ padding: "12px 24px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.08)", background: "#0D1119" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 16, fontWeight: 800, background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>COMMON SENSE</span>
            <span style={{ fontSize: 10, color: "#8B95A8", fontWeight: 400, letterSpacing: "2px", textTransform: "uppercase" }}>Logistics</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {dataSource === "sheets" && (
              <div className="glass" style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 100, fontSize: 10, color: "#f59e0b", fontWeight: 600, border: "1px solid rgba(245,158,11,0.3)", background: "rgba(245,158,11,0.08)" }}>
                SHEETS MODE
              </div>
            )}
            <button onClick={() => setAskAIOpen(true)}
              title="Ask AI — Ctrl+K — drag files or inbox emails here"
              onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setAskAIDragOver(true); }}
              onDragLeave={() => setAskAIDragOver(false)}
              onDrop={e => {
                e.preventDefault();
                setAskAIDragOver(false);
                // Check for file drops first (PDF from Outlook/desktop)
                const files = Array.from(e.dataTransfer.files || []);
                if (files.length > 0) {
                  setAskAIInitialFiles(files);
                  setAskAIOpen(true);
                  return;
                }
                // Check for document hub drag
                try {
                  const data = JSON.parse(e.dataTransfer.getData("application/json"));
                  if (data.type === "document") {
                    // Fetch the document as a blob and pass as file
                    (async () => {
                      try {
                        const res = await apiFetch(`${API_BASE}/api/load/${data.efj}/documents/${data.doc_id}/download?inline=true`);
                        const blob = await res.blob();
                        const file = new File([blob], data.original_name || "document.pdf", { type: blob.type });
                        setAskAIInitialFiles([file]);
                        setAskAIOpen(true);
                      } catch { setAskAIOpen(true); }
                    })();
                    return;
                  }
                  // Inbox email thread drag (existing behavior)
                  const thread = data;
                  const msgs = (thread.messages || []).map(m =>
                    `[${m.direction === "sent" ? "CSL" : "External"}] ${(m.sender || "").replace(/<[^>]+>/g, "").trim()}: ${(m.body_text || m.body_preview || "").slice(0, 1000)}`
                  ).join("\n");
                  const prompt = `Summarize this email thread and tell me what action is needed:\n\nSubject: ${thread.latest_subject || "(no subject)"}\nFrom: ${(thread.latest_sender || "").replace(/<[^>]+>/g, "").trim()}\nEFJ: ${thread.efj || "unmatched"}\nType: ${thread.email_type || "general"}\nMessages (${thread.message_count || 1}):\n${msgs}\n\nAI classification: ${thread.ai_summary || "none"}`;
                  setAskAIInitialQuery(prompt);
                  setAskAIOpen(true);
                } catch {}
              }}
              style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 10px", borderRadius: 8, fontSize: 10, fontWeight: 700, cursor: "pointer",
                background: askAIDragOver ? "rgba(0,212,170,0.35)" : "rgba(0,212,170,0.10)",
                color: "#00D4AA",
                border: askAIDragOver ? "2px solid #00D4AA" : "1px solid rgba(0,212,170,0.25)",
                letterSpacing: "0.3px", transition: "all 0.15s",
                boxShadow: askAIDragOver ? "0 0 20px rgba(0,212,170,0.4)" : "none",
                transform: askAIDragOver ? "scale(1.08)" : "scale(1)" }}
              onMouseEnter={e => { if (!askAIDragOver) { e.currentTarget.style.background = "rgba(0,212,170,0.18)"; e.currentTarget.style.borderColor = "rgba(0,212,170,0.45)"; }}}
              onMouseLeave={e => { if (!askAIDragOver) { e.currentTarget.style.background = "rgba(0,212,170,0.10)"; e.currentTarget.style.borderColor = "rgba(0,212,170,0.25)"; }}}>
              <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
                <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z" />
              </svg>
              {askAIDragOver ? "Drop to Analyze" : "Ask AI"}
              <span style={{ fontSize: 8, opacity: 0.5, marginLeft: 2 }}>⌘K</span>
            </button>
            {/* Email Drafts badge */}
            {emailDrafts.length > 0 && (
              <button onClick={() => { setShowDraftModal(true); }}
                style={{ position: "relative", display: "flex", alignItems: "center", gap: 5, padding: "5px 10px", borderRadius: 8, fontSize: 10, fontWeight: 700, cursor: "pointer",
                  background: "rgba(37,99,235,0.10)", color: "#60a5fa", border: "1px solid rgba(37,99,235,0.25)", letterSpacing: "0.3px", transition: "all 0.15s" }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(37,99,235,0.18)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(37,99,235,0.10)"; }}>
                <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" />
                </svg>
                Drafts
                <span style={{ background: "#2563eb", color: "#fff", borderRadius: "50%", width: 16, height: 16, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800 }}>
                  {emailDrafts.length}
                </span>
              </button>
            )}
            <ClockDisplay lastSyncTime={lastSyncTime} apiError={apiError} />
            {/* User menu */}
            {currentUser && (
              <div style={{ position: "relative" }}>
                <button onClick={() => setShowUserMenu(!showUserMenu)}
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer",
                    background: "rgba(255,255,255,0.04)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.08)", letterSpacing: "0.3px" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.08)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; }}>
                  <div style={{ width: 22, height: 22, borderRadius: "50%", background: "linear-gradient(135deg, #3b82f6, #2563eb)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800, color: "#fff" }}>
                    {(currentUser.rep_name || currentUser.username || "?").charAt(0).toUpperCase()}
                  </div>
                  {currentUser.rep_name || currentUser.username}
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M2 4l3 3 3-3"/></svg>
                </button>
                {showUserMenu && (
                  <>
                    <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 998 }} onClick={() => setShowUserMenu(false)} />
                    <div style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", background: "#161e2c", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, padding: 6, minWidth: 180, zIndex: 999, boxShadow: "0 12px 40px rgba(0,0,0,0.5)" }}>
                      <div style={{ padding: "8px 12px", fontSize: 11, color: "#7b8ba3", borderBottom: "1px solid rgba(255,255,255,0.06)", marginBottom: 4 }}>
                        <div style={{ fontWeight: 700, color: "#e8ecf4", marginBottom: 2 }}>{currentUser.rep_name || currentUser.username}</div>
                        <div style={{ fontSize: 10 }}>{currentUser.email}</div>
                        <div style={{ fontSize: 9, marginTop: 2, textTransform: "uppercase", letterSpacing: 1, color: currentUser.role === "admin" ? "#f59e0b" : "#3b82f6" }}>{currentUser.role}</div>
                      </div>
                      <button onClick={() => { setShowUserMenu(false); setShowChangePassword(true); setPwForm({ current: "", newPw: "", confirm: "" }); setPwError(null); setPwSuccess(false); }}
                        style={{ width: "100%", padding: "8px 12px", background: "none", border: "none", color: "#e8ecf4", fontSize: 11, textAlign: "left", cursor: "pointer", borderRadius: 6, fontFamily: "inherit" }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
                        onMouseLeave={e => e.currentTarget.style.background = "none"}>
                        Change Password
                      </button>
                      {currentUser.role === "admin" && (
                        <button onClick={() => { setShowUserMenu(false); setActiveView("settings"); }}
                          style={{ width: "100%", padding: "8px 12px", background: "none", border: "none", color: "#e8ecf4", fontSize: 11, textAlign: "left", cursor: "pointer", borderRadius: 6, fontFamily: "inherit" }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
                          onMouseLeave={e => e.currentTarget.style.background = "none"}>
                        Manage Users
                        </button>
                      )}
                      <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", marginTop: 4, paddingTop: 4 }}>
                        <button onClick={() => { window.location.href = "/logout"; }}
                          style={{ width: "100%", padding: "8px 12px", background: "none", border: "none", color: "#ef4444", fontSize: 11, textAlign: "left", cursor: "pointer", borderRadius: 6, fontFamily: "inherit" }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(239,68,68,0.08)"}
                          onMouseLeave={e => e.currentTarget.style.background = "none"}>
                          Sign Out
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* View Content */}
        <div className="dash-content-area" style={{ flex: 1, overflow: "auto" }}>
          <div style={{ padding: "0 24px 24px" }}>
          {apiError && (
            <div style={{ margin: "8px 0", padding: "10px 16px", borderRadius: 10, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", display: "flex", alignItems: "center", justifyContent: "space-between", animation: "slide-up 0.3s ease" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "#f87171", fontSize: 13 }}>⚠</span>
                <span style={{ fontSize: 11, color: "#f87171", fontWeight: 600 }}>API Error: {apiError}</span>
              </div>
              <button onClick={() => setApiError(null)} aria-label="Dismiss error" style={{ background: "none", border: "none", color: "#f87171", cursor: "pointer", fontSize: 12, padding: "2px 6px" }}>✕</button>
            </div>
          )}
          {!loaded ? (
            <div style={{ padding: "60px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 16, animation: "fade-in 0.3s ease" }}>
              <div style={{ width: 32, height: 32, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
              <div style={{ fontSize: 12, color: "#8B95A8", fontWeight: 500 }}>Loading loadboard data...</div>
            </div>
          ) : (<>
          {activeView === "dashboard" && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 0 4px" }}>
              {selectedRep && (
                <select value={selectedRep} onChange={e => setSelectedRep(e.target.value)}
                  style={{ padding: "7px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", outline: "none" }}>
                  {ALL_REP_NAMES.map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
                </select>
              )}
            </div>
          )}
          {activeView === "dashboard" && !selectedRep && (
            <OverviewView loaded={loaded} shipments={shipments} apiStats={apiStats}
              accountOverview={accountOverview} apiError={apiError} onSelectRep={goToRepDashboard}
              unbilledStats={unbilledStats} repProfiles={repProfiles} repScoreboard={repScoreboard} accountHealth={accountHealth}
              trackingSummary={trackingSummary} docSummary={docSummary} handleLoadClick={handleLoadClick}
              alerts={allAlerts} onDismissAlert={handleDismissAlert} onDismissAll={handleDismissAllAlerts}
              onNavigateDispatch={() => setActiveView("dispatch")} onFilterStatus={(s) => { setDateFilter(null); setActiveStatus(s); setActiveView("dispatch"); }}
              onFilterAccount={(acct) => { if (acct === "Boviet" || acct === "Tolead") { goToRepDashboard(acct); } else { setDateFilter(null); setActiveAccount(acct); setActiveView("dispatch"); } }}
              onFilterDate={(df) => { setDateFilter(df); setActiveStatus("all"); setActiveAccount("All Accounts"); setActiveView("dispatch"); }}
              onNavigateUnbilled={() => setActiveView("billing")}
              onAddLoad={() => setShowAddForm(true)}
              onNavigateBilling={() => setActiveView("billing")}
              onNavigateInbox={(tab, search, rep) => { useAppStore.getState().setInboxInitialTab(tab || null); useAppStore.getState().setInboxInitialSearch(search || null); useAppStore.getState().setInboxInitialRep(rep || null); setActiveView("inbox"); }}
              onFilterRepDispatch={(rep, status) => { setActiveRep(rep); if (status) setActiveStatus(status); setActiveView("dispatch"); }} />
          )}
          {activeView === "dashboard" && selectedRep && (
            <RepDashboardView repName={selectedRep} shipments={shipments} onBack={goBackFromRep}
              handleStatusUpdate={handleStatusUpdate} handleLoadClick={handleLoadClick}
              handleFieldUpdate={handleFieldUpdate} handleMetadataUpdate={handleMetadataUpdate}
              handleDriverFieldUpdate={handleDriverFieldUpdate}
              repProfiles={repProfiles} onProfileUpdate={fetchProfiles}
              trackingSummary={trackingSummary} docSummary={docSummary}
              inboxThreads={inboxThreads}
              onNavigateInbox={(tab, search, rep) => { useAppStore.getState().setInboxInitialTab(tab || null); useAppStore.getState().setInboxInitialSearch(search || null); useAppStore.getState().setInboxInitialRep(rep || null); setActiveView("inbox"); }} />
          )}
          {activeView === "dispatch" && (
            <DispatchView loaded={loaded} shipments={shipments} filtered={filtered} accounts={accounts}
              activeStatus={activeStatus} setActiveStatus={setActiveStatus}
              activeAccount={activeAccount} setActiveAccount={setActiveAccount}
              activeRep={activeRep} setActiveRep={setActiveRep}
              searchQuery={searchQuery} setSearchQuery={setSearchQuery}
              statusCounts={statusCounts} selectedShipment={selectedShipment} setSelectedShipment={setSelectedShipment}
              editField={editField} setEditField={setEditField} editValue={editValue} setEditValue={setEditValue}
              sheetLog={sheetLog} handleStatusUpdate={handleStatusUpdate} handleFieldEdit={handleFieldEdit}
              handleLoadClick={handleLoadClick} activeLoads={activeLoads} inTransit={inTransit}
              deliveredCount={deliveredCount} issueCount={issueCount}
              onAddLoad={() => setShowAddForm(true)} addSheetLog={addSheetLog} setShipments={setShipments}
              podUploading={podUploading} setPodUploading={setPodUploading} podUploadMsg={podUploadMsg} setPodUploadMsg={setPodUploadMsg}
              trackingSummary={trackingSummary} docSummary={docSummary}
              dateFilter={dateFilter} setDateFilter={setDateFilter}
              moveTypeFilter={moveTypeFilter} setMoveTypeFilter={setMoveTypeFilter}
              dateRangeField={dateRangeField} setDateRangeField={setDateRangeField}
              dateRangeStart={dateRangeStart} setDateRangeStart={setDateRangeStart}
              dateRangeEnd={dateRangeEnd} setDateRangeEnd={setDateRangeEnd}
              handleFieldUpdate={handleFieldUpdate}
              handleMetadataUpdate={handleMetadataUpdate}
              handleDriverFieldUpdate={handleDriverFieldUpdate}
              onBack={() => { setActiveView("dashboard"); setDateFilter(null); setActiveStatus("all"); setActiveAccount("All Accounts"); }} />
          )}
          {activeView === "history" && (
            <HistoryView loaded={loaded} handleLoadClick={handleLoadClick} handleStatusUpdate={handleStatusUpdate} />
          )}
          {activeView === "inbox" && (
            <InboxView handleLoadClick={handleLoadClick} />
          )}
          {activeView === "quotes" && (
            <RateIQView />
          )}
          {activeView === "playbooks" && (
            <PlaybooksView />
          )}
          {activeView === "analytics" && (
            <AnalyticsView loaded={loaded} botStatus={botStatus} botHealth={botHealth} cronStatus={cronStatus} sheetLog={sheetLog} />
          )}
          {activeView === "billing" && (
            <BillingView loaded={loaded} shipments={shipments} handleStatusUpdate={handleStatusUpdate}
              handleLoadClick={handleLoadClick} setSelectedShipment={setSelectedShipment}
              unbilledOrders={unbilledOrders} setUnbilledOrders={setUnbilledOrders}
              unbilledStats={unbilledStats} setUnbilledStats={setUnbilledStats} docSummary={docSummary} />
          )}
          {activeView === "bol" && (
            <BOLGeneratorView loaded={loaded} />
          )}
          {activeView === "settings" && currentUser?.role === "admin" && (
            <UserManagementView API_BASE={API_BASE} apiFetchFn={apiFetch} />
          )}
          </>)}
          </div>
        </div>
      </div>

      {showAddForm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: Z.modal, animation: "fade-in 0.2s ease" }}
          onClick={() => setShowAddForm(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="add-form-title"
            onClick={e => e.stopPropagation()} className="glass-strong" style={{ borderRadius: 20, padding: 28, width: 460, maxHeight: "85vh", overflow: "auto", animation: "slide-up 0.3s ease", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div id="add-form-title" style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5", marginBottom: 4 }}>New Load</div>
            <div style={{ fontSize: 11, color: "#8B95A8", marginBottom: 20 }}>Create a new shipment</div>
            <AddForm onSubmit={handleAddShipment} onCancel={() => setShowAddForm(false)} accounts={accounts} />
          </div>
        </div>
      )}

      {showParseModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: Z.modal, animation: "fade-in 0.2s ease" }}
          onClick={() => { setShowParseModal(false); setParseResult(null); setParseError(null); }}>
          <div role="dialog" aria-modal="true" aria-label="Magic Parse"
            onClick={e => e.stopPropagation()} className="glass-strong"
            style={{ borderRadius: 20, padding: 28, width: 520, maxHeight: "85vh", overflow: "auto", animation: "slide-up 0.3s ease", border: "1px solid rgba(139,92,246,0.25)" }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <svg width="16" height="16" fill="none" stroke="#A78BFA" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
                    <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z" />
                  </svg>
                  <span style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5" }}>Magic Parse</span>
                </div>
                <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 3 }}>Paste any email, note, or dispatch text — AI extracts the key fields</div>
              </div>
              <button onClick={() => { setShowParseModal(false); setParseResult(null); setParseError(null); }}
                style={{ background: "none", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "2px 6px" }}>✕</button>
            </div>

            {/* Text Input */}
            <textarea value={parseText} onChange={e => setParseText(e.target.value)}
              placeholder={"Paste email body, dispatch note, or any freight text here...\n\nExample: EFJ107405 pickup LBCT, carrier Ace Drayage, all-in $1,850, container MSCU1234567"}
              rows={7}
              style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#F0F2F5", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", resize: "vertical", outline: "none", boxSizing: "border-box", lineHeight: 1.6 }} />

            {/* Action */}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10, marginBottom: parseResult || parseError ? 16 : 0 }}>
              <button onClick={handleQuickParse} disabled={isParsing || !parseText.trim()}
                style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 18px", borderRadius: 10, fontSize: 11, fontWeight: 700, cursor: isParsing || !parseText.trim() ? "not-allowed" : "pointer", background: isParsing || !parseText.trim() ? "rgba(139,92,246,0.08)" : "rgba(139,92,246,0.18)", color: isParsing || !parseText.trim() ? "#6B7280" : "#A78BFA", border: "1px solid rgba(139,92,246,0.25)", transition: "all 0.15s" }}>
                {isParsing ? (
                  <><div style={{ width: 11, height: 11, border: "2px solid rgba(167,139,250,0.3)", borderTop: "2px solid #A78BFA", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} /> Extracting...</>
                ) : (
                  <><svg width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z" /></svg> Extract Fields</>
                )}
              </button>
            </div>

            {/* Error */}
            {parseError && (
              <div style={{ padding: "10px 14px", borderRadius: 10, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#F87171", fontSize: 11, marginBottom: 12 }}>⚠ {parseError}</div>
            )}

            {/* Results */}
            {parseResult && (
              <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 16 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 12 }}>
                  Extracted Fields
                  {parseResult.confidence && (
                    <span style={{ marginLeft: 8, padding: "1px 6px", borderRadius: 4, fontSize: 9, background: parseResult.confidence === "high" ? "rgba(34,197,94,0.12)" : parseResult.confidence === "medium" ? "rgba(245,158,11,0.12)" : "rgba(239,68,68,0.10)", color: parseResult.confidence === "high" ? "#22C55E" : parseResult.confidence === "medium" ? "#F59E0B" : "#EF4444" }}>
                      {parseResult.confidence.toUpperCase()} CONFIDENCE
                    </span>
                  )}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {[
                    { label: "EFJ #", val: parseResult.efj_number, color: "#00D4AA" },
                    { label: "Rate", val: parseResult.rate != null ? `$${Number(parseResult.rate).toLocaleString("en-US", { minimumFractionDigits: 2 })}` : null, color: "#22C55E" },
                    { label: "Container", val: parseResult.container_number, color: "#3B82F6" },
                    { label: "Carrier", val: parseResult.carrier, color: "#F97316" },
                  ].map(({ label, val, color }) => (
                    <div key={label} style={{ padding: "10px 12px", borderRadius: 8, background: val ? `rgba(${color === "#00D4AA" ? "0,212,170" : color === "#22C55E" ? "34,197,94" : color === "#3B82F6" ? "59,130,246" : "249,115,22"},0.06)` : "rgba(255,255,255,0.02)", border: `1px solid ${val ? `${color}22` : "rgba(255,255,255,0.04)"}`, transition: "all 0.3s ease", animation: val ? "fade-in 0.4s ease" : "none" }}>
                      <div style={{ fontSize: 9, color: "#6B7280", fontWeight: 600, letterSpacing: "0.5px", marginBottom: 4, textTransform: "uppercase" }}>{label}</div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: val ? color : "#3A4255", fontFamily: val ? "'JetBrains Mono', monospace" : "inherit" }}>
                        {val || "—"}
                      </div>
                    </div>
                  ))}
                </div>
                {parseResult.efj_number && (
                  <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                    <button onClick={() => {
                      setShowParseModal(false);
                      const match = shipments.find(s => s.efj && s.efj.toUpperCase() === parseResult.efj_number.toUpperCase());
                      if (match) { handleLoadClick(match); }
                      else { setCmdkQuery(parseResult.efj_number); setCmdkOpen(true); }
                    }}
                      style={{ flex: 1, padding: "8px 14px", borderRadius: 8, fontSize: 11, fontWeight: 700, cursor: "pointer", background: "rgba(0,212,170,0.10)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.2)" }}>
                      Open {parseResult.efj_number} →
                    </button>
                    <button onClick={() => { setParseText(""); setParseResult(null); setParseError(null); }}
                      style={{ padding: "8px 14px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.03)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.06)" }}>
                      Parse Another
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <LoadSlideOver selectedShipment={selectedShipment} setSelectedShipment={setSelectedShipment}
        shipments={shipments} setShipments={setShipments} handleStatusUpdate={handleStatusUpdate}
        editField={editField} setEditField={setEditField} editValue={editValue} setEditValue={setEditValue}
        handleFieldEdit={handleFieldEdit} addSheetLog={addSheetLog}
        carrierDirectory={carrierDirectory}
        onDocChange={refreshDocSummary}
        isMobile={isMobile}
        expandEmailsOnOpen={expandEmailsOnOpen}
        onConsumeExpandEmails={() => setExpandEmailsOnOpen(false)}
        handleFieldUpdate={handleFieldUpdate}
        handleMetadataUpdate={handleMetadataUpdate}
        handleApplyRate={handleApplyRate} />

      {/* ═══ MOBILE BOTTOM NAV ═══ */}
      <nav className="mobile-bottom-nav" style={{ position: "fixed", bottom: 0, left: 0, right: 0, height: 56, background: "#0D1119", borderTop: "1px solid rgba(255,255,255,0.08)", display: "none", alignItems: "center", justifyContent: "space-around", zIndex: Z.sidebar + 5, paddingBottom: "env(safe-area-inset-bottom)" }}>
        {[
          { key: "dashboard", label: "Home", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
          { key: "inbox", label: "Inbox", icon: "M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
          { key: "quotes", label: "Rates", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
          { key: "billing", label: "Billing", icon: "M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2zM10 8.5a.5.5 0 11-1 0 .5.5 0 011 0zm5 5a.5.5 0 11-1 0 .5.5 0 011 0z" },
          { key: "analytics", label: "More", icon: "M4 6h16M4 12h16M4 18h16" },
        ].map(item => {
          const isActive = activeView === item.key;
          return (
            <button key={item.key} onClick={() => { setActiveView(item.key); setSelectedRep(null); }}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, border: "none", background: "none", cursor: "pointer", padding: "6px 12px", minWidth: 44, minHeight: 44,
                color: isActive ? "#00D4AA" : "#5A6478" }}>
              <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d={item.icon} /></svg>
              <span style={{ fontSize: 9, fontWeight: 600 }}>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* ═══ DRAFT TOAST ═══ */}
      {draftToast && (
        <div style={{ position: "fixed", top: 16, right: 24, zIndex: 9999, display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderRadius: 12,
          background: "linear-gradient(135deg, rgba(37,99,235,0.15), rgba(37,99,235,0.08))", border: "1px solid rgba(37,99,235,0.3)", backdropFilter: "blur(12px)",
          animation: "slide-down 0.3s ease", boxShadow: "0 8px 32px rgba(0,0,0,0.4)" }}>
          <span style={{ fontSize: 16 }}>📧</span>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#60a5fa" }}>Email draft ready</div>
            <div style={{ fontSize: 10, color: "#8B95A8" }}>{draftToast.loadNumber || draftToast.efj}</div>
          </div>
          <button onClick={() => {
            setDraftToast(null);
            // Open draft modal with this specific draft
            apiFetch(`${API_BASE}/api/email-drafts/${draftToast.id}`).then(r => r.ok ? r.json() : null).then(d => {
              if (d) { setActiveDraft(d); setShowDraftModal(true); }
            });
          }} style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(37,99,235,0.2)", border: "1px solid rgba(37,99,235,0.3)", color: "#60a5fa", fontSize: 10, fontWeight: 700, cursor: "pointer" }}>
            Review
          </button>
          <button onClick={() => setDraftToast(null)} style={{ background: "none", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 14, padding: "0 4px" }}>✕</button>
        </div>
      )}

      {/* ═══ EMAIL DRAFT MODAL ═══ */}
      {showDraftModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: Z.modal, animation: "fade-in 0.2s ease" }}
          onClick={() => { setShowDraftModal(false); setActiveDraft(null); }}>
          <div role="dialog" aria-modal="true" onClick={e => e.stopPropagation()} className="glass-strong"
            style={{ borderRadius: 20, padding: 28, width: 600, maxHeight: "85vh", overflow: "auto", animation: "slide-up 0.3s ease", border: "1px solid rgba(37,99,235,0.2)" }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ width: 32, height: 32, borderRadius: 10, background: "linear-gradient(135deg, #2563eb, #3b82f6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📧</div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5" }}>Email Drafts</div>
                  <div style={{ fontSize: 11, color: "#8B95A8" }}>{emailDrafts.length} pending</div>
                </div>
              </div>
              <button onClick={() => { setShowDraftModal(false); setActiveDraft(null); }}
                style={{ background: "none", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 18, padding: "2px 6px" }}>✕</button>
            </div>

            {/* Draft list or detail */}
            {activeDraft ? (
              <div>
                <button onClick={() => setActiveDraft(null)} style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", color: "#60a5fa", cursor: "pointer", fontSize: 11, fontWeight: 600, marginBottom: 12, padding: 0 }}>
                  ← Back to list
                </button>
                {/* Editable fields */}
                <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px" }}>To</label>
                    <input value={activeDraft.to_email} onChange={e => setActiveDraft({...activeDraft, to_email: e.target.value})}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#F0F2F5", fontSize: 12, outline: "none", boxSizing: "border-box" }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px" }}>CC</label>
                    <input value={activeDraft.cc_email || ""} onChange={e => setActiveDraft({...activeDraft, cc_email: e.target.value})}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#F0F2F5", fontSize: 12, outline: "none", boxSizing: "border-box" }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px" }}>Subject</label>
                    <input value={activeDraft.subject} onChange={e => setActiveDraft({...activeDraft, subject: e.target.value})}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#F0F2F5", fontSize: 12, outline: "none", boxSizing: "border-box" }} />
                  </div>
                </div>
                {/* HTML preview */}
                <div style={{ borderRadius: 12, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)", marginBottom: 16, maxHeight: 320, overflowY: "auto" }}>
                  <iframe srcDoc={activeDraft.body_html} style={{ width: "100%", height: 300, border: "none", background: "#fff" }} title="Email Preview" />
                </div>
                {/* Actions */}
                <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                  <button onClick={async () => {
                    try {
                      await apiFetch(`${API_BASE}/api/email-drafts/${activeDraft.id}/dismiss`, { method: "POST" });
                      setActiveDraft(null); fetchEmailDrafts();
                      addSheetLog(`Draft dismissed | ${activeDraft.efj}`);
                    } catch {}
                  }} style={{ padding: "8px 16px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                    Dismiss
                  </button>
                  <button disabled={draftSending} onClick={async () => {
                    setDraftSending(true);
                    try {
                      // Save any edits first
                      await apiFetch(`${API_BASE}/api/email-drafts/${activeDraft.id}`, {
                        method: "PATCH", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ to_email: activeDraft.to_email, cc_email: activeDraft.cc_email, subject: activeDraft.subject }),
                      });
                      // Send
                      const res = await apiFetch(`${API_BASE}/api/email-drafts/${activeDraft.id}/send`, { method: "POST" });
                      if (res.ok) {
                        addSheetLog(`Email sent | ${activeDraft.efj}`);
                        setActiveDraft(null); fetchEmailDrafts();
                      } else {
                        const err = await res.json().catch(() => ({}));
                        addSheetLog(`Email send failed: ${err.detail || res.status} | ${activeDraft.efj}`);
                      }
                    } catch (e) { addSheetLog(`Email send error | ${activeDraft.efj}`); }
                    finally { setDraftSending(false); }
                  }} style={{ padding: "8px 20px", borderRadius: 8, background: draftSending ? "rgba(34,197,94,0.08)" : "linear-gradient(135deg, #16a34a, #22c55e)",
                    border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: draftSending ? "wait" : "pointer", opacity: draftSending ? 0.6 : 1, display: "flex", alignItems: "center", gap: 6 }}>
                    {draftSending ? "Sending..." : "Send Email"}
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {emailDrafts.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "32px 0", color: "#5A6478", fontSize: 12 }}>No pending drafts</div>
                ) : emailDrafts.map(d => (
                  <div key={d.id} onClick={async () => {
                    const res = await apiFetch(`${API_BASE}/api/email-drafts/${d.id}`);
                    if (res.ok) { const full = await res.json(); setActiveDraft(full); }
                  }} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: 10, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer", transition: "all 0.15s" }}
                    onMouseEnter={e => { e.currentTarget.style.background = "rgba(37,99,235,0.06)"; e.currentTarget.style.borderColor = "rgba(37,99,235,0.2)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; }}>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: d.milestone === "delivered" ? "#16a34a" : d.milestone === "picked_up" ? "#2563eb" : d.milestone === "in_transit" ? "#4f46e5" : d.milestone === "out_for_delivery" ? "#ea580c" : "#0d9488", flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.subject}</div>
                      <div style={{ fontSize: 10, color: "#5A6478", marginTop: 2 }}>{d.efj} · {d.milestone?.replace(/_/g, " ")} · {new Date(d.created_at).toLocaleTimeString()}</div>
                    </div>
                    <svg width="14" height="14" fill="none" stroke="#5A6478" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6" /></svg>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Change Password Modal */}
      {showChangePassword && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={() => setShowChangePassword(false)}>
          <div style={{ background: "#161e2c", border: "1px solid #1e2a3d", borderRadius: 16, padding: 32, width: 380, maxWidth: "90vw" }} onClick={e => e.stopPropagation()}>
            <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, color: "#e8ecf4" }}>Change Password</h3>
            {pwSuccess ? (
              <div style={{ padding: "12px 16px", borderRadius: 8, background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)", color: "#22c55e", fontSize: 13, marginBottom: 16 }}>
                Password changed successfully!
              </div>
            ) : (
              <form onSubmit={async e => {
                e.preventDefault();
                setPwError(null);
                if (pwForm.newPw.length < 8) { setPwError("New password must be at least 8 characters"); return; }
                if (pwForm.newPw !== pwForm.confirm) { setPwError("Passwords do not match"); return; }
                try {
                  const res = await apiFetch(`${API_BASE}/api/me/change-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: pwForm.current, new_password: pwForm.newPw }) });
                  if (res.ok) { setPwSuccess(true); } else { const d = await res.json(); setPwError(d.error || "Failed"); }
                } catch { setPwError("Network error"); }
              }}>
                {pwError && <div style={{ padding: "8px 12px", borderRadius: 8, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#ef4444", fontSize: 12, marginBottom: 12 }}>{pwError}</div>}
                {[
                  { label: "Current Password", key: "current", type: "password" },
                  { label: "New Password", key: "newPw", type: "password" },
                  { label: "Confirm New Password", key: "confirm", type: "password" },
                ].map(f => (
                  <div key={f.key} style={{ marginBottom: 12 }}>
                    <label style={{ display: "block", fontSize: 11, color: "#7b8ba3", marginBottom: 4, fontWeight: 500 }}>{f.label}</label>
                    <input type={f.type} value={pwForm[f.key]} onChange={e => setPwForm({ ...pwForm, [f.key]: e.target.value })} required
                      style={{ width: "100%", padding: "10px 14px", background: "#0a0d12", border: "1px solid #1e2a3d", borderRadius: 8, color: "#e8ecf4", fontSize: 13, outline: "none", fontFamily: "inherit" }} />
                  </div>
                ))}
                <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                  <button type="button" onClick={() => setShowChangePassword(false)}
                    style={{ flex: 1, padding: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#8B95A8", fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>
                    Cancel
                  </button>
                  <button type="submit"
                    style={{ flex: 1, padding: 10, background: "linear-gradient(135deg, #3b82f6, #2563eb)", border: "none", borderRadius: 8, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                    Update Password
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
