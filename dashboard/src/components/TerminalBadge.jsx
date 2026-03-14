import { parseTerminalNotes } from "../helpers";

export default function TerminalBadge({ notes }) {
  const t = parseTerminalNotes(notes);
  if (!t) return null;
  if (t.isReady) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "#22C55E18", color: "#22C55E", border: "1px solid #22C55E33", letterSpacing: "0.5px", fontFamily: "'JetBrains Mono', monospace" }}>READY</span>
        {t.loc && <span style={{ fontSize: 11, color: "#8B95A8" }}>{t.loc}</span>}
      </span>
    );
  }
  if (t.hasHolds) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3, flexWrap: "wrap" }}>
        {t.holds.map(h => (
          <span key={h} style={{ fontSize: 11, fontWeight: 700, padding: "2px 5px", borderRadius: 4, background: "#EF444418", color: "#F87171", border: "1px solid #EF444422", letterSpacing: "0.5px", fontFamily: "'JetBrains Mono', monospace" }}>{h}</span>
        ))}
        {t.loc && <span style={{ fontSize: 11, color: "#8B95A8", marginLeft: 2 }}>{t.loc === "In Yard" ? "Yard" : t.loc}</span>}
      </span>
    );
  }
  return <span style={{ fontSize: 11, color: "#6B7280", fontFamily: "'JetBrains Mono', monospace" }}>{t.loc || "In Transit"}</span>;
}
