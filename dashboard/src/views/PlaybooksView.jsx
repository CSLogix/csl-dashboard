import { useState, useEffect, useCallback, useMemo } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';
import { useAppStore } from '../store';

// ═══════════════════════════════════════════════════════════════
// PLAYBOOKS VIEW — Lane playbook browser + detail viewer
// Self-contained: fetches own data, manages own sub-views
// ═══════════════════════════════════════════════════════════════

const ROLE_COLORS = {
  "Customer Primary": "#00D4AA", "Customer Backup": "#00A8CC",
  "Shipper Primary": "#F59E0B", "Shipper Backup": "#D97706",
  "Carrier Dispatch": "#8B5CF6", "Carrier Sales": "#7C3AED",
  "Warehouse": "#3B82F6", "Terminal": "#60A5FA",
  "Receiver": "#10B981", "Freight Forwarder": "#06B6D4", "Other": "#5A6478",
};

const FACILITY_ICONS = {
  "Shipper": "\u{1F3ED}", "Receiver": "\u{1F4E6}", "Warehouse": "\u{1F3E2}",
  "Transload": "\u{1F504}", "Port Terminal": "\u{2693}", "Rail Yard": "\u{1F6E4}\uFE0F",
  "Cross-Dock": "\u{1F69A}", "Other": "\u{1F4CD}",
};

const CARRIER_ROLE_COLORS = {
  "Primary": "#00D4AA", "Backup": "#F59E0B", "Spot Only": "#8B5CF6", "Emergency": "#EF4444",
};

// ── Detail: Contact Card ──
function ContactCard({ contact }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "rgba(255,255,255,0.02)", borderRadius: 8, border: "1px solid rgba(255,255,255,0.04)" }}>
      <div style={{ width: 6, height: 6, borderRadius: "50%", background: ROLE_COLORS[contact.role] || "#5A6478", flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{contact.name}</div>
        <div style={{ fontSize: 10, color: "#5A6478" }}>{contact.role} — {contact.facility}</div>
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        {contact.email && <span style={{ fontSize: 10, color: "#00A8CC", fontFamily: "'JetBrains Mono', monospace" }}>{contact.email}</span>}
        {contact.phone && <span style={{ fontSize: 10, color: "#8B95A8" }}>{contact.phone}</span>}
      </div>
    </div>
  );
}

// ── Detail: Facility Card ──
function FacilityCard({ facility }) {
  const icon = FACILITY_ICONS[facility.type] || "\u{1F4CD}";
  const det = facility.detention_rules || {};
  return (
    <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>{facility.name}</div>
          <div style={{ fontSize: 10, color: "#5A6478" }}>{facility.type}{facility.address ? ` — ${facility.address}` : ""}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 10 }}>
        {facility.hours && <div><span style={{ color: "#5A6478" }}>Hours:</span> <span style={{ color: "#8B95A8" }}>{facility.hours}</span></div>}
        {facility.scheduling_type && <div><span style={{ color: "#5A6478" }}>Schedule:</span> <span style={{ color: "#8B95A8" }}>{facility.scheduling_type}</span></div>}
        {facility.scheduling_method && <div><span style={{ color: "#5A6478" }}>Method:</span> <span style={{ color: "#8B95A8" }}>{facility.scheduling_method}</span></div>}
        {facility.transload_capable && <div><span style={{ color: "#00D4AA", fontWeight: 600 }}>Transload capable</span></div>}
        {facility.chassis_available && <div><span style={{ color: "#00A8CC", fontWeight: 600 }}>Chassis available</span></div>}
        {det.free_time_hours != null && <div><span style={{ color: "#5A6478" }}>Free time:</span> <span style={{ color: "#F59E0B" }}>{det.free_time_hours}h</span></div>}
        {det.demurrage_rate_per_day != null && <div><span style={{ color: "#5A6478" }}>Demurrage:</span> <span style={{ color: "#EF4444" }}>${det.demurrage_rate_per_day}/day</span></div>}
      </div>
      {facility.quirks && facility.quirks !== "TBD" && (
        <div style={{ marginTop: 8, padding: "6px 10px", background: "rgba(249,115,22,0.08)", borderRadius: 6, border: "1px solid rgba(249,115,22,0.15)", fontSize: 10, color: "#F59E0B" }}>
          {facility.quirks}
        </div>
      )}
    </div>
  );
}

