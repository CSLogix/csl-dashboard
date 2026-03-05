import { useState, useEffect, useRef, useCallback, Fragment } from "react";

// ─── API helper (same pattern as DispatchDashboard) ───
const apiFetch = (url, opts = {}) =>
  fetch(url, { ...opts, credentials: "include" }).then(res => {
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Session expired"); }
    return res;
  });

// ─── Logo (shared with CSLQuoteCards) ───
const LOGO_ICON = "data:image/png;base64,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";

const grad = "linear-gradient(135deg, #00c853 0%, #00b8d4 50%, #2979ff 100%)";

// ─── Formatting helpers ───
const fmt = (n) => {
  const num = parseFloat(n);
  return isNaN(num) ? "$0.00" : "$" + num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
};
const parseNum = (s) => {
  const n = parseFloat(String(s).replace(/[$,]/g, ""));
  return isNaN(n) ? 0 : n;
};

// ─── Section options for linehaul rows ───
const SECTION_OPTIONS = ["Charges", "Dray/Transload", "OTR", "Transload", "LTL"];

const defaultSection = (type) => {
  if (type === "Dray") return "Charges";
  if (type === "FTL" || type === "OTR") return "OTR";
  if (type === "Transload") return "Transload";
  if (type === "Dray+Transload") return "Dray/Transload";
  if (type === "LTL") return "LTL";
  return "Charges";
};

// ─── Default accessorials ───
const DEFAULT_ACCESSORIALS = [
  { charge: "Storage", rate: "45.00", frequency: "per day", checked: false, amount: "45.00" },
  { charge: "Pre-Pull", rate: "150.00", frequency: "flat", checked: false, amount: "150.00" },
  { charge: "Chassis (2 days)", rate: "45.00", frequency: "per day", checked: false, amount: "45.00" },
  { charge: "Overweight", rate: "150.00", frequency: "flat", checked: false, amount: "150.00" },
  { charge: "Detention", rate: "85.00", frequency: "per hour", checked: false, amount: "85.00" },
];

const DEFAULT_TERMS = [
  "Rates valid for 7 days from quote date",
  "Subject to carrier availability at time of booking",
  "Accessorial charges may vary based on actual services required",
  "Payment terms: Net 30 days from invoice date",
];

