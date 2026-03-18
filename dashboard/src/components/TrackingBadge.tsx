import { relativeTime } from "../helpers";

export default function TrackingBadge({ tracking, mpStatus, mpDisplayStatus, mpDisplayDetail, mpLastUpdated }) {
  const display = (mpDisplayStatus || "").trim();
  const raw = (mpStatus || tracking?.mpStatus || "").trim();
  const detail = (mpDisplayDetail || tracking?.mpDisplayDetail || "").trim();
  const lastUp = mpLastUpdated || tracking?.mpLastUpdated || "";

  const label = display || raw;
  if (!label) {
    if (!tracking) return <span style={{ fontSize: 11, color: "#5A6478", fontStyle: "italic" }}>No MP</span>;
    const st = (tracking.status || "").trim();
    if (!st) return <span style={{ fontSize: 11, color: "#5A6478", fontStyle: "italic" }}>No MP</span>;
  }

  const ll = (label || "").toLowerCase();
  let color, bg, border;

  if (ll === "on time" || ll.includes("tracking active")) {
    color = "#22C55E"; bg = "rgba(34,197,94,0.12)"; border = "rgba(34,197,94,0.25)";
  } else if (ll === "behind schedule") {
    color = "#EF4444"; bg = "rgba(239,68,68,0.12)"; border = "rgba(239,68,68,0.25)";
  } else if (ll === "in transit") {
    color = "#3B82F6"; bg = "rgba(59,130,246,0.12)"; border = "rgba(59,130,246,0.25)";
  } else if (ll === "at pickup") {
    color = "#F59E0B"; bg = "rgba(245,158,11,0.12)"; border = "rgba(245,158,11,0.25)";
  } else if (ll === "at delivery") {
    color = "#8B5CF6"; bg = "rgba(139,92,246,0.12)"; border = "rgba(139,92,246,0.25)";
  } else if (ll === "delivered") {
    color = "#22C55E"; bg = "rgba(34,197,94,0.12)"; border = "rgba(34,197,94,0.25)";
  } else if (ll === "awaiting update") {
    color = "#F97316"; bg = "rgba(249,115,22,0.12)"; border = "rgba(249,115,22,0.25)";
  } else if (ll === "no signal") {
    color = "#EF4444"; bg = "rgba(239,68,68,0.12)"; border = "rgba(239,68,68,0.25)";
  } else if (ll === "assigned") {
    color = "#6B7280"; bg = "rgba(107,114,128,0.12)"; border = "rgba(107,114,128,0.25)";
  } else if (ll === "unassigned" || ll === "no mp") {
    color = "#5A6478"; bg = "rgba(90,100,120,0.08)"; border = "rgba(90,100,120,0.15)";
  } else if (ll.includes("unresponsive")) {
    color = "#EF4444"; bg = "rgba(239,68,68,0.12)"; border = "rgba(239,68,68,0.25)";
  } else if (ll.includes("completed")) {
    color = "#22C55E"; bg = "rgba(34,197,94,0.12)"; border = "rgba(34,197,94,0.25)";
  } else {
    color = "#8B95A8"; bg = "rgba(139,149,168,0.12)"; border = "rgba(139,149,168,0.25)";
  }

  let tooltip = detail || "";
  if (lastUp) {
    const ago = relativeTime(lastUp);
    tooltip = tooltip ? `${tooltip} | Updated ${ago}` : `Updated ${ago}`;
  }

  return (
    <span
      title={tooltip || undefined}
      style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700, color, background: bg, border: `1px solid ${border}`, whiteSpace: "nowrap", cursor: tooltip ? "help" : "default" }}
    >{label}</span>
  );
}
