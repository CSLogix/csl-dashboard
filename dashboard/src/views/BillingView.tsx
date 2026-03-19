import { useState, useMemo } from "react";
import { apiFetch, API_BASE } from "../helpers/api";
import { BILLING_STATUSES, BILLING_STATUS_COLORS, MASTER_REPS, REP_COLORS } from "../helpers/constants";
import { getBillingReadiness, resolveRepForShipment } from "../helpers/utils";
import UnbilledView from "./UnbilledView";

export default function BillingView({ loaded, shipments, handleStatusUpdate, handleLoadClick, setSelectedShipment,
  unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats, docSummary }) {
  const [billingTab, setBillingTab] = useState("queue");
  const [billingFilter, setBillingFilter] = useState("all");
  const [billSearch, setBillSearch] = useState("");
  const [billRepFilter, setBillRepFilter] = useState("All Reps");
  const [billAcctFilter, setBillAcctFilter] = useState("All Accounts");

  const BILLING_KEYS = ["ready_to_close", "missing_invoice", "ppwk_needed", "waiting_confirmation", "waiting_cx_approval", "cx_approved"];

  const billingQueue = useMemo(() => {
    return (Array.isArray(shipments) ? shipments : []).filter(s => BILLING_KEYS.includes(s.status));
  }, [shipments]);

  const filteredQueue = useMemo(() => {
    let q = billingQueue;
    if (billingFilter !== "all") q = q.filter(s => {
      if (billingFilter === "waiting") return ["waiting_confirmation", "waiting_cx_approval", "cx_approved"].includes(s.status);
      if (billingFilter === "close_ready") return getBillingReadiness(s.efj, docSummary).ready;
      return s.status === billingFilter;
    });
    if (billRepFilter !== "All Reps") q = q.filter(s => {
      const rep = resolveRepForShipment(s);
      return rep === billRepFilter;
    });
    if (billAcctFilter !== "All Accounts") q = q.filter(s => s.account === billAcctFilter);
    if (billSearch) {
      const qs = billSearch.toLowerCase();
      q = q.filter(s => (s.efj || "").toLowerCase().includes(qs) || (s.container || "").toLowerCase().includes(qs) ||
        (s.account || "").toLowerCase().includes(qs) || (s.carrier || "").toLowerCase().includes(qs) ||
        (s.loadNumber || "").toLowerCase().includes(qs));
    }
    q.sort((a, b) => {
      const da = a.deliveryDate ? new Date(a.deliveryDate) : new Date(0);
      const db = b.deliveryDate ? new Date(b.deliveryDate) : new Date(0);
      return da - db;
    });
    return q;
  }, [billingQueue, billingFilter, billRepFilter, billAcctFilter, billSearch, docSummary]);

  const counts = useMemo(() => ({
    ready_to_close: billingQueue.filter(s => s.status === "ready_to_close").length,
    missing_invoice: billingQueue.filter(s => s.status === "missing_invoice").length,
    ppwk_needed: billingQueue.filter(s => s.status === "ppwk_needed").length,
    waiting: billingQueue.filter(s => ["waiting_confirmation", "waiting_cx_approval", "cx_approved"].includes(s.status)).length,
    close_ready: billingQueue.filter(s => getBillingReadiness(s.efj, docSummary).ready).length,
  }), [billingQueue, docSummary]);

  const queueAccounts = useMemo(() => {
    const accts = [...new Set(billingQueue.map(s => s.account).filter(Boolean))].sort();
    return ["All Accounts", ...accts];
  }, [billingQueue]);

  const handleInvoicedToggle = async (s) => {
    const newVal = !s._invoiced;
    try {
      await apiFetch(`${API_BASE}/api/load/${s.efj}/invoiced`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ invoiced: newVal }),
      });
    } catch {}
  };

  const [bulkClosing, setBulkClosing] = useState(false);

  const smartAdvanceBillingStatus = (s) => {
    const readiness = getBillingReadiness(s.efj, docSummary);
    if (readiness.ready) {
      handleStatusUpdate(s.id, "billed_closed");
    } else if (readiness.missing.includes("carrier_invoice")) {
      if (s.status !== "missing_invoice") handleStatusUpdate(s.id, "missing_invoice");
      else handleStatusUpdate(s.id, "ppwk_needed");
    } else if (readiness.missing.includes("pod")) {
      if (s.status !== "ppwk_needed") handleStatusUpdate(s.id, "ppwk_needed");
      else handleStatusUpdate(s.id, "billed_closed");
    } else {
      handleStatusUpdate(s.id, "billed_closed");
    }
  };

  const handleBulkCloseReady = async () => {
    const readyLoads = billingQueue.filter(s => getBillingReadiness(s.efj, docSummary).ready);
    if (readyLoads.length === 0) return;
    if (!window.confirm(`Close ${readyLoads.length} load${readyLoads.length > 1 ? "s" : ""} with complete docs?`)) return;
    setBulkClosing(true);
    for (let i = 0; i < readyLoads.length; i++) {
      await handleStatusUpdate(readyLoads[i].id, "billed_closed");
      if (i < readyLoads.length - 1) await new Promise(r => setTimeout(r, 100));
    }
    setBulkClosing(false);
  };

  const statCards = [
    { label: "Close Ready", count: counts.close_ready, color: "#22C55E", filter: "close_ready" },
    { label: "Ready to Close", count: counts.ready_to_close, color: "#F59E0B", filter: "ready_to_close" },
    { label: "Missing Invoice", count: counts.missing_invoice, color: "#EF4444", filter: "missing_invoice" },
    { label: "PPWK Needed", count: counts.ppwk_needed, color: "#EAB308", filter: "ppwk_needed" },
    { label: "Waiting", count: counts.waiting, color: "#6B7280", filter: "waiting" },
  ];

  return (
    <div style={{ paddingTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 16 }}>
        {[{ key: "queue", label: "Billing Queue", count: billingQueue.length }, { key: "unbilled", label: "Unbilled Orders", count: unbilledStats?.count || 0 }].map(t => (
          <button key={t.key} onClick={() => setBillingTab(t.key)}
            style={{ padding: "8px 18px", borderRadius: 10, border: billingTab === t.key ? "1px solid rgba(0,212,170,0.3)" : "1px solid rgba(255,255,255,0.06)",
              background: billingTab === t.key ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.02)",
              color: billingTab === t.key ? "#00D4AA" : "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            {t.label}
            <span style={{ background: billingTab === t.key ? "#00D4AA22" : "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 8, fontSize: 11, fontWeight: 700,
              color: billingTab === t.key ? "#00D4AA" : "#8B95A8" }}>{t.count}</span>
          </button>
        ))}
      </div>

      {billingTab === "queue" && (
        <>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            {statCards.map(c => (
              <div key={c.filter} onClick={() => setBillingFilter(billingFilter === c.filter ? "all" : c.filter)}
                className="glass" style={{ flex: "1 1 140px", padding: "14px 18px", borderRadius: 12, cursor: "pointer",
                  border: billingFilter === c.filter ? `1px solid ${c.color}44` : "1px solid rgba(255,255,255,0.06)",
                  background: billingFilter === c.filter ? `${c.color}0A` : "rgba(255,255,255,0.02)" }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: c.color, fontFamily: "'JetBrains Mono', monospace" }}>{c.count}</div>
                <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, marginTop: 2 }}>{c.label}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <input value={billSearch} onChange={e => setBillSearch(e.target.value)} placeholder="Search EFJ, container, carrier..."
              style={{ padding: "7px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)",
                color: "#F0F2F5", fontSize: 12, width: 220, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
            <select value={billRepFilter} onChange={e => setBillRepFilter(e.target.value)}
              style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119",
                color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {["All Reps", ...MASTER_REPS].map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
            </select>
            <select value={billAcctFilter} onChange={e => setBillAcctFilter(e.target.value)}
              style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119",
                color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {queueAccounts.map(a => <option key={a} value={a} style={{ background: "#0D1119" }}>{a}</option>)}
            </select>
            {(billingFilter !== "all" || billRepFilter !== "All Reps" || billAcctFilter !== "All Accounts" || billSearch) && (
              <button onClick={() => { setBillingFilter("all"); setBillRepFilter("All Reps"); setBillAcctFilter("All Accounts"); setBillSearch(""); }}
                style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)",
                  color: "#8B95A8", fontSize: 11, cursor: "pointer" }}>Clear</button>
            )}
            {counts.close_ready > 0 && (
              <button onClick={handleBulkCloseReady} disabled={bulkClosing}
                style={{ marginLeft: "auto", padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(34,197,94,0.4)",
                  background: bulkClosing ? "rgba(34,197,94,0.05)" : "rgba(34,197,94,0.12)",
                  color: "#22C55E", fontSize: 11, fontWeight: 700, cursor: bulkClosing ? "wait" : "pointer", whiteSpace: "nowrap" }}>
                {bulkClosing ? "Closing..." : `Close All Ready (${counts.close_ready})`}
              </button>
            )}
          </div>

          <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  {["EFJ #", "Account", "Rep", "Container/Load", "Carrier", "Route", "Docs", "Delivered", "Status", "Invoiced", ""].map(h => (
                    <th key={h} style={{ padding: "10px 12px", textAlign: "left", color: "#8B95A8", fontSize: 11, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredQueue.length === 0 && (
                  <tr><td colSpan={11} style={{ padding: "40px 0", textAlign: "center", color: "#3D4557", fontSize: 12 }}>No loads in billing queue</td></tr>
                )}
                {filteredQueue.map(s => {
                  const bStatus = BILLING_STATUSES.find(b => b.key === s.status);
                  const bColor = BILLING_STATUS_COLORS[s.status]?.main || "#6B7280";
                  const rep = resolveRepForShipment(s);
                  const readiness = getBillingReadiness(s.efj, docSummary);
                  return (
                    <tr key={s.id} onClick={() => handleLoadClick(s)}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", cursor: "pointer", transition: "background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.04)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <td style={{ padding: "10px 12px", fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{s.loadNumber || s.efj}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8" }}>{s.account}</td>
                      <td style={{ padding: "10px 12px", color: REP_COLORS[rep] || "#8B95A8", fontWeight: 600 }}>{rep}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>{s.container}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8" }}>{s.carrier}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11 }}>{s.origin && s.destination ? `${s.origin} \u2192 ${s.destination}` : s.destination || "\u2014"}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <span style={{ display: "inline-flex", gap: 4, fontSize: 11 }}>
                          <span title="Carrier Invoice" style={{ color: readiness.present.includes("carrier_invoice") ? "#22C55E" : "#EF4444", fontWeight: 700 }}>
                            {readiness.present.includes("carrier_invoice") ? "INV\u2713" : "INV\u2717"}
                          </span>
                          <span title="Proof of Delivery" style={{ color: readiness.present.includes("pod") ? "#22C55E" : "#EF4444", fontWeight: 700 }}>
                            {readiness.present.includes("pod") ? "POD\u2713" : "POD\u2717"}
                          </span>
                        </span>
                      </td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
                        {s.deliveryDate ? new Date(s.deliveryDate + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "\u2014"}
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        {readiness.ready ? (
                          <button onClick={e => { e.stopPropagation(); handleStatusUpdate(s.id, "billed_closed"); }}
                            style={{ padding: "4px 12px", borderRadius: 8, border: "1px solid rgba(34,197,94,0.4)", background: "rgba(34,197,94,0.15)",
                              color: "#22C55E", fontSize: 11, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>
                            Close {"\u2713"}
                          </button>
                        ) : (
                          <button onClick={e => { e.stopPropagation(); smartAdvanceBillingStatus(s); }}
                            title={readiness.missing.length > 0 ? `Missing: ${readiness.missing.join(", ")}` : ""}
                            style={{ padding: "4px 12px", borderRadius: 8, border: `1px solid ${bColor}44`, background: `${bColor}15`,
                              color: bColor, fontSize: 11, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>
                            {bStatus?.label || s.status}
                          </button>
                        )}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "center" }}>
                        <button onClick={e => { e.stopPropagation(); handleInvoicedToggle(s); }}
                          style={{ width: 18, height: 18, borderRadius: 4, border: s._invoiced ? "2px solid #A855F7" : "2px solid #3D4557",
                            background: s._invoiced ? "#A855F7" : "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", padding: 0 }}>
                          {s._invoiced && <span style={{ color: "#fff", fontSize: 11, lineHeight: 1 }}>{"\u2713"}</span>}
                        </button>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <button onClick={e => { e.stopPropagation(); handleStatusUpdate(s.id, "billed_closed"); }}
                          title="Close out"
                          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(34,197,94,0.3)", background: "rgba(34,197,94,0.08)",
                            color: "#22C55E", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Close</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {billingTab === "unbilled" && (
        <UnbilledView loaded={loaded} unbilledOrders={unbilledOrders} setUnbilledOrders={setUnbilledOrders}
          unbilledStats={unbilledStats} setUnbilledStats={setUnbilledStats} />
      )}
    </div>
  );
}
