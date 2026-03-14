import { useState, useEffect, useCallback, useMemo } from "react";
import { useAppStore } from "../store";
import { apiFetch, API_BASE } from "../helpers/api";
import { Z } from "../helpers/constants";

// ─── Inbox-local constants (different shape from helpers/constants versions) ───
const LOCAL_INBOX_TABS = [
  { key: "all", label: "All" },
  { key: "needs_reply", label: "Needs Reply" },
  { key: "unmatched", label: "Unmatched" },
  { key: "rates", label: "Rates" },
];

const LOCAL_EMAIL_TYPE_COLORS = {
  carrier_rate: { bg: "rgba(0,212,170,0.12)", color: "#00D4AA" },
  customer_rate: { bg: "rgba(0,212,170,0.12)", color: "#00D4AA" },
  detention: { bg: "rgba(239,68,68,0.12)", color: "#EF4444" },
  pod: { bg: "rgba(34,197,94,0.12)", color: "#22C55E" },
  bol: { bg: "rgba(59,130,246,0.12)", color: "#3B82F6" },
  appointment: { bg: "rgba(168,85,247,0.12)", color: "#A855F7" },
  invoice: { bg: "rgba(249,115,22,0.12)", color: "#F97316" },
  delivery_update: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
  tracking_update: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
  general: { bg: "rgba(139,149,168,0.12)", color: "#8B95A8" },
  payment_escalation: { bg: "rgba(239,68,68,0.15)", color: "#EF4444" },
  carrier_rate_response: { bg: "rgba(0,212,170,0.15)", color: "#00D4AA" },
  rate_outreach: { bg: "rgba(59,130,246,0.12)", color: "#3B82F6" },
  carrier_invoice: { bg: "rgba(249,115,22,0.12)", color: "#F97316" },
  carrier_rate_confirmation: { bg: "rgba(168,85,247,0.12)", color: "#A855F7" },
  warehouse_rate: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
};

const LOCAL_INBOX_TYPE_LABELS = {
  carrier_rate: "CARRIER RATE",
  customer_rate: "CUSTOMER RATE",
  carrier_rate_response: "RATE RESPONSE",
  carrier_rate_confirmation: "RATE CON",
  carrier_invoice: "INVOICE",
  payment_escalation: "PAYMENT ALERT",
  rate_outreach: "OUTREACH",
  pod: "POD",
  bol: "BOL",
  detention: "DETENTION",
  appointment: "APPT",
  invoice: "INVOICE",
  delivery_update: "DELIVERY",
  tracking_update: "TRACKING",
  general: "GENERAL",
  warehouse_rate: "WAREHOUSE",
};

