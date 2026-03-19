import { useState, useRef, useMemo, useEffect } from "react";
import { apiFetch, API_BASE } from "../helpers/api";
import { REP_ACCOUNTS } from "../helpers/constants";

const MAPPING_KEY = "csl_bulk_mappings";
const SHIPMENT_FIELDS = [
  { value: "", label: "-- Skip --" },
  { value: "efj", label: "EFJ #" },
  { value: "move_type", label: "Move Type" },
  { value: "container", label: "Container #" },
  { value: "bol", label: "BOL / Booking" },
  { value: "vessel", label: "Vessel / SSL" },
  { value: "carrier", label: "Carrier" },
  { value: "origin", label: "Origin" },
  { value: "destination", label: "Destination" },
  { value: "eta", label: "ETA / ERD" },
  { value: "lfd", label: "LFD / Cutoff" },
  { value: "pickup_date", label: "Pickup Date" },
  { value: "delivery_date", label: "Delivery Date" },
  { value: "status", label: "Status" },
  { value: "notes", label: "Notes" },
  { value: "driver", label: "Driver" },
  { value: "account", label: "Account" },
  { value: "customer_rate", label: "Customer Rate" },
  { value: "carrier_pay", label: "Carrier Pay" },
  { value: "hub", label: "Hub" },
];

