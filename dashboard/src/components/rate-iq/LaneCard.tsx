import React, { useState } from 'react';
import { fmt, grad, MOVE_TYPE_STYLES } from './constants';
import LaneName from './LaneName';

/**
 * Render an interactive card summarizing a shipping lane with actions for quick quoting and move-type reclassification.
 *
 * @param {Object} props.lane - Lane data used to populate the card (e.g., origin_city, origin_state, dest_city, dest_state, port, destination, origin_zip, dest_zip, load_count, avg_rate, average, miles, trend_pct, move_type, carrier_count, bidirectional).
 * @param {Function} props.onClick - Handler invoked when the card is clicked.
 * @param {Function} [props.onQuickQuote] - Optional handler invoked when the "Quick Quote" button is clicked.
 * @param {Function} [props.onReclassify] - Optional handler invoked with a move type string when a new move type is selected from the picker.
 * @param {Array<string>} [props.rateIds] - Optional array of rate identifiers included in drag payloads.
 * @returns {JSX.Element} The rendered LaneCard element.
 */
export default function LaneCard({ lane, onClick, onQuickQuote, onReclassify, rateIds }) {
  const [hovered, setHovered] = useState(false);
  const [showMtPicker, setShowMtPicker] = useState(false);
  const volume = lane.load_count || 0;
  const mtStyle = MOVE_TYPE_STYLES[(lane.move_type || "dray").toLowerCase()] || MOVE_TYPE_STYLES.dray;
  const volTag = volume >= 20 ? { label: "High Volume", color: "#00D4AA", bg: "rgba(0,212,170,0.15)", border: "rgba(0,212,170,0.35)" }
    : volume >= 5 ? { label: "Active", color: "#3B82F6", bg: "rgba(59,130,246,0.15)", border: "rgba(59,130,246,0.35)" }
    : { label: "Low Volume", color: "#5A6478", bg: "rgba(90,100,120,0.08)", border: "rgba(90,100,120,0.15)" };
  const avgRate = lane.avg_rate || lane.average || 0;
  const miles = lane.miles || null;

  return (
    <div onClick={onClick} draggable className="glass" style={{ borderRadius: 12, padding: "18px 20px", cursor: "pointer", border: "1px solid rgba(255,255,255,0.10)", transition: "all 0.2s", position: "relative" }}
      onDragStart={e => { e.dataTransfer.setData("application/json", JSON.stringify({ port: lane.port || lane.origin_city, destination: lane.destination || lane.dest_city, rateIds: rateIds || [] })); e.dataTransfer.effectAllowed = "move"; }}
      onMouseEnter={e => { setHovered(true); e.currentTarget.style.borderColor = "rgba(0,212,170,0.25)"; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 0 20px rgba(0,212,170,0.08)"; }}
      onMouseLeave={e => { setHovered(false); e.currentTarget.style.borderColor = "rgba(255,255,255,0.10)"; e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5" }}>
            <LaneName city={lane.origin_city} state={lane.origin_state} raw={lane.port} citySize={15} />
            {" "}<span style={{ color: "#5A6478" }}>{lane.bidirectional ? "\u2194" : "\u2192"}</span>{" "}
            <LaneName city={lane.dest_city} state={lane.dest_state} raw={lane.destination} citySize={15} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
            <span style={{ fontSize: 11, color: "#5A6478" }}>{volume} rate{volume !== 1 ? "s" : ""} on file</span>
            {miles && <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{miles.toLocaleString()} mi</span>}
          </div>
          {(lane.origin_zip || lane.dest_zip) && (
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
              {lane.origin_zip || "\u2014"} {"\u2192"} {lane.dest_zip || "\u2014"}
            </div>
          )}
        </div>
        {avgRate > 0 && (
          <div style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, justifyContent: "flex-end" }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: "'tnum'" }}>{fmt(avgRate)}</div>
              {lane.trend_pct != null && Math.abs(lane.trend_pct) > 2 && (
                <span style={{ fontSize: 11, fontWeight: 700, color: lane.trend_pct > 0 ? "#f87171" : "#34d399" }}>
                  {lane.trend_pct > 0 ? "\u2191" : "\u2193"} {Math.abs(lane.trend_pct).toFixed(1)}%
                </span>
              )}
            </div>
            <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600 }}>avg rate</div>
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", gap: 6 }}>
          <span onClick={e => { e.stopPropagation(); if (onReclassify) setShowMtPicker(!showMtPicker); }}
            style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: mtStyle.bg, color: mtStyle.color, border: `1px solid ${mtStyle.border}`, cursor: onReclassify ? "pointer" : "default", position: "relative" }}
            title={onReclassify ? "Click to reclassify move type" : ""}>
            {mtStyle.label}
            {showMtPicker && onReclassify && (
              <div onClick={e => e.stopPropagation()} style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, zIndex: 60, background: "#151922", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 8px 24px rgba(0,0,0,0.5)", overflow: "hidden", minWidth: 100 }}>
                {["dray", "ftl", "transload"].filter(mt => mt !== (lane.move_type || "dray").toLowerCase()).map(mt => {
                  const s = MOVE_TYPE_STYLES[mt];
                  return (
                    <div key={mt} onClick={() => { onReclassify(mt); setShowMtPicker(false); }}
                      style={{ padding: "6px 14px", cursor: "pointer", fontSize: 11, fontWeight: 700, color: s.color, transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.05)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      {s.label}
                    </div>
                  );
                })}
              </div>
            )}
          </span>
          <span style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: volTag.bg, color: volTag.color, border: `1px solid ${volTag.border}` }}>
            {volTag.label}
          </span>
          {lane.carrier_count > 0 && (
            <span style={{ padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700, background: "rgba(255,255,255,0.04)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.08)" }}>
              {lane.carrier_count} carrier{lane.carrier_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        {hovered && (
          <div style={{ display: "flex", gap: 4 }}>
            <button onClick={e => { e.stopPropagation(); onQuickQuote && onQuickQuote(); }}
              style={{ padding: "3px 10px", borderRadius: 6, border: "none", background: grad, color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
              Quick Quote {"\u2192"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