function _relTime(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function InboxView({ handleLoadClick }) {
  const { inboxThreads, inboxStats, setInboxThreads, setInboxStats, shipments, setSelectedShipment, setActiveView, inboxInitialTab, inboxInitialSearch, inboxInitialRep, setInboxInitialTab, setInboxInitialSearch, setInboxInitialRep, setAskAIOpen, setAskAIInitialQuery } = useAppStore();
  const [activeTab, setActiveTab] = useState(() => inboxInitialTab || "all");
  const [repFilter, setRepFilter] = useState(() => inboxInitialRep || "");
  const [loading, setLoading] = useState(true);
  const [assigningId, setAssigningId] = useState(null);
  const [assignEfj, setAssignEfj] = useState("");
  const [feedbackGiven, setFeedbackGiven] = useState({});
  const [correctionId, setCorrectionId] = useState(null);
  const [quoteActions, setQuoteActions] = useState({});
  const [quoteLinkId, setQuoteLinkId] = useState(null);
  const [quoteLinkEfj, setQuoteLinkEfj] = useState("");
  const [sortCol, setSortCol] = useState("time");
  const [sortDir, setSortDir] = useState("desc");
  const [inboxSearch, setInboxSearch] = useState(() => inboxInitialSearch || "");
  const [selectedThread, setSelectedThread] = useState(null);
  const [colFilters, setColFilters] = useState({});
  const [openFilterCol, setOpenFilterCol] = useState(null);
  const [inboxDays, setInboxDays] = useState(3);
  const [hideActioned, setHideActioned] = useState(true);
  const [actioningThread, setActioningThread] = useState(null);
  const [actionFlash, setActionFlash] = useState(null);

  const handleAutoAction = async (thread, action, docType) => {
    setActioningThread(thread.thread_id);
    try {
      const res = await apiFetch(`${API_BASE}/api/inbox/${thread.thread_id}/auto-action`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, doc_type: docType }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || e.error || "Failed"); }
      const data = await res.json();
      setInboxThreads(prev => prev.map(t => t.thread_id === thread.thread_id ? { ...t, actioned: true } : t));
      setActionFlash(thread.thread_id);
      setTimeout(() => setActionFlash(null), 1500);
      return data;
    } catch (e) {
      console.error("Auto-action failed:", e);
      alert(`Action failed: ${e.message}`);
    } finally {
      setActioningThread(null);
    }
  };

  const getAutoAction = (thread) => {
    const t = thread.email_type;
    const hasAtt = thread.has_attachments;
    const hasEfj = !!thread.efj;
    const docTypes = ["pod", "carrier_invoice", "invoice", "bol", "carrier_rate", "carrier_rate_confirmation", "customer_rate"];
    if (hasAtt && hasEfj && docTypes.includes(t)) {
      const labels = { pod: "POD", carrier_invoice: "Invoice", invoice: "Invoice", bol: "BOL", carrier_rate: "Rate Con", carrier_rate_confirmation: "Rate Con", customer_rate: "Cust Rate" };
      return { action: "save_attachment", label: `Save ${labels[t] || "Doc"}`, color: "#00D4AA", bg: "rgba(0,212,170,0.12)", border: "rgba(0,212,170,0.25)" };
    }
    if (t === "delivery_update" && hasEfj) {
      return { action: "mark_delivered", label: "Delivered", color: "#22C55E", bg: "rgba(34,197,94,0.10)", border: "rgba(34,197,94,0.25)" };
    }
    return null;
  };

  useEffect(() => {
    if (inboxInitialTab) setInboxInitialTab(null);
    if (inboxInitialSearch) setInboxInitialSearch(null);
    if (inboxInitialRep) setInboxInitialRep(null);
  }, []);

  const fetchInbox = useCallback(async () => {
    try {
      let url = `${API_BASE}/api/inbox?days=${inboxDays}&tab=${activeTab}`;
      if (repFilter) url += `&rep=${encodeURIComponent(repFilter)}`;
      const res = await apiFetch(url);
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      setInboxThreads(data.threads || []);
      setInboxStats(data.stats || {});
    } catch (e) {
      console.error("Inbox fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [activeTab, inboxDays, repFilter]);

  useEffect(() => { setLoading(true); fetchInbox(); }, [fetchInbox]);
  useEffect(() => { const iv = setInterval(fetchInbox, 90000); return () => clearInterval(iv); }, [fetchInbox]);

  const handleAssign = async (emailId) => {
    if (!assignEfj.trim()) return;
    try {
      const res = await apiFetch(`${API_BASE}/api/unmatched-emails/${emailId}/assign`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ efj: assignEfj.trim().toUpperCase() }),
      });
      if (res.ok) { setAssigningId(null); setAssignEfj(""); fetchInbox(); }
    } catch (e) { console.error("Assign failed:", e); }
  };
  const handleDismiss = async (emailId) => {
    try { await apiFetch(`${API_BASE}/api/unmatched-emails/${emailId}/dismiss`, { method: "POST" }); fetchInbox(); }
    catch (e) { console.error("Dismiss failed:", e); }
  };
  const handleFeedback = async (emailId, feedback, correctedType) => {
    try {
      await apiFetch(`${API_BASE}/api/inbox/${emailId}/feedback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback, corrected_type: correctedType || null }),
      });
      setFeedbackGiven(prev => ({ ...prev, [emailId]: feedback }));
      setCorrectionId(null);
    } catch (e) { console.error("Feedback failed:", e); }
  };

  const handleQuoteAction = async (emailId, status, newEfj) => {
    try {
      const body = { quote_status: status || null };
      if (newEfj) body.efj = newEfj.trim().toUpperCase();
      await apiFetch(`${API_BASE}/api/inbox/${emailId}/quote-action`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setQuoteActions(prev => ({ ...prev, [emailId]: status || null }));
      setQuoteLinkId(null);
      setQuoteLinkEfj("");
      setInboxThreads(prev => prev.map(t => {
        const msg = (t.messages || []).find(m => m.id === emailId);
        if (!msg) return t;
        return { ...t, quote_status: status || null };
      }));
    } catch (e) { console.error("Quote action failed:", e); }
  };

  const openLoad = (efj) => {
    if (!efj) return;
    const ship = (Array.isArray(shipments) ? shipments : []).find(s => s.efj === efj);
    if (ship) { setSelectedShipment(ship); setSelectedThread(null); }
  };

  const threads = inboxThreads;
  const stats = inboxStats;
  const CORRECTION_TYPES = ["carrier_rate", "customer_rate", "carrier_rate_response", "carrier_rate_confirmation", "carrier_invoice", "payment_escalation", "pod", "bol", "appointment", "detention", "delivery_update", "tracking_update", "invoice", "general"];

  const filtered = useMemo(() => {
    let list = threads;
    if (inboxSearch.trim()) {
      const q = inboxSearch.toLowerCase();
      list = list.filter(t =>
        (t.latest_subject || "").toLowerCase().includes(q) ||
        (t.latest_sender || "").toLowerCase().includes(q) ||
        (t.efj || "").toLowerCase().includes(q) ||
        (t.lane || "").toLowerCase().includes(q)
      );
    }
    const active = Object.entries(colFilters).filter(([, v]) => v != null);
    if (active.length) {
      list = list.filter(t => active.every(([key, val]) => {
        if (key === "type") return t.email_type === val;
        if (key === "efj") return t.efj === val;
        if (key === "sender") return (t.latest_sender || "").replace(/<[^>]+>/g, "").trim() === val;
        if (key === "status") {
          if (val === "needs_reply") return t.needs_reply;
          if (val === "replied") return t.has_csl_reply;
          if (val === "unmatched") return t.source === "unmatched";
          return true;
        }
        return true;
      }));
    }
    if (hideActioned) {
      list = list.filter(t => !t.actioned && (t.needs_reply || t.source === "unmatched"));
    }
    return list;
  }, [threads, inboxSearch, colFilters, hideActioned]);

  const sorted = useMemo(() => {
    const list = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      let cmp = 0;
      if (sortCol === "priority") cmp = (a.max_priority || 0) - (b.max_priority || 0);
      else if (sortCol === "subject") cmp = (a.latest_subject || "").localeCompare(b.latest_subject || "");
      else if (sortCol === "efj") cmp = (a.efj || "").localeCompare(b.efj || "");
      else if (sortCol === "type") cmp = (a.email_type || "").localeCompare(b.email_type || "");
      else if (sortCol === "msgs") cmp = (a.message_count || 0) - (b.message_count || 0);
      else if (sortCol === "sender") cmp = (a.latest_sender || "").localeCompare(b.latest_sender || "");
      else if (sortCol === "time") cmp = (a.latest_sent_at || "").localeCompare(b.latest_sent_at || "");
      return cmp * dir;
    });
    return list;
  }, [filtered, sortCol, sortDir]);

  const filterOpts = useMemo(() => {
    const opts = {};
    opts.type = [...new Set(threads.map(t => t.email_type).filter(Boolean))].sort();
    opts.efj = [...new Set(threads.map(t => t.efj).filter(Boolean))].sort();
    opts.sender = [...new Set(threads.map(t => (t.latest_sender || "").replace(/<[^>]+>/g, "").trim()).filter(Boolean))].sort();
    opts.status = ["needs_reply", "replied", "unmatched"];
    return opts;
  }, [threads]);

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("desc"); }
  };

  const thStyle = { padding: "6px 8px", textAlign: "left", fontSize: 8, fontWeight: 600, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: Z.table, cursor: "pointer", whiteSpace: "nowrap", userSelect: "none" };
  const cellStyle = { padding: "5px 8px", fontSize: 10, color: "#F0F2F5", borderBottom: "1px solid rgba(255,255,255,0.03)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

  const renderFilterDrop = (colKey, w) => {
    if (openFilterCol !== colKey) return null;
    const options = filterOpts[colKey] || [];
    return (
      <div style={{ position: "absolute", top: "100%", left: 0, zIndex: Z.dropdown, background: "#141A28", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: 4, minWidth: w || 120, maxHeight: 200, overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}
        onClick={e => e.stopPropagation()}>
        <div style={{ padding: "4px 8px", fontSize: 9, color: "#8B95A8", cursor: "pointer", borderRadius: 4 }}
          onClick={() => { setColFilters(f => { const n = { ...f }; delete n[colKey]; return n; }); setOpenFilterCol(null); }}>
          Clear filter
        </div>
        {options.map(opt => {
          const label = colKey === "type" ? (LOCAL_INBOX_TYPE_LABELS[opt] || opt.replace(/_/g, " ")) : colKey === "status" ? opt.replace(/_/g, " ") : opt;
          return (
            <div key={opt} style={{ padding: "4px 8px", fontSize: 9, color: colFilters[colKey] === opt ? "#00D4AA" : "#F0F2F5", cursor: "pointer", borderRadius: 4, background: colFilters[colKey] === opt ? "rgba(0,212,170,0.08)" : "transparent" }}
              onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
              onMouseLeave={e => { e.currentTarget.style.background = colFilters[colKey] === opt ? "rgba(0,212,170,0.08)" : "transparent"; }}
              onClick={() => { setColFilters(f => ({ ...f, [colKey]: opt })); setOpenFilterCol(null); }}>
              {label}
            </div>
          );
        })}
      </div>
    );
  };

  const renderTh = (label, colKey, w, filterable) => {
    const isSort = sortCol === colKey;
    const hasFilter = colFilters[colKey] != null;
    return (
      <th key={colKey} style={{ ...thStyle, width: w || "auto", minWidth: w || "auto", position: "relative",
        borderBottom: hasFilter ? "2px solid rgba(0,212,170,0.4)" : thStyle.borderBottom,
        background: hasFilter ? "rgba(0,212,170,0.04)" : thStyle.background,
        color: isSort ? "#00D4AA" : thStyle.color }}>
        <span onClick={() => toggleSort(colKey)}>{label} {isSort ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}</span>
        {filterable && (
          <span onClick={e => { e.stopPropagation(); setOpenFilterCol(openFilterCol === colKey ? null : colKey); }}
            style={{ marginLeft: 4, cursor: "pointer", fontSize: 8, color: hasFilter ? "#00D4AA" : "#5A6478" }}>
            {hasFilter ? "\u2726" : "\u25BE"}
          </span>
        )}
        {filterable && renderFilterDrop(colKey, w)}
      </th>
    );
  };

  const selThread = selectedThread;
  const selMsgId = selThread ? ((selThread.messages || []).filter(m => m.direction === "inbound").slice(-1)[0]?.id) : null;
  const selFeedback = selMsgId ? feedbackGiven[selMsgId] : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 60px)", position: "relative" }} onClick={() => { if (openFilterCol) setOpenFilterCol(null); }}>
      {/* Header + Tabs + Search */}
      <div style={{ padding: "12px 16px 0", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>Inbox</div>
          <div style={{ fontSize: 10, color: "#8B95A8" }}>
            {stats.total_threads || 0} threads
            {stats.needs_reply > 0 && <> &middot; <span style={{ color: "#EF4444", fontWeight: 600 }}>{stats.needs_reply} need reply</span></>}
            {stats.unmatched > 0 && <> &middot; <span style={{ color: "#F97316" }}>{stats.unmatched} unmatched</span></>}
            {stats.high_priority > 0 && <> &middot; {stats.high_priority} high priority</>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, marginBottom: 8, alignItems: "center" }}>
          {LOCAL_INBOX_TABS.map(tab => {
            const isActive = activeTab === tab.key;
            let count = null;
            if (tab.key === "needs_reply") count = stats.needs_reply;
            else if (tab.key === "unmatched") count = stats.unmatched;
            return (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                style={{ padding: "5px 12px", borderRadius: 6, fontSize: 10, fontWeight: 600, cursor: "pointer",
                  background: isActive ? "rgba(0,212,170,0.12)" : "rgba(255,255,255,0.04)",
                  color: isActive ? "#00D4AA" : "#8B95A8",
                  border: isActive ? "1px solid rgba(0,212,170,0.25)" : "1px solid rgba(255,255,255,0.06)" }}>
                {tab.label}
                {count > 0 && (
                  <span style={{ marginLeft: 5, padding: "1px 5px", borderRadius: 8, fontSize: 8, fontWeight: 700,
                    background: tab.key === "needs_reply" ? "rgba(239,68,68,0.20)" : "rgba(249,115,22,0.20)",
                    color: tab.key === "needs_reply" ? "#EF4444" : "#F97316" }}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
          <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
            <input value={inboxSearch} onChange={e => setInboxSearch(e.target.value)}
              placeholder="Search subject, sender, EFJ..."
              style={{ width: 200, padding: "5px 10px", borderRadius: 6, fontSize: 10, background: "rgba(255,255,255,0.04)", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.08)", outline: "none" }} />
            {repFilter && (
              <button onClick={() => setRepFilter("")}
                style={{ padding: "4px 8px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(59,130,246,0.10)", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.25)", display: "flex", alignItems: "center", gap: 4 }}>
                {repFilter}'s Inbox <span style={{ fontSize: 11, lineHeight: 1 }}>&times;</span>
              </button>
            )}
            {Object.keys(colFilters).length > 0 && (
              <button onClick={() => setColFilters({})}
                style={{ padding: "4px 8px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>
                Clear Filters
              </button>
            )}
            <button onClick={() => setHideActioned(h => !h)}
              style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer",
                background: hideActioned ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.04)",
                color: hideActioned ? "#00D4AA" : "#8B95A8",
                border: hideActioned ? "1px solid rgba(0,212,170,0.20)" : "1px solid rgba(255,255,255,0.06)" }}>
              {hideActioned ? "Showing New" : "Show All"}
            </button>
            <button onClick={() => { const d = inboxDays === 3 ? 7 : 3; setInboxDays(d); }}
              style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", color: inboxDays === 7 ? "#A78BFA" : "#8B95A8", border: `1px solid ${inboxDays === 7 ? "rgba(167,139,250,0.25)" : "rgba(255,255,255,0.06)"}` }}>
              {inboxDays}d
            </button>
            <button onClick={() => { setLoading(true); fetchInbox(); }}
              style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.06)" }}>
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: "auto", position: "relative" }} className="dispatch-table-wrap">
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "#5A6478" }}>
            <div style={{ width: 24, height: 24, border: "2px solid rgba(0,212,170,0.2)", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
            Loading inbox...
          </div>
        ) : sorted.length === 0 ? (
          <div style={{ textAlign: "center", padding: 60, color: "#5A6478", fontSize: 11 }}>No threads found</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead>
              <tr>
                {renderTh("", "priority", 28, false)}
                {renderTh("Status", "status", 85, true)}
                {renderTh("Type", "type", 100, true)}
                <th style={{ ...thStyle, width: "auto", cursor: "pointer" }} onClick={() => toggleSort("subject")}>
                  Subject {sortCol === "subject" ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}
                </th>
                {renderTh("EFJ", "efj", 85, true)}
                {renderTh("Sender", "sender", 140, true)}
                {renderTh("Msgs", "msgs", 42, false)}
                {renderTh("Updated", "time", 65, false)}
                <th style={{ ...thStyle, width: 95, textAlign: "center" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((thread, idx) => {
                const typeColors = LOCAL_EMAIL_TYPE_COLORS[thread.email_type] || LOCAL_EMAIL_TYPE_COLORS.general;
                const isSelected = selThread?.thread_id === thread.thread_id;
                const rowBg = isSelected ? "rgba(0,212,170,0.06)" : idx % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent";
                return (
                  <tr key={thread.thread_id} style={{ background: rowBg, cursor: "pointer" }}
                    draggable="true"
                    onDragStart={e => {
                      e.dataTransfer.setData("application/json", JSON.stringify(thread));
                      e.dataTransfer.effectAllowed = "copy";
                      e.currentTarget.style.opacity = "0.5";
                    }}
                    onDragEnd={e => { e.currentTarget.style.opacity = "1"; }}
                    onClick={() => setSelectedThread(isSelected ? null : thread)}
                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = idx % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent"; }}>
                    {/* Priority */}
                    <td style={{ ...cellStyle, textAlign: "center" }}>
                      <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                        background: thread.max_priority >= 5 ? "#EF4444" : thread.max_priority >= 4 ? "#F97316" : thread.max_priority >= 3 ? "#3B82F6" : "#4D5669" }} />
                    </td>
                    {/* Status */}
                    <td style={cellStyle}>
                      {thread.actioned && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.10)", color: "#22C55E", fontWeight: 600, marginRight: 2 }}>ACTIONED</span>}
                      {thread.needs_reply && !thread.actioned && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(239,68,68,0.15)", color: "#EF4444", fontWeight: 700 }}>NEEDS REPLY</span>}
                      {thread.has_csl_reply && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#22C55E", fontWeight: 600 }}>REPLIED</span>}
                      {!thread.needs_reply && !thread.has_csl_reply && thread.source === "unmatched" && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(249,115,22,0.12)", color: "#F97316", fontWeight: 600 }}>UNMATCHED</span>}
                      {thread.quote_status === "quoted" && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(59,130,246,0.15)", color: "#3B82F6", fontWeight: 700, marginLeft: 2 }}>QUOTED</span>}
                      {thread.quote_status === "won"    && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.15)",  color: "#22C55E", fontWeight: 700, marginLeft: 2 }}>WON</span>}
                      {thread.quote_status === "lost"   && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(239,68,68,0.12)",  color: "#EF4444", fontWeight: 700, marginLeft: 2 }}>LOST</span>}
                      {thread.quote_status === "pass"   && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(107,114,128,0.12)", color: "#9CA3AF", fontWeight: 700, marginLeft: 2 }}>PASS</span>}
                    </td>
                    {/* Type */}
                    <td style={cellStyle}>
                      {thread.email_type && (
                        <span style={{ fontSize: 7, padding: "1px 5px", borderRadius: 3, fontWeight: 700, background: typeColors.bg, color: typeColors.color, letterSpacing: "0.3px" }}>
                          {LOCAL_INBOX_TYPE_LABELS[thread.email_type] || thread.email_type.replace(/_/g, " ").toUpperCase()}
                        </span>
                      )}
                    </td>
                    {/* Subject */}
                    <td style={{ ...cellStyle, maxWidth: 0 }} title={thread.ai_summary || thread.latest_subject}>
                      <span style={{ fontWeight: 500 }}>{thread.latest_subject || "(no subject)"}</span>
                      {thread.has_attachments && <span style={{ marginLeft: 4, fontSize: 9, opacity: 0.5 }}>&#128206;</span>}
                    </td>
                    {/* EFJ */}
                    <td style={cellStyle}>
                      {thread.efj ? (
                        <span onClick={e => { e.stopPropagation(); openLoad(thread.efj); }}
                          style={{ padding: "1px 4px", borderRadius: 3, background: "rgba(0,212,170,0.10)", color: "#00D4AA", fontWeight: 600, fontSize: 9, fontFamily: "JetBrains Mono, monospace", cursor: "pointer" }}>
                          {thread.efj}
                        </span>
                      ) : <span style={{ color: "#4D5669", fontSize: 9 }}>--</span>}
                    </td>
                    {/* Sender */}
                    <td style={{ ...cellStyle, fontSize: 9, color: "#8B95A8", maxWidth: 0 }}>
                      {(thread.latest_sender || "").replace(/<[^>]+>/g, "").trim()}
                    </td>
                    {/* Msgs */}
                    <td style={{ ...cellStyle, textAlign: "center", color: "#8B95A8", fontSize: 9 }}>
                      {thread.message_count || 1}
                    </td>
                    {/* Updated */}
                    <td style={{ ...cellStyle, textAlign: "right", color: "#5A6478", fontSize: 9 }}>
                      {_relTime(thread.latest_sent_at)}
                    </td>
                    {/* Actions */}
                    <td style={{ ...cellStyle, textAlign: "center", padding: "3px 4px" }} onClick={e => e.stopPropagation()}>
                      {actionFlash === thread.thread_id ? (
                        <span style={{ fontSize: 9, color: "#22C55E", fontWeight: 700 }}>Done!</span>
                      ) : actioningThread === thread.thread_id ? (
                        <span style={{ fontSize: 8, color: "#8B95A8" }}>...</span>
                      ) : (() => {
                        const auto = getAutoAction(thread);
                        return (
                          <div style={{ display: "flex", gap: 3, justifyContent: "center", flexWrap: "wrap" }}>
                            {auto && (
                              <button onClick={() => handleAutoAction(thread, auto.action)}
                                style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 700, cursor: "pointer",
                                  background: auto.bg, color: auto.color, border: `1px solid ${auto.border}`, lineHeight: 1.3 }}>
                                {auto.label}
                              </button>
                            )}
                            {thread.needs_reply && thread.efj && (
                              <button onClick={() => {
                                const msgs = (thread.messages || []).map(m =>
                                  `[${m.direction === "sent" ? "CSL" : "External"}] ${(m.sender || "").replace(/<[^>]+>/g, "").trim()}: ${(m.body_text || m.body_preview || "").slice(0, 1000)}`
                                ).join("\n");
                                setAskAIInitialQuery(`Draft a professional reply to this email thread:\n\nSubject: ${thread.latest_subject || "(no subject)"}\nFrom: ${(thread.latest_sender || "").replace(/<[^>]+>/g, "").trim()}\nEFJ: ${thread.efj}\nType: ${thread.email_type || "general"}\n\nMessages:\n${msgs}\n\nWrite a concise, professional reply. Keep it brief and action-oriented.`);
                                setAskAIOpen(true);
                              }}
                                style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 700, cursor: "pointer",
                                  background: "rgba(59,130,246,0.10)", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.25)", lineHeight: 1.3 }}>
                                Draft
                              </button>
                            )}
                            {!thread.actioned && !auto && (
                              <button onClick={() => handleAutoAction(thread, "mark_actioned")}
                                style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 600, cursor: "pointer",
                                  background: "rgba(255,255,255,0.04)", color: "#5A6478", border: "1px solid rgba(255,255,255,0.08)", lineHeight: 1.3 }}>
                                Done
                              </button>
                            )}
                          </div>
                        );
                      })()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Thread Detail Slide-Over */}
      {selThread && (
        <div className="inbox-thread-panel" style={{ position: "fixed", right: 0, top: 0, height: "100vh", width: 480, zIndex: Z.threadPanel, background: "#0F1420", borderLeft: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", boxShadow: "-8px 0 30px rgba(0,0,0,0.5)", animation: "slideInRight 0.2s ease" }}>
          {/* Header */}
          <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)", flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <button onClick={() => setSelectedThread(null)}
                style={{ padding: "2px 6px", borderRadius: 4, fontSize: 12, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "none" }}>&#10005;</button>
              <div style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {selThread.latest_subject || "(no subject)"}
              </div>
              {(() => {
                const raw = selThread.latest_sender || "";
                const match = raw.match(/<([^>]+)>/) || raw.match(/[\w.+-]+@[\w.-]+\.\w+/);
                const toEmail = match ? (match[1] || match[0]) : null;
                if (!toEmail) return null;
                const subj = encodeURIComponent("Re: " + (selThread.latest_subject || ""));
                const href = `mailto:${toEmail}?subject=${subj}&cc=efj-operations%40evansdelivery.com`;
                return (
                  <a href={href}
                    style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700, background: "rgba(59,130,246,0.15)", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.3)", textDecoration: "none", flexShrink: 0 }}
                    title={`Reply to ${toEmail}`}>
                    {"\u21A9"} Reply
                  </a>
                );
              })()}
              {/* Draft Reply button */}
              <button onClick={() => {
                const msgs = (selThread.messages || []).map(m =>
                  `[${m.direction === "sent" ? "CSL" : "External"}] ${(m.sender || "").replace(/<[^>]+>/g, "").trim()}: ${(m.body_text || m.body_preview || "").slice(0, 1000)}`
                ).join("\n");
                setAskAIInitialQuery(`Draft a professional reply to this email thread:\n\nSubject: ${selThread.latest_subject || "(no subject)"}\nFrom: ${(selThread.latest_sender || "").replace(/<[^>]+>/g, "").trim()}\nEFJ: ${selThread.efj || "unmatched"}\nType: ${selThread.email_type || "general"}\n\nMessages:\n${msgs}\n\nWrite a concise, professional reply. Keep it brief and action-oriented.`);
                setAskAIOpen(true);
              }}
                style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700, background: "rgba(168,85,247,0.15)", color: "#A855F7", border: "1px solid rgba(168,85,247,0.3)", cursor: "pointer", flexShrink: 0 }}>
                Draft Reply
              </button>
              {/* Save Attachments button */}
              {selThread.has_attachments && selThread.efj && (
                <button onClick={() => handleAutoAction(selThread, "save_attachment")}
                  disabled={actioningThread === selThread.thread_id}
                  style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700, background: "rgba(0,212,170,0.15)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.3)", cursor: "pointer", flexShrink: 0, opacity: actioningThread === selThread.thread_id ? 0.5 : 1 }}>
                  {actioningThread === selThread.thread_id ? "Saving..." : "Save Docs"}
                </button>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              {selThread.email_type && (() => {
                const tc = LOCAL_EMAIL_TYPE_COLORS[selThread.email_type] || LOCAL_EMAIL_TYPE_COLORS.general;
                return <span style={{ fontSize: 8, padding: "2px 6px", borderRadius: 4, fontWeight: 700, background: tc.bg, color: tc.color }}>{LOCAL_INBOX_TYPE_LABELS[selThread.email_type] || selThread.email_type.replace(/_/g," ").toUpperCase()}</span>;
              })()}
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: selThread.max_priority >= 5 ? "#EF4444" : selThread.max_priority >= 4 ? "#F97316" : selThread.max_priority >= 3 ? "#3B82F6" : "#4D5669" }} />
              {selThread.efj && (
                <button onClick={() => openLoad(selThread.efj)}
                  style={{ padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(0,212,170,0.10)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.20)", fontFamily: "JetBrains Mono, monospace" }}>
                  {selThread.efj} &rarr; Open Load
                </button>
              )}
              {selThread.lane && <span style={{ fontSize: 9, color: "#8B95A8" }}>{selThread.lane}</span>}
            </div>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
            {/* AI Summary Card */}
            {selThread.ai_summary && (
              <div style={{ margin: "4px 16px 10px", padding: "10px 14px", borderRadius: 8, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                  <svg width="12" height="12" fill="none" stroke="#00D4AA" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z" /></svg>
                  <span style={{ fontSize: 8, fontWeight: 700, color: "#00D4AA", textTransform: "uppercase", letterSpacing: "0.5px" }}>AI Summary</span>
                </div>
                <div style={{ fontSize: 10, color: "#C8CDD8", lineHeight: 1.6 }}>{selThread.ai_summary}</div>
              </div>
            )}
            {(selThread.messages || []).map((msg, idx) => (
              <div key={idx} style={{ padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,0.03)", display: "flex", gap: 8 }}>
                <span style={{ fontSize: 11, color: msg.direction === "sent" ? "#00D4AA" : "#8B95A8", flexShrink: 0, marginTop: 1 }}>
                  {msg.direction === "sent" ? "\u2191" : "\u2193"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 500, color: msg.direction === "sent" ? "#00D4AA" : "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                      {msg.direction === "sent" ? "CSL Team" : (msg.sender || "").replace(/<[^>]+>/g, "").trim()}
                    </span>
                    <span style={{ fontSize: 8, color: "#5A6478", whiteSpace: "nowrap" }}>
                      {msg.sent_at ? new Date(msg.sent_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}
                    </span>
                  </div>
                  {msg.body_preview && (
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 3, lineHeight: 1.5, maxHeight: 60, overflow: "hidden" }}>
                      {msg.body_preview.slice(0, 300)}
                    </div>
                  )}
                  {msg.has_attachments && msg.attachment_names && (
                    <div style={{ fontSize: 8, color: "#8B95A8", marginTop: 3 }}>&#128206; {msg.attachment_names}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Actions */}
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", flexShrink: 0 }}>

            {/* Quote Action Bar */}
            {(() => {
              const isQuoteThread = selThread.email_type === "customer_rate" || selThread.corrected_type === "customer_rate";
              if (!isQuoteThread) return null;
              const currentStatus = quoteActions.hasOwnProperty(selMsgId) ? quoteActions[selMsgId] : selThread.quote_status;
              const QS_CONFIG = {
                quoted: { label: "Quoted \u2713", bg: "rgba(59,130,246,0.18)", color: "#3B82F6", border: "rgba(59,130,246,0.35)" },
                won:    { label: "Won \uD83C\uDFC6",    bg: "rgba(34,197,94,0.18)",  color: "#22C55E", border: "rgba(34,197,94,0.35)" },
                lost:   { label: "Lost \u2717",    bg: "rgba(239,68,68,0.15)",  color: "#EF4444", border: "rgba(239,68,68,0.30)" },
                pass:   { label: "Pass \u2014",    bg: "rgba(107,114,128,0.15)", color: "#9CA3AF", border: "rgba(107,114,128,0.30)" },
              };
              return (
                <div style={{ padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap", background: "rgba(0,0,0,0.12)" }}>
                  <span style={{ fontSize: 8, color: "#5A6478", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginRight: 2 }}>Quote</span>
                  {currentStatus ? (
                    <>
                      <span style={{ fontSize: 9, padding: "3px 10px", borderRadius: 5, fontWeight: 700,
                        background: QS_CONFIG[currentStatus]?.bg, color: QS_CONFIG[currentStatus]?.color,
                        border: `1px solid ${QS_CONFIG[currentStatus]?.border}` }}>
                        {QS_CONFIG[currentStatus]?.label}
                      </span>
                      {selThread.quote_status_at && (
                        <span style={{ fontSize: 8, color: "#4D5669" }}>
                          {new Date(selThread.quote_status_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                        </span>
                      )}
                      <button onClick={() => handleQuoteAction(selMsgId, null)}
                        style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, cursor: "pointer", background: "rgba(255,255,255,0.05)", color: "#5A6478", border: "1px solid rgba(255,255,255,0.08)" }}>
                        Clear
                      </button>
                    </>
                  ) : (
                    Object.entries(QS_CONFIG).map(([key, cfg]) => (
                      <button key={key} onClick={() => handleQuoteAction(selMsgId, key)}
                        style={{ padding: "4px 9px", borderRadius: 5, fontSize: 9, fontWeight: 600, cursor: "pointer",
                          background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}>
                        {cfg.label}
                      </button>
                    ))
                  )}
                  <div style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
                    {quoteLinkId === selMsgId ? (
                      <>
                        <input value={quoteLinkEfj} onChange={e => setQuoteLinkEfj(e.target.value)}
                          placeholder="EFJ#" autoFocus
                          onKeyDown={e => {
                            if (e.key === "Enter") handleQuoteAction(selMsgId, currentStatus || "quoted", quoteLinkEfj);
                            if (e.key === "Escape") { setQuoteLinkId(null); setQuoteLinkEfj(""); }
                          }}
                          style={{ width: 80, padding: "3px 7px", borderRadius: 5, fontSize: 10, background: "rgba(255,255,255,0.06)", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.14)", outline: "none", fontFamily: "JetBrains Mono, monospace" }} />
                        <button onClick={() => handleQuoteAction(selMsgId, currentStatus || "quoted", quoteLinkEfj)}
                          style={{ padding: "3px 8px", borderRadius: 5, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "#00D4AA", color: "#0A0E17", border: "none" }}>Link</button>
                        <button onClick={() => { setQuoteLinkId(null); setQuoteLinkEfj(""); }}
                          style={{ padding: "3px 6px", borderRadius: 5, fontSize: 9, cursor: "pointer", background: "rgba(255,255,255,0.05)", color: "#8B95A8", border: "none" }}>&#10005;</button>
                      </>
                    ) : (
                      <button onClick={() => setQuoteLinkId(selMsgId)} title={selThread.efj ? `Linked: ${selThread.efj}` : "Link to EFJ"}
                        style={{ padding: "3px 8px", borderRadius: 5, fontSize: 9, cursor: "pointer",
                          background: selThread.efj ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.05)",
                          color: selThread.efj ? "#00D4AA" : "#5A6478",
                          border: `1px solid ${selThread.efj ? "rgba(0,212,170,0.20)" : "rgba(255,255,255,0.08)"}`,
                          fontFamily: "JetBrains Mono, monospace" }}>
                        {selThread.efj ? selThread.efj : "Link EFJ"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* Rep Assign + Mark Actioned */}
            <div style={{ padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: 8, color: "#5A6478", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>Rep</span>
              <select value={selThread.manual_rep || selThread.rep || ""} onChange={async (e) => {
                const rep = e.target.value;
                const msgId = selMsgId;
                if (!msgId) return;
                try {
                  await apiFetch(`${API_BASE}/api/inbox/${msgId}/assign-rep`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rep }) });
                  setSelectedThread(prev => ({ ...prev, manual_rep: rep, rep }));
                } catch (err) { console.error("assign-rep error", err); }
              }}
                style={{ padding: "4px 8px", borderRadius: 5, fontSize: 10, background: "#141A28", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.12)", cursor: "pointer" }}>
                <option value="">Unassigned</option>
                {["Eli", "Radka", "John F", "Janice"].map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                <button onClick={async () => {
                  const newVal = !selThread.actioned;
                  const msgId = selMsgId;
                  if (!msgId) return;
                  try {
                    await apiFetch(`${API_BASE}/api/inbox/${msgId}/mark-actioned`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actioned: newVal }) });
                    setSelectedThread(prev => ({ ...prev, actioned: newVal }));
                  } catch (err) { console.error("mark-actioned error", err); }
                }}
                  style={{ padding: "4px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer",
                    background: selThread.actioned ? "rgba(34,197,94,0.10)" : "rgba(255,255,255,0.05)",
                    color: selThread.actioned ? "#22C55E" : "#8B95A8",
                    border: `1px solid ${selThread.actioned ? "rgba(34,197,94,0.20)" : "rgba(255,255,255,0.08)"}` }}>
                  {selThread.actioned ? "\u2713 Actioned" : "Mark Actioned"}
                </button>
              </div>
            </div>

            {/* Assign / Dismiss / Classification feedback */}
            <div style={{ padding: "8px 16px", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              {selThread.source === "unmatched" && assigningId !== selMsgId && (
                <>
                  <button onClick={() => setAssigningId(selMsgId)}
                    style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(59,130,246,0.10)", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.20)" }}>
                    Assign to Load
                  </button>
                  <button onClick={() => handleDismiss(selMsgId)}
                    style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>
                    Dismiss
                  </button>
                </>
              )}
              {assigningId === selMsgId && (
                <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  <input value={assignEfj} onChange={e => setAssignEfj(e.target.value)} placeholder="EFJ#" autoFocus
                    onKeyDown={e => { if (e.key === "Enter") handleAssign(selMsgId); if (e.key === "Escape") { setAssigningId(null); setAssignEfj(""); } }}
                    style={{ width: 90, padding: "4px 8px", borderRadius: 6, fontSize: 10, background: "rgba(255,255,255,0.06)", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.12)", outline: "none", fontFamily: "JetBrains Mono, monospace" }} />
                  <button onClick={() => handleAssign(selMsgId)}
                    style={{ padding: "4px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "#00D4AA", color: "#0A0E17", border: "none" }}>Assign</button>
                  <button onClick={() => { setAssigningId(null); setAssignEfj(""); }}
                    style={{ padding: "4px 8px", borderRadius: 6, fontSize: 9, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.08)" }}>Cancel</button>
                </div>
              )}
              <div style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
                {selFeedback ? (
                  <span style={{ fontSize: 9, color: selFeedback === "correct" ? "#22C55E" : "#F97316", fontWeight: 600 }}>
                    {selFeedback === "correct" ? "Confirmed" : "Corrected"}
                  </span>
                ) : selMsgId && correctionId !== selMsgId ? (
                  <>
                    <button onClick={() => handleFeedback(selMsgId, "correct")} title="Classification correct"
                      style={{ padding: "3px 8px", borderRadius: 4, fontSize: 11, cursor: "pointer", background: "rgba(34,197,94,0.08)", color: "#22C55E", border: "1px solid rgba(34,197,94,0.15)" }}>&#128077;</button>
                    <button onClick={() => setCorrectionId(selMsgId)} title="Classification incorrect"
                      style={{ padding: "3px 8px", borderRadius: 4, fontSize: 11, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>&#128078;</button>
                  </>
                ) : null}
                {correctionId === selMsgId && (
                  <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
                    <select onChange={e => handleFeedback(selMsgId, "incorrect", e.target.value)} defaultValue=""
                      style={{ padding: "3px 8px", borderRadius: 4, fontSize: 9, background: "#141A28", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.12)" }}>
                      <option value="" disabled>Correct type...</option>
                      {CORRECTION_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
                    </select>
                    <button onClick={() => setCorrectionId(null)}
                      style={{ padding: "2px 6px", borderRadius: 4, fontSize: 9, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "none" }}>&#10005;</button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