// ════════════════════════════════════════════════════════════
// ─── Quote Preview Card (customer-facing) ───
// ════════════════════════════════════════════════════════════
function QuotePreview({ route, linehaul, accessorials, marginPct, marginType, terms, quoteNumber, shipmentType }) {
  const margin = parseNum(marginPct) / 100;
  const flatMarkup = marginType === "flat" ? parseNum(marginPct) : 0;
  const isRoundTrip = shipmentType === "Dray";

  // Build route data for card — format-specific labels (always show rows, "—" if empty)
  const routeRows = [];
  routeRows.push({ label: isRoundTrip ? "POD" : "Port / Origin", value: route.pod || "—" });
  routeRows.push({ label: "Delivery Destination", value: route.finalDelivery || "—" });
  routeRows.push({ label: isRoundTrip ? "R/T Mileage" : "One-Way Mileage", value: (isRoundTrip ? route.roundTripMiles : route.oneWayMiles) || "—" });
  // Dray: show drive hours rounded up to nearest 15 min. FTL/other: show day-range string.
  let transitDisplay = "—";
  if (isRoundTrip && route.durationHours) {
    const h = parseFloat(route.durationHours);
    if (!isNaN(h)) {
      const rounded = Math.ceil(h * 4) / 4; // round up to nearest 0.25 hr
      const hrs = Math.floor(rounded);
      const mins = Math.round((rounded - hrs) * 60);
      transitDisplay = mins > 0 ? `${hrs} hr ${mins} min` : `${hrs} hr`;
    }
  } else if (route.transitTime) {
    transitDisplay = route.transitTime;
  }
  routeRows.push({ label: "Transit Time (One-Way)", value: transitDisplay });

  // Group linehaul by section with margin applied
  const lhBySection = {};
  linehaul.filter(r => r.description && parseNum(r.rate) > 0).forEach(r => {
    const sec = r.section || "Charges";
    if (!lhBySection[sec]) lhBySection[sec] = [];
    const base = parseNum(r.rate);
    const sell = marginType === "flat" ? base + flatMarkup : base * (1 + margin);
    lhBySection[sec].push({
      desc: r.description,
      rate: fmt(sell),
    });
  });
  const sellSubtotal = linehaul.reduce((sum, r) => {
    const base = parseNum(r.rate);
    return sum + (marginType === "flat" ? base + flatMarkup : base * (1 + margin));
  }, 0);

  // All accessorials with amounts show on preview; only checked ones count toward total
  const accRows = accessorials.filter(a => parseNum(a.amount) > 0).map(a => ({
    desc: a.charge + (a.frequency && a.frequency !== "flat" ? ` ${a.frequency}` : ""),
    rate: fmt(parseNum(a.amount)),
    included: a.checked,
  }));
  const accTotal = accessorials.filter(a => a.checked).reduce((sum, a) => sum + parseNum(a.amount), 0);
  const total = sellSubtotal + accTotal;

  // Build sections — linehaul groups first, then accessorials
  const sections = [];
  Object.entries(lhBySection).forEach(([title, rows]) => {
    sections.push({ title: title.toUpperCase(), rows });
  });
  if (accRows.length > 0) sections.push({ title: "ACCESSORIAL CHARGES", rows: accRows });

  const cellLabel = { padding: "8px 20px", fontSize: 13.5, fontWeight: 700, color: "rgba(255,255,255,0.85)", borderBottom: "1px solid rgba(255,255,255,0.04)" };
  const cellValue = { padding: "8px 20px", fontSize: 13.5, fontWeight: 700, color: "#fff", textAlign: "right", borderBottom: "1px solid rgba(255,255,255,0.04)" };
  const sectionHead = (left) => ({ padding: "9px 20px", fontSize: 12, fontWeight: 800, letterSpacing: "0.06em", textTransform: "uppercase", textAlign: left ? "left" : "right", background: "rgba(0,200,83,0.06)", borderTop: "2px solid", borderImage: grad + " 1", backgroundClip: "text", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundImage: grad });
  const rowL = { padding: "8px 20px", fontSize: 13.5, fontWeight: 500, color: "rgba(255,255,255,0.7)", borderBottom: "1px solid rgba(255,255,255,0.04)" };
  const rowR = { padding: "8px 20px", fontSize: 13.5, color: "#fff", fontWeight: 700, textAlign: "right", fontVariantNumeric: "tabular-nums", borderBottom: "1px solid rgba(255,255,255,0.04)" };
  const totalL = { padding: "14px 20px", fontSize: 12, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", borderTop: "2px solid", borderImage: grad + " 1", background: "rgba(0,200,83,0.04)", backgroundClip: "text", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundImage: grad, verticalAlign: "middle" };
  const totalR = { padding: "14px 20px", fontSize: 24, fontWeight: 800, textAlign: "right", borderTop: "2px solid", borderImage: grad + " 1", background: "rgba(0,200,83,0.04)", fontVariantNumeric: "tabular-nums", backgroundClip: "text", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundImage: grad, verticalAlign: "middle" };

  return (
    <div id="quote-preview-card" style={{ width: "100%", maxWidth: 520 }}>
      <table cellPadding={0} cellSpacing={0} style={{ fontFamily: "'Segoe UI', -apple-system, sans-serif", width: "100%", background: "#0f1215", borderRadius: 10, overflow: "hidden", borderCollapse: "collapse", color: "#fff" }}>
        <tbody>
          {/* Header */}
          <tr>
            <td colSpan={2} style={{ padding: "18px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <img src="/logo.svg" alt="CSL" style={{ height: 64, width: 64, objectFit: "contain", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "0.01em" }}>Common Sense Logistics</div>
                  <div style={{ fontSize: 10.5, color: "rgba(255,255,255,0.35)", fontWeight: 500, marginTop: 1 }}>Evans Delivery Company</div>
                </div>
                {quoteNumber && (
                  <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", fontWeight: 600, textAlign: "right" }}>
                    {quoteNumber}
                  </div>
                )}
              </div>
            </td>
          </tr>

          {/* Route Info */}
          {routeRows.map((row, i) => (
            <tr key={i}><td style={cellLabel}>{row.label}</td><td style={cellValue}>{row.value}</td></tr>
          ))}

          {routeRows.length > 0 && <tr><td colSpan={2} style={{ height: 10 }} /></tr>}

          {/* Sections */}
          {sections.map((section, si) => (
            <Fragment key={si}>
              <tr><td style={sectionHead(true)}>{section.title}</td><td style={sectionHead(false)}>Rate</td></tr>
              {section.rows.map((row, ri) => (
                <tr key={ri}>
                  <td style={rowL}>{row.desc}</td>
                  <td style={rowR}>{row.rate}</td>
                </tr>
              ))}
            </Fragment>
          ))}

          {/* Total */}
          <tr>
            <td style={totalL}>Estimated Total Invoice</td>
            <td style={totalR}>{fmt(total)}</td>
          </tr>

          {/* Footer gradient */}
          <tr><td colSpan={2} style={{ height: 3, background: grad }} /></tr>
        </tbody>
      </table>
    </div>
  );
}


// ════════════════════════════════════════════════════════════
// ─── History Tab ───
// ════════════════════════════════════════════════════════════

const STATUS_FILTERS = [
  { key: null, label: "All" },
  { key: "draft", label: "Drafts" },
  { key: "sent", label: "Sent" },
  { key: "accepted", label: "Won" },
  { key: "lost", label: "Lost" },
  { key: "expired", label: "Expired" },
];

const statusColor = { draft: "#F59E0B", sent: "#3B82F6", accepted: "#00D4AA", lost: "#EF4444", expired: "#6B7280" };
const statusIcon = { draft: "\u270F", sent: "\u2709", accepted: "\u2713", lost: "\u2717", expired: "\u23F3" };

const SORT_OPTIONS = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "highest", label: "Highest $" },
  { key: "lowest", label: "Lowest $" },
  { key: "customer", label: "Customer" },
];

function _relativeTime(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now - d;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function _sortQuotes(quotes, sortKey) {
  const sorted = [...quotes];
  switch (sortKey) {
    case "oldest": return sorted.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    case "highest": return sorted.sort((a, b) => (b.estimated_total || 0) - (a.estimated_total || 0));
    case "lowest": return sorted.sort((a, b) => (a.estimated_total || 0) - (b.estimated_total || 0));
    case "customer": return sorted.sort((a, b) => (a.customer_name || "").localeCompare(b.customer_name || ""));
    default: return sorted.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  }
}

const PAGE_SIZE = 25;

function HistoryTab({ onLoadQuote }) {
  const [quotes, setQuotes] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(null);
  const [sortBy, setSortBy] = useState("newest");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const searchTimer = useRef(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [updatingId, setUpdatingId] = useState(null);

  // Debounce search input — 400ms
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(searchTimer.current);
  }, [search]);

  // Reset page when filters change
  useEffect(() => { setPage(0); }, [debouncedSearch, statusFilter, sortBy]);

  const fetchQuotes = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "200", offset: "0" });
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (statusFilter) params.set("status", statusFilter);
    apiFetch(`/api/quotes?${params}`).then(r => r.json()).then(data => {
      setQuotes(data.quotes || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [debouncedSearch, statusFilter]);

  useEffect(() => { fetchQuotes(); }, [fetchQuotes]);

  const handleStatusUpdate = async (e, id, newStatus) => {
    e.stopPropagation();
    setUpdatingId(id);
    try {
      const res = await apiFetch(`/api/quotes/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        setQuotes(prev => prev.map(q => q.id === id ? { ...q, status: newStatus } : q));
      }
    } catch (err) {
      console.error("Status update failed:", err);
    } finally {
      setUpdatingId(null);
    }
  };

  const sorted = _sortQuotes(quotes, sortBy);
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const pageQuotes = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const chipStyle = (active) => ({
    padding: "5px 10px", borderRadius: 6, border: "1px solid",
    borderColor: active ? "rgba(0,212,170,0.4)" : "rgba(255,255,255,0.08)",
    background: active ? "rgba(0,212,170,0.1)" : "transparent",
    color: active ? "#00D4AA" : "#5A6478",
    fontSize: 11, fontWeight: 600, cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

      {/* Search bar */}
      <div style={{ position: "relative" }}>
        <svg style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", opacity: 0.35 }} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search by quote #, customer, lane..."
          style={{ width: "100%", padding: "10px 14px 10px 34px", background: "#0D1119", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#F0F2F5", fontSize: 13, outline: "none" }} />
        {search && (
          <button onClick={() => setSearch("")}
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 16, lineHeight: 1 }}>&times;</button>
        )}
      </div>

      {/* Status filter chips */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {STATUS_FILTERS.map(f => (
          <button key={f.key || "all"} onClick={() => setStatusFilter(f.key)} style={chipStyle(statusFilter === f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Sort + count row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#5A6478" }}>
          {sorted.length} quote{sorted.length !== 1 ? "s" : ""}
          {debouncedSearch ? ` matching "${debouncedSearch}"` : ""}
        </span>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)}
          style={{ background: "#0D1119", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#8B95A8", fontSize: 11, padding: "4px 8px", cursor: "pointer", outline: "none" }}>
          {SORT_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </div>

      {/* Results */}
      {loading ? (
        <div style={{ textAlign: "center", color: "#5A6478", padding: 40, fontSize: 12 }}>Loading...</div>
      ) : pageQuotes.length === 0 ? (
        <div style={{ textAlign: "center", color: "#5A6478", padding: 40, fontSize: 12 }}>
          {quotes.length === 0 ? "No quotes yet — build your first one!" : "No quotes match your filters"}
        </div>
      ) : (
        pageQuotes.map(q => {
          const st = q.status || "draft";
          const lane = [q.pod, q.final_delivery].filter(Boolean).join(" → ");
          const typeLabel = q.shipment_type || "";
          const isUpdating = updatingId === q.id;
          const showActions = st === "draft" || st === "sent";
          return (
            <div key={q.id} onClick={() => onLoadQuote(q.id)}
              style={{ background: "#141A28", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, padding: "12px 14px", cursor: "pointer", transition: "border-color 0.15s" }}
              onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(255,255,255,0.15)"}
              onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"}>

              {/* Row 1: lane (primary) + status badge */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>
                    {lane || q.quote_number}
                  </span>
                  {typeLabel && (
                    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                      background: typeLabel === "Dray" ? "rgba(59,130,246,0.15)" : typeLabel === "FTL" ? "rgba(139,92,246,0.15)" : typeLabel === "Transload" ? "rgba(245,158,11,0.15)" : typeLabel === "Dray+Transload" ? "rgba(236,72,153,0.15)" : typeLabel === "OTR" ? "rgba(139,92,246,0.15)" : typeLabel === "LTL" ? "rgba(20,184,166,0.15)" : "rgba(255,255,255,0.06)",
                      color: typeLabel === "Dray" ? "#60A5FA" : typeLabel === "FTL" ? "#A78BFA" : typeLabel === "Transload" ? "#F59E0B" : typeLabel === "Dray+Transload" ? "#EC4899" : typeLabel === "OTR" ? "#A78BFA" : typeLabel === "LTL" ? "#14B8A6" : "#8B95A8",
                      textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {typeLabel}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 700, color: statusColor[st] || "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  <span>{statusIcon[st] || ""}</span>
                  <span>{st}</span>
                </div>
              </div>

              {/* Row 2: quote # + customer/carrier */}
              <div style={{ fontSize: 11, color: "#8B95A8", marginBottom: 4, display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ color: "#5A6478", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>{q.quote_number}</span>
                {q.customer_name && <><span style={{ color: "#3A4050" }}>·</span><span style={{ color: "#C8CED8", fontWeight: 600, fontSize: 12 }}>{q.customer_name}</span></>}
                {q.carrier_name && <><span style={{ color: "#3A4050" }}>·</span><span style={{ fontSize: 11 }}>{q.carrier_name}</span></>}
              </div>

              {/* Row 3: date + total + action buttons */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, color: "#5A6478" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span title={q.created_at ? new Date(q.created_at).toLocaleString() : ""}>{_relativeTime(q.created_at)}</span>
                  {showActions && !isUpdating && (
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={e => handleStatusUpdate(e, q.id, "accepted")}
                        style={{ padding: "2px 8px", borderRadius: 4, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", fontSize: 10, fontWeight: 700, cursor: "pointer", transition: "all 0.15s", textTransform: "uppercase", letterSpacing: "0.03em" }}
                        onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,212,170,0.2)"; }}
                        onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,212,170,0.08)"; }}>
                        Won
                      </button>
                      <button onClick={e => handleStatusUpdate(e, q.id, "lost")}
                        style={{ padding: "2px 8px", borderRadius: 4, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)", color: "#EF4444", fontSize: 10, fontWeight: 700, cursor: "pointer", transition: "all 0.15s", textTransform: "uppercase", letterSpacing: "0.03em" }}
                        onMouseEnter={e => { e.currentTarget.style.background = "rgba(239,68,68,0.2)"; }}
                        onMouseLeave={e => { e.currentTarget.style.background = "rgba(239,68,68,0.08)"; }}>
                        Lost
                      </button>
                    </div>
                  )}
                  {isUpdating && <span style={{ fontSize: 10, color: "#5A6478" }}>Updating...</span>}
                </div>
                <span style={{ fontWeight: 700, fontSize: 13, color: q.estimated_total > 0 ? "#00D4AA" : "#5A6478" }}>
                  {q.estimated_total ? fmt(q.estimated_total) : "—"}
                </span>
              </div>
            </div>
          );
        })
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 8, paddingTop: 4 }}>
          <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
            style={{ background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: page === 0 ? "#3A4050" : "#8B95A8", padding: "4px 10px", fontSize: 11, cursor: page === 0 ? "default" : "pointer" }}>
            Prev
          </button>
          <span style={{ fontSize: 11, color: "#5A6478" }}>{page + 1} / {totalPages}</span>
          <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
            style={{ background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: page >= totalPages - 1 ? "#3A4050" : "#8B95A8", padding: "4px 10px", fontSize: 11, cursor: page >= totalPages - 1 ? "default" : "pointer" }}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}


// ════════════════════════════════════════════════════════════
// ─── Main QuoteBuilder Component ───
// ════════════════════════════════════════════════════════════
export default function QuoteBuilder() {
  const [tab, setTab] = useState("builder"); // builder | history
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [quoteNumber, setQuoteNumber] = useState("");
  const [fetchingMiles, setFetchingMiles] = useState(false);
  const fileInputRef = useRef(null);
  const previewRef = useRef(null);

  // ── Route state ──
  const [route, setRoute] = useState({
    pod: "", finalDelivery: "", finalZip: "", roundTripMiles: "", oneWayMiles: "", transitTime: "", durationHours: null, shipmentType: "Dray",
  });

  // ── Linehaul rows (with section grouping) ──
  const [linehaul, setLinehaul] = useState([
    { description: "", rate: "", section: "Charges" },
  ]);

  // ── Margin ──
  const [marginPct, setMarginPct] = useState(15);
  const [marginType, setMarginType] = useState("pct"); // "pct" or "flat"

  // ── Accessorials ──
  const [accessorials, setAccessorials] = useState(JSON.parse(JSON.stringify(DEFAULT_ACCESSORIALS)));

  // ── Terms ──
  const [terms, setTerms] = useState([...DEFAULT_TERMS]);

  // ── Customer ──
  const [customerName, setCustomerName] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");

  // ── Carrier (internal) ──
  const [carrierName, setCarrierName] = useState("");

  // Load defaults from server on mount
  useEffect(() => {
    apiFetch("/api/quotes/settings").then(r => r.json()).then(data => {
      if (data.default_margin_pct) setMarginPct(data.default_margin_pct);
      if (data.default_terms?.length) setTerms(data.default_terms);
      if (data.default_accessorials?.length) setAccessorials(data.default_accessorials);
    }).catch(() => {});
  }, []);

  // ── Auto-populate mileage when origin + destination both filled ──
  const mileageTimer = useRef(null);
  useEffect(() => {
    if (!route.pod || !route.finalDelivery) return;
    if (mileageTimer.current) clearTimeout(mileageTimer.current);
    mileageTimer.current = setTimeout(async () => {
      setFetchingMiles(true);
      try {
        const params = new URLSearchParams({ origin: route.pod, destination: route.finalDelivery });
        const res = await apiFetch(`/api/quotes/distance?${params}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.one_way_miles) {
          setRoute(prev => ({
            ...prev,
            oneWayMiles: String(data.one_way_miles),
            roundTripMiles: String(data.round_trip_miles || data.one_way_miles * 2),
            transitTime: prev.transitTime || data.transit_time || "",
            durationHours: data.duration_hours || null,
          }));
        }
      } catch { /* distance API not available yet */ }
      finally { setFetchingMiles(false); }
    }, 1200);
    return () => clearTimeout(mileageTimer.current);
  }, [route.pod, route.finalDelivery]);

  // ── Calculations ──
  const margin = parseNum(marginPct) / 100;
  const flatMarkup = marginType === "flat" ? parseNum(marginPct) : 0;
  const carrierSubtotal = linehaul.reduce((s, r) => s + parseNum(r.rate), 0);
  const sellSubtotal = linehaul.reduce((s, r) => {
    const base = parseNum(r.rate);
    return s + (marginType === "flat" ? base + flatMarkup : base * (1 + margin));
  }, 0);
  const accTotal = accessorials.filter(a => a.checked).reduce((s, a) => s + parseNum(a.amount), 0);
  const estimatedTotal = sellSubtotal + accTotal;

  // ── Linehaul handlers ──
  const updateLH = (i, field, val) => setLinehaul(prev => prev.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
  const addLH = () => setLinehaul(prev => [...prev, { description: "", rate: "", section: defaultSection(route.shipmentType) }]);
  const removeLH = (i) => setLinehaul(prev => prev.length > 1 ? prev.filter((_, idx) => idx !== i) : prev);

  // ── Accessorial handlers ──
  const updateAcc = (i, field, val) => setAccessorials(prev => prev.map((a, idx) => idx === i ? { ...a, [field]: val } : a));
  const toggleAcc = (i) => setAccessorials(prev => prev.map((a, idx) => idx === i ? { ...a, checked: !a.checked } : a));
  const addAcc = () => setAccessorials(prev => [...prev, { charge: "", rate: "", frequency: "flat", checked: false, amount: "" }]);
  const removeAcc = (i) => setAccessorials(prev => prev.filter((_, idx) => idx !== i));

  // ── Drag-to-reorder accessorials ──
  const dragIdx = useRef(null);
  const dragOverIdx = useRef(null);
  const handleAccDragStart = (i) => { dragIdx.current = i; };
  const handleAccDragOver = (e, i) => { e.preventDefault(); dragOverIdx.current = i; };
  const handleAccDrop = () => {
    const from = dragIdx.current;
    const to = dragOverIdx.current;
    if (from === null || to === null || from === to) return;
    setAccessorials(prev => {
      const copy = [...prev];
      const [item] = copy.splice(from, 1);
      copy.splice(to, 0, item);
      return copy;
    });
    dragIdx.current = null;
    dragOverIdx.current = null;
  };

  // ── Route handler ──
  const updateRoute = (field, val) => setRoute(prev => ({ ...prev, [field]: val }));

  // ── Extract from file ──
  const handleExtract = async (file) => {
    if (!file) return;
    setExtracting(true);
    setSaveMsg(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiFetch("/api/quotes/extract", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      // Populate fields from extraction
      if (data.carrier_name) setCarrierName(data.carrier_name);
      if (data.origin) updateRoute("pod", data.origin);
      if (data.destination) updateRoute("finalDelivery", data.destination);
      if (data.shipment_type) updateRoute("shipmentType", data.shipment_type);
      if (data.round_trip_miles) updateRoute("roundTripMiles", data.round_trip_miles);
      if (data.one_way_miles) updateRoute("oneWayMiles", data.one_way_miles);
      if (data.transit_time) updateRoute("transitTime", data.transit_time);

      if (data.linehaul_items?.length) {
        setLinehaul(data.linehaul_items.map(item => ({
          description: item.description || "",
          rate: item.rate || "",
          section: item.section || defaultSection(data.shipment_type || route.shipmentType),
        })));
      }
      if (data.accessorials?.length) {
        // Merge with defaults — match by charge name
        setAccessorials(prev => {
          const merged = prev.map(a => {
            const match = data.accessorials.find(ex => ex.charge?.toLowerCase() === a.charge?.toLowerCase());
            return match ? { ...a, rate: match.rate || a.rate, frequency: match.frequency || a.frequency, amount: match.amount || a.amount, checked: false } : a;
          });
          // Add any new accessorials not in defaults
          const existing = new Set(prev.map(a => a.charge?.toLowerCase()));
          const extras = data.accessorials.filter(ex => !existing.has(ex.charge?.toLowerCase())).map(ex => ({
            charge: ex.charge || "", rate: ex.rate || "", frequency: ex.frequency || "flat", checked: false, amount: ex.amount || "",
          }));
          return [...merged, ...extras];
        });
      }
      setSaveMsg({ type: "success", text: "Extracted! Review and adjust rates." });
    } catch (err) {
      setSaveMsg({ type: "error", text: `Extraction failed: ${err.message}` });
    } finally {
      setExtracting(false);
    }
  };

  // ── Drop zone ──
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer?.files?.[0];
    if (file) handleExtract(file);
  };

  // ── Extract from pasted text ──
  const handleExtractText = async (text) => {
    if (!text || text.trim().length < 20) return; // ignore tiny pastes
    setExtracting(true);
    setSaveMsg(null);
    try {
      const formData = new FormData();
      formData.append("text", text);
      const res = await apiFetch("/api/quotes/extract", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.carrier_name) setCarrierName(data.carrier_name);
      if (data.origin) updateRoute("pod", data.origin);
      if (data.destination) updateRoute("finalDelivery", data.destination);
      if (data.shipment_type) updateRoute("shipmentType", data.shipment_type);
      if (data.round_trip_miles) updateRoute("roundTripMiles", data.round_trip_miles);
      if (data.one_way_miles) updateRoute("oneWayMiles", data.one_way_miles);
      if (data.transit_time) updateRoute("transitTime", data.transit_time);
      if (data.linehaul_items?.length) {
        setLinehaul(data.linehaul_items.map(item => ({
          description: item.description || "",
          rate: item.rate || "",
          section: item.section || defaultSection(data.shipment_type || route.shipmentType),
        })));
      }
      if (data.accessorials?.length) {
        setAccessorials(prev => {
          const merged = prev.map(a => {
            const match = data.accessorials.find(ex => ex.charge?.toLowerCase() === a.charge?.toLowerCase());
            return match ? { ...a, rate: match.rate || a.rate, frequency: match.frequency || a.frequency, amount: match.amount || a.amount, checked: false } : a;
          });
          const existing = new Set(prev.map(a => a.charge?.toLowerCase()));
          const extras = data.accessorials.filter(ex => !existing.has(ex.charge?.toLowerCase())).map(ex => ({
            charge: ex.charge || "", rate: ex.rate || "", frequency: ex.frequency || "flat", checked: false, amount: ex.amount || "",
          }));
          return [...merged, ...extras];
        });
      }
      setSaveMsg({ type: "success", text: "Extracted! Review and adjust rates." });
    } catch (err) {
      setSaveMsg({ type: "error", text: `Extraction failed: ${err.message}` });
    } finally {
      setExtracting(false);
    }
  };

  // ── Clipboard paste (Ctrl+V screenshot or text) ──
  useEffect(() => {
    const handlePaste = (e) => {
      // Don't intercept paste if user is typing in an input/textarea
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const items = e.clipboardData?.items;
      if (!items) return;
      // Check for image first
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) handleExtract(file);
          return;
        }
      }
      // Then check for text (email body, rate text)
      const text = e.clipboardData.getData("text/plain");
      if (text && text.trim().length >= 20) {
        e.preventDefault();
        handleExtractText(text);
      }
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, []);

  // ── Save quote ──
  const handleSave = async (status = "draft") => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const isRT = route.shipmentType === "Dray";
      const payload = {
        status,
        pod: route.pod, final_delivery: route.finalDelivery, final_zip: route.finalZip,
        round_trip_miles: route.roundTripMiles, one_way_miles: route.oneWayMiles,
        transit_time: route.transitTime, shipment_type: route.shipmentType,
        carrier_name: carrierName, carrier_total: carrierSubtotal,
        margin_pct: marginPct, margin_type: marginType, sell_subtotal: sellSubtotal,
        accessorial_total: accTotal, estimated_total: estimatedTotal,
        customer_name: customerName, customer_email: customerEmail,
        linehaul_items: linehaul, accessorials, terms,
        route: [
          route.pod && { label: isRT ? "POD" : "Port / Origin", value: route.pod },
          route.finalDelivery && { label: "Delivery Destination", value: route.finalDelivery },
          isRT && route.roundTripMiles && { label: "R/T Mileage", value: route.roundTripMiles },
          !isRT && route.oneWayMiles && { label: "One-Way Mileage", value: route.oneWayMiles },
          route.transitTime && { label: "Transit Time (One-Way)", value: route.transitTime },
        ].filter(Boolean),
      };

      const formData = new FormData();
      formData.append("quote_data", JSON.stringify(payload));

      let res;
      if (editingId) {
        res = await apiFetch(`/api/quotes/${editingId}`, { method: "PUT", body: formData });
      } else {
        res = await apiFetch("/api/quotes", { method: "POST", body: formData });
      }
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.quote_number) setQuoteNumber(data.quote_number);
      if (data.id) setEditingId(data.id);
      setSaveMsg({ type: "success", text: `Saved as ${data.quote_number || "updated"}` });
    } catch (err) {
      setSaveMsg({ type: "error", text: err.message });
    } finally {
      setSaving(false);
    }
  };

  // ── Load quote from history ──
  const handleLoadQuote = async (id) => {
    try {
      const res = await apiFetch(`/api/quotes/${id}`);
      const q = await res.json();
      setEditingId(q.id);
      setQuoteNumber(q.quote_number);
      setRoute({
        pod: q.pod || "", finalDelivery: q.final_delivery || "", finalZip: q.final_zip || "",
        roundTripMiles: q.round_trip_miles || "", oneWayMiles: q.one_way_miles || "",
        transitTime: q.transit_time || "", shipmentType: q.shipment_type || "Dray",
      });
      setCarrierName(q.carrier_name || "");
      setCustomerName(q.customer_name || "");
      setCustomerEmail(q.customer_email || "");
      setMarginType(q.margin_type || "pct");
      setMarginPct(q.margin_pct || 15);
      if (q.linehaul_json?.length) setLinehaul(q.linehaul_json);
      if (q.accessorials_json?.length) setAccessorials(q.accessorials_json);
      if (q.terms_json?.length) setTerms(q.terms_json);
      setTab("builder");
    } catch (err) {
      console.error("Failed to load quote:", err);
    }
  };

  // ── Export PDF ──
  const handleExportPDF = async () => {
    const el = document.getElementById("quote-preview-card");
    if (!el) return;
    try {
      const { default: html2canvas } = await import("html2canvas");
      const { default: jsPDF } = await import("jspdf");
      const canvas = await html2canvas(el, { backgroundColor: null, scale: 2 });
      const imgData = canvas.toDataURL("image/png");
      const pdf = new jsPDF({ orientation: "portrait", unit: "px", format: [canvas.width / 2, canvas.height / 2] });
      pdf.addImage(imgData, "PNG", 0, 0, canvas.width / 2, canvas.height / 2);
      pdf.save(`${quoteNumber || "CSL-Quote"}.pdf`);
    } catch (err) {
      console.error("PDF export failed:", err);
    }
  };

  // ── Copy to clipboard as image ──
  const handleCopyToClipboard = async () => {
    try {
      const card = document.getElementById("quote-preview-card");
      if (!card) throw new Error("Preview card not found");
      const html2canvas = (await import("html2canvas")).default;

      // Pre-render SVG logo to high-res PNG data URL for html2canvas compatibility
      const logoDataUrl = await new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
          const c = document.createElement("canvas");
          c.width = 128; c.height = 128;
          const cx = c.getContext("2d");
          cx.drawImage(img, 0, 0, 128, 128);
          resolve(c.toDataURL("image/png"));
        };
        img.onerror = () => resolve(null);
        img.src = "/logo.svg";
      });

      // Clone card off-screen at wider width so text doesn't wrap
      const clone = card.cloneNode(true);
      clone.style.position = "absolute";
      clone.style.left = "-9999px";
      clone.style.top = "0";
      clone.style.maxWidth = "650px";
      clone.style.width = "650px";
      // Swap logo to high-res PNG in clone
      const logoImg = clone.querySelector("img");
      if (logoImg && logoDataUrl) logoImg.src = logoDataUrl;
      document.body.appendChild(clone);

      const hiRes = await html2canvas(clone, {
        backgroundColor: "#0f1215",
        scale: 2,
        useCORS: true,
        logging: false,
        width: clone.scrollWidth,
        height: clone.scrollHeight,
        windowWidth: clone.scrollWidth,
        windowHeight: clone.scrollHeight,
      });
      document.body.removeChild(clone);

      // Downscale to 576px wide (≈6" at 96dpi in Outlook — fits email body)
      const targetW = 576;
      const ratio = hiRes.height / hiRes.width;
      const targetH = Math.round(targetW * ratio);
      const canvas = document.createElement("canvas");
      canvas.width = targetW;
      canvas.height = targetH;
      const ctx = canvas.getContext("2d");
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(hiRes, 0, 0, targetW, targetH);

      const blob = await new Promise(r => canvas.toBlob(r, "image/png"));
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setSaveMsg({ type: "success", text: "Quote copied — paste into Outlook!" });
    } catch (err) {
      console.error("Copy to clipboard failed:", err);
      setSaveMsg({ type: "error", text: "Copy failed — try PDF instead" });
    }
  };

  // ── Clear form ──
  const handleClear = () => {
    setRoute({ pod: "", finalDelivery: "", finalZip: "", roundTripMiles: "", oneWayMiles: "", transitTime: "", shipmentType: "Dray" });
    setLinehaul([{ description: "", rate: "", section: "Charges" }]);
    setMarginPct(15);
    setMarginType("pct");
    setAccessorials(JSON.parse(JSON.stringify(DEFAULT_ACCESSORIALS)));
    setTerms([...DEFAULT_TERMS]);
    setCustomerName("");
    setCustomerEmail("");
    setCarrierName("");
    setEditingId(null);
    setQuoteNumber("");
    setSaveMsg(null);
  };

  // ── Shared input styles ──
  const inputStyle = { width: "100%", padding: "8px 10px", background: "#0D1119", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#F0F2F5", fontSize: 12.5, outline: "none" };
  const labelStyle = { fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 };
  const sectionTitle = { fontSize: 11, fontWeight: 800, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10, marginTop: 20 };

  return (
    <div style={{ display: "flex", gap: 40, height: "100%", minHeight: 0, overflow: "hidden", maxWidth: 1100, margin: "0 auto" }}>

      {/* ═══ LEFT: Builder Panel ═══ */}
      <div style={{ width: 480, flexShrink: 0, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

        {/* Tab row */}
        <div style={{ display: "flex", gap: 2, marginBottom: 16, background: "#0D1119", borderRadius: 8, padding: 3 }}>
          {["builder", "history"].map(t => (
            <button key={t} onClick={() => setTab(t)}
              style={{ flex: 1, padding: "8px 0", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: "pointer", transition: "all 0.15s",
                background: tab === t ? "#1A2236" : "transparent", color: tab === t ? "#F0F2F5" : "#5A6478" }}>
              {t === "builder" ? "Quote Builder" : "History"}
            </button>
          ))}
        </div>

        {/* Tab content (scrollable) */}
        <div style={{ flex: 1, overflowY: "auto", paddingRight: 8 }}>

          {tab === "history" ? (
            <HistoryTab onLoadQuote={handleLoadQuote} />
          ) : (<>

            {/* ── Drop Zone ── */}
            <div onDrop={handleDrop} onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
              style={{ border: "2px dashed rgba(255,255,255,0.1)", borderRadius: 10, padding: "20px 20px 14px", textAlign: "center", transition: "border-color 0.2s", marginBottom: 16, background: "rgba(0,212,170,0.02)" }}
              onDragEnter={e => e.currentTarget.style.borderColor = "rgba(0,212,170,0.4)"}
              onDragLeave={e => e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)"}>
              <input ref={fileInputRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.msg,.eml"
                style={{ display: "none" }} onChange={e => handleExtract(e.target.files?.[0])} />
              {extracting ? (
                <div style={{ color: "#00D4AA", fontSize: 13, fontWeight: 600, padding: "12px 0" }}>Extracting rates with AI...</div>
              ) : (
                <>
                  <div style={{ fontSize: 22, marginBottom: 4 }}>&#128206;</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#8B95A8" }}>Drop carrier quote here</div>
                  <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 10 }}>
                    <button onClick={async () => {
                      try {
                        const items = await navigator.clipboard.read();
                        for (const item of items) {
                          const imgType = item.types.find(t => t.startsWith("image/"));
                          if (imgType) {
                            const blob = await item.getType(imgType);
                            const file = new File([blob], "clipboard.png", { type: imgType });
                            handleExtract(file);
                            return;
                          }
                        }
                        const text = await navigator.clipboard.readText();
                        if (text && text.trim().length >= 20) { handleExtractText(text); return; }
                        setSaveMsg({ type: "error", text: "No image or text found in clipboard" });
                      } catch { setSaveMsg({ type: "error", text: "Clipboard access denied — use Ctrl+V instead" }); }
                    }}
                      style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>
                      Paste from Clipboard
                    </button>
                    <button onClick={() => fileInputRef.current?.click()}
                      style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                      Browse Files
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* ── Save message ── */}
            {saveMsg && (
              <div style={{ padding: "8px 12px", borderRadius: 6, marginBottom: 12, fontSize: 12, fontWeight: 600,
                background: saveMsg.type === "success" ? "rgba(0,212,170,0.1)" : "rgba(239,68,68,0.1)",
                color: saveMsg.type === "success" ? "#00D4AA" : "#EF4444" }}>
                {saveMsg.text}
              </div>
            )}

            {/* ── Customer Info ── */}
            <div style={sectionTitle}>Customer</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 4 }}>
              <div>
                <div style={labelStyle}>Name</div>
                <input value={customerName} onChange={e => setCustomerName(e.target.value)} placeholder="Company name" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>Email</div>
                <input value={customerEmail} onChange={e => setCustomerEmail(e.target.value)} placeholder="email@co.com" style={inputStyle} />
              </div>
            </div>

            {/* ── Carrier (internal) ── */}
            <div style={{ marginTop: 8 }}>
              <div style={labelStyle}>Carrier (internal only)</div>
              <input value={carrierName} onChange={e => setCarrierName(e.target.value)} placeholder="Carrier name" style={inputStyle} />
            </div>

            {/* ── Route ── */}
            <div style={sectionTitle}>Route {fetchingMiles && <span style={{ fontSize: 10, color: "#00D4AA", fontWeight: 500, marginLeft: 8 }}>calculating miles...</span>}</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <div style={labelStyle}>Port / Origin</div>
                <input value={route.pod} onChange={e => updateRoute("pod", e.target.value)} placeholder="NY/NJ Ports" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>Delivery</div>
                <input value={route.finalDelivery} onChange={e => updateRoute("finalDelivery", e.target.value)} placeholder="Dallas, TX 76470" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>R/T Miles</div>
                <input value={route.roundTripMiles} onChange={e => updateRoute("roundTripMiles", e.target.value)} placeholder="auto" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>One-Way Miles</div>
                <input value={route.oneWayMiles} onChange={e => updateRoute("oneWayMiles", e.target.value)} placeholder="auto" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>Transit Time</div>
                <input value={route.transitTime} onChange={e => updateRoute("transitTime", e.target.value)} placeholder="3 days" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>Type</div>
                <select value={route.shipmentType} onChange={e => updateRoute("shipmentType", e.target.value)}
                  style={{ ...inputStyle, cursor: "pointer" }}>
                  {["Dray", "FTL", "OTR", "Transload", "Dray+Transload", "LTL"].map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>

            {/* ── Linehaul ── */}
            <div style={{ ...sectionTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Linehaul</span>
              <button onClick={addLH} style={{ background: "none", border: "none", color: "#00D4AA", fontSize: 18, cursor: "pointer", lineHeight: 1, padding: "0 4px" }}>+</button>
            </div>
            {linehaul.map((row, i) => (
              <div key={i} style={{ display: "flex", gap: 6, marginBottom: 8, alignItems: "center" }}>
                <select value={row.section || "Charges"} onChange={e => updateLH(i, "section", e.target.value)}
                  style={{ ...inputStyle, width: 110, flex: "none", fontSize: 10.5, cursor: "pointer", padding: "8px 4px", color: "#00D4AA" }}>
                  {SECTION_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <input value={row.description} onChange={e => updateLH(i, "description", e.target.value)} placeholder="Description"
                  style={{ ...inputStyle, flex: 2 }} />
                <div style={{ position: "relative", flex: 1 }}>
                  <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#5A6478", fontSize: 12.5 }}>$</span>
                  <input value={row.rate} onChange={e => updateLH(i, "rate", e.target.value)} placeholder="0.00"
                    style={{ ...inputStyle, paddingLeft: 22 }} />
                </div>
                {linehaul.length > 1 && (
                  <button onClick={() => removeLH(i)} style={{ background: "none", border: "none", color: "#EF4444", fontSize: 16, cursor: "pointer", padding: "0 4px", flexShrink: 0 }}>x</button>
                )}
              </div>
            ))}

            {/* ── Margin ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, marginBottom: 4, flexWrap: "wrap" }}>
              <select value={marginType} onChange={e => { setMarginType(e.target.value); setMarginPct(e.target.value === "flat" ? "" : "15"); }}
                style={{ ...inputStyle, width: 90, fontSize: 11, cursor: "pointer", padding: "8px 4px" }}>
                <option value="pct">% Markup</option>
                <option value="flat">$ Flat</option>
              </select>
              <input value={marginPct} onChange={e => setMarginPct(e.target.value)} type="number" min="0" step={marginType === "flat" ? "25" : "0.5"}
                placeholder={marginType === "flat" ? "0.00" : "15"}
                style={{ ...inputStyle, width: 80, textAlign: "center" }} />
              <div style={{ fontSize: 12, color: "#5A6478", whiteSpace: "nowrap" }}>
                Carrier: {fmt(carrierSubtotal)} → Sell: <span style={{ color: "#00D4AA", fontWeight: 700 }}>{fmt(sellSubtotal)}</span>
              </div>
            </div>

            {/* ── Accessorials ── */}
            <div style={{ ...sectionTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Accessorials</span>
              <button onClick={addAcc} style={{ background: "none", border: "none", color: "#00D4AA", fontSize: 18, cursor: "pointer", lineHeight: 1, padding: "0 4px" }}>+</button>
            </div>
            {accessorials.map((acc, i) => (
              <div key={i} draggable onDragStart={() => handleAccDragStart(i)} onDragOver={(e) => handleAccDragOver(e, i)} onDrop={handleAccDrop}
                style={{ display: "flex", gap: 6, marginBottom: 8, alignItems: "center", transition: "opacity 0.15s" }}
                onDragEnter={e => e.currentTarget.style.opacity = "0.5"} onDragLeave={e => e.currentTarget.style.opacity = "1"} onDragEnd={e => e.currentTarget.style.opacity = "1"}>
                <span style={{ cursor: "grab", color: "#3D4557", fontSize: 14, flexShrink: 0, userSelect: "none" }} title="Drag to reorder">⠿</span>
                <input type="checkbox" checked={acc.checked} onChange={() => toggleAcc(i)}
                  style={{ accentColor: "#00D4AA", cursor: "pointer", flexShrink: 0 }} />
                <input value={acc.charge} onChange={e => updateAcc(i, "charge", e.target.value)} placeholder="Charge"
                  style={{ ...inputStyle, flex: 3, fontSize: 11.5, minWidth: 0 }} />
                <select value={acc.frequency} onChange={e => updateAcc(i, "frequency", e.target.value)}
                  style={{ ...inputStyle, flex: 1.2, fontSize: 11, cursor: "pointer", padding: "8px 4px" }}>
                  {["flat", "per day", "per hour", "per mile"].map(f => <option key={f} value={f}>{f}</option>)}
                </select>
                <div style={{ position: "relative", flex: 1.2 }}>
                  <span style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "#5A6478", fontSize: 11.5 }}>$</span>
                  <input value={acc.amount} onChange={e => updateAcc(i, "amount", e.target.value)} placeholder="0.00"
                    style={{ ...inputStyle, paddingLeft: 20, fontSize: 11.5 }} />
                </div>
                <button onClick={() => removeAcc(i)} style={{ background: "none", border: "none", color: "#EF4444", fontSize: 14, cursor: "pointer", padding: "0 2px", flexShrink: 0 }}>x</button>
              </div>
            ))}

            {/* ── Total bar ── */}
            <div style={{ background: "linear-gradient(135deg, rgba(0,200,83,0.15), rgba(0,184,212,0.1))", borderRadius: 10, padding: "16px 20px", marginTop: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em" }}>Estimated Total</div>
              <div style={{ fontSize: 22, fontWeight: 800, backgroundImage: grad, backgroundClip: "text", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                {fmt(estimatedTotal)}
              </div>
            </div>

            {/* ── Action buttons ── */}
            <div style={{ display: "flex", gap: 8, marginTop: 16, marginBottom: 24 }}>
              <button onClick={() => handleSave("draft")} disabled={saving}
                style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "none", fontWeight: 700, fontSize: 12.5, cursor: "pointer",
                  background: "linear-gradient(135deg, #00c853, #00b8d4)", color: "#fff", opacity: saving ? 0.6 : 1 }}>
                {saving ? "Saving..." : editingId ? "Update Quote" : "Save Draft"}
              </button>
              <button onClick={handleCopyToClipboard}
                style={{ padding: "10px 16px", borderRadius: 8, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>
                Copy
              </button>
              <button onClick={handleExportPDF}
                style={{ padding: "10px 16px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "#141A28", color: "#8B95A8", fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>
                PDF
              </button>
              <button onClick={handleClear}
                style={{ padding: "10px 16px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "#141A28", color: "#5A6478", fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>
                Clear
              </button>
            </div>

          </>)}
        </div>
      </div>

      {/* ═══ RIGHT: Live Preview ═══ */}
      <div style={{ width: 560, flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center", overflowY: "auto", padding: "0 20px", position: "relative" }}>
        <img src="/rateiq-bot.png" alt="" style={{ width: "100%", maxWidth: 520, pointerEvents: "none", userSelect: "none", borderRadius: 12, marginBottom: 20 }} />
        <div style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 16, textAlign: "center" }}>
          Customer Preview {quoteNumber && `— ${quoteNumber}`}
        </div>
        <QuotePreview
          route={route}
          linehaul={linehaul}
          accessorials={accessorials}
          marginPct={marginPct}
          marginType={marginType}
          terms={terms}
          quoteNumber={quoteNumber}
          shipmentType={route.shipmentType}
        />
      </div>
    </div>
  );
}
