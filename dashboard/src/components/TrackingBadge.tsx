import { relativeTime } from "../helpers";

// Only recognized Macropoint tracking statuses — everything else is not MP data
const MP_STATUS_MAP = {
  "tracking now":                   { color: "#22C55E", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.25)",  short: "Tracking" },
  "ready to track":                 { color: "#22C55E", bg: "rgba(34,197,94,0.08)",  border: "rgba(34,197,94,0.18)",  short: "Ready" },
  "tracking completed successfully":{ color: "#22C55E", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.25)",  short: "Completed" },
  "tracking - waiting for update":  { color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)", short: "Waiting" },
  "tracking waiting for update":    { color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)", short: "Waiting" },
  "driver phone unresponsive":      { color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)", short: "No Signal" },
  "requesting app install":         { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Req. Install" },
  "expired without location":       { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Expired" },
  "location hidden by driver":      { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Hidden" },
  "denied by driver":               { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Denied" },
  "invalid truck number":           { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Invalid" },
  "stopped by creator":             { color: "#EF4444", bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.25)",  short: "Stopped" },
};

// Partial matches for statuses that come through with slight variations
const MP_PARTIAL_MATCHES = [
  { match: "tracking now",       style: MP_STATUS_MAP["tracking now"] },
  { match: "ready to track",     style: MP_STATUS_MAP["ready to track"] },
  { match: "completed successfully", style: MP_STATUS_MAP["tracking completed successfully"] },
  { match: "waiting for update", style: MP_STATUS_MAP["tracking - waiting for update"] },
  { match: "unresponsive",       style: MP_STATUS_MAP["driver phone unresponsive"] },
  { match: "requesting",         style: MP_STATUS_MAP["requesting app install"] },
  { match: "expired without",    style: MP_STATUS_MAP["expired without location"] },
  { match: "hidden by driver",   style: MP_STATUS_MAP["location hidden by driver"] },
  { match: "denied by driver",   style: MP_STATUS_MAP["denied by driver"] },
  { match: "invalid truck",      style: MP_STATUS_MAP["invalid truck number"] },
  { match: "stopped by",         style: MP_STATUS_MAP["stopped by creator"] },
  // In-progress statuses from webhook events (not official MP page statuses but valid tracking data)
  { match: "tracking started",   style: { color: "#22C55E", bg: "rgba(34,197,94,0.08)", border: "rgba(34,197,94,0.18)", short: "Started" } },
  { match: "in transit",         style: { color: "#3B82F6", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.25)", short: "In Transit" } },
  { match: "departed pickup",    style: { color: "#3B82F6", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.25)", short: "In Transit" } },
  { match: "en route",           style: { color: "#3B82F6", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.25)", short: "In Transit" } },
  { match: "at pickup",          style: { color: "#F59E0B", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.25)", short: "At Pickup" } },
  { match: "arrived at origin",  style: { color: "#F59E0B", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.25)", short: "At Pickup" } },
  { match: "at delivery",        style: { color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)", short: "At Delivery" } },
  { match: "arrived at destination", style: { color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)", short: "At Delivery" } },
  { match: "delivered",          style: { color: "#22C55E", bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.25)", short: "Delivered" } },
  { match: "departed delivery",  style: { color: "#22C55E", bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.25)", short: "Delivered" } },
];

function resolveMpStyle(rawLabel) {
  const ll = rawLabel.toLowerCase().trim();
  // Exact match first
  const exact = MP_STATUS_MAP[ll];
  if (exact) return exact;
  // Partial match
  for (const { match, style } of MP_PARTIAL_MATCHES) {
    if (ll.includes(match)) return style;
  }
  return null; // Not a recognized MP status
}

export default function TrackingBadge({ tracking, mpStatus, mpDisplayStatus, mpDisplayDetail, mpLastUpdated }) {
  const raw = (mpStatus || tracking?.status || "").trim();
  const detail = (mpDisplayDetail || tracking?.mpDisplayDetail || "").trim();
  const lastUp = mpLastUpdated || tracking?.mpLastUpdated || "";

  // Only show recognized Macropoint tracking statuses
  const style = raw ? resolveMpStyle(raw) : null;

  if (!style) {
    return <span style={{ fontSize: 11, color: "#5A6478", fontStyle: "italic" }}>—</span>;
  }

  let tooltip = raw;
  if (detail) tooltip += ` — ${detail}`;
  if (lastUp) {
    const ago = relativeTime(lastUp);
    tooltip += ` | Updated ${ago}`;
  }

  return (
    <span
      title={tooltip || undefined}
      style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700, color: style.color, background: style.bg, border: `1px solid ${style.border}`, whiteSpace: "nowrap", cursor: "help" }}
    >{style.short}</span>
  );
}
