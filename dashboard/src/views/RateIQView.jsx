import { useState, useEffect, useCallback, useMemo } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';
import QuoteBuilder from '../QuoteBuilder';
import OOGQuoteBuilder from '../OOGQuoteBuilder';

// ═══════════════════════════════════════════════════════════════
// HISTORY TAB CONTENT (local to RateIQView)
// ═══════════════════════════════════════════════════════════════
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

  // Group by port_group
  const grouped = {};
  rateHistory.forEach(r => {
    const key = r.port_group || r.origin || "Unknown";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(r);
  });

  return (
    <div>
      <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 12 }}>
        {rateHistory.length} applied rates across {Object.keys(grouped).length} markets
      </div>
      {Object.entries(grouped).sort((a, b) => b[1].length - a[1].length).map(([group, rates]) => (
        <div key={group} className="glass" style={{ borderRadius: 10, marginBottom: 8, overflow: "hidden", border: "1px solid rgba(255,255,255,0.04)" }}>
          <div style={{ padding: "10px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>{group}</span>
            <span style={{ fontSize: 10, color: "#5A6478", fontWeight: 600 }}>{rates.length} rate{rates.length !== 1 ? "s" : ""}</span>
            <span style={{ fontSize: 10, color: "#00D4AA", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
              ${Math.round(rates.reduce((s, r) => s + (r.rate || 0), 0) / rates.filter(r => r.rate).length).toLocaleString()} avg
            </span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
            <thead>
              <tr style={{ background: "rgba(255,255,255,0.02)" }}>
                {["EFJ", "Lane", "Carrier", "Rate", "Account", "Rep", "Applied"].map(h => (
                  <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", fontSize: 8 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rates.map(r => (
                <tr key={r.id} style={{ borderTop: "1px solid rgba(255,255,255,0.03)" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <td style={{ padding: "6px 10px", fontFamily: "'JetBrains Mono', monospace", color: "#3B82F6", fontWeight: 600, cursor: "pointer" }}>{r.efj}</td>
                  <td style={{ padding: "6px 10px", color: "#C8D0DC" }}>{r.origin || "?"} {"\u2192"} {r.destination || "?"}</td>
                  <td style={{ padding: "6px 10px", color: "#F0F2F5", fontWeight: 600 }}>{r.carrier || "\u2014"}</td>
                  <td style={{ padding: "6px 10px", fontFamily: "'JetBrains Mono', monospace", color: "#00D4AA", fontWeight: 700 }}>
                    {r.rate ? `$${r.rate.toLocaleString()}` : "\u2014"}
                  </td>
                  <td style={{ padding: "6px 10px", color: "#8B95A8" }}>{r.account || "\u2014"}</td>
                  <td style={{ padding: "6px 10px", color: "#8B95A8" }}>{r.rep || "\u2014"}</td>
                  <td style={{ padding: "6px 10px", color: "#5A6478", fontSize: 9 }}>
                    {r.applied_at ? new Date(r.applied_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// RATE IQ VIEW
// ═══════════════════════════════════════════════════════════════
export default function RateIQView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedCarrier, setExpandedCarrier] = useState(null);
  const [tab, setTab] = useState("dray"); // dray | ftl | oog | scorecard | lanes | directory | history
  const [replyAlerts, setReplyAlerts] = useState([]);
  const [scorecardPerf, setScorecardPerf] = useState([]);
  const [laneStats, setLaneStats] = useState([]);
  // Directory state
  const [dirCarriers, setDirCarriers] = useState([]);
  const [dirSearch, setDirSearch] = useState("");
  const [dirMarket, setDirMarket] = useState("all");
  const [dirCaps, setDirCaps] = useState([]);
  const [dirHideDnu, setDirHideDnu] = useState(true);
  const [dirPort, setDirPort] = useState("all");
  const [dirExpanded, setDirExpanded] = useState(null);
  const [editingCarrierId, setEditingCarrierId] = useState(null);
  // Lane Search state
  const [laneOrigin, setLaneOrigin] = useState("");
  const [laneDest, setLaneDest] = useState("");
  const [laneResults, setLaneResults] = useState([]);
  const [laneSearching, setLaneSearching] = useState(false);
  const [laneExpanded, setLaneExpanded] = useState(null);
  const [editingLaneRateId, setEditingLaneRateId] = useState(null);
  const [editingLaneField, setEditingLaneField] = useState(null);
  const [editingLaneValue, setEditingLaneValue] = useState("");
  // Port groups + History state
  const [portGroups, setPortGroups] = useState([]);
  const [rateHistory, setRateHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ── Carrier update handler (Directory) ──
  const handleCarrierUpdate = async (carrierId, field, value) => {
    setDirCarriers(prev => prev.map(c => c.id === carrierId ? { ...c, [field]: value } : c));
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers/${carrierId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) {
      console.error("Carrier update failed:", e);
    }
  };

  // ── Lane rate update handler ──
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
    } catch (e) {
      console.error("Lane rate update failed:", e);
    }
    setEditingLaneRateId(null);
    setEditingLaneField(null);
  };

  const fetchData = useCallback(async () => {
    try {
      const [rateRes, alertRes, perfRes, laneRes, carrierRes, pgRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/rate-iq`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/customer-reply-alerts`).then(r => r.json()).catch(() => []),
        apiFetch(`${API_BASE}/api/carriers/scorecard`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/lane-stats`).then(r => r.json()).catch(() => ({ lanes: [] })),
        apiFetch(`${API_BASE}/api/carriers?include_lanes=true`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/port-groups`).then(r => r.json()).catch(() => ({ groups: [] })),
      ]);
      setData(rateRes);
      setReplyAlerts(alertRes);
      setScorecardPerf(perfRes.carriers || []);
      setLaneStats(laneRes.lanes || []);
      setDirCarriers(carrierRes.carriers || carrierRes || []);
      setPortGroups(pgRes.groups || []);
    } catch (e) { console.error("Rate IQ fetch:", e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); const iv = setInterval(fetchData, 60000); return () => clearInterval(iv); }, [fetchData]);

  const handleQuoteAction = async (quoteId, status) => {
    try {
      await apiFetch(`${API_BASE}/api/rate-iq/${quoteId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      fetchData();
    } catch (e) { console.error("Quote action failed:", e); }
  };

  const dismissReplyAlert = async (alertId) => {
    try {
      await apiFetch(`${API_BASE}/api/customer-reply-alerts/${alertId}/dismiss`, { method: "POST" });
      setReplyAlerts(prev => prev.filter(a => a.id !== alertId));
    } catch {}
  };

  // Lane Search handler
  const searchLanes = useCallback(async () => {
    if (!laneOrigin && !laneDest) return;
    setLaneSearching(true);
    try {
      const params = new URLSearchParams();
      if (laneOrigin) params.set("port", laneOrigin);
      if (laneDest) params.set("destination", laneDest);
      const res = await apiFetch(`${API_BASE}/api/lane-rates?${params.toString()}`).then(r => r.json());
      const data = res.lane_rates || (Array.isArray(res) ? res : []);
      setLaneResults(data);
    } catch (e) { console.error("Lane search:", e); setLaneResults([]); }
    setLaneSearching(false);
  }, [laneOrigin, laneDest]);

  // Directory filtering
  const CAP_OPTIONS = [
    { key: "can_hazmat", label: "HAZ", color: "#f87171" },
    { key: "can_overweight", label: "OWT", color: "#FBBF24" },
    { key: "can_reefer", label: "Reefer", color: "#60a5fa" },
    { key: "can_bonded", label: "Bonded", color: "#a78bfa" },
    { key: "can_oog", label: "OOG", color: "#fb923c" },
    { key: "can_warehousing", label: "WHS", color: "#34d399" },
    { key: "can_transload", label: "Transload", color: "#38bdf8" },
  ];
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

  // Build carrier capability lookup from directory data
  const carrierCapMap = useMemo(() => {
    const m = {};
    dirCarriers.forEach(c => {
      m[(c.carrier_name || "").toLowerCase()] = {
        can_hazmat: c.can_hazmat, can_overweight: c.can_overweight, can_reefer: c.can_reefer,
        can_bonded: c.can_bonded, can_oog: c.can_oog, can_warehousing: c.can_warehousing,
        can_transload: c.can_transload, tier_rank: c.tier_rank, dnu: c.dnu, mc_number: c.mc_number,
      };
    });
    return m;
  }, [dirCarriers]);

  // Group lane results by destination
  const groupedLanes = useMemo(() => {
    const map = {};
    (Array.isArray(laneResults) ? laneResults : []).forEach(r => {
      const key = `${r.port || ""} \u2192 ${r.destination || ""}`;
      if (!map[key]) map[key] = { port: r.port, destination: r.destination, carriers: [], minRate: Infinity, maxRate: 0, total: 0, count: 0 };
      map[key].carriers.push(r);
      const rate = parseFloat(r.total || r.dray_rate || 0);
      if (rate > 0) { map[key].minRate = Math.min(map[key].minRate, rate); map[key].maxRate = Math.max(map[key].maxRate, rate); map[key].total += rate; map[key].count++; }
    });
    return Object.values(map).sort((a, b) => b.count - a.count);
  }, [laneResults]);

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#8B95A8" }}>Loading Rate IQ...</div>;

  const lanes = data?.lanes || [];
  const scorecard = data?.scorecard || [];

  return (
    <div style={{ padding: "0 24px 24px", maxWidth: (tab === "dray" || tab === "oog" || tab === "directory" || tab === "lanes" || tab === "history") ? "none" : 1200 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate IQ</h2>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
            {data?.total_rate_quotes || 0} parsed quotes | {data?.total_carrier_quotes || 0} carrier emails | {data?.total_customer_requests || 0} customer requests
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {[
          { key: "dray", label: "Dray IQ" },
          { key: "ftl", label: "FTL IQ" },
          { key: "oog", label: "OOG IQ" },
          { key: "scorecard", label: `Scorecard (${scorecardPerf.length})` },
          { key: "directory", label: `Directory (${dirCarriers.length})` },
          { key: "lanes", label: `Lane Search` },
          { key: "history", label: `History (${rateHistory.length})` },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{ padding: "6px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid " + (tab === t.key ? "rgba(0,212,170,0.4)" : "rgba(255,255,255,0.06)"), background: tab === t.key ? "rgba(0,212,170,0.08)" : "transparent", color: tab === t.key ? "#00D4AA" : "#8B95A8", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s ease" }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Dray IQ Tab (was Quote Builder) */}
      {tab === "dray" && (
        <div style={{ height: "calc(100vh - 180px)" }}>
          <QuoteBuilder />
        </div>
      )}

      {/* FTL IQ Tab */}
      {tab === "ftl" && (
        <div style={{ textAlign: "center", padding: 60, color: "#5A6478" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>{"\uD83D\uDE9B"}</div>
          <h2 style={{ color: "#F0F2F5", fontWeight: 800, fontSize: 20, margin: "0 0 8px" }}>FTL IQ</h2>
          <div style={{ fontSize: 13 }}>Full Truckload quote builder {"\u2014"} coming soon</div>
        </div>
      )}

      {/* OOG IQ Tab */}
      {tab === "oog" && (
        <OOGQuoteBuilder />
      )}

      {/* Scorecard Tab — Carrier Performance from completed loads */}
      {tab === "scorecard" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {scorecardPerf.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>
              No carrier performance data yet {"\u2014"} data populates from completed loads.
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
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.carrier}
                    </div>
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 1 }}>
                      {c.primary_move_type || "\u2014"}{c.last_delivery ? ` \u00B7 Last: ${c.last_delivery}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center", flexShrink: 0 }}>
                    <div style={{ textAlign: "center", minWidth: 44 }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.total_loads}</div>
                      <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600, letterSpacing: "0.5px" }}>LOADS</div>
                    </div>
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 10, fontWeight: 700, background: otBg, color: otColor, border: `1px solid ${otColor}30` }}>
                      {c.on_time_pct}% OT
                    </span>
                    {c.avg_transit_days != null && (
                      <div style={{ textAlign: "center", minWidth: 44 }}>
                        <div style={{ fontSize: 14, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.avg_transit_days}</div>
                        <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600 }}>AVG DAYS</div>
                      </div>
                    )}
                    <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60a5fa", fontSize: 9, fontWeight: 700 }}>
                      {c.lanes_served} lane{c.lanes_served !== 1 ? "s" : ""}
                    </span>
                    <span style={{ color: "#5A6478", fontSize: 14, transition: "transform 0.2s", transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}>&#9660;</span>
                  </div>
                </div>
                {isExpanded && c.top_lanes?.length > 0 && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "10px 16px 14px" }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Top Lanes</div>
                    {c.top_lanes.map((tl, li) => (
                      <div key={li} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(255,255,255,0.02)", marginBottom: 3 }}>
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
      )}

      {/* Carrier Directory Tab */}
      {tab === "directory" && (
        <div>
          {/* Search + Filters */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
            <input value={dirSearch} onChange={e => setDirSearch(e.target.value)} placeholder="Search carrier, MC#, email..." style={{ flex: "1 1 200px", minWidth: 200, padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
            <select value={dirMarket} onChange={e => setDirMarket(e.target.value)} style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#151926", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
              <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Markets</option>
              {allMarkets.map(m => <option key={m} value={m} style={{ background: "#151926", color: "#F0F2F5" }}>{m}</option>)}
            </select>
            <select value={dirPort} onChange={e => setDirPort(e.target.value)} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${dirPort !== "all" ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: dirPort !== "all" ? "rgba(0,212,170,0.06)" : "#151926", color: dirPort !== "all" ? "#00D4AA" : "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
              <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Ports/Rails</option>
              {portGroups.filter(g => !g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
              <option disabled style={{ background: "#151926", color: "#5A6478" }}>{"\u2500\u2500 Rail \u2500\u2500"}</option>
              {portGroups.filter(g => g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
            </select>
            {CAP_OPTIONS.map(cap => {
              const active = dirCaps.includes(cap.key);
              return <button key={cap.key} onClick={() => setDirCaps(prev => active ? prev.filter(c => c !== cap.key) : [...prev, cap.key])}
                style={{ padding: "5px 12px", borderRadius: 6, fontSize: 10, fontWeight: 700, cursor: "pointer", border: `1px solid ${active ? cap.color + "60" : "rgba(255,255,255,0.06)"}`, background: active ? cap.color + "18" : "transparent", color: active ? cap.color : "#8B95A8", fontFamily: "inherit", transition: "all 0.15s" }}>
                {cap.label}
              </button>;
            })}
            <button onClick={() => setDirHideDnu(!dirHideDnu)} style={{ padding: "5px 12px", borderRadius: 6, fontSize: 10, fontWeight: 700, cursor: "pointer", border: `1px solid ${dirHideDnu ? "rgba(255,255,255,0.06)" : "rgba(239,68,68,0.4)"}`, background: dirHideDnu ? "transparent" : "rgba(239,68,68,0.1)", color: dirHideDnu ? "#8B95A8" : "#f87171", fontFamily: "inherit" }}>
              {dirHideDnu ? "Show DNU" : "Hide DNU"}
            </button>
          </div>
          <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 12 }}>{filteredDir.length} carriers {"\u00B7"} {allMarkets.length} markets</div>

          {/* Carrier Cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {filteredDir.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>No carriers match your filters.</div>}
            {filteredDir.slice(0, 100).map((c, i) => {
              const isExp = dirExpanded === (c.id || i);
              const tierColors = { 1: { bg: "rgba(34,197,94,0.12)", color: "#34d399", label: "Tier 1" }, 2: { bg: "rgba(245,158,11,0.12)", color: "#FBBF24", label: "Tier 2" }, 3: { bg: "rgba(251,146,60,0.12)", color: "#fb923c", label: "Tier 3" }, 0: { bg: "rgba(239,68,68,0.12)", color: "#f87171", label: "DNU" } };
              const tier = tierColors[c.tier_rank] || { bg: "rgba(107,114,128,0.08)", color: "#6B7280", label: "Unranked" };
              return (
                <div key={c.id || i} className="glass" style={{ borderRadius: 10, overflow: "hidden", border: isExp ? "1px solid rgba(0,212,170,0.2)" : c.dnu ? "1px solid rgba(239,68,68,0.15)" : "1px solid rgba(255,255,255,0.04)" }}>
                  <div onClick={() => setDirExpanded(isExp ? null : (c.id || i))} style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12, transition: "background 0.15s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                    {/* Name + MC */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: c.dnu ? "#f87171" : "#F0F2F5", textDecoration: c.dnu ? "line-through" : "none" }}>{c.carrier_name}</span>
                        {c.mc_number && <span style={{ fontSize: 9, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{c.mc_number}</span>}
                      </div>
                      {/* Capability pills */}
                      <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
                        {editingCarrierId === c.id ? (
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
                    {/* Edit toggle */}
                    <button onClick={e => { e.stopPropagation(); setEditingCarrierId(editingCarrierId === c.id ? null : c.id); if (!isExp) setDirExpanded(c.id || i); }}
                      title="Edit carrier" style={{ padding: "3px 8px", borderRadius: 6, border: editingCarrierId === c.id ? "1px solid rgba(0,212,170,0.4)" : "1px solid rgba(255,255,255,0.06)", background: editingCarrierId === c.id ? "rgba(0,212,170,0.1)" : "transparent", color: editingCarrierId === c.id ? "#00D4AA" : "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit", flexShrink: 0, transition: "all 0.15s" }}>
                      {editingCarrierId === c.id ? "Done" : "\u270F\uFE0F"}
                    </button>
                    {/* Tier badge */}
                    {editingCarrierId === c.id ? (
                      <select value={c.tier_rank ?? ""} onClick={e => e.stopPropagation()}
                        onChange={e => { const v = e.target.value === "" ? null : parseInt(e.target.value); handleCarrierUpdate(c.id, "tier_rank", v); if (v === 0) handleCarrierUpdate(c.id, "dnu", true); else if (c.dnu) handleCarrierUpdate(c.id, "dnu", false); }}
                        style={{ padding: "3px 8px", borderRadius: 6, fontSize: 9, fontWeight: 700, background: "#151926", color: tier.color, border: `1px solid ${tier.color}30`, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 }}>
                        <option value="" style={{ background: "#151926", color: "#6B7280" }}>Unranked</option>
                        <option value="1" style={{ background: "#151926", color: "#34d399" }}>Tier 1</option>
                        <option value="2" style={{ background: "#151926", color: "#FBBF24" }}>Tier 2</option>
                        <option value="3" style={{ background: "#151926", color: "#fb923c" }}>Tier 3</option>
                        <option value="0" style={{ background: "#151926", color: "#f87171" }}>DNU</option>
                      </select>
                    ) : (
                      <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 9, fontWeight: 700, background: tier.bg, color: tier.color, border: `1px solid ${tier.color}30`, flexShrink: 0 }}>{tier.label}</span>
                    )}
                    {/* Markets */}
                    <div style={{ display: "flex", gap: 3, flexShrink: 0, flexWrap: "wrap", maxWidth: 200 }}>
                      {(c.markets || []).slice(0, 4).map(m => (
                        <span key={m} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 600, background: "rgba(59,130,246,0.1)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.2)" }}>{m}</span>
                      ))}
                      {(c.markets || []).length > 4 && <span style={{ fontSize: 8, color: "#5A6478" }}>+{c.markets.length - 4}</span>}
                    </div>
                    {c.trucks && <div style={{ textAlign: "center", minWidth: 36, flexShrink: 0 }}><div style={{ fontSize: 13, fontWeight: 800, color: "#F0F2F5" }}>{c.trucks}</div><div style={{ fontSize: 7, color: "#5A6478", fontWeight: 600 }}>TRUCKS</div></div>}
                    <span style={{ color: "#5A6478", fontSize: 12, transition: "transform 0.2s", transform: isExp ? "rotate(180deg)" : "rotate(0)", flexShrink: 0 }}>{"\u25BC"}</span>
                  </div>
                  {/* Expanded detail */}
                  {isExp && (() => {
                    const isEdit = editingCarrierId === c.id;
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
                              {val}{opts.copyable ? " \uD83D\uDCCB" : ""}
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
                      </div>
                    );
                  })()}
                </div>
              );
            })}
            {filteredDir.length > 100 && <div style={{ padding: 12, textAlign: "center", color: "#5A6478", fontSize: 11 }}>Showing 100 of {filteredDir.length} carriers. Refine your search.</div>}
          </div>
        </div>
      )}

      {/* Lane Search Tab */}
      {tab === "lanes" && (
        <div>
          {/* Search inputs */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 9, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Origin / Port</label>
              <input value={laneOrigin} onChange={e => setLaneOrigin(e.target.value)} placeholder="e.g. Houston, NYNJ, Savannah..." style={{ width: "100%", padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onKeyDown={e => e.key === "Enter" && searchLanes()} />
            </div>
            <div style={{ fontSize: 14, color: "#5A6478", padding: "0 4px 8px" }}>{"\u2192"}</div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 9, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Destination</label>
              <input value={laneDest} onChange={e => setLaneDest(e.target.value)} placeholder="e.g. Dallas, Chicago..." style={{ width: "100%", padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onKeyDown={e => e.key === "Enter" && searchLanes()} />
            </div>
            <button onClick={searchLanes} disabled={laneSearching} style={{ padding: "8px 20px", borderRadius: 8, border: "none", background: "linear-gradient(135deg, #00D4AA, #00B894)", color: "#0A0F1C", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", opacity: laneSearching ? 0.6 : 1, whiteSpace: "nowrap" }}>
              {laneSearching ? "Searching..." : "Search Lanes"}
            </button>
          </div>

          {/* Port Group Quick Filters */}
          {portGroups.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 12 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", alignSelf: "center", marginRight: 4 }}>Ports:</span>
              {portGroups.filter(g => !g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setLaneOrigin(g.name); setLaneDest(""); setTimeout(searchLanes, 100); }}
                  style={{ padding: "3px 10px", borderRadius: 6, border: "1px solid rgba(0,212,170,0.15)", background: laneOrigin === g.name ? "rgba(0,212,170,0.10)" : "rgba(255,255,255,0.02)", color: laneOrigin === g.name ? "#00D4AA" : "#8B95A8", fontSize: 9, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
              <span style={{ fontSize: 9, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", alignSelf: "center", marginLeft: 8, marginRight: 4 }}>Rail:</span>
              {portGroups.filter(g => g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setLaneOrigin(g.name); setLaneDest(""); setTimeout(searchLanes, 100); }}
                  style={{ padding: "3px 10px", borderRadius: 6, border: "1px solid rgba(167,139,250,0.15)", background: laneOrigin === g.name ? "rgba(167,139,250,0.10)" : "rgba(255,255,255,0.02)", color: laneOrigin === g.name ? "#A78BFA" : "#8B95A8", fontSize: 9, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
            </div>
          )}

          {/* Results */}
          {groupedLanes.length === 0 && !laneSearching && (
            <div style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>{"\uD83D\uDD0D"}</div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Search for a lane to see carrier rates & accessorials</div>
              <div style={{ fontSize: 11, marginTop: 4 }}>Enter an origin or destination above, then hit Enter or click Search</div>
              {laneStats.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "1px", marginBottom: 8 }}>Popular Lanes</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
                    {laneStats.slice(0, 8).map((ls, li) => (
                      <button key={li} onClick={() => { setLaneOrigin(ls.origin_city || ""); setLaneDest(ls.dest_city || ""); setTimeout(searchLanes, 100); }}
                        style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.02)", color: "#C8D0DC", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                        {ls.origin_city} {"\u2192"} {ls.dest_city} ({ls.load_count})
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {groupedLanes.map((group, gi) => {
            const isExp = laneExpanded === gi;
            const avgRate = group.count > 0 ? Math.round(group.total / group.count) : 0;
            return (
              <div key={gi} className="glass" style={{ borderRadius: 10, overflow: "hidden", marginBottom: 6, border: isExp ? "1px solid rgba(0,212,170,0.2)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setLaneExpanded(isExp ? null : gi)} style={{ padding: "12px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: 16, transition: "background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#00D4AA" }}>{group.port}</span>
                    <span style={{ color: "#5A6478", margin: "0 8px" }}>{"\u2192"}</span>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5" }}>{group.destination}</span>
                  </div>
                  <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(59,130,246,0.1)", color: "#60a5fa", fontSize: 9, fontWeight: 700, border: "1px solid rgba(59,130,246,0.2)" }}>{group.carriers.length} carrier{group.carriers.length !== 1 ? "s" : ""}</span>
                  {group.count > 0 && (
                    <div style={{ textAlign: "center", minWidth: 80 }}>
                      <span style={{ fontSize: 10, color: "#5A6478" }}>${group.minRate === group.maxRate ? group.minRate.toLocaleString() : `${Math.round(group.minRate).toLocaleString()} \u2013 ${Math.round(group.maxRate).toLocaleString()}`}</span>
                    </div>
                  )}
                  {avgRate > 0 && <div style={{ textAlign: "center", minWidth: 60 }}><div style={{ fontSize: 15, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>${avgRate.toLocaleString()}</div><div style={{ fontSize: 7, color: "#5A6478", fontWeight: 600 }}>AVG</div></div>}
                  <span style={{ color: "#5A6478", fontSize: 12, transition: "transform 0.2s", transform: isExp ? "rotate(180deg)" : "rotate(0)" }}>{"\u25BC"}</span>
                </div>
                {/* Expanded: carrier rate table */}
                {isExp && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: 0, overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                          {["Carrier", "Linehaul", "FSC", "Total", "Chassis/day", "Prepull", "Storage/day", "Detention", "Split", "OW", "Tolls", "HAZ", "Triaxle", "Reefer", "Bond"].map(h => (
                            <th key={h} style={{ padding: "6px 8px", textAlign: h === "Carrier" ? "left" : "center", color: "#5A6478", fontWeight: 700, fontSize: 9, textTransform: "uppercase", letterSpacing: "0.03em", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {group.carriers.map((cr, ci) => {
                          const caps = carrierCapMap[(cr.carrier_name || "").toLowerCase()] || {};
                          const capBadges = [
                            caps.can_hazmat && { label: "\uD83D\uDD25", title: "Hazmat", color: "#f87171" },
                            caps.can_overweight && { label: "\u2696", title: "Overweight", color: "#FBBF24" },
                            caps.can_reefer && { label: "\u2744", title: "Reefer", color: "#60a5fa" },
                            caps.can_bonded && { label: "\uD83D\uDD12", title: "Bonded", color: "#a78bfa" },
                            caps.can_oog && { label: "\uD83D\uDCE6", title: "OOG", color: "#fb923c" },
                            caps.can_warehousing && { label: "\uD83C\uDFED", title: "Warehouse", color: "#34d399" },
                            caps.can_transload && { label: "\uD83D\uDD04", title: "Transload", color: "#38bdf8" },
                          ].filter(Boolean);
                          const tierColor = caps.tier_rank === 1 ? "#22c55e" : caps.tier_rank === 2 ? "#FBBF24" : caps.tier_rank === 3 ? "#fb923c" : null;
                          const daysSince = cr.created_at ? Math.floor((Date.now() - new Date(cr.created_at).getTime()) / 86400000) : null;
                          return (
                          <tr key={ci} className="lane-carrier-row" style={{ borderBottom: "1px solid rgba(255,255,255,0.03)", position: "relative" }}
                            onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; const btn = e.currentTarget.querySelector(".draft-btn"); if (btn) btn.style.opacity = "1"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; const btn = e.currentTarget.querySelector(".draft-btn"); if (btn) btn.style.opacity = "0"; }}>
                            <td style={{ padding: "8px 8px", fontWeight: 600, color: "#F0F2F5", whiteSpace: "nowrap" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                {tierColor && <span title={`Tier ${caps.tier_rank}`} style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: tierColor, flexShrink: 0 }} />}
                                <span>{cr.carrier_name}</span>
                                {caps.mc_number && <span style={{ fontSize: 8, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{caps.mc_number}</span>}
                                {capBadges.map((b, bi) => (
                                  <span key={bi} title={b.title} style={{ fontSize: 8, cursor: "default", opacity: 0.8 }}>{b.label}</span>
                                ))}
                                {daysSince !== null && <span style={{ fontSize: 8, color: daysSince > 90 ? "#f87171" : daysSince > 30 ? "#FBBF24" : "#5A6478", marginLeft: 4, fontStyle: "italic" }}>{daysSince === 0 ? "today" : daysSince < 7 ? `${daysSince}d` : daysSince < 30 ? `${Math.floor(daysSince / 7)}w` : `${Math.floor(daysSince / 30)}mo`}</span>}
                                <button className="draft-btn" onClick={(e) => { e.stopPropagation(); document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true })); }}
                                  style={{ opacity: 0, marginLeft: "auto", padding: "2px 6px", borderRadius: 4, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", fontSize: 8, fontWeight: 700, cursor: "pointer", transition: "opacity 0.15s", whiteSpace: "nowrap" }}>
                                  Draft Load {"\u2192"}
                                </button>
                              </div>
                            </td>
                            {[
                              { val: cr.dray_rate, field: "dray_rate" }, { val: cr.fsc, field: "fsc" }, { val: cr.total, field: "total" },
                              { val: cr.chassis_per_day, field: "chassis_per_day" }, { val: cr.prepull, field: "prepull" }, { val: cr.storage_per_day, field: "storage_per_day" },
                              { val: cr.detention, field: "detention" }, { val: cr.chassis_split, field: "chassis_split" }, { val: cr.overweight, field: "overweight" },
                              { val: cr.tolls, field: "tolls" }, { val: cr.hazmat, field: "hazmat" }, { val: cr.triaxle, field: "triaxle" },
                              { val: cr.reefer, field: "reefer" }, { val: cr.bond_fee, field: "bond_fee" },
                            ].map(({ val: v, field: f }, vi) => {
                              const isEditingThis = editingLaneRateId === cr.id && editingLaneField === f;
                              return (
                                <td key={vi} onClick={e => { e.stopPropagation(); setEditingLaneRateId(cr.id); setEditingLaneField(f); setEditingLaneValue(v != null && v !== "" ? String(v) : ""); }}
                                  style={{ padding: "8px 6px", textAlign: "center", cursor: "text", fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
                                    color: isEditingThis ? "#F0F2F5" : v ? "#C8D0DC" : "#2D3340" }}>
                                  {isEditingThis ? (
                                    <input autoFocus type="number" step="0.01" value={editingLaneValue}
                                      onChange={e => setEditingLaneValue(e.target.value)}
                                      onBlur={() => handleLaneRateUpdate(cr.id, f, editingLaneValue)}
                                      onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setEditingLaneRateId(null); setEditingLaneField(null); } }}
                                      onClick={e => e.stopPropagation()}
                                      style={{ width: 55, padding: "2px 4px", textAlign: "center", borderRadius: 4, border: "1px solid rgba(0,212,170,0.4)", background: "rgba(0,212,170,0.06)", color: "#F0F2F5", fontSize: 10, fontFamily: "'JetBrains Mono', monospace", outline: "none" }} />
                                  ) : (
                                    v ? (typeof v === "number" || !isNaN(v) ? `$${parseFloat(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}` : v) : "\u2014"
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* History Tab — Applied rates from accepted quotes */}
      {tab === "history" && (
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
      )}

    </div>
  );
}