const inputStyle: React.CSSProperties = { width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" };
const selectStyle: React.CSSProperties = { ...inputStyle, cursor: "pointer", appearance: "none" as const, backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238B95A8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center", paddingRight: 28 };
const labelStyle: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: "#5A6478", letterSpacing: "1.5px", textTransform: "uppercase" as const, marginBottom: 4, display: "block" };

function hashHeaders(headers: string[]): string {
  return [...headers].map(h => h.toLowerCase().trim()).sort().join("|");
}
function loadSavedMapping(headers: string[]): Record<string, string> | null {
  try {
    const stored = localStorage.getItem(MAPPING_KEY);
    if (!stored) return null;
    const all = JSON.parse(stored);
    return all[hashHeaders(headers)] || null;
  } catch { return null; }
}
function saveMapping(headers: string[], mappings: Record<string, string>) {
  try {
    const stored = JSON.parse(localStorage.getItem(MAPPING_KEY) || "{}");
    stored[hashHeaders(headers)] = mappings;
    localStorage.setItem(MAPPING_KEY, JSON.stringify(stored));
  } catch {}
}

function resolveRep(account: string): string {
  if (!account) return "";
  for (const [rep, accts] of Object.entries(REP_ACCOUNTS)) {
    if ((accts as string[]).some(a => a.toLowerCase() === account.toLowerCase())) return rep;
  }
  return "Unassigned";
}

export default function BulkLoadView({ accounts, onCreated }: { accounts: string[]; onCreated: () => void }) {
  const accts = (accounts || []).filter(a => a !== "All Accounts");
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Step 1 state
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragOver, setDragOver] = useState(false);

  // Step 2 state
  const [headers, setHeaders] = useState<string[]>([]);
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [remember, setRemember] = useState(true);
  const [defaults, setDefaults] = useState({ account: "", move_type: "Dray Import", status: "pending", rep: "" });
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [showDefaults, setShowDefaults] = useState(true);
  const [savedMappingApplied, setSavedMappingApplied] = useState(false);

  // Step 3 state
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<any>(null);

  // Auto-resolve rep from account default
  useEffect(() => {
    if (defaults.account) setDefaults(d => ({ ...d, rep: resolveRep(d.account) }));
  }, [defaults.account]);

  // ─── Step 1: Upload ───
  const handleFile = async (file: File) => {
    if (!file) return;
    setUploading(true); setUploadError("");
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiFetch(`${API_BASE}/api/loads/bulk-upload/preview`, { method: "POST", body: fd });
      if (r.ok) {
        const data = await r.json();
        setHeaders(data.headers);
        setRows(data.rows);
        // Check for saved mapping
        const saved = loadSavedMapping(data.headers);
        if (saved) {
          setMappings(saved);
          setSavedMappingApplied(true);
        } else {
          setMappings(data.mappings);
          setSavedMappingApplied(false);
        }
        setExcluded(new Set());
        setStep(2);
      } else {
        const err = await r.json().catch(() => ({}));
        setUploadError(err.error || `Upload failed (${r.status})`);
      }
    } catch (e: any) {
      setUploadError(e.message || "Network error");
    } finally { setUploading(false); }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    const file = e.dataTransfer?.files?.[0];
    if (file && /\.(csv|xls|xlsx|xlsm|tsv)$/i.test(file.name)) handleFile(file);
    else setUploadError("Please upload a CSV or Excel file");
  };

  // ─── Step 2: Mapping ───
  const activeMappings = useMemo(() => {
    const mapped: { colIdx: string; field: string; header: string }[] = [];
    for (const [colIdx, field] of Object.entries(mappings)) {
      if (field) mapped.push({ colIdx, field, header: headers[parseInt(colIdx)] || "" });
    }
    return mapped;
  }, [mappings, headers]);

  const includedRows = useMemo(() => rows.filter((_, i) => !excluded.has(i)), [rows, excluded]);

  const mappedPreview = useMemo(() => {
    return rows.map((row) => {
      const obj: Record<string, string> = {};
      for (const [colIdx, field] of Object.entries(mappings)) {
        if (field) obj[field] = row[colIdx] || "";
      }
      return obj;
    });
  }, [rows, mappings]);

  const missingRequired = useMemo(() => {
    const set = new Set<number>();
    mappedPreview.forEach((row, i) => {
      if (excluded.has(i)) return;
      const efj = (row.efj || defaults.account ? row.efj : "");
      const account = row.account || defaults.account;
      if (!efj && !defaults.account) set.add(i);
      if (!row.efj) set.add(i);
      if (!account) set.add(i);
    });
    return set;
  }, [mappedPreview, excluded, defaults]);

  const handleMappingChange = (colIdx: string, field: string) => {
    setMappings(prev => {
      const next = { ...prev };
      // Remove any existing mapping to this field
      if (field) {
        for (const k of Object.keys(next)) {
          if (next[k] === field && k !== colIdx) delete next[k];
        }
      }
      if (field) next[colIdx] = field;
      else delete next[colIdx];
      return next;
    });
  };

  const handleCellEdit = (rowIdx: number, colIdx: string, value: string) => {
    setRows(prev => prev.map((r, i) => i === rowIdx ? { ...r, [colIdx]: value } : r));
    setEditingCell(null);
  };

  // ─── Step 3: Create ───
  const handleCreate = async () => {
    setCreating(true);
    // Build final load objects
    const loads = includedRows.map(row => {
      const obj: Record<string, string> = {};
      for (const [colIdx, field] of Object.entries(mappings)) {
        if (field && row[colIdx]) obj[field] = row[colIdx];
      }
      return obj;
    });

    try {
      const r = await apiFetch(`${API_BASE}/api/loads/bulk-upload/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ loads, defaults }),
      });
      const data = await r.json();
      setResult(data);
      if (remember) saveMapping(headers, mappings);
      onCreated();
    } catch (e: any) {
      setResult({ error: e.message || "Network error" });
    } finally { setCreating(false); setStep(3); }
  };

  const reset = () => {
    setStep(1); setHeaders([]); setMappings({}); setRows([]); setExcluded(new Set());
    setResult(null); setUploadError(""); setSavedMappingApplied(false);
  };

  // ─── Render ───
  const displayCols = activeMappings.length > 0 ? activeMappings : headers.map((h, i) => ({ colIdx: String(i), field: "", header: h }));

  return (
    <div style={{ animation: "fade-in 0.5s ease" }}>
      {/* Header */}
      <div style={{ padding: "24px 0 16px" }}>
        <h2 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>BULK </span>
          <span style={{ color: "#00D4AA" }}>LOAD CREATOR</span>
        </h2>
        <div style={{ fontSize: 12, color: "#5A6478", marginTop: 4 }}>Upload TMS export, map columns, create loads in one click</div>
      </div>

      {/* Step indicator */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {[{ n: 1, label: "Upload" }, { n: 2, label: "Map & Preview" }, { n: 3, label: "Results" }].map(s => (
          <div key={s.n} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 24, height: 24, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700,
              background: step >= s.n ? "#00D4AA" : "rgba(255,255,255,0.06)",
              color: step >= s.n ? "#0A0E17" : "#5A6478",
            }}>{s.n}</div>
            <span style={{ fontSize: 12, fontWeight: 600, color: step >= s.n ? "#F0F2F5" : "#5A6478" }}>{s.label}</span>
            {s.n < 3 && <div style={{ width: 24, height: 1, background: "rgba(255,255,255,0.08)" }} />}
          </div>
        ))}
      </div>

      {/* ═══ STEP 1: Upload ═══ */}
      {step === 1 && (
        <div className="dash-panel" style={{ padding: 40, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 240, cursor: "pointer", border: dragOver ? "2px dashed #00D4AA" : "1px solid rgba(255,255,255,0.06)", transition: "border 0.2s" }}
          onClick={() => fileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.stopPropagation(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}>
          <input ref={fileRef} type="file" accept=".csv,.xls,.xlsx,.xlsm,.tsv" style={{ display: "none" }}
            onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]); e.target.value = ""; }} />
          {uploading ? (
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 32, height: 32, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 12px" }} />
              <div style={{ fontSize: 13, color: "#8B95A8" }}>Parsing file...</div>
            </div>
          ) : (
            <>
              <svg width="40" height="40" fill="none" stroke={dragOver ? "#00D4AA" : "#5A6478"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" style={{ marginBottom: 12, transition: "stroke 0.2s" }}>
                <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5", marginBottom: 4 }}>Drop your TMS export here</div>
              <div style={{ fontSize: 12, color: "#5A6478" }}>or click to browse &mdash; CSV, XLS, XLSX supported</div>
            </>
          )}
          {uploadError && <div style={{ marginTop: 12, fontSize: 12, color: "#EF4444", fontWeight: 600 }}>{uploadError}</div>}
        </div>
      )}

      {/* ═══ STEP 2: Map & Preview ═══ */}
      {step === 2 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Column Mapping */}
          <div className="dash-panel" style={{ padding: 20 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5" }}>Column Mapping</div>
                <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
                  {savedMappingApplied ? "Restored saved mapping" : "Auto-detected"} &mdash; adjust as needed
                </div>
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}
                  style={{ accentColor: "#00D4AA" }} />
                <span style={{ fontSize: 11, color: "#8B95A8" }}>Remember mapping</span>
              </label>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
              {headers.map((h, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "#8B95A8", minWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={h}>{h}</span>
                  <svg width="12" height="12" fill="none" stroke="#5A6478" strokeWidth="2" viewBox="0 0 24 24"><path d="M5 12h14m-7-7l7 7-7 7" /></svg>
                  <select value={mappings[String(i)] || ""} onChange={e => handleMappingChange(String(i), e.target.value)}
                    style={{ ...selectStyle, flex: 1, padding: "6px 28px 6px 10px", fontSize: 11, borderColor: mappings[String(i)] ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.06)" }}>
                    {SHIPMENT_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </div>

          {/* Defaults */}
          <div className="dash-panel" style={{ padding: showDefaults ? 20 : "12px 20" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}
              onClick={() => setShowDefaults(!showDefaults)}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5" }}>Default Values</div>
              <svg width="16" height="16" fill="none" stroke="#5A6478" strokeWidth="2" viewBox="0 0 24 24" style={{ transform: showDefaults ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </div>
            {showDefaults && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginTop: 14 }}>
                <div>
                  <label style={labelStyle}>Account</label>
                  <select value={defaults.account} onChange={e => setDefaults(d => ({ ...d, account: e.target.value }))} style={selectStyle}>
                    <option value="">--</option>
                    {accts.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Move Type</label>
                  <select value={defaults.move_type} onChange={e => setDefaults(d => ({ ...d, move_type: e.target.value }))} style={selectStyle}>
                    <option value="">--</option>
                    <option value="Dray Import">Dray Import</option>
                    <option value="Dray Export">Dray Export</option>
                    <option value="FTL">FTL</option>
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Status</label>
                  <select value={defaults.status} onChange={e => setDefaults(d => ({ ...d, status: e.target.value }))} style={selectStyle}>
                    <option value="pending">Pending</option>
                    <option value="at_port">At Port</option>
                    <option value="tracking_waiting">Tracking Waiting</option>
                    <option value="in_transit">In Transit</option>
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Rep</label>
                  <input value={defaults.rep} readOnly style={{ ...inputStyle, padding: "8px 12px", opacity: 0.7 }} />
                </div>
              </div>
            )}
          </div>

          {/* Preview Table */}
          <div className="dash-panel" style={{ padding: 20 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#F0F2F5" }}>Preview</div>
                <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
                  {includedRows.length} loads to create
                  {excluded.size > 0 && <span style={{ color: "#EF4444" }}> ({excluded.size} excluded)</span>}
                  {missingRequired.size > 0 && <span style={{ color: "#F59E0B" }}> &mdash; {missingRequired.size} missing required fields</span>}
                </div>
              </div>
              <button onClick={() => setStep(1)} style={{ fontSize: 11, color: "#8B95A8", background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, padding: "6px 14px", cursor: "pointer" }}>
                Change File
              </button>
            </div>
            <div style={{ overflowX: "auto", maxHeight: 400, overflowY: "auto", borderRadius: 8, border: "1px solid rgba(255,255,255,0.04)" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ position: "sticky", top: 0, zIndex: 2, background: "#0D1119" }}>
                    <th style={{ padding: "8px 10px", textAlign: "center", color: "#5A6478", fontSize: 10, fontWeight: 700, borderBottom: "1px solid rgba(255,255,255,0.06)", width: 32 }}>
                      <input type="checkbox" checked={excluded.size === 0}
                        onChange={() => excluded.size === 0 ? setExcluded(new Set(rows.map((_, i) => i))) : setExcluded(new Set())}
                        style={{ accentColor: "#00D4AA" }} />
                    </th>
                    <th style={{ padding: "8px 10px", textAlign: "center", color: "#5A6478", fontSize: 10, fontWeight: 700, borderBottom: "1px solid rgba(255,255,255,0.06)", width: 36 }}>#</th>
                    {activeMappings.map(m => (
                      <th key={m.colIdx} style={{ padding: "8px 10px", textAlign: "left", color: "#00D4AA", fontSize: 10, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.06)", whiteSpace: "nowrap" }}>
                        {SHIPMENT_FIELDS.find(f => f.value === m.field)?.label || m.field}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIdx) => {
                    const isExcluded = excluded.has(rowIdx);
                    const isMissing = missingRequired.has(rowIdx);
                    return (
                      <tr key={rowIdx} style={{ opacity: isExcluded ? 0.3 : 1, background: isMissing && !isExcluded ? "rgba(245,158,11,0.04)" : rowIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)" }}>
                        <td style={{ padding: "6px 10px", textAlign: "center", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                          <input type="checkbox" checked={!isExcluded}
                            onChange={() => setExcluded(prev => { const next = new Set(prev); next.has(rowIdx) ? next.delete(rowIdx) : next.add(rowIdx); return next; })}
                            style={{ accentColor: "#00D4AA" }} />
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "center", color: "#5A6478", fontSize: 10, borderBottom: "1px solid rgba(255,255,255,0.03)" }}>{rowIdx + 1}</td>
                        {activeMappings.map(m => {
                          const val = row[m.colIdx] || "";
                          const isEditing = editingCell?.row === rowIdx && editingCell?.col === m.colIdx;
                          return (
                            <td key={m.colIdx} style={{ padding: "4px 10px", borderBottom: "1px solid rgba(255,255,255,0.03)", color: "#F0F2F5", maxWidth: 200, cursor: "text" }}
                              onClick={() => !isExcluded && setEditingCell({ row: rowIdx, col: m.colIdx })}>
                              {isEditing ? (
                                <input autoFocus defaultValue={val}
                                  style={{ ...inputStyle, padding: "4px 8px", fontSize: 12, width: "100%" }}
                                  onBlur={e => handleCellEdit(rowIdx, m.colIdx, e.target.value)}
                                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditingCell(null); }} />
                              ) : (
                                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>{val || <span style={{ color: "#3A4050" }}>&mdash;</span>}</span>
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
          </div>

          {/* Action bar */}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, paddingBottom: 40 }}>
            <button onClick={reset} style={{ fontSize: 12, fontWeight: 600, color: "#8B95A8", background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, padding: "10px 20px", cursor: "pointer" }}>
              Cancel
            </button>
            <button onClick={handleCreate}
              disabled={includedRows.length === 0 || activeMappings.length === 0}
              style={{
                fontSize: 12, fontWeight: 700, color: "#0A0E17", border: "none", borderRadius: 10, padding: "10px 24px", cursor: "pointer",
                background: includedRows.length > 0 ? "linear-gradient(135deg, #00D4AA, #00B894)" : "rgba(255,255,255,0.06)",
                opacity: includedRows.length > 0 && activeMappings.length > 0 ? 1 : 0.4,
              }}>
              Create {includedRows.length} Load{includedRows.length !== 1 ? "s" : ""}
            </button>
          </div>
        </div>
      )}

      {/* ═══ STEP 3: Results ═══ */}
      {step === 3 && (
        <div className="dash-panel" style={{ padding: 32, textAlign: "center" }}>
          {creating ? (
            <div>
              <div style={{ width: 40, height: 40, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 16px" }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: "#F0F2F5" }}>Creating loads...</div>
            </div>
          ) : result?.error ? (
            <div>
              <div style={{ fontSize: 32, marginBottom: 12 }}>!</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#EF4444", marginBottom: 8 }}>Error</div>
              <div style={{ fontSize: 12, color: "#8B95A8" }}>{result.error}</div>
            </div>
          ) : result ? (
            <div>
              <div style={{ fontSize: 36, marginBottom: 8 }}>
                {result.errors?.length > 0 ? "!" : result.created?.length > 0 ? "" : ""}
              </div>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", marginBottom: 4 }}>{result.summary}</div>

              <div style={{ display: "flex", justifyContent: "center", gap: 16, marginTop: 20, marginBottom: 24 }}>
                {result.created?.length > 0 && (
                  <div style={{ background: "rgba(0,212,170,0.08)", border: "1px solid rgba(0,212,170,0.15)", borderRadius: 12, padding: "14px 24px" }}>
                    <div style={{ fontSize: 24, fontWeight: 800, color: "#00D4AA" }}>{result.created.length}</div>
                    <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase" }}>Created</div>
                  </div>
                )}
                {result.skipped?.length > 0 && (
                  <div style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.15)", borderRadius: 12, padding: "14px 24px" }}>
                    <div style={{ fontSize: 24, fontWeight: 800, color: "#F59E0B" }}>{result.skipped.length}</div>
                    <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase" }}>Skipped</div>
                  </div>
                )}
                {result.errors?.length > 0 && (
                  <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)", borderRadius: 12, padding: "14px 24px" }}>
                    <div style={{ fontSize: 24, fontWeight: 800, color: "#EF4444" }}>{result.errors.length}</div>
                    <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase" }}>Errors</div>
                  </div>
                )}
              </div>

              {/* Detail lists */}
              {result.skipped?.length > 0 && (
                <div style={{ textAlign: "left", marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#F59E0B", marginBottom: 4 }}>Skipped:</div>
                  {result.skipped.map((s: any, i: number) => (
                    <div key={i} style={{ fontSize: 11, color: "#8B95A8", paddingLeft: 8 }}>{s.efj} &mdash; {s.reason}</div>
                  ))}
                </div>
              )}
              {result.errors?.length > 0 && (
                <div style={{ textAlign: "left", marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#EF4444", marginBottom: 4 }}>Errors:</div>
                  {result.errors.map((e: any, i: number) => (
                    <div key={i} style={{ fontSize: 11, color: "#8B95A8", paddingLeft: 8 }}>{e.efj} &mdash; {e.reason}</div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          <button onClick={reset}
            style={{ marginTop: 16, fontSize: 12, fontWeight: 700, color: "#0A0E17", border: "none", borderRadius: 10, padding: "10px 24px", cursor: "pointer", background: "linear-gradient(135deg, #00D4AA, #00B894)" }}>
            Upload Another
          </button>
        </div>
      )}
    </div>
  );
}
