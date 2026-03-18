import { useState, useEffect } from 'react';
import { DRAY_EQUIPMENT, FTL_EQUIPMENT, TRUCK_TYPES, REP_ACCOUNTS, MASTER_REPS, STATUSES, FTL_STATUSES, DOC_TYPES_ADD, DOC_TYPE_LABELS } from '../helpers/constants';
import { apiFetch, API_BASE } from '../helpers/api';
import { parseMMDD, formatMMDD } from '../helpers/utils';

export default function AddForm({ onSubmit, onCancel, accounts }) {
  const accts = (accounts || ["All Accounts"]).filter(a => a !== "All Accounts");
  const [form, setForm] = useState({
    efj: "", status: "at_port", account: accts[0] || "", carrier: "", origin: "", destination: "",
    container: "", moveType: "Dray Import", eta: "", lfd: "", pickupDate: "", deliveryDate: "", notes: "",
    macropointUrl: "", carrierEmail: "", trailerNumber: "", driverPhone: "",
    bol: "", customerRef: "", equipmentType: "", rep: "", hub: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupDone, setLookupDone] = useState(false);
  const [addingAccount, setAddingAccount] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountRep, setNewAccountRep] = useState("Eli");
  const [pendingDocs, setPendingDocs] = useState([]);
  const [dateInputs, setDateInputs] = useState({ eta: "", lfd: "", pickupDate: "", deliveryDate: "" });
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkRows, setBulkRows] = useState([{ efj: "", container: "", customerRef: "", pickupDate: "", deliveryDate: "", notes: "" }]);
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0, active: false, errors: [] });
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));
  const inputStyle = { width: "100%", padding: "10px 14px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" };
  const autoFilledStyle = { ...inputStyle, borderColor: "rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.04)" };
  const labelStyle = { fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 6, display: "block", textTransform: "uppercase" };

  const isDray = form.moveType.startsWith("Dray");
  const isExport = form.moveType === "Dray Export";
  const isFTL = form.moveType === "FTL";
  const equipOpts = isFTL ? FTL_EQUIPMENT : DRAY_EQUIPMENT;
  const isBoviet = form.account.toLowerCase() === "boviet";
  const isTolead = form.account.toLowerCase() === "tolead";
  const needsHub = isBoviet || isTolead;
  const hubOptions = isBoviet
    ? ["", "Piedra", "Hanson", "DTE Fresh/Stock", "Radiance Solar", "Renewable Energy", "Sundance", "Other Shipments"]
    : isTolead ? ["", "ORD", "JFK", "LAX", "DFW"] : [""];

  // Auto-resolve rep from account (skip if adding a brand-new account)
  useEffect(() => {
    if (!form.account || addingAccount) return;
    for (const [rep, acctList] of Object.entries(REP_ACCOUNTS)) {
      if (acctList.some(a => a.toLowerCase() === form.account.toLowerCase())) {
        set("rep", rep);
        return;
      }
    }
    // Unknown account from dropdown — clear rep so user can pick manually
    set("rep", "");
    set("hub", ""); // clear hub when account changes
  }, [form.account]);

  // Dynamic date labels
  const dateLabel1 = isExport ? "ERD" : "ETA";
  const dateLabel2 = isExport ? "CUTOFF" : "LFD";

  // MM/DD date input handler
  const handleDateInput = (field, raw) => {
    const digits = raw.replace(/\D/g, "");
    let display = digits;
    if (digits.length >= 3) display = digits.slice(0, 2) + "/" + digits.slice(2, 4);
    setDateInputs(p => ({ ...p, [field]: display }));
    if (digits.length === 4) {
      const parsed = parseMMDD(digits);
      if (parsed) set(field, parsed);
    } else if (digits.length === 0) {
      set(field, "");
    }
  };

  // SeaRates auto-fetch
  const doLookup = async () => {
    const number = isDray ? (isExport ? form.bol : form.container) : null;
    if (!number || !number.trim()) return;
    setLookupLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/searates/lookup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ moveType: form.moveType, number: number.trim(), origin: form.origin, destination: form.destination }),
      });
      if (res.ok) {
        const data = await res.json();
        if (isExport) {
          if (data.erd) { set("eta", data.erd); setDateInputs(p => ({ ...p, eta: formatMMDD(data.erd) })); }
          if (data.cutoff) { set("lfd", data.cutoff); setDateInputs(p => ({ ...p, lfd: formatMMDD(data.cutoff) })); }
        } else {
          if (data.eta) { set("eta", data.eta); setDateInputs(p => ({ ...p, eta: formatMMDD(data.eta) })); }
          if (data.lfd) { set("lfd", data.lfd); setDateInputs(p => ({ ...p, lfd: formatMMDD(data.lfd) })); }
        }
        if (data.carrier && !form.carrier) set("carrier", data.carrier);
        if (data.vessel) set("vessel", data.vessel);
        setLookupDone(true);
      }
    } catch (e) { /* auto-fetch failed silently — user can enter dates manually */ }
    setLookupLoading(false);
  };

  // File handling for doc upload (click + drag-and-drop)
  const [dragOver, setDragOver] = useState(false);
  const guessDocType = (name) => {
    const n = name.toLowerCase();
    if (n.endsWith(".msg") || n.endsWith(".eml")) return "email";
    if (n.includes("bol") || n.includes("bill_of_lading")) return "bol";
    if (n.includes("pod") || n.includes("proof_of_delivery")) return "pod";
    if (n.includes("invoice")) return "carrier_invoice";
    if (n.includes("rate") && n.includes("carrier")) return "carrier_rate";
    if (n.includes("rate")) return "customer_rate";
    return "other";
  };
  const handleFileAdd = (e) => {
    const files = Array.from(e.target.files || []);
    const newDocs = files.map(f => ({ file: f, docType: guessDocType(f.name) }));
    setPendingDocs(p => [...p, ...newDocs]);
    e.target.value = "";
  };
  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) {
      const newDocs = files.map(f => ({ file: f, docType: guessDocType(f.name) }));
      setPendingDocs(p => [...p, ...newDocs]);
    }
  };

  // Bulk helpers
  const addBulkRow = () => setBulkRows(r => [...r, { efj: "", container: "", customerRef: "", pickupDate: "", deliveryDate: "", notes: "" }]);
  const removeBulkRow = (i) => setBulkRows(r => r.length <= 1 ? r : r.filter((_, j) => j !== i));
  const setBulkField = (i, field, val) => setBulkRows(r => r.map((row, j) => j === i ? { ...row, [field]: val } : row));
  const handleBulkSubmit = async () => {
    setError("");
    const valid = bulkRows.filter(r => r.efj.trim());
    if (!valid.length) { setError("At least one EFJ is required"); return; }
    if (!form.origin || !form.destination) { setError("Origin and Destination are required for all loads"); return; }
    setSubmitting(true);
    setBulkProgress({ done: 0, total: valid.length, active: true, errors: [] });
    for (let i = 0; i < valid.length; i++) {
      const row = valid[i];
      try {
        await onSubmit({
          efj: row.efj.trim(),
          move_type: form.moveType,
          status: form.status,
          account: form.account,
          carrier: form.carrier,
          origin: form.origin,
          destination: form.destination,
          container: row.container || "",
          pickup_date: row.pickupDate || form.pickupDate || "",
          delivery_date: row.deliveryDate || form.deliveryDate || "",
          eta: form.eta || "",
          lfd: form.lfd || "",
          bol: form.bol || "",
          customer_ref: row.customerRef || form.customerRef || "",
          equipment_type: form.equipmentType || "",
          notes: row.notes || form.notes,
          rep: form.rep || "",
          hub: form.hub || "",
          macropoint_url: form.moveType === "FTL" ? (form.macropointUrl || null) : null,
          driver_phone: form.driverPhone || null,
          trailer_number: form.trailerNumber || null,
          carrier_email: form.carrierEmail || null,
          pendingDocs: i === 0 ? pendingDocs : [], // only attach docs to first load
          _bulkMode: true, // signal parent not to close form
        });
        setBulkProgress(p => ({ ...p, done: p.done + 1 }));
      } catch (err) {
        setBulkProgress(p => ({ ...p, done: p.done + 1, errors: [...p.errors, `${row.efj}: ${err.message}`] }));
      }
    }
    setBulkProgress(p => ({ ...p, active: false }));
    setSubmitting(false);
    // Don't auto-close — let user see results and click Cancel to close
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {error && <div style={{ padding: "8px 12px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, color: "#f87171", fontSize: 11, fontWeight: 600 }}>{error}</div>}

      {/* Mode toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button onClick={() => setBulkMode(false)} style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid " + (!bulkMode ? "#00D4AA" : "rgba(255,255,255,0.06)"), background: !bulkMode ? "rgba(0,212,170,0.1)" : "transparent", color: !bulkMode ? "#00D4AA" : "#8B95A8", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Single Load</button>
        <button onClick={() => setBulkMode(true)} style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid " + (bulkMode ? "#3B82F6" : "rgba(255,255,255,0.06)"), background: bulkMode ? "rgba(59,130,246,0.1)" : "transparent", color: bulkMode ? "#3B82F6" : "#8B95A8", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Bulk Create</button>
      </div>

      {/* Row 1: EFJ + Container/Booking (single mode only) */}
      {!bulkMode && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div><label style={labelStyle}>EFJ Pro #</label><input value={form.efj} onChange={e => set("efj", e.target.value.toUpperCase())} placeholder="EFJ107050" style={{ ...inputStyle, fontWeight: 700, fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }} /></div>
          <div>
            <label style={labelStyle}>Container #</label>
            <div style={{ position: "relative" }}>
              <input value={form.container} onChange={e => set("container", e.target.value.toUpperCase())} onBlur={() => { if (isDray && !isExport && form.container.trim()) doLookup(); }} placeholder="MAEU1234567" style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace", paddingRight: lookupLoading ? 36 : 14 }} />
              {lookupLoading && <div style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", width: 14, height: 14, border: "2px solid #1e293b", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />}
              {lookupDone && !lookupLoading && isDray && !isExport && <div style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", color: "#00D4AA", fontSize: 12 }}>&#10003;</div>}
            </div>
          </div>
        </div>
      )}

      {/* Row 2: Move Type + Equipment Type */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={labelStyle}>Move Type</label>
          <select value={form.moveType} onChange={e => { set("moveType", e.target.value); set("equipmentType", ""); setLookupDone(false); }} style={inputStyle}>
            {["Dray Import", "Dray Export", "Dray/Transload", "FTL"].map(t => <option key={t} style={{ background: "#0D1119" }}>{t}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Equipment Type</label>
          <select value={form.equipmentType} onChange={e => set("equipmentType", e.target.value)} style={inputStyle}>
            {equipOpts.map(t => <option key={t} value={t} style={{ background: "#0D1119" }}>{t || "Select..."}</option>)}
          </select>
        </div>
      </div>

      {/* Row 3: Account + Rep */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={labelStyle}>Account</label>
          {addingAccount ? (
            <div style={{ display: "flex", gap: 6 }}>
              <input value={newAccountName} onChange={e => setNewAccountName(e.target.value)} placeholder="New account name" style={{ ...inputStyle, flex: 1 }} autoFocus />
              <button onClick={() => { if (newAccountName.trim()) { set("account", newAccountName.trim()); set("rep", newAccountRep); setAddingAccount(false); } }} style={{ padding: "8px 12px", background: "rgba(0,212,170,0.15)", border: "1px solid rgba(0,212,170,0.3)", borderRadius: 8, color: "#00D4AA", fontSize: 11, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>Add</button>
              <button onClick={() => { setAddingAccount(false); set("account", accts[0] || ""); }} style={{ padding: "8px 10px", background: "transparent", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, color: "#8B95A8", fontSize: 11, cursor: "pointer" }}>&#10005;</button>
            </div>
          ) : (
            <select value={form.account} onChange={e => { if (e.target.value === "__new__") { setAddingAccount(true); setNewAccountName(""); } else { set("account", e.target.value); } }} style={inputStyle}>
              {accts.map(a => <option key={a} style={{ background: "#0D1119" }}>{a}</option>)}
              <option value="__new__" style={{ background: "#0D1119", color: "#00D4AA" }}>+ Add New Account...</option>
            </select>
          )}
        </div>
        <div>
          <label style={labelStyle}>{addingAccount ? "Assign Rep" : "Assigned Rep"}</label>
          {addingAccount ? (
            <select value={newAccountRep} onChange={e => setNewAccountRep(e.target.value)} style={inputStyle}>
              {MASTER_REPS.map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
            </select>
          ) : (
            <select value={form.rep} onChange={e => set("rep", e.target.value)} style={inputStyle}>
              <option value="" style={{ background: "#0D1119" }}>Auto (from account)</option>
              {MASTER_REPS.map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Row 3b: Project/Hub (Boviet or Tolead only) */}
      {needsHub && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <label style={labelStyle}>{isBoviet ? "Project" : "Hub"}</label>
            <select value={form.hub} onChange={e => set("hub", e.target.value)} style={inputStyle}>
              {hubOptions.map(h => <option key={h} value={h} style={{ background: "#0D1119" }}>{h || `Select ${isBoviet ? "project" : "hub"}...`}</option>)}
            </select>
          </div>
          <div />
        </div>
      )}

      {/* Row 4: BOL/Booking + Customer Ref */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={labelStyle}>{isExport ? "Booking #" : "BOL #"}</label>
          <div style={{ position: "relative" }}>
            <input value={form.bol} onChange={e => set("bol", e.target.value.toUpperCase())} onBlur={() => { if (isExport && form.bol.trim()) doLookup(); }} placeholder={isExport ? "Booking number" : "BOL number"} style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace", paddingRight: (lookupLoading && isExport) ? 36 : 14 }} />
            {lookupLoading && isExport && <div style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", width: 14, height: 14, border: "2px solid #1e293b", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />}
            {lookupDone && !lookupLoading && isExport && <div style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", color: "#00D4AA", fontSize: 12 }}>&#10003;</div>}
          </div>
        </div>
        <div><label style={labelStyle}>Customer Ref #</label><input value={form.customerRef} onChange={e => set("customerRef", e.target.value)} placeholder="Reference number" style={inputStyle} /></div>
      </div>

      {/* Row 5: Carrier + Status */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div><label style={labelStyle}>Carrier</label><input value={form.carrier} onChange={e => set("carrier", e.target.value)} placeholder="Carrier name" style={lookupDone && form.carrier ? autoFilledStyle : inputStyle} /></div>
        <div>
          <label style={labelStyle}>Status</label>
          <select value={form.status} onChange={e => set("status", e.target.value)} style={inputStyle}>
            {(isFTL ? FTL_STATUSES : STATUSES).filter(s => s.key !== "all").map(s => <option key={s.key} value={s.key} style={{ background: "#0D1119" }}>{s.label}</option>)}
          </select>
        </div>
      </div>

      {/* Row 6: Origin + Destination */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div><label style={labelStyle}>Origin</label><input value={form.origin} onChange={e => set("origin", e.target.value)} placeholder="Port Newark, NJ" style={inputStyle} /></div>
        <div><label style={labelStyle}>Destination</label><input value={form.destination} onChange={e => set("destination", e.target.value)} placeholder="Columbus, OH" style={inputStyle} /></div>
      </div>

      {/* Row 7: ETA/ERD + LFD/Cutoff (hidden for FTL) */}
      {!isFTL && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <label style={labelStyle}>{dateLabel1} <span style={{ fontWeight: 400, color: "#5A6478", letterSpacing: 0, textTransform: "none" }}>MM/DD</span></label>
            <input value={dateInputs.eta || formatMMDD(form.eta)} onChange={e => handleDateInput("eta", e.target.value)} onBlur={() => { if (!dateInputs.eta) return; const parsed = parseMMDD(dateInputs.eta); if (parsed) set("eta", parsed); }} placeholder="03/05" maxLength={5} style={lookupDone && form.eta ? autoFilledStyle : { ...inputStyle, fontFamily: "'JetBrains Mono', monospace" }} />
          </div>
          <div>
            <label style={labelStyle}>{dateLabel2} <span style={{ fontWeight: 400, color: "#5A6478", letterSpacing: 0, textTransform: "none" }}>MM/DD</span></label>
            <input value={dateInputs.lfd || formatMMDD(form.lfd)} onChange={e => handleDateInput("lfd", e.target.value)} onBlur={() => { if (!dateInputs.lfd) return; const parsed = parseMMDD(dateInputs.lfd); if (parsed) set("lfd", parsed); }} placeholder="03/07" maxLength={5} style={lookupDone && form.lfd ? autoFilledStyle : { ...inputStyle, fontFamily: "'JetBrains Mono', monospace" }} />
          </div>
        </div>
      )}

      {/* Row 8: Pickup + Delivery */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={labelStyle}>Pickup Date <span style={{ fontWeight: 400, color: "#5A6478", letterSpacing: 0, textTransform: "none" }}>MM/DD</span></label>
          <input value={dateInputs.pickupDate || formatMMDD(form.pickupDate)} onChange={e => handleDateInput("pickupDate", e.target.value)} onBlur={() => { if (!dateInputs.pickupDate) return; const parsed = parseMMDD(dateInputs.pickupDate); if (parsed) set("pickupDate", parsed); }} placeholder="03/10" maxLength={5} style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace" }} />
        </div>
        <div>
          <label style={labelStyle}>Delivery Date <span style={{ fontWeight: 400, color: "#5A6478", letterSpacing: 0, textTransform: "none" }}>MM/DD</span></label>
          <input value={dateInputs.deliveryDate || formatMMDD(form.deliveryDate)} onChange={e => handleDateInput("deliveryDate", e.target.value)} onBlur={() => { if (!dateInputs.deliveryDate) return; const parsed = parseMMDD(dateInputs.deliveryDate); if (parsed) set("deliveryDate", parsed); }} placeholder="03/12" maxLength={5} style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace" }} />
        </div>
      </div>

      {/* Notes */}
      <div><label style={labelStyle}>Notes</label><textarea value={form.notes} onChange={e => set("notes", e.target.value)} placeholder="Load notes..." style={{ ...inputStyle, minHeight: 60, resize: "vertical" }} /></div>

      {/* FTL Details */}
      {isFTL && (
        <>
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12, marginTop: 2 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#14b8a6", letterSpacing: "1.5px", marginBottom: 10, textTransform: "uppercase" }}>FTL Details</div>
            <div><label style={labelStyle}>Macropoint URL</label><input value={form.macropointUrl} onChange={e => set("macropointUrl", e.target.value)} placeholder="https://visibility.macropoint.com/..." style={inputStyle} /></div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div><label style={labelStyle}>Driver Phone #</label><input value={form.driverPhone} onChange={e => set("driverPhone", e.target.value)} placeholder="(555) 555-5555" style={inputStyle} /></div>
            <div><label style={labelStyle}>Trailer #</label><input value={form.trailerNumber} onChange={e => set("trailerNumber", e.target.value)} placeholder="Trailer #" style={inputStyle} /></div>
          </div>
          <div><label style={labelStyle}>Carrier Email</label><input value={form.carrierEmail} onChange={e => set("carrierEmail", e.target.value)} placeholder="dispatch@carrier.com" style={inputStyle} /></div>
        </>
      )}

      {/* Document Upload — drag & drop + click */}
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12, marginTop: 2 }}
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase" }}>Documents</span>
          <label style={{ padding: "5px 12px", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: 6, color: "#3B82F6", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            + Add Files
            <input type="file" multiple onChange={handleFileAdd} style={{ display: "none" }} />
          </label>
        </div>
        {pendingDocs.length === 0 && (
          <label style={{ display: "block", padding: "28px 12px", borderRadius: 10, border: dragOver ? "2px dashed #3B82F6" : "2px dashed rgba(255,255,255,0.08)", background: dragOver ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.015)", textAlign: "center", transition: "all 0.15s", cursor: "pointer" }}>
            <div style={{ fontSize: 22, marginBottom: 6, opacity: dragOver ? 1 : 0.4 }}>{dragOver ? "\u{1F4E5}" : "\u{1F4CE}"}</div>
            <div style={{ fontSize: 11, color: dragOver ? "#3B82F6" : "#8B95A8", fontWeight: 600 }}>{dragOver ? "Drop files here" : "Drag & drop files here"}</div>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 4 }}>PDFs, images, emails (.msg, .eml), or any document</div>
            <input type="file" multiple onChange={handleFileAdd} style={{ display: "none" }} />
          </label>
        )}
        {pendingDocs.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {pendingDocs.map((doc, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: "rgba(255,255,255,0.02)", borderRadius: 6, border: "1px solid rgba(255,255,255,0.04)" }}>
                <span style={{ fontSize: 11, color: "#F0F2F5", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.file.name}</span>
                <select value={doc.docType} onChange={e => { const updated = [...pendingDocs]; updated[i] = { ...doc, docType: e.target.value }; setPendingDocs(updated); }} style={{ padding: "3px 6px", background: "#0D1119", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 4, color: "#8B95A8", fontSize: 11 }}>
                  {DOC_TYPES_ADD.map(dt => <option key={dt} value={dt}>{DOC_TYPE_LABELS[dt] || dt}</option>)}
                </select>
                <button onClick={() => setPendingDocs(p => p.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "#EF4444", cursor: "pointer", fontSize: 12, padding: "0 4px" }}>&#10005;</button>
              </div>
            ))}
            <div style={{ padding: "8px", borderRadius: 6, border: dragOver ? "2px dashed #3B82F6" : "2px dashed rgba(255,255,255,0.04)", textAlign: "center", transition: "all 0.15s" }}>
              <div style={{ fontSize: 11, color: "#5A6478" }}>Drop more files here</div>
            </div>
          </div>
        )}
      </div>

      {/* Bulk Mode: per-load rows */}
      {bulkMode && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12, marginTop: 2 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#3B82F6", letterSpacing: "1.5px", textTransform: "uppercase" }}>Loads to Create ({bulkRows.length})</span>
            <button onClick={addBulkRow} style={{ padding: "4px 12px", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: 6, color: "#3B82F6", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>+ Add Row</button>
          </div>
          <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 8 }}>Shared fields above (account, carrier, origin, dest, status) apply to all loads. Enter unique EFJ, container, and dates per row.</div>
          <div style={{ display: "grid", gridTemplateColumns: "110px 110px 110px 65px 65px 1fr 28px", gap: 4, marginBottom: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>EFJ #</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>Container/Load</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>Customer Ref</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>PU</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>DEL</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", padding: "0 4px" }}>Notes</span>
            <span />
          </div>
          {bulkRows.map((row, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "110px 110px 110px 65px 65px 1fr 28px", gap: 4, marginBottom: 4 }}>
              <input value={row.efj} onChange={e => setBulkField(i, "efj", e.target.value.toUpperCase())} placeholder="EFJ107050" style={{ ...inputStyle, padding: "6px 8px", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }} />
              <input value={row.container} onChange={e => setBulkField(i, "container", e.target.value.toUpperCase())} placeholder="Container #" style={{ ...inputStyle, padding: "6px 8px", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }} />
              <input value={row.customerRef} onChange={e => setBulkField(i, "customerRef", e.target.value)} placeholder="Ref #" style={{ ...inputStyle, padding: "6px 8px", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }} />
              <input value={row.pickupDate} onChange={e => { let v = e.target.value.replace(/[^\d/: ]/g, ""); setBulkField(i, "pickupDate", v); }} placeholder="MM/DD" style={{ ...inputStyle, padding: "6px 6px", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", textAlign: "center" }} />
              <input value={row.deliveryDate} onChange={e => { let v = e.target.value.replace(/[^\d/: ]/g, ""); setBulkField(i, "deliveryDate", v); }} placeholder="MM/DD" style={{ ...inputStyle, padding: "6px 6px", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", textAlign: "center" }} />
              <input value={row.notes} onChange={e => setBulkField(i, "notes", e.target.value)} placeholder="Notes (optional)" style={{ ...inputStyle, padding: "6px 8px", fontSize: 11 }} />
              <button onClick={() => removeBulkRow(i)} disabled={bulkRows.length <= 1} style={{ background: "none", border: "none", color: bulkRows.length <= 1 ? "#2A3040" : "#EF4444", cursor: bulkRows.length <= 1 ? "default" : "pointer", fontSize: 12, padding: 0, fontFamily: "inherit" }}>&#10005;</button>
            </div>
          ))}
          {bulkProgress.active && (
            <div style={{ marginTop: 8 }}>
              <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                <div style={{ height: "100%", background: "#3B82F6", borderRadius: 2, width: `${(bulkProgress.done / bulkProgress.total) * 100}%`, transition: "width 0.3s ease" }} />
              </div>
              <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 4 }}>Creating {bulkProgress.done}/{bulkProgress.total} loads...</div>
            </div>
          )}
          {!bulkProgress.active && bulkProgress.done > 0 && (
            <div style={{ marginTop: 8, padding: "8px 12px", background: bulkProgress.errors.length ? "rgba(239,68,68,0.08)" : "rgba(0,212,170,0.08)", border: "1px solid " + (bulkProgress.errors.length ? "rgba(239,68,68,0.2)" : "rgba(0,212,170,0.2)"), borderRadius: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: bulkProgress.errors.length ? "#f87171" : "#00D4AA" }}>
                {bulkProgress.done - bulkProgress.errors.length}/{bulkProgress.total} loads created successfully
              </div>
              {bulkProgress.errors.map((err, i) => <div key={i} style={{ fontSize: 11, color: "#f87171", marginTop: 2 }}>{err}</div>)}
            </div>
          )}
        </div>
      )}

      {/* Submit */}
      <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
        <button onClick={onCancel} style={{ flex: 1, padding: "11px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Cancel</button>
        {!bulkMode ? (
          <button disabled={submitting} onClick={() => {
            setError("");
            if (!form.efj.trim()) { setError("EFJ Pro # is required"); return; }
            if (!form.carrier || !form.origin || !form.destination) { setError("Carrier, Origin, and Destination are required"); return; }
            setSubmitting(true);
            onSubmit({
              efj: form.efj.trim(),
              move_type: form.moveType,
              status: form.status,
              account: form.account,
              carrier: form.carrier,
              origin: form.origin,
              destination: form.destination,
              container: form.container,
              pickup_date: form.pickupDate || "",
              delivery_date: form.deliveryDate || "",
              eta: form.eta || "",
              lfd: form.lfd || "",
              bol: form.bol || "",
              customer_ref: form.customerRef || "",
              equipment_type: form.equipmentType || "",
              notes: form.notes,
              rep: form.rep || "",
              hub: form.hub || "",
              macropoint_url: isFTL ? (form.macropointUrl || null) : null,
              driver_phone: form.driverPhone || null,
              trailer_number: form.trailerNumber || null,
              carrier_email: form.carrierEmail || null,
              pendingDocs,
            });
          }} className="btn-primary" style={{ flex: 1.5, padding: "11px", border: "none", borderRadius: 10, color: "#fff", fontSize: 12, fontWeight: 700, cursor: submitting ? "wait" : "pointer", opacity: submitting ? 0.6 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
            {submitting ? "Creating..." : "Add Load"}
          </button>
        ) : (
          <button disabled={submitting} onClick={handleBulkSubmit} style={{ flex: 1.5, padding: "11px", border: "none", borderRadius: 10, background: submitting ? "#1e40af" : "linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: submitting ? "wait" : "pointer", opacity: submitting ? 0.7 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
            {submitting ? `Creating ${bulkProgress.done}/${bulkProgress.total}...` : `Create ${bulkRows.filter(r => r.efj.trim()).length} Loads`}
          </button>
        )}
      </div>
    </div>
  );
}