// ── Detail: Carrier Card ──
function CarrierCard({ carrier }) {
  const roleColor = CARRIER_ROLE_COLORS[carrier.role] || "#5A6478";
  return (
    <div className="glass" style={{ padding: 14, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", flex: 1 }}>{carrier.name}</div>
        <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 6, background: `${roleColor}20`, color: roleColor, textTransform: "uppercase", letterSpacing: "0.5px" }}>
          {carrier.role}
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 10 }}>
        {carrier.dot_number && <span style={{ color: "#5A6478" }}>DOT: <span style={{ color: "#8B95A8" }}>{carrier.dot_number}</span></span>}
        {carrier.mc_number && <span style={{ color: "#5A6478" }}>MC: <span style={{ color: "#8B95A8" }}>{carrier.mc_number}</span></span>}
        {carrier.rate_paid != null && <span style={{ color: "#5A6478" }}>Rate: <span style={{ color: "#00D4AA", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>${carrier.rate_paid.toLocaleString()}</span></span>}
        {carrier.flag_if_over != null && <span style={{ color: "#5A6478" }}>Flag if &gt; <span style={{ color: "#EF4444", fontWeight: 700 }}>${carrier.flag_if_over.toLocaleString()}</span></span>}
        {carrier.loads_covered && <span style={{ color: "#5A6478" }}>Covers: <span style={{ color: "#8B95A8" }}>Load {carrier.loads_covered.join(", ")}</span></span>}
      </div>
      {carrier.notes && (
        <div style={{ marginTop: 6, fontSize: 10, color: "#F59E0B", fontStyle: "italic" }}>{carrier.notes}</div>
      )}
      {carrier.rate_source && <div style={{ marginTop: 4, fontSize: 9, color: "#5A6478" }}>Source: {carrier.rate_source}</div>}
    </div>
  );
}

