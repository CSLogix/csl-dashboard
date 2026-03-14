import { useState, useEffect, useRef } from "react";
import { apiFetch, API_BASE } from "../helpers/api";
import { UNBILLED_BILLING_FLOW, REP_COLORS, Z } from "../helpers/constants";

export default function UnbilledView({ loaded, unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats }) {
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [groupBy, setGroupBy] = useState(false);
  const [collapsed, setCollapsed] = useState({});
  const [ubSearch, setUbSearch] = useState("");
  const [billingFilter, setBillingFilter] = useState("all");
  const fileRef = useRef(null);

  const handleBillingStatus = async (id, currentStatus) => {
    const flowKeys = UNBILLED_BILLING_FLOW.map(s => s.key);
    const idx = flowKeys.indexOf(currentStatus || "ready_to_bill");
    const nextStatus = flowKeys[Math.min(idx + 1, flowKeys.length - 1)];
    setUnbilledOrders(prev => prev.map(o => o.id === id ? { ...o, billing_status: nextStatus } : o));
    try {
      await apiFetch(`${API_BASE}/api/unbilled/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ billing_status: nextStatus }),
      });
      if (nextStatus === "closed") {
        setTimeout(() => setUnbilledOrders(prev => prev.filter(o => o.id !== id)), 2000);
      }
    } catch {
      setUnbilledOrders(prev => prev.map(o => o.id === id ? { ...o, billing_status: currentStatus } : o));
    }
  };

  const fetchUnbilled = async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled`);
      if (r.ok) { const data = await r.json(); setUnbilledOrders(data.orders || data || []); }
    } catch {}
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled/stats`);
      if (r.ok) setUnbilledStats(await r.json());
    } catch {}
  };

  useEffect(() => { fetchUnbilled(); }, []);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploading(true); setUploadMsg(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled/upload`, { method: "POST", body: fd });
      if (r.ok) {
        const data = await r.json();
        let msg = `Imported ${data.imported} orders`;
        if (data.reconciled > 0) msg += ` | ${data.reconciled} reconciled`;
        if (data.delivered_count > 0) msg += ` | ${data.delivered_count} already delivered`;
        setUploadMsg(msg);
        fetchUnbilled();
      }
      else { setUploadMsg(`Upload failed (${r.status})`); }
    } catch (e) { setUploadMsg("Upload error \u2014 backend may not be ready"); }
    setUploading(false);
  };

  const handleDismiss = async (id) => {
    try {
      await apiFetch(`${API_BASE}/api/unbilled/${id}/dismiss`, { method: "POST" });
      setUnbilledOrders(prev => prev.filter(o => o.id !== id));
    } catch {}
  };

  const ageColor = (days) => days > 60 ? "#ef4444" : days > 30 ? "#f97316" : days > 14 ? "#fbbf24" : "#94a3b8";

  const customerGroups = {};
  unbilledOrders.forEach(o => {
    const key = o.bill_to || o.customer || "Unknown";
    if (!customerGroups[key]) customerGroups[key] = [];
    customerGroups[key].push(o);
  });
  const sortedCustomers = Object.entries(customerGroups).sort((a, b) => {
    const maxA = Math.max(...a[1].map(o => o.age_days || 0));
    const maxB = Math.max(...b[1].map(o => o.age_days || 0));
    return maxB - maxA;
  });

  const filteredOrders = unbilledOrders.filter(o => {
    if (billingFilter !== "all" && (o.billing_status || "ready_to_bill") !== billingFilter) return false;
    if (ubSearch) {
      const q = ubSearch.toLowerCase();
      return (o.order_num || "").toLowerCase().includes(q)
        || (o.container || "").toLowerCase().includes(q)
        || (o.bill_to || o.customer || "").toLowerCase().includes(q)
        || (o.tractor || "").toLowerCase().includes(q)
        || (o.rep || "").toLowerCase().includes(q);
    }
    return true;
  });
  const searchedOrders = filteredOrders;

  const searchedCustomerGroups = {};
  searchedOrders.forEach(o => {
    const key = o.bill_to || o.customer || "Unknown";
    if (!searchedCustomerGroups[key]) searchedCustomerGroups[key] = [];
    searchedCustomerGroups[key].push(o);
  });
  const searchedCustomers = Object.entries(searchedCustomerGroups).sort((a, b) => {
    const maxA = Math.max(...a[1].map(o => o.age_days || 0));
    const maxB = Math.max(...b[1].map(o => o.age_days || 0));
    return maxB - maxA;
  });

  const handleDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    const file = e.dataTransfer?.files?.[0];
    if (file && (file.name.endsWith('.xls') || file.name.endsWith('.xlsx'))) handleUpload(file);
  };

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      <div style={{ padding: "24px 0 16px" }}>
        <h2 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>UNBILLED </span>
          <span style={{ color: "#F97316" }}>ORDERS</span>
        </h2>
        <div style={{ fontSize: 12, color: "#5A6478", marginTop: 4, letterSpacing: "0.01em" }}>Upload report, track aging, prioritize collections</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="dash-panel" style={{ padding: "20px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", cursor: "pointer", minHeight: 120 }}
          onClick={() => fileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
          onDrop={handleDrop}>
          <input ref={fileRef} type="file" accept=".xls,.xlsx" style={{ display: "none" }}
            onChange={e => { if (e.target.files[0]) handleUpload(e.target.files[0]); e.target.value = ""; }} />
          {uploading ? (
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 24, height: 24, border: "3px solid #1A2236", borderTop: "3px solid #f97316", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 10px" }} />
              <div style={{ fontSize: 12, color: "#f97316", fontWeight: 600 }}>Processing...</div>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>{"\uD83D\uDCC4"}</div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Drop .xls/.xlsx or click to upload</div>
              <div style={{ fontSize: 11, color: "#3D4557", marginTop: 4 }}>Order Not Billed Report</div>
            </>
          )}
          {uploadMsg && <div style={{ marginTop: 8, fontSize: 11, fontWeight: 600, color: uploadMsg.includes("failed") || uploadMsg.includes("error") ? "#f87171" : "#34d399" }}>{uploadMsg}</div>}
        </div>

        <div className="dash-panel" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div className="dash-panel-title" style={{ marginBottom: 12 }}>Summary</div>
          <div style={{ display: "flex", gap: 20 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#f97316", fontFamily: "'JetBrains Mono', monospace" }}>{unbilledStats?.count || unbilledOrders.length}</div>
              <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Orders</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: ageColor(unbilledStats?.oldest_age || 0), fontFamily: "'JetBrains Mono', monospace" }}>{unbilledStats?.oldest_age || 0}<span style={{ fontSize: 12, color: "#8B95A8" }}>d</span></div>
              <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Oldest</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{sortedCustomers.length}</div>
              <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Customers</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{unbilledOrders.filter(o => o.shipment_delivered).length}</div>
              <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Delivered</div>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <div style={{ display: "flex", gap: 2, background: "#0D1119", borderRadius: 10, padding: 3, width: "fit-content" }}>
          <button onClick={() => setGroupBy(false)}
            style={{ padding: "5px 14px", borderRadius: 5, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              background: !groupBy ? "#1E2738" : "transparent", color: !groupBy ? "#F0F2F5" : "#8B95A8" }}>All Orders</button>
          <button onClick={() => setGroupBy(true)}
            style={{ padding: "5px 14px", borderRadius: 5, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              background: groupBy ? "#1E2738" : "transparent", color: groupBy ? "#F0F2F5" : "#8B95A8" }}>By Customer</button>
        </div>
        {unbilledOrders.filter(o => o.shipment_delivered).length > 0 && (
          <button onClick={async () => {
            if (!confirm(`Close ${unbilledOrders.filter(o => o.shipment_delivered).length} delivered orders and archive them to history?`)) return;
            try {
              const r = await apiFetch(`${API_BASE}/api/unbilled/bulk-close-delivered`, { method: "POST" });
              if (r.ok) { const d = await r.json(); setUploadMsg(`Closed ${d.closed_count} delivered orders \u2192 archived to history`); fetchUnbilled(); }
            } catch {}
          }}
            style={{ padding: "5px 14px", borderRadius: 8, border: "1px solid #34d39944", background: "#34d39918", color: "#34d399",
              fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
            Close {unbilledOrders.filter(o => o.shipment_delivered).length} Delivered
          </button>
        )}
      </div>

      <div style={{ position: "relative", marginBottom: 12, maxWidth: 320 }}>
        <input value={ubSearch} onChange={e => setUbSearch(e.target.value)}
          placeholder="Search order#, container, customer..."
          style={{ width: "100%", padding: "9px 14px 9px 34px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
        <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: "#8B95A8" }}>{"\u2315"}</span>
        {ubSearch && (
          <span onClick={() => setUbSearch("")}
            style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "#8B95A8", cursor: "pointer" }}>{"\u2715"}</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
        {[{ key: "all", label: "All", color: "#8B95A8" }, ...UNBILLED_BILLING_FLOW].map(f => {
          const count = f.key === "all" ? unbilledOrders.length : unbilledOrders.filter(o => (o.billing_status || "ready_to_bill") === f.key).length;
          const isActive = billingFilter === f.key;
          return (
            <button key={f.key} onClick={() => setBillingFilter(f.key)}
              style={{ padding: "4px 12px", fontSize: 11, fontWeight: 700, borderRadius: 6, border: `1px solid ${isActive ? f.color + "66" : "rgba(255,255,255,0.06)"}`,
                background: isActive ? f.color + "18" : "transparent", color: isActive ? f.color : "#5A6478", cursor: "pointer", fontFamily: "inherit" }}>
              {f.label} <span style={{ opacity: 0.7 }}>{count}</span>
            </button>
          );
        })}
      </div>

      {unbilledOrders.length === 0 ? (
        <div className="dash-panel" style={{ padding: 40, textAlign: "center" }}>
          <div style={{ fontSize: 36, marginBottom: 10, opacity: 0.2 }}>{"\uD83D\uDCCB"}</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#8B95A8" }}>No unbilled orders loaded</div>
          <div style={{ fontSize: 11, color: "#3D4557", marginTop: 4 }}>Upload an Order Not Billed Report to get started</div>
        </div>
      ) : !groupBy ? (
        <div className="dash-panel" style={{ overflow: "hidden" }}>
          <div style={{ overflow: "auto", maxHeight: "calc(100vh - 400px)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["Order #", "Container", "Customer", "Rep", "Entered", "Age", "Tracking", "Billing"].map(h => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: Z.table }}>{h}</th>
                  ))}
                  <th style={{ padding: "10px 14px", width: 40, background: "#0D1119", position: "sticky", top: 0, zIndex: Z.table, borderBottom: "1px solid rgba(255,255,255,0.04)" }} />
                </tr>
              </thead>
              <tbody>
                {searchedOrders.map((o, i) => (
                  <tr key={o.id || i} className="row-hover" style={{ borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{o.order_num}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#5A6478" }}>{o.container}</td>
                    <td style={{ padding: "8px 14px", color: "#8B95A8", fontSize: 11 }}>{o.bill_to || o.customer}</td>
                    <td style={{ padding: "8px 14px", fontSize: 11, fontWeight: 600, color: REP_COLORS[o.rep] || "#5A6478" }}>{o.rep || "\u2014"}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#8B95A8" }}>{o.entered_date || o.entered}</td>
                    <td style={{ padding: "8px 14px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(o.age_days || 0), fontFamily: "'JetBrains Mono', monospace" }}>{o.age_days || 0}d</span>
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {o.shipment_delivered ? (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700,
                          color: "#34d399", background: "rgba(52,211,153,0.12)", border: "1px solid rgba(52,211,153,0.2)" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#34d399" }} />
                          {o.shipment_status || "Delivered"}
                        </span>
                      ) : o.shipment_status ? (
                        <span style={{ fontSize: 11, fontWeight: 600, color: "#5A6478", padding: "2px 8px", borderRadius: 12,
                          background: "rgba(139,149,168,0.08)", border: "1px solid rgba(139,149,168,0.12)" }}>
                          {o.shipment_status}
                        </span>
                      ) : (
                        <span style={{ fontSize: 11, color: "#3D4557" }}>{"\u2014"}</span>
                      )}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {(() => {
                        const st = UNBILLED_BILLING_FLOW.find(s => s.key === (o.billing_status || "ready_to_bill")) || UNBILLED_BILLING_FLOW[0];
                        const isClosed = st.key === "closed";
                        return (
                          <button onClick={() => !isClosed && handleBillingStatus(o.id, o.billing_status || "ready_to_bill")}
                            title={isClosed ? "Closed" : "Click to advance"}
                            style={{ padding: "3px 10px", fontSize: 11, fontWeight: 700, borderRadius: 12,
                              border: `1px solid ${st.color}44`, background: `${st.color}18`, color: st.color,
                              cursor: isClosed ? "default" : "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
                              opacity: isClosed ? 0.6 : 1 }}>
                            {st.label}
                          </button>
                        );
                      })()}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      <button onClick={() => handleDismiss(o.id)} title="Dismiss"
                        style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 12, padding: "2px 6px", borderRadius: 4 }}
                        onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>{"\u2715"}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {searchedCustomers.length === 0 && ubSearch && (
            <div className="dash-panel" style={{ padding: 30, textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "#8B95A8" }}>{"No orders match \""}{ubSearch}{"\""}</div>
            </div>
          )}
          {searchedCustomers.map(([customer, orders]) => {
            const isCollapsed = collapsed[customer];
            const maxAge = Math.max(...orders.map(o => o.age_days || 0));
            return (
              <div key={customer} className="dash-panel" style={{ overflow: "hidden" }}>
                <div onClick={() => setCollapsed(p => ({ ...p, [customer]: !isCollapsed }))}
                  style={{ padding: "12px 16px", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: isCollapsed ? "none" : "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 11, color: "#8B95A8", transition: "transform 0.2s", transform: isCollapsed ? "rotate(-90deg)" : "rotate(0)" }}>{"\u25BC"}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>{customer}</span>
                    <span style={{ fontSize: 11, color: "#8B95A8", background: "rgba(255,255,255,0.04)", padding: "2px 8px", borderRadius: 10 }}>{orders.length} orders</span>
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(maxAge), fontFamily: "'JetBrains Mono', monospace" }}>oldest: {maxAge}d</span>
                </div>
                {!isCollapsed && (
                  <div style={{ overflow: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <tbody>
                        {orders.map((o, i) => (
                          <tr key={o.id || i} className="row-hover" style={{ borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                            <td style={{ padding: "6px 14px 6px 36px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{o.order_num}</td>
                            <td style={{ padding: "6px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#5A6478" }}>{o.container}</td>
                            <td style={{ padding: "6px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#8B95A8" }}>{o.entered_date}</td>
                            <td style={{ padding: "6px 14px" }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(o.age_days || 0), fontFamily: "'JetBrains Mono', monospace" }}>{o.age_days || 0}d</span>
                            </td>
                            <td style={{ padding: "6px 14px" }}>
                              {(() => {
                                const st = UNBILLED_BILLING_FLOW.find(s => s.key === (o.billing_status || "ready_to_bill")) || UNBILLED_BILLING_FLOW[0];
                                const isClosed = st.key === "closed";
                                return (
                                  <button onClick={() => !isClosed && handleBillingStatus(o.id, o.billing_status || "ready_to_bill")}
                                    style={{ padding: "2px 8px", fontSize: 8, fontWeight: 700, borderRadius: 10,
                                      border: `1px solid ${st.color}44`, background: `${st.color}18`, color: st.color,
                                      cursor: isClosed ? "default" : "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
                                      opacity: isClosed ? 0.6 : 1 }}>
                                    {st.label}
                                  </button>
                                );
                              })()}
                            </td>
                            <td style={{ padding: "6px 14px", textAlign: "right" }}>
                              <button onClick={() => handleDismiss(o.id)} title="Dismiss"
                                style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 12, padding: "2px 6px", borderRadius: 4 }}
                                onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>{"\u2715"}</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
