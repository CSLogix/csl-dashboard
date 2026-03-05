import { useState, useRef, useMemo, useCallback } from "react";

// ─── Theme (matches DispatchDashboard global CSS) ───
const GRADIENT = "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)";
const COLORS = {
  base: "#0A0E17", card: "#141A28", elevated: "#1A2236", input: "#0D1119",
  border: "rgba(255,255,255,0.08)", borderHover: "rgba(255,255,255,0.15)",
  text1: "#F0F2F5", text2: "#8B95A8", text3: "#5A6478",
  accent: "#00D4AA",
};

// ─── Formatting helpers ───
function fmt(val) {
  const n = parseFloat(val) || 0;
  return n > 0 ? "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function num(v) { return parseFloat(v) || 0; }
function fmtK(n) { return n >= 1000 ? "$" + (n / 1000).toFixed(1) + "k" : "$" + n.toLocaleString(); }

// ════════════════════════════════════════════════════════════
// ─── LOOKUP TABLES (placeholder values — swap for API later)
// ════════════════════════════════════════════════════════════

const FEDERAL_THRESHOLDS = {
  width_ft: 8.5,     // 8'6"
  height_ft: 13.5,   // 13'6"
  length_ft: { flatbed: 48, stepdeck: 53, rgn: 53, double_drop: 53, perimeter: 53, multi_axle: 53, custom: 75 },
  weight_lbs: 80000,
};

const EQUIPMENT_OPTIONS = [
  { value: "flatbed", label: "Flatbed (48')" },
  { value: "stepdeck", label: "Step Deck (53')" },
  { value: "rgn", label: "RGN / Lowboy" },
  { value: "double_drop", label: "Double Drop" },
  { value: "perimeter", label: "Perimeter Frame" },
  { value: "multi_axle", label: "Multi-Axle (9+)" },
  { value: "custom", label: "Custom / Specialized" },
];

// Dim penalty tiers: $/mile based on how far over threshold
const DIM_PENALTY_TIERS = {
  width: [
    { overFt: 0, upToFt: 2, label: "8'6\" – 10'6\"", perMile: 0.00 },
    { overFt: 2, upToFt: 4, label: "10'6\" – 12'6\"", perMile: 0.25 },
    { overFt: 4, upToFt: 6, label: "12'6\" – 14'6\"", perMile: 0.50 },
    { overFt: 6, upToFt: null, label: "Over 14'6\"", perMile: 1.00 },
  ],
  height: [
    { overFt: 0, upToFt: 2, label: "13'6\" – 15'6\"", perMile: 0.00 },
    { overFt: 2, upToFt: 4, label: "15'6\" – 17'6\"", perMile: 0.50 },
    { overFt: 4, upToFt: null, label: "Over 17'6\"", perMile: 1.00 },
  ],
  length: [
    { overFt: 0, upToFt: 10, label: "Up to +10'", perMile: 0.00 },
    { overFt: 10, upToFt: 30, label: "+10' – +30'", perMile: 0.25 },
    { overFt: 30, upToFt: null, label: "Over +30'", perMile: 0.50 },
  ],
  weight: [
    { overLbs: 0, upToLbs: 25000, label: "80K – 105K", perMile: 0.00 },
    { overLbs: 25000, upToLbs: 70000, label: "105K – 150K", perMile: 0.50 },
    { overLbs: 70000, upToLbs: null, label: "150K+", perMile: 1.00 },
  ],
};

// State permit costs (single-trip oversize)
const STATE_PERMITS = {
  AL: { singleTrip: 50, superload: 200 }, AZ: { singleTrip: 60, superload: 250 },
  AR: { singleTrip: 40, superload: 175 }, CA: { singleTrip: 90, superload: 400 },
  CO: { singleTrip: 55, superload: 225 }, CT: { singleTrip: 70, superload: 300 },
  DE: { singleTrip: 45, superload: 180 }, FL: { singleTrip: 75, superload: 325 },
  GA: { singleTrip: 50, superload: 200 }, ID: { singleTrip: 45, superload: 190 },
  IL: { singleTrip: 55, superload: 250 }, IN: { singleTrip: 50, superload: 200 },
  IA: { singleTrip: 40, superload: 175 }, KS: { singleTrip: 45, superload: 185 },
  KY: { singleTrip: 50, superload: 200 }, LA: { singleTrip: 55, superload: 225 },
  ME: { singleTrip: 50, superload: 200 }, MD: { singleTrip: 65, superload: 275 },
  MA: { singleTrip: 75, superload: 325 }, MI: { singleTrip: 50, superload: 200 },
  MN: { singleTrip: 50, superload: 200 }, MS: { singleTrip: 45, superload: 185 },
  MO: { singleTrip: 50, superload: 200 }, MT: { singleTrip: 40, superload: 175 },
  NE: { singleTrip: 45, superload: 185 }, NV: { singleTrip: 55, superload: 225 },
  NH: { singleTrip: 50, superload: 200 }, NJ: { singleTrip: 70, superload: 300 },
  NM: { singleTrip: 50, superload: 200 }, NY: { singleTrip: 80, superload: 350 },
  NC: { singleTrip: 55, superload: 225 }, ND: { singleTrip: 40, superload: 175 },
  OH: { singleTrip: 55, superload: 225 }, OK: { singleTrip: 45, superload: 185 },
  OR: { singleTrip: 60, superload: 250 }, PA: { singleTrip: 60, superload: 250 },
  RI: { singleTrip: 55, superload: 225 }, SC: { singleTrip: 50, superload: 200 },
  SD: { singleTrip: 40, superload: 175 }, TN: { singleTrip: 50, superload: 200 },
  TX: { singleTrip: 60, superload: 275 }, UT: { singleTrip: 50, superload: 200 },
  VT: { singleTrip: 50, superload: 200 }, VA: { singleTrip: 55, superload: 225 },
  WA: { singleTrip: 65, superload: 275 }, WV: { singleTrip: 45, superload: 185 },
  WI: { singleTrip: 50, superload: 200 }, WY: { singleTrip: 40, superload: 175 },
  DC: { singleTrip: 70, superload: 300 },
};

// Per-state escort requirements
const ESCORT_REQUIREMENTS = {
  AL: { escortWidthFt: 14, escortHeightFt: 16 }, AZ: { escortWidthFt: 12, escortHeightFt: 16 },
  AR: { escortWidthFt: 12, escortHeightFt: 15 }, CA: { escortWidthFt: 12, escortHeightFt: 15 },
  CO: { escortWidthFt: 13, escortHeightFt: 16 }, CT: { escortWidthFt: 12, escortHeightFt: 14.5 },
  DE: { escortWidthFt: 12, escortHeightFt: 14.5 }, FL: { escortWidthFt: 12, escortHeightFt: 14.5, surveyRequired: true },
  GA: { escortWidthFt: 12, escortHeightFt: 15.5, surveyRequired: true }, ID: { escortWidthFt: 14, escortHeightFt: 16 },
  IL: { escortWidthFt: 12, escortHeightFt: 15 }, IN: { escortWidthFt: 12, escortHeightFt: 15 },
  IA: { escortWidthFt: 14.5, escortHeightFt: 16 }, KS: { escortWidthFt: 14, escortHeightFt: 16 },
  KY: { escortWidthFt: 12, escortHeightFt: 15 }, LA: { escortWidthFt: 12, escortHeightFt: 15.5 },
  MD: { escortWidthFt: 12, escortHeightFt: 14.5, surveyRequired: true }, MA: { escortWidthFt: 11, escortHeightFt: 14 },
  MI: { escortWidthFt: 14, escortHeightFt: 15.5 }, MN: { escortWidthFt: 14.5, escortHeightFt: 15.5 },
  MS: { escortWidthFt: 14, escortHeightFt: 16 }, MO: { escortWidthFt: 14, escortHeightFt: 16 },
  NE: { escortWidthFt: 14.5, escortHeightFt: 16 }, NV: { escortWidthFt: 12, escortHeightFt: 15 },
  NJ: { escortWidthFt: 12, escortHeightFt: 14.5, surveyRequired: true }, NM: { escortWidthFt: 12, escortHeightFt: 15 },
  NY: { escortWidthFt: 12, escortHeightFt: 14.5, surveyRequired: true }, NC: { escortWidthFt: 12, escortHeightFt: 15 },
  OH: { escortWidthFt: 12, escortHeightFt: 15 }, OK: { escortWidthFt: 12, escortHeightFt: 16 },
  OR: { escortWidthFt: 12, escortHeightFt: 15 }, PA: { escortWidthFt: 12, escortHeightFt: 15 },
  SC: { escortWidthFt: 12, escortHeightFt: 15, surveyRequired: true }, TN: { escortWidthFt: 12, escortHeightFt: 15 },
  TX: { escortWidthFt: 14, escortHeightFt: 17 }, VA: { escortWidthFt: 12, escortHeightFt: 14.5, surveyRequired: true },
  WA: { escortWidthFt: 12, escortHeightFt: 15 }, WV: { escortWidthFt: 12, escortHeightFt: 15 },
  WI: { escortWidthFt: 14.5, escortHeightFt: 16 },
};

const ESCORT_RATES = {
  perMile: 3.50,
  minCharge: 500,
  policePerHour: 85,
  policeMinHours: 4,
};

const FSC_CONFIG = { baseRate: 0.54 }; // $/mile

const SURVEY_RATES = { basic: 500, bridge: 1200, fullRoute: 2500 };

const TARP_OPTIONS = [
  { value: "none", label: "None", cost: 0 },
  { value: "standard", label: "Standard Tarp", cost: 150 },
  { value: "heavy", label: "Heavy Duty Tarp", cost: 300 },
  { value: "custom", label: "Custom / Specialized", cost: 500 },
];

const ALL_STATES = Object.keys(STATE_PERMITS).sort();

// ════════════════════════════════════════════════════════════
// ─── Calculation Functions ───
// ════════════════════════════════════════════════════════════

function classifyOversize(length, width, height, weight, equipment) {
  const flags = [];
  if (num(width) > FEDERAL_THRESHOLDS.width_ft)
    flags.push({ type: "OVERWIDTH", dim: "width", over: num(width) - FEDERAL_THRESHOLDS.width_ft, value: num(width), threshold: FEDERAL_THRESHOLDS.width_ft });
  if (num(height) > FEDERAL_THRESHOLDS.height_ft)
    flags.push({ type: "OVERHEIGHT", dim: "height", over: num(height) - FEDERAL_THRESHOLDS.height_ft, value: num(height), threshold: FEDERAL_THRESHOLDS.height_ft });
  const lenThreshold = FEDERAL_THRESHOLDS.length_ft[equipment] || FEDERAL_THRESHOLDS.length_ft.custom;
  if (num(length) > lenThreshold)
    flags.push({ type: "OVERLENGTH", dim: "length", over: num(length) - lenThreshold, value: num(length), threshold: lenThreshold });
  if (num(weight) > FEDERAL_THRESHOLDS.weight_lbs)
    flags.push({ type: "OVERWEIGHT", dim: "weight", over: num(weight) - FEDERAL_THRESHOLDS.weight_lbs, value: num(weight), threshold: FEDERAL_THRESHOLDS.weight_lbs });
  return flags;
}

function calcDimPenalties(flags, miles) {
  let total = 0;
  const details = [];
  for (const flag of flags) {
    const key = flag.dim === "weight" ? "weight" : flag.dim;
    const tiers = DIM_PENALTY_TIERS[key];
    if (!tiers) continue;
    let tier;
    if (key === "weight") {
      tier = tiers.find(t => flag.over >= t.overLbs && (t.upToLbs === null || flag.over < t.upToLbs));
    } else {
      tier = tiers.find(t => flag.over >= t.overFt && (t.upToFt === null || flag.over < t.upToFt));
    }
    if (tier) {
      const cost = tier.perMile * num(miles);
      details.push({ type: flag.type, label: tier.label, perMile: tier.perMile, total: cost });
      total += cost;
    }
  }
  return { total, details };
}

function calcPermitCosts(states, isSuperload) {
  let total = 0;
  const details = [];
  for (const st of states) {
    const p = STATE_PERMITS[st];
    if (!p) continue;
    const cost = isSuperload ? p.superload : p.singleTrip;
    details.push({ state: st, cost });
    total += cost;
  }
  return { total, details };
}

function calcEscortCosts(states, dims, miles) {
  let totalEscort = 0;
  const statesNeedingEscort = [];
  const statesNeedingSurvey = [];
  const milesPer = states.length > 0 ? num(miles) / states.length : 0;

  for (const st of states) {
    const req = ESCORT_REQUIREMENTS[st];
    if (!req) continue;
    const needsEscort = num(dims.width) > req.escortWidthFt || num(dims.height) > (req.escortHeightFt || 99);
    if (needsEscort) {
      statesNeedingEscort.push(st);
      totalEscort += Math.max(milesPer * ESCORT_RATES.perMile, ESCORT_RATES.minCharge);
    }
    if (req.surveyRequired && needsEscort) {
      statesNeedingSurvey.push(st);
    }
  }
  const totalSurvey = statesNeedingSurvey.length > 0 ? SURVEY_RATES.basic * statesNeedingSurvey.length : 0;
  return { totalEscort, totalSurvey, statesNeedingEscort, statesNeedingSurvey };
}

// ════════════════════════════════════════════════════════════
// ─── Bell Curve SVG ───
// ════════════════════════════════════════════════════════════

function BellCurve({ low, average, high, current }) {
  if (!average || average <= 0) return null;
  const w = 380, h = 130, padX = 40, padY = 20;
  const rangeMin = low * 0.75, rangeMax = high * 1.25;
  const sigma = (high - low) / 4 || 1;
  const points = [];
  const steps = 120;
  for (let i = 0; i <= steps; i++) {
    const x = rangeMin + (i / steps) * (rangeMax - rangeMin);
    const y = Math.exp(-0.5 * Math.pow((x - average) / sigma, 2));
    points.push({ x, y });
  }
  const maxY = Math.max(...points.map(p => p.y));
  const sx = (v) => padX + ((v - rangeMin) / (rangeMax - rangeMin)) * (w - 2 * padX);
  const sy = (v) => h - padY - (v / maxY) * (h - 2 * padY);

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
  const fillD = `M${sx(rangeMin).toFixed(1)},${(h - padY).toFixed(1)} ${pathD.replace("M", "L")} L${sx(rangeMax).toFixed(1)},${(h - padY).toFixed(1)} Z`;

  const markers = [
    { val: low, label: fmtK(low), color: "#22C55E", sub: "Low" },
    { val: average, label: fmtK(average), color: "#00D4AA", sub: "Average" },
    { val: high, label: fmtK(high), color: "#F59E0B", sub: "High" },
  ];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto" }}>
      <defs>
        <linearGradient id="bellFill" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#22C55E" stopOpacity="0.15" />
          <stop offset="50%" stopColor="#00D4AA" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#F59E0B" stopOpacity="0.15" />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#bellFill)" />
      <path d={pathD} fill="none" stroke="#00D4AA" strokeWidth="1.5" opacity="0.6" />
      {/* baseline */}
      <line x1={padX} y1={h - padY} x2={w - padX} y2={h - padY} stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
      {/* markers */}
      {markers.map(m => (
        <g key={m.sub}>
          <line x1={sx(m.val)} y1={padY} x2={sx(m.val)} y2={h - padY} stroke={m.color} strokeWidth="1" strokeDasharray={m.sub === "Average" ? "none" : "3,3"} opacity="0.5" />
          <text x={sx(m.val)} y={h - 4} textAnchor="middle" fill={m.color} fontSize="9" fontWeight="700" fontFamily="system-ui">{m.label}</text>
          <text x={sx(m.val)} y={padY - 4} textAnchor="middle" fill={m.color} fontSize="8" fontFamily="system-ui" opacity="0.7">{m.sub}</text>
        </g>
      ))}
      {/* current marker */}
      {current > 0 && current !== average && (
        <g>
          <line x1={sx(current)} y1={padY} x2={sx(current)} y2={h - padY} stroke="#F0F2F5" strokeWidth="1.5" />
          <circle cx={sx(current)} cy={padY + 2} r="3" fill="#F0F2F5" />
          <text x={sx(current)} y={padY - 4} textAnchor="middle" fill="#F0F2F5" fontSize="9" fontWeight="700" fontFamily="system-ui">{fmtK(current)}</text>
        </g>
      )}
    </svg>
  );
}

