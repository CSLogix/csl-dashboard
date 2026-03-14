import { useState, useEffect, useRef, useMemo } from "react";
import { CMD_STATUS_COLORS, Z } from "../helpers/constants";
import { resolveStatusColor } from "../helpers/utils";

export default function CommandPalette({ open, query, setQuery, index, setIndex, shipments, onSelect, onClose }) {
  const inputRef = useRef(null);
  useEffect(() => { if (open && inputRef.current) setTimeout(() => inputRef.current.focus(), 50); }, [open]);

  const results = useMemo(() => {
    if (!query || query.length < 2) return [];
    const q = query.toLowerCase();
    return (Array.isArray(shipments) ? shipments : []).filter(s =>
      (s.efj || "").toLowerCase().includes(q) ||
      (s.container || "").toLowerCase().includes(q) ||
      (s.account || "").toLowerCase().includes(q) ||
      (s.carrier || "").toLowerCase().includes(q) ||
      (s.origin || "").toLowerCase().includes(q) ||
      (s.destination || "").toLowerCase().includes(q)
    ).slice(0, 8);
  }, [query, shipments]);

  useEffect(() => { setIndex(0); }, [results.length]);

  const handleKeyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex(i => Math.min(i + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex(i => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && results[index]) { onSelect(results[index]); onClose(); }
    else if (e.key === "Escape") { onClose(); }
  };

  if (!open) return null;

  const statusLabel = (s) => (s.rawStatus || s.status || "").toUpperCase().replace(/_/g, " ");
  const statusColor = (s) => CMD_STATUS_COLORS[s.status] || "#8B95A8";

  return (
    <div role="presentation" onClick={onClose} style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)", zIndex: Z.palette, display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "15vh" }}>
      <div role="dialog" aria-modal="true" aria-label="Search shipments"
        onClick={e => e.stopPropagation()} style={{ width: 560, background: "#0f1215", border: "1px solid #00b8d4", borderRadius: 12, overflow: "hidden", boxShadow: "0 0 40px rgba(0,184,212,0.15), 0 20px 60px rgba(0,0,0,0.5)", fontFamily: "'Plus Jakarta Sans', sans-serif", animation: "fade-in 0.15s ease" }}>
        {/* Search input */}
        <div style={{ display: "flex", alignItems: "center", padding: "14px 18px", borderBottom: "1px solid #1e2a30", gap: 10 }}>
          <span aria-hidden="true" style={{ color: "#00b8d4", fontSize: 13, fontWeight: 700, flexShrink: 0 }}>⌘F</span>
          <input ref={inputRef} type="text" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={handleKeyDown}
            aria-label="Search EFJ, container, customer"
            aria-autocomplete="list"
            aria-controls="cmdk-results"
            aria-activedescendant={results[index] ? `cmdk-result-${results[index].id}` : undefined}
            placeholder="Search EFJ, container, customer..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "rgba(255,255,255,0.9)", fontSize: 14, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.3px" }} />
          <span aria-hidden="true" style={{ color: "rgba(255,255,255,0.2)", fontSize: 11, background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 4, flexShrink: 0 }}>ESC</span>
        </div>
        {/* Results */}
        <div id="cmdk-results" role="listbox" aria-label="Search results" style={{ maxHeight: 340, overflowY: "auto" }}>
          {query.length >= 2 && results.length === 0 && (
            <div style={{ padding: "20px 18px", textAlign: "center", color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No results for "{query}"</div>
          )}
          {query.length < 2 && (
            <div style={{ padding: "20px 18px", textAlign: "center", color: "rgba(255,255,255,0.15)", fontSize: 11 }}>Type 2+ characters to search...</div>
          )}
          {results.map((s, i) => (
            <div key={s.id} id={`cmdk-result-${s.id}`} role="option" aria-selected={i === index}
              onClick={() => { onSelect(s); onClose(); }}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 18px", cursor: "pointer",
                background: i === index ? "rgba(0,184,212,0.08)" : "transparent",
                borderLeft: i === index ? "3px solid #00b8d4" : "3px solid transparent",
                transition: "background 0.1s" }}
              onMouseEnter={() => setIndex(i)}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                <span style={{ color: i === index ? "#00b8d4" : "rgba(255,255,255,0.6)", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", fontSize: 13, flexShrink: 0 }}>{s.loadNumber}</span>
                <span style={{ color: "rgba(255,255,255,0.25)", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.container}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, marginLeft: 12 }}>
                <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 11, whiteSpace: "nowrap" }}>{s.account}{s.destination ? ` · ${s.destination}` : ""}</span>
                <span style={{ background: `${statusColor(s)}20`, color: statusColor(s), padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>{statusLabel(s)}</span>
              </div>
            </div>
          ))}
        </div>
        {/* Footer */}
        <div style={{ padding: "8px 18px", borderTop: "1px solid #1e2a30", display: "flex", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 14, fontSize: 11, color: "rgba(255,255,255,0.18)" }}>
            <span>↑↓ Navigate</span><span>↵ Open</span><span>ESC Close</span>
          </div>
          <span style={{ fontSize: 11, color: "rgba(255,255,255,0.12)" }}>{results.length > 0 ? `${results.length} result${results.length !== 1 ? "s" : ""}` : ""}</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// ASK AI — Command palette overlay with Claude tool-calling
// ═══════════════════════════════════════════════════════════════