// ── Detail: Workflow Timeline ──
function WorkflowTimeline({ steps }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div style={{ position: "relative", paddingLeft: 20 }}>
      <div style={{ position: "absolute", left: 7, top: 4, bottom: 4, width: 2, background: "rgba(0,212,170,0.15)", borderRadius: 2 }} />
      {steps.map((step, i) => (
        <div key={i} style={{ position: "relative", paddingBottom: i < steps.length - 1 ? 16 : 0, paddingLeft: 16 }}>
          <div style={{ position: "absolute", left: -16, top: 3, width: 16, height: 16, borderRadius: "50%", background: "#141A28", border: "2px solid #00D4AA", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8, fontWeight: 700, color: "#00D4AA" }}>
            {step.step_number}
          </div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", marginBottom: 2 }}>{step.action}</div>
          {step.details && <div style={{ fontSize: 10, color: "#8B95A8", marginBottom: 4 }}>{step.details}</div>}
          {step.notify && step.notify.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {step.notify.map((email, j) => (
                <span key={j} style={{ fontSize: 9, padding: "1px 6px", borderRadius: 4, background: "rgba(0,168,204,0.1)", color: "#00A8CC", fontFamily: "'JetBrains Mono', monospace" }}>{email}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Detail: Escalation Rules ──
function EscalationPanel({ rules }) {
  if (!rules) return null;
  const tiers = [
    { key: "handle_autonomously", label: "Handle Autonomously", color: "#00D4AA", icon: "\u2713" },
    { key: "flag_but_proceed", label: "Flag but Proceed", color: "#F59E0B", icon: "\u26A0" },
    { key: "escalate_to_john", label: "Escalate to John", color: "#EF4444", icon: "\u{1F6A8}" },
  ];
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {tiers.map(tier => {
        const items = rules[tier.key];
        if (!items || items.length === 0) return null;
        return (
          <div key={tier.key} style={{ padding: "10px 14px", borderRadius: 8, background: `${tier.color}08`, border: `1px solid ${tier.color}20` }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: tier.color, marginBottom: 6 }}>{tier.icon} {tier.label}</div>
            {items.map((item, i) => (
              <div key={i} style={{ fontSize: 10, color: "#8B95A8", paddingLeft: 12, position: "relative", marginBottom: 2 }}>
                <span style={{ position: "absolute", left: 0, color: tier.color }}>•</span>{item}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// PLAYBOOK DETAIL VIEW
// ═══════════════════════════════════════════════════════════════
function PlaybookDetail({ playbook, onBack }) {
  const pb = playbook.playbook || playbook;
  const lane = pb.lane || {};
  const ls = pb.load_structure || {};
  const rates = pb.rates || {};
  const bd = pb.booking_defaults || {};

  return (
    <div style={{ animation: "fade-in 0.3s ease" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <button onClick={onBack} style={{ background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#8B95A8", cursor: "pointer", padding: "6px 12px", fontSize: 12, fontWeight: 600 }}>
          ← Back
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", letterSpacing: "-0.5px" }}>{pb.lane_code || playbook.lane_code}</div>
          <div style={{ fontSize: 12, color: "#5A6478" }}>{pb.account_name || playbook.account_name} — {lane.origin_city}, {lane.origin_state} →{lane.destination_city}, {lane.destination_state}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#5A6478" }}>v{pb.version || playbook.version}</span>
          <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 6, background: (pb.status || playbook.status) === "active" ? "rgba(0,212,170,0.12)" : "rgba(249,115,22,0.12)", color: (pb.status || playbook.status) === "active" ? "#00D4AA" : "#F59E0B", textTransform: "uppercase" }}>
            {pb.status || playbook.status}
          </span>
        </div>
      </div>

      {/* Overview Cards Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 20 }}>
        {lane.commodity && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Commodity</div>
            <div style={{ fontSize: 12, color: "#F0F2F5", fontWeight: 600, marginTop: 2 }}>{lane.commodity}</div>
          </div>
        )}
        {lane.typical_weight_lbs && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Typical Weight</div>
            <div style={{ fontSize: 12, color: "#F0F2F5", fontWeight: 600, marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>{lane.typical_weight_lbs.toLocaleString()} lbs</div>
          </div>
        )}
        {rates.combined_lane_revenue != null && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Lane Revenue</div>
            <div style={{ fontSize: 12, color: "#00D4AA", fontWeight: 700, marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>${rates.combined_lane_revenue.toLocaleString()}</div>
          </div>
        )}
        {rates.estimated_margin_pct != null && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Est. Margin</div>
            <div style={{ fontSize: 12, color: rates.estimated_margin_pct >= 20 ? "#00D4AA" : rates.estimated_margin_pct >= 10 ? "#F59E0B" : "#EF4444", fontWeight: 700, marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>{rates.estimated_margin_pct.toFixed(1)}%</div>
          </div>
        )}
        {ls.total_loads && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Structure</div>
            <div style={{ fontSize: 12, color: "#F0F2F5", fontWeight: 600, marginTop: 2 }}>{ls.multi_load ? `${ls.total_loads} loads / booking` : "Single load"}</div>
          </div>
        )}
        {bd.typical_container_size && (
          <div className="glass" style={{ padding: "10px 14px", borderRadius: 10 }}>
            <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Container</div>
            <div style={{ fontSize: 12, color: "#F0F2F5", fontWeight: 600, marginTop: 2 }}>{bd.typical_container_size}</div>
          </div>
        )}
      </div>

      {/* Main Grid: 2 columns */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }} className="dash-grid-2">
        {/* Left Column */}
        <div style={{ display: "grid", gap: 16 }}>
          {/* Load Structure */}
          {ls.loads && ls.loads.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Load Structure</div>
              {ls.loads.map((load, i) => (
                <div key={i} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.02)", borderRadius: 8, border: "1px solid rgba(255,255,255,0.04)", marginBottom: i < ls.loads.length - 1 ? 8 : 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 800, color: "#00D4AA" }}>Load {load.load_number}</span>
                    <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 4, background: "rgba(0,136,232,0.1)", color: "#0088E8", fontWeight: 600 }}>{load.move_type}</span>
                    {load.equipment && <span style={{ fontSize: 10, color: "#5A6478" }}>{load.equipment}</span>}
                  </div>
                  <div style={{ fontSize: 10, color: "#8B95A8" }}>
                    {load.origin_facility} →{load.destination_facility}
                  </div>
                  {load.notes && <div style={{ fontSize: 10, color: "#5A6478", fontStyle: "italic", marginTop: 2 }}>{load.notes}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Carriers */}
          {pb.carriers && pb.carriers.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Carriers</div>
              <div style={{ display: "grid", gap: 8 }}>
                {pb.carriers.map((c, i) => <CarrierCard key={i} carrier={c} />)}
              </div>
            </div>
          )}

          {/* Customer Rates */}
          {rates.customer_rates && rates.customer_rates.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Customer Rates</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ background: "rgba(255,255,255,0.02)" }}>
                    {["Load", "Description", "All-In Rate", "Source"].map(h => (
                      <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", fontSize: 9 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rates.customer_rates.map((r, i) => (
                    <tr key={i} className="row-hover" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                      <td style={{ padding: "6px 10px", color: "#00D4AA", fontWeight: 700 }}>#{r.load_number}</td>
                      <td style={{ padding: "6px 10px", color: "#8B95A8" }}>{r.description}</td>
                      <td style={{ padding: "6px 10px", color: "#F0F2F5", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>${r.all_in_rate?.toLocaleString()}</td>
                      <td style={{ padding: "6px 10px", color: "#5A6478", fontSize: 10 }}>{r.rate_source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {/* Accessorials */}
              {rates.accessorials && rates.accessorials.length > 0 && (
                <div style={{ marginTop: 12, borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", marginBottom: 6 }}>Accessorials</div>
                  {rates.accessorials.map((a, i) => (
                    <div key={i} style={{ padding: "3px 0", fontSize: 10 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ color: "#8B95A8" }}>{a.charge_type} <span style={{ color: "#5A6478" }}>({a.unit || "flat"})</span></span>
                        <span style={{ color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>${a.amount?.toLocaleString()}</span>
                      </div>
                      {a.rule && <div style={{ fontSize: 9, color: "#F59E0B", marginTop: 1 }}>{a.rule}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column */}
        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          {/* Facilities */}
          {pb.facilities && pb.facilities.length > 0 && (
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Facilities</div>
              <div style={{ display: "grid", gap: 8 }}>
                {pb.facilities.map((f, i) => <FacilityCard key={i} facility={f} />)}
              </div>
            </div>
          )}

          {/* Contacts */}
          {pb.contacts && pb.contacts.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Contacts ({pb.contacts.length})</div>
              <div style={{ display: "grid", gap: 6 }}>
                {pb.contacts.map((c, i) => <ContactCard key={i} contact={c} />)}
              </div>
            </div>
          )}

          {/* Workflow */}
          {pb.workflow_steps && pb.workflow_steps.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 16 }}>Workflow ({pb.workflow_steps.length} steps)</div>
              <WorkflowTimeline steps={pb.workflow_steps} />
            </div>
          )}

          {/* Escalation Rules */}
          {pb.escalation_rules && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 12 }}>Escalation Rules</div>
              <EscalationPanel rules={pb.escalation_rules} />
            </div>
          )}

          {/* Changelog */}
          {pb.changelog && pb.changelog.length > 0 && (
            <div className="glass" style={{ padding: 16, borderRadius: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 10 }}>Changelog</div>
              {pb.changelog.slice().reverse().map((entry, i) => (
                <div key={i} style={{ fontSize: 10, color: "#8B95A8", padding: "4px 0", borderTop: i > 0 ? "1px solid rgba(255,255,255,0.04)" : "none" }}>
                  <span style={{ color: "#5A6478" }}>{new Date(entry.date).toLocaleDateString()}</span>
                  {entry.changed_by && <span style={{ color: "#5A6478" }}> by {entry.changed_by}</span>}
                  {" — "}{entry.summary}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN EXPORT
// ═══════════════════════════════════════════════════════════════
export default function PlaybooksView() {
  const [playbooks, setPlaybooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedLane, setSelectedLane] = useState(null); // full playbook row
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");

  const fetchPlaybooks = useCallback(async () => {
    try {
      const url = statusFilter ? `${API_BASE}/api/playbooks/?status=${statusFilter}` : `${API_BASE}/api/playbooks/`;
      const res = await apiFetch(url);
      const data = await res.json();
      setPlaybooks(Array.isArray(data) ? data : []);
    } catch (e) { console.error("Failed to fetch playbooks:", e); }
    finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { fetchPlaybooks(); }, [fetchPlaybooks]);

  const fetchDetail = useCallback(async (laneCode) => {
    setDetailLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/playbooks/${laneCode}`);
      const data = await res.json();
      setSelectedLane(data);
    } catch (e) { console.error("Failed to fetch playbook detail:", e); }
    finally { setDetailLoading(false); }
  }, []);

  const filtered = useMemo(() => {
    if (!search) return playbooks;
    const q = search.toLowerCase();
    return playbooks.filter(p =>
      (p.lane_code || "").toLowerCase().includes(q) ||
      (p.account_name || "").toLowerCase().includes(q) ||
      JSON.stringify(p.lane || {}).toLowerCase().includes(q)
    );
  }, [playbooks, search]);

  // ── Detail view ──
  if (selectedLane && !detailLoading) {
    return (
      <div style={{ padding: "0 8px", animation: "fade-in 0.2s ease" }}>
        <PlaybookDetail playbook={selectedLane} onBack={() => setSelectedLane(null)} />
      </div>
    );
  }

  // ── List view ──
  return (
    <div style={{ padding: "0 8px", animation: "fade-in 0.2s ease" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", letterSpacing: "-0.5px", margin: 0 }}>Lane Playbooks</h1>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>{filtered.length} playbook{filtered.length !== 1 ? "s" : ""} configured</div>
        </div>
        <button onClick={() => { useAppStore.getState().setAskAIOpen(true); useAppStore.getState().setAskAIInitialQuery("I want to index a new lane. Help me build a playbook."); }}
          className="btn-primary"
          style={{ padding: "8px 16px", borderRadius: 8, border: "none", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
          <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 4v16m8-8H4" /></svg>
          Index New Lane
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}>
        <input
          type="text" placeholder="Search lanes, accounts..." value={search} onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, maxWidth: 320, padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "var(--bg-input)", color: "#F0F2F5", fontSize: 12, outline: "none" }}
        />
        <div style={{ display: "flex", gap: 4 }}>
          {["active", "draft", "inactive", ""].map(s => (
            <button key={s} onClick={() => setStatusFilter(s)}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: statusFilter === s ? "rgba(0,212,170,0.12)" : "transparent", color: statusFilter === s ? "#00D4AA" : "#5A6478", fontSize: 10, fontWeight: 600, cursor: "pointer", textTransform: "capitalize" }}>
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ padding: 60, textAlign: "center", color: "#5A6478" }}>
          <div style={{ width: 24, height: 24, border: "2px solid #00D4AA40", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
          Loading playbooks...
        </div>
      )}

      {/* Empty state */}
      {!loading && filtered.length === 0 && (
        <div className="glass" style={{ padding: 60, textAlign: "center", borderRadius: 14 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>{"\uD83D\uDCD6"}</div>
          <h2 style={{ color: "#F0F2F5", fontWeight: 800, fontSize: 18, margin: "0 0 8px" }}>No Playbooks Yet</h2>
          <div style={{ fontSize: 12, color: "#5A6478", maxWidth: 400, margin: "0 auto" }}>
            Lane playbooks capture everything needed to handle a specific route: contacts, rates, carriers, workflow steps, and escalation rules. Click "Index New Lane" to create your first one.
          </div>
        </div>
      )}

      {/* Playbook Cards Grid */}
      {!loading && filtered.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 12 }}>
          {filtered.map(pb => {
            const lane = typeof pb.lane === "string" ? JSON.parse(pb.lane) : (pb.lane || {});
            const rev = pb.revenue;
            const margin = pb.margin_pct;
            const loads = pb.total_loads;
            return (
              <div key={pb.lane_code} className="glass rep-card" onClick={() => fetchDetail(pb.lane_code)}
                style={{ padding: 16, borderRadius: 12, cursor: "pointer" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <div style={{ fontSize: 14, fontWeight: 800, color: "#F0F2F5", flex: 1, letterSpacing: "-0.3px" }}>{pb.lane_code}</div>
                  <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 6, background: pb.status === "active" ? "rgba(0,212,170,0.12)" : pb.status === "draft" ? "rgba(249,115,22,0.12)" : "rgba(90,100,120,0.12)", color: pb.status === "active" ? "#00D4AA" : pb.status === "draft" ? "#F59E0B" : "#5A6478", textTransform: "uppercase" }}>
                    {pb.status}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "#8B95A8", marginBottom: 6 }}>
                  {pb.account_name} — {lane.origin_city || "?"}, {lane.origin_state || "?"} →{lane.destination_city || "?"}, {lane.destination_state || "?"}
                </div>
                <div style={{ display: "flex", gap: 12, fontSize: 10 }}>
                  {loads && <span style={{ color: "#5A6478" }}>{loads} load{loads > 1 ? "s" : ""}</span>}
                  {rev != null && <span style={{ color: "#00D4AA", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>${Number(rev).toLocaleString()}</span>}
                  {margin != null && <span style={{ color: Number(margin) >= 20 ? "#00D4AA" : Number(margin) >= 10 ? "#F59E0B" : "#EF4444", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{Number(margin).toFixed(1)}%</span>}
                  <span style={{ color: "#5A6478" }}>v{pb.version}</span>
                </div>
                {pb.updated_at && (
                  <div style={{ fontSize: 9, color: "#3D4557", marginTop: 6 }}>Updated {new Date(pb.updated_at).toLocaleDateString()}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