// ════════════════════════════════════════════════════════════
// ─── Email HTML Card ───
// ════════════════════════════════════════════════════════════

function buildEmailHtml(data, breakdown, marketRate) {
  const rows = [
    data.origin && data.dest ? ["Route", `${data.origin} → ${data.dest}`] : null,
    data.miles ? ["Miles", `${data.miles} mi (one-way)`] : null,
    ["Equipment", EQUIPMENT_OPTIONS.find(e => e.value === data.equipment)?.label || data.equipment],
    (data.length || data.width || data.height)
      ? ["Dimensions (L×W×H)", `${data.length || "—"}' × ${data.width || "—"}' × ${data.height || "—"}'`]
      : null,
    data.weight ? ["Gross Weight", `${Number(data.weight).toLocaleString()} lbs`] : null,
  ].filter(Boolean);

  const costRows = [
    breakdown.tripRate > 0 ? ["O/S Freight", fmt(breakdown.tripRate)] : null,
    breakdown.fuel > 0 ? ["Fuel Surcharge", fmt(breakdown.fuel)] : null,
    breakdown.dimPenalties > 0 ? ["Dim Penalties", fmt(breakdown.dimPenalties)] : null,
    breakdown.permits > 0 ? [`Permits (${data.states.length} state${data.states.length !== 1 ? "s" : ""})`, fmt(breakdown.permits)] : null,
    breakdown.escort > 0 ? ["Escort Charge", fmt(breakdown.escort)] : null,
    breakdown.survey > 0 ? ["Route Survey", fmt(breakdown.survey)] : null,
    breakdown.police > 0 ? ["Police Escort", fmt(breakdown.police)] : null,
    breakdown.tarp > 0 ? ["Tarp", fmt(breakdown.tarp)] : null,
    breakdown.other > 0 ? [data.otherLabel || "Other", fmt(breakdown.other)] : null,
  ].filter(Boolean);

  return `<table style="font-family:Arial,sans-serif;border-collapse:collapse;width:600px;background:#0f1215;border-radius:8px;overflow:hidden;">
  <tr><td colspan="2" style="padding:16px 20px 10px;border-bottom:1px solid #1e2830;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;background:linear-gradient(90deg,#00c853,#00b8d4,#2979ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Common Sense Logistics</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px;">Evans Delivery Company · Oversize Load Quote</div>
  </td></tr>
  <tr><td colspan="2" style="padding:6px 20px 2px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;background:linear-gradient(90deg,#00c853,#00b8d4,#2979ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Load Details</div>
  </td></tr>
  ${rows.map(([l, v], i) => `<tr style="background:${i % 2 === 0 ? "#0f1215" : "#131820"}"><td style="padding:7px 20px;font-size:12px;color:rgba(255,255,255,0.5);">${l}</td><td style="padding:7px 20px;font-size:12px;color:rgba(255,255,255,0.85);font-weight:700;text-align:right;">${v}</td></tr>`).join("")}
  <tr><td colspan="2" style="padding:6px 20px 2px;border-top:1px solid #1e2830;">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;background:linear-gradient(90deg,#00c853,#00b8d4,#2979ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Cost Breakdown</div>
  </td></tr>
  ${costRows.map(([l, v], i) => `<tr style="background:${i % 2 === 0 ? "#131820" : "#0f1215"}"><td style="padding:7px 20px;font-size:12px;color:rgba(255,255,255,0.5);">${l}</td><td style="padding:7px 20px;font-size:12px;color:rgba(255,255,255,0.85);font-weight:700;text-align:right;">${v}</td></tr>`).join("")}
  <tr style="border-top:1px solid #1e2830;"><td style="padding:12px 20px;font-size:13px;font-weight:700;color:rgba(255,255,255,0.9);">MARKET RATE</td><td style="padding:12px 20px;font-size:15px;font-weight:700;text-align:right;background:linear-gradient(90deg,#00c853,#00b8d4,#2979ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">${fmt(marketRate)}</td></tr>
  ${data.notes ? `<tr><td colspan="2" style="padding:8px 20px 14px;font-size:11px;color:rgba(255,255,255,0.35);border-top:1px solid #1e2830;">Notes: ${data.notes}</td></tr>` : ""}
</table>`;
}

// ════════════════════════════════════════════════════════════
// ─── Shared Input Components ───
// ════════════════════════════════════════════════════════════

const inputStyle = {
  background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6,
  padding: "7px 10px", color: COLORS.text1, fontSize: 13, outline: "none",
  width: "100%", boxSizing: "border-box", fontFamily: "inherit",
};

function Field({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={{ fontSize: 10, color: COLORS.text3, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 600 }}>{label}</span>
      {children}
    </div>
  );
}

function SectionHeader({ title }) {
  return (
    <div style={{
      background: GRADIENT, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
      fontWeight: 700, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase",
      padding: "10px 0 4px", borderBottom: `1px solid ${COLORS.border}`, marginTop: 8,
    }}>{title}</div>
  );
}

// ════════════════════════════════════════════════════════════
// ─── Main Component ───
// ════════════════════════════════════════════════════════════

export default function OOGQuoteBuilder() {
  // Route
  const [origin, setOrigin] = useState("");
  const [dest, setDest] = useState("");
  const [miles, setMiles] = useState("");
  const [states, setStates] = useState([]);
  const [stateInput, setStateInput] = useState("");

  // Load specs
  const [equipment, setEquipment] = useState("rgn");
  const [weight, setWeight] = useState("");
  const [length, setLength] = useState("");
  const [width, setWidth] = useState("");
  const [height, setHeight] = useState("");

  // Costs (manual + override toggle)
  const [tripRate, setTripRate] = useState("");
  const [overrides, setOverrides] = useState({
    fuel: { on: false, val: "" },
    dimPenalties: { on: false, val: "" },
    permits: { on: false, val: "" },
    escort: { on: false, val: "" },
    survey: { on: false, val: "" },
  });
  const [police, setPolice] = useState("");
  const [tarpType, setTarpType] = useState("none");
  const [other, setOther] = useState("");
  const [otherLabel, setOtherLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [copied, setCopied] = useState(false);

  // State tag input handler
  const handleStateKey = (e) => {
    if (e.key === "Enter" || e.key === "," || e.key === " ") {
      e.preventDefault();
      const val = stateInput.trim().toUpperCase().replace(",", "");
      if (val && ALL_STATES.includes(val) && !states.includes(val)) {
        setStates(prev => [...prev, val]);
      }
      setStateInput("");
    }
  };
  const removeState = (st) => setStates(prev => prev.filter(s => s !== st));

  const toggleOverride = (key) => setOverrides(prev => ({
    ...prev, [key]: { ...prev[key], on: !prev[key].on },
  }));
  const setOverrideVal = (key, val) => setOverrides(prev => ({
    ...prev, [key]: { ...prev[key], val },
  }));

  // ── Auto-calculations ──
  const oversizeFlags = useMemo(() =>
    classifyOversize(length, width, height, weight, equipment),
    [length, width, height, weight, equipment]
  );

  const isSuperload = useMemo(() =>
    oversizeFlags.some(f =>
      (f.dim === "weight" && f.over >= 70000) ||
      (f.dim === "width" && f.over >= 6) ||
      (f.dim === "height" && f.over >= 4)
    ), [oversizeFlags]
  );

  const autoDimPenalties = useMemo(() => calcDimPenalties(oversizeFlags, miles), [oversizeFlags, miles]);
  const autoPermits = useMemo(() => calcPermitCosts(states, isSuperload), [states, isSuperload]);
  const autoEscort = useMemo(() => calcEscortCosts(states, { width, height }, miles), [states, width, height, miles]);
  const autoFuel = useMemo(() => FSC_CONFIG.baseRate * num(miles), [miles]);

  const tarpCost = TARP_OPTIONS.find(t => t.value === tarpType)?.cost || 0;

  // Resolved values (auto or override)
  const resolved = useMemo(() => ({
    tripRate: num(tripRate),
    fuel: overrides.fuel.on ? num(overrides.fuel.val) : autoFuel,
    dimPenalties: overrides.dimPenalties.on ? num(overrides.dimPenalties.val) : autoDimPenalties.total,
    permits: overrides.permits.on ? num(overrides.permits.val) : autoPermits.total,
    escort: overrides.escort.on ? num(overrides.escort.val) : autoEscort.totalEscort,
    survey: overrides.survey.on ? num(overrides.survey.val) : autoEscort.totalSurvey,
    police: num(police),
    tarp: tarpCost,
    other: num(other),
  }), [tripRate, overrides, autoFuel, autoDimPenalties, autoPermits, autoEscort, police, tarpCost, other]);

  const marketRate = useMemo(() =>
    Object.values(resolved).reduce((s, v) => s + v, 0),
    [resolved]
  );

  const bellLow = marketRate * 0.85;
  const bellHigh = marketRate * 1.30;

  // Alerts
  const alerts = useMemo(() => {
    const a = [];
    if (states.length > 0 && autoPermits.total > 0)
      a.push({ type: "permit", color: "#F59E0B", text: `Freight will require permits in ${states.length} state${states.length !== 1 ? "s" : ""}: ${states.join(", ")}` });
    if (autoEscort.statesNeedingEscort.length > 0)
      a.push({ type: "escort", color: "#EF4444", text: `Escort required in: ${autoEscort.statesNeedingEscort.join(", ")}` });
    if (autoEscort.statesNeedingSurvey.length > 0)
      a.push({ type: "survey", color: "#FBBF24", text: `Route survey recommended in: ${autoEscort.statesNeedingSurvey.join(", ")}` });
    if (isSuperload)
      a.push({ type: "superload", color: "#A855F7", text: "Superload classification — multi-axle may be required" });
    if (oversizeFlags.length > 0 && oversizeFlags.length >= 3)
      a.push({ type: "multi", color: "#3B82F6", text: `Load is oversize in ${oversizeFlags.length} dimensions — verify route clearances` });
    return a;
  }, [states, autoPermits, autoEscort, isSuperload, oversizeFlags]);

  // Copy
  const handleCopy = async () => {
    const html = buildEmailHtml(
      { origin, dest, miles, equipment, length, width, height, weight, states, otherLabel, notes },
      resolved, marketRate,
    );
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }) }),
      ]);
      setCopied(true);
    } catch {
      // Fallback: copy as plain text
      const plain = `OOG Quote: ${origin} → ${dest} | Market Rate: ${fmt(marketRate)}`;
      await navigator.clipboard.writeText(plain).catch(() => {});
      setCopied(true);
    }
    setTimeout(() => setCopied(false), 2500);
  };

  // Clear
  const handleClear = () => {
    setOrigin(""); setDest(""); setMiles(""); setStates([]); setStateInput("");
    setEquipment("rgn"); setWeight(""); setLength(""); setWidth(""); setHeight("");
    setTripRate(""); setPolice(""); setTarpType("none"); setOther(""); setOtherLabel(""); setNotes("");
    setOverrides({ fuel: { on: false, val: "" }, dimPenalties: { on: false, val: "" }, permits: { on: false, val: "" }, escort: { on: false, val: "" }, survey: { on: false, val: "" } });
  };

  // Badge color mapping
  const badgeColor = { OVERWIDTH: "#EF4444", OVERHEIGHT: "#F59E0B", OVERLENGTH: "#EAB308", OVERWEIGHT: "#A855F7" };

  // Cost line with override toggle
  const CostLine = ({ label, costKey, autoVal }) => {
    const ov = overrides[costKey];
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1 }}>
          <Field label={label}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "6px 10px", flex: 1 }}>
                <span style={{ color: COLORS.text3, fontSize: 13, marginRight: 4 }}>$</span>
                <input
                  type="number" min="0"
                  value={ov.on ? ov.val : (autoVal > 0 ? autoVal.toFixed(2) : "")}
                  onChange={e => ov.on ? setOverrideVal(costKey, e.target.value) : null}
                  readOnly={!ov.on}
                  placeholder="0.00"
                  style={{ background: "transparent", border: "none", color: ov.on ? COLORS.text1 : COLORS.text2, fontSize: 13, outline: "none", width: "100%", fontFamily: "inherit", MozAppearance: "textfield" }}
                />
              </div>
              <button
                onClick={() => toggleOverride(costKey)}
                title={ov.on ? "Switch to auto" : "Override manually"}
                style={{
                  background: "none", border: `1px solid ${ov.on ? "rgba(245,158,11,0.4)" : "rgba(0,212,170,0.3)"}`,
                  borderRadius: 4, padding: "3px 8px", cursor: "pointer",
                  fontSize: 9, fontWeight: 700, letterSpacing: "0.05em", fontFamily: "inherit",
                  color: ov.on ? "#FBBF24" : "#00D4AA",
                }}
              >
                {ov.on ? "MANUAL" : "AUTO"}
              </button>
            </div>
          </Field>
        </div>
      </div>
    );
  };

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 800, color: COLORS.text1, margin: 0 }}>OOG IQ</h2>
        <div style={{ fontSize: 11, color: COLORS.text3, marginTop: 2 }}>Oversize / Out-of-Gauge freight quote calculator</div>
      </div>

      {/* Two-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>

        {/* ═══ LEFT COLUMN: Builder ═══ */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Route */}
          <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <SectionHeader title="Route Information" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 100px", gap: 10, marginTop: 10 }}>
              <Field label="Origin">
                <input style={inputStyle} value={origin} onChange={e => setOrigin(e.target.value)} placeholder="City, ST" />
              </Field>
              <Field label="Destination">
                <input style={inputStyle} value={dest} onChange={e => setDest(e.target.value)} placeholder="City, ST" />
              </Field>
              <Field label="Miles">
                <input style={inputStyle} type="number" value={miles} onChange={e => setMiles(e.target.value)} placeholder="0" />
              </Field>
            </div>
            {/* States traversed */}
            <div style={{ marginTop: 10 }}>
              <Field label="States Traversed">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center", background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "5px 8px", minHeight: 32 }}>
                  {states.map(st => (
                    <span key={st} style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      background: "rgba(0,212,170,0.1)", border: "1px solid rgba(0,212,170,0.25)",
                      borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 700, color: "#00D4AA",
                    }}>
                      {st}
                      <span onClick={() => removeState(st)} style={{ cursor: "pointer", opacity: 0.6, fontSize: 13 }}>×</span>
                    </span>
                  ))}
                  <input
                    value={stateInput}
                    onChange={e => setStateInput(e.target.value)}
                    onKeyDown={handleStateKey}
                    placeholder={states.length === 0 ? "Type state codes (GA, FL, TX...)" : ""}
                    style={{ background: "transparent", border: "none", color: COLORS.text1, fontSize: 12, outline: "none", flex: 1, minWidth: 80, fontFamily: "inherit" }}
                  />
                </div>
              </Field>
            </div>
          </div>

          {/* Load Specs */}
          <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <SectionHeader title="Load Specifications" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
              <Field label="Equipment">
                <select value={equipment} onChange={e => setEquipment(e.target.value)} style={{ ...inputStyle, cursor: "pointer" }}>
                  {EQUIPMENT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Field>
              <Field label="Gross Weight (lbs)">
                <input style={inputStyle} type="number" value={weight} onChange={e => setWeight(e.target.value)} placeholder="e.g. 84000" />
              </Field>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 10 }}>
              <Field label="Length (ft)">
                <input style={inputStyle} type="number" value={length} onChange={e => setLength(e.target.value)} placeholder="e.g. 65" />
              </Field>
              <Field label="Width (ft)">
                <input style={inputStyle} type="number" value={width} onChange={e => setWidth(e.target.value)} placeholder="e.g. 14" />
              </Field>
              <Field label="Height (ft)">
                <input style={inputStyle} type="number" value={height} onChange={e => setHeight(e.target.value)} placeholder="e.g. 15.5" />
              </Field>
            </div>
            {/* Oversize badges */}
            {oversizeFlags.length > 0 && (
              <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                {oversizeFlags.map(f => (
                  <span key={f.type} style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    padding: "3px 10px", borderRadius: 6, fontSize: 10, fontWeight: 800,
                    letterSpacing: "0.08em",
                    background: `${badgeColor[f.type]}18`, border: `1px solid ${badgeColor[f.type]}44`,
                    color: badgeColor[f.type],
                    animation: isSuperload && f.type === "OVERWEIGHT" ? "pulse 1.5s infinite" : "none",
                  }}>
                    {f.type}
                    <span style={{ fontWeight: 500, opacity: 0.8 }}>+{f.dim === "weight" ? `${(f.over / 1000).toFixed(0)}K lbs` : `${f.over.toFixed(1)}'`}</span>
                  </span>
                ))}
                {isSuperload && (
                  <span style={{
                    padding: "3px 10px", borderRadius: 6, fontSize: 10, fontWeight: 800,
                    background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.4)",
                    color: "#EF4444", letterSpacing: "0.08em", animation: "pulse 1.5s infinite",
                  }}>SUPERLOAD</span>
                )}
              </div>
            )}
          </div>

          {/* Cost Breakdown */}
          <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <SectionHeader title="Cost Breakdown" />
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
              {/* Trip rate - always manual */}
              <Field label="O/S Freight (Trip Rate)">
                <div style={{ display: "flex", alignItems: "center", background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "6px 10px" }}>
                  <span style={{ color: COLORS.text3, fontSize: 13, marginRight: 4 }}>$</span>
                  <input type="number" min="0" value={tripRate} onChange={e => setTripRate(e.target.value)} placeholder="0.00"
                    style={{ background: "transparent", border: "none", color: COLORS.text1, fontSize: 13, outline: "none", width: "100%", fontFamily: "inherit", MozAppearance: "textfield" }} />
                </div>
              </Field>
              <CostLine label="Fuel Surcharge (FSC)" costKey="fuel" autoVal={autoFuel} />
              <CostLine label="Dim Penalties" costKey="dimPenalties" autoVal={autoDimPenalties.total} />
              <CostLine label={`Permits (${states.length} state${states.length !== 1 ? "s" : ""})`} costKey="permits" autoVal={autoPermits.total} />
              <CostLine label="Escort Charge" costKey="escort" autoVal={autoEscort.totalEscort} />
              <CostLine label="Route Survey" costKey="survey" autoVal={autoEscort.totalSurvey} />
              {/* Police - manual only */}
              <Field label="Police Escort">
                <div style={{ display: "flex", alignItems: "center", background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "6px 10px" }}>
                  <span style={{ color: COLORS.text3, fontSize: 13, marginRight: 4 }}>$</span>
                  <input type="number" min="0" value={police} onChange={e => setPolice(e.target.value)} placeholder="0.00"
                    style={{ background: "transparent", border: "none", color: COLORS.text1, fontSize: 13, outline: "none", width: "100%", fontFamily: "inherit", MozAppearance: "textfield" }} />
                </div>
              </Field>
              {/* Tarp */}
              <Field label="Tarp">
                <select value={tarpType} onChange={e => setTarpType(e.target.value)} style={{ ...inputStyle, cursor: "pointer" }}>
                  {TARP_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}{t.cost > 0 ? ` ($${t.cost})` : ""}</option>)}
                </select>
              </Field>
              {/* Other */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <Field label="Other Label">
                  <input style={inputStyle} value={otherLabel} onChange={e => setOtherLabel(e.target.value)} placeholder="e.g. Tarping" />
                </Field>
                <Field label="Other Amount">
                  <div style={{ display: "flex", alignItems: "center", background: COLORS.input, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "6px 10px" }}>
                    <span style={{ color: COLORS.text3, fontSize: 13, marginRight: 4 }}>$</span>
                    <input type="number" min="0" value={other} onChange={e => setOther(e.target.value)} placeholder="0.00"
                      style={{ background: "transparent", border: "none", color: COLORS.text1, fontSize: 13, outline: "none", width: "100%", fontFamily: "inherit", MozAppearance: "textfield" }} />
                  </div>
                </Field>
              </div>
            </div>

            <SectionHeader title="Notes" />
            <textarea
              value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Permit restrictions, routing notes, transit days, validity..."
              rows={2}
              style={{ ...inputStyle, resize: "vertical", marginTop: 8 }}
            />
          </div>

          {/* Action buttons */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <button onClick={handleClear} style={{
              padding: "10px", background: COLORS.card, border: `1px solid ${COLORS.border}`,
              borderRadius: 8, color: COLORS.text2, fontWeight: 700, fontSize: 12,
              cursor: "pointer", fontFamily: "inherit", letterSpacing: "0.04em",
            }}>CLEAR</button>
            <button onClick={handleCopy} style={{
              padding: "10px", background: copied ? "#22C55E" : GRADIENT,
              border: "none", borderRadius: 8, color: "#fff", fontWeight: 700, fontSize: 12,
              cursor: "pointer", fontFamily: "inherit", letterSpacing: "0.04em",
              transition: "background 0.2s",
            }}>{copied ? "COPIED — PASTE INTO EMAIL" : "COPY QUOTE FOR EMAIL"}</button>
          </div>
        </div>

        {/* ═══ RIGHT COLUMN: Analysis + Preview ═══ */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Market Analysis Breakdown */}
          <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <SectionHeader title="Market Analysis" />
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
              <tbody>
                {[
                  ["Trip Rate", resolved.tripRate],
                  ["Dim Penalties", resolved.dimPenalties],
                  [`Permits (${states.length})`, resolved.permits],
                  ["Escort Charge", resolved.escort],
                  ["FSC", resolved.fuel],
                  ["Survey Charge", resolved.survey],
                  ["Police Escort", resolved.police],
                  ["Tarp Charge", resolved.tarp],
                  resolved.other > 0 ? [otherLabel || "Other", resolved.other] : null,
                ].filter(Boolean).map(([label, val], i) => (
                  <tr key={label} style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                    <td style={{ padding: "8px 0", fontSize: 12, color: COLORS.text2 }}>{label}</td>
                    <td style={{ padding: "8px 0", fontSize: 13, color: val > 0 ? COLORS.text1 : COLORS.text3, fontWeight: 700, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmt(val)}</td>
                  </tr>
                ))}
                <tr style={{ borderTop: `2px solid rgba(0,212,170,0.3)` }}>
                  <td style={{ padding: "10px 0", fontSize: 14, fontWeight: 800, color: COLORS.text1 }}>Market Rate</td>
                  <td style={{
                    padding: "10px 0", fontSize: 18, fontWeight: 800, textAlign: "right",
                    background: marketRate > 0 ? GRADIENT : "none",
                    WebkitBackgroundClip: marketRate > 0 ? "text" : "unset",
                    WebkitTextFillColor: marketRate > 0 ? "transparent" : COLORS.text3,
                    backgroundClip: marketRate > 0 ? "text" : "unset",
                  }}>{fmt(marketRate)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Bell Curve */}
          {marketRate > 0 && (
            <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
              <SectionHeader title="Market Range" />
              <div style={{ marginTop: 8 }}>
                <BellCurve low={bellLow} average={marketRate} high={bellHigh} current={marketRate} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: COLORS.text3, marginTop: 4, padding: "0 4px" }}>
                <span style={{ color: "#22C55E" }}>Low estimate</span>
                <span style={{ color: "#00D4AA" }}>Market rate</span>
                <span style={{ color: "#F59E0B" }}>High estimate</span>
              </div>
            </div>
          )}

          {/* Alerts */}
          {alerts.length > 0 && (
            <div className="glass" style={{ borderRadius: 12, padding: "14px 16px" }}>
              <SectionHeader title="Alerts" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 10 }}>
                {alerts.map((a, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "flex-start", gap: 8,
                    padding: "8px 10px", borderRadius: 8,
                    background: `${a.color}0A`, borderLeft: `3px solid ${a.color}`,
                  }}>
                    <span style={{ fontSize: 12, color: a.color, flexShrink: 0, marginTop: 1 }}>
                      {a.type === "permit" ? "⚠" : a.type === "escort" ? "🚗" : a.type === "survey" ? "📋" : a.type === "superload" ? "⚡" : "ℹ"}
                    </span>
                    <span style={{ fontSize: 12, color: COLORS.text2, lineHeight: 1.4 }}>{a.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Quote Preview Card */}
          <div className="glass" style={{ borderRadius: 12, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px 8px", borderBottom: `1px solid ${COLORS.border}` }}>
              <div style={{
                background: GRADIENT, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                backgroundClip: "text", fontSize: 11, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase",
              }}>Common Sense Logistics</div>
              <div style={{ fontSize: 10, color: COLORS.text3, marginTop: 2 }}>Evans Delivery Company · Oversize Load Quote</div>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                {[
                  origin && dest ? ["Route", `${origin} → ${dest}`] : null,
                  miles ? ["Miles", `${miles} mi (one-way)`] : null,
                  ["Equipment", EQUIPMENT_OPTIONS.find(e => e.value === equipment)?.label || equipment],
                  (length || width || height) ? ["Dimensions (L×W×H)", `${length || "—"}' × ${width || "—"}' × ${height || "—"}'`] : null,
                  weight ? ["Gross Weight", `${Number(weight).toLocaleString()} lbs`] : null,
                ].filter(Boolean).map(([label, val], i) => (
                  <tr key={label} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)" }}>
                    <td style={{ padding: "6px 16px", fontSize: 12, color: COLORS.text3 }}>{label}</td>
                    <td style={{ padding: "6px 16px", fontSize: 12, color: COLORS.text2, fontWeight: 600, textAlign: "right" }}>{val}</td>
                  </tr>
                ))}
                {/* Cost rows */}
                {[
                  resolved.tripRate > 0 ? ["O/S Freight", fmt(resolved.tripRate)] : null,
                  resolved.fuel > 0 ? ["Fuel Surcharge", fmt(resolved.fuel)] : null,
                  resolved.dimPenalties > 0 ? ["Dim Penalties", fmt(resolved.dimPenalties)] : null,
                  resolved.permits > 0 ? [`Permits (${states.length})`, fmt(resolved.permits)] : null,
                  resolved.escort > 0 ? ["Escort Charge", fmt(resolved.escort)] : null,
                  resolved.survey > 0 ? ["Route Survey", fmt(resolved.survey)] : null,
                  resolved.police > 0 ? ["Police Escort", fmt(resolved.police)] : null,
                  resolved.tarp > 0 ? ["Tarp", fmt(resolved.tarp)] : null,
                  resolved.other > 0 ? [otherLabel || "Other", fmt(resolved.other)] : null,
                ].filter(Boolean).map(([label, val], i) => (
                  <tr key={label} style={{ borderTop: i === 0 ? `1px solid ${COLORS.border}` : "none", background: i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent" }}>
                    <td style={{ padding: "6px 16px", fontSize: 12, color: COLORS.text3 }}>{label}</td>
                    <td style={{ padding: "6px 16px", fontSize: 12, color: COLORS.text1, fontWeight: 700, textAlign: "right" }}>{val}</td>
                  </tr>
                ))}
                <tr style={{ borderTop: `1px solid ${COLORS.border}` }}>
                  <td style={{ padding: "10px 16px", fontSize: 13, fontWeight: 800, color: COLORS.text1 }}>MARKET RATE</td>
                  <td style={{
                    padding: "10px 16px", fontSize: 16, fontWeight: 800, textAlign: "right",
                    background: marketRate > 0 ? GRADIENT : "none",
                    WebkitBackgroundClip: marketRate > 0 ? "text" : "unset",
                    WebkitTextFillColor: marketRate > 0 ? "transparent" : COLORS.text3,
                    backgroundClip: marketRate > 0 ? "text" : "unset",
                  }}>{fmt(marketRate)}</td>
                </tr>
                {notes && (
                  <tr style={{ borderTop: `1px solid ${COLORS.border}` }}>
                    <td colSpan={2} style={{ padding: "8px 16px", fontSize: 11, color: COLORS.text3 }}>Notes: {notes}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
