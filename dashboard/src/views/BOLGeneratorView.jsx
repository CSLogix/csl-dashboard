import { useState, useEffect, useRef } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';

// ═══════════════════════════════════════════════════════════════
// BOL GENERATOR VIEW
// ═══════════════════════════════════════════════════════════════
export default function BOLGeneratorView({ loaded }) {
  const [accounts, setAccounts] = useState([]);
  const [account, setAccount] = useState("");
  const [inputMode, setInputMode] = useState("upload"); // "upload" | "paste" | "manual" | "screenshot"
  const [file, setFile] = useState(null);
  const [pasteText, setPasteText] = useState("");
  const [previewRows, setPreviewRows] = useState(null);
  const [previewHeaders, setPreviewHeaders] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState(null);
  const [messageType, setMessageType] = useState("success");
  const fileRef = useRef(null);
  const imgRef = useRef(null);
  // Manual entry state
  const [manualRows, setManualRows] = useState([{}]);
  // Screenshot OCR state
  const [extracting, setExtracting] = useState(false);
  const [screenshotPreview, setScreenshotPreview] = useState(null);

  // Fetch available accounts
  useEffect(() => {
    apiFetch(`${API_BASE}/api/bol/accounts`).then(r => r.json()).then(data => {
      setAccounts(data.accounts || []);
      if (data.accounts?.length) setAccount(data.accounts[0].key);
    }).catch(() => {});
  }, []);

  const selectedAccount = accounts.find(a => a.key === account);

  // Parse CSV text into headers + rows
  const parseCSV = (text) => {
    const lines = text.split(/\r?\n/).filter(l => l.trim());
    if (lines.length < 2) return { headers: [], rows: [] };
    // Handle quoted CSV fields
    const parseLine = (line) => {
      const result = [];
      let current = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') { inQuotes = !inQuotes; }
        else if ((ch === ',' || ch === '\t') && !inQuotes) { result.push(current.trim()); current = ""; }
        else { current += ch; }
      }
      result.push(current.trim());
      return result;
    };
    const headers = parseLine(lines[0]);
    const rows = lines.slice(1).map(line => {
      const vals = parseLine(line);
      const obj = {};
      headers.forEach((h, i) => obj[h] = vals[i] || "");
      return obj;
    });
    return { headers, rows };
  };

  // Handle file selection
  const handleFileSelect = (f) => {
    if (!f) return;
    setFile(f);
    setMessage(null);
    if (f.name.toLowerCase().endsWith('.csv')) {
      const reader = new FileReader();
      reader.onload = (e) => {
        const { headers, rows } = parseCSV(e.target.result);
        setPreviewHeaders(headers);
        setPreviewRows(rows);
      };
      reader.readAsText(f);
    } else {
      // XLSX — show file info, no client-side preview
      setPreviewHeaders([]);
      setPreviewRows([{ _info: `${f.name} (${(f.size / 1024).toFixed(1)} KB)` }]);
    }
  };

  // Handle paste
  const handlePasteChange = (text) => {
    setPasteText(text);
    setMessage(null);
    if (text.trim()) {
      const { headers, rows } = parseCSV(text);
      setPreviewHeaders(headers);
      setPreviewRows(rows);
    } else {
      setPreviewHeaders([]);
      setPreviewRows(null);
    }
  };

  // Handle drop
  const handleDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    const f = e.dataTransfer?.files?.[0];
    if (f && /\.(csv|xlsx?)$/i.test(f.name)) handleFileSelect(f);
  };

  // Generate BOLs
  const handleGenerate = async () => {
    setGenerating(true); setMessage(null);
    const fd = new FormData();
    fd.append("account", account);

    if (inputMode === "manual") {
      // Convert manual rows to CSV
      const cols = selectedAccount?.columns || [];
      const header = cols.map(c => c.includes(',') ? `"${c}"` : c).join(',');
      const dataRows = manualRows
        .filter(r => Object.values(r).some(v => v && v.trim()))
        .map(r => cols.map(c => { const v = (r[c] || "").trim(); return v.includes(',') ? `"${v}"` : v; }).join(','));
      if (dataRows.length === 0) { setMessage("No data entered"); setMessageType("error"); setGenerating(false); return; }
      const csvContent = [header, ...dataRows].join('\n');
      const blob = new Blob([csvContent], { type: "text/csv" });
      fd.append("file", blob, "manual_entry.csv");
    } else if (inputMode === "paste" && pasteText.trim()) {
      // Convert pasted TSV/CSV to CSV blob
      const lines = pasteText.split(/\r?\n/).filter(l => l.trim());
      const csvContent = lines.map(line => {
        // If tab-separated, convert to CSV
        if (line.includes('\t')) {
          return line.split('\t').map(cell => {
            const c = cell.trim();
            return c.includes(',') ? `"${c}"` : c;
          }).join(',');
        }
        return line;
      }).join('\n');
      const blob = new Blob([csvContent], { type: "text/csv" });
      fd.append("file", blob, "pasted_data.csv");
    } else if (file) {
      fd.append("file", file);
    } else {
      setMessage("No data to generate from");
      setMessageType("error");
      setGenerating(false);
      return;
    }

    try {
      const res = await apiFetch(`${API_BASE}/api/bol/generate`, { method: "POST", body: fd });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const disposition = res.headers.get("content-disposition") || "";
        const fnMatch = disposition.match(/filename="?([^"]+)"?/);
        a.download = fnMatch ? fnMatch[1] : "BOLs.zip";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        const count = previewRows?.filter(r => !r._info)?.length || "?";
        setMessage(`Generated ${count} BOLs \u2014 downloading ZIP`);
        setMessageType("success");
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        setMessage(err.detail || `Generation failed (${res.status})`);
        setMessageType("error");
      }
    } catch (e) {
      setMessage("Generation error \u2014 check connection");
      setMessageType("error");
    }
    setGenerating(false);
  };

  // Handle screenshot upload + OCR extraction
  const handleScreenshot = async (f) => {
    if (!f) return;
    setMessage(null);
    // Show image preview
    const reader = new FileReader();
    reader.onload = (e) => setScreenshotPreview(e.target.result);
    reader.readAsDataURL(f);
    // Send to OCR endpoint
    setExtracting(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await apiFetch(`${API_BASE}/api/bol/extract`, { method: "POST", body: fd });
      if (res.ok) {
        const data = await res.json();
        // Parse OCR lines into the paste textarea for user to review/edit
        const ocrText = (data.lines || []).join("\n") || data.raw_text || "";
        setInputMode("paste");
        setPasteText(ocrText);
        if (ocrText.trim()) {
          const { headers, rows } = parseCSV(ocrText);
          setPreviewHeaders(headers);
          setPreviewRows(rows);
        }
        setMessage(`Extracted ${data.line_count || 0} lines \u2014 review and adjust below`);
        setMessageType("success");
      } else {
        const err = await res.json().catch(() => ({ detail: "OCR failed" }));
        setMessage(err.detail || "Extraction failed");
        setMessageType("error");
      }
    } catch {
      setMessage("Extraction error \u2014 check connection");
      setMessageType("error");
    }
    setExtracting(false);
  };

  // Manual entry helpers
  const manualCols = selectedAccount?.columns || [];
  const updateManualRow = (idx, col, val) => {
    setManualRows(prev => prev.map((r, i) => i === idx ? { ...r, [col]: val } : r));
  };
  const addManualRow = () => setManualRows(prev => [...prev, {}]);
  const removeManualRow = (idx) => setManualRows(prev => prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev);
  const duplicateManualRow = (idx) => setManualRows(prev => {
    const copy = { ...prev[idx] };
    const arr = [...prev];
    arr.splice(idx + 1, 0, copy);
    return arr;
  });

  // Sync manual rows to preview
  useEffect(() => {
    if (inputMode === "manual" && manualCols.length > 0) {
      const filled = manualRows.filter(r => Object.values(r).some(v => v && v.trim()));
      if (filled.length > 0) {
        setPreviewHeaders(manualCols);
        setPreviewRows(filled);
      } else {
        setPreviewRows(null);
        setPreviewHeaders([]);
      }
    }
  }, [manualRows, inputMode]);

  // Reset
  const handleClear = () => {
    setFile(null);
    setPasteText("");
    setPreviewRows(null);
    setPreviewHeaders([]);
    setMessage(null);
    setManualRows([{}]);
    setScreenshotPreview(null);
    if (fileRef.current) fileRef.current.value = "";
    if (imgRef.current) imgRef.current.value = "";
  };

  const rowCount = inputMode === "manual"
    ? manualRows.filter(r => Object.values(r).some(v => v && v.trim())).length
    : (previewRows?.filter(r => !r._info)?.length || 0);
  const hasData = inputMode === "upload" ? !!file
    : inputMode === "paste" ? !!pasteText.trim()
    : inputMode === "manual" ? rowCount > 0
    : false;
  const displayCols = previewHeaders.length > 0 ? previewHeaders : (selectedAccount?.columns || []);

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      {/* Title */}
      <div style={{ padding: "24px 0 16px" }}>
        <h2 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>BOL </span>
          <span style={{ color: "#00D4AA" }}>GENERATOR</span>
        </h2>
        <div style={{ fontSize: 12, color: "#5A6478", marginTop: 4, letterSpacing: "0.01em" }}>Upload CSV, paste data, enter manually, or extract from screenshot</div>
      </div>

      {/* Top grid: Input + Format Info */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        {/* Left: Account + Input */}
        <div className="dash-panel" style={{ padding: 20 }}>
          {/* Account selector */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 6, display: "block", textTransform: "uppercase" }}>Account</label>
            <select value={account} onChange={e => { setAccount(e.target.value); handleClear(); }}
              style={{ width: "100%", padding: "10px 14px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {accounts.map(a => <option key={a.key} value={a.key} style={{ background: "#0D1119" }}>{a.label}</option>)}
            </select>
          </div>

          {/* Input mode toggle */}
          <div style={{ display: "flex", gap: 2, marginBottom: 12, background: "#0D1119", borderRadius: 10, padding: 3, width: "fit-content", flexWrap: "wrap" }}>
            {[
              { key: "upload", label: "Upload" },
              { key: "paste", label: "Paste" },
              { key: "manual", label: "Manual" },
              { key: "screenshot", label: "Screenshot" },
            ].map(m => (
              <button key={m.key} onClick={() => { setInputMode(m.key); if (m.key !== "paste") handleClear(); }}
                style={{ padding: "5px 12px", borderRadius: 5, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                  background: inputMode === m.key ? "#1E2738" : "transparent", color: inputMode === m.key ? "#F0F2F5" : "#8B95A8" }}>{m.label}</button>
            ))}
          </div>

          {/* Upload zone */}
          {inputMode === "upload" && (
            <div style={{ border: "2px dashed rgba(255,255,255,0.08)", borderRadius: 12, padding: 20, textAlign: "center", cursor: "pointer", minHeight: 100, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", transition: "border-color 0.2s" }}
              onClick={() => fileRef.current?.click()}
              onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={handleDrop}>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }}
                onChange={e => { if (e.target.files[0]) handleFileSelect(e.target.files[0]); e.target.value = ""; }} />
              {file ? (
                <>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#00D4AA" }}>{file.name}</div>
                  <div style={{ fontSize: 11, color: "#5A6478", marginTop: 4 }}>{(file.size / 1024).toFixed(1)} KB {"\u2014"} {rowCount} row{rowCount !== 1 ? "s" : ""} detected</div>
                  <button onClick={(e) => { e.stopPropagation(); handleClear(); }}
                    style={{ marginTop: 8, padding: "4px 12px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#8B95A8", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Clear</button>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>{"\uD83D\uDCC4"}</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Drop CSV/XLSX or click to upload</div>
                  <div style={{ fontSize: 11, color: "#3D4557", marginTop: 4 }}>Piedra Solar pickup & delivery plan</div>
                </>
              )}
            </div>
          )}

          {/* Paste zone */}
          {inputMode === "paste" && (
            <div>
              <textarea
                value={pasteText}
                onChange={e => handlePasteChange(e.target.value)}
                placeholder={"Paste from Excel or Google Sheets here...\n\nHeaders should be on the first row.\nTab-separated or comma-separated both work."}
                style={{ width: "100%", minHeight: 120, padding: "12px 14px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "'JetBrains Mono', monospace", resize: "vertical", lineHeight: 1.6 }}
              />
              {pasteText.trim() && (
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                  <span style={{ fontSize: 11, color: "#5A6478" }}>{rowCount} row{rowCount !== 1 ? "s" : ""} detected</span>
                  <button onClick={handleClear}
                    style={{ padding: "3px 10px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#8B95A8", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Clear</button>
                </div>
              )}
            </div>
          )}

          {/* Manual entry */}
          {inputMode === "manual" && manualCols.length > 0 && (
            <div style={{ maxHeight: 320, overflow: "auto" }}>
              {manualRows.map((row, ri) => (
                <div key={ri} style={{ marginBottom: 10, padding: "10px 12px", background: "rgba(255,255,255,0.02)", borderRadius: 10, border: "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#00D4AA", letterSpacing: "1px" }}>BOL {ri + 1}</span>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={() => duplicateManualRow(ri)} title="Duplicate"
                        style={{ padding: "2px 8px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4, color: "#8B95A8", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Copy</button>
                      {manualRows.length > 1 && (
                        <button onClick={() => removeManualRow(ri)} title="Remove"
                          style={{ padding: "2px 8px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 4, color: "#ef4444", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>X</button>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                    {manualCols.map(col => (
                      <div key={col}>
                        <label style={{ fontSize: 8, fontWeight: 600, color: "#5A6478", letterSpacing: "0.5px", marginBottom: 2, display: "block" }}>{col}</label>
                        <input value={row[col] || ""} onChange={e => updateManualRow(ri, col, e.target.value)}
                          placeholder={col}
                          style={{ width: "100%", padding: "6px 10px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "'JetBrains Mono', monospace" }} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <button onClick={addManualRow}
                style={{ width: "100%", padding: "8px", background: "rgba(0,212,170,0.06)", border: "1px dashed rgba(0,212,170,0.2)", borderRadius: 8, color: "#00D4AA", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                + Add Row
              </button>
            </div>
          )}

          {/* Screenshot upload */}
          {inputMode === "screenshot" && (
            <div>
              <div style={{ border: "2px dashed rgba(255,255,255,0.08)", borderRadius: 12, padding: 20, textAlign: "center", cursor: "pointer", minHeight: 100, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}
                onClick={() => imgRef.current?.click()}>
                <input ref={imgRef} type="file" accept="image/*" style={{ display: "none" }}
                  onChange={e => { if (e.target.files[0]) handleScreenshot(e.target.files[0]); e.target.value = ""; }} />
                {extracting ? (
                  <div style={{ textAlign: "center" }}>
                    <div style={{ width: 24, height: 24, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 10px" }} />
                    <div style={{ fontSize: 12, color: "#00D4AA", fontWeight: 600 }}>Extracting text from image...</div>
                  </div>
                ) : screenshotPreview ? (
                  <>
                    <img src={screenshotPreview} alt="Screenshot" style={{ maxWidth: "100%", maxHeight: 150, borderRadius: 8, marginBottom: 8, opacity: 0.8 }} />
                    <div style={{ fontSize: 11, color: "#5A6478" }}>Click to upload a different image</div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>{"\uD83D\uDCF7"}</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Upload a screenshot</div>
                    <div style={{ fontSize: 11, color: "#3D4557", marginTop: 4 }}>Image of a spreadsheet or delivery plan</div>
                  </>
                )}
              </div>
              {screenshotPreview && !extracting && (
                <div style={{ fontSize: 11, color: "#5A6478", marginTop: 8, lineHeight: 1.5 }}>
                  OCR extracted text will appear in the Paste tab for review. Adjust column alignment as needed before generating.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Expected Format */}
        <div className="dash-panel" style={{ padding: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 12, textTransform: "uppercase" }}>Expected CSV Columns</div>
          {selectedAccount ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {selectedAccount.columns.map((col, i) => {
                const isRequired = (selectedAccount.required_columns || selectedAccount.columns || []).includes(col);
                return (
                  <div key={col} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: isRequired ? "#00D4AA" : "#2A3348", flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color: isRequired ? "#F0F2F5" : "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{col}</span>
                    {isRequired && <span style={{ fontSize: 8, color: "#00D4AA", fontWeight: 700, letterSpacing: "0.5px" }}>REQUIRED</span>}
                  </div>
                );
              })}
              {(selectedAccount.combined_columns || []).length > 0 && (
                <div style={{ marginTop: 6, padding: "6px 10px", background: "rgba(96,165,250,0.04)", borderRadius: 8, border: "1px solid rgba(96,165,250,0.1)" }}>
                  <div style={{ fontSize: 8, fontWeight: 700, color: "#60a5fa", letterSpacing: "0.5px", marginBottom: 4 }}>COMBINED COLUMNS</div>
                  {selectedAccount.combined_columns.map(cc => (
                    <div key={cc.name} style={{ fontSize: 11, color: "#8B95A8", marginBottom: 2 }}>
                      <span style={{ color: "#C8D0DC", fontWeight: 600 }}>{cc.name}</span> = {cc.sources.join(" + ")}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 11, color: "#5A6478" }}>Select an account to see expected columns</div>
          )}
        </div>
      </div>

      {/* Preview Table */}
      {previewRows && previewRows.length > 0 && !previewRows[0]._info && (
        <div className="dash-panel" style={{ padding: 16, marginBottom: 14, overflowX: "auto" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 10, textTransform: "uppercase" }}>
            Preview ({previewRows.length} row{previewRows.length !== 1 ? "s" : ""})
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr>
                {displayCols.map(h => (
                  <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#5A6478", fontSize: 8, textTransform: "uppercase", letterSpacing: "0.5px", borderBottom: "1px solid rgba(255,255,255,0.06)", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewRows.slice(0, 10).map((row, ri) => (
                <tr key={ri} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                  {displayCols.map(h => (
                    <td key={h} style={{ padding: "5px 10px", color: "#C8D0DC", fontFamily: "'JetBrains Mono', monospace", whiteSpace: "nowrap" }}>{row[h] || ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {previewRows.length > 10 && (
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 8, textAlign: "center" }}>
              Showing 10 of {previewRows.length} rows
            </div>
          )}
        </div>
      )}

      {/* File info for non-CSV uploads */}
      {previewRows && previewRows.length > 0 && previewRows[0]._info && (
        <div className="dash-panel" style={{ padding: 16, marginBottom: 14 }}>
          <div style={{ fontSize: 11, color: "#8B95A8" }}>{previewRows[0]._info}</div>
        </div>
      )}

      {/* Generate Button + Message */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={handleGenerate} disabled={generating || !hasData || !account}
          style={{ padding: "10px 28px", borderRadius: 10, border: "none", background: hasData ? "linear-gradient(135deg, #00D4AA, #00B894)" : "rgba(255,255,255,0.04)", color: hasData ? "#0A0F1C" : "#5A6478", fontSize: 13, fontWeight: 700, cursor: hasData ? "pointer" : "default", fontFamily: "inherit", opacity: generating ? 0.6 : 1, transition: "all 0.2s ease" }}>
          {generating ? "Generating..." : `Generate ${rowCount > 0 ? rowCount + " " : ""}BOL${rowCount !== 1 ? "s" : ""}`}
        </button>
        {message && (
          <div style={{ fontSize: 12, fontWeight: 600, color: messageType === "success" ? "#00D4AA" : "#ef4444", animation: "fade-in 0.3s ease" }}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
}
