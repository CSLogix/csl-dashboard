import { useState, useEffect, useRef, useCallback } from "react";
import { Z } from "../helpers/constants";

export default function AskAIOverlay({ open, onClose, API_BASE, apiFetchFn, initialQuery, onConsumeInitialQuery, initialFiles, onConsumeInitialFiles, onBulkCreated }) {
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const fileInputRef = useRef(null);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [dragOverBody, setDragOverBody] = useState(false);

  useEffect(() => { if (open && inputRef.current) setTimeout(() => inputRef.current.focus(), 80); }, [open]);

  // Auto-send initial query (e.g. from drag-drop)
  useEffect(() => {
    if (open && initialQuery && !loading) {
      setTimeout(() => askAI(initialQuery), 150);
      if (onConsumeInitialQuery) onConsumeInitialQuery();
    }
  }, [open, initialQuery]);

  // Handle initial files (e.g. from drag onto Ask AI button)
  useEffect(() => {
    if (open && initialFiles && initialFiles.length > 0) {
      setAttachedFiles(initialFiles);
      if (onConsumeInitialFiles) onConsumeInitialFiles();
      // Auto-send with default prompt
      setTimeout(() => askAI("", initialFiles), 300);
    }
  }, [open, initialFiles]);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, loading]);

  const askAI = useCallback(async (q, filesOverride) => {
    const files = filesOverride || attachedFiles;
    const hasFiles = files && files.length > 0;
    if (!q.trim() && !hasFiles) return;
    if (loading) return;

    const displayText = q.trim() || (hasFiles ? `📎 ${files.map(f => f.name).join(", ")}` : "");
    const userMsg = { role: "user", text: displayText, files: hasFiles ? files.map(f => ({ name: f.name, size: f.size })) : undefined };
    setMessages(prev => [...prev, userMsg]);
    setQuery("");
    setAttachedFiles([]);
    setLoading(true);
    try {
      let res;
      if (hasFiles) {
        // Multipart upload
        const fd = new FormData();
        fd.append("file", files[0]); // primary file
        fd.append("question", q.trim());
        res = await apiFetchFn(`${API_BASE}/api/ask-ai/upload`, {
          method: "POST",
          body: fd,
        });
      } else {
        res = await apiFetchFn(`${API_BASE}/api/ask-ai`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q.trim() }),
        });
      }
      const data = await res.json();
      const aiMsg = { role: "ai", text: data.answer || data.error || "No response", tool_calls: data.tool_calls || [], sources: data.sources || [] };
      setMessages(prev => [...prev, aiMsg]);
      // If bulk_create_loads was called, notify parent to refresh
      if (data.tool_calls && data.tool_calls.some(tc => tc.tool === "bulk_create_loads") && onBulkCreated) {
        onBulkCreated();
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: "ai", text: `Error: ${e.message}` }]);
    }
    setLoading(false);
  }, [loading, API_BASE, apiFetchFn, attachedFiles, onBulkCreated]);

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askAI(query); }
    if (e.key === "Escape") onClose();
  };

  const quickActions = [
    { label: "Who covers Savannah?", q: "Which carriers cover Savannah? Show me their capabilities." },
    { label: "Rate for Houston → Dallas", q: "What do we typically pay for Houston to Dallas?" },
    { label: "Status of EFJ", q: "What is the status of EFJ" },
    { label: "Add new load", q: "I need to create a new load" },
  ];

  // Render markdown-like text (bold, tables, lists)
  const renderText = (text) => {
    if (!text) return null;
    const lines = text.split("\n");
    const elements = [];
    let tableRows = [];
    let inTable = false;

    const flushTable = () => {
      if (tableRows.length > 0) {
        const headers = tableRows[0];
        const dataRows = tableRows.slice(1).filter(r => !r.every(c => /^[-:]+$/.test(c.trim())));
        elements.push(
          <div key={`tbl-${elements.length}`} style={{ overflowX: "auto", margin: "8px 0" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr>{headers.map((h, i) => <th key={i} style={{ padding: "6px 10px", textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.1)", color: "#00D4AA", fontWeight: 700, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.5px" }}>{h.trim()}</th>)}</tr>
              </thead>
              <tbody>
                {dataRows.map((row, ri) => (
                  <tr key={ri} style={{ background: ri % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)" }}>
                    {row.map((cell, ci) => <td key={ci} style={{ padding: "5px 10px", borderBottom: "1px solid rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.8)", fontSize: 11 }}>{cell.trim()}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        tableRows = [];
      }
      inTable = false;
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes("|") && line.trim().startsWith("|")) {
        inTable = true;
        const cells = line.split("|").slice(1, -1);
        tableRows.push(cells);
        continue;
      }
      if (inTable) flushTable();

      if (line.startsWith("### ")) {
        elements.push(<div key={i} style={{ fontWeight: 800, fontSize: 13, color: "#00D4AA", marginTop: 10, marginBottom: 4 }}>{line.slice(4)}</div>);
      } else if (line.startsWith("## ")) {
        elements.push(<div key={i} style={{ fontWeight: 800, fontSize: 14, color: "#F0F2F5", marginTop: 12, marginBottom: 4 }}>{line.slice(3)}</div>);
      } else if (line.startsWith("**") && line.endsWith("**")) {
        elements.push(<div key={i} style={{ fontWeight: 700, color: "#F0F2F5", marginTop: 6 }}>{line.slice(2, -2)}</div>);
      } else if (line.startsWith("- ") || line.startsWith("• ")) {
        elements.push(<div key={i} style={{ paddingLeft: 12, color: "rgba(255,255,255,0.8)", fontSize: 12, lineHeight: 1.6 }}>• {formatBold(line.slice(2))}</div>);
      } else if (line.trim()) {
        elements.push(<div key={i} style={{ color: "rgba(255,255,255,0.8)", fontSize: 12, lineHeight: 1.6, marginBottom: 2 }}>{formatBold(line)}</div>);
      } else {
        elements.push(<div key={i} style={{ height: 6 }} />);
      }
    }
    if (inTable) flushTable();
    return elements;
  };

  const formatBold = (text) => {
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((p, i) => p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} style={{ color: "#F0F2F5", fontWeight: 700 }}>{p.slice(2, -2)}</strong>
      : p
    );
  };

  if (!open) return null;

  return (
    <div role="presentation" onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(6px)", zIndex: Z.palette + 10, display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "8vh" }}>
      <div role="dialog" aria-modal="true" aria-label="Ask AI"
        onClick={e => e.stopPropagation()}
        onDragOver={e => { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = "copy"; setDragOverBody(true); }}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOverBody(false); }}
        onDrop={e => {
          e.preventDefault(); e.stopPropagation(); setDragOverBody(false);
          const files = Array.from(e.dataTransfer.files || []);
          if (files.length > 0) setAttachedFiles(prev => [...prev, ...files]);
        }}
        style={{ width: 640, maxHeight: "78vh", background: "#0C1017", border: dragOverBody ? "2px solid #00D4AA" : "1px solid rgba(0,212,170,0.25)", borderRadius: 16, overflow: "hidden", boxShadow: dragOverBody ? "0 0 40px rgba(0,212,170,0.3), 0 20px 60px rgba(0,0,0,0.6)" : "0 0 60px rgba(0,212,170,0.12), 0 20px 60px rgba(0,0,0,0.6)", fontFamily: "'Plus Jakarta Sans', sans-serif", animation: "fade-in 0.15s ease", display: "flex", flexDirection: "column", transition: "border 0.15s, box-shadow 0.15s" }}>

        {/* Header */}
        <div style={{ padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 16 }}>✨</span>
            <span style={{ fontWeight: 800, fontSize: 14, color: "#F0F2F5" }}>Ask AI</span>
            <span style={{ fontSize: 9, color: "rgba(255,255,255,0.25)", background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 4 }}>Claude • Tool-Calling</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {messages.length > 0 && (
              <button onClick={() => setMessages([])} style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, padding: "3px 8px", cursor: "pointer" }}>Clear</button>
            )}
            <span onClick={onClose} style={{ cursor: "pointer", color: "rgba(255,255,255,0.3)", fontSize: 9, background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 4 }}>ESC</span>
          </div>
        </div>

        {/* Messages area */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "12px 20px", minHeight: 120, maxHeight: "calc(78vh - 160px)" }}>
          {messages.length === 0 && !loading && (
            <div style={{ textAlign: "center", padding: "30px 0" }}>
              <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.5 }}>🔍</div>
              <div style={{ fontSize: 13, color: "rgba(255,255,255,0.5)", fontWeight: 600, marginBottom: 4 }}>Ask anything about your loads, carriers, or rates</div>
              <div style={{ fontSize: 11, color: "rgba(255,255,255,0.25)", marginBottom: 16 }}>Powered by Claude with live database access</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                {quickActions.map(qa => (
                  <button key={qa.label} onClick={() => askAI(qa.q)}
                    style={{ padding: "6px 12px", borderRadius: 20, border: "1px solid rgba(0,212,170,0.2)", background: "rgba(0,212,170,0.06)", color: "#00D4AA", fontSize: 11, fontWeight: 600, cursor: "pointer", transition: "all 0.15s", fontFamily: "inherit" }}
                    onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,212,170,0.15)"; e.currentTarget.style.borderColor = "rgba(0,212,170,0.4)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,212,170,0.06)"; e.currentTarget.style.borderColor = "rgba(0,212,170,0.2)"; }}>
                    {qa.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} style={{ marginBottom: 12, display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>
              {msg.role === "user" ? (
                <div style={{ background: "rgba(0,212,170,0.1)", border: "1px solid rgba(0,212,170,0.15)", borderRadius: 12, padding: "8px 14px", maxWidth: "85%", color: "rgba(255,255,255,0.9)", fontSize: 12, lineHeight: 1.5 }}>
                  {msg.files && msg.files.length > 0 && (
                    <div style={{ marginBottom: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {msg.files.map((f, fi) => (
                        <span key={fi} style={{ fontSize: 9, padding: "2px 6px", borderRadius: 6, background: "rgba(0,212,170,0.15)", border: "1px solid rgba(0,212,170,0.25)" }}>📎 {f.name}</span>
                      ))}
                    </div>
                  )}
                  {msg.text}
                </div>
              ) : (
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 12, padding: "12px 16px", maxWidth: "95%", width: "100%" }}>
                  {msg.tool_calls && msg.tool_calls.length > 0 && (
                    <div style={{ marginBottom: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {msg.tool_calls.map((tc, ti) => (
                        <span key={ti} style={{ fontSize: 9, color: "#a78bfa", background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.15)", padding: "2px 8px", borderRadius: 10 }}>
                          🔧 {tc.tool || tc.name || (typeof tc === "string" ? tc : JSON.stringify(tc))}
                        </span>
                      ))}
                    </div>
                  )}
                  {renderText(msg.text)}
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: 8, fontSize: 9, color: "rgba(255,255,255,0.2)" }}>Sources: {msg.sources.join(", ")}</div>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0" }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#00D4AA", animation: "pulse 1s infinite" }} />
              <span style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>Thinking...</span>
            </div>
          )}
        </div>

        {/* Attached files bar */}
        {attachedFiles.length > 0 && (
          <div style={{ padding: "6px 20px", borderTop: "1px solid rgba(255,255,255,0.06)", display: "flex", flexWrap: "wrap", gap: 6 }}>
            {attachedFiles.map((f, i) => (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", borderRadius: 8, background: "rgba(0,212,170,0.1)", border: "1px solid rgba(0,212,170,0.2)", fontSize: 10, color: "#00D4AA" }}>
                📎 {f.name} <span style={{ opacity: 0.5 }}>({(f.size / 1024).toFixed(0)}KB)</span>
                <span onClick={() => setAttachedFiles(prev => prev.filter((_, j) => j !== i))} style={{ cursor: "pointer", marginLeft: 2, opacity: 0.6 }}>✕</span>
              </span>
            ))}
          </div>
        )}

        {/* Input area */}
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: "12px 20px", display: "flex", gap: 8, alignItems: "flex-end" }}>
          <input ref={fileInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.xls,.xlsx,.csv,.tsv,.eml,.msg,.txt" style={{ display: "none" }}
            onChange={e => { if (e.target.files?.[0]) { setAttachedFiles(prev => [...prev, e.target.files[0]]); e.target.value = ""; } }} />
          <button onClick={() => fileInputRef.current?.click()} title="Attach file (PDF, image, spreadsheet)"
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.4)", fontSize: 14, cursor: "pointer", flexShrink: 0, lineHeight: 1, transition: "all 0.15s" }}
            onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,212,170,0.1)"; e.currentTarget.style.color = "#00D4AA"; e.currentTarget.style.borderColor = "rgba(0,212,170,0.3)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "rgba(255,255,255,0.4)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)"; }}>
            📎
          </button>
          <textarea ref={inputRef} value={query} onChange={e => setQuery(e.target.value)} onKeyDown={handleKey}
            placeholder={attachedFiles.length > 0 ? "Ask about the attached file, or press Enter to analyze..." : "Ask about carriers, rates, load status, or drag a PDF here..."}
            rows={1}
            style={{ flex: 1, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, padding: "10px 14px", color: "rgba(255,255,255,0.9)", fontSize: 12, fontFamily: "'Plus Jakarta Sans', sans-serif", outline: "none", resize: "none", lineHeight: 1.5, minHeight: 38, maxHeight: 100 }}
            onFocus={e => e.target.style.borderColor = "rgba(0,212,170,0.3)"}
            onBlur={e => e.target.style.borderColor = "rgba(255,255,255,0.08)"} />
          <button onClick={() => askAI(query)} disabled={(!query.trim() && attachedFiles.length === 0) || loading}
            style={{ padding: "10px 18px", borderRadius: 10, border: "none", background: (query.trim() || attachedFiles.length > 0) && !loading ? "linear-gradient(135deg, #00D4AA, #00B894)" : "rgba(255,255,255,0.06)", color: (query.trim() || attachedFiles.length > 0) && !loading ? "#0A0F1C" : "rgba(255,255,255,0.2)", fontSize: 12, fontWeight: 700, cursor: (query.trim() || attachedFiles.length > 0) && !loading ? "pointer" : "default", fontFamily: "inherit", transition: "all 0.15s", flexShrink: 0 }}>
            {loading ? "..." : "Ask"}
          </button>
        </div>

        {/* Footer */}
        <div style={{ padding: "6px 20px 10px", display: "flex", justifyContent: "space-between", fontSize: 9, color: "rgba(255,255,255,0.15)" }}>
          <span>Enter to send · Shift+Enter for newline · 📎 to attach · ESC to close</span>
          <span>Ctrl+K to toggle</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// CLOCK DISPLAY — isolated to prevent full-tree re-render every 1s
// ═══════════════════════════════════════════════════════════════
