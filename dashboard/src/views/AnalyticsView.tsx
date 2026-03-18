import { useState, useEffect } from "react";
import { useAppStore } from "../store";
import { apiFetch, API_BASE } from "../helpers/api";

function DataSourceToggle() {
  const { dataSource, setDataSource, systemHealth, setSystemHealth } = useAppStore();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/health`).then(r => r.json()).then(setSystemHealth).catch(() => {});
    const t = setInterval(() => {
      apiFetch(`${API_BASE}/api/health`).then(r => r.json()).then(setSystemHealth).catch(() => {});
    }, 60000);
    return () => clearInterval(t);
  }, []);

  const toggle = () => {
    const next = dataSource === "postgres" ? "sheets" : "postgres";
    setDataSource(next);
    setLoading(true);
    setTimeout(() => setLoading(false), 2000);
  };

  const h = systemHealth;
  const pgOk = h?.checks?.postgres?.status === "ok";
  const sheetOk = h?.checks?.sheets_cache?.status === "ok";
  const overall = h?.overall || "unknown";
  const overallColor = { healthy: "#10b981", degraded: "#f59e0b", critical: "#ef4444" }[overall] || "#6b7280";

  return (
    <div style={{ background: "#141A28", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 14, padding: "14px 18px", marginBottom: 14, position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: overallColor }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", marginBottom: 4 }}>Data Source</div>
          <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
            <span style={{ color: pgOk ? "#10b981" : "#ef4444" }}>
              PG: {pgOk ? `${h?.checks?.postgres?.active_shipments || "?"} active` : "DOWN"}
            </span>
            <span style={{ color: sheetOk ? "#10b981" : "#f59e0b" }}>
              Sheets: {sheetOk ? `${h?.checks?.sheets_cache?.shipment_count || "?"} cached` : h?.checks?.sheets_cache?.status || "?"}
            </span>
            {h?.checks?.disk && <span style={{ color: "#5A6478" }}>Disk: {h.checks.disk.use_pct}</span>}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: dataSource === "postgres" ? "#00D4AA" : "#f59e0b", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {loading ? "Switching..." : dataSource === "postgres" ? "Postgres" : "Google Sheets"}
          </span>
          <button onClick={toggle} style={{
            background: dataSource === "postgres" ? "rgba(0,212,170,0.15)" : "rgba(245,158,11,0.15)",
            border: `1px solid ${dataSource === "postgres" ? "rgba(0,212,170,0.3)" : "rgba(245,158,11,0.3)"}`,
            borderRadius: 8, padding: "6px 14px", cursor: "pointer",
            color: dataSource === "postgres" ? "#00D4AA" : "#f59e0b",
            fontSize: 11, fontWeight: 700, transition: "all 0.2s"
          }}>
            Switch to {dataSource === "postgres" ? "Sheets" : "Postgres"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AnalyticsView({ loaded, botStatus, botHealth, cronStatus, sheetLog }) {
  const HEALTH_CONFIG = {
    healthy:    { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.20)", label: "HEALTHY", icon: "\u25CF" },
    degraded:   { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.20)", label: "DEGRADED", icon: "\u25B2" },
    crash_loop: { color: "#ef4444", bg: "rgba(239,68,68,0.10)", border: "rgba(239,68,68,0.25)", label: "CRASH LOOP", icon: "\u25C6" },
    down:       { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "DOWN", icon: "\u25CB" },
    idle:       { color: "#8b95a8", bg: "rgba(139,149,168,0.06)", border: "rgba(139,149,168,0.15)", label: "IDLE", icon: "\u25C7" },
  };

  const services = botHealth?.services ? Object.entries(botHealth.services) : [];
  const summary = botHealth?.summary || {};
  const cronJobs = cronStatus?.cron_jobs ? Object.entries(cronStatus.cron_jobs) : [];

  const CRON_STATUS = {
    success:  { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.20)", label: "SUCCESS", icon: "\u2713" },
    partial:  { color: "#3b82f6", bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.20)", label: "PARTIAL", icon: "\u25D4" },
    failed:   { color: "#ef4444", bg: "rgba(239,68,68,0.10)", border: "rgba(239,68,68,0.25)", label: "FAILED", icon: "\u2717" },
    overdue:  { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.20)", label: "OVERDUE", icon: "\u25B2" },
    idle:     { color: "#8b95a8", bg: "rgba(139,149,168,0.06)", border: "rgba(139,149,168,0.15)", label: "IDLE", icon: "\u25C7" },
    pending:  { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "PENDING", icon: "\u25CB" },
    no_data:  { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "NO DATA", icon: "\u2014" },
  };

  const allErrors = services.flatMap(([unit, svc]) =>
    (svc.recent_errors || []).map(e => ({ ...e, unit, name: svc.name }))
  ).sort((a, b) => (b.time || "").localeCompare(a.time || "")).slice(0, 20);

  const cronOk = cronJobs.filter(([, j]) => ["success", "partial", "idle", "pending"].includes(j.status)).length;
  const svcHealthy = (summary.services_healthy || 0) + cronOk;
  const svcTotal = (summary.services_total || 0) + cronJobs.length;

  const summaryCards = [
    { label: "Emails Sent", sub: "24h", value: summary.total_emails_24h || 0, color: "#00D4AA", gradient: "#00D4AA" },
    { label: "Crashes", sub: "24h", value: summary.total_crashes_24h || 0, color: (summary.total_crashes_24h || 0) > 0 ? "#ef4444" : "#3D4557", gradient: (summary.total_crashes_24h || 0) > 0 ? "#ef4444" : "#3D4557" },
    { label: "Cycles Run", sub: "24h", value: summary.total_cycles_24h || 0, color: "#3b82f6", gradient: "#3b82f6" },
    { label: "Services OK", sub: "", value: `${svcHealthy}/${svcTotal}`, color: svcHealthy === svcTotal ? "#10b981" : "#f59e0b", gradient: svcHealthy === svcTotal ? "#10b981" : "#f59e0b" },
  ];

  const MetricCell = ({ label, value, color }) => (
    <div>
      <div style={{ fontSize: 18, fontWeight: 800, color, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.1 }}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
    </div>
  );

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      <div style={{ padding: "20px 0 16px" }}>
        <h2 style={{ fontSize: 22, fontWeight: 900, margin: 0 }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>SYSTEM </span>
          <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>HEALTH</span>
        </h2>
        <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 2 }}>
          Bot health metrics, crash detection, and system connections
          {botHealth?.generated_at && <span style={{ marginLeft: 8, color: "#3D4557", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>cached {Math.round((Date.now() - new Date(botHealth.generated_at).getTime()) / 60000)}m ago</span>}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {summaryCards.map((s, i) => (
          <div key={i} style={{ flex: 1, minWidth: 0, background: "#141A28", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 14, padding: "14px 16px", position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: s.gradient }} />
            <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1, color: s.color, fontFamily: "'JetBrains Mono', monospace", marginBottom: 2 }}>{typeof s.value === "number" ? s.value.toLocaleString() : s.value}</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label} {s.sub && <span style={{ color: "#3D4557" }}>{s.sub}</span>}</div>
          </div>
        ))}
      </div>

      <DataSourceToggle />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        {services.map(([unit, svc]) => {
          const h = HEALTH_CONFIG[svc.health] || HEALTH_CONFIG.down;
          const j = svc.journal_24h || {};
          const isServer = svc.poll_min === 0;
          return (
            <div key={unit} style={{ background: "#141A28", border: `1px solid ${h.border}`, borderRadius: 12, padding: "14px 16px", position: "relative", overflow: "hidden", transition: "border-color 0.2s" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: h.color }} />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: svc.active_state === "active" ? "#10b981" : "#ef4444", boxShadow: `0 0 6px ${svc.active_state === "active" ? "#10b98166" : "#ef444466"}` }} />
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{svc.name}</span>
                </div>
                <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 6, background: h.bg, color: h.color, border: `1px solid ${h.border}` }}>
                  {h.icon} {h.label}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: isServer ? "1fr 1fr" : "1fr 1fr 1fr 1fr", gap: "6px 16px", marginBottom: 8 }}>
                <MetricCell label="Crashes" value={j.crashes || 0} color={(j.crashes || 0) > 0 ? "#ef4444" : "#3D4557"} />
                <MetricCell label="Emails" value={j.emails_sent || 0} color={(j.emails_sent || 0) > 0 ? "#00D4AA" : "#3D4557"} />
                {!isServer && <MetricCell label="Cycles" value={j.cycles_completed || 0} color={(j.cycles_completed || 0) > 0 ? "#3b82f6" : "#3D4557"} />}
                {!isServer && <MetricCell label="Loads" value={j.loads_tracked || 0} color={(j.loads_tracked || 0) > 0 ? "#8b5cf6" : "#3D4557"} />}
              </div>
              <div style={{ fontSize: 11, color: "#5A6478", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6, display: "flex", justifyContent: "space-between" }}>
                <span>{svc.last_successful_cycle ? `Last cycle: ${(() => { const m = Math.round((Date.now() - new Date(svc.last_successful_cycle).getTime()) / 60000); return m < 1 ? "just now" : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; })()}` : isServer ? `Up: ${svc.last_run}` : "Last cycle: none (24h)"}</span>
                {svc.next_run && !isServer && (
                  <span style={{ color: svc.next_run === "overdue" ? "#f59e0b" : "#3b82f6", fontWeight: 600 }}>next: {svc.next_run}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {cronJobs.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Scheduled Jobs
            <span style={{ fontWeight: 400, color: "#3D4557", marginLeft: 8 }}>7:30 AM & 1:30 PM Mon-Fri</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
            {cronJobs.map(([key, job]) => {
              const cs = CRON_STATUS[job.status] || CRON_STATUS.no_data;
              return (
                <div key={key} style={{ background: "#141A28", border: `1px solid ${cs.border}`, borderRadius: 12, padding: "14px 16px", position: "relative", overflow: "hidden", transition: "border-color 0.2s" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: cs.color }} />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 14 }}>{key === "dray_import" ? "\u{1F4E5}" : "\u{1F4E4}"}</span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{job.name}</span>
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 6, background: cs.bg, color: cs.color, border: `1px solid ${cs.border}` }}>
                      {cs.icon} {cs.label}
                    </span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px 16px", marginBottom: 8 }}>
                    <MetricCell label="Runs Today" value={job.runs_today || 0} color={(job.runs_today || 0) > 0 ? "#10b981" : "#3D4557"} />
                    <MetricCell label="Items" value={job.items_tracked || 0} color={(job.items_tracked || 0) > 0 ? "#8b5cf6" : "#3D4557"} />
                    <MetricCell label="Errors" value={(job.errors || []).length} color={(job.errors || []).length > 0 ? "#ef4444" : "#3D4557"} />
                  </div>
                  <div style={{ fontSize: 11, color: "#5A6478", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6 }}>
                    {job.last_run ? `Last run: ${(() => { const m = Math.round((Date.now() - new Date(job.last_run.replace(" ", "T")).getTime()) / 60000); return m < 1 ? "just now" : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; })()}` : "No runs recorded"}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div className="dash-panel" style={{ padding: "18px 20px", maxHeight: 340, overflowY: "auto" }}>
          <div className="dash-panel-title" style={{ marginBottom: 14 }}>Recent Errors & Events</div>
          {allErrors.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "#3D4557", fontSize: 11 }}>No errors in the last 24 hours</div>
          ) : allErrors.map((e, i) => (
            <div key={i} style={{ display: "flex", gap: 8, padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.02)", fontSize: 11, alignItems: "flex-start" }}>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#3D4557", flexShrink: 0, minWidth: 55 }}>{e.time}</span>
              <span style={{ padding: "0px 5px", borderRadius: 4, fontSize: 11, fontWeight: 700, flexShrink: 0,
                background: e.level === "crash" ? "rgba(239,68,68,0.12)" : "rgba(245,158,11,0.12)",
                color: e.level === "crash" ? "#ef4444" : "#f59e0b",
                border: `1px solid ${e.level === "crash" ? "rgba(239,68,68,0.25)" : "rgba(245,158,11,0.25)"}`,
              }}>{e.level === "crash" ? "CRASH" : "ERROR"}</span>
              <span style={{ color: "#8B95A8", fontWeight: 500 }}>{e.name}</span>
              <span style={{ color: "#5A6478", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.msg}</span>
            </div>
          ))}
        </div>

        <div className="dash-panel" style={{ padding: "18px 20px" }}>
          <div className="dash-panel-title" style={{ marginBottom: 14 }}>Google Sheets</div>
          {[
            { name: "Track/Tracing Master", id: "19MB5Hmm...B2S0" },
            { name: "Boviet", id: "1OP-ZDaM...p3wI" },
            { name: "Tolead ORD", id: "1-zl7CCF...2ac" },
            { name: "Tolead JFK", id: "1mfhEsK2...Bhs" },
            { name: "Tolead LAX", id: "1YLB6z5L...bXo" },
            { name: "Tolead DFW", id: "1RfGcq25...9oI" },
          ].map(s => (
            <div key={s.name} style={{ padding: 10, borderRadius: 8, border: "1px solid rgba(255,255,255,0.04)", background: "rgba(0,0,0,0.15)", marginBottom: 7 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 13 }}>{"\uD83D\uDCCA"}</span>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700 }}>{s.name}</div>
                  <div style={{ fontSize: 8, color: "#8B95A8" }}>Spreadsheet</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 11 }}>
                <span style={{ color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{s.id}</span>
                <span style={{ color: "#34d399", fontWeight: 700, fontSize: 11, padding: "1px 6px", borderRadius: 4, background: "#10b98112" }}>Operational</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
