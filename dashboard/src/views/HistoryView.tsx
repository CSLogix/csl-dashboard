import { useState, useEffect, useCallback } from "react";
import { apiFetch, API_BASE } from "../helpers/api";
import {
  STATUSES, FTL_STATUSES, BILLING_STATUSES,
  STATUS_COLORS, BILLING_STATUS_COLORS,
  MASTER_REPS,
} from "../helpers/constants";
import { normalizeStatus, mapShipment } from "../helpers/utils";

export default function HistoryView({ loaded, handleLoadClick, handleStatusUpdate }) {
  const [completedLoads, setCompletedLoads] = useState([]);
  const [historySearch, setHistorySearch] = useState("");
  const [historyRep, setHistoryRep] = useState("all");
  const [historyAccount, setHistoryAccount] = useState("all");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [inlineStatusId, setInlineStatusId] = useState(null);

  const handleHistoryStatusUpdate = async (load, newStatusKey) => {
    setInlineStatusId(null);
    const allStatuses = [...STATUSES, ...FTL_STATUSES, ...BILLING_STATUSES];
    const statusLabel = allStatuses.find(st => st.key === newStatusKey)?.label || newStatusKey;
    setCompletedLoads(prev => prev.map(l => l.efj === load.efj ? { ...l, status: statusLabel } : l));
    try {
      const r = await apiFetch(`${API_BASE}/api/v2/load/${load.efj}/status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatusKey }),
      });
      if (!r.ok) setCompletedLoads(prev => prev.map(l => l.efj === load.efj ? { ...l, status: load.status } : l));
    } catch {
      setCompletedLoads(prev => prev.map(l => l.efj === load.efj ? { ...l, status: load.status } : l));
    }
    if (handleStatusUpdate) {
      const mapped = mapShipment(load, 9999);
      if (mapped?.id) handleStatusUpdate(mapped.id, newStatusKey);
    }
  };

  useEffect(() => {
    if (!inlineStatusId) return;
    const close = () => setInlineStatusId(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [inlineStatusId]);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), limit: "50" });
      if (historySearch) params.set("search", historySearch);
      if (historyRep !== "all") params.set("rep", historyRep);
      if (historyAccount !== "all") params.set("account", historyAccount);
      const res = await apiFetch(`${API_BASE}/api/completed?${params}`);
      if (res.ok) {
        const data = await res.json();
        setCompletedLoads(data.loads || []);
        setHasMore(data.has_more || false);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [page, historySearch, historyRep, historyAccount]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const allAccounts = [...new Set(completedLoads.map(l => l.account).filter(Boolean))].sort();

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      <div style={{ padding: "16px 0 10px" }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em", margin: 0 }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>LOAD </span>
          <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>HISTORY</span>
        </h1>
        <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>Completed and archived loads</div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input value={historySearch} onChange={e => { setHistorySearch(e.target.value); setPage(1); }}
          placeholder="Search EFJ, container, account..."
          style={{ flex: 1, minWidth: 180, padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
        <select value={historyRep} onChange={e => { setHistoryRep(e.target.value); setPage(1); }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119", color: "#F0F2F5", fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          <option value="all">All Reps</option>
          {MASTER_REPS.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={historyAccount} onChange={e => { setHistoryAccount(e.target.value); setPage(1); }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119", color: "#F0F2F5", fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          <option value="all">All Accounts</option>
          {allAccounts.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>

      <div className="dash-panel" style={{ overflow: "hidden" }}>
        <div style={{ overflow: "auto", maxHeight: 600 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["EFJ #", "Container", "Account", "Carrier", "Origin \u2192 Dest", "Delivery", "Status", "Rep"].map(h => (
                  <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>Loading...</td></tr>
              ) : completedLoads.length === 0 ? (
                <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: "#3D4557" }}>
                  <div style={{ fontSize: 11, fontWeight: 600 }}>{historySearch ? "No loads match your search" : "No completed loads found"}</div>
                  <div style={{ fontSize: 11, marginTop: 4, color: "#3D4557" }}>Loads appear here after being archived from active sheets</div>
                </td></tr>
              ) : completedLoads.map((l, i) => {
                const sc = STATUS_COLORS[normalizeStatus(l.status)] || BILLING_STATUS_COLORS[normalizeStatus(l.status)] || { main: "#94a3b8" };
                return (
                  <tr key={i} className="row-hover" onClick={() => handleLoadClick && handleLoadClick(mapShipment(l, 9000 + i))}
                    style={{ cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{l.efj}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#F0F2F5" }}>{l.container}</td>
                    <td style={{ padding: "8px 14px", fontSize: 11, color: "#F0F2F5" }}>{l.account}</td>
                    <td style={{ padding: "8px 14px", fontSize: 11, color: "#F0F2F5" }}>{l.carrier}</td>
                    <td style={{ padding: "8px 14px", fontSize: 11 }}>
                      <span style={{ color: "#F0F2F5" }}>{l.origin}</span>
                      <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                      <span style={{ color: "#F0F2F5" }}>{l.destination}</span>
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 11, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{l.delivery_date || l.delivery}</td>
                    <td style={{ padding: "8px 14px", position: "relative" }}
                      onClick={(e) => { e.stopPropagation(); setInlineStatusId(inlineStatusId === l.efj ? null : l.efj); }}>
                      {inlineStatusId === l.efj ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 3, position: "absolute", left: 0, top: 0, zIndex: 20,
                          background: "#161B26", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, padding: "8px 10px",
                          boxShadow: "0 8px 32px rgba(0,0,0,0.6)", minWidth: 200 }}
                          onClick={e => e.stopPropagation()}>
                          {[...STATUSES, ...BILLING_STATUSES].filter(st => st.key !== "all").map(st => {
                            const stc = STATUS_COLORS[st.key] || BILLING_STATUS_COLORS[st.key] || { main: "#94a3b8" };
                            const isActive = normalizeStatus(l.status) === st.key;
                            return (
                              <button key={st.key} onClick={(e) => { e.stopPropagation(); handleHistoryStatusUpdate(l, st.key); }}
                                style={{ padding: "3px 8px", fontSize: 8, fontWeight: 700, borderRadius: 14, cursor: "pointer",
                                  border: `1px solid ${isActive ? stc.main + "66" : "rgba(255,255,255,0.06)"}`,
                                  background: isActive ? `${stc.main}18` : "transparent",
                                  color: isActive ? stc.main : "#64748b", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{st.label}</button>
                            );
                          })}
                        </div>
                      ) : (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 11, fontWeight: 700,
                          color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase", cursor: "pointer" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                          {l.status}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 11, color: "#8B95A8" }}>{l.rep}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {(page > 1 || hasMore) && (
          <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: page > 1 ? "#F0F2F5" : "#3D4557", fontSize: 11, fontWeight: 600, cursor: page > 1 ? "pointer" : "default", fontFamily: "inherit" }}>
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: "#5A6478" }}>Page {page}</span>
            <button onClick={() => setPage(p => p + 1)} disabled={!hasMore}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: hasMore ? "#F0F2F5" : "#3D4557", fontSize: 11, fontWeight: 600, cursor: hasMore ? "pointer" : "default", fontFamily: "inherit" }}>
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
