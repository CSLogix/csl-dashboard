import { useState, useEffect } from "react";
import { apiFetch, API_BASE } from "../helpers/api";
import { MACROPOINT_FALLBACK, Z } from "../helpers/constants";
import { relativeTime } from "../helpers/utils";

export default function MacropointModal({ shipment, onClose }) {
  const [mp, setMp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [screenshot, setScreenshot] = useState(null);

  useEffect(() => {
    if (!shipment?.efj) { setLoading(false); return; }
    setLoading(true);
    Promise.allSettled([
      apiFetch(`${API_BASE}/api/macropoint/${shipment.efj}`).then(r => r.ok ? r.json() : null),
      apiFetch(`${API_BASE}/api/load/${shipment.efj}/driver`).then(r => r.ok ? r.json() : null),
      apiFetch(`${API_BASE}/api/macropoint/${shipment.efj}/screenshot`).then(r => r.ok ? r.blob() : null),
    ]).then(([mpRes, driverRes, ssRes]) => {
      const mpData = mpRes.status === "fulfilled" && mpRes.value ? mpRes.value : { ...MACROPOINT_FALLBACK };
      const driverData = driverRes.status === "fulfilled" && driverRes.value ? driverRes.value : {};
      if (driverData.driverName) mpData.driverName = driverData.driverName;
      if (driverData.driverPhone) mpData.driverPhone = driverData.driverPhone;
      if (driverData.driverEmail) mpData.driverEmail = driverData.driverEmail;
      if (!mpData.trackingStatus || mpData.trackingStatus === "Unknown") {
        mpData.trackingStatus = shipment.rawStatus || "Pending";
      }
      setMp(mpData);
      if (ssRes.status === "fulfilled" && ssRes.value) setScreenshot(URL.createObjectURL(ssRes.value));
      setLoading(false);
    });
  }, [shipment?.efj]);

  const d = mp || MACROPOINT_FALLBACK;
  const statusColor = d.trackingStatus?.toLowerCase().includes("deliver") ? "#10b981"
    : d.trackingStatus?.toLowerCase().includes("transit") || d.trackingStatus?.toLowerCase().includes("departed") ? "#3b82f6"
    : d.trackingStatus?.toLowerCase().includes("unresponsive") || d.trackingStatus?.toLowerCase().includes("late") ? "#ef4444"
    : "#f59e0b";

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.8)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: Z.modal, animation: "fade-in 0.2s ease", padding: 20 }}
      onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ width: "100%", maxWidth: 900, maxHeight: "90vh", overflow: "auto",
        background: "linear-gradient(135deg, #0D1119, #141A28)", borderRadius: 20, border: "1px solid rgba(255,255,255,0.08)", animation: "slide-up 0.3s ease" }}>
        <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.06)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18 }}>{"\uD83D\uDCCD"}</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 800, color: "#F0F2F5" }}>Macropoint Tracking</div>
              <div style={{ fontSize: 11, color: "#8B95A8" }}>{shipment.loadNumber} | {shipment.container}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: "rgba(255,255,255,0.06)", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 16, width: 32, height: 32, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center" }}>x</button>
        </div>

        {loading ? (
          <div style={{ padding: 60, textAlign: "center", color: "#8B95A8" }}>
            <div style={{ width: 24, height: 24, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 12px" }} />
            Loading tracking data...
          </div>
        ) : (
          <>
            <div style={{ margin: "16px 24px", borderRadius: 14, overflow: "hidden", background: "linear-gradient(135deg, #0D1119, #141A28)", border: "1px solid rgba(255,255,255,0.06)" }}>
              {screenshot ? (
                <img src={screenshot} alt="Macropoint tracking" style={{ width: "100%", height: "auto", display: "block" }} />
              ) : (
                <svg width="100%" height="200" viewBox="0 0 800 200">
                  {[40,80,120,160].map(y => <line key={y} x1="0" y1={y} x2="800" y2={y} stroke="#1e293b" strokeWidth="0.5" />)}
                  {[100,200,300,400,500,600,700].map(x => <line key={x} x1={x} y1="0" x2={x} y2="200" stroke="#1e293b" strokeWidth="0.5" />)}
                  <path d="M 120 150 C 200 130, 300 40, 400 60 S 550 80, 680 50" stroke="#00A8CC" strokeWidth="3" fill="none" opacity="0.8" />
                  <circle cx="120" cy="150" r="10" fill="#10b981" stroke="#0D1119" strokeWidth="3" />
                  <text x="120" y="175" fill="#8B95A8" fontSize="10" textAnchor="middle" fontFamily="Plus Jakarta Sans">{d.origin || shipment.origin}</text>
                  {(() => { const done = d.progress.filter(s => s.done).length; const pct = done / d.progress.length; const cx = 120 + (680-120)*pct; const cy = 150 - 90*Math.sin(pct*Math.PI);
                    return <circle cx={cx} cy={cy} r="7" fill={statusColor} stroke="#0D1119" strokeWidth="2"><animate attributeName="r" values="7;9;7" dur="2s" repeatCount="indefinite" /></circle>; })()}
                  <circle cx="680" cy="50" r="10" fill="#ef4444" stroke="#0D1119" strokeWidth="3" />
                  <text x="680" y="35" fill="#8B95A8" fontSize="10" textAnchor="middle" fontFamily="Plus Jakarta Sans">{d.destination || shipment.destination}</text>
                </svg>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: 20, padding: "0 24px 20px" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 14, textTransform: "uppercase" }}>Progress Tracker</div>
                {d.progress.map((step, i) => {
                  const isLast = i === d.progress.length - 1;
                  return (
                    <div key={i} style={{ display: "flex", gap: 12, marginBottom: isLast ? 0 : 4 }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <div style={{ width: 16, height: 16, borderRadius: "50%",
                          background: step.done ? "#10b981" : "rgba(255,255,255,0.06)",
                          border: step.done ? "none" : "2px solid #334155",
                          display: "flex", alignItems: "center", justifyContent: "center" }}>
                          {step.done && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><path d="M5 13l4 4L19 7" /></svg>}
                        </div>
                        {!isLast && <div style={{ width: 2, height: 24, background: step.done ? "#10b98144" : "#1e293b" }} />}
                      </div>
                      <span style={{ fontSize: 12, color: step.done ? "#F0F2F5" : "#8B95A8", fontWeight: step.done ? 600 : 400 }}>{step.label}</span>
                    </div>
                  );
                })}
              </div>

              <div>
                {d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>{"\u26A0"}</span>
                    <div>
                      <div style={{ fontSize: 11, color: "#f87171", fontWeight: 700 }}>{"Can't Make It"}</div>
                      <div style={{ fontSize: 11, color: "#fca5a5", marginTop: 2 }}>{d.cantMakeIt}</div>
                    </div>
                  </div>
                )}
                {d.behindSchedule && !d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: "rgba(251,146,60,0.12)", border: "1px solid rgba(251,146,60,0.3)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>{"\u23F1"}</span>
                    <div>
                      <span style={{ fontSize: 11, color: "#fb923c", fontWeight: 700 }}>Behind Schedule</span>
                      {d.mpDisplayDetail && <div style={{ fontSize: 11, color: "#fdba74", marginTop: 2 }}>{d.mpDisplayDetail}</div>}
                    </div>
                  </div>
                )}
                {d.scheduleAlert && !d.behindSchedule && !d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: d.mpDisplayStatus === "On Time" ? "rgba(34,197,94,0.12)" : "rgba(59,130,246,0.12)", border: `1px solid ${d.mpDisplayStatus === "On Time" ? "rgba(34,197,94,0.3)" : "rgba(59,130,246,0.3)"}`, display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>{d.mpDisplayStatus === "On Time" ? "\u2713" : "\u2139"}</span>
                    <div>
                      <span style={{ fontSize: 11, color: d.mpDisplayStatus === "On Time" ? "#22C55E" : "#60A5FA", fontWeight: 700 }}>{d.mpDisplayStatus || "Tracking"}</span>
                      {d.mpDisplayDetail && <div style={{ fontSize: 11, color: d.mpDisplayStatus === "On Time" ? "#86EFAC" : "#93C5FD", marginTop: 2 }}>{d.mpDisplayDetail}{d.distanceToStop ? ` | ${parseFloat(d.distanceToStop).toFixed(0)} mi to stop` : ""}</div>}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 14, textTransform: "uppercase" }}>Load Details</div>
                {[
                  { label: "Load ID", value: d.loadId || shipment.container },
                  { label: "Carrier", value: d.carrier },
                  { label: "Account", value: d.account || shipment.account },
                  ...(d.mpLoadId ? [{ label: "MP Load ID", value: d.mpLoadId }] : []),
                ].map((item, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>{item.label}</span>
                    <span style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}

                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginTop: 16, marginBottom: 10, textTransform: "uppercase" }}>Driver</div>
                {d.driverName && (
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>Name</span>
                    <span style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 600 }}>{d.driverName}</span>
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Driver Phone</span>
                  {d.driverPhone ? (
                    <a href={`tel:${d.driverPhone.replace(/\D/g, '')}`} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 8,
                      background: "linear-gradient(135deg, #10b98118, #10b98128)", border: "1px solid #10b98144",
                      color: "#10b981", fontSize: 11, fontWeight: 700, textDecoration: "none" }}>
                      {"\uD83D\uDCDE"} {d.driverPhone}
                    </a>
                  ) : (
                    <span style={{ fontSize: 11, color: "#3D4557", fontStyle: "italic" }}>Not set</span>
                  )}
                </div>

                {d.driverEmail && (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>Driver Email</span>
                    <a href={`mailto:${d.driverEmail}?subject=${encodeURIComponent(`${shipment.loadNumber} - ${shipment.container} Update`)}`}
                      style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 8,
                        background: "rgba(59,130,246,0.12)", border: "1px solid rgba(59,130,246,0.3)",
                        color: "#3b82f6", fontSize: 11, fontWeight: 600, textDecoration: "none" }}>
                      {"\u2709"} {d.driverEmail}
                    </a>
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Dispatch</span>
                  <a href={`tel:${d.phone.replace(/\D/g, '')}`} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", borderRadius: 6,
                    background: "rgba(0,212,170,0.12)", border: "1px solid rgba(0,212,170,0.3)", color: "#00D4AA", fontSize: 11, fontWeight: 600, textDecoration: "none" }}>
                    {"\uD83D\uDCDE"} {d.phone}
                  </a>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Status</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, boxShadow: `0 0 6px ${statusColor}66`, animation: "pulse-glow 2s ease infinite" }} />
                    <span style={{ fontSize: 11, color: statusColor, fontWeight: 700 }}>{d.trackingStatus}</span>
                  </div>
                </div>

                {(d.pickup || d.delivery || d.eta) && (
                  <div style={{ marginTop: 8, display: "flex", gap: 12 }}>
                    {d.pickup && <div style={{ fontSize: 11, color: "#8B95A8" }}>PU: <span style={{ color: "#8B95A8" }}>{d.pickup}</span></div>}
                    {d.delivery && <div style={{ fontSize: 11, color: "#8B95A8" }}>DEL: <span style={{ color: "#8B95A8" }}>{d.delivery}</span></div>}
                    {d.eta && <div style={{ fontSize: 11, color: "#8B95A8" }}>ETA: <span style={{ color: "#8B95A8" }}>{d.eta}</span></div>}
                  </div>
                )}

                {d.timeline && d.timeline.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>Tracking History</div>
                    {d.timeline.map((ev, i) => {
                      const dotColor = ev.type === "delivered" ? "#00D4AA" : ev.type === "arrived" ? "#10b981" : ev.type === "departed" ? "#3b82f6" : ev.type === "info" ? "#f59e0b" : "#8B95A8";
                      const fmtTime = ev.time ? (() => { try { const dt = new Date(ev.time); return dt.toLocaleString("en-US", { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true }); } catch { return ev.time; } })() : "";
                      return (
                        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, marginTop: 3, background: dotColor }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <span style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 600 }}>{ev.event}</span>
                            {ev.location && <span style={{ fontSize: 11, color: "#8B95A8", marginLeft: 6 }}>{ev.location}</span>}
                          </div>
                          <span style={{ fontSize: 11, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace", flexShrink: 0, whiteSpace: "nowrap" }}>{fmtTime}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {(d.mpLastUpdated || d.lastScraped) && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "#3D4557", textAlign: "right" }} title={d.mpLastUpdated || d.lastScraped}>
                    Last MP update: {relativeTime(d.mpLastUpdated || d.lastScraped) || d.lastScraped}
                  </div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                  {d.driverPhone ? (
                    <a href={`tel:${d.driverPhone.replace(/\D/g, '')}`}
                      style={{ flex: 1, padding: "9px 0", borderRadius: 10, background: "linear-gradient(135deg, #10b98118, #10b98128)", border: "1px solid #10b98144",
                        color: "#10b981", fontSize: 11, fontWeight: 700, textDecoration: "none", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      {"\uD83D\uDCDE"} Call Driver
                    </a>
                  ) : (
                    <a href={`mailto:${d.email}?subject=${encodeURIComponent(`${shipment.loadNumber} - ${shipment.container} Tracking`)}`}
                      style={{ flex: 1, padding: "9px 0", borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
                        color: "#F0F2F5", fontSize: 11, fontWeight: 600, textDecoration: "none", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      {"\u2709"} Email Dispatch
                    </a>
                  )}
                  <button onClick={() => { const url = d.macropointUrl || shipment.macropointUrl; if (url) window.open(url, '_blank'); }}
                    style={{ flex: 1.5, padding: "9px 0", borderRadius: 10, background: "linear-gradient(135deg, #00D4AA, #0088E8)",
                      border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    {"Full Report \u2197"}
                  </button>
                </div>
              </div>
            </div>

            <div style={{ padding: "0 24px 24px" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 10, textTransform: "uppercase" }}>Shipment Route</div>
              <div style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", padding: 16, display: "flex", alignItems: "center", gap: 16, background: "rgba(0,0,0,0.2)" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>Origin</div>
                  <div style={{ fontSize: 13, color: "#10b981", fontWeight: 700, marginTop: 2 }}>{d.origin || shipment.origin || "\u2014"}</div>
                </div>
                <div style={{ color: "#3D4557", fontSize: 20 }}>{"\u2192"}</div>
                <div style={{ flex: 1, textAlign: "right" }}>
                  <div style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>Destination</div>
                  <div style={{ fontSize: 13, color: "#ef4444", fontWeight: 700, marginTop: 2 }}>{d.destination || shipment.destination || "\u2014"}</div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
