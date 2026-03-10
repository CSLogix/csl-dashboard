import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "./store";
import QuoteBuilder from "./QuoteBuilder";
import OOGQuoteBuilder from "./OOGQuoteBuilder";

// ─── API Configuration ───
const API_BASE = "";
const apiFetch = (url, opts = {}) =>
  fetch(url, { ...opts, credentials: "include" }).then(res => {
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Session expired"); }
    return res;
  });

// ─── Status Normalization ───
const STATUS_MAP = {
  // Dray statuses
  "at yard": "at_yard", "at pickup": "at_port", "discharged": "released", "at port": "at_port",
  "vessel": "on_vessel", "vessel arrived": "on_vessel", "on vessel": "on_vessel",
  "in transit": "in_transit", "intransit": "in_transit",
  "delivered": "delivered",
  "returned to port": "returned_to_port", "empty return": "empty_return",
  "hold": "on_hold", "on hold": "on_hold",
  "scheduled": "scheduled",
  "released": "released",
  "rail": "rail",
  "transload": "transload",
  "on site loading": "on_site_loading", "on-site loading": "on_site_loading",
  // FTL statuses
  "unassigned": "unassigned",
  "assigned": "assigned",
  "picking up": "picking_up",
  "on-site": "on_site", "on site": "on_site",
  "out for delivery": "out_for_delivery",
  "need pod": "need_pod",
  "pod rc'd": "pod_received", "pod received": "pod_received", "pod recd": "pod_received",
  "driver paid": "driver_paid",
  // Tolead hub statuses
  "cargo claim": "issue",
  // Cancelled statuses
  "cancelled": "cancelled",
  "cancelled tonu": "cancelled_tonu",
  "canceled": "cancelled",
  "canceled tonu": "cancelled_tonu",
  // Billing statuses (from Google Sheet column M dropdown)
  "ready to close out": "ready_to_close",
  "missing invoice": "missing_invoice",
  "billed and closed": "billed_closed",
  "ppwk needed": "ppwk_needed",
  "waiting on confirmation": "waiting_confirmation",
  "waiting cx approval": "waiting_cx_approval",
  "cx approved": "cx_approved",
};
function normalizeStatus(raw, moveType) {
  if (!raw) return moveType === "FTL" ? "unassigned" : "pending";
  const mapped = STATUS_MAP[raw.toLowerCase()];
  if (mapped) return mapped;
  // Fallback: FTL defaults to unassigned, Dray to pending
  return moveType === "FTL" ? "unassigned" : "pending";
}

// ─── Map backend shipment to frontend shape ───
function mapShipment(s, idx) {
  return {
    id: idx + 1,
    efj: s.efj || "",
    loadNumber: s.efj ? (s.efj.startsWith("EFJ") ? s.efj : `EFJ ${s.efj}`) : `#${idx + 1}`,
    container: s.container || "",
    status: normalizeStatus(s.status, s.move_type),
    rawStatus: s.status || "",
    account: s.account || "",
    carrier: s.carrier || "",
    moveType: s.move_type || "",
    origin: s.origin || "",
    destination: s.destination || "",
    eta: s.eta || "",
    lfd: s.lfd || "",
    pickupDate: s.pickup || "",
    deliveryDate: s.delivery || "",
    macropointUrl: s.container_url || null,
    driver: null,
    driverPhone: s.driver_phone || null,
    carrierEmail: s.carrier_email || null,
    trailerNumber: s.trailer || null,
    notes: s.notes || "",
    truckType: s.truck_type || "",
    customerRate: s.customer_rate || "",
    botAlert: s.bot_alert || "",
    rep: s.rep || "",
    bol: s.bol || "",
    ssl: s.ssl || "",
    returnPort: s.return_port || "",
    project: s.project || "",
    hub: s.hub || "",
    mpStatus: s.mp_status || "",
    mpDisplayStatus: s.mp_display_status || "",
    mpDisplayDetail: s.mp_display_detail || "",
    mpLastUpdated: s.mp_last_updated || "",
    email_count: s.email_count || 0,
    email_max_priority: s.email_max_priority || 0,
    synced: true,
  };
}

// ─── Statuses ───
const STATUSES = [
  { key: "all", label: "All", icon: "◎", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "at_port", label: "At Port", icon: "⚓", grad: "linear-gradient(135deg, #F97316, #FB923C)" },
  { key: "on_vessel", label: "On Vessel", icon: "🚢", grad: "linear-gradient(135deg, #2563EB, #3B82F6)" },
  { key: "in_transit", label: "In Transit", icon: "◈", grad: "linear-gradient(135deg, #3B82F6, #60A5FA)" },
  { key: "out_for_delivery", label: "Out for Delivery", icon: "🚛", grad: "linear-gradient(135deg, #A855F7, #C084FC)" },
  { key: "delivered", label: "Delivered", icon: "✦", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "empty_return", label: "Empty Return", icon: "↩", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "pending", label: "Pending", icon: "◆", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "on_hold", label: "On Hold", icon: "⏸", grad: "linear-gradient(135deg, #D97706, #F59E0B)" },
  { key: "scheduled", label: "Scheduled", icon: "📅", grad: "linear-gradient(135deg, #8B5CF6, #A78BFA)" },
  { key: "released", label: "Released", icon: "✓", grad: "linear-gradient(135deg, #059669, #10B981)" },
  { key: "returned_to_port", label: "Returned to Port", icon: "↩", grad: "linear-gradient(135deg, #0891B2, #06B6D4)" },
  { key: "at_yard", label: "At Yard", icon: "◆", grad: "linear-gradient(135deg, #4F46E5, #6366F1)" },
  { key: "rail", label: "Rail", icon: "◈", grad: "linear-gradient(135deg, #475569, #64748B)" },
  { key: "transload", label: "Transload", icon: "⇄", grad: "linear-gradient(135deg, #7C3AED, #8B5CF6)" },
  { key: "on_site_loading", label: "On Site Loading", icon: "▲", grad: "linear-gradient(135deg, #B45309, #D97706)" },
  { key: "issue", label: "Exception", icon: "⚠", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
  { key: "cancelled", label: "Cancelled", icon: "✕", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "cancelled_tonu", label: "TONU", icon: "⚠", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
];

// Billing statuses (shared across Dray + FTL, shown as separate group in status selector)
const BILLING_STATUSES = [
  { key: "ready_to_close", label: "Ready to Close", icon: "✓", grad: "linear-gradient(135deg, #F59E0B, #FBBF24)" },
  { key: "missing_invoice", label: "Missing Invoice", icon: "!", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
  { key: "billed_closed", label: "Billed & Closed", icon: "✦", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "ppwk_needed", label: "PPWK Needed", icon: "◆", grad: "linear-gradient(135deg, #EAB308, #FACC15)" },
  { key: "waiting_confirmation", label: "Waiting Confirm", icon: "◇", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "waiting_cx_approval", label: "CX Approval", icon: "◈", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "cx_approved", label: "CX Approved", icon: "●", grad: "linear-gradient(135deg, #14B8A6, #2DD4BF)" },
];

const BILLING_STATUS_COLORS = {
  ready_to_close: { main: "#F59E0B", glow: "#F59E0B33" },
  missing_invoice: { main: "#EF4444", glow: "#EF444433" },
  billed_closed: { main: "#22C55E", glow: "#22C55E33" },
  ppwk_needed: { main: "#EAB308", glow: "#EAB30833" },
  waiting_confirmation: { main: "#6B7280", glow: "#6B728033" },
  waiting_cx_approval: { main: "#06B6D4", glow: "#06B6D433" },
  cx_approved: { main: "#14B8A6", glow: "#14B8A633" },
};

// Unbilled orders billing workflow
const UNBILLED_BILLING_FLOW = [
  { key: "ready_to_bill", label: "Ready to Bill", color: "#fbbf24" },
  { key: "billed_cx", label: "Billed CX", color: "#3b82f6" },
  { key: "driver_paid", label: "Driver Paid", color: "#f97316" },
  { key: "closed", label: "Closed", color: "#34d399" },
];

const STATUS_COLORS = {
  at_port: { main: "#F97316", glow: "#F9731633" },
  on_vessel: { main: "#2563EB", glow: "#2563EB33" },
  in_transit: { main: "#3B82F6", glow: "#3B82F633" },
  out_for_delivery: { main: "#A855F7", glow: "#A855F733" },
  delivered: { main: "#22C55E", glow: "#22C55E33" },
  empty_return: { main: "#06B6D4", glow: "#06B6D433" },
  pending: { main: "#4B5563", glow: "#4B556333" },
  on_hold: { main: "#D97706", glow: "#D9770633" },
  scheduled: { main: "#8B5CF6", glow: "#8B5CF633" },
  released: { main: "#059669", glow: "#05966933" },
  returned_to_port: { main: "#0891B2", glow: "#0891B233" },
  at_yard: { main: "#4F46E5", glow: "#4F46E533" },
  rail: { main: "#475569", glow: "#47556933" },
  transload: { main: "#7C3AED", glow: "#7C3AED33" },
  on_site_loading: { main: "#B45309", glow: "#B4530933" },
  issue: { main: "#F87171", glow: "#EF444433" },
  cancelled: { main: "#6B7280", glow: "#6B728033" },
  cancelled_tonu: { main: "#EF4444", glow: "#EF444433" },
  ...BILLING_STATUS_COLORS,
};

// ─── FTL Statuses ───
const FTL_STATUSES = [
  { key: "all", label: "All", icon: "◎", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "unassigned", label: "Unassigned", icon: "○", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "assigned", label: "Assigned", icon: "●", grad: "linear-gradient(135deg, #F59E0B, #FBBF24)" },
  { key: "scheduled", label: "Scheduled", icon: "📅", grad: "linear-gradient(135deg, #8B5CF6, #A78BFA)" },
  { key: "picking_up", label: "Picking Up", icon: "🚛", grad: "linear-gradient(135deg, #A855F7, #C084FC)" },
  { key: "in_transit", label: "In Transit", icon: "◈", grad: "linear-gradient(135deg, #3B82F6, #60A5FA)" },
  { key: "on_site", label: "On-Site", icon: "📍", grad: "linear-gradient(135deg, #F97316, #FB923C)" },
  { key: "delivered", label: "Delivered", icon: "✦", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "need_pod", label: "Need POD", icon: "📋", grad: "linear-gradient(135deg, #EAB308, #FACC15)" },
  { key: "pod_received", label: "POD Rc'd", icon: "✓", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "driver_paid", label: "Driver Paid", icon: "💲", grad: "linear-gradient(135deg, #10B981, #34D399)" },
  { key: "cancelled", label: "Cancelled", icon: "✕", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "cancelled_tonu", label: "TONU", icon: "⚠", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
];

const FTL_STATUS_COLORS = {
  unassigned: { main: "#6B7280", glow: "#6B728033" },
  assigned: { main: "#F59E0B", glow: "#F59E0B33" },
  scheduled: { main: "#8B5CF6", glow: "#8B5CF633" },
  picking_up: { main: "#A855F7", glow: "#A855F733" },
  in_transit: { main: "#3B82F6", glow: "#3B82F633" },
  on_site: { main: "#F97316", glow: "#F9731633" },
  delivered: { main: "#22C55E", glow: "#22C55E33" },
  need_pod: { main: "#EAB308", glow: "#EAB30833" },
  pod_received: { main: "#06B6D4", glow: "#06B6D433" },
  driver_paid: { main: "#10B981", glow: "#10B98133" },
  cancelled: { main: "#6B7280", glow: "#6B728033" },
  cancelled_tonu: { main: "#EF4444", glow: "#EF444433" },
  ...BILLING_STATUS_COLORS,
};

// ─── Move-type helpers ───
function isFTLShipment(s) {
  return s.moveType === "FTL" || s.account === "Boviet" || s.account === "Tolead";
}
function getStatusesForShipment(s) {
  return isFTLShipment(s) ? FTL_STATUSES : STATUSES;
}
function getStatusColors(s) {
  return isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS;
}
function resolveStatusLabel(s) {
  const list = isFTLShipment(s) ? FTL_STATUSES : STATUSES;
  return list.find(st => st.key === s.status)?.label || s.rawStatus || s.status;
}
function resolveStatusColor(s) {
  const colors = isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS;
  return colors[s.status] || { main: "#94a3b8", glow: "#94a3b833" };
}

// Merge both status lists for "All" mode in filter bar
const ALL_STATUSES_COMBINED = (() => {
  const seen = new Set();
  const merged = [];
  for (const s of [...STATUSES, ...FTL_STATUSES]) {
    if (!seen.has(s.key)) { seen.add(s.key); merged.push(s); }
  }
  return merged;
})();

const ACCOUNT_COLORS = ["#ef4444", "#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#a855f7"];

const MACROPOINT_FALLBACK = {
  loadId: "", carrier: "Evans Delivery Company, Inc.", driver: "",
  phone: "(443) 761-4954", email: "efj-operations@evansdelivery.com",
  trackingStatus: "Unknown",
  progress: [
    { label: "Driver Assigned", done: false }, { label: "Ready To Track", done: false },
    { label: "Arrived At Origin", done: false }, { label: "Departed Origin", done: false },
    { label: "At Delivery", done: false }, { label: "Delivered", done: false },
  ],
};

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { key: "dispatch", label: "Dispatch", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" },
  { key: "inbox", label: "Inbox", icon: "M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
  { key: "history", label: "History", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
  { key: "quotes", label: "Rate IQ", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { key: "analytics", label: "Analytics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { key: "billing", label: "Billing", icon: "M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2zM10 8.5a.5.5 0 11-1 0 .5.5 0 011 0zm5 5a.5.5 0 11-1 0 .5.5 0 011 0z" },
  { key: "bol", label: "BOL Gen", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
];

// ─── Rep-to-Account Mapping (from Account Rep lookup table) ───
const REP_ACCOUNTS = {
  Eli: ["DSV", "EShipping", "Kishco", "MAO", "Rose"],
  Radka: ["Allround", "Cadi", "IWS", "Kripke", "MGF", "Meiko", "Sutton", "Tanera", "TCR", "Texas International", "USHA"],
  "John F": ["DHL", "Mamata", "SEI Acquisition"],
  Janice: ["CNL"],
  Boviet: ["Boviet"],
  Tolead: ["Tolead"],
};
const REP_COLORS = { Eli: "#f59e0b", Radka: "#ef4444", "John F": "#10b981", Janice: "#ec4899", Boviet: "#8b5cf6", Tolead: "#06b6d4" };
const ALL_REP_NAMES = Object.keys(REP_ACCOUNTS);
const MASTER_REPS = ["Eli", "Radka", "John F", "Janice"];
const TRUCK_TYPES = ["", "53' Solo", "53' Team", "Flat Bed", "26' Box"];

const DRAY_EQUIPMENT = ["", "20'", "40' Standard", "40' HC", "40' HC Reefer", "Flatrack", "Flatrack OOG", "LCL"];
const FTL_EQUIPMENT = ["", "53' Van", "53' Team", "Box Truck", "Sprinter Van", "53' Reefer", "48ft Flatbed", "48ft Flatbed (Tarps)", "53' Flatbed", "53' Flatbed (Tarps)", "Flatbed Hotshot"];
const DOC_TYPES_ADD = ["customer_rate", "carrier_rate", "pod", "bol", "carrier_invoice", "email", "other"];
const DOC_TYPE_LABELS = { customer_rate: "CX Rate", carrier_rate: "RC", pod: "POD", bol: "BOL", carrier_invoice: "Carrier Inv", email: "Email", other: "Other" };

const ALERT_TYPES = {
  STATUS_CHANGE: "status_change",
  DELIVERED_NEEDS_BILLING: "delivered_needs_billing",
  TRACKING_BEHIND: "tracking_behind",
  POD_RECEIVED: "pod_received",
  NEEDS_DRIVER: "needs_driver",
  DOC_INDEXED: "doc_indexed",
  RATE_RESPONSE: "rate_response",
  PAYMENT_ESCALATION: "payment_escalation",
  SEND_FINAL_CHARGES: "send_final_charges",
};
const ALERT_TYPE_CONFIG = {
  status_change:           { icon: "\u2197", color: "#3B82F6", label: "Status Change" },
  delivered_needs_billing:  { icon: "\u2726", color: "#F59E0B", label: "Needs Close-Out" },
  tracking_behind:          { icon: "\u26A0", color: "#F97316", label: "Behind Schedule" },
  pod_received:             { icon: "\u25C9", color: "#22C55E", label: "POD Received" },
  needs_driver:             { icon: "\u25CF", color: "#EF4444", label: "Needs Driver" },
  doc_indexed:              { icon: "\u25C8", color: "#8B5CF6", label: "Doc Indexed" },
  rate_response:            { icon: "\u2605", color: "#00D4AA", label: "Rate Response" },
  payment_escalation:       { icon: "\u26A0", color: "#EF4444", label: "Payment Alert" },
  send_final_charges:       { icon: "$", color: "#F59E0B", label: "Send Final Charges" },
};

function getRepShipments(shipments, repName) {
  const accts = REP_ACCOUNTS[repName] || [];
  return (Array.isArray(shipments) ? shipments : []).filter(s =>
    accts.some(a => a.toLowerCase() === s.account.toLowerCase()) ||
    s.rep?.toLowerCase() === repName.toLowerCase()
  );
}

function parseDate(str) {
  if (!str) return null;
  const s = str.trim();
  // Skip obvious non-dates
  if (/^[*\w]/.test(s) && !/^\d/.test(s)) return null;
  const year = new Date().getFullYear();
  // MM/DD or MM-DD (no year) — e.g. "02/27", "03-02"
  let m = s.match(/^(\d{1,2})[/-](\d{1,2})$/);
  if (m) return new Date(year, +m[1] - 1, +m[2]);
  // MM/DD time or MM-DD time — e.g. "03-02 8:00 AM", "03/02 8:00"
  m = s.match(/^(\d{1,2})[/-](\d{1,2})\s+(.+)/);
  if (m && !/\d{4}/.test(m[3])) {
    const d = new Date(`${m[1]}/${m[2]}/${year} ${m[3].replace(/\s*(am|pm|to\s+.*)$/i, (x) => x.match(/am|pm/i)?.[0] || '')}`);
    if (!isNaN(d.getTime())) return d;
    return new Date(year, +m[1] - 1, +m[2]);
  }
  // YYYY-MM-DD HHMM (military without colon) — e.g. "2026-03-02 1200"
  m = s.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2})(\d{2})$/);
  if (m) return new Date(`${m[1]}T${m[2]}:${m[3]}`);
  // Native parse
  const d = new Date(s);
  if (!isNaN(d.getTime())) return d;
  // Append year fallback
  const withYear = new Date(s + " " + year);
  if (!isNaN(withYear.getTime())) return withYear;
  return null;
}
function relativeTime(str) {
  if (!str) return "";
  const ts = str.replace(/ E[SD]?T$/, "").trim();
  const d = new Date(ts);
  if (isNaN(d.getTime())) return str;
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
function isDateToday(str) {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
function isDateTomorrow(str) {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setDate(t.getDate() + 1);
  return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
function isDatePast(str) {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setHours(0,0,0,0); return d < t;
}
function isDateFuture(str) {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setHours(23,59,59,999); return d > t;
}
function isDateThisWeek(str) {
  const d = parseDate(str); if (!d) return false;
  const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? -6 : 1);
  const mon = new Date(now); mon.setDate(diff); mon.setHours(0,0,0,0);
  const sun = new Date(mon); sun.setDate(sun.getDate() + 6); sun.setHours(23,59,59,999);
  return d >= mon && d <= sun;
}

// ─── Column Header Filter Helpers ───
const COL_FILTER_KEY_MAP = {
  "Account": "account", "Status": "status", "Carrier": "carrier",
  "MP Status": "mpStatus", "Origin": "origin", "Destination": "destination",
  "Pickup": "pickup", "Delivery": "delivery", "PU": "pickup", "DEL": "delivery",
};
const DATE_FILTER_PRESETS = ["Today", "Tomorrow", "This Week", "Past Due"];

function matchesDatePreset(dateStr, preset) {
  if (preset === "Today") return isDateToday(dateStr);
  if (preset === "Tomorrow") return isDateTomorrow(dateStr);
  if (preset === "This Week") return isDateThisWeek(dateStr);
  if (preset === "Past Due") return dateStr && isDatePast(dateStr);
  return true;
}
function applyColFilters(data, filters, trackingSummary) {
  const active = Object.entries(filters).filter(([, v]) => v != null);
  if (!active.length) return data;
  return data.filter(s => active.every(([key, val]) => {
    if (key === "pickup" || key === "delivery") return matchesDatePreset(key === "pickup" ? s.pickupDate : s.deliveryDate, val);
    if (key === "status") return s.status === val;
    if (key === "mpStatus") { const e = (s.efj || "").replace(/^EFJ\s*/i, ""); return (s.mpDisplayStatus || trackingSummary?.[e]?.mpDisplayStatus || s.mpStatus || trackingSummary?.[e]?.mpStatus || "") === val; }
    return (s[key] || "") === val;
  }));
}
function buildColFilterOptions(data, trackingSummary) {
  const opts = {};
  opts.account = [...new Set(data.map(s => s.account).filter(Boolean))].sort();
  opts.status = [...new Set(data.map(s => s.status).filter(Boolean))]
    .map(v => ({ value: v, label: [...STATUSES, ...FTL_STATUSES].find(st => st.key === v)?.label || v }))
    .sort((a, b) => a.label.localeCompare(b.label));
  opts.carrier = [...new Set(data.map(s => s.carrier).filter(Boolean))].sort();
  opts.mpStatus = [...new Set(data.map(s => { const e = (s.efj||"").replace(/^EFJ\s*/i,""); return s.mpDisplayStatus || trackingSummary?.[e]?.mpDisplayStatus || s.mpStatus || trackingSummary?.[e]?.mpStatus || ""; }).filter(Boolean))].sort();
  opts.origin = [...new Set(data.map(s => s.origin).filter(v => v && v !== "\u2014" && v !== "—"))].sort();
  opts.destination = [...new Set(data.map(s => s.destination).filter(v => v && v !== "\u2014" && v !== "—"))].sort();
  opts.pickup = DATE_FILTER_PRESETS;
  opts.delivery = DATE_FILTER_PRESETS;
  return opts;
}

function resolveRepForShipment(s) {
  if (s.rep) return s.rep;
  for (const [rep, accts] of Object.entries(REP_ACCOUNTS)) {
    if (accts.some(a => a.toLowerCase() === (s.account || "").toLowerCase())) return rep;
  }
  return "";
}
function timeAgo(ts) {
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
function loadDismissedAlerts() {
  try { return JSON.parse(localStorage.getItem("csl_dismissed_alerts") || "[]"); } catch { return []; }
}
function saveDismissedAlerts(ids) {
  localStorage.setItem("csl_dismissed_alerts", JSON.stringify(ids.slice(-500)));
}
function generateSnapshotAlerts(shipments, trackingSummary, docSummary) {
  const alerts = [];
  if (!Array.isArray(shipments)) return alerts;
  for (const s of shipments) {
    const efjBare = s.efj?.replace(/^EFJ\s*/i, "");
    const rep = resolveRepForShipment(s);
    // Delivered needs billing
    if (s.status === "delivered") {
      alerts.push({ id: `delivered_needs_billing-${s.efj}`, type: ALERT_TYPES.DELIVERED_NEEDS_BILLING,
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} delivered \u2014 needs billing`,
        detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
    }
    // Tracking behind
    const track = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
    if (track && (track.behindSchedule || track.cantMakeIt)) {
      alerts.push({ id: `tracking_behind-${s.efj}`, type: ALERT_TYPES.TRACKING_BEHIND,
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} ${track.cantMakeIt ? "cannot make it" : "behind schedule"}`,
        detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
    }
    // POD received but still needs action
    const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
    if (docs?.pod && ["delivered", "need_pod"].includes(s.status)) {
      alerts.push({ id: `pod_received-${s.efj}`, type: ALERT_TYPES.POD_RECEIVED,
        efj: s.efj, account: s.account, rep,
        message: `POD received for ${s.loadNumber || s.efj}`,
        detail: `${s.account} \u2014 update status`, timestamp: Date.now(), shipmentId: s.id });
    }
    // Needs driver
    if (!s.carrier && (isDateToday(s.pickupDate) || isDateTomorrow(s.pickupDate)) && !["delivered", "empty_return", "cancelled", "cancelled_tonu"].includes(s.status)) {
      alerts.push({ id: `needs_driver-${s.efj}`, type: ALERT_TYPES.NEEDS_DRIVER,
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} needs driver`,
        detail: `Pickup ${isDateToday(s.pickupDate) ? "today" : "tomorrow"} | ${s.account}`, timestamp: Date.now(), shipmentId: s.id });
    }
  }
  return alerts;
}

// ─── Date/Time Splitting ───
function splitDateTime(str) {
  if (!str) return { date: "", time: "" };
  const s = str.trim();
  // Try "YYYY-MM-DD HH:MM" or "MM/DD/YYYY HH:MM" patterns
  const spaceIdx = s.indexOf(" ");
  if (spaceIdx > 0) {
    const afterSpace = s.slice(spaceIdx + 1).trim();
    // Check if the part after space looks like a time (contains : or AM/PM)
    if (/\d{1,2}:\d{2}/.test(afterSpace) || /[ap]m/i.test(afterSpace)) {
      return { date: s.slice(0, spaceIdx).trim(), time: afterSpace };
    }
  }
  return { date: s, time: "" };
}

// ─── MM-DD Short Date Display ───
// Formats any date string to "MM/DD" for compact display
function formatDDMM(dateStr) {
  if (!dateStr) return "";
  // Strip time portion first — only format the date part
  const { date: dateOnly } = splitDateTime(dateStr);
  if (!dateOnly) return "";
  const s = dateOnly.trim();
  // "YYYY-MM-DD"
  const ymd = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (ymd) return `${ymd[2]}/${ymd[3]}`;
  // "MM/DD/YYYY"
  const mdy = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (mdy) return `${mdy[1].padStart(2, "0")}/${mdy[2].padStart(2, "0")}`;
  // "M/D" (no year, e.g. Tolead delivery "3/8")
  const mdNoYear = s.match(/^(\d{1,2})\/(\d{1,2})$/);
  if (mdNoYear) return `${mdNoYear[1].padStart(2, "0")}/${mdNoYear[2].padStart(2, "0")}`;
  // "MM/DD" already
  if (/^\d{2}\/\d{2}$/.test(s)) return s;
  return s.slice(0, 5);
}

// ─── Parse 4-digit MMDD input → "YYYY-MM-DD" ───
function parseDDMM(input) {
  const digits = input.replace(/\D/g, "");
  if (digits.length !== 4) return null;
  const mm = digits.slice(0, 2);
  const dd = digits.slice(2, 4);
  const d = parseInt(dd, 10), m = parseInt(mm, 10);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const year = new Date().getFullYear();
  return `${year}-${mm}-${dd}`;
}

// ─── Format date as MM/DD for display ───
function formatMMDD(dateStr) {
  if (!dateStr) return "";
  const s = dateStr.trim();
  const ymd = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (ymd) return `${ymd[2]}/${ymd[3]}`;
  const mdy = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (mdy) return `${mdy[1].padStart(2, "0")}/${mdy[2].padStart(2, "0")}`;
  if (/^\d{2}\/\d{2}$/.test(s)) return s;
  return s.slice(0, 5);
}

// ─── Parse 4-digit MMDD input → "YYYY-MM-DD" ───
function parseMMDD(input) {
  const digits = input.replace(/\D/g, "");
  if (digits.length !== 4) return null;
  const mm = digits.slice(0, 2);
  const dd = digits.slice(2, 4);
  const m = parseInt(mm, 10), d = parseInt(dd, 10);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const year = new Date().getFullYear();
  return `${year}-${mm}-${dd}`;
}

// ─── Document Indicator Icons ───
function DocIndicators({ docs }) {
  if (!docs || Object.keys(docs).length === 0) return null;
  const icons = [];
  if (docs.bol) icons.push({ icon: "\u{1F4CB}", label: "BOL", key: "bol" });
  if (docs.pod) icons.push({ icon: "\u{1F4F8}", label: "POD", key: "pod" });
  if (docs.customer_rate || docs.carrier_rate) icons.push({ icon: "\u{1F4B0}", label: "Rate", key: "rate" });
  if (docs.carrier_invoice) icons.push({ icon: "\u{1F9FE}", label: "Invoice", key: "inv" });
  if (icons.length === 0) icons.push({ icon: "\u{1F4C4}", label: `${Object.values(docs).reduce((a, b) => a + b, 0)} docs`, key: "other" });
  return (
    <span style={{ display: "inline-flex", gap: 2, marginLeft: 4 }}>
      {icons.map(ic => <span key={ic.key} title={ic.label} style={{ fontSize: 10, cursor: "default", opacity: 0.7 }}>{ic.icon}</span>)}
    </span>
  );
}

// ─── FTL Tracking Badge — shows actual Macropoint status ───
function TrackingBadge({ tracking, mpStatus, mpDisplayStatus, mpDisplayDetail, mpLastUpdated }) {
  // mpDisplayStatus = classified status from server (On Time, Behind Schedule, At Pickup, etc.)
  // Falls back to mpStatus (raw Macropoint status) then tracking summary
  const display = (mpDisplayStatus || "").trim();
  const raw = (mpStatus || tracking?.mpStatus || "").trim();
  const detail = (mpDisplayDetail || tracking?.mpDisplayDetail || "").trim();
  const lastUp = mpLastUpdated || tracking?.mpLastUpdated || "";

  // Use classified display status if available, otherwise fall back to raw
  const label = display || raw;
  if (!label) {
    if (!tracking) return <span style={{ fontSize: 9, color: "#5A6478", fontStyle: "italic" }}>No MP</span>;
    const st = (tracking.status || "").trim();
    if (!st) return <span style={{ fontSize: 9, color: "#5A6478", fontStyle: "italic" }}>No MP</span>;
  }

  const ll = (label || "").toLowerCase();
  let color, bg, border;

  // Color mapping for classified statuses
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

  // Build tooltip with detail + relative time of last update
  let tooltip = detail || "";
  if (lastUp) {
    const ago = relativeTime(lastUp);
    tooltip = tooltip ? `${tooltip} | Updated ${ago}` : `Updated ${ago}`;
  }

  return (
    <span
      title={tooltip || undefined}
      style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 9, fontWeight: 700, color, background: bg, border: `1px solid ${border}`, whiteSpace: "nowrap", cursor: tooltip ? "help" : "default" }}
    >{label}</span>
  );
}

// ═══════════════════════════════════════════════════════════════
// COMMAND PALETTE — Ctrl+K global search overlay
// ═══════════════════════════════════════════════════════════════
const CMD_STATUS_COLORS = {
  delivered: "#22c55e", empty_return: "#22c55e", billed_closed: "#22c55e",
  in_transit: "#60a5fa", picked_up: "#60a5fa",
  at_port: "#f97316", on_vessel: "#f97316",
  pending: "#8B95A8", unassigned: "#8B95A8", need_pod: "#fbbf24",
};

function CommandPalette({ open, query, setQuery, index, setIndex, shipments, onSelect, onClose }) {
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
    <div onClick={onClose} style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)", zIndex: 9999, display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "15vh" }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 560, background: "#0f1215", border: "1px solid #00b8d4", borderRadius: 12, overflow: "hidden", boxShadow: "0 0 40px rgba(0,184,212,0.15), 0 20px 60px rgba(0,0,0,0.5)", fontFamily: "'Plus Jakarta Sans', sans-serif", animation: "fade-in 0.15s ease" }}>
        {/* Search input */}
        <div style={{ display: "flex", alignItems: "center", padding: "14px 18px", borderBottom: "1px solid #1e2a30", gap: 10 }}>
          <span style={{ color: "#00b8d4", fontSize: 13, fontWeight: 700, flexShrink: 0 }}>⌘F</span>
          <input ref={inputRef} type="text" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={handleKeyDown}
            placeholder="Search EFJ, container, customer..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "rgba(255,255,255,0.9)", fontSize: 14, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.3px" }} />
          <span style={{ color: "rgba(255,255,255,0.2)", fontSize: 9, background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 4, flexShrink: 0 }}>ESC</span>
        </div>
        {/* Results */}
        <div style={{ maxHeight: 340, overflowY: "auto" }}>
          {query.length >= 2 && results.length === 0 && (
            <div style={{ padding: "20px 18px", textAlign: "center", color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No results for "{query}"</div>
          )}
          {query.length < 2 && (
            <div style={{ padding: "20px 18px", textAlign: "center", color: "rgba(255,255,255,0.15)", fontSize: 11 }}>Type 2+ characters to search...</div>
          )}
          {results.map((s, i) => (
            <div key={s.id} onClick={() => { onSelect(s); onClose(); }}
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
                <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, whiteSpace: "nowrap" }}>{s.account}{s.destination ? ` · ${s.destination}` : ""}</span>
                <span style={{ background: `${statusColor(s)}20`, color: statusColor(s), padding: "2px 8px", borderRadius: 10, fontSize: 9, fontWeight: 600, whiteSpace: "nowrap" }}>{statusLabel(s)}</span>
              </div>
            </div>
          ))}
        </div>
        {/* Footer */}
        <div style={{ padding: "8px 18px", borderTop: "1px solid #1e2a30", display: "flex", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 14, fontSize: 9, color: "rgba(255,255,255,0.18)" }}>
            <span>↑↓ Navigate</span><span>↵ Open</span><span>ESC Close</span>
          </div>
          <span style={{ fontSize: 9, color: "rgba(255,255,255,0.12)" }}>{results.length > 0 ? `${results.length} result${results.length !== 1 ? "s" : ""}` : ""}</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// CLOCK DISPLAY — isolated to prevent full-tree re-render every 1s
// ═══════════════════════════════════════════════════════════════
function ClockDisplay({ lastSyncTime, apiError }) {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const syncText = lastSyncTime ? (() => {
    const secs = Math.floor((time - lastSyncTime) / 1000);
    if (secs < 10) return "Just synced";
    if (secs < 60) return `Synced ${secs}s ago`;
    return `Synced ${Math.floor(secs / 60)}m ago`;
  })() : "Connecting...";
  return (
    <>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#8B95A8" }}>
        {time.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })} - {time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
      </div>
      <div className="glass" style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 100, fontSize: 10, color: apiError ? "#EF4444" : "#00D4AA", fontWeight: 500 }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: apiError ? "#EF4444" : "#00D4AA", animation: "pulse-glow 2s ease infinite", boxShadow: `0 0 8px ${apiError ? "#EF444466" : "#00D4AA66"}` }} />
        {syncText}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════
export default function DispatchDashboard() {
  // ── Core state from Zustand store (shared across components) ──
  const {
    shipments, setShipments, accounts, setAccounts,
    botStatus, setBotStatus, botHealth, setBotHealth, cronStatus, setCronStatus,
    apiStats, setApiStats, accountOverview, setAccountOverview,
    trackingSummary, setTrackingSummary, docSummary, setDocSummary,
    unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats,
    repProfiles, setRepProfiles, eventAlerts, setEventAlerts,
    sheetLog, setSheetLog, lastSyncTime, setLastSyncTime,
    loaded, setLoaded, apiError, setApiError,
    activeView, setActiveView, selectedRep, setSelectedRep,
    selectedShipment, setSelectedShipment,
    activeStatus, setActiveStatus, activeAccount, setActiveAccount,
    activeRep, setActiveRep, searchQuery, setSearchQuery,
    moveTypeFilter, setMoveTypeFilter, dateFilter, setDateFilter,
    dateRangeField, setDateRangeField, dateRangeStart, setDateRangeStart,
    dateRangeEnd, setDateRangeEnd,
    dataSource, setDataSource, systemHealth, setSystemHealth,
  } = useAppStore();

  // Clean up stale localStorage keys from old builds
  useState(() => { try { localStorage.removeItem("csl_preferred_rep"); } catch {} });

  // ── Local-only UI state (not shared) ──
  const [dismissedAlertIds, setDismissedAlertIds] = useState(() => loadDismissedAlerts());
  const prevStatusMapRef = useRef({});
  const prevDocMapRef = useRef({});
  const prevRateAlertsRef = useRef(new Set());
  const [inboxThreads, setInboxThreads] = useState([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editField, setEditField] = useState(null);
  const [editValue, setEditValue] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [podUploading, setPodUploading] = useState(false);
  const [podUploadMsg, setPodUploadMsg] = useState(null);
  const [carrierDirectory, setCarrierDirectory] = useState([]);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [cmdkQuery, setCmdkQuery] = useState("");
  const [cmdkIndex, setCmdkIndex] = useState(0);

  // Fetch team profiles (avatars)
  const fetchProfiles = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/team/profiles`);
      if (res.ok) { const data = await res.json(); setRepProfiles(data.profiles || {}); }
    } catch {}
  }, []);

  const fetchData = useCallback(async () => {
    const src = useAppStore.getState().dataSource;
    const isSheets = src === "sheets";
    try {
      const [shipmentsRes, statsRes, botRes, accountsRes, trackRes, docRes] = await Promise.allSettled([
        apiFetch(`${API_BASE}/api/${isSheets ? "shipments" : "v2/shipments"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/${isSheets ? "stats" : "v2/stats"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/bot-status`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/${isSheets ? "accounts" : "v2/accounts"}`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/shipments/tracking-summary`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/shipments/document-summary`).then(r => r.json()),
      ]);
      if (shipmentsRes.status === "fulfilled") {
        const mapped = shipmentsRes.value.shipments.map(mapShipment);
        setShipments(prev => {
          const prevMap = new Map(prev.map(s => [s.efj, s]));
          return mapped.map(s => {
            const existing = prevMap.get(s.efj);
            if (existing && !existing.synced) return { ...existing, id: s.id };
            return s;
          });
        });
        const acctNames = [...new Set(mapped.map(s => s.account).filter(Boolean))].sort();
        setAccounts(["All Accounts", ...acctNames]);
      }
      if (statsRes.status === "fulfilled") setApiStats(statsRes.value);
      if (botRes.status === "fulfilled") {
        const bots = Array.isArray(botRes.value) ? botRes.value : (botRes.value.services || []);
        setBotStatus(bots);
      }
      if (accountsRes.status === "fulfilled") {
        const accts = accountsRes.value.accounts || [];
        setAccountOverview(accts.map((a, i) => ({ name: a.name, loads: a.active, alerts: a.alerts || 0, color: ACCOUNT_COLORS[i % ACCOUNT_COLORS.length] })));
      }
      if (trackRes.status === "fulfilled") setTrackingSummary(trackRes.value.tracking || {});
      if (docRes.status === "fulfilled") setDocSummary(docRes.value.documents || {});
      // Detect status changes from backend
      if (shipmentsRes.status === "fulfilled") {
        const mapped2 = shipmentsRes.value.shipments.map(mapShipment);
        const newStatusMap = {};
        mapped2.forEach(s => { if (s.id) newStatusMap[s.id] = s.status; });
        const prev = prevStatusMapRef.current;
        if (Object.keys(prev).length > 0) {
          const changeAlerts = [];
          for (const s of mapped2) {
            if (!s.id) continue;
            const old = prev[s.id];
            if (old && old !== s.status) {
              const sList2 = isFTLShipment(s) ? FTL_STATUSES : STATUSES;
              const label = sList2.find(st => st.key === s.status)?.label || BILLING_STATUSES.find(st => st.key === s.status)?.label || s.rawStatus || s.status;
              changeAlerts.push({ id: `status_change-${s.id}-${s.status}-${Date.now()}`, type: ALERT_TYPES.STATUS_CHANGE,
                efj: s.efj, account: s.account, rep: resolveRepForShipment(s),
                message: `${s.loadNumber || s.efj} \u2192 ${label}`,
                detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
            }
          }
          if (changeAlerts.length > 0) setEventAlerts(p => [...changeAlerts, ...p].slice(0, 200));
        }
        prevStatusMapRef.current = newStatusMap;
      }
      // Detect new documents indexed
      if (docRes.status === "fulfilled") {
        const newDocs = docRes.value.documents || {};
        const prevDocs = prevDocMapRef.current;
        if (Object.keys(prevDocs).length > 0 && shipmentsRes.status === "fulfilled") {
          const mapped3 = shipmentsRes.value.shipments.map(mapShipment);
          const docAlerts = [];
          for (const [efj, docs] of Object.entries(newDocs)) {
            const oldDoc = prevDocs[efj] || {};
            for (const [docType, val] of Object.entries(docs)) {
              if (val && !oldDoc[docType]) {
                const s = mapped3.find(sh => sh.efj === efj || sh.efj?.replace(/^EFJ\s*/i, "") === efj);
                if (s) {
                  const typeLabel = docType.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                  docAlerts.push({ id: `doc_indexed-${efj}-${docType}-${Date.now()}`, type: ALERT_TYPES.DOC_INDEXED,
                    efj: s.efj, account: s.account, rep: resolveRepForShipment(s),
                    message: `${typeLabel} indexed for ${s.loadNumber || s.efj}`,
                    detail: s.account, timestamp: Date.now(), shipmentId: s.id });
                }
              }
            }
          }
          if (docAlerts.length > 0) setEventAlerts(p => [...docAlerts, ...p].slice(0, 200));
        }
        prevDocMapRef.current = newDocs;
      }
      // Fetch unbilled stats (silently fail if endpoint not ready)
      try {
        const ubRes = await apiFetch(`${API_BASE}/api/unbilled/stats`);
        if (ubRes.ok) setUnbilledStats(await ubRes.json());
      } catch {}
      // Fetch bot health metrics + cron status
      try {
        const [bhRes, csRes] = await Promise.allSettled([
          apiFetch(`${API_BASE}/api/bot-health`).then(r => r.ok ? r.json() : null),
          apiFetch(`${API_BASE}/api/cron-status`).then(r => r.ok ? r.json() : null),
        ]);
        if (bhRes.status === "fulfilled" && bhRes.value) setBotHealth(bhRes.value);
        if (csRes.status === "fulfilled" && csRes.value) setCronStatus(csRes.value);
      } catch {}
      // Fetch carrier directory for dray slide-over carrier info
      try {
        const crRes = await apiFetch(`${API_BASE}/api/carriers`);
        if (crRes.ok) { const crData = await crRes.json(); setCarrierDirectory(crData.carriers || []); }
      } catch {}
      // Fetch rate response alerts + inbox threads for email integration
      try {
        const [rateRes, inboxRes] = await Promise.allSettled([
          apiFetch(`${API_BASE}/api/rate-response-alerts`).then(r => r.ok ? r.json() : null),
          apiFetch(`${API_BASE}/api/inbox?days=7`).then(r => r.ok ? r.json() : null),
        ]);
        if (rateRes.status === "fulfilled" && rateRes.value) {
          const alerts = rateRes.value.alerts || [];
          const prev = prevRateAlertsRef.current;
          const newAlerts = [];
          for (const a of alerts) {
            const key = `${a.id}`;
            if (!prev.has(key)) {
              const alertType = a.email_type === "payment_escalation" ? ALERT_TYPES.PAYMENT_ESCALATION
                : (a.email_type === "carrier_invoice" || a.email_type === "carrier_rate_confirmation") ? ALERT_TYPES.SEND_FINAL_CHARGES
                : ALERT_TYPES.RATE_RESPONSE;
              newAlerts.push({
                id: `${alertType}-${a.id}-${Date.now()}`, type: alertType,
                efj: a.efj, account: "", rep: a.rep || "",
                message: alertType === ALERT_TYPES.PAYMENT_ESCALATION ? `Payment alert: ${a.efj || "Unknown"} \u2014 ${a.subject || ""}`
                  : alertType === ALERT_TYPES.SEND_FINAL_CHARGES ? `Send final charges: ${a.efj || "Unknown"}`
                  : `Rate response: ${a.sender || "Carrier"} on ${a.lane || a.efj || ""}`,
                detail: a.summary || a.subject || "", timestamp: new Date(a.sent_at || Date.now()).getTime(),
              });
            }
          }
          if (prev.size > 0 && newAlerts.length > 0) setEventAlerts(p => [...newAlerts, ...p].slice(0, 200));
          prevRateAlertsRef.current = new Set(alerts.map(a => `${a.id}`));
        }
        if (inboxRes.status === "fulfilled" && inboxRes.value) {
          setInboxThreads(inboxRes.value.threads || []);
        }
      } catch {}
      setLastSyncTime(new Date());
      setApiError(null);
    } catch (err) { console.error("API fetch error:", err); setApiError(err.message); }
  }, []);

  const refreshDocSummary = useCallback(async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/shipments/document-summary`);
      if (r.ok) { const data = await r.json(); setDocSummary(data.documents || {}); }
    } catch {}
  }, []);

  useEffect(() => {
    fetchData().then(() => setLoaded(true));
    fetchProfiles();
    const fallback = setTimeout(() => setLoaded(true), 10000);
    return () => clearTimeout(fallback);
  }, [fetchData, fetchProfiles]);
  useEffect(() => { const i = setInterval(fetchData, 90000); return () => clearInterval(i); }, [fetchData]);

  // Deep link support: ?view=billing&load=EFJ-XXXX
  useEffect(() => {
    if (!loaded || !shipments.length) return;
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view");
    const loadEfj = params.get("load");
    if (view) {
      setActiveView(view);
      if (loadEfj) {
        const match = shipments.find(s => s.efj === loadEfj);
        if (match) setSelectedShipment(match);
      }
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [loaded, shipments.length]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const handler = (e) => setSidebarCollapsed(e.matches);
    handler(mq); mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Global keyboard shortcuts: Ctrl+K command palette, ESC close modals
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+F / Cmd+F → toggle command palette
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setCmdkOpen(prev => !prev);
        setCmdkQuery("");
        setCmdkIndex(0);
        return;
      }
      if (e.key === "Escape") {
        if (cmdkOpen) { setCmdkOpen(false); return; }
        if (selectedShipment) { setSelectedShipment(null); return; }
        if (showAddForm) { setShowAddForm(false); return; }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedShipment, showAddForm, cmdkOpen]);

  const addSheetLog = useCallback((msg) => {
    setSheetLog(prev => [{ time: new Date().toLocaleTimeString(), msg }, ...prev].slice(0, 25));
  }, []);

  const filtered = useMemo(() => (Array.isArray(shipments) ? shipments : []).filter(s => {
    // Move type filter
    if (moveTypeFilter === "ftl" && !isFTLShipment(s)) return false;
    if (moveTypeFilter === "dray" && isFTLShipment(s)) return false;
    if (activeStatus !== "all" && s.status !== activeStatus) return false;
    if (activeAccount !== "All Accounts" && s.account !== activeAccount) return false;
    if (activeRep !== "All Reps") {
      const repMatch = (s.rep || "").toLowerCase() === activeRep.toLowerCase() ||
        s.account.toLowerCase() === activeRep.toLowerCase();
      if (!repMatch) return false;
    }
    if (dateFilter) {
      if (dateFilter === "pickup_today" && (!isDateToday(s.pickupDate) || s.status === "delivered")) return false;
      if (dateFilter === "pickup_tomorrow" && (!isDateTomorrow(s.pickupDate) || s.status === "delivered")) return false;
      if (dateFilter === "delivery_today" && !isDateToday(s.deliveryDate)) return false;
      if (dateFilter === "delivery_tomorrow" && (!isDateTomorrow(s.deliveryDate) || s.status === "delivered")) return false;
    }
    // Date range filter
    if (dateRangeField && dateRangeStart) {
      const fieldKey = dateRangeField === "pickup" ? "pickupDate" : "deliveryDate";
      const val = parseDate(s[fieldKey]);
      if (!val) return false;
      const start = new Date(dateRangeStart + "T00:00:00");
      const end = dateRangeEnd ? new Date(dateRangeEnd + "T23:59:59") : new Date(dateRangeStart + "T23:59:59");
      const d = new Date(val.getFullYear(), val.getMonth(), val.getDate());
      if (d < start || d > end) return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return s.loadNumber.toLowerCase().includes(q) || s.carrier.toLowerCase().includes(q) ||
        s.origin.toLowerCase().includes(q) || s.destination.toLowerCase().includes(q) ||
        s.container.toLowerCase().includes(q) || s.account.toLowerCase().includes(q) ||
        (s.notes || "").toLowerCase().includes(q) || (s.truckType || "").toLowerCase().includes(q);
    }
    return true;
  }), [shipments, activeStatus, activeAccount, activeRep, searchQuery, dateFilter, moveTypeFilter, dateRangeField, dateRangeStart, dateRangeEnd]);

  // Dynamic status counts based on move type filter
  const activeStatusList = useMemo(() => {
    if (moveTypeFilter === "ftl") return FTL_STATUSES;
    if (moveTypeFilter === "dray") return STATUSES;
    return ALL_STATUSES_COMBINED;
  }, [moveTypeFilter]);

  const statusCounts = useMemo(() => {
    // Apply all filters EXCEPT status so counts show per-status within current filter context
    const base = (Array.isArray(shipments) ? shipments : []).filter(s => {
      if (moveTypeFilter === "ftl" && !isFTLShipment(s)) return false;
      if (moveTypeFilter === "dray" && isFTLShipment(s)) return false;
      if (activeAccount !== "All Accounts" && s.account !== activeAccount) return false;
      if (activeRep !== "All Reps") {
        const repMatch = (s.rep || "").toLowerCase() === activeRep.toLowerCase() ||
          s.account.toLowerCase() === activeRep.toLowerCase();
        if (!repMatch) return false;
      }
      if (dateRangeField && dateRangeStart) {
        const fieldKey = dateRangeField === "pickup" ? "pickupDate" : "deliveryDate";
        const val = parseDate(s[fieldKey]);
        if (!val) return false;
        const start = new Date(dateRangeStart + "T00:00:00");
        const end = dateRangeEnd ? new Date(dateRangeEnd + "T23:59:59") : new Date(dateRangeStart + "T23:59:59");
        const d = new Date(val.getFullYear(), val.getMonth(), val.getDate());
        if (d < start || d > end) return false;
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return s.loadNumber.toLowerCase().includes(q) || s.carrier.toLowerCase().includes(q) ||
          s.origin.toLowerCase().includes(q) || s.destination.toLowerCase().includes(q) ||
          s.container.toLowerCase().includes(q) || s.account.toLowerCase().includes(q) ||
          (s.notes || "").toLowerCase().includes(q) || (s.truckType || "").toLowerCase().includes(q);
      }
      return true;
    });
    return activeStatusList.map(s => ({
      ...s, count: s.key === "all" ? base.length : base.filter(sh => sh.status === s.key).length,
    }));
  }, [shipments, activeStatusList, moveTypeFilter, activeAccount, activeRep, searchQuery, dateRangeField, dateRangeStart, dateRangeEnd]);

  const handleStatusUpdate = (shipmentId, newStatus) => {
    const ship = shipments.find(s => s.id === shipmentId);
    const sList = ship && isFTLShipment(ship) ? FTL_STATUSES : STATUSES;
    const statusLabel = sList.find(st => st.key === newStatus)?.label || BILLING_STATUSES.find(st => st.key === newStatus)?.label || newStatus;
    // Generate event alert
    if (ship) {
      setEventAlerts(prev => [{ id: `status_change-${ship.efj}-${newStatus}-${Date.now()}`, type: ALERT_TYPES.STATUS_CHANGE,
        efj: ship.efj, account: ship.account, rep: resolveRepForShipment(ship),
        message: `${ship.loadNumber || ship.efj} \u2192 ${statusLabel}`,
        detail: `${ship.account}${ship.carrier ? " | " + ship.carrier : ""}`, timestamp: Date.now(), shipmentId: ship.id,
      }, ...prev].slice(0, 200));
    }
    setShipments(prev => prev.map(s => {
      if (s.id === shipmentId) {
        addSheetLog(`Status -> ${statusLabel} | ${s.loadNumber}`);
        if (s.efj) {
          apiFetch(`${API_BASE}/api/v2/load/${s.efj}/status`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: statusLabel }),
          }).then(r => {
            if (r.ok) {
              setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x));
              addSheetLog(`Synced -> Postgres | ${s.loadNumber}`);
              // Delivered → auto-transition to Ready to Close Out
              if (newStatus === "delivered") {
                setTimeout(() => handleStatusUpdate(shipmentId, "ready_to_close"), 1500);
              }
              // Billed & Closed → remove from active view
              if (newStatus === "billed_closed") {
                setTimeout(() => {
                  setShipments(p => p.filter(x => x.id !== shipmentId));
                  setSelectedShipment(null);
                }, 2000);
              }
            }
            else { addSheetLog(`Sync failed (${r.status}) | ${s.loadNumber}`); setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x)); }
          }).catch(() => { addSheetLog(`Sync error | ${s.loadNumber}`); setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x)); });
        } else { setTimeout(() => { setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x)); }, 800); }
        return { ...s, status: newStatus, rawStatus: statusLabel, synced: false };
      }
      return s;
    }));
    setSelectedShipment(prev => prev ? { ...prev, status: newStatus, rawStatus: statusLabel, synced: false } : prev);
  };

  const handleFieldEdit = (shipmentId, field, value) => {
    setShipments(prev => prev.map(s => {
      if (s.id === shipmentId) {
        addSheetLog(`${field} updated | ${s.loadNumber}`);
        setTimeout(() => { setShipments(p => p.map(x => x.id === shipmentId ? { ...x, synced: true } : x)); addSheetLog(`Synced | ${s.loadNumber}`); }, 800);
        return { ...s, [field]: value, synced: false };
      }
      return s;
    }));
    setEditField(null);
  };

  // Inline field update — writes to Postgres via POST /api/v2/load/{efj}/update
  const FIELD_TO_PG = { pickup: "pickup_date", delivery: "delivery_date", eta: "eta", lfd: "lfd", carrier: "carrier", driver: "driver", origin: "origin", destination: "destination", status: "status", vessel: "vessel", bol: "bol", return_date: "return_date", ssl: "vessel", container: "container" };
  const handleFieldUpdate = async (shipment, field, value) => {
    const stateKey = field === "pickup" ? "pickupDate" : field === "delivery" ? "deliveryDate" : field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    setSelectedShipment(prev => prev && prev.id === shipment.id ? { ...prev, [stateKey]: value, synced: false } : prev);
    if (shipment.efj) {
      const pgField = FIELD_TO_PG[field] || field;
      try {
        const r = await apiFetch(`${API_BASE}/api/v2/load/${shipment.efj}/update`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [pgField]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); }
    } else {
      setTimeout(() => setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s)), 800);
    }
  };

  // Inline metadata update — writes to Postgres via POST /api/v2/load/{efj}/update
  const META_TO_PG = { truckType: "equipment_type", customerRate: "customer_rate", notes: "notes" };
  const handleMetadataUpdate = async (shipment, field, value) => {
    const stateKey = field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    setSelectedShipment(prev => prev && prev.id === shipment.id ? { ...prev, [stateKey]: value, synced: false } : prev);
    if (shipment.efj) {
      const pgField = META_TO_PG[field] || field;
      try {
        const r = await apiFetch(`${API_BASE}/api/v2/load/${shipment.efj}/update`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [pgField]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); }
    } else {
      setTimeout(() => setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s)), 800);
    }
  };

  // Inline driver field update — writes to backend via POST /api/load/{efj}/driver
  const handleDriverFieldUpdate = async (shipment, field, value) => {
    const driverFieldMap = { trailer: "trailerNumber", driverPhone: "driverPhone", carrierEmail: "carrierEmail" };
    const apiFieldMap = { trailer: "trailerNumber", driverPhone: "driverPhone", carrierEmail: "carrierEmail" };
    const stateKey = driverFieldMap[field] || field;
    setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, [stateKey]: value, synced: false } : s));
    if (shipment.efj) {
      try {
        const r = await apiFetch(`${API_BASE}/api/load/${shipment.efj}/driver`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [apiFieldMap[field] || field]: value }),
        });
        if (r.ok) {
          setShipments(prev => prev.map(s => s.id === shipment.id ? { ...s, synced: true } : s));
          addSheetLog(`${field} saved | ${shipment.loadNumber}`);
        } else { addSheetLog(`Save failed (${r.status}) | ${shipment.loadNumber}`); }
      } catch { addSheetLog(`Save error | ${shipment.loadNumber}`); }
    }
  };

  const handleAddShipment = async (data) => {
    const { pendingDocs, ...loadData } = data;
    try {
      const res = await apiFetch(`${API_BASE}/api/v2/load/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loadData),
      });
      if (!res.ok) {
        const txt = await res.text();
        addSheetLog(`Add failed (${res.status}) | ${data.efj}`);
        throw new Error(txt);
      }
      const result = await res.json();
      addSheetLog(`New row → Sheet | ${result.efj} (${result.tab})`);

      // Upload pending documents after load creation
      if (pendingDocs && pendingDocs.length > 0) {
        for (const doc of pendingDocs) {
          try {
            const fd = new FormData();
            fd.append("file", doc.file);
            fd.append("doc_type", doc.docType);
            await apiFetch(`${API_BASE}/api/load/${result.efj}/documents`, { method: "POST", body: fd });
            addSheetLog(`Doc uploaded | ${doc.file.name} → ${result.efj}`);
          } catch (docErr) {
            addSheetLog(`Doc upload failed | ${doc.file.name}: ${docErr.message}`);
          }
        }
      }

      setShowAddForm(false);
      fetchData();
    } catch (err) {
      addSheetLog(`Add error: ${err.message}`);
    }
  };

  const handleLoadClick = (s) => { setSelectedShipment(s); };

  const activeLoads = useMemo(() => filtered.filter(s => !["delivered", "issue", "cancelled", "cancelled_tonu", "empty_return", "driver_paid"].includes(s.status)).length, [filtered]);
  const inTransit = useMemo(() => filtered.filter(s => s.status === "in_transit").length, [filtered]);
  const deliveredCount = useMemo(() => filtered.filter(s => s.status === "delivered").length, [filtered]);
  const issueCount = useMemo(() => filtered.filter(s => s.status === "issue").length, [filtered]);
  const sidebarW = sidebarCollapsed ? 56 : 72;

  // Alert system
  const snapshotAlerts = useMemo(() => generateSnapshotAlerts(shipments, trackingSummary, docSummary), [shipments, trackingSummary, docSummary]);
  const allAlerts = useMemo(() => [...eventAlerts, ...snapshotAlerts].filter(a => !dismissedAlertIds.includes(a.id)), [eventAlerts, snapshotAlerts, dismissedAlertIds]);
  const handleDismissAlert = useCallback((id) => {
    setDismissedAlertIds(prev => { const next = [...prev, id]; saveDismissedAlerts(next); return next; });
  }, []);
  const handleDismissAllAlerts = useCallback(() => {
    const ids = allAlerts.map(a => a.id);
    setDismissedAlertIds(prev => { const next = [...new Set([...prev, ...ids])]; saveDismissedAlerts(next); return next; });
  }, [allAlerts]);

  const goToRepDashboard = (repName) => { setSelectedRep(repName); };
  const goBackFromRep = () => { setSelectedRep(null); };

  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", background: "#0A0E17", color: "#F0F2F5", minHeight: "100vh", display: "flex", position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        :root { --bg-base: #0A0E17; --bg-card: #141A28; --bg-elevated: #1A2236; --bg-input: #0D1119; --border-card: rgba(255,255,255,0.10); --border-emphasis: rgba(255,255,255,0.16); --text-primary: #F0F2F5; --text-secondary: #8B95A8; --text-tertiary: #5A6478; --text-muted: #3D4557; --brand-green: #00D4AA; --brand-cyan: #00A8CC; --brand-blue: #0088E8; --brand-gradient: linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8); --radius-card: 14px; --shadow-card: 0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2); --shadow-elevated: 0 4px 16px rgba(0,0,0,0.4), 0 8px 32px rgba(0,0,0,0.2); }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 5px; height: 5px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #ffffff15; border-radius: 10px; }
        .dispatch-table-wrap { scrollbar-color: #3D4557 rgba(255,255,255,0.04); }
        .dispatch-table-wrap::-webkit-scrollbar { height: 12px; width: 6px; }
        .dispatch-table-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,0.04); border-radius: 10px; }
        .dispatch-table-wrap::-webkit-scrollbar-thumb { background: #3D4557; border-radius: 10px; min-width: 40px; }
        .dispatch-table-wrap::-webkit-scrollbar-thumb:hover { background: #5A6478; }
        .dispatch-table-wrap::-webkit-scrollbar-corner { background: transparent; }
        input, select, textarea { font-family: 'Plus Jakarta Sans', sans-serif; }
        @keyframes pulse-glow { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
        @keyframes slide-up { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes slide-right { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes glow-pulse { 0%, 100% { box-shadow: 0 0 16px rgba(0,222,180,0.08); } 50% { box-shadow: 0 0 28px rgba(0,222,180,0.18); } }
        @keyframes alert-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 6px rgba(239,68,68,0.5); } 50% { opacity: 0.6; box-shadow: 0 0 12px rgba(239,68,68,0.3); } }
        @keyframes unbilled-pulse { 0%, 100% { box-shadow: 0 0 8px rgba(249,115,22,0.15); border-color: rgba(249,115,22,0.4); } 50% { box-shadow: 0 0 20px rgba(249,115,22,0.3); border-color: rgba(249,115,22,0.7); } }
        .glass { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: var(--radius-card); box-shadow: var(--shadow-card); position: relative; }
        .glass::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); border-radius: var(--radius-card) var(--radius-card) 0 0; pointer-events: none; }
        .glass-strong { background: var(--bg-elevated); border: 1px solid var(--border-emphasis); border-radius: var(--radius-card); box-shadow: var(--shadow-elevated); position: relative; }
        .glass-strong::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent); border-radius: var(--radius-card) var(--radius-card) 0 0; pointer-events: none; }
        .row-hover { transition: all 0.2s ease; } .row-hover:hover { background: rgba(255,255,255,0.04) !important; }
        .btn-primary { background: var(--brand-gradient); transition: all 0.3s ease; position: relative; overflow: hidden; }
        .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 30px -5px #00D4AA55; }
        .dash-panel { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: var(--radius-card); box-shadow: var(--shadow-card); position: relative; overflow: hidden; }
        .dash-panel::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); pointer-events: none; z-index: 1; }
        .dash-panel-title { font-size: 14px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.3px; }
        .nav-item { transition: all 0.2s ease; cursor: pointer; border: none; background: none; }
        .nav-item:hover { background: rgba(0,212,170,0.06) !important; }
        .rep-card { transition: all 0.25s ease; cursor: pointer; }
        .rep-card:hover { transform: translateY(-2px); border-color: rgba(0,212,170,0.3) !important; background: rgba(0,212,170,0.04) !important; }
        .acct-card { transition: all 0.2s ease; cursor: pointer; }
        .acct-card:hover { border-color: rgba(0,212,170,0.3) !important; background: rgba(0,212,170,0.05) !important; }
        .status-card { transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; }
        .status-card:hover { transform: translateY(-3px) scale(1.02); }
        .metric-card { position: relative; overflow: hidden; }
        input[type="date"]::-webkit-calendar-picker-indicator, input[type="time"]::-webkit-calendar-picker-indicator { filter: invert(0.7); cursor: pointer; padding: 4px; }
        input[type="date"], input[type="time"] { min-height: 32px; }
        @media (max-width: 768px) {
          .dash-grid-2 { grid-template-columns: 1fr !important; }
          .dash-sidebar { display: none !important; }
          .dash-topbar { padding: 8px 12px !important; }
          .dash-content-area { padding: 0 10px !important; }
          .dash-stat-row { flex-wrap: wrap !important; }
          .dash-stat-row > div { flex: 1 1 30% !important; min-width: 90px !important; }
        }
        @media (max-width: 480px) {
          .dash-stat-row > div { padding: 10px 8px !important; }
          .dash-stat-row .stat-value { font-size: 22px !important; }
          .dash-stat-row .stat-label { font-size: 9px !important; }
        }
      `}</style>

      {/* Ambient BG */}
      <div style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
        <div style={{ position: "absolute", top: "-20%", left: "-10%", width: "50%", height: "50%", background: "radial-gradient(circle, #00D4AA06 0%, transparent 70%)" }} />
        <div style={{ position: "absolute", bottom: "-20%", right: "-10%", width: "60%", height: "60%", background: "radial-gradient(circle, #0088E806 0%, transparent 70%)" }} />
      </div>

      {/* ═══ SIDEBAR ═══ */}
      <div className="dash-sidebar" style={{ width: sidebarW, minHeight: "100vh", background: "#0D1119", borderRight: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 16, gap: 4, position: "relative", zIndex: 20, flexShrink: 0 }}>
        <div style={{ width: 52, height: 52, borderRadius: 12, background: "#0F1A14", border: "1px solid rgba(0,222,180,0.25)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, animation: "glow-pulse 3s ease infinite", cursor: "pointer", overflow: "hidden", padding: 2, boxShadow: "0 0 20px rgba(0,212,170,0.15)" }}
          onClick={() => { setActiveView("dashboard"); setSelectedRep(null); }}>
          <img src="/logo.svg" alt="CSL" style={{ width: 44, height: 44, objectFit: "contain", filter: "hue-rotate(-15deg) saturate(1.3)" }} />
        </div>
        {NAV_ITEMS.map(item => {
          const isActive = activeView === item.key;
          return (
            <button key={item.key} className="nav-item"
              onClick={() => { setActiveView(item.key); setSelectedRep(null); }}
              style={{ width: sidebarW - 12, padding: "10px 0", borderRadius: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
                background: isActive ? "rgba(0,212,170,0.10)" : "transparent",
                borderLeft: isActive ? "3px solid #00D4AA" : "3px solid transparent",
                color: isActive ? "#00D4AA" : "#8B95A8" }}>
              <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d={item.icon} /></svg>
              {!sidebarCollapsed && <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.5px" }}>{item.label}</span>}
            </button>
          );
        })}
      </div>

      {/* ═══ COMMAND PALETTE ═══ */}
      <CommandPalette open={cmdkOpen} query={cmdkQuery} setQuery={setCmdkQuery}
        index={cmdkIndex} setIndex={setCmdkIndex} shipments={shipments}
        onSelect={(s) => handleLoadClick(s)} onClose={() => setCmdkOpen(false)} />

      {/* ═══ MAIN CONTENT ═══ */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 10 }}>
        {/* Top Bar */}
        <div className="dash-topbar" style={{ padding: "12px 24px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.08)", background: "#0D1119" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 16, fontWeight: 800, background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>COMMON SENSE</span>
            <span style={{ fontSize: 10, color: "#8B95A8", fontWeight: 400, letterSpacing: "2px", textTransform: "uppercase" }}>Logistics</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {dataSource === "sheets" && (
              <div className="glass" style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 100, fontSize: 10, color: "#f59e0b", fontWeight: 600, border: "1px solid rgba(245,158,11,0.3)", background: "rgba(245,158,11,0.08)" }}>
                SHEETS MODE
              </div>
            )}
            <ClockDisplay lastSyncTime={lastSyncTime} apiError={apiError} />
          </div>
        </div>

        {/* View Content */}
        <div className="dash-content-area" style={{ flex: 1, overflow: "auto", padding: "0 24px 24px" }}>
          {apiError && (
            <div style={{ margin: "8px 0", padding: "10px 16px", borderRadius: 10, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", display: "flex", alignItems: "center", justifyContent: "space-between", animation: "slide-up 0.3s ease" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "#f87171", fontSize: 13 }}>⚠</span>
                <span style={{ fontSize: 11, color: "#f87171", fontWeight: 600 }}>API Error: {apiError}</span>
              </div>
              <button onClick={() => setApiError(null)} style={{ background: "none", border: "none", color: "#f87171", cursor: "pointer", fontSize: 12, padding: "2px 6px" }}>✕</button>
            </div>
          )}
          {!loaded ? (
            <div style={{ padding: "60px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 16, animation: "fade-in 0.3s ease" }}>
              <div style={{ width: 32, height: 32, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
              <div style={{ fontSize: 12, color: "#8B95A8", fontWeight: 500 }}>Loading dispatch data...</div>
            </div>
          ) : (<>
          {activeView === "dashboard" && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 0 4px" }}>
              {selectedRep && (
                <select value={selectedRep} onChange={e => setSelectedRep(e.target.value)}
                  style={{ padding: "7px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", outline: "none" }}>
                  {ALL_REP_NAMES.map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
                </select>
              )}
            </div>
          )}
          {activeView === "dashboard" && !selectedRep && (
            <OverviewView loaded={loaded} shipments={shipments} apiStats={apiStats}
              accountOverview={accountOverview} apiError={apiError} onSelectRep={goToRepDashboard}
              unbilledStats={unbilledStats} repProfiles={repProfiles}
              trackingSummary={trackingSummary} handleLoadClick={handleLoadClick}
              alerts={allAlerts} onDismissAlert={handleDismissAlert} onDismissAll={handleDismissAllAlerts}
              onNavigateDispatch={() => setActiveView("dispatch")} onFilterStatus={(s) => { setDateFilter(null); setActiveStatus(s); setActiveView("dispatch"); }}
              onFilterAccount={(acct) => { if (acct === "Boviet" || acct === "Tolead") { goToRepDashboard(acct); } else { setDateFilter(null); setActiveAccount(acct); setActiveView("dispatch"); } }}
              onFilterDate={(df) => { setDateFilter(df); setActiveStatus("all"); setActiveAccount("All Accounts"); setActiveView("dispatch"); }}
              onNavigateUnbilled={() => setActiveView("billing")} />
          )}
          {activeView === "dashboard" && selectedRep && (
            <RepDashboardView repName={selectedRep} shipments={shipments} onBack={goBackFromRep}
              handleStatusUpdate={handleStatusUpdate} handleLoadClick={handleLoadClick}
              handleFieldUpdate={handleFieldUpdate} handleMetadataUpdate={handleMetadataUpdate}
              handleDriverFieldUpdate={handleDriverFieldUpdate}
              repProfiles={repProfiles} onProfileUpdate={fetchProfiles}
              trackingSummary={trackingSummary} docSummary={docSummary}
              inboxThreads={inboxThreads}
              onNavigateInbox={(tab) => { setActiveView("inbox"); }} />
          )}
          {activeView === "dispatch" && (
            <DispatchView loaded={loaded} shipments={shipments} filtered={filtered} accounts={accounts}
              activeStatus={activeStatus} setActiveStatus={setActiveStatus}
              activeAccount={activeAccount} setActiveAccount={setActiveAccount}
              activeRep={activeRep} setActiveRep={setActiveRep}
              searchQuery={searchQuery} setSearchQuery={setSearchQuery}
              statusCounts={statusCounts} selectedShipment={selectedShipment} setSelectedShipment={setSelectedShipment}
              editField={editField} setEditField={setEditField} editValue={editValue} setEditValue={setEditValue}
              sheetLog={sheetLog} handleStatusUpdate={handleStatusUpdate} handleFieldEdit={handleFieldEdit}
              handleLoadClick={handleLoadClick} activeLoads={activeLoads} inTransit={inTransit}
              deliveredCount={deliveredCount} issueCount={issueCount}
              onAddLoad={() => setShowAddForm(true)} addSheetLog={addSheetLog} setShipments={setShipments}
              podUploading={podUploading} setPodUploading={setPodUploading} podUploadMsg={podUploadMsg} setPodUploadMsg={setPodUploadMsg}
              trackingSummary={trackingSummary} docSummary={docSummary}
              dateFilter={dateFilter} setDateFilter={setDateFilter}
              moveTypeFilter={moveTypeFilter} setMoveTypeFilter={setMoveTypeFilter}
              dateRangeField={dateRangeField} setDateRangeField={setDateRangeField}
              dateRangeStart={dateRangeStart} setDateRangeStart={setDateRangeStart}
              dateRangeEnd={dateRangeEnd} setDateRangeEnd={setDateRangeEnd}
              handleFieldUpdate={handleFieldUpdate}
              handleMetadataUpdate={handleMetadataUpdate}
              handleDriverFieldUpdate={handleDriverFieldUpdate} />
          )}
          {activeView === "history" && (
            <HistoryView loaded={loaded} handleLoadClick={handleLoadClick} />
          )}
          {activeView === "inbox" && (
            <InboxView handleLoadClick={handleLoadClick} />
          )}
          {activeView === "quotes" && (
            <RateIQView />
          )}
          {activeView === "analytics" && (
            <AnalyticsView loaded={loaded} botStatus={botStatus} botHealth={botHealth} cronStatus={cronStatus} sheetLog={sheetLog} />
          )}
          {activeView === "billing" && (
            <BillingView loaded={loaded} shipments={shipments} handleStatusUpdate={handleStatusUpdate}
              handleLoadClick={handleLoadClick} setSelectedShipment={setSelectedShipment}
              unbilledOrders={unbilledOrders} setUnbilledOrders={setUnbilledOrders}
              unbilledStats={unbilledStats} setUnbilledStats={setUnbilledStats} />
          )}
          {activeView === "bol" && (
            <BOLGeneratorView loaded={loaded} />
          )}
          </>)}
        </div>
      </div>

      {showAddForm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, animation: "fade-in 0.2s ease" }}
          onClick={() => setShowAddForm(false)}>
          <div onClick={e => e.stopPropagation()} className="glass-strong" style={{ borderRadius: 20, padding: 28, width: 460, maxHeight: "85vh", overflow: "auto", animation: "slide-up 0.3s ease", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5", marginBottom: 4 }}>New Load</div>
            <div style={{ fontSize: 11, color: "#8B95A8", marginBottom: 20 }}>Create a new shipment</div>
            <AddForm onSubmit={handleAddShipment} onCancel={() => setShowAddForm(false)} accounts={accounts} />
          </div>
        </div>
      )}

      <LoadSlideOver selectedShipment={selectedShipment} setSelectedShipment={setSelectedShipment}
        shipments={shipments} setShipments={setShipments} handleStatusUpdate={handleStatusUpdate}
        editField={editField} setEditField={setEditField} editValue={editValue} setEditValue={setEditValue}
        handleFieldEdit={handleFieldEdit} addSheetLog={addSheetLog}
        carrierDirectory={carrierDirectory}
        onDocChange={refreshDocSummary} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// OVERVIEW VIEW (replaces old DashboardView)
// ═══════════════════════════════════════════════════════════════
function OverviewView({ loaded, shipments, apiStats, accountOverview, apiError, onSelectRep, onNavigateDispatch, onFilterStatus, onFilterDate, onFilterAccount, unbilledStats, onNavigateUnbilled, repProfiles, trackingSummary, handleLoadClick, alerts, onDismissAlert, onDismissAll }) {
  const [alertFilter, setAlertFilter] = useState("all");

  // Status pipeline data
  const statusGroups = {};
  STATUSES.filter(s => s.key !== "all").forEach(s => {
    statusGroups[s.key] = shipments.filter(sh => sh.status === s.key).length;
  });
  const total = shipments.length || 1;

  // Today's action items
  const pickupsToday = shipments.filter(s => isDateToday(s.pickupDate) && s.status !== "delivered");
  const pickupsTomorrow = shipments.filter(s => isDateTomorrow(s.pickupDate) && s.status !== "delivered");
  const deliveriesToday = shipments.filter(s => isDateToday(s.deliveryDate));
  const deliveriesTomorrow = shipments.filter(s => isDateTomorrow(s.deliveryDate) && s.status !== "delivered");

  // Tracking Behind — FTL loads behind on Macropoint
  const trackingBehind = shipments.filter(s => {
    const efjBare = s.efj?.replace(/^EFJ\s*/i, "");
    const t = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
    return t && (t.behindSchedule || t.cantMakeIt);
  });

  // Loads to Cover — unassigned status (Boviet, Tolead, etc.)
  const loadsToCover = shipments.filter(s =>
    s.rawStatus?.toLowerCase() === "unassigned" && !["delivered", "empty_return"].includes(s.status)
  );

  // Operational stat card counts
  const isNonTerminal = (s) => !["delivered", "empty_return"].includes(s.status);
  const activeCount = shipments.filter(isNonTerminal).length;
  const pickingUpCount = shipments.filter(s => isNonTerminal(s) && (isDateToday(s.pickupDate) || isDateTomorrow(s.pickupDate))).length;
  const deliveringCount = shipments.filter(s => isDateToday(s.deliveryDate) && s.status !== "empty_return").length;
  const inTransitCount = shipments.filter(s => isNonTerminal(s) && s.pickupDate && !s.deliveryDate && !isDateToday(s.pickupDate) && !isDateTomorrow(s.pickupDate)).length;
  const upcomingCount = shipments.filter(s => {
    if (!isNonTerminal(s)) return false;
    if (s.moveType === "FTL") return s.pickupDate && isDateFuture(s.pickupDate);
    return s.eta && !isDatePast(s.eta);
  }).length;

  // Team data
  const repData = ALL_REP_NAMES.map(name => {
    const repShips = getRepShipments(shipments, name);
    const incoming = repShips.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length;
    const active = repShips.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length;
    const behindSchedule = repShips.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status)).length;
    const delivered = repShips.filter(s => s.status === "delivered").length;
    const invoiced = repShips.filter(s => s._invoiced).length;
    const onSchedule = repShips.filter(s =>
      !["delivered", "empty_return"].includes(s.status) &&
      !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))
    ).length;
    const unbilled = (unbilledStats?.by_rep || []).find(r => r.rep === name)?.cnt || 0;
    return {
      name, color: REP_COLORS[name] || "#94a3b8",
      total: repShips.length, incoming, active, onSchedule, behindSchedule, delivered, invoiced, unbilled,
    };
  });

  // Alert filtering by rep
  const alertReps = [...new Set((alerts || []).map(a => a.rep).filter(Boolean))];
  const filteredAlerts = alertFilter === "all" ? (alerts || []) : (alerts || []).filter(a => a.rep === alertFilter);
  const alertTabs = [
    { id: "all", label: "All", count: (alerts || []).length },
    ...alertReps.map(name => ({
      id: name, label: name, count: (alerts || []).filter(a => a.rep === name).length, color: REP_COLORS[name] || "#94a3b8",
    })),
  ];

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      {/* Title */}
      <div style={{ padding: "16px 0 10px" }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em", margin: 0, lineHeight: 1.2 }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>DISPATCH </span>
          <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>OVERVIEW</span>
        </h1>
        <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2, letterSpacing: "0.01em" }}>Real-time logistics across all sheets</div>
      </div>

      {/* Status Pipeline Bar */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: "flex", height: 6, borderRadius: 100, gap: 2, background: "rgba(255,255,255,0.04)" }}>
          {STATUSES.filter(s => s.key !== "all").map(s => {
            const count = statusGroups[s.key] || 0;
            if (count === 0) return null;
            return (
              <div key={s.key} title={`${s.label}: ${count}`}
                style={{ width: `${(count / total) * 100}%`, background: STATUS_COLORS[s.key]?.main, cursor: "pointer", transition: "all 0.5s ease", borderRadius: 100 }}
                onMouseEnter={e => e.currentTarget.style.filter = "brightness(1.2)"}
                onMouseLeave={e => e.currentTarget.style.filter = "none"}
                onClick={() => onFilterStatus(s.key)} />
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
          {STATUSES.filter(s => s.key !== "all").map(s => {
            const count = statusGroups[s.key] || 0;
            if (count === 0) return null;
            return (
              <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }} onClick={() => onFilterStatus(s.key)}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_COLORS[s.key]?.main }} />
                <span style={{ fontSize: 10, color: "#8B95A8", fontWeight: 500 }}>{s.label}</span>
                <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{count}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Operational Stats Row — clickable stat cards */}
      <div className="dash-stat-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {[
          { label: "Active", value: activeCount, color: "#F0F2F5", indicator: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", action: () => onFilterStatus("all"), emphasis: true },
          { label: "Picking Up", value: pickingUpCount, color: "#3B82F6", indicator: "#3B82F6", action: () => onFilterDate("pickup_today") },
          { label: "Delivering", value: deliveringCount, color: "#22C55E", indicator: "#22C55E", action: () => onFilterDate("delivery_today") },
          { label: "In Transit", value: inTransitCount, color: "#60A5FA", indicator: "#60A5FA", action: () => onFilterStatus("in_transit") },
          { label: "Upcoming", value: upcomingCount, color: "#F59E0B", indicator: "#F59E0B", action: () => onFilterDate("upcoming") },
          { label: "Unbilled", value: unbilledStats?.count || 0, color: "#F97316", indicator: "#F97316", action: onNavigateUnbilled, emphasis: true, pulse: true },
        ].map((s, i) => {
          const isUnbilledPulsing = s.pulse && s.value > 0;
          return (
          <div key={i} onClick={s.action}
            style={{ flex: s.emphasis ? 1.4 : 1, minWidth: s.emphasis ? 100 : 0, background: isUnbilledPulsing ? "rgba(249,115,22,0.06)" : "#141A28", border: `1px solid ${isUnbilledPulsing ? "rgba(249,115,22,0.4)" : "rgba(255,255,255,0.10)"}`, borderRadius: 14, padding: "16px 16px", cursor: "pointer", position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)", transition: "border-color 0.2s, box-shadow 0.2s", animation: isUnbilledPulsing ? "unbilled-pulse 2.5s ease infinite" : "none" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.7)" : "rgba(255,255,255,0.16)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.4), 0 8px 32px rgba(0,0,0,0.2)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = isUnbilledPulsing ? "rgba(249,115,22,0.4)" : "rgba(255,255,255,0.10)"; e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2)"; }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: s.emphasis ? 3 : 2, background: s.indicator, borderRadius: "0 0 2px 2px" }} />
            <div className="stat-value" style={{ fontSize: s.emphasis ? 32 : 24, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1, color: s.color, marginBottom: 2 }}>{s.value}</div>
            <div className="stat-label" style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
          </div>
          );
        })}
      </div>

      {/* Row 1: Today's Actions + Live Alerts */}
      <div className="dash-grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14, animation: loaded ? "slide-up 0.4s ease 0.1s both" : "none" }}>
        {/* Today's Action Items */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14 }}>📋</span> Today's Actions
            </div>
            <span style={{ fontSize: 11, color: "#00D4AA", cursor: "pointer", fontWeight: 600 }} onClick={onNavigateDispatch}>View all →</span>
          </div>
          {[
            { label: "Pickups Today", items: pickupsToday, color: "#3B82F6", icon: "↑", filterKey: "pickup_today" },
            { label: "Pickups Tomorrow", items: pickupsTomorrow, color: "#00A8CC", icon: "↗", filterKey: "pickup_tomorrow" },
            { label: "Deliveries Today", items: deliveriesToday, color: "#22C55E", icon: "↓", filterKey: "delivery_today" },
            { label: "Deliveries Tomorrow", items: deliveriesTomorrow, color: "#10B981", icon: "↘", filterKey: "delivery_tomorrow" },
            { label: "Tracking Behind", items: trackingBehind, color: "#F97316", icon: "📡", statusKey: "issue" },
            { label: "Loads to Cover", items: loadsToCover, color: "#EF4444", icon: "🔴", statusKey: "pending" },
          ].map((group, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ fontSize: 10, color: group.color }}>{group.icon}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8" }}>{group.label}</span>
                </div>
                <span style={{ fontSize: 13, fontWeight: 800, color: group.items.length > 0 ? group.color : "#334155", fontFamily: "'JetBrains Mono', monospace" }}>
                  {group.items.length}
                </span>
              </div>
              {group.items.length > 0 && (() => {
                const acctCounts = {};
                group.items.forEach(s => { acctCounts[s.account] = (acctCounts[s.account] || 0) + 1; });
                const sorted = Object.entries(acctCounts).sort((a, b) => b[1] - a[1]);
                return (
                <div style={{ marginLeft: 15, marginBottom: 4 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px" }}>
                    {sorted.map(([acct, cnt]) => (
                      <div key={acct} style={{ fontSize: 10, color: "#5A6478", padding: "2px 0", display: "flex", gap: 4, alignItems: "center" }}>
                        <span style={{ color: "#F0F2F5", fontWeight: 600 }}>{acct}</span>
                        <span style={{ color: group.color, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700 }}>{cnt}</span>
                      </div>
                    ))}
                  </div>
                  <div onClick={() => group.filterKey ? onFilterDate && onFilterDate(group.filterKey) : group.statusKey ? onFilterStatus && onFilterStatus(group.statusKey) : null}
                    style={{ fontSize: 9, color: group.color, padding: "2px 0", cursor: "pointer", fontWeight: 600, marginTop: 2 }}
                    onMouseEnter={e => e.currentTarget.style.opacity = "0.7"}
                    onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                    View all →
                  </div>
                </div>
                );
              })()}
            </div>
          ))}
          {pickupsToday.length === 0 && pickupsTomorrow.length === 0 && deliveriesToday.length === 0 && deliveriesTomorrow.length === 0 && trackingBehind.length === 0 && loadsToCover.length === 0 && (
            <div style={{ textAlign: "center", padding: 20, color: "#3D4557", fontSize: 11 }}>No action items for today</div>
          )}
        </div>

        {/* Live Alerts */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div className="dash-panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14 }}>{"\u26A1"}</span> Live Alerts
              {filteredAlerts.length > 0 && <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#00D4AA", fontWeight: 700 }}>{filteredAlerts.length}</span>}
            </div>
            {filteredAlerts.length > 0 && (
              <button onClick={onDismissAll}
                style={{ padding: "4px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#5A6478", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s ease" }}
                onMouseEnter={e => { e.currentTarget.style.color = "#8B95A8"; }}
                onMouseLeave={e => { e.currentTarget.style.color = "#5A6478"; }}>
                Clear All
              </button>
            )}
          </div>
          {/* Rep filter tabs */}
          <div style={{ display: "flex", gap: 2, marginBottom: 12, background: "#0D1119", borderRadius: 10, padding: 3, width: "fit-content", flexWrap: "wrap" }}>
            {alertTabs.map(t => (
              <button key={t.id} onClick={() => setAlertFilter(t.id)}
                style={{ padding: "6px 12px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 500, cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s ease",
                  background: alertFilter === t.id ? "#1E2738" : "transparent",
                  boxShadow: alertFilter === t.id ? "0 1px 4px rgba(0,0,0,0.3)" : "none",
                  color: alertFilter === t.id ? "#F0F2F5" : "#8B95A8" }}>
                {t.label}{t.count > 0 && <span style={{ marginLeft: 4, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: alertFilter === t.id ? (t.color || "#00D4AA") : "#5A6478" }}>{t.count}</span>}
              </button>
            ))}
          </div>
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            {filteredAlerts.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "#3D4557", fontSize: 12 }}>No active alerts</div>}
            {filteredAlerts.map(alert => {
              const config = ALERT_TYPE_CONFIG[alert.type] || ALERT_TYPE_CONFIG.status_change;
              const alertShipment = alert.shipmentId ? shipments.find(s => s.id === alert.shipmentId) : null;
              return (
                <div key={alert.id} style={{ padding: "8px 10px", borderRadius: 8, marginBottom: 2, display: "flex", alignItems: "center", gap: 8, cursor: alertShipment ? "pointer" : "default", transition: "background 0.15s ease" }}
                  onClick={() => alertShipment && handleLoadClick(alertShipment)}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <span style={{ fontSize: 12, width: 20, textAlign: "center", flexShrink: 0, color: config.color }}>{config.icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{alert.message}</div>
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 1 }}>{alert.detail}{alert.timestamp ? ` \u00B7 ${timeAgo(alert.timestamp)}` : ""}</div>
                  </div>
                  <span style={{ fontSize: 8, fontWeight: 600, padding: "2px 6px", borderRadius: 6, background: `${config.color}18`, color: config.color, border: `1px solid ${config.color}33`, flexShrink: 0, whiteSpace: "nowrap" }}>{config.label}</span>
                  <span onClick={(e) => { e.stopPropagation(); onDismissAlert(alert.id); }}
                    style={{ fontSize: 12, color: "#3D4557", cursor: "pointer", flexShrink: 0, padding: "0 2px", transition: "color 0.15s ease" }}
                    onMouseEnter={e => e.currentTarget.style.color = "#8B95A8"}
                    onMouseLeave={e => e.currentTarget.style.color = "#3D4557"}>&times;</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Row 2: Team Load Distribution + Account Overview */}
      <div className="dash-grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, animation: loaded ? "slide-up 0.4s ease 0.2s both" : "none" }}>
        {/* Team */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div className="dash-panel-title" style={{ marginBottom: 10 }}>Team</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {repData.map(r => (
              <div key={r.name} className="rep-card"
                onClick={() => onSelectRep(r.name)}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderRadius: 10, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer" }}>
                {repProfiles[r.name]?.avatar_url ? (
                  <img src={`${API_BASE}${repProfiles[r.name].avatar_url}`} alt={r.name}
                    style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover", flexShrink: 0, border: `2px solid ${r.color}66` }} />
                ) : (
                  <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg, ${r.color}33, ${r.color}66)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0 }}>
                    {r.name.slice(0, 2).toUpperCase()}
                  </div>
                )}
                <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{r.name}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{r.total}</span>
                    {r.behindSchedule > 0 && <span style={{ fontSize: 9, color: "#EF4444", fontWeight: 700 }}>{r.behindSchedule} behind</span>}
                  </div>
                </div>
                <div style={{ width: 50, height: 3, borderRadius: 100, overflow: "hidden", background: "rgba(255,255,255,0.04)", flexShrink: 0 }}>
                  {r.total > 0 && <div style={{ width: `${((r.total - r.delivered) / Math.max(r.total, 1)) * 100}%`, height: "100%", background: r.color, borderRadius: 100 }} />}
                </div>
                <span style={{ color: "#3D4557", fontSize: 14, flexShrink: 0 }}>›</span>
              </div>
            ))}
          </div>
        </div>

        {/* Account Overview */}
        <div className="dash-panel" style={{ padding: 16 }}>
          <div className="dash-panel-title" style={{ marginBottom: 10 }}>Account Overview</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {accountOverview.slice(0, 10).map((acct, i) => {
            const maxLoads = accountOverview.length > 0 ? accountOverview[0].loads : 1;
            const pct = maxLoads > 0 ? (acct.loads / maxLoads) * 100 : 0;
            return (
              <div key={i} onClick={() => onFilterAccount && onFilterAccount(acct.name)}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", borderRadius: 8, transition: "background 0.15s ease", cursor: "pointer" }}
                onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                <div style={{ width: 24, height: 24, borderRadius: 6, background: `linear-gradient(135deg, ${acct.color}33, ${acct.color}66)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{acct.name[0]}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: "#F0F2F5", fontWeight: 600, marginBottom: 4 }}>{acct.name}</div>
                  <div style={{ height: 3, borderRadius: 100, background: "rgba(255,255,255,0.04)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct}%`, borderRadius: 100, background: `linear-gradient(90deg, ${acct.color}, ${acct.color}88)`, transition: "width 0.8s ease" }} />
                  </div>
                </div>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 13 }}>{acct.loads}</span>
                {acct.alerts > 0 && <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 6, background: "#EF444418", color: "#F87171", fontWeight: 700, border: "1px solid #EF444422", fontFamily: "'JetBrains Mono', monospace" }}>{acct.alerts}</span>}
              </div>
            );
          })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// REP DASHBOARD VIEW
// ═══════════════════════════════════════════════════════════════
function RepDashboardView({ repName, shipments, onBack, handleStatusUpdate, handleLoadClick, handleFieldUpdate, handleMetadataUpdate, handleDriverFieldUpdate, repProfiles, onProfileUpdate, trackingSummary, docSummary, inboxThreads, onNavigateInbox }) {
  const [expandedAccount, setExpandedAccount] = useState(null);
  const [bovietTab, setBovietTab] = useState("Piedra");
  const [toleadHub, setToleadHub] = useState("ORD");
  const [opsTableFilter, setOpsTableFilter] = useState("all");
  const [masterTableFilter, setMasterTableFilter] = useState("all");
  const [repViewMode, setRepViewMode] = useState("dray"); // "dray" | "ftl"
  const [inlineEditId, setInlineEditId] = useState(null);
  const [inlineEditField, setInlineEditField] = useState(null);
  const [inlineEditValue, setInlineEditValue] = useState("");
  const [repColumnFilters, setRepColumnFilters] = useState({});
  const [repOpenFilterCol, setRepOpenFilterCol] = useState(null);
  const [filterDropdownPos, setFilterDropdownPos] = useState({ top: 0, left: 0 });

  // Close column filter dropdown on outside click
  useEffect(() => {
    if (!repOpenFilterCol) return;
    const handler = (e) => { if (!e.target.closest('.col-filter-dd')) setRepOpenFilterCol(null); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [repOpenFilterCol]);

  const isMaster = MASTER_REPS.includes(repName);
  const isBoviet = repName === "Boviet";
  const isTolead = repName === "Tolead";
  const color = REP_COLORS[repName] || "#94a3b8";

  const repShipments = getRepShipments(shipments, repName);
  const incoming = repShipments.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length;
  const activeCount = repShipments.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length;
  const onSchedule = repShipments.filter(s => !["delivered", "empty_return"].includes(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))).length;
  const behindSchedule = repShipments.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status)).length;
  const delivered = repShipments.filter(s => s.status === "delivered").length;
  const invoiced = repShipments.filter(s => s._invoiced).length;

  // For master reps: group by account
  const accountGroups = isMaster ? (REP_ACCOUNTS[repName] || []).map(acctName => {
    const acctShips = repShipments.filter(s => s.account.toLowerCase() === acctName.toLowerCase());
    return {
      name: acctName,
      ships: acctShips,
      incoming: acctShips.filter(s => ["at_port", "on_vessel", "pending"].includes(s.status)).length,
      active: acctShips.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)).length,
      onSchedule: acctShips.filter(s => !["delivered", "empty_return"].includes(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))).length,
      behind: acctShips.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status)).length,
      delivered: acctShips.filter(s => s.status === "delivered").length,
      invoiced: acctShips.filter(s => s._invoiced).length,
    };
  }) : [];

  // For Boviet: filter by project
  const bovietShips = isBoviet ? repShipments.filter(s => {
    if (!s.project) return bovietTab === "Piedra"; // default to Piedra if no project
    return s.project.toLowerCase().includes(bovietTab.toLowerCase());
  }) : [];

  // For Tolead: filter by hub field from backend
  const toleadShips = isTolead ? repShipments.filter(s => {
    return (s.hub || "ORD") === toleadHub;
  }) : [];

  // Which shipments to show in the table
  const displayShipsBase = isMaster
    ? (expandedAccount ? repShipments.filter(s => s.account.toLowerCase() === expandedAccount.toLowerCase()) : repShipments)
    : isBoviet ? bovietShips : toleadShips;

  // Apply master rep table filter
  const displayShipsFiltered = isMaster && masterTableFilter !== "all" ? displayShipsBase.filter(s => {
    if (masterTableFilter === "incoming") return ["at_port", "on_vessel", "pending"].includes(s.status);
    if (masterTableFilter === "active") return !["delivered", "empty_return"].includes(s.status);
    if (masterTableFilter === "on_schedule") return !["delivered", "empty_return"].includes(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)));
    if (masterTableFilter === "behind") return (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status);
    if (masterTableFilter === "delivered") return s.status === "delivered";
    if (masterTableFilter === "invoiced") return s._invoiced;
    if (masterTableFilter === "pu_today") return isDateToday(s.pickupDate) && s.status !== "delivered";
    if (masterTableFilter === "pu_tomorrow") return isDateTomorrow(s.pickupDate) && s.status !== "delivered";
    if (masterTableFilter === "del_today") return isDateToday(s.deliveryDate);
    if (masterTableFilter === "del_tomorrow") return isDateTomorrow(s.deliveryDate) && s.status !== "delivered";
    if (masterTableFilter === "needs_driver") return s.rawStatus?.toLowerCase() === "unassigned" && !["delivered", "empty_return"].includes(s.status);
    if (masterTableFilter === "awaiting_pod") { if (s.status !== "delivered") return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); return !(docSummary?.[eb] || docSummary?.[s.efj])?.pod; }
    // Status key filter (from dropdown)
    if ([...STATUSES, ...FTL_STATUSES].some(st => st.key === masterTableFilter && st.key !== "all")) return s.status === masterTableFilter;
    return true;
  }) : displayShipsBase;

  // Both views show the same data — only the grid layout changes
  const displayShips = displayShipsFiltered;

  // Action summary data (shared across all rep views)
  const isOps = isBoviet || isTolead;
  const actionBase = displayShipsBase; // unfiltered for pill counts
  const actionPuToday = actionBase.filter(s => isDateToday(s.pickupDate) && s.status !== "delivered");
  const actionPuTmrw = actionBase.filter(s => isDateTomorrow(s.pickupDate) && s.status !== "delivered");
  const actionDelToday = actionBase.filter(s => isDateToday(s.deliveryDate));
  const actionDelTmrw = actionBase.filter(s => isDateTomorrow(s.deliveryDate) && s.status !== "delivered");
  const actionNoDriver = actionBase.filter(s => s.rawStatus?.toLowerCase() === "unassigned" && !["delivered", "empty_return"].includes(s.status));
  const actionBehind = actionBase.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status));
  const actionNoPod = actionBase.filter(s => { if (s.status !== "delivered") return false; const eb = (s.efj || "").replace(/^EFJ\s*/i, ""); return !(docSummary?.[eb] || docSummary?.[s.efj])?.pod; });
  const actionActive = actionBase.filter(s => !["delivered", "empty_return"].includes(s.status));

  // Inbox-derived pill data for this rep
  const repAccts = (REP_ACCOUNTS[repName] || []).map(a => a.toLowerCase());
  const repInboxThreads = useMemo(() => {
    if (!inboxThreads?.length) return [];
    return inboxThreads.filter(t => {
      const threadAcct = (t.account || "").toLowerCase();
      if (repAccts.some(a => threadAcct.includes(a))) return true;
      // For Boviet/Tolead, match on account name
      if (repName === "Boviet" && threadAcct.includes("boviet")) return true;
      if (repName === "Tolead" && threadAcct.includes("tolead")) return true;
      // Match by rep name in suggested_rep
      const tRep = (t.suggested_rep || "").toLowerCase();
      if (tRep && tRep === repName.toLowerCase()) return true;
      // Match by EFJ — check if any of the rep's shipments match the thread EFJ
      if (t.efj) {
        const tEfj = t.efj.replace(/^EFJ\s*/i, "").toLowerCase();
        return actionBase.some(s => (s.efj || "").replace(/^EFJ\s*/i, "").toLowerCase() === tEfj);
      }
      return false;
    });
  }, [inboxThreads, repName, actionBase]);
  const inboxNeedsReply = repInboxThreads.filter(t => t.needs_reply && t.email_type !== "rate_outreach").length;
  const inboxRateResponses = repInboxThreads.filter(t => t.email_type === "carrier_rate_response").length;

  const opsBase = displayShipsFiltered;
  const opsPickupsToday = opsBase.filter(s => isDateToday(s.pickupDate) && s.status !== "delivered");
  const opsPickupsTomorrow = opsBase.filter(s => isDateTomorrow(s.pickupDate) && s.status !== "delivered");
  const opsDeliveriesToday = opsBase.filter(s => isDateToday(s.deliveryDate));
  const opsDeliveriesTomorrow = opsBase.filter(s => isDateTomorrow(s.deliveryDate) && s.status !== "delivered");
  const needsDriver = opsBase.filter(s => s.rawStatus?.toLowerCase() === "unassigned" && !["delivered", "empty_return"].includes(s.status));
  const opsBehind = opsBase.filter(s => (s.status === "issue" || (s.lfd && isDatePast(s.lfd))) && !["delivered", "empty_return"].includes(s.status));
  const awaitingPod = opsBase.filter(s => {
    if (s.status !== "delivered") return false;
    const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
    const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
    return !docs?.pod;
  });
  const opsActive = opsBase.filter(s => !["delivered", "empty_return"].includes(s.status));
  const opsTableShips = !isOps ? [] :
    opsTableFilter === "behind" ? opsBehind :
    opsTableFilter === "on_schedule" ? opsBase.filter(s => !["delivered", "empty_return"].includes(s.status) && !(s.status === "issue" || (s.lfd && isDatePast(s.lfd)))) :
    opsTableFilter === "in_transit" ? opsBase.filter(s => ["in_transit", "out_for_delivery"].includes(s.status)) :
    opsTableFilter === "pu_today" ? opsPickupsToday :
    opsTableFilter === "pu_tomorrow" ? opsPickupsTomorrow :
    opsTableFilter === "del_today" ? opsDeliveriesToday :
    opsTableFilter === "del_tomorrow" ? opsDeliveriesTomorrow :
    opsTableFilter === "needs_driver" ? needsDriver :
    opsTableFilter === "awaiting_pod" ? awaitingPod :
    [...STATUSES, ...FTL_STATUSES].some(st => st.key === opsTableFilter && st.key !== "all") ? opsBase.filter(s => s.status === opsTableFilter) :
    opsActive;

  // Inline edit styles (reuse dispatch pattern)
  const inlineInputStyle = { background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 4, color: "#F0F2F5", padding: "2px 5px", fontSize: 11, width: 90, outline: "none", fontFamily: "'JetBrains Mono', monospace" };
  const thStyle = { padding: "10px 14px", textAlign: "left", fontSize: 9, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5 };

  // Total count for toggle badges (both views show same data, different layout)
  const totalCount = displayShipsFiltered.length;

  // Column filter: filtered data + options
  const repColFilterOpts = useMemo(() => buildColFilterOptions(isOps ? opsTableShips : displayShips, trackingSummary), [isOps, opsTableShips, displayShips, trackingSummary]);
  const opsDataFiltered = useMemo(() => applyColFilters(opsTableShips, repColumnFilters, trackingSummary), [opsTableShips, repColumnFilters, trackingSummary]);
  const displayDataFiltered = useMemo(() => applyColFilters(displayShips, repColumnFilters, trackingSummary), [displayShips, repColumnFilters, trackingSummary]);

  // Render a filterable <th> with column dropdown
  const renderFilterTh = (label, extraStyle) => {
    const filterKey = COL_FILTER_KEY_MAP[label];
    const isFilterable = !!filterKey;
    const hasFilter = isFilterable && !!repColumnFilters[filterKey];
    const isOpen = repOpenFilterCol === label;
    const opts = isFilterable ? (repColFilterOpts[filterKey] || []) : [];
    return (
      <th key={label} style={{ ...thStyle, ...extraStyle, position: "relative", zIndex: isOpen ? 50 : 5,
        borderBottom: hasFilter ? "2px solid rgba(0,212,170,0.4)" : thStyle.borderBottom,
        background: hasFilter ? "rgba(0,212,170,0.04)" : thStyle.background,
        color: hasFilter ? "#00D4AA" : thStyle.color }}>
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          <span style={{ flex: 1 }}>{label}</span>
          {isFilterable && (
            <span className="col-filter-dd"
              onClick={e => { e.stopPropagation(); if (isOpen) { setRepOpenFilterCol(null); } else { const rect = e.currentTarget.closest('th').getBoundingClientRect(); setFilterDropdownPos({ top: rect.bottom + 2, left: rect.left }); setRepOpenFilterCol(label); } }}
              style={{ fontSize: 8, color: hasFilter ? "#00D4AA" : "#5A6478", cursor: "pointer",
                padding: "2px 3px", borderRadius: 3, background: hasFilter ? "rgba(0,212,170,0.12)" : "transparent", lineHeight: 1 }}>
              {hasFilter ? "✦" : "▾"}
            </span>
          )}
        </div>
        {isOpen && isFilterable && (
          <div className="col-filter-dd" onClick={e => e.stopPropagation()}
            style={{ position: "fixed", top: filterDropdownPos.top, left: filterDropdownPos.left, zIndex: 9999, background: "#1A2236",
              border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, minWidth: 150,
              maxHeight: 300, overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
            <div onClick={() => { setRepColumnFilters(f => { const n = {...f}; delete n[filterKey]; return n; }); setRepOpenFilterCol(null); }}
              style={{ padding: "6px 10px", fontSize: 11, color: !hasFilter ? "#00D4AA" : "#8B95A8",
                cursor: "pointer", borderRadius: 4, background: !hasFilter ? "rgba(0,212,170,0.06)" : "transparent", fontWeight: 600 }}>
              All
            </div>
            {opts.map(opt => {
              const val = typeof opt === "object" ? opt.value : opt;
              const lbl = typeof opt === "object" ? opt.label : opt;
              const isActive = repColumnFilters[filterKey] === val;
              return (
                <div key={val} onClick={() => { setRepColumnFilters(f => ({ ...f, [filterKey]: val })); setRepOpenFilterCol(null); }}
                  style={{ padding: "6px 10px", fontSize: 11, color: isActive ? "#00D4AA" : "#F0F2F5",
                    cursor: "pointer", borderRadius: 4, background: isActive ? "rgba(0,212,170,0.08)" : "transparent",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {lbl}
                </div>
              );
            })}
          </div>
        )}
      </th>
    );
  };

  // ── FTL Dispatch Table (shared by master + ops in FTL view) ──
  const renderFTLTable = (ships) => {
    const ftlCols = ["Account", "Status", "EFJ #", "Container/Load #", "MP Status", "Pickup", "Origin", "Destination", "Delivery", "Truck", "Trailer #", "Driver Phone", "Carrier Email", "Rate", "Notes"];
    const filteredShips = applyColFilters(ships, repColumnFilters, trackingSummary);
    return (
      <div className="dash-panel" style={{ overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="dash-panel-title">FTL Dispatch — {filteredShips.length} loads</span>
        </div>
        <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>{ftlCols.map(h => renderFilterTh(h))}</tr>
            </thead>
            <tbody>
              {filteredShips.map((s) => {
                const sc = (isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS)[s.status] || { main: "#94a3b8" };
                const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                const tracking = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
                const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                const pu = splitDateTime(s.pickupDate);
                const del = splitDateTime(s.deliveryDate);
                const isEditing = inlineEditId === s.id;
                const cellBorder = "1px solid rgba(255,255,255,0.04)";
                const tdBase = { padding: "5px 8px", borderBottom: "1px solid rgba(255,255,255,0.06)", borderRight: cellBorder };
                return (
                  <tr key={s.id} className="row-hover" onClick={() => { if (!isEditing) handleLoadClick(s); }}
                    style={{ cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                    {/* Account */}
                    <td style={{ ...tdBase, color: "#F0F2F5", fontSize: 11, fontWeight: 600 }}>{s.account}</td>
                    {/* Status (inline-editable) */}
                    <td style={{ ...tdBase, position: "relative" }}
                      onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                      {isEditing && inlineEditField === "status" ? (
                        <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 20, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 220, overflowY: "auto", minWidth: 120 }}>
                          {getStatusesForShipment(s).filter(st => st.key !== "all").map(st => {
                            const stc = getStatusColors(s)[st.key] || { main: "#94a3b8" };
                            return (
                              <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                                style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                  background: s.status === st.key ? `${stc.main}18` : "transparent",
                                  color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                                <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                                {st.label}
                              </button>
                            );
                          })}
                          <button onClick={(e) => { e.stopPropagation(); setInlineEditId(null); }}
                            style={{ display: "block", width: "100%", padding: "3px 7px", marginTop: 2, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.03)", color: "#5A6478", fontSize: 9, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                        </div>
                      ) : null}
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 12, fontSize: 9, fontWeight: 700,
                        color: sc.main, background: `${sc.main}0D`, border: `1px solid ${sc.main}18`, textTransform: "uppercase", cursor: "pointer", whiteSpace: "nowrap" }}>
                        <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                        {resolveStatusLabel(s)}
                      </span>
                    </td>
                    {/* EFJ # */}
                    <td style={tdBase}>
                      <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{s.loadNumber}</span>
                        <DocIndicators docs={docs} />
                      </div>
                    </td>
                    {/* Container/Load # */}
                    <td style={{ ...tdBase, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#F0F2F5" }}>{s.container}</td>
                    {/* MP Status */}
                    <td style={tdBase}>
                      {(s.moveType === "FTL" || s.mpStatus) ? <TrackingBadge tracking={tracking} mpStatus={s.mpStatus || tracking?.mpStatus} mpDisplayStatus={s.mpDisplayStatus || tracking?.mpDisplayStatus} mpDisplayDetail={s.mpDisplayDetail || tracking?.mpDisplayDetail} mpLastUpdated={s.mpLastUpdated} /> : <span style={{ color: "#5A6478", fontSize: 9, fontStyle: "italic" }}>No MP</span>}
                    </td>
                    {/* Pickup (inline-editable, DD-MM + time) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                      {isEditing && inlineEditField === "pickup" ? (
                        <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : isEditing && inlineEditField === "pickupTime" ? (
                        <div onClick={e => e.stopPropagation()}>
                          <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 70 }} />
                        </div>
                      ) : (
                        <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                          <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                          {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                        </span>
                      )}
                    </td>
                    {/* Origin */}
                    <td style={{ ...tdBase, fontSize: 10, color: "#F0F2F5", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.origin}>{s.origin || "\u2014"}</td>
                    {/* Destination */}
                    <td style={{ ...tdBase, fontSize: 10, color: "#F0F2F5", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.destination}>{s.destination || "\u2014"}</td>
                    {/* Delivery (inline-editable, DD-MM + time) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                      {isEditing && inlineEditField === "delivery" ? (
                        <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                          <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                            onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                        </div>
                      ) : isEditing && inlineEditField === "deliveryTime" ? (
                        <div onClick={e => e.stopPropagation()}>
                          <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                            onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                            style={{ ...inlineInputStyle, width: 70 }} />
                        </div>
                      ) : (
                        <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                          <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                          {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                        </span>
                      )}
                    </td>
                    {/* Truck Type (inline-editable dropdown) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("truckType"); setInlineEditValue(s.truckType || ""); }}>
                      {isEditing && inlineEditField === "truckType" ? (
                        <select autoFocus value={inlineEditValue}
                          onChange={e => { const v = e.target.value; setInlineEditValue(v); handleMetadataUpdate(s, "truckType", v); setInlineEditId(null); }}
                          onBlur={() => setInlineEditId(null)} onKeyDown={e => { if (e.key === "Escape") setInlineEditId(null); }}
                          onClick={e => e.stopPropagation()} style={{ ...inlineInputStyle, width: 80, cursor: "pointer" }}>
                          {TRUCK_TYPES.map(t => <option key={t} value={t}>{t || "\u2014"}</option>)}
                        </select>
                      ) : (
                        <span style={{ fontSize: 10, color: s.truckType ? "#F0F2F5" : "#3D4557", cursor: "pointer" }}>{s.truckType || "\u2014"}</span>
                      )}
                    </td>
                    {/* Trailer # (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("trailer"); setInlineEditValue(s.trailerNumber || tracking?.trailer || ""); }}>
                      {isEditing && inlineEditField === "trailer" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "trailer", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 70 }} onClick={e => e.stopPropagation()} placeholder="Trailer" />
                      ) : (
                        <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>{s.trailerNumber || tracking?.trailer || "\u2014"}</span>
                      )}
                    </td>
                    {/* Driver Phone (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("driverPhone"); setInlineEditValue(s.driverPhone || tracking?.driverPhone || ""); }}>
                      {isEditing && inlineEditField === "driverPhone" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "driverPhone", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} placeholder="Phone" />
                      ) : (
                        <span style={{ fontSize: 10, color: (s.driverPhone || tracking?.driverPhone) ? "#F0F2F5" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>{s.driverPhone || tracking?.driverPhone || "\u2014"}</span>
                      )}
                    </td>
                    {/* Carrier Email (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrierEmail"); setInlineEditValue(s.carrierEmail || ""); }}>
                      {isEditing && inlineEditField === "carrierEmail" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleDriverFieldUpdate(s, "carrierEmail", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="email@carrier.com" />
                      ) : (
                        <span style={{ fontSize: 10, color: s.carrierEmail ? "#8B95A8" : "#3D4557", maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.carrierEmail || ""}>{s.carrierEmail || "\u2014"}</span>
                      )}
                    </td>
                    {/* Rate (inline-editable) */}
                    <td style={tdBase} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("customerRate"); setInlineEditValue(s.customerRate || ""); }}>
                      {isEditing && inlineEditField === "customerRate" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleMetadataUpdate(s, "customerRate", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 65 }} onClick={e => e.stopPropagation()} placeholder="$0.00" />
                      ) : (
                        <span style={{ fontSize: 10, color: s.customerRate ? "#22C55E" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", fontWeight: s.customerRate ? 600 : 400 }}>{s.customerRate || "\u2014"}</span>
                      )}
                    </td>
                    {/* Notes (inline-editable) */}
                    <td style={{ ...tdBase, borderRight: "none" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("notes"); setInlineEditValue(s.notes || ""); }}>
                      {isEditing && inlineEditField === "notes" ? (
                        <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { handleMetadataUpdate(s, "notes", inlineEditValue); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="Add note..." />
                      ) : (
                        <span style={{ fontSize: 10, color: s.notes ? "#F0F2F5" : "#3D4557", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.notes || ""}>{s.notes || "\u2014"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {ships.length === 0 && (
            <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>No FTL loads found</div>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div style={{ animation: "fade-in 0.4s ease" }}>
      {/* Back button + View toggle + header */}
      <div style={{ padding: "16px 0 8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <button onClick={onBack} style={{ background: "none", border: "1px solid rgba(255,255,255,0.06)", color: "#8B95A8", padding: "6px 10px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>{"\u2190"}</button>
          <div style={{ display: "flex", background: "#0D1119", borderRadius: 10, padding: 3, gap: 2, border: "1px solid rgba(255,255,255,0.06)" }}>
            <button onClick={() => setRepViewMode("dray")}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: repViewMode === "dray" ? "#1E2738" : "transparent", color: repViewMode === "dray" ? "#00D4AA" : "#5A6478",
                boxShadow: repViewMode === "dray" ? "0 1px 4px rgba(0,0,0,0.3)" : "none", transition: "all 0.15s" }}>
              Dray View <span style={{ fontSize: 9, opacity: 0.6, marginLeft: 3 }}>{totalCount}</span>
            </button>
            <button onClick={() => setRepViewMode("ftl")}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: repViewMode === "ftl" ? "#1E2738" : "transparent", color: repViewMode === "ftl" ? "#3B82F6" : "#5A6478",
                boxShadow: repViewMode === "ftl" ? "0 1px 4px rgba(0,0,0,0.3)" : "none", transition: "all 0.15s" }}>
              FTL View <span style={{ fontSize: 9, opacity: 0.6, marginLeft: 3 }}>{totalCount}</span>
            </button>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
          <div style={{ position: "relative", cursor: "pointer" }} onClick={() => { const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*,.pdf"; inp.onchange = async (e) => { const file = e.target.files[0]; if (!file) return; const fd = new FormData(); fd.append("file", file); try { const res = await apiFetch(`${API_BASE}/api/team/${repName}/avatar`, { method: "POST", body: fd }); if (res.ok) { if (onProfileUpdate) onProfileUpdate(); } else { const err = await res.json().catch(() => ({})); alert(err.error || "Upload failed"); } } catch (ex) { console.error("Avatar upload error:", ex); alert("Upload failed \u2014 check connection"); } }; inp.click(); }}>
            {repProfiles?.[repName]?.avatar_url ? (
              <img src={`${API_BASE}${repProfiles[repName].avatar_url}?t=${Date.now()}`} alt={repName}
                style={{ width: 56, height: 56, borderRadius: "50%", objectFit: "cover", border: `2px solid ${color}44` }} />
            ) : (
              <div style={{ width: 56, height: 56, borderRadius: "50%", background: `${color}18`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 800, color, border: `2px solid ${color}44` }}>
                {repName.slice(0, 2).toUpperCase()}
              </div>
            )}
            <div style={{ position: "absolute", bottom: 0, right: 0, width: 18, height: 18, borderRadius: "50%", background: "#1A2236", border: "1px solid rgba(255,255,255,0.15)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#8B95A8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>
            </div>
          </div>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>{repName}</h2>
            <div style={{ fontSize: 11, color: "#8B95A8" }}>
              {repName === "Eli" ? <em>Nothing is True, Everything is Freight</em> : isMaster ? `Track/Tracing Master \u2014 ${(REP_ACCOUNTS[repName] || []).length} accounts` : isBoviet ? "Boviet Solar Projects" : "Tolead Operations"}
            </div>
          </div>
        </div>
      </div>

      {/* Action Summary — unified pills for all views (Active first) */}
      {(() => {
        const filterState = isOps ? opsTableFilter : masterTableFilter;
        const setFilter = isOps ? setOpsTableFilter : (f) => setMasterTableFilter(masterTableFilter === f ? "all" : f);
        const pills = [
          { label: "Active", value: actionActive.length, c: "#3B82F6", filter: isOps ? "all" : "active" },
          { label: "PU Today", value: actionPuToday.length, c: "#F59E0B", filter: "pu_today" },
          { label: "PU Tmrw", value: actionPuTmrw.length, c: "#00A8CC", filter: "pu_tomorrow" },
          { label: "DEL Today", value: actionDelToday.length, c: "#22C55E", filter: "del_today" },
          { label: "DEL Tmrw", value: actionDelTmrw.length, c: "#10B981", filter: "del_tomorrow" },
          { label: "No Driver", value: actionNoDriver.length, c: "#EF4444", filter: "needs_driver" },
          { label: "Behind", value: actionBehind.length, c: "#F97316", filter: "behind" },
          { label: "No POD", value: actionNoPod.length, c: "#A855F7", filter: "awaiting_pod" },
          { label: "Needs Reply", value: inboxNeedsReply, c: "#EF4444", filter: null, action: () => onNavigateInbox("needs_reply") },
          { label: "Rate Responses", value: inboxRateResponses, c: "#00D4AA", filter: null, action: () => onNavigateInbox("rates") },
        ];
        return (
        <div style={{ display: "flex", gap: 6, marginBottom: 14, marginTop: 8, flexWrap: "wrap" }}>
          {pills.map((s, i) => (
            <button key={i} onClick={() => { if (s.filter) setFilter(s.filter); else if (s.action) s.action(); }}
              style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${filterState === s.filter && s.filter ? `${s.c}44` : "rgba(255,255,255,0.06)"}`,
                background: filterState === s.filter && s.filter ? `${s.c}15` : "rgba(255,255,255,0.03)",
                cursor: s.filter || s.action ? "pointer" : "default", display: "flex", alignItems: "center", gap: 6, fontFamily: "inherit" }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: s.value > 0 ? s.c : "#334155", fontFamily: "'JetBrains Mono', monospace" }}>{s.value}</span>
              <span style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase" }}>{s.label}</span>
            </button>
          ))}
        </div>
        );
      })()}

      {/* Status Filter Dropdown */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
        {(() => {
          const filterState = isOps ? opsTableFilter : masterTableFilter;
          const setFilter = isOps ? setOpsTableFilter : setMasterTableFilter;
          const statusList = repViewMode === "ftl" ? FTL_STATUSES : (isOps ? FTL_STATUSES : STATUSES);
          const isStatusFilter = [...STATUSES, ...FTL_STATUSES].some(st => st.key === filterState && st.key !== "all");
          return (
            <select value={isStatusFilter ? filterState : ""} onChange={e => setFilter(e.target.value || "all")}
              style={{ padding: "7px 12px", background: isStatusFilter ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${isStatusFilter ? "rgba(59,130,246,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 10, color: isStatusFilter ? "#60A5FA" : "#8B95A8", fontSize: 11, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 600 }}>
              <option value="" style={{ background: "#0D1119" }}>Filter by Status</option>
              {statusList.filter(s => s.key !== "all").map(s => <option key={s.key} value={s.key} style={{ background: "#0D1119" }}>{s.label}</option>)}
            </select>
          );
        })()}
        {(() => {
          const filterState = isOps ? opsTableFilter : masterTableFilter;
          const setFilter = isOps ? setOpsTableFilter : setMasterTableFilter;
          if (filterState === "all" && Object.keys(repColumnFilters).length === 0) return null;
          return (
            <button onClick={() => { setFilter("all"); setRepColumnFilters({}); setRepOpenFilterCol(null); }}
              style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.15)", background: "rgba(239,68,68,0.08)", color: "#f87171", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              ✕ Clear
            </button>
          );
        })()}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#8B95A8", fontWeight: 600 }}>
          {(isOps ? opsDataFiltered : displayDataFiltered).length} {(isOps ? opsDataFiltered : displayDataFiltered).length === 1 ? "load" : "loads"}
        </span>
      </div>

      {/* Boviet project tabs */}
      {isBoviet && (
        <div style={{ display: "flex", gap: 2, marginBottom: 14, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, width: "fit-content" }}>
          {["Piedra", "Hanson"].map(t => (
            <button key={t} onClick={() => setBovietTab(t)}
              style={{ padding: "6px 16px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                background: bovietTab === t ? "rgba(139,92,246,0.15)" : "transparent",
                color: bovietTab === t ? "#a78bfa" : "#8B95A8" }}>
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Tolead hub tabs */}
      {isTolead && (
        <div style={{ display: "flex", gap: 2, marginBottom: 14, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, width: "fit-content" }}>
          {["ORD", "JFK", "LAX", "DFW"].map(h => {
            const hubCount = repShipments.filter(s => (s.hub || "ORD") === h).length;
            return (
              <button key={h} onClick={() => setToleadHub(h)}
                style={{ padding: "6px 16px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                  background: toleadHub === h ? "rgba(6,182,212,0.15)" : "transparent",
                  color: toleadHub === h ? "#22d3ee" : "#8B95A8" }}>
                {h} <span style={{ fontSize: 9, opacity: 0.6, marginLeft: 2 }}>{hubCount}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Master reps: Account cards (only in dray view) */}
      {isMaster && repViewMode === "dray" && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Accounts</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
            {accountGroups.map(ag => (
              <div key={ag.name} className="acct-card"
                onClick={() => setExpandedAccount(expandedAccount === ag.name ? null : ag.name)}
                style={{ padding: "10px 14px", borderRadius: 10, background: expandedAccount === ag.name ? "rgba(0,212,170,0.06)" : "rgba(255,255,255,0.02)",
                  border: `1px solid ${expandedAccount === ag.name ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.04)"}` }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5", marginBottom: 6 }}>{ag.name}</div>
                <div style={{ display: "flex", gap: 8, fontSize: 10, flexWrap: "wrap" }}>
                  {ag.incoming > 0 && <span style={{ color: "#F59E0B" }}>{ag.incoming} <span style={{ color: "#8B95A8" }}>in</span></span>}
                  {ag.active > 0 && <span style={{ color: "#3B82F6" }}>{ag.active} <span style={{ color: "#8B95A8" }}>active</span></span>}
                  {ag.behind > 0 && <span style={{ color: "#EF4444" }}>{ag.behind} <span style={{ color: "#8B95A8" }}>behind</span></span>}
                  <span style={{ color: "#22C55E" }}>{ag.delivered} <span style={{ color: "#8B95A8" }}>done</span></span>
                </div>
              </div>
            ))}
          </div>
          {expandedAccount && (
            <div style={{ fontSize: 11, color: "#00D4AA", fontWeight: 600, marginTop: 8, padding: "4px 0" }}>
              Showing: {expandedAccount} <span style={{ cursor: "pointer", color: "#8B95A8", marginLeft: 8 }} onClick={() => setExpandedAccount(null)}>{"\u00d7"} clear</span>
            </div>
          )}
        </div>
      )}

      {/* ── FTL View: full dispatch table ── */}
      {repViewMode === "ftl" && renderFTLTable(isOps ? opsTableShips : displayShips)}

      {/* ── Dray View: Operations Dashboard — Boviet/Tolead ── */}
      {repViewMode === "dray" && isOps && (<>
        <div className="dash-panel" style={{ overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="dash-panel-title">
              {isBoviet ? bovietTab : `${toleadHub} Hub`} {"\u2014"} {opsDataFiltered.length} {opsDataFiltered.length === 1 ? "Load" : "Loads"}
            </span>
            {opsTableFilter !== "all" && (
              <button onClick={() => setOpsTableFilter("all")}
                style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", color: "#8B95A8" }}>
                Show All
              </button>
            )}
          </div>
          <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["EFJ #", "Container/Load #", "Type", "Carrier", "Origin \u2192 Dest", "ETA/ERD", "PU", "DEL", "Driver", "Status"].map(h => renderFilterTh(h))}
                </tr>
              </thead>
              <tbody>
                {opsDataFiltered.map((s) => {
                  const sc = STATUS_COLORS[s.status] || { main: "#94a3b8" };
                  const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                  const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                  const isFTL = s.moveType === "FTL";
                  const pu = splitDateTime(s.pickupDate);
                  const del = splitDateTime(s.deliveryDate);
                  const isEditing = inlineEditId === s.id;
                  return (
                    <tr key={s.id} className="row-hover" onClick={() => { if (!isEditing) handleLoadClick(s); }}
                      style={{ cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                      <td style={{ padding: "8px 14px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{s.loadNumber}</span>
                          <DocIndicators docs={docs} />
                        </div>
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#F0F2F5" }}>{s.container}</td>
                      {/* Move Type */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          color: isFTL ? "#60A5FA" : "#F59E0B", background: isFTL ? "#60A5FA12" : "#F59E0B12",
                          border: `1px solid ${isFTL ? "#60A5FA22" : "#F59E0B22"}`, textTransform: "uppercase" }}>
                          {s.moveType || "Dray"}
                        </span>
                      </td>
                      <td style={{ padding: "8px 14px", fontSize: 10, color: "#F0F2F5" }}>{s.carrier}</td>
                      <td style={{ padding: "8px 14px", fontSize: 10 }}>
                        <span style={{ color: "#F0F2F5" }}>{s.origin}</span>
                        <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                        <span style={{ color: "#F0F2F5" }}>{s.destination}</span>
                      </td>
                      {/* ETA/ERD */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>
                          {formatDDMM(s.eta || s.lfd) || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}
                        </span>
                      </td>
                      {/* PU Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "pickup" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "pickupTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                            {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                          </span>
                        )}
                      </td>
                      {/* DEL Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "delivery" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "deliveryTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                            {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px", fontSize: 10, color: "#8B95A8", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.driver || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}</td>
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 9, fontWeight: 700,
                          color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                          {STATUSES.find(st => st.key === s.status)?.label || s.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {opsTableShips.length === 0 && (
              <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
                <div style={{ fontSize: 11, fontWeight: 600 }}>No loads found</div>
              </div>
            )}
          </div>
        </div>
      </>)}

      {/* ── Dray View: Shipment table — master reps ── */}
      {repViewMode === "dray" && isMaster && (
      <div className="dash-panel" style={{ overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="dash-panel-title">
            {expandedAccount || "All Accounts"} {"\u2014"} {displayDataFiltered.length} loads
          </span>
          {masterTableFilter !== "all" && (
            <button onClick={() => setMasterTableFilter("all")}
              style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", color: "#8B95A8" }}>
              Show All
            </button>
          )}
        </div>
        <div style={{ overflow: "auto", maxHeight: "calc(100vh - 340px)", minHeight: 400 }}>
          {(() => {
            const repCols = ["Account", "EFJ #", "Container/Load #", "Type", "Carrier", "Origin \u2192 Dest", "ETA/ERD", "PU", "DEL", "Status"];
            return (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {repCols.map(h => renderFilterTh(h))}
                </tr>
              </thead>
              <tbody>
                {displayDataFiltered.map((s) => {
                  const sc = STATUS_COLORS[s.status] || { main: "#94a3b8" };
                  const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
                  const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
                  const isFTL = s.moveType === "FTL";
                  const pu = splitDateTime(s.pickupDate);
                  const del = splitDateTime(s.deliveryDate);
                  const isEditing = inlineEditId === s.id;
                  return (
                    <tr key={s.id} className="row-hover" onClick={() => { if (!isEditing) handleLoadClick(s); }}
                      style={{ cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                      <td style={{ padding: "8px 14px", color: "#F0F2F5", fontSize: 11 }}>{s.account}</td>
                      <td style={{ padding: "8px 14px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{s.loadNumber}</span>
                          <DocIndicators docs={docs} />
                        </div>
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#F0F2F5" }}>{s.container}</td>
                      {/* Move Type */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          color: isFTL ? "#60A5FA" : "#F59E0B", background: isFTL ? "#60A5FA12" : "#F59E0B12",
                          border: `1px solid ${isFTL ? "#60A5FA22" : "#F59E0B22"}`, textTransform: "uppercase" }}>
                          {s.moveType || "Dray"}
                        </span>
                      </td>
                      {/* Carrier */}
                      <td style={{ padding: "8px 14px", fontSize: 10, color: "#F0F2F5", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.carrier || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}</td>
                      <td style={{ padding: "8px 14px", fontSize: 10 }}>
                        <span style={{ color: "#F0F2F5" }}>{s.origin}</span>
                        <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                        <span style={{ color: "#F0F2F5" }}>{s.destination}</span>
                      </td>
                      {/* ETA/ERD */}
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>
                          {formatDDMM(s.eta || s.lfd) || <span style={{ color: "#3D4557" }}>{"\u2014"}</span>}
                        </span>
                      </td>
                      {/* PU Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "pickup" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "pickupTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "\u2014"}</span>
                            {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                          </span>
                        )}
                      </td>
                      {/* DEL Date + Time (inline-editable, DD-MM + time) */}
                      <td style={{ padding: "8px 14px" }} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                        {isEditing && inlineEditField === "delivery" ? (
                          <div style={{ display: "flex", gap: 3 }} onClick={e => e.stopPropagation()}>
                            <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                              onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                          </div>
                        ) : isEditing && inlineEditField === "deliveryTime" ? (
                          <div onClick={e => e.stopPropagation()}>
                            <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                              onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                              style={{ ...inlineInputStyle, width: 70 }} />
                          </div>
                        ) : (
                          <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                            <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "\u2014"}</span>
                            {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 9, fontWeight: 700,
                          color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                          {STATUSES.find(st => st.key === s.status)?.label || s.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            );
          })()}
          {displayShips.length === 0 && (
            <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>No loads found</div>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// HISTORY VIEW — Completed/Archived Loads
// ═══════════════════════════════════════════════════════════════
function HistoryView({ loaded, handleLoadClick }) {
  const [completedLoads, setCompletedLoads] = useState([]);
  const [historySearch, setHistorySearch] = useState("");
  const [historyRep, setHistoryRep] = useState("all");
  const [historyAccount, setHistoryAccount] = useState("all");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), limit: "50" });
      if (historySearch) params.set("search", historySearch);
      if (historyRep !== "all") params.set("rep", historyRep);
      if (historyAccount !== "all") params.set("account", historyAccount);
      const res = await apiFetch(`${API_BASE}/api/completed?${params}`);
      if (res.ok) {
        const data = await res.json();
        setCompletedLoads(data.loads || []);
        setHasMore(data.has_more || false);
      }
    } catch {}
    setLoading(false);
  }, [page, historySearch, historyRep, historyAccount]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Get unique accounts/reps from results for filter dropdowns
  const allAccounts = [...new Set(completedLoads.map(l => l.account).filter(Boolean))].sort();
  const allReps = [...new Set(completedLoads.map(l => l.rep).filter(Boolean))].sort();

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      <div style={{ padding: "16px 0 10px" }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em", margin: 0 }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>LOAD </span>
          <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>HISTORY</span>
        </h1>
        <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>Completed and archived loads</div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input value={historySearch} onChange={e => { setHistorySearch(e.target.value); setPage(1); }}
          placeholder="Search EFJ, container, account..."
          style={{ flex: 1, minWidth: 180, padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
        <select value={historyRep} onChange={e => { setHistoryRep(e.target.value); setPage(1); }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119", color: "#F0F2F5", fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          <option value="all">All Reps</option>
          {MASTER_REPS.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={historyAccount} onChange={e => { setHistoryAccount(e.target.value); setPage(1); }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119", color: "#F0F2F5", fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          <option value="all">All Accounts</option>
          {allAccounts.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>

      {/* Results table */}
      <div className="dash-panel" style={{ overflow: "hidden" }}>
        <div style={{ overflow: "auto", maxHeight: 600 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["EFJ #", "Container", "Account", "Carrier", "Origin → Dest", "Delivery", "Status", "Rep"].map(h => (
                  <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 9, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>Loading...</td></tr>
              ) : completedLoads.length === 0 ? (
                <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: "#3D4557" }}>
                  <div style={{ fontSize: 11, fontWeight: 600 }}>{historySearch ? "No loads match your search" : "No completed loads found"}</div>
                  <div style={{ fontSize: 10, marginTop: 4, color: "#3D4557" }}>Loads appear here after being archived from active sheets</div>
                </td></tr>
              ) : completedLoads.map((l, i) => {
                const sc = STATUS_COLORS[normalizeStatus(l.status)] || BILLING_STATUS_COLORS[normalizeStatus(l.status)] || { main: "#94a3b8" };
                return (
                  <tr key={i} className="row-hover" onClick={() => handleLoadClick && handleLoadClick(mapShipment(l, 9000 + i))}
                    style={{ cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{l.efj}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#F0F2F5" }}>{l.container}</td>
                    <td style={{ padding: "8px 14px", fontSize: 10, color: "#F0F2F5" }}>{l.account}</td>
                    <td style={{ padding: "8px 14px", fontSize: 10, color: "#F0F2F5" }}>{l.carrier}</td>
                    <td style={{ padding: "8px 14px", fontSize: 10 }}>
                      <span style={{ color: "#F0F2F5" }}>{l.origin}</span>
                      <span style={{ color: "#3D4557", margin: "0 4px" }}>{"\u2192"}</span>
                      <span style={{ color: "#F0F2F5" }}>{l.destination}</span>
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{l.delivery_date || l.delivery}</td>
                    <td style={{ padding: "8px 14px" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 20, fontSize: 9, fontWeight: 700,
                        color: sc.main, background: `${sc.main}12`, border: `1px solid ${sc.main}22`, textTransform: "uppercase" }}>
                        <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                        {l.status}
                      </span>
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 10, color: "#8B95A8" }}>{l.rep}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {/* Pagination */}
        {(page > 1 || hasMore) && (
          <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: page > 1 ? "#F0F2F5" : "#3D4557", fontSize: 10, fontWeight: 600, cursor: page > 1 ? "pointer" : "default", fontFamily: "inherit" }}>
              ← Prev
            </button>
            <span style={{ fontSize: 10, color: "#5A6478" }}>Page {page}</span>
            <button onClick={() => setPage(p => p + 1)} disabled={!hasMore}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: hasMore ? "#F0F2F5" : "#3D4557", fontSize: 10, fontWeight: 600, cursor: hasMore ? "pointer" : "default", fontFamily: "inherit" }}>
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// INBOX COMMAND CENTER VIEW
// ═══════════════════════════════════════════════════════════════

const INBOX_TABS = [
  { key: "all", label: "All" },
  { key: "needs_reply", label: "Needs Reply" },
  { key: "unmatched", label: "Unmatched" },
  { key: "rates", label: "Rates" },
];

const EMAIL_TYPE_COLORS = {
  carrier_rate: { bg: "rgba(0,212,170,0.12)", color: "#00D4AA" },
  customer_rate: { bg: "rgba(0,212,170,0.12)", color: "#00D4AA" },
  detention: { bg: "rgba(239,68,68,0.12)", color: "#EF4444" },
  pod: { bg: "rgba(34,197,94,0.12)", color: "#22C55E" },
  bol: { bg: "rgba(59,130,246,0.12)", color: "#3B82F6" },
  appointment: { bg: "rgba(168,85,247,0.12)", color: "#A855F7" },
  invoice: { bg: "rgba(249,115,22,0.12)", color: "#F97316" },
  delivery_update: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
  tracking_update: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
  general: { bg: "rgba(139,149,168,0.12)", color: "#8B95A8" },
  payment_escalation: { bg: "rgba(239,68,68,0.15)", color: "#EF4444" },
  carrier_rate_response: { bg: "rgba(0,212,170,0.15)", color: "#00D4AA" },
  rate_outreach: { bg: "rgba(59,130,246,0.12)", color: "#3B82F6" },
  carrier_invoice: { bg: "rgba(249,115,22,0.12)", color: "#F97316" },
  carrier_rate_confirmation: { bg: "rgba(168,85,247,0.12)", color: "#A855F7" },
  warehouse_rate: { bg: "rgba(6,182,212,0.12)", color: "#06B6D4" },
};

const INBOX_TYPE_LABELS = {
  carrier_rate: "CARRIER RATE",
  customer_rate: "CUSTOMER RATE",
  carrier_rate_response: "RATE RESPONSE",
  carrier_rate_confirmation: "RATE CON",
  carrier_invoice: "INVOICE",
  payment_escalation: "PAYMENT ALERT",
  rate_outreach: "OUTREACH",
  pod: "POD",
  bol: "BOL",
  detention: "DETENTION",
  appointment: "APPT",
  invoice: "INVOICE",
  delivery_update: "DELIVERY",
  tracking_update: "TRACKING",
  general: "GENERAL",
  warehouse_rate: "WAREHOUSE",
};

function _relTime(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function InboxView({ handleLoadClick }) {
  const { inboxThreads, inboxStats, setInboxThreads, setInboxStats, shipments, setSelectedShipment, setActiveView } = useAppStore();
  const [activeTab, setActiveTab] = useState("all");
  const [loading, setLoading] = useState(true);
  const [assigningId, setAssigningId] = useState(null);
  const [assignEfj, setAssignEfj] = useState("");
  const [feedbackGiven, setFeedbackGiven] = useState({});
  const [correctionId, setCorrectionId] = useState(null);
  const [sortCol, setSortCol] = useState("time");
  const [sortDir, setSortDir] = useState("desc");
  const [inboxSearch, setInboxSearch] = useState("");
  const [selectedThread, setSelectedThread] = useState(null);
  const [colFilters, setColFilters] = useState({});
  const [openFilterCol, setOpenFilterCol] = useState(null);

  const fetchInbox = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/inbox?days=7&tab=${activeTab}`);
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      setInboxThreads(data.threads || []);
      setInboxStats(data.stats || {});
    } catch (e) {
      console.error("Inbox fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => { setLoading(true); fetchInbox(); }, [fetchInbox]);
  useEffect(() => { const iv = setInterval(fetchInbox, 90000); return () => clearInterval(iv); }, [fetchInbox]);

  const handleAssign = async (emailId) => {
    if (!assignEfj.trim()) return;
    try {
      const res = await apiFetch(`${API_BASE}/api/unmatched-emails/${emailId}/assign`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ efj: assignEfj.trim().toUpperCase() }),
      });
      if (res.ok) { setAssigningId(null); setAssignEfj(""); fetchInbox(); }
    } catch (e) { console.error("Assign failed:", e); }
  };
  const handleDismiss = async (emailId) => {
    try { await apiFetch(`${API_BASE}/api/unmatched-emails/${emailId}/dismiss`, { method: "POST" }); fetchInbox(); }
    catch (e) { console.error("Dismiss failed:", e); }
  };
  const handleFeedback = async (emailId, feedback, correctedType) => {
    try {
      await apiFetch(`${API_BASE}/api/inbox/${emailId}/feedback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback, corrected_type: correctedType || null }),
      });
      setFeedbackGiven(prev => ({ ...prev, [emailId]: feedback }));
      setCorrectionId(null);
    } catch (e) { console.error("Feedback failed:", e); }
  };
  const openLoad = (efj) => {
    if (!efj) return;
    const ship = (Array.isArray(shipments) ? shipments : []).find(s => s.efj === efj);
    if (ship) { setSelectedShipment(ship); setSelectedThread(null); }
  };

  const threads = inboxThreads;
  const stats = inboxStats;
  const CORRECTION_TYPES = ["carrier_rate", "customer_rate", "carrier_rate_response", "carrier_rate_confirmation", "carrier_invoice", "payment_escalation", "pod", "bol", "appointment", "detention", "delivery_update", "tracking_update", "invoice", "general"];

  // Filtering
  const filtered = useMemo(() => {
    let list = threads;
    if (inboxSearch.trim()) {
      const q = inboxSearch.toLowerCase();
      list = list.filter(t =>
        (t.latest_subject || "").toLowerCase().includes(q) ||
        (t.latest_sender || "").toLowerCase().includes(q) ||
        (t.efj || "").toLowerCase().includes(q) ||
        (t.lane || "").toLowerCase().includes(q)
      );
    }
    const active = Object.entries(colFilters).filter(([, v]) => v != null);
    if (active.length) {
      list = list.filter(t => active.every(([key, val]) => {
        if (key === "type") return t.email_type === val;
        if (key === "efj") return t.efj === val;
        if (key === "sender") return (t.latest_sender || "").replace(/<[^>]+>/g, "").trim() === val;
        if (key === "status") {
          if (val === "needs_reply") return t.needs_reply;
          if (val === "replied") return t.has_csl_reply;
          if (val === "unmatched") return t.source === "unmatched";
          return true;
        }
        return true;
      }));
    }
    return list;
  }, [threads, inboxSearch, colFilters]);

  // Sorting
  const sorted = useMemo(() => {
    const list = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      let cmp = 0;
      if (sortCol === "priority") cmp = (a.max_priority || 0) - (b.max_priority || 0);
      else if (sortCol === "subject") cmp = (a.latest_subject || "").localeCompare(b.latest_subject || "");
      else if (sortCol === "efj") cmp = (a.efj || "").localeCompare(b.efj || "");
      else if (sortCol === "type") cmp = (a.email_type || "").localeCompare(b.email_type || "");
      else if (sortCol === "msgs") cmp = (a.message_count || 0) - (b.message_count || 0);
      else if (sortCol === "sender") cmp = (a.latest_sender || "").localeCompare(b.latest_sender || "");
      else if (sortCol === "time") cmp = (a.latest_sent_at || "").localeCompare(b.latest_sent_at || "");
      return cmp * dir;
    });
    return list;
  }, [filtered, sortCol, sortDir]);

  // Column filter options
  const filterOpts = useMemo(() => {
    const opts = {};
    opts.type = [...new Set(threads.map(t => t.email_type).filter(Boolean))].sort();
    opts.efj = [...new Set(threads.map(t => t.efj).filter(Boolean))].sort();
    opts.sender = [...new Set(threads.map(t => (t.latest_sender || "").replace(/<[^>]+>/g, "").trim()).filter(Boolean))].sort();
    opts.status = ["needs_reply", "replied", "unmatched"];
    return opts;
  }, [threads]);

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("desc"); }
  };

  const thStyle = { padding: "6px 8px", textAlign: "left", fontSize: 8, fontWeight: 600, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5, cursor: "pointer", whiteSpace: "nowrap", userSelect: "none" };
  const cellStyle = { padding: "5px 8px", fontSize: 10, color: "#F0F2F5", borderBottom: "1px solid rgba(255,255,255,0.03)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

  const renderFilterDrop = (colKey, w) => {
    if (openFilterCol !== colKey) return null;
    const options = filterOpts[colKey] || [];
    return (
      <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 60, background: "#141A28", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: 4, minWidth: w || 120, maxHeight: 200, overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}
        onClick={e => e.stopPropagation()}>
        <div style={{ padding: "4px 8px", fontSize: 9, color: "#8B95A8", cursor: "pointer", borderRadius: 4 }}
          onClick={() => { setColFilters(f => { const n = { ...f }; delete n[colKey]; return n; }); setOpenFilterCol(null); }}>
          Clear filter
        </div>
        {options.map(opt => {
          const label = colKey === "type" ? (INBOX_TYPE_LABELS[opt] || opt.replace(/_/g, " ")) : colKey === "status" ? opt.replace(/_/g, " ") : opt;
          return (
            <div key={opt} style={{ padding: "4px 8px", fontSize: 9, color: colFilters[colKey] === opt ? "#00D4AA" : "#F0F2F5", cursor: "pointer", borderRadius: 4, background: colFilters[colKey] === opt ? "rgba(0,212,170,0.08)" : "transparent" }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
              onMouseLeave={e => e.currentTarget.style.background = colFilters[colKey] === opt ? "rgba(0,212,170,0.08)" : "transparent"}
              onClick={() => { setColFilters(f => ({ ...f, [colKey]: opt })); setOpenFilterCol(null); }}>
              {label}
            </div>
          );
        })}
      </div>
    );
  };

  const renderTh = (label, colKey, w, filterable) => {
    const isSort = sortCol === colKey;
    const hasFilter = colFilters[colKey] != null;
    return (
      <th key={colKey} style={{ ...thStyle, width: w || "auto", minWidth: w || "auto", position: "relative",
        borderBottom: hasFilter ? "2px solid rgba(0,212,170,0.4)" : thStyle.borderBottom,
        background: hasFilter ? "rgba(0,212,170,0.04)" : thStyle.background,
        color: isSort ? "#00D4AA" : thStyle.color }}>
        <span onClick={() => toggleSort(colKey)}>{label} {isSort ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}</span>
        {filterable && (
          <span onClick={e => { e.stopPropagation(); setOpenFilterCol(openFilterCol === colKey ? null : colKey); }}
            style={{ marginLeft: 4, cursor: "pointer", fontSize: 8, color: hasFilter ? "#00D4AA" : "#5A6478" }}>
            {hasFilter ? "\u2726" : "\u25BE"}
          </span>
        )}
        {filterable && renderFilterDrop(colKey, w)}
      </th>
    );
  };

  const selThread = selectedThread;
  const selMsgId = selThread ? ((selThread.messages || []).filter(m => m.direction === "inbound").slice(-1)[0]?.id) : null;
  const selFeedback = selMsgId ? feedbackGiven[selMsgId] : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 60px)", position: "relative" }} onClick={() => { if (openFilterCol) setOpenFilterCol(null); }}>
      {/* Header + Tabs + Search */}
      <div style={{ padding: "12px 16px 0", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>Inbox</div>
          <div style={{ fontSize: 10, color: "#8B95A8" }}>
            {stats.total_threads || 0} threads
            {stats.needs_reply > 0 && <> &middot; <span style={{ color: "#EF4444", fontWeight: 600 }}>{stats.needs_reply} need reply</span></>}
            {stats.unmatched > 0 && <> &middot; <span style={{ color: "#F97316" }}>{stats.unmatched} unmatched</span></>}
            {stats.high_priority > 0 && <> &middot; {stats.high_priority} high priority</>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, marginBottom: 8, alignItems: "center" }}>
          {INBOX_TABS.map(tab => {
            const isActive = activeTab === tab.key;
            let count = null;
            if (tab.key === "needs_reply") count = stats.needs_reply;
            else if (tab.key === "unmatched") count = stats.unmatched;
            return (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                style={{ padding: "5px 12px", borderRadius: 6, fontSize: 10, fontWeight: 600, cursor: "pointer",
                  background: isActive ? "rgba(0,212,170,0.12)" : "rgba(255,255,255,0.04)",
                  color: isActive ? "#00D4AA" : "#8B95A8",
                  border: isActive ? "1px solid rgba(0,212,170,0.25)" : "1px solid rgba(255,255,255,0.06)" }}>
                {tab.label}
                {count > 0 && (
                  <span style={{ marginLeft: 5, padding: "1px 5px", borderRadius: 8, fontSize: 8, fontWeight: 700,
                    background: tab.key === "needs_reply" ? "rgba(239,68,68,0.20)" : "rgba(249,115,22,0.20)",
                    color: tab.key === "needs_reply" ? "#EF4444" : "#F97316" }}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
          <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
            <input value={inboxSearch} onChange={e => setInboxSearch(e.target.value)}
              placeholder="Search subject, sender, EFJ..."
              style={{ width: 200, padding: "5px 10px", borderRadius: 6, fontSize: 10, background: "rgba(255,255,255,0.04)", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.08)", outline: "none" }} />
            {Object.keys(colFilters).length > 0 && (
              <button onClick={() => setColFilters({})}
                style={{ padding: "4px 8px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>
                Clear Filters
              </button>
            )}
            <button onClick={() => { setLoading(true); fetchInbox(); }}
              style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.06)" }}>
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: "auto", position: "relative" }} className="dispatch-table-wrap">
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "#5A6478" }}>
            <div style={{ width: 24, height: 24, border: "2px solid rgba(0,212,170,0.2)", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
            Loading inbox...
          </div>
        ) : sorted.length === 0 ? (
          <div style={{ textAlign: "center", padding: 60, color: "#5A6478", fontSize: 11 }}>No threads found</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <thead>
              <tr>
                {renderTh("", "priority", 28, false)}
                {renderTh("Status", "status", 85, true)}
                {renderTh("Type", "type", 100, true)}
                <th style={{ ...thStyle, width: "auto", cursor: "pointer" }} onClick={() => toggleSort("subject")}>
                  Subject {sortCol === "subject" ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}
                </th>
                {renderTh("EFJ", "efj", 85, true)}
                {renderTh("Sender", "sender", 140, true)}
                {renderTh("Msgs", "msgs", 42, false)}
                {renderTh("Updated", "time", 65, false)}
              </tr>
            </thead>
            <tbody>
              {sorted.map((thread, idx) => {
                const typeColors = EMAIL_TYPE_COLORS[thread.email_type] || EMAIL_TYPE_COLORS.general;
                const isSelected = selThread?.thread_id === thread.thread_id;
                const rowBg = isSelected ? "rgba(0,212,170,0.06)" : idx % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent";
                return (
                  <tr key={thread.thread_id} style={{ background: rowBg, cursor: "pointer" }}
                    onClick={() => setSelectedThread(isSelected ? null : thread)}
                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = idx % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent"; }}>
                    {/* Priority */}
                    <td style={{ ...cellStyle, textAlign: "center" }}>
                      <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                        background: thread.max_priority >= 5 ? "#EF4444" : thread.max_priority >= 4 ? "#F97316" : thread.max_priority >= 3 ? "#3B82F6" : "#4D5669" }} />
                    </td>
                    {/* Status */}
                    <td style={cellStyle}>
                      {thread.needs_reply && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(239,68,68,0.15)", color: "#EF4444", fontWeight: 700 }}>NEEDS REPLY</span>}
                      {thread.has_csl_reply && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#22C55E", fontWeight: 600 }}>REPLIED</span>}
                      {!thread.needs_reply && !thread.has_csl_reply && thread.source === "unmatched" && <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, background: "rgba(249,115,22,0.12)", color: "#F97316", fontWeight: 600 }}>UNMATCHED</span>}
                    </td>
                    {/* Type */}
                    <td style={cellStyle}>
                      {thread.email_type && (
                        <span style={{ fontSize: 7, padding: "1px 5px", borderRadius: 3, fontWeight: 700, background: typeColors.bg, color: typeColors.color, letterSpacing: "0.3px" }}>
                          {INBOX_TYPE_LABELS[thread.email_type] || thread.email_type.replace(/_/g, " ").toUpperCase()}
                        </span>
                      )}
                    </td>
                    {/* Subject */}
                    <td style={{ ...cellStyle, maxWidth: 0 }} title={thread.ai_summary || thread.latest_subject}>
                      <span style={{ fontWeight: 500 }}>{thread.latest_subject || "(no subject)"}</span>
                      {thread.has_attachments && <span style={{ marginLeft: 4, fontSize: 9, opacity: 0.5 }}>&#128206;</span>}
                    </td>
                    {/* EFJ */}
                    <td style={cellStyle}>
                      {thread.efj ? (
                        <span onClick={e => { e.stopPropagation(); openLoad(thread.efj); }}
                          style={{ padding: "1px 4px", borderRadius: 3, background: "rgba(0,212,170,0.10)", color: "#00D4AA", fontWeight: 600, fontSize: 9, fontFamily: "JetBrains Mono, monospace", cursor: "pointer" }}>
                          {thread.efj}
                        </span>
                      ) : <span style={{ color: "#4D5669", fontSize: 9 }}>--</span>}
                    </td>
                    {/* Sender */}
                    <td style={{ ...cellStyle, fontSize: 9, color: "#8B95A8", maxWidth: 0 }}>
                      {(thread.latest_sender || "").replace(/<[^>]+>/g, "").trim()}
                    </td>
                    {/* Msgs */}
                    <td style={{ ...cellStyle, textAlign: "center", color: "#8B95A8", fontSize: 9 }}>
                      {thread.message_count || 1}
                    </td>
                    {/* Updated */}
                    <td style={{ ...cellStyle, textAlign: "right", color: "#5A6478", fontSize: 9 }}>
                      {_relTime(thread.latest_sent_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Thread Detail Slide-Over */}
      {selThread && (
        <div style={{ position: "fixed", right: 0, top: 0, height: "100vh", width: 480, zIndex: 35, background: "#0F1420", borderLeft: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", boxShadow: "-8px 0 30px rgba(0,0,0,0.5)", animation: "slideInRight 0.2s ease" }}>
          {/* Header */}
          <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)", flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <button onClick={() => setSelectedThread(null)}
                style={{ padding: "2px 6px", borderRadius: 4, fontSize: 12, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "none" }}>&#10005;</button>
              <div style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {selThread.latest_subject || "(no subject)"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              {selThread.email_type && (() => {
                const tc = EMAIL_TYPE_COLORS[selThread.email_type] || EMAIL_TYPE_COLORS.general;
                return <span style={{ fontSize: 8, padding: "2px 6px", borderRadius: 4, fontWeight: 700, background: tc.bg, color: tc.color }}>{INBOX_TYPE_LABELS[selThread.email_type] || selThread.email_type.replace(/_/g," ").toUpperCase()}</span>;
              })()}
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: selThread.max_priority >= 5 ? "#EF4444" : selThread.max_priority >= 4 ? "#F97316" : selThread.max_priority >= 3 ? "#3B82F6" : "#4D5669" }} />
              {selThread.efj && (
                <button onClick={() => openLoad(selThread.efj)}
                  style={{ padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(0,212,170,0.10)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.20)", fontFamily: "JetBrains Mono, monospace" }}>
                  {selThread.efj} &rarr; Open Load
                </button>
              )}
              {selThread.lane && <span style={{ fontSize: 9, color: "#8B95A8" }}>{selThread.lane}</span>}
            </div>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
            {(selThread.messages || []).map((msg, idx) => (
              <div key={idx} style={{ padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,0.03)", display: "flex", gap: 8 }}>
                <span style={{ fontSize: 11, color: msg.direction === "sent" ? "#00D4AA" : "#8B95A8", flexShrink: 0, marginTop: 1 }}>
                  {msg.direction === "sent" ? "\u2191" : "\u2193"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 500, color: msg.direction === "sent" ? "#00D4AA" : "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                      {msg.direction === "sent" ? "CSL Team" : (msg.sender || "").replace(/<[^>]+>/g, "").trim()}
                    </span>
                    <span style={{ fontSize: 8, color: "#5A6478", whiteSpace: "nowrap" }}>
                      {msg.sent_at ? new Date(msg.sent_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}
                    </span>
                  </div>
                  {msg.body_preview && (
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 3, lineHeight: 1.5, maxHeight: 60, overflow: "hidden" }}>
                      {msg.body_preview.slice(0, 300)}
                    </div>
                  )}
                  {msg.has_attachments && msg.attachment_names && (
                    <div style={{ fontSize: 8, color: "#8B95A8", marginTop: 3 }}>&#128206; {msg.attachment_names}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Actions */}
          <div style={{ padding: "10px 16px", borderTop: "1px solid rgba(255,255,255,0.06)", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", flexShrink: 0 }}>
            {selThread.source === "unmatched" && assigningId !== selMsgId && (
              <>
                <button onClick={() => setAssigningId(selMsgId)}
                  style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(59,130,246,0.10)", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.20)" }}>
                  Assign to Load
                </button>
                <button onClick={() => handleDismiss(selMsgId)}
                  style={{ padding: "5px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>
                  Dismiss
                </button>
              </>
            )}
            {assigningId === selMsgId && (
              <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <input value={assignEfj} onChange={e => setAssignEfj(e.target.value)} placeholder="EFJ#" autoFocus
                  onKeyDown={e => { if (e.key === "Enter") handleAssign(selMsgId); if (e.key === "Escape") { setAssigningId(null); setAssignEfj(""); } }}
                  style={{ width: 90, padding: "4px 8px", borderRadius: 6, fontSize: 10, background: "rgba(255,255,255,0.06)", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.12)", outline: "none", fontFamily: "JetBrains Mono, monospace" }} />
                <button onClick={() => handleAssign(selMsgId)}
                  style={{ padding: "4px 10px", borderRadius: 6, fontSize: 9, fontWeight: 600, cursor: "pointer", background: "#00D4AA", color: "#0A0E17", border: "none" }}>Assign</button>
                <button onClick={() => { setAssigningId(null); setAssignEfj(""); }}
                  style={{ padding: "4px 8px", borderRadius: 6, fontSize: 9, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "1px solid rgba(255,255,255,0.08)" }}>Cancel</button>
              </div>
            )}
            <div style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
              {selFeedback ? (
                <span style={{ fontSize: 9, color: selFeedback === "correct" ? "#22C55E" : "#F97316", fontWeight: 600 }}>
                  {selFeedback === "correct" ? "Confirmed" : "Corrected"}
                </span>
              ) : selMsgId && correctionId !== selMsgId ? (
                <>
                  <button onClick={() => handleFeedback(selMsgId, "correct")} title="Classification correct"
                    style={{ padding: "3px 8px", borderRadius: 4, fontSize: 11, cursor: "pointer", background: "rgba(34,197,94,0.08)", color: "#22C55E", border: "1px solid rgba(34,197,94,0.15)" }}>&#128077;</button>
                  <button onClick={() => setCorrectionId(selMsgId)} title="Classification incorrect"
                    style={{ padding: "3px 8px", borderRadius: 4, fontSize: 11, cursor: "pointer", background: "rgba(239,68,68,0.08)", color: "#EF4444", border: "1px solid rgba(239,68,68,0.15)" }}>&#128078;</button>
                </>
              ) : null}
              {correctionId === selMsgId && (
                <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
                  <select onChange={e => handleFeedback(selMsgId, "incorrect", e.target.value)} defaultValue=""
                    style={{ padding: "3px 8px", borderRadius: 4, fontSize: 9, background: "#141A28", color: "#F0F2F5", border: "1px solid rgba(255,255,255,0.12)" }}>
                    <option value="" disabled>Correct type...</option>
                    {CORRECTION_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
                  </select>
                  <button onClick={() => setCorrectionId(null)}
                    style={{ padding: "2px 6px", borderRadius: 4, fontSize: 9, cursor: "pointer", background: "rgba(255,255,255,0.06)", color: "#8B95A8", border: "none" }}>&#10005;</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// ANALYTICS VIEW
// ═══════════════════════════════════════════════════════════════
function DataSourceToggle() {
  const { dataSource, setDataSource, systemHealth, setSystemHealth } = useAppStore();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/health`).then(r => r.json()).then(setSystemHealth).catch(() => {});
    const t = setInterval(() => {
      apiFetch(`${API_BASE}/api/health`).then(r => r.json()).then(setSystemHealth).catch(() => {});
    }, 60000);
    return () => clearInterval(t);
  }, []);

  const toggle = () => {
    const next = dataSource === "postgres" ? "sheets" : "postgres";
    setDataSource(next);
    setLoading(true);
    setTimeout(() => setLoading(false), 2000);
  };

  const h = systemHealth;
  const pgOk = h?.checks?.postgres?.status === "ok";
  const sheetOk = h?.checks?.sheets_cache?.status === "ok";
  const overall = h?.overall || "unknown";
  const overallColor = { healthy: "#10b981", degraded: "#f59e0b", critical: "#ef4444" }[overall] || "#6b7280";

  return (
    <div style={{ background: "#141A28", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 14, padding: "14px 18px", marginBottom: 14, position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: overallColor }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", marginBottom: 4 }}>Data Source</div>
          <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
            <span style={{ color: pgOk ? "#10b981" : "#ef4444" }}>
              PG: {pgOk ? `${h?.checks?.postgres?.active_shipments || "?"} active` : "DOWN"}
            </span>
            <span style={{ color: sheetOk ? "#10b981" : "#f59e0b" }}>
              Sheets: {sheetOk ? `${h?.checks?.sheets_cache?.shipment_count || "?"} cached` : h?.checks?.sheets_cache?.status || "?"}
            </span>
            {h?.checks?.disk && <span style={{ color: "#5A6478" }}>Disk: {h.checks.disk.use_pct}</span>}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: dataSource === "postgres" ? "#00D4AA" : "#f59e0b", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {loading ? "Switching..." : dataSource === "postgres" ? "Postgres" : "Google Sheets"}
          </span>
          <button onClick={toggle} style={{
            background: dataSource === "postgres" ? "rgba(0,212,170,0.15)" : "rgba(245,158,11,0.15)",
            border: `1px solid ${dataSource === "postgres" ? "rgba(0,212,170,0.3)" : "rgba(245,158,11,0.3)"}`,
            borderRadius: 8, padding: "6px 14px", cursor: "pointer",
            color: dataSource === "postgres" ? "#00D4AA" : "#f59e0b",
            fontSize: 11, fontWeight: 700, transition: "all 0.2s"
          }}>
            Switch to {dataSource === "postgres" ? "Sheets" : "Postgres"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AnalyticsView({ loaded, botStatus, botHealth, cronStatus, sheetLog }) {
  const HEALTH_CONFIG = {
    healthy:    { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.20)", label: "HEALTHY", icon: "\u25CF" },
    degraded:   { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.20)", label: "DEGRADED", icon: "\u25B2" },
    crash_loop: { color: "#ef4444", bg: "rgba(239,68,68,0.10)", border: "rgba(239,68,68,0.25)", label: "CRASH LOOP", icon: "\u25C6" },
    down:       { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "DOWN", icon: "\u25CB" },
    idle:       { color: "#8b95a8", bg: "rgba(139,149,168,0.06)", border: "rgba(139,149,168,0.15)", label: "IDLE", icon: "\u25C7" },
  };

  const services = botHealth?.services ? Object.entries(botHealth.services) : [];
  const summary = botHealth?.summary || {};
  const cronJobs = cronStatus?.cron_jobs ? Object.entries(cronStatus.cron_jobs) : [];

  // Cron status config
  const CRON_STATUS = {
    success:  { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.20)", label: "SUCCESS", icon: "\u2713" },
    partial:  { color: "#3b82f6", bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.20)", label: "PARTIAL", icon: "\u25D4" },
    failed:   { color: "#ef4444", bg: "rgba(239,68,68,0.10)", border: "rgba(239,68,68,0.25)", label: "FAILED", icon: "\u2717" },
    overdue:  { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.20)", label: "OVERDUE", icon: "\u25B2" },
    idle:     { color: "#8b95a8", bg: "rgba(139,149,168,0.06)", border: "rgba(139,149,168,0.15)", label: "IDLE", icon: "\u25C7" },
    pending:  { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "PENDING", icon: "\u25CB" },
    no_data:  { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.20)", label: "NO DATA", icon: "\u2014" },
  };

  // Collect all recent errors across services
  const allErrors = services.flatMap(([unit, svc]) =>
    (svc.recent_errors || []).map(e => ({ ...e, unit, name: svc.name }))
  ).sort((a, b) => (b.time || "").localeCompare(a.time || "")).slice(0, 20);

  // Include cron jobs in "Services OK" count
  const cronOk = cronJobs.filter(([, j]) => ["success", "partial", "idle", "pending"].includes(j.status)).length;
  const svcHealthy = (summary.services_healthy || 0) + cronOk;
  const svcTotal = (summary.services_total || 0) + cronJobs.length;

  const summaryCards = [
    { label: "Emails Sent", sub: "24h", value: summary.total_emails_24h || 0, color: "#00D4AA", gradient: "#00D4AA" },
    { label: "Crashes", sub: "24h", value: summary.total_crashes_24h || 0, color: (summary.total_crashes_24h || 0) > 0 ? "#ef4444" : "#3D4557", gradient: (summary.total_crashes_24h || 0) > 0 ? "#ef4444" : "#3D4557" },
    { label: "Cycles Run", sub: "24h", value: summary.total_cycles_24h || 0, color: "#3b82f6", gradient: "#3b82f6" },
    { label: "Services OK", sub: "", value: `${svcHealthy}/${svcTotal}`, color: svcHealthy === svcTotal ? "#10b981" : "#f59e0b", gradient: svcHealthy === svcTotal ? "#10b981" : "#f59e0b" },
  ];

  const MetricCell = ({ label, value, color }) => (
    <div>
      <div style={{ fontSize: 18, fontWeight: 800, color, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.1 }}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
    </div>
  );

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      {/* Title */}
      <div style={{ padding: "20px 0 16px" }}>
        <h2 style={{ fontSize: 22, fontWeight: 900, margin: 0 }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>SYSTEM </span>
          <span style={{ background: "linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>HEALTH</span>
        </h2>
        <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 2 }}>
          Bot health metrics, crash detection, and system connections
          {botHealth?.generated_at && <span style={{ marginLeft: 8, color: "#3D4557", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>cached {Math.round((Date.now() - new Date(botHealth.generated_at).getTime()) / 60000)}m ago</span>}
        </div>
      </div>

      {/* Summary stat bar */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {summaryCards.map((s, i) => (
          <div key={i} style={{ flex: 1, minWidth: 0, background: "#141A28", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 14, padding: "14px 16px", position: "relative", overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: s.gradient }} />
            <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1, color: s.color, fontFamily: "'JetBrains Mono', monospace", marginBottom: 2 }}>{typeof s.value === "number" ? s.value.toLocaleString() : s.value}</div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label} {s.sub && <span style={{ color: "#3D4557" }}>{s.sub}</span>}</div>
          </div>
        ))}
      </div>

      {/* Data Source Toggle */}
      <DataSourceToggle />

      {/* Service Health Cards — 2 column grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        {services.map(([unit, svc]) => {
          const h = HEALTH_CONFIG[svc.health] || HEALTH_CONFIG.down;
          const j = svc.journal_24h || {};
          const isServer = svc.poll_min === 0;
          return (
            <div key={unit} style={{ background: "#141A28", border: `1px solid ${h.border}`, borderRadius: 12, padding: "14px 16px", position: "relative", overflow: "hidden", transition: "border-color 0.2s" }}>
              {/* Top accent bar */}
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: h.color }} />
              {/* Header: name + health badge */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: svc.active_state === "active" ? "#10b981" : "#ef4444", boxShadow: `0 0 6px ${svc.active_state === "active" ? "#10b98166" : "#ef444466"}` }} />
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{svc.name}</span>
                </div>
                <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 6, background: h.bg, color: h.color, border: `1px solid ${h.border}` }}>
                  {h.icon} {h.label}
                </span>
              </div>
              {/* Metrics grid */}
              <div style={{ display: "grid", gridTemplateColumns: isServer ? "1fr 1fr" : "1fr 1fr 1fr 1fr", gap: "6px 16px", marginBottom: 8 }}>
                <MetricCell label="Crashes" value={j.crashes || 0} color={(j.crashes || 0) > 0 ? "#ef4444" : "#3D4557"} />
                <MetricCell label="Emails" value={j.emails_sent || 0} color={(j.emails_sent || 0) > 0 ? "#00D4AA" : "#3D4557"} />
                {!isServer && <MetricCell label="Cycles" value={j.cycles_completed || 0} color={(j.cycles_completed || 0) > 0 ? "#3b82f6" : "#3D4557"} />}
                {!isServer && <MetricCell label="Loads" value={j.loads_tracked || 0} color={(j.loads_tracked || 0) > 0 ? "#8b5cf6" : "#3D4557"} />}
              </div>
              {/* Footer: last cycle + next run */}
              <div style={{ fontSize: 10, color: "#5A6478", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6, display: "flex", justifyContent: "space-between" }}>
                <span>{svc.last_successful_cycle ? `Last cycle: ${(() => { const m = Math.round((Date.now() - new Date(svc.last_successful_cycle).getTime()) / 60000); return m < 1 ? "just now" : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; })()}` : isServer ? `Up: ${svc.last_run}` : "Last cycle: none (24h)"}</span>
                {svc.next_run && !isServer && (
                  <span style={{ color: svc.next_run === "overdue" ? "#f59e0b" : "#3b82f6", fontWeight: 600 }}>next: {svc.next_run}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Scheduled Jobs (cron-based monitors) */}
      {cronJobs.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Scheduled Jobs
            <span style={{ fontWeight: 400, color: "#3D4557", marginLeft: 8 }}>7:30 AM & 1:30 PM Mon-Fri</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
            {cronJobs.map(([key, job]) => {
              const cs = CRON_STATUS[job.status] || CRON_STATUS.no_data;
              return (
                <div key={key} style={{ background: "#141A28", border: `1px solid ${cs.border}`, borderRadius: 12, padding: "14px 16px", position: "relative", overflow: "hidden", transition: "border-color 0.2s" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: cs.color }} />
                  {/* Header */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 14 }}>{key === "dray_import" ? "\u{1F4E5}" : "\u{1F4E4}"}</span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{job.name}</span>
                    </div>
                    <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 6, background: cs.bg, color: cs.color, border: `1px solid ${cs.border}` }}>
                      {cs.icon} {cs.label}
                    </span>
                  </div>
                  {/* Metrics */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px 16px", marginBottom: 8 }}>
                    <MetricCell label="Runs Today" value={job.runs_today || 0} color={(job.runs_today || 0) > 0 ? "#10b981" : "#3D4557"} />
                    <MetricCell label="Items" value={job.items_tracked || 0} color={(job.items_tracked || 0) > 0 ? "#8b5cf6" : "#3D4557"} />
                    <MetricCell label="Errors" value={(job.errors || []).length} color={(job.errors || []).length > 0 ? "#ef4444" : "#3D4557"} />
                  </div>
                  {/* Footer */}
                  <div style={{ fontSize: 10, color: "#5A6478", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6 }}>
                    {job.last_run ? `Last run: ${(() => { const m = Math.round((Date.now() - new Date(job.last_run.replace(" ", "T")).getTime()) / 60000); return m < 1 ? "just now" : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; })()}` : "No runs recorded"}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Bottom row: Recent Errors + Google Sheets */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* Recent Errors & Events */}
        <div className="dash-panel" style={{ padding: "18px 20px", maxHeight: 340, overflowY: "auto" }}>
          <div className="dash-panel-title" style={{ marginBottom: 14 }}>Recent Errors & Events</div>
          {allErrors.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "#3D4557", fontSize: 11 }}>No errors in the last 24 hours</div>
          ) : allErrors.map((e, i) => (
            <div key={i} style={{ display: "flex", gap: 8, padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.02)", fontSize: 10, alignItems: "flex-start" }}>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#3D4557", flexShrink: 0, minWidth: 55 }}>{e.time}</span>
              <span style={{ padding: "0px 5px", borderRadius: 4, fontSize: 9, fontWeight: 700, flexShrink: 0,
                background: e.level === "crash" ? "rgba(239,68,68,0.12)" : "rgba(245,158,11,0.12)",
                color: e.level === "crash" ? "#ef4444" : "#f59e0b",
                border: `1px solid ${e.level === "crash" ? "rgba(239,68,68,0.25)" : "rgba(245,158,11,0.25)"}`,
              }}>{e.level === "crash" ? "CRASH" : "ERROR"}</span>
              <span style={{ color: "#8B95A8", fontWeight: 500 }}>{e.name}</span>
              <span style={{ color: "#5A6478", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.msg}</span>
            </div>
          ))}
        </div>

        {/* Google Sheets */}
        <div className="dash-panel" style={{ padding: "18px 20px" }}>
          <div className="dash-panel-title" style={{ marginBottom: 14 }}>Google Sheets</div>
          {[
            { name: "Track/Tracing Master", id: "19MB5Hmm...B2S0" },
            { name: "Boviet", id: "1OP-ZDaM...p3wI" },
            { name: "Tolead ORD", id: "1-zl7CCF...2ac" },
            { name: "Tolead JFK", id: "1mfhEsK2...Bhs" },
            { name: "Tolead LAX", id: "1YLB6z5L...bXo" },
            { name: "Tolead DFW", id: "1RfGcq25...9oI" },
          ].map(s => (
            <div key={s.name} style={{ padding: 10, borderRadius: 8, border: "1px solid rgba(255,255,255,0.04)", background: "rgba(0,0,0,0.15)", marginBottom: 7 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 13 }}>📊</span>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700 }}>{s.name}</div>
                  <div style={{ fontSize: 8, color: "#8B95A8" }}>Spreadsheet</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 9 }}>
                <span style={{ color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{s.id}</span>
                <span style={{ color: "#34d399", fontWeight: 700, fontSize: 9, padding: "1px 6px", borderRadius: 4, background: "#10b98112" }}>Operational</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// LOAD SLIDE-OVER PANEL (shared across all views)
// ═══════════════════════════════════════════════════════════════
function LoadSlideOver({ selectedShipment, setSelectedShipment, shipments, setShipments, handleStatusUpdate, editField, setEditField, editValue, setEditValue, handleFieldEdit, addSheetLog, carrierDirectory, onDocChange }) {
  const docInputRef = useRef(null);

  // FTL tracking preview state
  const [trackingData, setTrackingData] = useState(null);
  const [trackingLoading, setTrackingLoading] = useState(false);

  // Document hub state
  const [loadDocs, setLoadDocs] = useState([]);
  const [docFilter, setDocFilter] = useState("all");
  const [docUploading, setDocUploading] = useState(false);
  const [docType, setDocType] = useState("other");
  const [docUploadMsg, setDocUploadMsg] = useState(null);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [reclassDocId, setReclassDocId] = useState(null);
  const [loadEmails, setLoadEmails] = useState([]);
  const [copiedEfj, setCopiedEfj] = useState(false);

  // Driver contact state
  const [driverInfo, setDriverInfo] = useState({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
  const [driverEditing, setDriverEditing] = useState(null); // which field is being edited
  const [driverEditVal, setDriverEditVal] = useState("");
  const [driverSaving, setDriverSaving] = useState(false);
  const [statusExpanded, setStatusExpanded] = useState(false);
  const [emailsCollapsed, setEmailsCollapsed] = useState(true);
  const [aiSummary, setAiSummary] = useState(null);
  const [aiSummaryLoading, setAiSummaryLoading] = useState(false);

  // Timestamped notes log state
  const [loadNotes, setLoadNotes] = useState([]);
  const [noteInput, setNoteInput] = useState("");
  const [noteSubmitting, setNoteSubmitting] = useState(false);

  // Fetch tracking + documents + driver info when slide-over opens
  useEffect(() => {
    if (!selectedShipment) {
      setTrackingData(null);
      setLoadDocs([]);
      setDocUploadMsg(null);
      setDriverInfo({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
      setDriverEditing(null);
      setLoadEmails([]);
      setStatusExpanded(false);
      setAiSummary(null);
      setAiSummaryLoading(false);
      setLoadNotes([]);
      setNoteInput("");
      return;
    }
    setAiSummary(null);
    // Fetch documents
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`)
      .then(r => r.ok ? r.json() : { documents: [] })
      .then(data => setLoadDocs(data.documents || []))
      .catch(() => setLoadDocs([]));
    // Fetch email history
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/emails`)
      .then(r => r.ok ? r.json() : { emails: [] })
      .then(data => setLoadEmails(data.emails || []))
      .catch(() => setLoadEmails([]));
    // Fetch timestamped notes
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/notes`)
      .then(r => r.ok ? r.json() : { notes: [] })
      .then(data => setLoadNotes(data.notes || []))
      .catch(() => setLoadNotes([]));
    // Fetch driver contact info
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/driver`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setDriverInfo(data); })
      .catch(() => {});
    // Fetch tracking for FTL loads
    if (selectedShipment.moveType === "FTL" || selectedShipment.macropointUrl) {
      setTrackingLoading(true);
      apiFetch(`${API_BASE}/api/macropoint/${selectedShipment.efj}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data) setTrackingData(data);
          setTrackingLoading(false);
        })
        .catch(() => setTrackingLoading(false));
    }
  }, [selectedShipment?.efj]);

  // ESC to close preview modal (capture phase so it fires before slide-over ESC handler)
  useEffect(() => {
    if (!previewDoc) return;
    const handleKey = (e) => {
      if (e.key === "Escape") { setPreviewDoc(null); e.stopPropagation(); }
    };
    document.addEventListener("keydown", handleKey, true);
    return () => document.removeEventListener("keydown", handleKey, true);
  }, [previewDoc]);

  const saveDriverField = async (field, value) => {
    if (!selectedShipment?.efj) return;
    setDriverSaving(true);
    try {
      await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/driver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      setDriverInfo(prev => ({ ...prev, [field]: value }));
    } catch {}
    setDriverSaving(false);
    setDriverEditing(null);
  };

  // AI Summary — send pre-loaded context to Claude Haiku for operational summary
  // Submit a timestamped note
  const submitNote = async () => {
    const text = noteInput.trim();
    if (!text || !selectedShipment?.efj || noteSubmitting) return;
    setNoteSubmitting(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.note) setLoadNotes(prev => [data.note, ...prev]);
        setNoteInput("");
      }
    } catch (e) { /* ignore */ }
    setNoteSubmitting(false);
  };

  const requestAiSummary = async () => {
    if (!selectedShipment?.efj || aiSummaryLoading) return;
    setAiSummaryLoading(true);
    setAiSummary(null);
    try {
      const payload = {
        shipment: {
          efj: selectedShipment.efj, loadNumber: selectedShipment.loadNumber,
          container: selectedShipment.container, moveType: selectedShipment.moveType,
          account: selectedShipment.account, carrier: selectedShipment.carrier,
          status: selectedShipment.status, rawStatus: selectedShipment.rawStatus,
          origin: selectedShipment.origin, destination: selectedShipment.destination,
          eta: selectedShipment.eta, lfd: selectedShipment.lfd,
          pickupDate: selectedShipment.pickupDate, deliveryDate: selectedShipment.deliveryDate,
          bol: selectedShipment.bol, ssl: selectedShipment.ssl,
          returnPort: selectedShipment.returnPort, notes: selectedShipment.notes,
          botAlert: selectedShipment.botAlert, rep: selectedShipment.rep,
          hub: selectedShipment.hub, project: selectedShipment.project, mpStatus: selectedShipment.mpStatus,
        },
        emails: loadEmails.slice(0, 10).map(e => ({
          subject: e.subject, sender: e.sender, body_preview: e.body_preview,
          has_attachments: e.has_attachments, attachment_names: e.attachment_names, sent_at: e.sent_at,
        })),
        documents: loadDocs.map(d => ({ doc_type: d.doc_type, original_name: d.original_name, size_bytes: d.size_bytes, uploaded_at: d.uploaded_at })),
        driver: { driverName: driverInfo.driverName, driverPhone: driverInfo.driverPhone, driverEmail: driverInfo.driverEmail, carrierEmail: driverInfo.carrierEmail, trailerNumber: driverInfo.trailerNumber },
        tracking: trackingData ? { trackingStatus: trackingData.trackingStatus, eta: trackingData.eta, behindSchedule: trackingData.behindSchedule, cantMakeIt: trackingData.cantMakeIt, progress: trackingData.progress } : null,
      };
      const res = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/summary`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (res.ok) { const data = await res.json(); setAiSummary(data.summary); }
      else { setAiSummary("Failed to generate summary. Please try again."); }
    } catch { setAiSummary("Failed to generate summary. Please try again."); }
    setAiSummaryLoading(false);
  };

  const handleDocUpload = async (file) => {
    if (!selectedShipment?.efj || !file) return;
    setDocUploading(true); setDocUploadMsg(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("doc_type", docType);
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`, { method: "POST", body: fd });
      if (r.ok) {
        setDocUploadMsg("Uploaded");
        // Refresh doc list
        const listRes = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`);
        if (listRes.ok) { const data = await listRes.json(); setLoadDocs(data.documents || []); }
        addSheetLog(`Doc uploaded | ${selectedShipment.loadNumber}`);
        onDocChange?.();
      } else { setDocUploadMsg(`Upload failed (${r.status})`); }
    } catch { setDocUploadMsg("Upload error"); }
    setDocUploading(false);
  };

  const handleDocDelete = async (docId) => {
    if (!selectedShipment?.efj) return;
    try {
      await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${docId}`, { method: "DELETE" });
      setLoadDocs(prev => prev.filter(d => d.id !== docId));
      onDocChange?.();
    } catch {}
  };

  const handleDocReclassify = async (docId, newType) => {
    if (!selectedShipment?.efj) return;
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${docId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_type: newType }),
      });
      if (r.ok) {
        setLoadDocs(prev => prev.map(d => d.id === docId ? { ...d, doc_type: newType } : d));
        setReclassDocId(null);
        onDocChange?.();
      }
    } catch {}
  };

  const getFileExt = (name) => name?.split(".").pop().toLowerCase() || "";
  const isImage = (name) => ["png", "jpg", "jpeg", "tiff"].includes(getFileExt(name));
  const isPdf = (name) => getFileExt(name) === "pdf";

  // Parse tracking timeline for schedule grid
  const parsedStops = useMemo(() => {
    const pickup = { arrived: null, departed: null, eta: null, location: null };
    const delivery = { arrived: null, departed: null, eta: null, location: null };
    let delivered = null;
    let deliveredLocation = null;
    if (trackingData?.timeline?.length > 0) {
      trackingData.timeline.forEach(ev => {
        const e = ev.event?.toLowerCase() || "";
        if (e.includes("pickup") || e.includes("origin")) {
          if (ev.type === "arrived" || e.includes("arrived")) { pickup.arrived = ev.time; pickup.location = ev.location; }
          if (ev.type === "departed" || e.includes("departed")) pickup.departed = ev.time;
        }
        if (e.includes("delivery") || e.includes("destination")) {
          if (ev.type === "arrived" || e.includes("arrived")) { delivery.arrived = ev.time; delivery.location = ev.location; }
          if (ev.type === "departed" || e.includes("departed")) delivery.departed = ev.time;
        }
        if (ev.type === "eta") {
          if (e.includes("pickup")) pickup.eta = ev.time;
          if (e.includes("delivery")) delivery.eta = ev.time;
        }
        if (ev.type === "delivered") { delivered = ev.time; deliveredLocation = ev.location; }
      });
    }
    return { pickup, delivery, delivered, deliveredLocation };
  }, [trackingData]);

  if (!selectedShipment) return null;

  return (
    <>
      <div onClick={() => setSelectedShipment(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 50, animation: "fade-in 0.2s ease" }} />
      <div className="glass-strong" style={{ position: "fixed", top: 0, right: 0, width: 380, height: "100vh", zIndex: 60, display: "flex", flexDirection: "column", overflow: "hidden", animation: "slide-right 0.3s ease", borderLeft: "1px solid rgba(255,255,255,0.08)" }}>
        <div style={{ flex: 1, overflow: "auto" }}>
          {/* Header */}
          <div style={{ padding: "18px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>{selectedShipment.loadNumber}</div>
              <div style={{ fontSize: 10, color: "#8B95A8", marginTop: 2 }}>{selectedShipment.container} | {selectedShipment.moveType}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: selectedShipment.synced ? "#34d399" : "#fbbf24" }} />
                <span style={{ fontSize: 9, color: selectedShipment.synced ? "#34d399" : "#fbbf24", fontWeight: 600 }}>{selectedShipment.synced ? "Synced" : "Syncing..."}</span>
              </div>
              {/* Trip Progress Bar */}
              {(selectedShipment.moveType === "FTL") && (() => {
                const steps = trackingData?.progress || [];
                const done = steps.filter(s => s.done).length;
                const pct = steps.length > 0 ? Math.round((done / steps.length) * 100) : 0;
                const statusColor = pct >= 100 ? "#34d399" : pct > 50 ? "#60a5fa" : pct > 0 ? "#fbbf24" : "#3D4557";
                const loc = trackingData?.lastLocation;
                const locLabel = loc ? `${loc.city}, ${loc.state}` : null;
                return (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <span style={{ fontSize: 8, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.5px", color: statusColor }}>
                        {trackingData?.trackingStatus || selectedShipment.status || "Pending"}
                      </span>
                      {(trackingData?.eta || selectedShipment.eta) && (
                        <span style={{ fontSize: 8, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>
                          ETA {trackingData?.eta || selectedShipment.eta}
                        </span>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 7, color: pct > 0 ? "#8B95A8" : "#5A6478", fontWeight: 600, flexShrink: 0, maxWidth: 70, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {selectedShipment.origin || "Origin"}
                      </span>
                      <div style={{ flex: 1, position: "relative", height: 5 }}>
                        <div style={{ position: "absolute", inset: 0, borderRadius: 3, background: "rgba(255,255,255,0.06)" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: `${Math.max(pct, 2)}%`, borderRadius: 3, background: `linear-gradient(90deg, ${statusColor}88, ${statusColor})`, transition: "width 0.5s ease" }} />
                        {pct > 0 && pct < 100 && (
                          <div title={locLabel || ""} style={{ position: "absolute", top: "50%", left: `${pct}%`, transform: "translate(-50%, -50%)", width: 9, height: 9, borderRadius: "50%", background: statusColor, border: "2px solid #141A28", boxShadow: `0 0 6px ${statusColor}66` }} />
                        )}
                      </div>
                      <span style={{ fontSize: 7, color: pct >= 100 ? "#34d399" : "#5A6478", fontWeight: 600, flexShrink: 0, maxWidth: 70, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {selectedShipment.destination || "Dest"}
                      </span>
                    </div>
                    {locLabel && pct > 0 && pct < 100 && (
                      <div style={{ textAlign: "center", marginTop: 2 }}>
                        <span style={{ fontSize: 7, color: "#5A6478", fontStyle: "italic" }}>{locLabel}</span>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
            <button onClick={() => setSelectedShipment(null)} style={{ background: "rgba(255,255,255,0.05)", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 14, width: 28, height: 28, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
          </div>

          {/* Quick Action Strip */}
          <div style={{ padding: "8px 20px 10px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[
              { icon: "📋", label: copiedEfj ? "Copied!" : "Copy EFJ", color: copiedEfj ? "#34d399" : "rgba(255,255,255,0.5)",
                onClick: () => { navigator.clipboard.writeText(selectedShipment.efj); setCopiedEfj(true); setTimeout(() => setCopiedEfj(false), 1500); }, enabled: true },
              { icon: "📧", label: "Email", color: "#00D4AA",
                onClick: () => { const email = driverInfo.carrierEmail || driverInfo.driverEmail; if (email) window.open(`mailto:${email}?subject=${encodeURIComponent(`${selectedShipment.loadNumber} - ${selectedShipment.container} Update`)}`); },
                enabled: !!(driverInfo.carrierEmail || driverInfo.driverEmail) },
              { icon: "📞", label: "Call", color: "#10b981",
                onClick: () => { if (driverInfo.driverPhone) window.open(`tel:${driverInfo.driverPhone.replace(/\D/g, "")}`); },
                enabled: !!driverInfo.driverPhone },
              { icon: "📍", label: "Tracking", color: "#3B82F6",
                onClick: () => { const url = trackingData?.macropointUrl || driverInfo.macropointUrl || selectedShipment.macropointUrl; if (url) window.open(url, '_blank'); },
                enabled: !!(trackingData?.macropointUrl || driverInfo.macropointUrl || selectedShipment.macropointUrl) },
              { icon: "📄", label: "BOL", color: "rgba(255,255,255,0.5)",
                onClick: () => { const bol = loadDocs.find(d => d.doc_type === 'bol'); if (bol) setPreviewDoc(bol); },
                enabled: loadDocs.some(d => d.doc_type === 'bol') },
              { icon: "✦", label: aiSummaryLoading ? "Thinking..." : "AI Summary",
                color: aiSummaryLoading ? "#fbbf24" : "#00D4AA",
                onClick: requestAiSummary, enabled: !aiSummaryLoading },
            ].map((btn, i) => (
              <button key={i} onClick={btn.enabled ? btn.onClick : undefined}
                style={{ background: btn.enabled ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.02)", border: `1px solid ${btn.enabled ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.04)"}`,
                  borderRadius: 6, padding: "5px 10px", cursor: btn.enabled ? "pointer" : "default",
                  color: btn.enabled ? btn.color : "rgba(255,255,255,0.2)", fontSize: 10, fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 600,
                  transition: "all 0.15s ease", opacity: btn.enabled ? 1 : 0.5 }}
                title={!btn.enabled ? "Not available" : btn.label}
              >{btn.icon} {btn.label}</button>
            ))}
          </div>

          {/* AI Summary — inline section */}
          {(aiSummary || aiSummaryLoading) && (
            <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              {aiSummaryLoading ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 8, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}>
                  <div style={{ width: 12, height: 12, border: "2px solid rgba(0,212,170,0.2)", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
                  <span style={{ fontSize: 10, color: "#00D4AA", fontWeight: 600 }}>Generating AI summary...</span>
                </div>
              ) : (
                <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)", position: "relative" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: "#00D4AA", textTransform: "uppercase", letterSpacing: "0.05em" }}>AI Summary</span>
                    <button onClick={() => setAiSummary(null)} style={{ background: "none", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 12, padding: "0 2px", lineHeight: 1 }} title="Dismiss">✕</button>
                  </div>
                  <div style={{ fontSize: 11, color: "#C8CED8", lineHeight: 1.6, whiteSpace: "pre-line" }}>{aiSummary}</div>
                </div>
              )}
            </div>
          )}

          {/* Behind schedule / Can't make it warnings — FTL only */}
          {selectedShipment.moveType === "FTL" && trackingData?.cantMakeIt && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 9, color: "#f87171", fontWeight: 600 }}>
                ⚠ {trackingData.cantMakeIt}
              </div>
            </div>
          )}
          {selectedShipment.moveType === "FTL" && trackingData?.behindSchedule && !trackingData?.cantMakeIt && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(251,146,60,0.12)", border: "1px solid rgba(251,146,60,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 9, color: "#fb923c", fontWeight: 600 }}>
                ⏱ Behind Schedule{trackingData?.mpDisplayDetail ? ` — ${trackingData.mpDisplayDetail}` : ""}
              </div>
            </div>
          )}
          {selectedShipment.moveType === "FTL" && trackingData?.mpDisplayStatus === "On Time" && !trackingData?.cantMakeIt && !trackingData?.behindSchedule && trackingData?.mpDisplayDetail && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 9, color: "#22C55E", fontWeight: 600 }}>
                ✓ On Time — {trackingData.mpDisplayDetail}
              </div>
            </div>
          )}

          {/* Schedule & Tracking — compact table */}
          {(selectedShipment.pickupDate || selectedShipment.deliveryDate || parsedStops.pickup.arrived || parsedStops.delivery.arrived) && (() => {
            const fmtTs = (v) => {
              if (!v) return "";
              // ISO timestamp (from tracking events) — check for digit-T-digit to avoid matching "ET" suffix
              if (/\dT\d/.test(v)) { try { const d = new Date(v); if (!isNaN(d)) return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; } catch {} }
              // Scheduled dates like "3/6/2026 9:00" or "2026-03-06 09:00" — strip year, show m/d h:mm
              const m = v.match(/^(\d{1,2})\/(\d{1,2})\/\d{4}\s+(.+)/);
              if (m) return `${m[1]}/${m[2]} ${m[3]}`;
              const m2 = v.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}:\d{2})/);
              if (m2) return `${parseInt(m2[2])}/${parseInt(m2[3])} ${m2[4]}`;
              // Already compact like "3/6 20:45"
              return v;
            };
            const origin = selectedShipment.origin || trackingData?.origin || "";
            const dest = selectedShipment.destination || trackingData?.destination || "";
            const mono = { fontFamily: "'JetBrains Mono', monospace", fontSize: 9, fontWeight: 600 };
            const headerCell = { fontSize: 7, fontWeight: 700, color: "#5A6478", letterSpacing: "1px", textTransform: "uppercase", padding: "0 0 3px", textAlign: "right" };
            const valCell = { ...mono, padding: "2px 0", textAlign: "right" };
            return (
            <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Schedule & Tracking</div>
              <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr 1fr", gap: "0 10px", alignItems: "center" }}>
                {/* Header row */}
                <div />
                <div style={headerCell}>Sched</div>
                <div style={headerCell}>Arrived</div>
                <div style={headerCell}>Departed</div>
                {/* Pickup row */}
                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#f59e0b", flexShrink: 0 }} />
                  <span style={{ fontSize: 9, fontWeight: 700, color: "#F0F2F5" }}>PU</span>
                  {origin && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{origin.length > 18 ? origin.slice(0, 18) + "…" : origin}</span>}
                </div>
                <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.pickupDate) || "—"}</div>
                <div style={{ ...valCell, color: parsedStops.pickup.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.pickup.arrived) || "—"}</div>
                <div style={{ ...valCell, color: parsedStops.pickup.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.pickup.departed) || "—"}</div>
                {/* Delivery row */}
                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#10b981", flexShrink: 0 }} />
                  <span style={{ fontSize: 9, fontWeight: 700, color: "#F0F2F5" }}>DEL</span>
                  {dest && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{dest.length > 18 ? dest.slice(0, 18) + "…" : dest}</span>}
                </div>
                <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.deliveryDate) || "—"}</div>
                <div style={{ ...valCell, color: parsedStops.delivery.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.delivery.arrived) || "—"}</div>
                <div style={{ ...valCell, color: parsedStops.delivery.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.delivery.departed) || "—"}</div>
              </div>
              {/* Delivered confirmation */}
              {parsedStops.delivered && (
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#00D4AA", flexShrink: 0 }} />
                  <span style={{ fontSize: 9, fontWeight: 700, color: "#00D4AA" }}>Delivered</span>
                  {parsedStops.deliveredLocation && <span style={{ fontSize: 8, color: "#5A6478" }}>{parsedStops.deliveredLocation}</span>}
                  <span style={{ marginLeft: "auto", ...mono, fontSize: 9, color: "#8B95A8" }}>{fmtTs(parsedStops.delivered)}</span>
                </div>
              )}
            </div>
            );
          })()}

          {/* Status Selector — collapsible, move-type aware */}
          {(() => {
            const allStatuses = [...getStatusesForShipment(selectedShipment).filter(s => s.key !== "all"), ...BILLING_STATUSES];
            const activeStatus = allStatuses.find(s => s.key === selectedShipment.status);
            const activeColor = (getStatusColors(selectedShipment)[selectedShipment.status] || BILLING_STATUS_COLORS[selectedShipment.status] || { main: "#94a3b8" }).main;
            return (
              <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setStatusExpanded(!statusExpanded)}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>Status</span>
                    {!statusExpanded && activeStatus && (
                      <span style={{ padding: "3px 10px", fontSize: 9, fontWeight: 700, borderRadius: 20,
                        border: `1px solid ${activeColor}66`, background: `${activeColor}18`, color: activeColor,
                        fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{activeStatus.label}</span>
                    )}
                  </div>
                  <span style={{ fontSize: 10, color: "#5A6478", transition: "transform 0.15s" }}>{statusExpanded ? "▾" : "▸"}</span>
                </div>
                {statusExpanded && (
                  <>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
                      {getStatusesForShipment(selectedShipment).filter(s => s.key !== "all").map(s => {
                        const isActive = selectedShipment.status === s.key;
                        const sc2 = getStatusColors(selectedShipment)[s.key] || { main: "#94a3b8" };
                        return (
                          <button key={s.key} onClick={() => handleStatusUpdate(selectedShipment.id, s.key)}
                            style={{ padding: "4px 10px", fontSize: 9, fontWeight: 700, borderRadius: 20,
                              border: `1px solid ${isActive ? sc2.main + "66" : "rgba(255,255,255,0.06)"}`,
                              background: isActive ? `${sc2.main}18` : "transparent",
                              color: isActive ? sc2.main : "#64748b", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{s.label}</button>
                        );
                      })}
                    </div>
                    {(["delivered", "empty_return", "need_pod", "pod_received", "driver_paid", "ready_to_close", "missing_invoice", "billed_closed", "ppwk_needed", "waiting_confirmation", "waiting_cx_approval", "cx_approved"].includes(selectedShipment.status)) && (
                      <>
                        <div style={{ fontSize: 8, fontWeight: 700, color: "#5A6478", letterSpacing: "2px", marginTop: 10, marginBottom: 6, textTransform: "uppercase" }}>Billing</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {BILLING_STATUSES.map(s => {
                            const isActive = selectedShipment.status === s.key;
                            const sc2 = BILLING_STATUS_COLORS[s.key] || { main: "#94a3b8" };
                            return (
                              <button key={s.key} onClick={() => handleStatusUpdate(selectedShipment.id, s.key)}
                                style={{ padding: "3px 8px", fontSize: 8, fontWeight: 700, borderRadius: 16,
                                  border: `1px solid ${isActive ? sc2.main + "66" : "rgba(255,255,255,0.06)"}`,
                                  background: isActive ? `${sc2.main}18` : "transparent",
                                  color: isActive ? sc2.main : "#64748b", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{s.label}</button>
                            );
                          })}
                        </div>
                      </>
                    )}
                  </>
                )}
              </div>
            );
          })()}

          {/* Unified Fields Grid — shipment details + driver contact */}
          <div style={{ padding: "14px 20px" }}>
            {[
              { label: "Account", field: "account", val: selectedShipment.account },
              { label: "Container / Load #", field: "container", val: selectedShipment.container },
              { label: "BOL / Booking", field: "bol", val: selectedShipment.bol },
              ...(selectedShipment.moveType !== "FTL" ? [
                { label: "SSL / Vessel", field: "ssl", val: selectedShipment.ssl },
              ] : []),
              { label: "Carrier", field: "carrier", val: selectedShipment.carrier },
              // Carrier directory info for dray loads
              ...(() => {
                if (selectedShipment.moveType === "FTL" || !selectedShipment.carrier || !carrierDirectory?.length) return [];
                const cLower = selectedShipment.carrier.toLowerCase();
                const match = carrierDirectory.find(c => {
                  const n = (c.carrier_name || "").toLowerCase();
                  return n === cLower || n.startsWith(cLower) || cLower.startsWith(n);
                });
                if (!match) return [];
                return [
                  ...(match.mc_number ? [{ label: "MC #", field: "_mc", val: match.mc_number, readOnly: true }] : []),
                  ...(match.v_code ? [{ label: "V-Code", field: "_vcode", val: match.v_code, readOnly: true }] : []),
                ];
              })(),
              { label: "Move Type", field: "moveType", val: selectedShipment.moveType },
              { label: "Origin", field: "origin", val: selectedShipment.origin },
              { label: "Destination", field: "destination", val: selectedShipment.destination },
              ...(selectedShipment.moveType !== "FTL" ? [
                { label: "ETA", field: "eta", val: selectedShipment.eta },
                { label: "LFD", field: "lfd", val: selectedShipment.lfd },
              ] : []),
              { label: "Pickup", field: "pickupDate", val: selectedShipment.pickupDate },
              { label: "Delivery", field: "deliveryDate", val: selectedShipment.deliveryDate },
              // Driver contact fields (inline with shipment details)
              ...((selectedShipment.moveType === "FTL" || selectedShipment.macropointUrl) ? [
                { label: "Driver", dField: "driverName", val: driverInfo.driverName, placeholder: "Add name", isDriver: true },
                { label: "Phone", dField: "driverPhone", val: driverInfo.driverPhone, placeholder: "(555) 555-5555", action: driverInfo.driverPhone ? "call" : null, isDriver: true },
                { label: "Email", dField: "driverEmail", val: driverInfo.driverEmail, placeholder: "driver@email.com", action: driverInfo.driverEmail ? "email" : null, isDriver: true },
                { label: "Carrier Email", dField: "carrierEmail", val: driverInfo.carrierEmail, placeholder: "carrier@email.com", action: driverInfo.carrierEmail ? "email" : null, isDriver: true },
                { label: "Trailer", dField: "trailerNumber", val: driverInfo.trailerNumber, placeholder: "Trailer #", isDriver: true },
                { label: "MP URL", dField: "macropointUrl", val: driverInfo.macropointUrl || selectedShipment.macropointUrl, placeholder: "Set URL", isDriver: true },
              ] : []),
            ].map((item) => (
              <div key={item.field || item.dField} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                <span style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{item.label}</span>
                {item.isDriver ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    {driverEditing === item.dField ? (
                      <input autoFocus value={driverEditVal}
                        onChange={e => setDriverEditVal(e.target.value)}
                        onBlur={() => saveDriverField(item.dField, driverEditVal)}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setDriverEditing(null); }}
                        placeholder={item.placeholder}
                        style={{ background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, color: "#F0F2F5", padding: "3px 8px", fontSize: 11, width: 140, textAlign: "right", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                    ) : (
                      <span onClick={() => { setDriverEditing(item.dField); setDriverEditVal(item.val || ""); }}
                        style={{ fontSize: 11, color: item.dField === "macropointUrl" && item.val ? "#00D4AA" : item.val ? "#F0F2F5" : "#3D4557", cursor: "pointer", fontWeight: 500,
                          maxWidth: item.action ? 130 : 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title="Click to edit">{item.val || item.placeholder}</span>
                    )}
                    {item.action === "call" && (
                      <a href={`tel:${item.val.replace(/\D/g, "")}`}
                        style={{ padding: "2px 6px", borderRadius: 4, background: "rgba(16,185,129,0.15)", border: "1px solid rgba(16,185,129,0.3)", color: "#10b981", fontSize: 8, fontWeight: 700, textDecoration: "none" }}>Call</a>
                    )}
                    {item.action === "email" && (
                      <a href={`mailto:${item.val}?subject=${encodeURIComponent(`${selectedShipment.loadNumber} - ${selectedShipment.container} Update`)}`}
                        style={{ padding: "2px 6px", borderRadius: 4, background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.3)", color: "#3b82f6", fontSize: 8, fontWeight: 700, textDecoration: "none" }}>Email</a>
                    )}
                  </div>
                ) : item.readOnly ? (
                  <span style={{ fontSize: 11, color: "#8B95A8", fontWeight: 500, fontFamily: "'JetBrains Mono', monospace" }}>{item.val}</span>
                ) : editField === `${selectedShipment.id}-${item.field}` ? (
                  <input autoFocus value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={() => {
                      const v = editValue.trim();
                      const SLIDE_FIELD_MAP = { pickupDate: "pickup", deliveryDate: "delivery", carrier: "carrier", origin: "origin", destination: "destination", eta: "eta", lfd: "lfd", ssl: "ssl", container: "container", bol: "bol" };
                      const pgField = SLIDE_FIELD_MAP[item.field];
                      if (v || item.field === 'pickupDate' || item.field === 'deliveryDate') {
                        if (pgField && selectedShipment.efj) { handleFieldUpdate(selectedShipment, pgField, v); }
                        else { handleFieldEdit(selectedShipment.id, item.field, v); }
                      }
                      setEditField(null);
                    }}
                    onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditField(null); }}
                    style={{ background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, color: "#F0F2F5", padding: "3px 8px", fontSize: 11, width: 140, textAlign: "right", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                ) : (
                  <span onClick={(e) => { e.stopPropagation(); setEditField(`${selectedShipment.id}-${item.field}`); setEditValue(String(item.val || "")); }}
                    style={{ fontSize: 11, color: "#F0F2F5", cursor: "pointer", padding: "2px 6px", borderRadius: 4, fontWeight: 500 }}
                    title="Click to edit">{item.val || "—"}</span>
                )}
              </div>
            ))}
          </div>

          {/* Notes */}
          <div style={{ padding: "8px 20px 14px" }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Notes</div>
            <textarea
              value={shipments.find(s => s.id === selectedShipment.id)?.notes || ""}
              onChange={e => { const v = e.target.value; setShipments(prev => prev.map(s => s.id === selectedShipment.id ? { ...s, notes: v } : s)); }}
              onBlur={() => addSheetLog(`Notes updated | ${selectedShipment.loadNumber}`)}
              placeholder="Add notes..."
              style={{ width: "100%", minHeight: 50, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", padding: 10, fontSize: 11, resize: "vertical", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
          </div>

          {/* Timestamped Notes Log */}
          <div style={{ padding: "4px 20px 14px" }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>
              Notes Log {loadNotes.length > 0 && <span style={{ color: "#5A6478" }}>({loadNotes.length})</span>}
            </div>
            <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
              <input
                value={noteInput}
                onChange={e => setNoteInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitNote(); } }}
                placeholder="Add a timestamped note..."
                style={{ flex: 1, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#F0F2F5", padding: "7px 10px", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
              <button
                onClick={submitNote}
                disabled={!noteInput.trim() || noteSubmitting}
                style={{ background: noteInput.trim() ? "#00D4AA" : "rgba(255,255,255,0.06)", color: noteInput.trim() ? "#0A0E17" : "#5A6478", border: "none", borderRadius: 8, padding: "6px 14px", fontSize: 10, fontWeight: 700, cursor: noteInput.trim() ? "pointer" : "default", opacity: noteSubmitting ? 0.5 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {noteSubmitting ? "..." : "Add"}
              </button>
            </div>
            {loadNotes.length > 0 && (
              <div style={{ maxHeight: 180, overflow: "auto", borderLeft: "2px solid rgba(0,212,170,0.15)", paddingLeft: 12 }}>
                {loadNotes.map(n => (
                  <div key={n.id} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                    <div style={{ fontSize: 10, color: "#F0F2F5", lineHeight: 1.4 }}>{n.note_text}</div>
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 3 }}>
                      {n.created_by} &middot; {new Date(n.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Email History (collapsible) */}
          {loadEmails.length > 0 && (
            <div style={{ padding: "8px 20px 12px" }}>
              <div onClick={() => setEmailsCollapsed(prev => !prev)}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>
                  Emails <span style={{ color: "#8B95A8" }}>({loadEmails.length})</span>
                </div>
                <span style={{ fontSize: 10, color: "#5A6478", transition: "transform 0.2s", transform: emailsCollapsed ? "rotate(0deg)" : "rotate(180deg)" }}>&#9660;</span>
              </div>
              {!emailsCollapsed && (
                <div style={{ maxHeight: 200, overflow: "auto", marginTop: 8 }}>
                  {loadEmails.map(em => (
                    <div key={em.id} style={{ display: "flex", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1 }}>{em.has_attachments ? "\u{1F4CE}" : "\u2709"}</span>
                      {em.priority && <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginTop: 5, background: em.priority >= 5 ? "#EF4444" : em.priority >= 4 ? "#F97316" : em.priority >= 3 ? "#3B82F6" : "#6B7280" }} />}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <div style={{ fontSize: 10, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
                            {em.subject || "(no subject)"}
                          </div>
                          {em.email_type && em.email_type !== "general" && (
                            <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, fontWeight: 600, background: em.email_type.includes("rate") ? "rgba(0,212,170,0.15)" : em.email_type === "detention" ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.15)", color: em.email_type.includes("rate") ? "#00D4AA" : em.email_type === "detention" ? "#EF4444" : "#3B82F6", whiteSpace: "nowrap", flexShrink: 0 }}>
                              {em.email_type.replace(/_/g, " ").toUpperCase()}
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 8, color: "#8B95A8" }}>
                          {(em.sender || "").replace(/<[^>]+>/g, "").trim()}
                          {" \u00B7 "}
                          {em.sent_at ? new Date(em.sent_at).toLocaleDateString("en-US", { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}
                        </div>
                        {em.ai_summary && (
                          <div style={{ fontSize: 8, color: "#5A6478", marginTop: 2, fontStyle: "italic", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {em.ai_summary}
                          </div>
                        )}
                        {em.attachment_names && (
                          <div style={{ fontSize: 8, color: "#4D5669", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {em.attachment_names}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Document Hub */}
          <div style={{ padding: "8px 20px 20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>
                Documents {loadDocs.length > 0 && <span style={{ color: "#8B95A8" }}>({loadDocs.length})</span>}
              </div>
            </div>

            {/* Category filter tabs */}
            {loadDocs.length > 0 && (
              <div style={{ display: "flex", gap: 2, marginBottom: 10, background: "#0D1119", borderRadius: 10, padding: 3 }}>
                {[
                  { id: "all", label: "All" },
                  { id: "cx_rate", label: "CX Rate", match: t => t === "customer_rate" },
                  { id: "rc", label: "RC", match: t => t === "carrier_rate" },
                  { id: "pod", label: "POD", match: t => t === "pod" },
                  { id: "bol", label: "BOL", match: t => t === "bol" },
                  { id: "email", label: "Email", match: t => t === "email" },
                  { id: "carrier_invoice", label: "Carrier Invoice", match: t => t === "carrier_invoice" },
                  { id: "other", label: "Other", match: t => t !== "customer_rate" && t !== "carrier_rate" && t !== "pod" && t !== "bol" && t !== "email" && t !== "carrier_invoice" },
                ].map(tab => {
                  const count = tab.id === "all" ? loadDocs.length : loadDocs.filter(d => tab.match(d.doc_type)).length;
                  return (
                    <button key={tab.id} onClick={() => setDocFilter(tab.id)}
                      style={{ flex: 1, padding: "3px 6px", borderRadius: 4, border: "none", fontSize: 8, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                        background: docFilter === tab.id ? "#1E2738" : "transparent", boxShadow: docFilter === tab.id ? "0 1px 4px rgba(0,0,0,0.3)" : "none",
                        color: docFilter === tab.id ? "#F0F2F5" : "#8B95A8" }}>
                      {tab.label} {count > 0 && <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{count}</span>}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Document list */}
            {loadDocs.length > 0 && (
              <div style={{ maxHeight: 180, overflow: "auto", marginBottom: 10 }}>
                {loadDocs.filter(d => {
                  if (docFilter === "all") return true;
                  if (docFilter === "cx_rate") return d.doc_type === "customer_rate";
                  if (docFilter === "rc") return d.doc_type === "carrier_rate";
                  if (docFilter === "pod") return d.doc_type === "pod";
                  if (docFilter === "bol") return d.doc_type === "bol";
                  if (docFilter === "email") return d.doc_type === "email";
                  if (docFilter === "carrier_invoice") return d.doc_type === "carrier_invoice";
                  return d.doc_type !== "customer_rate" && d.doc_type !== "carrier_rate" && d.doc_type !== "pod" && d.doc_type !== "bol" && d.doc_type !== "email" && d.doc_type !== "carrier_invoice";
                }).map(doc => {
                  const icon = doc.doc_type === "carrier_invoice" ? "🧾" : doc.doc_type.includes("rate") ? "💰" : doc.doc_type === "pod" ? "📸" : doc.doc_type === "bol" ? "📋" : doc.doc_type === "screenshot" ? "🖼" : doc.doc_type === "email" ? "✉" : "📄";
                  const size = doc.size_bytes < 1024 ? `${doc.size_bytes}B` : doc.size_bytes < 1048576 ? `${Math.round(doc.size_bytes / 1024)}KB` : `${(doc.size_bytes / 1048576).toFixed(1)}MB`;
                  const date = doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString("en-US", { month: "numeric", day: "numeric" }) : "";
                  return (
                    <div key={doc.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, cursor: "pointer" }}
                        onClick={() => setPreviewDoc(doc)}>
                        <span style={{ fontSize: 12, flexShrink: 0 }}>{icon}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 10, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.original_name}</div>
                          <div style={{ fontSize: 8, color: "#8B95A8", display: "flex", alignItems: "center", gap: 4 }}>
                            {reclassDocId === doc.id ? (
                              <select autoFocus value={doc.doc_type}
                                onChange={e => handleDocReclassify(doc.id, e.target.value)}
                                onBlur={() => setReclassDocId(null)}
                                onClick={e => e.stopPropagation()}
                                style={{ background: "#0D1119", border: "1px solid #00D4AA", borderRadius: 4, color: "#F0F2F5", fontSize: 11, padding: "2px 6px", outline: "none", fontFamily: "inherit", cursor: "pointer" }}>
                                <option value="customer_rate">Customer Rate</option>
                                <option value="carrier_rate">Carrier Rate</option>
                                <option value="pod">POD</option>
                                <option value="bol">BOL</option>
                                <option value="carrier_invoice">Carrier Invoice</option>
                                <option value="screenshot">Screenshot</option>
                                <option value="email">Email</option>
                                <option value="other">Other</option>
                              </select>
                            ) : (
                              <span onClick={e => { e.stopPropagation(); setReclassDocId(doc.id); }}
                                style={{ cursor: "pointer", background: "rgba(0,212,170,0.08)", border: "1px solid rgba(0,212,170,0.25)", borderRadius: 3, padding: "2px 6px", color: "#00D4AA", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }}
                                title="Click to change type">
                                {doc.doc_type.replace("_", " ")} <span style={{ fontSize: 9, opacity: 0.7 }}>{"\u25BC"}</span>
                              </span>
                            )}
                            <span>· {size} · {date}</span>
                          </div>
                        </div>
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${doc.id}/download`, '_blank'); }}
                        style={{ background: "none", border: "none", color: "#00D4AA", cursor: "pointer", fontSize: 10, padding: "2px 4px", flexShrink: 0 }}>↓</button>
                      <button onClick={(e) => { e.stopPropagation(); handleDocDelete(doc.id); }}
                        style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 10, padding: "2px 4px", flexShrink: 0 }}
                        onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>✕</button>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Upload area */}
            <input ref={docInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff,.xlsx,.xls,.doc,.docx,.eml,.msg" style={{ display: "none" }}
              onChange={e => { if (e.target.files[0]) handleDocUpload(e.target.files[0]); e.target.value = ""; }} />
            <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
              <select value={docType} onChange={e => setDocType(e.target.value)}
                style={{ flex: 1, padding: "6px 8px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, color: "#8B95A8", fontSize: 10, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", cursor: "pointer" }}>
                <option value="customer_rate" style={{ background: "#0D1119" }}>Customer Rate</option>
                <option value="carrier_rate" style={{ background: "#0D1119" }}>Carrier Rate</option>
                <option value="pod" style={{ background: "#0D1119" }}>POD</option>
                <option value="bol" style={{ background: "#0D1119" }}>BOL</option>
                <option value="carrier_invoice" style={{ background: "#0D1119" }}>Carrier Invoice</option>
                <option value="screenshot" style={{ background: "#0D1119" }}>Screenshot</option>
                <option value="email" style={{ background: "#0D1119" }}>Email</option>
                <option value="other" style={{ background: "#0D1119" }}>Other</option>
              </select>
              <button onClick={() => docInputRef.current?.click()} disabled={docUploading}
                style={{ padding: "6px 14px", borderRadius: 6, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 10, fontWeight: 700, cursor: docUploading ? "default" : "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", opacity: docUploading ? 0.6 : 1 }}>
                {docUploading ? "..." : "+ Upload"}
              </button>
            </div>
            <div onClick={() => !docUploading && docInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={e => { e.preventDefault(); e.stopPropagation(); if (e.dataTransfer?.files?.[0]) handleDocUpload(e.dataTransfer.files[0]); }}
              style={{ padding: "12px 14px", borderRadius: 8, background: "rgba(255,255,255,0.02)", border: "1px dashed rgba(255,255,255,0.1)", color: "#8B95A8", fontSize: 10, textAlign: "center", cursor: docUploading ? "default" : "pointer" }}>
              Drop files here — PDF, images, Excel, Word, email
            </div>
            {docUploadMsg && (
              <div style={{ marginTop: 6, fontSize: 10, fontWeight: 600, color: docUploadMsg === "Uploaded" ? "#34d399" : "#f87171", textAlign: "center" }}>
                {docUploadMsg}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Document Preview Modal */}
      {previewDoc && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", backdropFilter: "blur(12px)",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          zIndex: 200, padding: 20,
        }} onClick={() => setPreviewDoc(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            width: "90%", maxWidth: 900, maxHeight: "90vh", display: "flex", flexDirection: "column",
            background: "#0D1119", borderRadius: 16, border: "1px solid rgba(255,255,255,0.08)",
            overflow: "hidden",
          }}>
            {/* Header */}
            <div style={{
              padding: "12px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)",
              display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ fontSize: 14 }}>
                  {previewDoc.doc_type === "carrier_invoice" ? "\u{1f9fe}" : previewDoc.doc_type.includes("rate") ? "\u{1f4b0}" : previewDoc.doc_type === "pod" ? "\u{1f4f8}" : previewDoc.doc_type === "bol" ? "\u{1f4cb}" : previewDoc.doc_type === "screenshot" ? "\u{1f5bc}" : previewDoc.doc_type === "email" ? "\u2709" : "\u{1f4c4}"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {previewDoc.original_name}
                  </div>
                  <div style={{ fontSize: 10, color: "#8B95A8" }}>
                    {previewDoc.doc_type.replace("_", " ")} · {previewDoc.size_bytes < 1048576 ? `${Math.round(previewDoc.size_bytes / 1024)}KB` : `${(previewDoc.size_bytes / 1048576).toFixed(1)}MB`}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button onClick={() => window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download`, '_blank')}
                  style={{ padding: "6px 14px", borderRadius: 8, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                  Download
                </button>
                <button onClick={() => setPreviewDoc(null)}
                  style={{ background: "rgba(255,255,255,0.06)", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 14, width: 32, height: 32, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  ✕
                </button>
              </div>
            </div>
            {/* Preview content */}
            <div style={{ flex: 1, overflow: "auto", display: "flex", alignItems: "center", justifyContent: "center", padding: 20, minHeight: 300 }}>
              {isImage(previewDoc.original_name) ? (
                <img
                  src={`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download?inline=true`}
                  alt={previewDoc.original_name}
                  style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", borderRadius: 8 }}
                />
              ) : isPdf(previewDoc.original_name) ? (
                <iframe
                  src={`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download?inline=true`}
                  title={previewDoc.original_name}
                  style={{ width: "100%", height: "70vh", border: "none", borderRadius: 8, background: "#fff" }}
                />
              ) : (
                <div style={{ textAlign: "center", color: "#5A6478" }}>
                  <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>{"\u{1f4c4}"}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>No preview available</div>
                  <div style={{ fontSize: 11, color: "#3D4557", marginBottom: 16 }}>
                    {getFileExt(previewDoc.original_name).toUpperCase()} files cannot be previewed in the browser
                  </div>
                  <button onClick={() => window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download`, '_blank')}
                    style={{ padding: "8px 20px", borderRadius: 8, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    Download File
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// DISPATCH TABLE VIEW
// ═══════════════════════════════════════════════════════════════
function DispatchView({
  loaded, shipments, filtered, accounts,
  activeStatus, setActiveStatus, activeAccount, setActiveAccount,
  activeRep, setActiveRep, searchQuery, setSearchQuery, statusCounts,
  selectedShipment, setSelectedShipment,
  editField, setEditField, editValue, setEditValue,
  sheetLog, handleStatusUpdate, handleFieldEdit, handleLoadClick,
  activeLoads, inTransit, deliveredCount, issueCount, onAddLoad, addSheetLog, setShipments,
  podUploading, setPodUploading, podUploadMsg, setPodUploadMsg,
  trackingSummary, docSummary,
  dateFilter, setDateFilter,
  moveTypeFilter, setMoveTypeFilter,
  dateRangeField, setDateRangeField, dateRangeStart, setDateRangeStart,
  dateRangeEnd, setDateRangeEnd,
  handleFieldUpdate,
  handleMetadataUpdate,
  handleDriverFieldUpdate,
}) {
  const ACCOUNTS = accounts || ["All Accounts"];
  const podInputRef = useRef(null);
  const docInputRef = useRef(null);
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [inlineEditId, setInlineEditId] = useState(null);
  const [inlineEditField, setInlineEditField] = useState(null);
  const [inlineEditValue, setInlineEditValue] = useState("");
  const [showDatePopover, setShowDatePopover] = useState(false);
  const [zebraStripe, setZebraStripe] = useState(true);
  const [columnFilters, setColumnFilters] = useState({});
  const [openFilterCol, setOpenFilterCol] = useState(null);

  // Close column filter dropdown on outside click
  useEffect(() => {
    if (!openFilterCol) return;
    const handler = (e) => { if (!e.target.closest('.col-filter-dd')) setOpenFilterCol(null); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [openFilterCol]);

  const activeStatusList = useMemo(() => {
    if (moveTypeFilter === "ftl") return FTL_STATUSES;
    if (moveTypeFilter === "dray") return STATUSES;
    return ALL_STATUSES_COMBINED;
  }, [moveTypeFilter]);

  // FTL tracking preview state
  const [trackingData, setTrackingData] = useState(null);
  const [trackingScreenshot, setTrackingScreenshot] = useState(null);
  const [trackingLoading, setTrackingLoading] = useState(false);

  // Document hub state
  const [loadDocs, setLoadDocs] = useState([]);
  const [docFilter, setDocFilter] = useState("all");
  const [docUploading, setDocUploading] = useState(false);
  const [docType, setDocType] = useState("other");
  const [docUploadMsg, setDocUploadMsg] = useState(null);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [reclassDocId, setReclassDocId] = useState(null);
  const [loadEmails, setLoadEmails] = useState([]);

  // Driver contact state
  const [driverInfo, setDriverInfo] = useState({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
  const [driverEditing, setDriverEditing] = useState(null); // which field is being edited
  const [driverEditVal, setDriverEditVal] = useState("");
  const [driverSaving, setDriverSaving] = useState(false);

  // Fetch tracking + documents + driver info when slide-over opens
  // NOTE: Data fetching now handled by LoadSlideOver component
  useEffect(() => {
    return;
    if (!selectedShipment) {
      setTrackingData(null);
      setTrackingScreenshot(null);
      setLoadDocs([]);
      setDocUploadMsg(null);
      setDriverInfo({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
      setDriverEditing(null);
      setLoadEmails([]);
      return;
    }
    // Fetch documents
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`)
      .then(r => r.ok ? r.json() : { documents: [] })
      .then(data => setLoadDocs(data.documents || []))
      .catch(() => setLoadDocs([]));
    // Fetch email history
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/emails`)
      .then(r => r.ok ? r.json() : { emails: [] })
      .then(data => setLoadEmails(data.emails || []))
      .catch(() => setLoadEmails([]));
    // Fetch timestamped notes
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/notes`)
      .then(r => r.ok ? r.json() : { notes: [] })
      .then(data => setLoadNotes(data.notes || []))
      .catch(() => setLoadNotes([]));
    // Fetch driver contact info
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/driver`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setDriverInfo(data); })
      .catch(() => {});
    // Fetch tracking for FTL loads
    if (selectedShipment.moveType === "FTL" || selectedShipment.macropointUrl) {
      setTrackingLoading(true);
      Promise.allSettled([
        apiFetch(`${API_BASE}/api/macropoint/${selectedShipment.efj}`).then(r => r.ok ? r.json() : null),
        apiFetch(`${API_BASE}/api/macropoint/${selectedShipment.efj}/screenshot`).then(r => r.ok ? r.blob() : null),
      ]).then(([mpRes, ssRes]) => {
        if (mpRes.status === "fulfilled" && mpRes.value) setTrackingData(mpRes.value);
        if (ssRes.status === "fulfilled" && ssRes.value) setTrackingScreenshot(URL.createObjectURL(ssRes.value));
        setTrackingLoading(false);
      });
    }
  }, [selectedShipment?.efj]);

  // ESC to close preview modal (capture phase so it fires before slide-over ESC handler)
  useEffect(() => {
    if (!previewDoc) return;
    const handleKey = (e) => {
      if (e.key === "Escape") { setPreviewDoc(null); e.stopPropagation(); }
    };
    document.addEventListener("keydown", handleKey, true);
    return () => document.removeEventListener("keydown", handleKey, true);
  }, [previewDoc]);

  const saveDriverField = async (field, value) => {
    if (!selectedShipment?.efj) return;
    setDriverSaving(true);
    try {
      await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/driver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      setDriverInfo(prev => ({ ...prev, [field]: value }));
    } catch {}
    setDriverSaving(false);
    setDriverEditing(null);
  };

  const handleDocUpload = async (file) => {
    if (!selectedShipment?.efj || !file) return;
    setDocUploading(true); setDocUploadMsg(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("doc_type", docType);
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`, { method: "POST", body: fd });
      if (r.ok) {
        setDocUploadMsg("Uploaded");
        // Refresh doc list
        const listRes = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`);
        if (listRes.ok) { const data = await listRes.json(); setLoadDocs(data.documents || []); }
        addSheetLog(`Doc uploaded | ${selectedShipment.loadNumber}`);
        onDocChange?.();
      } else { setDocUploadMsg(`Upload failed (${r.status})`); }
    } catch { setDocUploadMsg("Upload error"); }
    setDocUploading(false);
  };

  const handleDocDelete = async (docId) => {
    if (!selectedShipment?.efj) return;
    try {
      await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${docId}`, { method: "DELETE" });
      setLoadDocs(prev => prev.filter(d => d.id !== docId));
      onDocChange?.();
    } catch {}
  };

  const handleDocReclassify = async (docId, newType) => {
    if (!selectedShipment?.efj) return;
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${docId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_type: newType }),
      });
      if (r.ok) {
        setLoadDocs(prev => prev.map(d => d.id === docId ? { ...d, doc_type: newType } : d));
        setReclassDocId(null);
        onDocChange?.();
      }
    } catch {}
  };

  const getFileExt = (name) => name?.split(".").pop().toLowerCase() || "";
  const isImage = (name) => ["png", "jpg", "jpeg", "tiff"].includes(getFileExt(name));
  const isPdf = (name) => getFileExt(name) === "pdf";

  const hasFTL = filtered.some(s => s.moveType === "FTL");
  const DISPATCH_COLS = [
    { key: "account", label: "Account", w: 80, sortFn: (a, b) => a.account.localeCompare(b.account) },
    { key: "status", label: "Status", w: 100, sortFn: (a, b) => a.status.localeCompare(b.status) },
    { key: "efj", label: "EFJ #", w: 90, sortFn: (a, b) => a.loadNumber.localeCompare(b.loadNumber) },
    { key: "container", label: "Container/Load #", w: 120, sortFn: (a, b) => a.container.localeCompare(b.container) },
    ...(hasFTL ? [{ key: "mpStatus", label: "MP Status", w: 110, sortFn: (a, b) => {
      const efjA = (a.efj || "").replace(/^EFJ\s*/i, ""); const efjB = (b.efj || "").replace(/^EFJ\s*/i, "");
      const aS = (a.mpDisplayStatus || trackingSummary?.[efjA]?.mpDisplayStatus || "").toLowerCase();
      const bS = (b.mpDisplayStatus || trackingSummary?.[efjB]?.mpDisplayStatus || "").toLowerCase();
      const pri = s => s === "behind schedule" ? 5 : s === "no signal" ? 4 : s === "awaiting update" ? 3 : s === "at delivery" ? 2 : s === "at pickup" ? 1 : 0;
      return pri(bS) - pri(aS);
    }}] : []),
    { key: "pickup", label: "Pickup", w: 110, sortFn: (a, b) => (a.pickupDate || "").localeCompare(b.pickupDate || "") },
    { key: "origin", label: "Origin", w: 120, sortFn: (a, b) => (a.origin || "").localeCompare(b.origin || "") },
    { key: "destination", label: "Destination", w: 120, sortFn: (a, b) => (a.destination || "").localeCompare(b.destination || "") },
    { key: "delivery", label: "Delivery", w: 110, sortFn: (a, b) => (a.deliveryDate || "").localeCompare(b.deliveryDate || "") },
    { key: "truckType", label: "Truck", w: 75, sortFn: (a, b) => (a.truckType || "").localeCompare(b.truckType || "") },
    { key: "trailer", label: "Trailer #", w: 70, sortFn: (a, b) => (a.trailerNumber || "").localeCompare(b.trailerNumber || "") },
    { key: "driverPhone", label: "Driver Phone", w: 100, sortFn: (a, b) => (a.driverPhone || "").localeCompare(b.driverPhone || "") },
    { key: "carrierEmail", label: "Carrier Email", w: 130, sortFn: (a, b) => (a.carrierEmail || "").localeCompare(b.carrierEmail || "") },
    { key: "customerRate", label: "Rate", w: 70, sortFn: (a, b) => (a.customerRate || "").localeCompare(b.customerRate || "") },
    { key: "notes", label: "Notes", w: 140, sortFn: (a, b) => (a.notes || "").localeCompare(b.notes || "") },
  ];

  // Column filter: compute unique options + apply filters
  const FILTERABLE_KEYS = useMemo(() => ["account", "status", "mpStatus", "origin", "destination", "pickup", "delivery"], []);
  const colFilterOpts = useMemo(() => buildColFilterOptions(filtered, trackingSummary), [filtered, trackingSummary]);
  const columnFiltered = useMemo(() => applyColFilters(filtered, columnFilters, trackingSummary), [filtered, columnFilters, trackingSummary]);

  const sorted = useMemo(() => {
    if (!sortCol) return columnFiltered;
    const col = DISPATCH_COLS.find(c => c.key === sortCol);
    if (!col) return columnFiltered;
    return [...columnFiltered].sort((a, b) => {
      const result = col.sortFn(a, b);
      return sortDir === "asc" ? result : -result;
    });
  }, [columnFiltered, sortCol, sortDir]);

  const hasActiveFilters = activeStatus !== "all" || activeAccount !== "All Accounts" || activeRep !== "All Reps" || searchQuery !== "" || !!dateFilter || moveTypeFilter !== "all" || !!dateRangeField || Object.keys(columnFilters).length > 0;

  const exportCSV = () => {
    const headers = ["Account", "Status", "EFJ #", "Container/Load #", "MP Status", "Pickup Date/Time", "Origin", "Destination", "Delivery Date/Time", "Truck Type", "Trailer #", "Driver Phone", "Carrier Email", "Customer Rate", "Notes", "Move Type", "Carrier"];
    const rows = sorted.map(s => {
      const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
      const t = trackingSummary?.[efjBare];
      return [s.account,
        [...FTL_STATUSES, ...STATUSES].find(st => st.key === s.status)?.label || s.status,
        s.loadNumber, s.container, s.mpDisplayStatus || t?.mpDisplayStatus || s.mpStatus || t?.mpStatus || "",
        s.pickupDate || "", s.origin, s.destination, s.deliveryDate || "",
        s.truckType || "", s.trailerNumber || "", s.driverPhone || "", s.carrierEmail || "",
        s.customerRate || "", (s.notes || "").replace(/"/g, '""'),
        s.moveType, s.carrier];
    });
    const csv = [headers.join(","), ...rows.map(r => r.map(v => `"${v}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dispatch-export-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePodUpload = async (file) => {
    if (!selectedShipment?.efj || !file) return;
    setPodUploading(true); setPodUploadMsg(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/upload`, { method: "POST", body: fd });
      if (r.ok) { setPodUploadMsg("Upload successful"); addSheetLog(`POD uploaded | ${selectedShipment.loadNumber}`); }
      else { setPodUploadMsg(`Upload failed (${r.status})`); }
    } catch (e) { setPodUploadMsg("Upload error"); }
    setPodUploading(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 60px)", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 0 10px", flexShrink: 0 }}>
        <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Dispatch Command</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setZebraStripe(z => !z)} style={{ border: `1px solid ${zebraStripe ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: zebraStripe ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: zebraStripe ? "#00D4AA" : "#8B95A8", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{zebraStripe ? "☰ Striped" : "☰ Flat"}</button>
          <button onClick={exportCSV} style={{ border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", fontSize: 11, fontWeight: 600, cursor: "pointer", color: "#8B95A8", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>↓ CSV</button>
          <button onClick={onAddLoad} className="btn-primary" style={{ border: "none", borderRadius: 8, padding: "8px 18px", fontSize: 12, fontWeight: 700, cursor: "pointer", color: "#fff" }}>+ New Load</button>
        </div>
      </div>

      {/* Metrics Strip */}
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexShrink: 0, animation: loaded ? "slide-up 0.5s ease 0.1s both" : "none" }}>
        {[
          { label: "Active Loads", value: activeLoads, color: "#60a5fa", icon: "◈" },
          { label: "In Transit", value: inTransit, color: "#34d399", icon: "▸" },
          { label: "Delivered", value: deliveredCount, color: "#fbbf24", icon: "✦" },
          { label: "Exceptions", value: issueCount, color: "#f87171", icon: "⚠" },
        ].map((m, i) => (
          <div key={i} className="glass metric-card" style={{ flex: 1, padding: "12px 14px", borderRadius: 12, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 34, height: 34, borderRadius: 8, background: `${m.color}15`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: m.color }}>{m.icon}</div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>{m.value}</div>
              <div style={{ fontSize: 9, color: "#5A6478", fontWeight: 500, letterSpacing: "1px", textTransform: "uppercase" }}>{m.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Move Type Toggle + Status Cards */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 2, background: "rgba(0,0,0,0.2)", borderRadius: 8, padding: 3, flexShrink: 0 }}>
          {[{ key: "all", label: "All" }, { key: "dray", label: "Dray" }, { key: "ftl", label: "FTL" }].map(t => (
            <button key={t.key} onClick={() => { setMoveTypeFilter(t.key); setActiveStatus("all"); }}
              style={{ padding: "5px 12px", borderRadius: 6, border: "none", fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                background: moveTypeFilter === t.key ? "rgba(0,212,170,0.15)" : "transparent",
                color: moveTypeFilter === t.key ? "#00D4AA" : "#8B95A8", letterSpacing: "0.5px" }}>
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, overflowX: "auto", flex: 1, paddingBottom: 2 }}>
          {statusCounts.map((s) => {
            const isActive = activeStatus === s.key;
            const allColors = { ...STATUS_COLORS, ...FTL_STATUS_COLORS };
            const sc = allColors[s.key] || { main: "#64748b" };
            return (
              <button key={s.key} className={`status-card ${isActive ? "active" : ""}`}
                onClick={() => setActiveStatus(s.key)}
                style={{ flex: "0 0 auto", minWidth: 80, padding: "8px 12px",
                  background: isActive ? `linear-gradient(135deg, ${sc.main}12, ${sc.main}08)` : "rgba(255,255,255,0.02)",
                  border: `1px solid ${isActive ? sc.main + "44" : "rgba(255,255,255,0.04)"}`,
                  borderRadius: 10, cursor: "pointer", textAlign: "left", position: "relative", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
                  <span style={{ fontSize: 11, opacity: 0.7 }}>{s.icon}</span>
                  <span style={{ fontSize: 20, fontWeight: 900, color: isActive ? sc.main : "#64748b" }}>{s.count}</span>
                </div>
                <div style={{ fontSize: 9, fontWeight: 600, color: isActive ? "#F0F2F5" : "#8B95A8", whiteSpace: "nowrap" }}>{s.label}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Filter Bar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap", flexShrink: 0 }}>
        <div style={{ position: "relative", flex: 1, maxWidth: 300, minWidth: 180 }}>
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search EFJ#, containers, carriers..."
            style={{ width: "100%", padding: "9px 14px 9px 34px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: "#8B95A8" }}>⌕</span>
        </div>
        <select value={activeAccount} onChange={e => setActiveAccount(e.target.value)}
          style={{ padding: "9px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {ACCOUNTS.map(a => <option key={a} value={a} style={{ background: "#0D1119" }}>{a}</option>)}
        </select>
        <select value={activeRep} onChange={e => setActiveRep(e.target.value)}
          style={{ padding: "9px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {["All Reps", ...ALL_REP_NAMES].map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
        </select>
        <select value={activeStatus} onChange={e => setActiveStatus(e.target.value)}
          style={{ padding: "9px 12px", background: activeStatus !== "all" ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.03)", border: `1px solid ${activeStatus !== "all" ? "rgba(59,130,246,0.25)" : "rgba(255,255,255,0.06)"}`, borderRadius: 10, color: activeStatus !== "all" ? "#60A5FA" : "#F0F2F5", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {activeStatusList.map(s => <option key={s.key} value={s.key} style={{ background: "#0D1119" }}>{s.key === "all" ? "All Statuses" : s.label}</option>)}
        </select>
        {/* Date Range Popover */}
        <div style={{ position: "relative" }}>
          <button onClick={() => setShowDatePopover(!showDatePopover)}
            style={{ padding: "9px 12px", background: dateRangeField ? "rgba(59,130,246,0.1)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${dateRangeField ? "rgba(59,130,246,0.3)" : "rgba(255,255,255,0.06)"}`,
              borderRadius: 10, color: dateRangeField ? "#60A5FA" : "#F0F2F5", fontSize: 12, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            📅 Dates
          </button>
          {showDatePopover && (
            <div style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, zIndex: 30, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, padding: 14, width: 280, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Filter by Date</div>
              {/* Field selector */}
              <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
                {[{ k: "pickup", l: "Pickup" }, { k: "delivery", l: "Delivery" }].map(f => (
                  <button key={f.k} onClick={() => setDateRangeField(dateRangeField === f.k ? null : f.k)}
                    style={{ flex: 1, padding: "5px 10px", borderRadius: 6, border: "none", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                      background: dateRangeField === f.k ? "rgba(59,130,246,0.15)" : "rgba(255,255,255,0.05)",
                      color: dateRangeField === f.k ? "#60A5FA" : "#8B95A8" }}>
                    {f.l} Date
                  </button>
                ))}
              </div>
              {/* Date inputs */}
              <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 9, color: "#5A6478", marginBottom: 3 }}>From</div>
                  <input type="date" value={dateRangeStart} onChange={e => { setDateRangeStart(e.target.value); if (!dateRangeField) setDateRangeField("pickup"); }}
                    style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "inherit" }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 9, color: "#5A6478", marginBottom: 3 }}>To</div>
                  <input type="date" value={dateRangeEnd} onChange={e => setDateRangeEnd(e.target.value)}
                    style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#F0F2F5", fontSize: 11, outline: "none", fontFamily: "inherit" }} />
                </div>
              </div>
              {/* Quick presets */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
                {[
                  { label: "Today", fn: () => { const d = new Date().toISOString().slice(0,10); setDateRangeStart(d); setDateRangeEnd(d); }},
                  { label: "Tomorrow", fn: () => { const d = new Date(Date.now() + 86400000).toISOString().slice(0,10); setDateRangeStart(d); setDateRangeEnd(d); }},
                  { label: "This Week", fn: () => {
                    const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? -6 : 1);
                    const mon = new Date(now); mon.setDate(diff); const fri = new Date(mon); fri.setDate(fri.getDate() + 4);
                    setDateRangeStart(mon.toISOString().slice(0,10)); setDateRangeEnd(fri.toISOString().slice(0,10));
                  }},
                  { label: "Next Week", fn: () => {
                    const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? 1 : 8);
                    const mon = new Date(now); mon.setDate(diff); const fri = new Date(mon); fri.setDate(fri.getDate() + 4);
                    setDateRangeStart(mon.toISOString().slice(0,10)); setDateRangeEnd(fri.toISOString().slice(0,10));
                  }},
                  { label: "Past Due", fn: () => {
                    setDateRangeStart("2020-01-01"); setDateRangeEnd(new Date(Date.now() - 86400000).toISOString().slice(0,10));
                  }},
                ].map(p => (
                  <button key={p.label} onClick={() => { p.fn(); if (!dateRangeField) setDateRangeField("pickup"); setDateFilter(null); setShowDatePopover(false); }}
                    style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.03)", color: "#8B95A8", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                    {p.label}
                  </button>
                ))}
              </div>
              {/* Actions */}
              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                <button onClick={() => { setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); setShowDatePopover(false); }}
                  style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#8B95A8", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                  Clear
                </button>
                <button onClick={() => setShowDatePopover(false)}
                  style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: "rgba(0,212,170,0.15)", color: "#00D4AA", fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#8B95A8" }}>
          <span><span style={{ color: "#8B95A8", fontWeight: 700 }}>{filtered.length}</span> of {shipments.length}</span>
          {hasActiveFilters && (
            <button onClick={() => { setActiveStatus("all"); setActiveAccount("All Accounts"); setActiveRep("All Reps"); setSearchQuery(""); if (setDateFilter) setDateFilter(null); setMoveTypeFilter("all"); setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); setColumnFilters({}); setOpenFilterCol(null); }}
              style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)", borderRadius: 6, padding: "4px 10px", fontSize: 10, fontWeight: 600, color: "#f87171", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              ✕ Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Active filter chips */}
      {(dateFilter || dateRangeField) && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {dateFilter && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60A5FA" }}>
              {{ pickup_today: "Pickups Today", pickup_tomorrow: "Pickups Tomorrow", delivery_today: "Deliveries Today", delivery_tomorrow: "Deliveries Tomorrow" }[dateFilter] || dateFilter}
              <span onClick={() => setDateFilter(null)} style={{ cursor: "pointer", marginLeft: 4, color: "#60A5FA", fontSize: 12, lineHeight: 1 }}>✕</span>
            </span>
          )}
          {dateRangeField && dateRangeStart && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: "rgba(6,182,212,0.1)", border: "1px solid rgba(6,182,212,0.25)", color: "#22D3EE" }}>
              {dateRangeField === "pickup" ? "PU" : "DEL"}: {dateRangeStart}{dateRangeEnd && dateRangeEnd !== dateRangeStart ? ` — ${dateRangeEnd}` : ""}
              <span onClick={() => { setDateRangeField(null); setDateRangeStart(""); setDateRangeEnd(""); }} style={{ cursor: "pointer", marginLeft: 4, color: "#22D3EE", fontSize: 12, lineHeight: 1 }}>✕</span>
            </span>
          )}
        </div>
      )}

      {/* Full-width Table */}
      <div className="dispatch-table-wrap" style={{ flex: 1, minHeight: 0, overflowX: "scroll", overflowY: "auto", borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.01)" }}>
        <table style={{ width: "100%", minWidth: 1600, borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr>
              {DISPATCH_COLS.map((col, ci) => {
                const isFilterable = FILTERABLE_KEYS.includes(col.key);
                const hasColFilter = !!columnFilters[col.key];
                const isOpen = openFilterCol === col.key;
                const opts = colFilterOpts[col.key] || [];
                return (
                  <th key={col.key}
                    style={{ padding: "7px 8px", textAlign: "left", fontSize: 10, fontWeight: 700,
                      color: hasColFilter ? "#00D4AA" : sortCol === col.key ? "#00D4AA" : "#8B95A8",
                      letterSpacing: "0.8px", textTransform: "uppercase",
                      borderBottom: hasColFilter ? "2px solid rgba(0,212,170,0.4)" : "1px solid rgba(255,255,255,0.08)",
                      borderRight: ci < DISPATCH_COLS.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
                      background: hasColFilter ? "rgba(0,212,170,0.04)" : "#0D1119",
                      position: "sticky", top: 0, zIndex: isOpen ? 50 : 5, cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", maxWidth: col.w }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                      <span style={{ flex: 1 }} onClick={() => {
                        if (sortCol === col.key) setSortDir(d => d === "asc" ? "desc" : "asc");
                        else { setSortCol(col.key); setSortDir("asc"); }
                      }}>
                        {col.label} {sortCol === col.key ? (sortDir === "asc" ? "▲" : "▼") : ""}
                      </span>
                      {isFilterable && (
                        <span className="col-filter-dd"
                          onClick={(e) => { e.stopPropagation(); setOpenFilterCol(isOpen ? null : col.key); }}
                          style={{ fontSize: 8, color: hasColFilter ? "#00D4AA" : "#5A6478", cursor: "pointer",
                            padding: "2px 3px", borderRadius: 3, background: hasColFilter ? "rgba(0,212,170,0.12)" : "transparent", lineHeight: 1 }}>
                          {hasColFilter ? "✦" : "▾"}
                        </span>
                      )}
                    </div>
                    {isOpen && (
                      <div className="col-filter-dd" onClick={e => e.stopPropagation()}
                        style={{ position: "absolute", top: "100%", left: 0, marginTop: 2, zIndex: 60, background: "#1A2236",
                          border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, minWidth: 150,
                          maxHeight: 300, overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
                        <div onClick={() => { setColumnFilters(f => { const n = {...f}; delete n[col.key]; return n; }); setOpenFilterCol(null); }}
                          style={{ padding: "6px 10px", fontSize: 11, color: !hasColFilter ? "#00D4AA" : "#8B95A8",
                            cursor: "pointer", borderRadius: 4, background: !hasColFilter ? "rgba(0,212,170,0.06)" : "transparent", fontWeight: 600 }}>
                          All
                        </div>
                        {opts.map(opt => {
                          const val = typeof opt === "object" ? opt.value : opt;
                          const label = typeof opt === "object" ? opt.label : opt;
                          const isActive = columnFilters[col.key] === val;
                          return (
                            <div key={val} onClick={() => { setColumnFilters(f => ({ ...f, [col.key]: val })); setOpenFilterCol(null); }}
                              style={{ padding: "6px 10px", fontSize: 11, color: isActive ? "#00D4AA" : "#F0F2F5",
                                cursor: "pointer", borderRadius: 4, background: isActive ? "rgba(0,212,170,0.08)" : "transparent",
                                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                              {label}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, rowIdx) => {
              const sc = resolveStatusColor(s);
              const isSelected = selectedShipment?.id === s.id;
              const isFTL = s.moveType === "FTL";
              const efjBare = (s.efj || "").replace(/^EFJ\s*/i, "");
              const tracking = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
              const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
              const pu = splitDateTime(s.pickupDate);
              const del = splitDateTime(s.deliveryDate);
              const isInlineEditing = inlineEditId === s.id;
              const inlineInputStyle = { background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 4, color: "#F0F2F5", padding: "2px 5px", fontSize: 11, width: 90, outline: "none", fontFamily: "'JetBrains Mono', monospace" };
              const cellStyle = (ci) => ({ padding: "5px 8px", borderBottom: "1px solid rgba(255,255,255,0.06)", borderRight: ci < DISPATCH_COLS.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none" });
              const zebraBg = zebraStripe && rowIdx % 2 === 1 ? "rgba(255,255,255,0.025)" : "transparent";
              const rowBg = isSelected ? `${sc.main}10` : zebraBg;
              let colIdx = 0;
              return (
                <tr key={s.id} className="row-hover" onClick={() => { if (!isInlineEditing) handleLoadClick(s); }}
                  style={{ cursor: "pointer", background: rowBg }}>
                  {/* Account */}
                  <td style={{ ...cellStyle(colIdx++), color: "#F0F2F5", fontSize: 11, fontWeight: 600 }}>{s.account}</td>
                  {/* Status (inline-editable) */}
                  <td style={{ ...cellStyle(colIdx++), position: "relative" }}
                    onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("status"); }}>
                    {isInlineEditing && inlineEditField === "status" ? (
                      <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 20, background: "#1A2236", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: 4, boxShadow: "0 8px 32px rgba(0,0,0,0.5)", maxHeight: 220, overflowY: "auto", minWidth: 120 }}>
                        {getStatusesForShipment(s).filter(st => st.key !== "all").map(st => {
                          const stc = getStatusColors(s)[st.key] || { main: "#94a3b8" };
                          return (
                            <button key={st.key} onClick={(e) => { e.stopPropagation(); handleStatusUpdate(s.id, st.key); setInlineEditId(null); }}
                              style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", padding: "4px 7px", borderRadius: 4, border: "none",
                                background: s.status === st.key ? `${stc.main}18` : "transparent",
                                color: s.status === st.key ? stc.main : "#8B95A8", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                              <span style={{ width: 4, height: 4, borderRadius: "50%", background: stc.main, flexShrink: 0 }} />
                              {st.label}
                            </button>
                          );
                        })}
                        <button onClick={(e) => { e.stopPropagation(); setInlineEditId(null); }}
                          style={{ display: "block", width: "100%", padding: "3px 7px", marginTop: 2, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.03)", color: "#5A6478", fontSize: 9, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                      </div>
                    ) : null}
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 12, fontSize: 9, fontWeight: 700,
                      color: sc.main, background: `${sc.main}0D`, border: `1px solid ${sc.main}18`, textTransform: "uppercase", cursor: "pointer", whiteSpace: "nowrap" }}>
                      <span style={{ width: 4, height: 4, borderRadius: "50%", background: sc.main }} />
                      {resolveStatusLabel(s)}
                    </span>
                  </td>
                  {/* EFJ # */}
                  <td style={cellStyle(colIdx++)}>
                    <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{s.loadNumber}</span>
                      {!s.synced && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fbbf24", display: "inline-block", animation: "pulse-glow 1s ease infinite" }} />}
                      <DocIndicators docs={docs} />
                      {s.email_count > 0 && (
                        <span title={`${s.email_count} email${s.email_count > 1 ? "s" : ""}${s.email_max_priority >= 4 ? " (urgent)" : ""}`}
                          style={{ fontSize: 8, padding: "0 4px", borderRadius: 8, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
                            background: s.email_max_priority >= 4 ? "rgba(249,115,22,0.15)" : "rgba(139,149,168,0.10)",
                            color: s.email_max_priority >= 4 ? "#F97316" : "#5A6478",
                            border: s.email_max_priority >= 4 ? "1px solid rgba(249,115,22,0.20)" : "none" }}>
                          &#9993;{s.email_count}
                        </span>
                      )}
                    </div>
                  </td>
                  {/* Container/Load # */}
                  <td style={{ ...cellStyle(colIdx++), fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#F0F2F5" }}>{s.container}</td>
                  {/* MP Status (FTL only) */}
                  {hasFTL && <td style={cellStyle(colIdx++)}>
                    {(isFTL || s.mpStatus) ? <TrackingBadge tracking={tracking} mpStatus={s.mpStatus || tracking?.mpStatus} mpDisplayStatus={s.mpDisplayStatus || tracking?.mpDisplayStatus} mpDisplayDetail={s.mpDisplayDetail || tracking?.mpDisplayDetail} mpLastUpdated={s.mpLastUpdated} /> : <span style={{ color: "#5A6478", fontSize: 9, fontStyle: "italic" }}>No MP</span>}
                  </td>}
                  {/* Pickup (inline-editable, DD-MM) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>
                    {isInlineEditing && inlineEditField === "pickup" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                          onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (pu.time ? " " + pu.time : ""); handleFieldUpdate(s, "pickup", v); } setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                      </div>
                    ) : isInlineEditing && inlineEditField === "pickupTime" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "pickup", pu.date || ""); setInlineEditId(null); return; } const v = (pu.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "pickup", v); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 70 }} />
                      </div>
                    ) : (
                      <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                        <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickup"); setInlineEditValue(""); }}>{formatDDMM(s.pickupDate) || "—"}</span>
                        {pu.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("pickupTime"); setInlineEditValue(pu.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{pu.time}</span> : null}
                      </span>
                    )}
                  </td>
                  {/* Origin */}
                  <td style={{ ...cellStyle(colIdx++), fontSize: 10, color: "#F0F2F5", fontWeight: 500, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.origin}>{s.origin || "—"}</td>
                  {/* Destination */}
                  <td style={{ ...cellStyle(colIdx++), fontSize: 10, color: "#F0F2F5", fontWeight: 500, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.destination}>{s.destination || "—"}</td>
                  {/* Delivery (inline-editable, MM/DD + time) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>
                    {isInlineEditing && inlineEditField === "delivery" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input autoFocus placeholder="MMDD" maxLength={5} value={inlineEditValue}
                          onChange={e => { let v = e.target.value.replace(/[^\d]/g, ""); if (v.length > 2) v = v.slice(0,2) + "/" + v.slice(2); setInlineEditValue(v); }}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", ""); setInlineEditId(null); return; } const parsed = parseDDMM(inlineEditValue); if (parsed) { const v = parsed + (del.time ? " " + del.time : ""); handleFieldUpdate(s, "delivery", v); } setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 52, textAlign: "center", letterSpacing: 1 }} />
                      </div>
                    ) : isInlineEditing && inlineEditField === "deliveryTime" ? (
                      <div onClick={e => e.stopPropagation()}>
                        <input type="time" autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                          onBlur={() => { if (!inlineEditValue.trim()) { handleFieldUpdate(s, "delivery", del.date || ""); setInlineEditId(null); return; } const v = (del.date || "") + " " + inlineEditValue; handleFieldUpdate(s, "delivery", v); setInlineEditId(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                          style={{ ...inlineInputStyle, width: 70 }} />
                      </div>
                    ) : (
                      <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>
                        <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("delivery"); setInlineEditValue(""); }}>{formatDDMM(s.deliveryDate) || "—"}</span>
                        {del.time ? <span onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("deliveryTime"); setInlineEditValue(del.time); }} style={{ color: "#8B95A8", marginLeft: 4 }}>{del.time}</span> : null}
                      </span>
                    )}
                  </td>
                  {/* Truck Type (inline-editable dropdown) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("truckType"); setInlineEditValue(s.truckType || ""); }}>
                    {isInlineEditing && inlineEditField === "truckType" ? (
                      <select autoFocus value={inlineEditValue}
                        onChange={e => { const v = e.target.value; setInlineEditValue(v); handleMetadataUpdate(s, "truckType", v); setInlineEditId(null); }}
                        onBlur={() => setInlineEditId(null)}
                        onKeyDown={e => { if (e.key === "Escape") setInlineEditId(null); }}
                        onClick={e => e.stopPropagation()}
                        style={{ ...inlineInputStyle, width: 80, cursor: "pointer" }}>
                        {TRUCK_TYPES.map(t => <option key={t} value={t}>{t || "—"}</option>)}
                      </select>
                    ) : (
                      <span style={{ fontSize: 10, color: s.truckType ? "#F0F2F5" : "#3D4557", cursor: "pointer" }}>{s.truckType || "—"}</span>
                    )}
                  </td>
                  {/* Trailer # (inline-editable) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("trailer"); setInlineEditValue(s.trailerNumber || tracking?.trailer || ""); }}>
                    {isInlineEditing && inlineEditField === "trailer" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "trailer", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                        style={{ ...inlineInputStyle, width: 70 }} onClick={e => e.stopPropagation()} placeholder="Trailer" />
                    ) : (
                      <span style={{ fontSize: 10, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", cursor: "text" }}>{s.trailerNumber || tracking?.trailer || "—"}</span>
                    )}
                  </td>
                  {/* Driver Phone (inline-editable) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("driverPhone"); setInlineEditValue(s.driverPhone || tracking?.driverPhone || ""); }}>
                    {isInlineEditing && inlineEditField === "driverPhone" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "driverPhone", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                        style={{ ...inlineInputStyle, width: 100 }} onClick={e => e.stopPropagation()} placeholder="Phone" />
                    ) : (
                      <span style={{ fontSize: 10, color: (s.driverPhone || tracking?.driverPhone) ? "#F0F2F5" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", whiteSpace: "nowrap" }}>{s.driverPhone || tracking?.driverPhone || "—"}</span>
                    )}
                  </td>
                  {/* Carrier Email (inline-editable) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("carrierEmail"); setInlineEditValue(s.carrierEmail || ""); }}>
                    {isInlineEditing && inlineEditField === "carrierEmail" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleDriverFieldUpdate(s, "carrierEmail", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                        style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="email@carrier.com" />
                    ) : (
                      <span style={{ fontSize: 10, color: s.carrierEmail ? "#8B95A8" : "#3D4557", maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.carrierEmail || ""}>{s.carrierEmail || "—"}</span>
                    )}
                  </td>
                  {/* Customer Rate (inline-editable) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("customerRate"); setInlineEditValue(s.customerRate || ""); }}>
                    {isInlineEditing && inlineEditField === "customerRate" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleMetadataUpdate(s, "customerRate", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                        style={{ ...inlineInputStyle, width: 65 }} onClick={e => e.stopPropagation()} placeholder="$0.00" />
                    ) : (
                      <span style={{ fontSize: 10, color: s.customerRate ? "#22C55E" : "#3D4557", fontFamily: "'JetBrains Mono', monospace", cursor: "text", fontWeight: s.customerRate ? 600 : 400 }}>{s.customerRate || "—"}</span>
                    )}
                  </td>
                  {/* Notes (inline-editable) */}
                  <td style={cellStyle(colIdx++)} onClick={(e) => { e.stopPropagation(); setInlineEditId(s.id); setInlineEditField("notes"); setInlineEditValue(s.notes || ""); }}>
                    {isInlineEditing && inlineEditField === "notes" ? (
                      <input autoFocus value={inlineEditValue} onChange={e => setInlineEditValue(e.target.value)}
                        onBlur={() => { handleMetadataUpdate(s, "notes", inlineEditValue); setInlineEditId(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setInlineEditId(null); }}
                        style={{ ...inlineInputStyle, width: 140 }} onClick={e => e.stopPropagation()} placeholder="Add note..." />
                    ) : (
                      <span style={{ fontSize: 10, color: s.notes ? "#F0F2F5" : "#3D4557", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", cursor: "text" }} title={s.notes || ""}>{s.notes || "—"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <div style={{ textAlign: "center", padding: 40, color: "#3D4557" }}>
            <div style={{ fontSize: 30, marginBottom: 8, opacity: 0.3 }}>◎</div>
            <div style={{ fontSize: 12, fontWeight: 600 }}>No loads match filters</div>
          </div>
        )}
      </div>

      {/* Slide-over Detail Panel — now rendered by LoadSlideOver at top level */}
      {false && selectedShipment && (
        <>
          <div onClick={() => setSelectedShipment(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 50, animation: "fade-in 0.2s ease" }} />
          <div className="glass-strong" style={{ position: "fixed", top: 0, right: 0, width: 380, height: "100vh", zIndex: 60, display: "flex", flexDirection: "column", overflow: "hidden", animation: "slide-right 0.3s ease", borderLeft: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ flex: 1, overflow: "auto" }}>
              {/* Header */}
              <div style={{ padding: "18px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 800, color: "#F0F2F5" }}>{selectedShipment.loadNumber}</div>
                  <div style={{ fontSize: 10, color: "#8B95A8", marginTop: 2 }}>{selectedShipment.container} | {selectedShipment.moveType}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
                    <span style={{ width: 5, height: 5, borderRadius: "50%", background: selectedShipment.synced ? "#34d399" : "#fbbf24" }} />
                    <span style={{ fontSize: 9, color: selectedShipment.synced ? "#34d399" : "#fbbf24", fontWeight: 600 }}>{selectedShipment.synced ? "Synced" : "Syncing..."}</span>
                  </div>
                </div>
                <button onClick={() => setSelectedShipment(null)} style={{ background: "rgba(255,255,255,0.05)", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 14, width: 28, height: 28, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
              </div>

              {/* FTL Tracking Preview Card */}
              {(selectedShipment.macropointUrl || selectedShipment.moveType === "FTL") && (
                <div style={{ padding: "12px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  {trackingLoading ? (
                    <div style={{ padding: "16px 0", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                      <div style={{ width: 14, height: 14, border: "2px solid #1e293b", borderTop: "2px solid #14b8a6", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
                      <span style={{ fontSize: 10, color: "#8B95A8" }}>Loading tracking...</span>
                    </div>
                  ) : (
                    <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", overflow: "hidden" }}>
                      {/* Status + ETA header */}
                      <div style={{ padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 11 }}>📍</span>
                          <span style={{ fontSize: 10, fontWeight: 700, color: trackingData?.trackingStatus?.toLowerCase().includes("deliver") ? "#34d399"
                            : trackingData?.trackingStatus?.toLowerCase().includes("transit") ? "#60a5fa"
                            : trackingData?.trackingStatus?.toLowerCase().includes("late") ? "#f87171" : "#fbbf24",
                            textTransform: "uppercase", letterSpacing: "0.5px" }}>
                            {trackingData?.trackingStatus || "Pending"}
                          </span>
                        </div>
                        {(trackingData?.eta || selectedShipment.eta) && (
                          <span style={{ fontSize: 10, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>
                            ETA: {trackingData?.eta || selectedShipment.eta}
                          </span>
                        )}
                      </div>
                      {/* Screenshot or progress bar */}
                      {trackingScreenshot ? (
                        <div style={{ padding: "0 14px 10px" }}>
                          <img src={trackingScreenshot} alt="Tracking map"
                            style={{ width: "100%", height: "auto", maxHeight: 200, objectFit: "contain", borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "#0a0e17" }} />
                        </div>
                      ) : trackingData?.progress ? (
                        <div style={{ padding: "0 14px 10px" }}>
                          <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", background: "rgba(255,255,255,0.04)" }}>
                            {trackingData.progress.map((step, i) => (
                              <div key={i} style={{ flex: 1, background: step.done ? "#14b8a6" : "transparent", borderRight: i < trackingData.progress.length - 1 ? "1px solid rgba(0,0,0,0.3)" : "none" }} />
                            ))}
                          </div>
                          <div style={{ fontSize: 9, color: "#8B95A8", marginTop: 4 }}>
                            {trackingData.progress.filter(s => s.done).length}/{trackingData.progress.length} steps
                          </div>
                        </div>
                      ) : null}
                      {/* Route + actions */}
                      <div style={{ padding: "8px 14px 10px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 10, color: "#5A6478" }}>{selectedShipment.origin} → {selectedShipment.destination}</span>
                      </div>
                      <div style={{ padding: "0 14px 12px", display: "flex", gap: 6 }}>
                        {(trackingData?.macropointUrl || driverInfo?.macropointUrl || selectedShipment.macropointUrl) && (
                          <button onClick={() => window.open(trackingData?.macropointUrl || driverInfo?.macropointUrl || selectedShipment.macropointUrl, '_blank')}
                            style={{ flex: 1, padding: "7px 10px", borderRadius: 8, background: "linear-gradient(135deg, #0f766e22, #14b8a622)", border: "1px solid #14b8a633", color: "#14b8a6", fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                            Open Macropoint ↗
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tracking warnings */}
              {trackingData?.cantMakeIt && (
                <div style={{ margin: "0 20px 8px", padding: "8px 12px", borderRadius: 8, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12 }}>⚠</span>
                  <span style={{ fontSize: 10, color: "#f87171", fontWeight: 600 }}>{trackingData.cantMakeIt}</span>
                </div>
              )}
              {trackingData?.behindSchedule && !trackingData?.cantMakeIt && (
                <div style={{ margin: "0 20px 8px", padding: "8px 12px", borderRadius: 8, background: "rgba(251,146,60,0.12)", border: "1px solid rgba(251,146,60,0.3)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12 }}>⏱</span>
                  <span style={{ fontSize: 10, color: "#fb923c", fontWeight: 600 }}>Behind Schedule{trackingData?.mpDisplayDetail ? ` — ${trackingData.mpDisplayDetail}` : ""}</span>
                </div>
              )}
              {trackingData?.mpDisplayStatus === "On Time" && !trackingData?.cantMakeIt && !trackingData?.behindSchedule && trackingData?.mpDisplayDetail && (
                <div style={{ margin: "0 20px 8px", padding: "8px 12px", borderRadius: 8, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12 }}>✓</span>
                  <span style={{ fontSize: 10, color: "#22C55E", fontWeight: 600 }}>On Time — {trackingData.mpDisplayDetail}</span>
                </div>
              )}

              {/* Schedule & Tracking — compact table (RepDashboard) */}
              {(selectedShipment.pickupDate || selectedShipment.deliveryDate || parsedStops.pickup.arrived || parsedStops.delivery.arrived) && (() => {
                const fmtTs = (v) => {
                  if (!v) return "";
                  if (v.includes("T")) { try { const d = new Date(v); return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; } catch {} }
                  const m = v.match(/^(\d{1,2})\/(\d{1,2})\/\d{4}\s+(.+)/);
                  if (m) return `${m[1]}/${m[2]} ${m[3]}`;
                  const m2 = v.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}:\d{2})/);
                  if (m2) return `${parseInt(m2[2])}/${parseInt(m2[3])} ${m2[4]}`;
                  return v;
                };
                const origin = selectedShipment.origin || trackingData?.origin || "";
                const dest = selectedShipment.destination || trackingData?.destination || "";
                const mono = { fontFamily: "'JetBrains Mono', monospace", fontSize: 9, fontWeight: 600 };
                const headerCell = { fontSize: 7, fontWeight: 700, color: "#5A6478", letterSpacing: "1px", textTransform: "uppercase", padding: "0 0 3px", textAlign: "right" };
                const valCell = { ...mono, padding: "2px 0", textAlign: "right" };
                return (
                <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Schedule & Tracking</div>
                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr 1fr", gap: "0 10px", alignItems: "center" }}>
                    <div />
                    <div style={headerCell}>Sched</div>
                    <div style={headerCell}>Arrived</div>
                    <div style={headerCell}>Departed</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#f59e0b", flexShrink: 0 }} />
                      <span style={{ fontSize: 9, fontWeight: 700, color: "#F0F2F5" }}>PU</span>
                      {origin && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{origin.length > 18 ? origin.slice(0, 18) + "…" : origin}</span>}
                    </div>
                    <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.pickupDate) || "—"}</div>
                    <div style={{ ...valCell, color: parsedStops.pickup.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.pickup.arrived) || "—"}</div>
                    <div style={{ ...valCell, color: parsedStops.pickup.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.pickup.departed) || "—"}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#10b981", flexShrink: 0 }} />
                      <span style={{ fontSize: 9, fontWeight: 700, color: "#F0F2F5" }}>DEL</span>
                      {dest && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{dest.length > 18 ? dest.slice(0, 18) + "…" : dest}</span>}
                    </div>
                    <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.deliveryDate) || "—"}</div>
                    <div style={{ ...valCell, color: parsedStops.delivery.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.delivery.arrived) || "—"}</div>
                    <div style={{ ...valCell, color: parsedStops.delivery.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.delivery.departed) || "—"}</div>
                  </div>
                  {parsedStops.delivered && (
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#00D4AA", flexShrink: 0 }} />
                      <span style={{ fontSize: 9, fontWeight: 700, color: "#00D4AA" }}>Delivered</span>
                      {parsedStops.deliveredLocation && <span style={{ fontSize: 8, color: "#5A6478" }}>{parsedStops.deliveredLocation}</span>}
                      <span style={{ marginLeft: "auto", ...mono, fontSize: 9, color: "#8B95A8" }}>{fmtTs(parsedStops.delivered)}</span>
                    </div>
                  )}
                </div>
                );
              })()}

              {/* Status Selector — move-type aware */}
              <div style={{ padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>Status</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {getStatusesForShipment(selectedShipment).filter(s => s.key !== "all").map(s => {
                    const isActive = selectedShipment.status === s.key;
                    const sc2 = getStatusColors(selectedShipment)[s.key] || { main: "#94a3b8" };
                    return (
                      <button key={s.key} onClick={() => handleStatusUpdate(selectedShipment.id, s.key)}
                        style={{ padding: "4px 10px", fontSize: 9, fontWeight: 700, borderRadius: 20,
                          border: `1px solid ${isActive ? sc2.main + "66" : "rgba(255,255,255,0.06)"}`,
                          background: isActive ? `${sc2.main}18` : "transparent",
                          color: isActive ? sc2.main : "#64748b", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{s.label}</button>
                    );
                  })}
                </div>
              </div>

              {/* Unified Fields Grid — shipment details + driver contact */}
              <div style={{ padding: "14px 20px" }}>
                {[
                  { label: "Account", field: "account", val: selectedShipment.account },
                  { label: "Carrier", field: "carrier", val: selectedShipment.carrier },
                  { label: "Move Type", field: "moveType", val: selectedShipment.moveType },
                  { label: "Origin", field: "origin", val: selectedShipment.origin },
                  { label: "Destination", field: "destination", val: selectedShipment.destination },
                  ...(selectedShipment.moveType !== "FTL" ? [
                    { label: "ETA", field: "eta", val: selectedShipment.eta },
                    { label: "LFD", field: "lfd", val: selectedShipment.lfd },
                  ] : []),
                  { label: "Pickup", field: "pickupDate", val: selectedShipment.pickupDate },
                  { label: "Delivery", field: "deliveryDate", val: selectedShipment.deliveryDate },
                  // Driver contact fields merged inline
                  ...((selectedShipment.moveType === "FTL" || selectedShipment.macropointUrl) ? [
                    { label: "Driver", dField: "driverName", val: driverInfo.driverName, placeholder: "Add name", isDriver: true },
                    { label: "Phone", dField: "driverPhone", val: driverInfo.driverPhone, placeholder: "(555) 555-5555", action: driverInfo.driverPhone ? "call" : null, isDriver: true },
                    { label: "Email", dField: "driverEmail", val: driverInfo.driverEmail, placeholder: "driver@email.com", action: driverInfo.driverEmail ? "email" : null, isDriver: true },
                    { label: "Carrier Email", dField: "carrierEmail", val: driverInfo.carrierEmail, placeholder: "carrier@email.com", action: driverInfo.carrierEmail ? "email" : null, isDriver: true },
                    { label: "Trailer", dField: "trailerNumber", val: driverInfo.trailerNumber, placeholder: "Trailer #", isDriver: true },
                    { label: "MP URL", dField: "macropointUrl", val: driverInfo.macropointUrl || selectedShipment.macropointUrl, placeholder: "Set URL", isDriver: true },
                  ] : []),
                ].map((item) => (
                  <div key={item.field || item.dField} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                    <span style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{item.label}</span>
                    {item.isDriver ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        {driverEditing === item.dField ? (
                          <input autoFocus value={driverEditVal}
                            onChange={e => setDriverEditVal(e.target.value)}
                            onBlur={() => saveDriverField(item.dField, driverEditVal)}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setDriverEditing(null); }}
                            placeholder={item.placeholder}
                            style={{ background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, color: "#F0F2F5", padding: "3px 8px", fontSize: 11, width: 140, textAlign: "right", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                        ) : (
                          <span onClick={() => { setDriverEditing(item.dField); setDriverEditVal(item.val || ""); }}
                            style={{ fontSize: 11, color: item.val ? "#F0F2F5" : "#3D4557", cursor: "pointer", padding: "2px 6px", borderRadius: 4, fontWeight: 500 }}
                            title="Click to edit">{item.val || item.placeholder}</span>
                        )}
                        {item.action === "call" && (
                          <a href={`tel:${item.val.replace(/\D/g, "")}`}
                            style={{ display: "inline-flex", alignItems: "center", padding: "3px 8px", borderRadius: 6,
                              background: "linear-gradient(135deg, #10b98122, #10b98133)", border: "1px solid #10b98144",
                              color: "#10b981", fontSize: 9, fontWeight: 700, textDecoration: "none" }}>Call</a>
                        )}
                        {item.action === "email" && (
                          <a href={`mailto:${item.val}?subject=${encodeURIComponent(`${selectedShipment.loadNumber} - ${selectedShipment.container} Update`)}`}
                            style={{ display: "inline-flex", alignItems: "center", padding: "3px 8px", borderRadius: 6,
                              background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.3)",
                              color: "#3b82f6", fontSize: 9, fontWeight: 700, textDecoration: "none" }}>Email</a>
                        )}
                      </div>
                    ) : (
                      editField === `${selectedShipment.id}-${item.field}` ? (
                        <input autoFocus value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={() => { if (editValue.trim() || item.field === 'pickupDate' || item.field === 'deliveryDate') { handleFieldEdit(selectedShipment.id, item.field, editValue.trim()); } else { setEditField(null); } }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditField(null); }}
                          style={{ background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, color: "#F0F2F5", padding: "3px 8px", fontSize: 11, width: 140, textAlign: "right", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                      ) : (
                        <span onClick={(e) => { e.stopPropagation(); setEditField(`${selectedShipment.id}-${item.field}`); setEditValue(String(item.val)); }}
                          style={{ fontSize: 11, color: "#F0F2F5", cursor: "pointer", padding: "2px 6px", borderRadius: 4, fontWeight: 500 }}
                          title="Click to edit">{item.val || "—"}</span>
                      )
                    )}
                  </div>
                ))}
              </div>

              {/* Notes */}
              <div style={{ padding: "8px 20px 14px" }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Notes</div>
                <textarea
                  value={shipments.find(s => s.id === selectedShipment.id)?.notes || ""}
                  onChange={e => { const v = e.target.value; setShipments(prev => prev.map(s => s.id === selectedShipment.id ? { ...s, notes: v } : s)); }}
                  onBlur={() => addSheetLog(`Notes updated | ${selectedShipment.loadNumber}`)}
                  placeholder="Add notes..."
                  style={{ width: "100%", minHeight: 50, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", padding: 10, fontSize: 11, resize: "vertical", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
              </div>

              {/* Timestamped Notes Log */}
              <div style={{ padding: "4px 20px 14px" }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>
                  Notes Log {loadNotes.length > 0 && <span style={{ color: "#5A6478" }}>({loadNotes.length})</span>}
                </div>
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  <input
                    value={noteInput}
                    onChange={e => setNoteInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitNote(); } }}
                    placeholder="Add a timestamped note..."
                    style={{ flex: 1, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#F0F2F5", padding: "7px 10px", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                  <button
                    onClick={submitNote}
                    disabled={!noteInput.trim() || noteSubmitting}
                    style={{ background: noteInput.trim() ? "#00D4AA" : "rgba(255,255,255,0.06)", color: noteInput.trim() ? "#0A0E17" : "#5A6478", border: "none", borderRadius: 8, padding: "6px 14px", fontSize: 10, fontWeight: 700, cursor: noteInput.trim() ? "pointer" : "default", opacity: noteSubmitting ? 0.5 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    {noteSubmitting ? "..." : "Add"}
                  </button>
                </div>
                {loadNotes.length > 0 && (
                  <div style={{ maxHeight: 180, overflow: "auto", borderLeft: "2px solid rgba(0,212,170,0.15)", paddingLeft: 12 }}>
                    {loadNotes.map(n => (
                      <div key={n.id} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                        <div style={{ fontSize: 10, color: "#F0F2F5", lineHeight: 1.4 }}>{n.note_text}</div>
                        <div style={{ fontSize: 9, color: "#5A6478", marginTop: 3 }}>
                          {n.created_by} &middot; {new Date(n.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Email History */}
              {loadEmails.length > 0 && (
                <div style={{ padding: "8px 20px 12px" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase", marginBottom: 8 }}>
                    Emails <span style={{ color: "#8B95A8" }}>({loadEmails.length})</span>
                  </div>
                  <div style={{ maxHeight: 200, overflow: "auto" }}>
                    {loadEmails.map(em => (
                      <div key={em.id} style={{ display: "flex", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                        <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1 }}>{em.has_attachments ? "\u{1F4CE}" : "\u2709"}</span>
                        {em.priority && <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginTop: 5, background: em.priority >= 5 ? "#EF4444" : em.priority >= 4 ? "#F97316" : em.priority >= 3 ? "#3B82F6" : "#6B7280" }} />}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <div style={{ fontSize: 10, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
                              {em.subject || "(no subject)"}
                            </div>
                            {em.email_type && em.email_type !== "general" && (
                              <span style={{ fontSize: 7, padding: "1px 4px", borderRadius: 3, fontWeight: 600, background: em.email_type.includes("rate") ? "rgba(0,212,170,0.15)" : em.email_type === "detention" ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.15)", color: em.email_type.includes("rate") ? "#00D4AA" : em.email_type === "detention" ? "#EF4444" : "#3B82F6", whiteSpace: "nowrap", flexShrink: 0 }}>
                                {em.email_type.replace(/_/g, " ").toUpperCase()}
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 8, color: "#8B95A8" }}>
                            {(em.sender || "").replace(/<[^>]+>/g, "").trim()}
                            {" \u00B7 "}
                            {em.sent_at ? new Date(em.sent_at).toLocaleDateString("en-US", { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}
                          </div>
                          {em.ai_summary && (
                            <div style={{ fontSize: 8, color: "#5A6478", marginTop: 2, fontStyle: "italic", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {em.ai_summary}
                            </div>
                          )}
                          {em.attachment_names && (
                            <div style={{ fontSize: 8, color: "#4D5669", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {em.attachment_names}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Document Hub */}
              <div style={{ padding: "8px 20px 20px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>
                    Documents {loadDocs.length > 0 && <span style={{ color: "#8B95A8" }}>({loadDocs.length})</span>}
                  </div>
                </div>

                {/* Category filter tabs */}
                {loadDocs.length > 0 && (
                  <div style={{ display: "flex", gap: 2, marginBottom: 10, background: "#0D1119", borderRadius: 10, padding: 3 }}>
                    {[
                      { id: "all", label: "All" },
                      { id: "rates", label: "Rates", match: t => t.includes("rate") },
                      { id: "pod", label: "POD", match: t => t === "pod" },
                      { id: "bol", label: "BOL", match: t => t === "bol" },
                      { id: "email", label: "Email", match: t => t === "email" },
                      { id: "other", label: "Other", match: t => !t.includes("rate") && t !== "pod" && t !== "bol" && t !== "email" },
                    ].map(tab => {
                      const count = tab.id === "all" ? loadDocs.length : loadDocs.filter(d => tab.match(d.doc_type)).length;
                      return (
                        <button key={tab.id} onClick={() => setDocFilter(tab.id)}
                          style={{ flex: 1, padding: "3px 6px", borderRadius: 4, border: "none", fontSize: 8, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                            background: docFilter === tab.id ? "#1E2738" : "transparent", boxShadow: docFilter === tab.id ? "0 1px 4px rgba(0,0,0,0.3)" : "none",
                            color: docFilter === tab.id ? "#F0F2F5" : "#8B95A8" }}>
                          {tab.label} {count > 0 && <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{count}</span>}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Document list */}
                {loadDocs.length > 0 && (
                  <div style={{ maxHeight: 180, overflow: "auto", marginBottom: 10 }}>
                    {loadDocs.filter(d => {
                      if (docFilter === "all") return true;
                      if (docFilter === "rates") return d.doc_type.includes("rate");
                      if (docFilter === "pod") return d.doc_type === "pod";
                      if (docFilter === "bol") return d.doc_type === "bol";
                      if (docFilter === "email") return d.doc_type === "email";
                      return !d.doc_type.includes("rate") && d.doc_type !== "pod" && d.doc_type !== "bol" && d.doc_type !== "email";
                    }).map(doc => {
                      const icon = doc.doc_type === "carrier_invoice" ? "🧾" : doc.doc_type.includes("rate") ? "💰" : doc.doc_type === "pod" ? "📸" : doc.doc_type === "bol" ? "📋" : doc.doc_type === "screenshot" ? "🖼" : doc.doc_type === "email" ? "✉" : "📄";
                      const size = doc.size_bytes < 1024 ? `${doc.size_bytes}B` : doc.size_bytes < 1048576 ? `${Math.round(doc.size_bytes / 1024)}KB` : `${(doc.size_bytes / 1048576).toFixed(1)}MB`;
                      const date = doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString("en-US", { month: "numeric", day: "numeric" }) : "";
                      return (
                        <div key={doc.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, cursor: "pointer" }}
                            onClick={() => setPreviewDoc(doc)}>
                            <span style={{ fontSize: 12, flexShrink: 0 }}>{icon}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: 10, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.original_name}</div>
                              <div style={{ fontSize: 8, color: "#8B95A8", display: "flex", alignItems: "center", gap: 4 }}>
                                {reclassDocId === doc.id ? (
                                  <select autoFocus value={doc.doc_type}
                                    onChange={e => handleDocReclassify(doc.id, e.target.value)}
                                    onBlur={() => setReclassDocId(null)}
                                    onClick={e => e.stopPropagation()}
                                    style={{ background: "#0D1119", border: "1px solid #00D4AA", borderRadius: 4, color: "#F0F2F5", fontSize: 11, padding: "2px 6px", outline: "none", fontFamily: "inherit", cursor: "pointer" }}>
                                    <option value="customer_rate">Customer Rate</option>
                                    <option value="carrier_rate">Carrier Rate</option>
                                    <option value="pod">POD</option>
                                    <option value="bol">BOL</option>
                                    <option value="carrier_invoice">Carrier Invoice</option>
                                    <option value="screenshot">Screenshot</option>
                                    <option value="email">Email</option>
                                    <option value="other">Other</option>
                                  </select>
                                ) : (
                                  <span onClick={e => { e.stopPropagation(); setReclassDocId(doc.id); }}
                                    style={{ cursor: "pointer", background: "rgba(0,212,170,0.08)", border: "1px solid rgba(0,212,170,0.25)", borderRadius: 3, padding: "2px 6px", color: "#00D4AA", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }}
                                    title="Click to change type">
                                    {doc.doc_type.replace("_", " ")} <span style={{ fontSize: 9, opacity: 0.7 }}>{"\u25BC"}</span>
                                  </span>
                                )}
                                <span>· {size} · {date}</span>
                              </div>
                            </div>
                          </div>
                          <button onClick={(e) => { e.stopPropagation(); window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${doc.id}/download`, '_blank'); }}
                            style={{ background: "none", border: "none", color: "#00D4AA", cursor: "pointer", fontSize: 10, padding: "2px 4px", flexShrink: 0 }}>↓</button>
                          <button onClick={(e) => { e.stopPropagation(); handleDocDelete(doc.id); }}
                            style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 10, padding: "2px 4px", flexShrink: 0 }}
                            onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>✕</button>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Upload area */}
                <input ref={docInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff,.xlsx,.xls,.doc,.docx,.eml,.msg" style={{ display: "none" }}
                  onChange={e => { if (e.target.files[0]) handleDocUpload(e.target.files[0]); e.target.value = ""; }} />
                <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                  <select value={docType} onChange={e => setDocType(e.target.value)}
                    style={{ flex: 1, padding: "6px 8px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, color: "#8B95A8", fontSize: 10, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", cursor: "pointer" }}>
                    <option value="customer_rate" style={{ background: "#0D1119" }}>Customer Rate</option>
                    <option value="carrier_rate" style={{ background: "#0D1119" }}>Carrier Rate</option>
                    <option value="pod" style={{ background: "#0D1119" }}>POD</option>
                    <option value="bol" style={{ background: "#0D1119" }}>BOL</option>
                    <option value="carrier_invoice" style={{ background: "#0D1119" }}>Carrier Invoice</option>
                    <option value="screenshot" style={{ background: "#0D1119" }}>Screenshot</option>
                    <option value="email" style={{ background: "#0D1119" }}>Email</option>
                    <option value="other" style={{ background: "#0D1119" }}>Other</option>
                  </select>
                  <button onClick={() => docInputRef.current?.click()} disabled={docUploading}
                    style={{ padding: "6px 14px", borderRadius: 6, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 10, fontWeight: 700, cursor: docUploading ? "default" : "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", opacity: docUploading ? 0.6 : 1 }}>
                    {docUploading ? "..." : "+ Upload"}
                  </button>
                </div>
                <div onClick={() => !docUploading && docInputRef.current?.click()}
                  onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
                  onDrop={e => { e.preventDefault(); e.stopPropagation(); if (e.dataTransfer?.files?.[0]) handleDocUpload(e.dataTransfer.files[0]); }}
                  style={{ padding: "12px 14px", borderRadius: 8, background: "rgba(255,255,255,0.02)", border: "1px dashed rgba(255,255,255,0.1)", color: "#8B95A8", fontSize: 10, textAlign: "center", cursor: docUploading ? "default" : "pointer" }}>
                  Drop files here — PDF, images, Excel, Word, email
                </div>
                {docUploadMsg && (
                  <div style={{ marginTop: 6, fontSize: 10, fontWeight: 600, color: docUploadMsg === "Uploaded" ? "#34d399" : "#f87171", textAlign: "center" }}>
                    {docUploadMsg}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Document Preview Modal — now rendered by LoadSlideOver at top level */}
      {false && previewDoc && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", backdropFilter: "blur(12px)",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          zIndex: 200, padding: 20,
        }} onClick={() => setPreviewDoc(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            width: "90%", maxWidth: 900, maxHeight: "90vh", display: "flex", flexDirection: "column",
            background: "#0D1119", borderRadius: 16, border: "1px solid rgba(255,255,255,0.08)",
            overflow: "hidden",
          }}>
            {/* Header */}
            <div style={{
              padding: "12px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)",
              display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ fontSize: 14 }}>
                  {previewDoc.doc_type === "carrier_invoice" ? "\u{1f9fe}" : previewDoc.doc_type.includes("rate") ? "\u{1f4b0}" : previewDoc.doc_type === "pod" ? "\u{1f4f8}" : previewDoc.doc_type === "bol" ? "\u{1f4cb}" : previewDoc.doc_type === "screenshot" ? "\u{1f5bc}" : previewDoc.doc_type === "email" ? "\u2709" : "\u{1f4c4}"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {previewDoc.original_name}
                  </div>
                  <div style={{ fontSize: 10, color: "#8B95A8" }}>
                    {previewDoc.doc_type.replace("_", " ")} · {previewDoc.size_bytes < 1048576 ? `${Math.round(previewDoc.size_bytes / 1024)}KB` : `${(previewDoc.size_bytes / 1048576).toFixed(1)}MB`}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button onClick={() => window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download`, '_blank')}
                  style={{ padding: "6px 14px", borderRadius: 8, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                  Download
                </button>
                <button onClick={() => setPreviewDoc(null)}
                  style={{ background: "rgba(255,255,255,0.06)", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 14, width: 32, height: 32, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  ✕
                </button>
              </div>
            </div>
            {/* Preview content */}
            <div style={{ flex: 1, overflow: "auto", display: "flex", alignItems: "center", justifyContent: "center", padding: 20, minHeight: 300 }}>
              {isImage(previewDoc.original_name) ? (
                <img
                  src={`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download?inline=true`}
                  alt={previewDoc.original_name}
                  style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", borderRadius: 8 }}
                />
              ) : isPdf(previewDoc.original_name) ? (
                <iframe
                  src={`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download?inline=true`}
                  title={previewDoc.original_name}
                  style={{ width: "100%", height: "70vh", border: "none", borderRadius: 8, background: "#fff" }}
                />
              ) : (
                <div style={{ textAlign: "center", color: "#5A6478" }}>
                  <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>{"\u{1f4c4}"}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>No preview available</div>
                  <div style={{ fontSize: 11, color: "#3D4557", marginBottom: 16 }}>
                    {getFileExt(previewDoc.original_name).toUpperCase()} files cannot be previewed in the browser
                  </div>
                  <button onClick={() => window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download`, '_blank')}
                    style={{ padding: "8px 20px", borderRadius: 8, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    Download File
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MACROPOINT MODAL
// ═══════════════════════════════════════════════════════════════
function MacropointModal({ shipment, onClose }) {
  const [mp, setMp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [screenshot, setScreenshot] = useState(null);

  useEffect(() => {
    if (!shipment?.efj) { setLoading(false); return; }
    setLoading(true);
    // Fetch macropoint tracking, driver contact, AND screenshot in parallel
    Promise.allSettled([
      apiFetch(`${API_BASE}/api/macropoint/${shipment.efj}`).then(r => r.ok ? r.json() : null),
      apiFetch(`${API_BASE}/api/load/${shipment.efj}/driver`).then(r => r.ok ? r.json() : null),
      apiFetch(`${API_BASE}/api/macropoint/${shipment.efj}/screenshot`).then(r => r.ok ? r.blob() : null),
    ]).then(([mpRes, driverRes, ssRes]) => {
      const mpData = mpRes.status === "fulfilled" && mpRes.value ? mpRes.value : { ...MACROPOINT_FALLBACK };
      const driverData = driverRes.status === "fulfilled" && driverRes.value ? driverRes.value : {};
      // Merge driver info into macropoint data (driver endpoint takes priority)
      if (driverData.driverName) mpData.driverName = driverData.driverName;
      if (driverData.driverPhone) mpData.driverPhone = driverData.driverPhone;
      if (driverData.driverEmail) mpData.driverEmail = driverData.driverEmail;
      if (!mpData.trackingStatus || mpData.trackingStatus === "Unknown") {
        mpData.trackingStatus = shipment.rawStatus || "Pending";
      }
      setMp(mpData);
      if (ssRes.status === "fulfilled" && ssRes.value) setScreenshot(URL.createObjectURL(ssRes.value));
      setLoading(false);
    });
  }, [shipment?.efj]);

  const d = mp || MACROPOINT_FALLBACK;
  const statusColor = d.trackingStatus?.toLowerCase().includes("deliver") ? "#10b981"
    : d.trackingStatus?.toLowerCase().includes("transit") || d.trackingStatus?.toLowerCase().includes("departed") ? "#3b82f6"
    : d.trackingStatus?.toLowerCase().includes("unresponsive") || d.trackingStatus?.toLowerCase().includes("late") ? "#ef4444"
    : "#f59e0b";

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.8)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200, animation: "fade-in 0.2s ease", padding: 20 }}
      onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ width: "100%", maxWidth: 900, maxHeight: "90vh", overflow: "auto",
        background: "linear-gradient(135deg, #0D1119, #141A28)", borderRadius: 20, border: "1px solid rgba(255,255,255,0.08)", animation: "slide-up 0.3s ease" }}>
        {/* Header */}
        <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.06)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18 }}>📍</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 800, color: "#F0F2F5" }}>Macropoint Tracking</div>
              <div style={{ fontSize: 11, color: "#8B95A8" }}>{shipment.loadNumber} | {shipment.container}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: "rgba(255,255,255,0.06)", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 16, width: 32, height: 32, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center" }}>x</button>
        </div>

        {loading ? (
          <div style={{ padding: 60, textAlign: "center", color: "#8B95A8" }}>
            <div style={{ width: 24, height: 24, border: "3px solid #1A2236", borderTop: "3px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 12px" }} />
            Loading tracking data...
          </div>
        ) : (
          <>
            {/* Map — real screenshot or SVG fallback */}
            <div style={{ margin: "16px 24px", borderRadius: 14, overflow: "hidden", background: "linear-gradient(135deg, #0D1119, #141A28)", border: "1px solid rgba(255,255,255,0.06)" }}>
              {screenshot ? (
                <img src={screenshot} alt="Macropoint tracking"
                  style={{ width: "100%", height: "auto", display: "block" }} />
              ) : (
                <svg width="100%" height="200" viewBox="0 0 800 200">
                  {[40,80,120,160].map(y => <line key={y} x1="0" y1={y} x2="800" y2={y} stroke="#1e293b" strokeWidth="0.5" />)}
                  {[100,200,300,400,500,600,700].map(x => <line key={x} x1={x} y1="0" x2={x} y2="200" stroke="#1e293b" strokeWidth="0.5" />)}
                  <path d="M 120 150 C 200 130, 300 40, 400 60 S 550 80, 680 50" stroke="#00A8CC" strokeWidth="3" fill="none" opacity="0.8" />
                  <circle cx="120" cy="150" r="10" fill="#10b981" stroke="#0D1119" strokeWidth="3" />
                  <text x="120" y="175" fill="#8B95A8" fontSize="10" textAnchor="middle" fontFamily="Plus Jakarta Sans">{d.origin || shipment.origin}</text>
                  {(() => { const done = d.progress.filter(s => s.done).length; const pct = done / d.progress.length; const cx = 120 + (680-120)*pct; const cy = 150 - 90*Math.sin(pct*Math.PI);
                    return <circle cx={cx} cy={cy} r="7" fill={statusColor} stroke="#0D1119" strokeWidth="2"><animate attributeName="r" values="7;9;7" dur="2s" repeatCount="indefinite" /></circle>; })()}
                  <circle cx="680" cy="50" r="10" fill="#ef4444" stroke="#0D1119" strokeWidth="3" />
                  <text x="680" y="35" fill="#8B95A8" fontSize="10" textAnchor="middle" fontFamily="Plus Jakarta Sans">{d.destination || shipment.destination}</text>
                </svg>
              )}
            </div>

            {/* Progress + Details */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: 20, padding: "0 24px 20px" }}>
              <div>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 14, textTransform: "uppercase" }}>Progress Tracker</div>
                {d.progress.map((step, i) => {
                  const isLast = i === d.progress.length - 1;
                  return (
                    <div key={i} style={{ display: "flex", gap: 12, marginBottom: isLast ? 0 : 4 }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <div style={{ width: 16, height: 16, borderRadius: "50%",
                          background: step.done ? "#10b981" : "rgba(255,255,255,0.06)",
                          border: step.done ? "none" : "2px solid #334155",
                          display: "flex", alignItems: "center", justifyContent: "center" }}>
                          {step.done && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><path d="M5 13l4 4L19 7" /></svg>}
                        </div>
                        {!isLast && <div style={{ width: 2, height: 24, background: step.done ? "#10b98144" : "#1e293b" }} />}
                      </div>
                      <span style={{ fontSize: 12, color: step.done ? "#F0F2F5" : "#8B95A8", fontWeight: step.done ? 600 : 400 }}>{step.label}</span>
                    </div>
                  );
                })}
              </div>

              <div>
                {/* Behind Schedule / Can't Make It warning */}
                {d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>⚠</span>
                    <div>
                      <div style={{ fontSize: 11, color: "#f87171", fontWeight: 700 }}>Can't Make It</div>
                      <div style={{ fontSize: 10, color: "#fca5a5", marginTop: 2 }}>{d.cantMakeIt}</div>
                    </div>
                  </div>
                )}
                {d.behindSchedule && !d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: "rgba(251,146,60,0.12)", border: "1px solid rgba(251,146,60,0.3)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>⏱</span>
                    <div>
                      <span style={{ fontSize: 11, color: "#fb923c", fontWeight: 700 }}>Behind Schedule</span>
                      {d.mpDisplayDetail && <div style={{ fontSize: 10, color: "#fdba74", marginTop: 2 }}>{d.mpDisplayDetail}</div>}
                    </div>
                  </div>
                )}
                {d.scheduleAlert && !d.behindSchedule && !d.cantMakeIt && (
                  <div style={{ marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: d.mpDisplayStatus === "On Time" ? "rgba(34,197,94,0.12)" : "rgba(59,130,246,0.12)", border: `1px solid ${d.mpDisplayStatus === "On Time" ? "rgba(34,197,94,0.3)" : "rgba(59,130,246,0.3)"}`, display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>{d.mpDisplayStatus === "On Time" ? "\u2713" : "\u2139"}</span>
                    <div>
                      <span style={{ fontSize: 11, color: d.mpDisplayStatus === "On Time" ? "#22C55E" : "#60A5FA", fontWeight: 700 }}>{d.mpDisplayStatus || "Tracking"}</span>
                      {d.mpDisplayDetail && <div style={{ fontSize: 10, color: d.mpDisplayStatus === "On Time" ? "#86EFAC" : "#93C5FD", marginTop: 2 }}>{d.mpDisplayDetail}{d.distanceToStop ? ` | ${parseFloat(d.distanceToStop).toFixed(0)} mi to stop` : ""}</div>}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 14, textTransform: "uppercase" }}>Load Details</div>
                {[
                  { label: "Load ID", value: d.loadId || shipment.container },
                  { label: "Carrier", value: d.carrier },
                  { label: "Account", value: d.account || shipment.account },
                  ...(d.mpLoadId ? [{ label: "MP Load ID", value: d.mpLoadId }] : []),
                ].map((item, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>{item.label}</span>
                    <span style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}

                {/* Driver Info Section */}
                <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginTop: 16, marginBottom: 10, textTransform: "uppercase" }}>Driver</div>
                {d.driverName && (
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>Name</span>
                    <span style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 600 }}>{d.driverName}</span>
                  </div>
                )}

                {/* Driver Phone + Call */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Driver Phone</span>
                  {d.driverPhone ? (
                    <a href={`tel:${d.driverPhone.replace(/\D/g, '')}`} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 8,
                      background: "linear-gradient(135deg, #10b98118, #10b98128)", border: "1px solid #10b98144",
                      color: "#10b981", fontSize: 11, fontWeight: 700, textDecoration: "none" }}>
                      📞 {d.driverPhone}
                    </a>
                  ) : (
                    <span style={{ fontSize: 10, color: "#3D4557", fontStyle: "italic" }}>Not set</span>
                  )}
                </div>

                {/* Driver Email */}
                {d.driverEmail && (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ fontSize: 11, color: "#8B95A8" }}>Driver Email</span>
                    <a href={`mailto:${d.driverEmail}?subject=${encodeURIComponent(`${shipment.loadNumber} - ${shipment.container} Update`)}`}
                      style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 8,
                        background: "rgba(59,130,246,0.12)", border: "1px solid rgba(59,130,246,0.3)",
                        color: "#3b82f6", fontSize: 11, fontWeight: 600, textDecoration: "none" }}>
                      ✉ {d.driverEmail}
                    </a>
                  </div>
                )}

                {/* Dispatch Phone */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Dispatch</span>
                  <a href={`tel:${d.phone.replace(/\D/g, '')}`} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", borderRadius: 6,
                    background: "rgba(0,212,170,0.12)", border: "1px solid rgba(0,212,170,0.3)", color: "#00D4AA", fontSize: 10, fontWeight: 600, textDecoration: "none" }}>
                    📞 {d.phone}
                  </a>
                </div>

                {/* Status */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ fontSize: 11, color: "#8B95A8" }}>Status</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, boxShadow: `0 0 6px ${statusColor}66`, animation: "pulse-glow 2s ease infinite" }} />
                    <span style={{ fontSize: 11, color: statusColor, fontWeight: 700 }}>{d.trackingStatus}</span>
                  </div>
                </div>

                {(d.pickup || d.delivery || d.eta) && (
                  <div style={{ marginTop: 8, display: "flex", gap: 12 }}>
                    {d.pickup && <div style={{ fontSize: 10, color: "#8B95A8" }}>PU: <span style={{ color: "#8B95A8" }}>{d.pickup}</span></div>}
                    {d.delivery && <div style={{ fontSize: 10, color: "#8B95A8" }}>DEL: <span style={{ color: "#8B95A8" }}>{d.delivery}</span></div>}
                    {d.eta && <div style={{ fontSize: 10, color: "#8B95A8" }}>ETA: <span style={{ color: "#8B95A8" }}>{d.eta}</span></div>}
                  </div>
                )}

                {/* Stop Timeline */}
                {d.timeline && d.timeline.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>Tracking History</div>
                    {d.timeline.map((ev, i) => {
                      const dotColor = ev.type === "delivered" ? "#00D4AA" : ev.type === "arrived" ? "#10b981" : ev.type === "departed" ? "#3b82f6" : ev.type === "info" ? "#f59e0b" : "#8B95A8";
                      const fmtTime = ev.time ? (() => { try { const dt = new Date(ev.time); return dt.toLocaleString("en-US", { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true }); } catch { return ev.time; } })() : "";
                      return (
                        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, marginTop: 3, background: dotColor }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <span style={{ fontSize: 10, color: "#F0F2F5", fontWeight: 600 }}>{ev.event}</span>
                            {ev.location && <span style={{ fontSize: 10, color: "#8B95A8", marginLeft: 6 }}>{ev.location}</span>}
                          </div>
                          <span style={{ fontSize: 10, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace", flexShrink: 0, whiteSpace: "nowrap" }}>{fmtTime}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Last MP update timestamp */}
                {(d.mpLastUpdated || d.lastScraped) && (
                  <div style={{ marginTop: 8, fontSize: 9, color: "#3D4557", textAlign: "right" }} title={d.mpLastUpdated || d.lastScraped}>
                    Last MP update: {relativeTime(d.mpLastUpdated || d.lastScraped) || d.lastScraped}
                  </div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                  {d.driverPhone ? (
                    <a href={`tel:${d.driverPhone.replace(/\D/g, '')}`}
                      style={{ flex: 1, padding: "9px 0", borderRadius: 10, background: "linear-gradient(135deg, #10b98118, #10b98128)", border: "1px solid #10b98144",
                        color: "#10b981", fontSize: 11, fontWeight: 700, textDecoration: "none", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      📞 Call Driver
                    </a>
                  ) : (
                    <a href={`mailto:${d.email}?subject=${encodeURIComponent(`${shipment.loadNumber} - ${shipment.container} Tracking`)}`}
                      style={{ flex: 1, padding: "9px 0", borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
                        color: "#F0F2F5", fontSize: 11, fontWeight: 600, textDecoration: "none", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      ✉ Email Dispatch
                    </a>
                  )}
                  <button onClick={() => { const url = d.macropointUrl || shipment.macropointUrl; if (url) window.open(url, '_blank'); }}
                    style={{ flex: 1.5, padding: "9px 0", borderRadius: 10, background: "linear-gradient(135deg, #00D4AA, #0088E8)",
                      border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    Full Report ↗
                  </button>
                </div>
              </div>
            </div>

            <div style={{ padding: "0 24px 24px" }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 10, textTransform: "uppercase" }}>Shipment Route</div>
              <div style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", padding: 16, display: "flex", alignItems: "center", gap: 16, background: "rgba(0,0,0,0.2)" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>Origin</div>
                  <div style={{ fontSize: 13, color: "#10b981", fontWeight: 700, marginTop: 2 }}>{d.origin || shipment.origin || "—"}</div>
                </div>
                <div style={{ color: "#3D4557", fontSize: 20 }}>→</div>
                <div style={{ flex: 1, textAlign: "right" }}>
                  <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>Destination</div>
                  <div style={{ fontSize: 13, color: "#ef4444", fontWeight: 700, marginTop: 2 }}>{d.destination || shipment.destination || "—"}</div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// BILLING VIEW — Billing Queue + Unbilled Orders
// ═══════════════════════════════════════════════════════════════
function BillingView({ loaded, shipments, handleStatusUpdate, handleLoadClick, setSelectedShipment,
  unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats }) {
  const [billingTab, setBillingTab] = useState("queue");
  const [billingFilter, setBillingFilter] = useState("all");
  const [billSearch, setBillSearch] = useState("");
  const [billRepFilter, setBillRepFilter] = useState("All Reps");
  const [billAcctFilter, setBillAcctFilter] = useState("All Accounts");

  const BILLING_KEYS = ["ready_to_close", "missing_invoice", "ppwk_needed", "waiting_confirmation", "waiting_cx_approval", "cx_approved"];

  const billingQueue = useMemo(() => {
    return (Array.isArray(shipments) ? shipments : []).filter(s => BILLING_KEYS.includes(s.status));
  }, [shipments]);

  const filteredQueue = useMemo(() => {
    let q = billingQueue;
    if (billingFilter !== "all") q = q.filter(s => {
      if (billingFilter === "waiting") return ["waiting_confirmation", "waiting_cx_approval", "cx_approved"].includes(s.status);
      return s.status === billingFilter;
    });
    if (billRepFilter !== "All Reps") q = q.filter(s => {
      const rep = resolveRepForShipment(s);
      return rep === billRepFilter;
    });
    if (billAcctFilter !== "All Accounts") q = q.filter(s => s.account === billAcctFilter);
    if (billSearch) {
      const qs = billSearch.toLowerCase();
      q = q.filter(s => (s.efj || "").toLowerCase().includes(qs) || (s.container || "").toLowerCase().includes(qs) ||
        (s.account || "").toLowerCase().includes(qs) || (s.carrier || "").toLowerCase().includes(qs) ||
        (s.loadNumber || "").toLowerCase().includes(qs));
    }
    q.sort((a, b) => {
      const da = a.deliveryDate ? new Date(a.deliveryDate) : new Date(0);
      const db = b.deliveryDate ? new Date(b.deliveryDate) : new Date(0);
      return da - db;
    });
    return q;
  }, [billingQueue, billingFilter, billRepFilter, billAcctFilter, billSearch]);

  const counts = useMemo(() => ({
    ready_to_close: billingQueue.filter(s => s.status === "ready_to_close").length,
    missing_invoice: billingQueue.filter(s => s.status === "missing_invoice").length,
    ppwk_needed: billingQueue.filter(s => s.status === "ppwk_needed").length,
    waiting: billingQueue.filter(s => ["waiting_confirmation", "waiting_cx_approval", "cx_approved"].includes(s.status)).length,
  }), [billingQueue]);

  const queueAccounts = useMemo(() => {
    const accts = [...new Set(billingQueue.map(s => s.account).filter(Boolean))].sort();
    return ["All Accounts", ...accts];
  }, [billingQueue]);

  const handleInvoicedToggle = async (s) => {
    const newVal = !s._invoiced;
    try {
      await apiFetch(`${API_BASE}/api/load/${s.efj}/invoiced`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ invoiced: newVal }),
      });
    } catch {}
  };

  const advanceBillingStatus = (s) => {
    const flow = ["ready_to_close", "missing_invoice", "ppwk_needed", "billed_closed"];
    const idx = flow.indexOf(s.status);
    if (idx >= 0 && idx < flow.length - 1) {
      handleStatusUpdate(s.id, flow[idx + 1]);
    } else if (!flow.includes(s.status)) {
      handleStatusUpdate(s.id, "billed_closed");
    }
  };

  const statCards = [
    { label: "Ready to Close", count: counts.ready_to_close, color: "#F59E0B", filter: "ready_to_close" },
    { label: "Missing Invoice", count: counts.missing_invoice, color: "#EF4444", filter: "missing_invoice" },
    { label: "PPWK Needed", count: counts.ppwk_needed, color: "#EAB308", filter: "ppwk_needed" },
    { label: "Waiting", count: counts.waiting, color: "#6B7280", filter: "waiting" },
  ];

  return (
    <div style={{ paddingTop: 16 }}>
      {/* Sub-tabs */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 16 }}>
        {[{ key: "queue", label: "Billing Queue", count: billingQueue.length }, { key: "unbilled", label: "Unbilled Orders", count: unbilledStats?.count || 0 }].map(t => (
          <button key={t.key} onClick={() => setBillingTab(t.key)}
            style={{ padding: "8px 18px", borderRadius: 10, border: billingTab === t.key ? "1px solid rgba(0,212,170,0.3)" : "1px solid rgba(255,255,255,0.06)",
              background: billingTab === t.key ? "rgba(0,212,170,0.08)" : "rgba(255,255,255,0.02)",
              color: billingTab === t.key ? "#00D4AA" : "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            {t.label}
            <span style={{ background: billingTab === t.key ? "#00D4AA22" : "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 8, fontSize: 10, fontWeight: 700,
              color: billingTab === t.key ? "#00D4AA" : "#8B95A8" }}>{t.count}</span>
          </button>
        ))}
      </div>

      {billingTab === "queue" && (
        <>
          {/* Stat cards */}
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            {statCards.map(c => (
              <div key={c.filter} onClick={() => setBillingFilter(billingFilter === c.filter ? "all" : c.filter)}
                className="glass" style={{ flex: "1 1 140px", padding: "14px 18px", borderRadius: 12, cursor: "pointer",
                  border: billingFilter === c.filter ? `1px solid ${c.color}44` : "1px solid rgba(255,255,255,0.06)",
                  background: billingFilter === c.filter ? `${c.color}0A` : "rgba(255,255,255,0.02)" }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: c.color, fontFamily: "'JetBrains Mono', monospace" }}>{c.count}</div>
                <div style={{ fontSize: 10, color: "#8B95A8", fontWeight: 600, marginTop: 2 }}>{c.label}</div>
              </div>
            ))}
          </div>

          {/* Filters */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <input value={billSearch} onChange={e => setBillSearch(e.target.value)} placeholder="Search EFJ, container, carrier..."
              style={{ padding: "7px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)",
                color: "#F0F2F5", fontSize: 12, width: 220, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
            <select value={billRepFilter} onChange={e => setBillRepFilter(e.target.value)}
              style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119",
                color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {["All Reps", ...MASTER_REPS].map(r => <option key={r} value={r} style={{ background: "#0D1119" }}>{r}</option>)}
            </select>
            <select value={billAcctFilter} onChange={e => setBillAcctFilter(e.target.value)}
              style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#0D1119",
                color: "#F0F2F5", fontSize: 11, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              {queueAccounts.map(a => <option key={a} value={a} style={{ background: "#0D1119" }}>{a}</option>)}
            </select>
            {(billingFilter !== "all" || billRepFilter !== "All Reps" || billAcctFilter !== "All Accounts" || billSearch) && (
              <button onClick={() => { setBillingFilter("all"); setBillRepFilter("All Reps"); setBillAcctFilter("All Accounts"); setBillSearch(""); }}
                style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)",
                  color: "#8B95A8", fontSize: 10, cursor: "pointer" }}>Clear</button>
            )}
          </div>

          {/* Table */}
          <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  {["EFJ #", "Account", "Rep", "Container/Load", "Carrier", "Route", "Delivered", "Status", "Invoiced", ""].map(h => (
                    <th key={h} style={{ padding: "10px 12px", textAlign: "left", color: "#8B95A8", fontSize: 10, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredQueue.length === 0 && (
                  <tr><td colSpan={10} style={{ padding: "40px 0", textAlign: "center", color: "#3D4557", fontSize: 12 }}>No loads in billing queue</td></tr>
                )}
                {filteredQueue.map(s => {
                  const bStatus = BILLING_STATUSES.find(b => b.key === s.status);
                  const bColor = BILLING_STATUS_COLORS[s.status]?.main || "#6B7280";
                  const rep = resolveRepForShipment(s);
                  return (
                    <tr key={s.id} onClick={() => handleLoadClick(s)}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", cursor: "pointer", transition: "background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.04)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <td style={{ padding: "10px 12px", fontWeight: 700, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{s.loadNumber || s.efj}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8" }}>{s.account}</td>
                      <td style={{ padding: "10px 12px", color: REP_COLORS[rep] || "#8B95A8", fontWeight: 600 }}>{rep}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>{s.container}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8" }}>{s.carrier}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11 }}>{s.origin && s.destination ? `${s.origin} → ${s.destination}` : s.destination || "—"}</td>
                      <td style={{ padding: "10px 12px", color: "#8B95A8", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
                        {s.deliveryDate ? new Date(s.deliveryDate + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—"}
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <button onClick={e => { e.stopPropagation(); advanceBillingStatus(s); }}
                          style={{ padding: "4px 12px", borderRadius: 8, border: `1px solid ${bColor}44`, background: `${bColor}15`,
                            color: bColor, fontSize: 10, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>
                          {bStatus?.label || s.status}
                        </button>
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "center" }}>
                        <button onClick={e => { e.stopPropagation(); handleInvoicedToggle(s); }}
                          style={{ width: 18, height: 18, borderRadius: 4, border: s._invoiced ? "2px solid #A855F7" : "2px solid #3D4557",
                            background: s._invoiced ? "#A855F7" : "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", padding: 0 }}>
                          {s._invoiced && <span style={{ color: "#fff", fontSize: 10, lineHeight: 1 }}>✓</span>}
                        </button>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <button onClick={e => { e.stopPropagation(); handleStatusUpdate(s.id, "billed_closed"); }}
                          title="Close out"
                          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(34,197,94,0.3)", background: "rgba(34,197,94,0.08)",
                            color: "#22C55E", fontSize: 10, fontWeight: 700, cursor: "pointer" }}>Close</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {billingTab === "unbilled" && (
        <UnbilledView loaded={loaded} unbilledOrders={unbilledOrders} setUnbilledOrders={setUnbilledOrders}
          unbilledStats={unbilledStats} setUnbilledStats={setUnbilledStats} />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// UNBILLED ORDERS VIEW
// ═══════════════════════════════════════════════════════════════
function UnbilledView({ loaded, unbilledOrders, setUnbilledOrders, unbilledStats, setUnbilledStats }) {
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [groupBy, setGroupBy] = useState(false);
  const [collapsed, setCollapsed] = useState({});
  const [ubSearch, setUbSearch] = useState("");
  const [billingFilter, setBillingFilter] = useState("all");
  const fileRef = useRef(null);

  const handleBillingStatus = async (id, currentStatus) => {
    const flowKeys = UNBILLED_BILLING_FLOW.map(s => s.key);
    const idx = flowKeys.indexOf(currentStatus || "ready_to_bill");
    const nextStatus = flowKeys[Math.min(idx + 1, flowKeys.length - 1)];
    // Optimistic update
    setUnbilledOrders(prev => prev.map(o => o.id === id ? { ...o, billing_status: nextStatus } : o));
    try {
      await apiFetch(`${API_BASE}/api/unbilled/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ billing_status: nextStatus }),
      });
      // Auto-dismiss when closed
      if (nextStatus === "closed") {
        setTimeout(() => setUnbilledOrders(prev => prev.filter(o => o.id !== id)), 2000);
      }
    } catch {
      // Revert on failure
      setUnbilledOrders(prev => prev.map(o => o.id === id ? { ...o, billing_status: currentStatus } : o));
    }
  };

  const fetchUnbilled = async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled`);
      if (r.ok) { const data = await r.json(); setUnbilledOrders(data.orders || data || []); }
    } catch {}
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled/stats`);
      if (r.ok) setUnbilledStats(await r.json());
    } catch {}
  };

  useEffect(() => { fetchUnbilled(); }, []);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploading(true); setUploadMsg(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiFetch(`${API_BASE}/api/unbilled/upload`, { method: "POST", body: fd });
      if (r.ok) {
        const data = await r.json();
        let msg = `Imported ${data.imported} orders`;
        if (data.reconciled > 0) msg += ` | ${data.reconciled} reconciled`;
        if (data.delivered_count > 0) msg += ` | ${data.delivered_count} already delivered`;
        setUploadMsg(msg);
        fetchUnbilled();
      }
      else { setUploadMsg(`Upload failed (${r.status})`); }
    } catch (e) { setUploadMsg("Upload error — backend may not be ready"); }
    setUploading(false);
  };

  const handleDismiss = async (id) => {
    try {
      await apiFetch(`${API_BASE}/api/unbilled/${id}/dismiss`, { method: "POST" });
      setUnbilledOrders(prev => prev.filter(o => o.id !== id));
    } catch {}
  };

  const ageColor = (days) => days > 60 ? "#ef4444" : days > 30 ? "#f97316" : days > 14 ? "#fbbf24" : "#94a3b8";

  // Group by customer
  const customerGroups = {};
  unbilledOrders.forEach(o => {
    const key = o.bill_to || o.customer || "Unknown";
    if (!customerGroups[key]) customerGroups[key] = [];
    customerGroups[key].push(o);
  });
  const sortedCustomers = Object.entries(customerGroups).sort((a, b) => {
    const maxA = Math.max(...a[1].map(o => o.age_days || 0));
    const maxB = Math.max(...b[1].map(o => o.age_days || 0));
    return maxB - maxA;
  });

  // Search + billing status filtering
  const filteredOrders = unbilledOrders.filter(o => {
    if (billingFilter !== "all" && (o.billing_status || "ready_to_bill") !== billingFilter) return false;
    if (ubSearch) {
      const q = ubSearch.toLowerCase();
      return (o.order_num || "").toLowerCase().includes(q)
        || (o.container || "").toLowerCase().includes(q)
        || (o.bill_to || o.customer || "").toLowerCase().includes(q)
        || (o.tractor || "").toLowerCase().includes(q)
        || (o.rep || "").toLowerCase().includes(q);
    }
    return true;
  });
  const searchedOrders = filteredOrders;

  const searchedCustomerGroups = {};
  searchedOrders.forEach(o => {
    const key = o.bill_to || o.customer || "Unknown";
    if (!searchedCustomerGroups[key]) searchedCustomerGroups[key] = [];
    searchedCustomerGroups[key].push(o);
  });
  const searchedCustomers = Object.entries(searchedCustomerGroups).sort((a, b) => {
    const maxA = Math.max(...a[1].map(o => o.age_days || 0));
    const maxB = Math.max(...b[1].map(o => o.age_days || 0));
    return maxB - maxA;
  });

  const handleDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    const file = e.dataTransfer?.files?.[0];
    if (file && (file.name.endsWith('.xls') || file.name.endsWith('.xlsx'))) handleUpload(file);
  };

  return (
    <div style={{ animation: loaded ? "fade-in 0.5s ease" : "none" }}>
      <div style={{ padding: "24px 0 16px" }}>
        <h2 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>
          <span style={{ background: "linear-gradient(135deg, #F0F2F5, #8B95A8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>UNBILLED </span>
          <span style={{ color: "#F97316" }}>ORDERS</span>
        </h2>
        <div style={{ fontSize: 12, color: "#5A6478", marginTop: 4, letterSpacing: "0.01em" }}>Upload report, track aging, prioritize collections</div>
      </div>

      {/* Upload Zone + Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="dash-panel" style={{ padding: "20px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", cursor: "pointer", minHeight: 120 }}
          onClick={() => fileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
          onDrop={handleDrop}>
          <input ref={fileRef} type="file" accept=".xls,.xlsx" style={{ display: "none" }}
            onChange={e => { if (e.target.files[0]) handleUpload(e.target.files[0]); e.target.value = ""; }} />
          {uploading ? (
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 24, height: 24, border: "3px solid #1A2236", borderTop: "3px solid #f97316", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 10px" }} />
              <div style={{ fontSize: 12, color: "#f97316", fontWeight: 600 }}>Processing...</div>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>📄</div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Drop .xls/.xlsx or click to upload</div>
              <div style={{ fontSize: 10, color: "#3D4557", marginTop: 4 }}>Order Not Billed Report</div>
            </>
          )}
          {uploadMsg && <div style={{ marginTop: 8, fontSize: 10, fontWeight: 600, color: uploadMsg.includes("failed") || uploadMsg.includes("error") ? "#f87171" : "#34d399" }}>{uploadMsg}</div>}
        </div>

        <div className="dash-panel" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div className="dash-panel-title" style={{ marginBottom: 12 }}>Summary</div>
          <div style={{ display: "flex", gap: 20 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#f97316", fontFamily: "'JetBrains Mono', monospace" }}>{unbilledStats?.count || unbilledOrders.length}</div>
              <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Orders</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: ageColor(unbilledStats?.oldest_age || 0), fontFamily: "'JetBrains Mono', monospace" }}>{unbilledStats?.oldest_age || 0}<span style={{ fontSize: 12, color: "#8B95A8" }}>d</span></div>
              <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Oldest</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{sortedCustomers.length}</div>
              <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Customers</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{unbilledOrders.filter(o => o.shipment_delivered).length}</div>
              <div style={{ fontSize: 9, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>Delivered</div>
            </div>
          </div>
        </div>
      </div>

      {/* View toggle + bulk close */}
      <div style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <div style={{ display: "flex", gap: 2, background: "#0D1119", borderRadius: 10, padding: 3, width: "fit-content" }}>
          <button onClick={() => setGroupBy(false)}
            style={{ padding: "5px 14px", borderRadius: 5, border: "none", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              background: !groupBy ? "#1E2738" : "transparent", color: !groupBy ? "#F0F2F5" : "#8B95A8" }}>All Orders</button>
          <button onClick={() => setGroupBy(true)}
            style={{ padding: "5px 14px", borderRadius: 5, border: "none", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              background: groupBy ? "#1E2738" : "transparent", color: groupBy ? "#F0F2F5" : "#8B95A8" }}>By Customer</button>
        </div>
        {unbilledOrders.filter(o => o.shipment_delivered).length > 0 && (
          <button onClick={async () => {
            if (!confirm(`Close ${unbilledOrders.filter(o => o.shipment_delivered).length} delivered orders and archive them to history?`)) return;
            try {
              const r = await apiFetch(`${API_BASE}/api/unbilled/bulk-close-delivered`, { method: "POST" });
              if (r.ok) { const d = await r.json(); setUploadMsg(`Closed ${d.closed_count} delivered orders → archived to history`); fetchUnbilled(); }
            } catch {}
          }}
            style={{ padding: "5px 14px", borderRadius: 8, border: "1px solid #34d39944", background: "#34d39918", color: "#34d399",
              fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
            Close {unbilledOrders.filter(o => o.shipment_delivered).length} Delivered
          </button>
        )}
      </div>

      {/* Search */}
      <div style={{ position: "relative", marginBottom: 12, maxWidth: 320 }}>
        <input value={ubSearch} onChange={e => setUbSearch(e.target.value)}
          placeholder="Search order#, container, customer..."
          style={{ width: "100%", padding: "9px 14px 9px 34px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
        <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: "#8B95A8" }}>⌕</span>
        {ubSearch && (
          <span onClick={() => setUbSearch("")}
            style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "#8B95A8", cursor: "pointer" }}>✕</span>
        )}
      </div>

      {/* Billing Status Filter */}
      <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
        {[{ key: "all", label: "All", color: "#8B95A8" }, ...UNBILLED_BILLING_FLOW].map(f => {
          const count = f.key === "all" ? unbilledOrders.length : unbilledOrders.filter(o => (o.billing_status || "ready_to_bill") === f.key).length;
          const isActive = billingFilter === f.key;
          return (
            <button key={f.key} onClick={() => setBillingFilter(f.key)}
              style={{ padding: "4px 12px", fontSize: 10, fontWeight: 700, borderRadius: 6, border: `1px solid ${isActive ? f.color + "66" : "rgba(255,255,255,0.06)"}`,
                background: isActive ? f.color + "18" : "transparent", color: isActive ? f.color : "#5A6478", cursor: "pointer", fontFamily: "inherit" }}>
              {f.label} <span style={{ opacity: 0.7 }}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* Orders Table */}
      {unbilledOrders.length === 0 ? (
        <div className="dash-panel" style={{ padding: 40, textAlign: "center" }}>
          <div style={{ fontSize: 36, marginBottom: 10, opacity: 0.2 }}>📋</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#8B95A8" }}>No unbilled orders loaded</div>
          <div style={{ fontSize: 11, color: "#3D4557", marginTop: 4 }}>Upload an Order Not Billed Report to get started</div>
        </div>
      ) : !groupBy ? (
        <div className="dash-panel" style={{ overflow: "hidden" }}>
          <div style={{ overflow: "auto", maxHeight: "calc(100vh - 400px)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["Order #", "Container", "Customer", "Rep", "Entered", "Age", "Tracking", "Billing"].map(h => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 9, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5 }}>{h}</th>
                  ))}
                  <th style={{ padding: "10px 14px", width: 40, background: "#0D1119", position: "sticky", top: 0, zIndex: 5, borderBottom: "1px solid rgba(255,255,255,0.04)" }} />
                </tr>
              </thead>
              <tbody>
                {searchedOrders.map((o, i) => (
                  <tr key={o.id || i} className="row-hover" style={{ borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{o.order_num}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#5A6478" }}>{o.container}</td>
                    <td style={{ padding: "8px 14px", color: "#8B95A8", fontSize: 11 }}>{o.bill_to || o.customer}</td>
                    <td style={{ padding: "8px 14px", fontSize: 10, fontWeight: 600, color: REP_COLORS[o.rep] || "#5A6478" }}>{o.rep || "—"}</td>
                    <td style={{ padding: "8px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#8B95A8" }}>{o.entered_date || o.entered}</td>
                    <td style={{ padding: "8px 14px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(o.age_days || 0), fontFamily: "'JetBrains Mono', monospace" }}>{o.age_days || 0}d</span>
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {o.shipment_delivered ? (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 9, fontWeight: 700,
                          color: "#34d399", background: "rgba(52,211,153,0.12)", border: "1px solid rgba(52,211,153,0.2)" }}>
                          <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#34d399" }} />
                          {o.shipment_status || "Delivered"}
                        </span>
                      ) : o.shipment_status ? (
                        <span style={{ fontSize: 9, fontWeight: 600, color: "#5A6478", padding: "2px 8px", borderRadius: 12,
                          background: "rgba(139,149,168,0.08)", border: "1px solid rgba(139,149,168,0.12)" }}>
                          {o.shipment_status}
                        </span>
                      ) : (
                        <span style={{ fontSize: 9, color: "#3D4557" }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {(() => {
                        const st = UNBILLED_BILLING_FLOW.find(s => s.key === (o.billing_status || "ready_to_bill")) || UNBILLED_BILLING_FLOW[0];
                        const isClosed = st.key === "closed";
                        return (
                          <button onClick={() => !isClosed && handleBillingStatus(o.id, o.billing_status || "ready_to_bill")}
                            title={isClosed ? "Closed" : "Click to advance"}
                            style={{ padding: "3px 10px", fontSize: 9, fontWeight: 700, borderRadius: 12,
                              border: `1px solid ${st.color}44`, background: `${st.color}18`, color: st.color,
                              cursor: isClosed ? "default" : "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
                              opacity: isClosed ? 0.6 : 1 }}>
                            {st.label}
                          </button>
                        );
                      })()}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      <button onClick={() => handleDismiss(o.id)} title="Dismiss"
                        style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 12, padding: "2px 6px", borderRadius: 4 }}
                        onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {searchedCustomers.length === 0 && ubSearch && (
            <div className="dash-panel" style={{ padding: 30, textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "#8B95A8" }}>No orders match "{ubSearch}"</div>
            </div>
          )}
          {searchedCustomers.map(([customer, orders]) => {
            const isCollapsed = collapsed[customer];
            const maxAge = Math.max(...orders.map(o => o.age_days || 0));
            return (
              <div key={customer} className="dash-panel" style={{ overflow: "hidden" }}>
                <div onClick={() => setCollapsed(p => ({ ...p, [customer]: !isCollapsed }))}
                  style={{ padding: "12px 16px", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: isCollapsed ? "none" : "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 11, color: "#8B95A8", transition: "transform 0.2s", transform: isCollapsed ? "rotate(-90deg)" : "rotate(0)" }}>▼</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>{customer}</span>
                    <span style={{ fontSize: 10, color: "#8B95A8", background: "rgba(255,255,255,0.04)", padding: "2px 8px", borderRadius: 10 }}>{orders.length} orders</span>
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(maxAge), fontFamily: "'JetBrains Mono', monospace" }}>oldest: {maxAge}d</span>
                </div>
                {!isCollapsed && (
                  <div style={{ overflow: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <tbody>
                        {orders.map((o, i) => (
                          <tr key={o.id || i} className="row-hover" style={{ borderBottom: "1px solid rgba(255,255,255,0.02)" }}>
                            <td style={{ padding: "6px 14px 6px 36px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: "#00D4AA", fontSize: 11 }}>{o.order_num}</td>
                            <td style={{ padding: "6px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#5A6478" }}>{o.container}</td>
                            <td style={{ padding: "6px 14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#8B95A8" }}>{o.entered_date}</td>
                            <td style={{ padding: "6px 14px" }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: ageColor(o.age_days || 0), fontFamily: "'JetBrains Mono', monospace" }}>{o.age_days || 0}d</span>
                            </td>
                            <td style={{ padding: "6px 14px" }}>
                              {(() => {
                                const st = UNBILLED_BILLING_FLOW.find(s => s.key === (o.billing_status || "ready_to_bill")) || UNBILLED_BILLING_FLOW[0];
                                const isClosed = st.key === "closed";
                                return (
                                  <button onClick={() => !isClosed && handleBillingStatus(o.id, o.billing_status || "ready_to_bill")}
                                    style={{ padding: "2px 8px", fontSize: 8, fontWeight: 700, borderRadius: 10,
                                      border: `1px solid ${st.color}44`, background: `${st.color}18`, color: st.color,
                                      cursor: isClosed ? "default" : "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
                                      opacity: isClosed ? 0.6 : 1 }}>
                                    {st.label}
                                  </button>
                                );
                              })()}
                            </td>
                            <td style={{ padding: "6px 14px", textAlign: "right" }}>
                              <button onClick={() => handleDismiss(o.id)} title="Dismiss"
                                style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 12, padding: "2px 6px", borderRadius: 4 }}
                                onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>✕</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// RATE IQ VIEW
// ═══════════════════════════════════════════════════════════════
function RateIQView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedCarrier, setExpandedCarrier] = useState(null);
  const [tab, setTab] = useState("dray"); // dray | ftl | oog | scorecard
  const [replyAlerts, setReplyAlerts] = useState([]);
  const [scorecardPerf, setScorecardPerf] = useState([]);

  const fetchData = useCallback(async () => {
    try {
      const [rateRes, alertRes, perfRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/rate-iq`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/customer-reply-alerts`).then(r => r.json()).catch(() => []),
        apiFetch(`${API_BASE}/api/carriers/scorecard`).then(r => r.json()).catch(() => ({ carriers: [] })),
      ]);
      setData(rateRes);
      setReplyAlerts(alertRes);
      setScorecardPerf(perfRes.carriers || []);
    } catch (e) { console.error("Rate IQ fetch:", e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); const iv = setInterval(fetchData, 60000); return () => clearInterval(iv); }, [fetchData]);

  const handleQuoteAction = async (quoteId, status) => {
    try {
      await apiFetch(`${API_BASE}/api/rate-iq/${quoteId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      fetchData();
    } catch (e) { console.error("Quote action failed:", e); }
  };

  const dismissReplyAlert = async (alertId) => {
    try {
      await apiFetch(`${API_BASE}/api/customer-reply-alerts/${alertId}/dismiss`, { method: "POST" });
      setReplyAlerts(prev => prev.filter(a => a.id !== alertId));
    } catch {}
  };

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#8B95A8" }}>Loading Rate IQ...</div>;

  const lanes = data?.lanes || [];
  const scorecard = data?.scorecard || [];

  return (
    <div style={{ padding: "0 24px 24px", maxWidth: (tab === "dray" || tab === "oog") ? "none" : 1200 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate IQ</h2>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
            {data?.total_rate_quotes || 0} parsed quotes | {data?.total_carrier_quotes || 0} carrier emails | {data?.total_customer_requests || 0} customer requests
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {[
          { key: "dray", label: "Dray IQ" },
          { key: "ftl", label: "FTL IQ" },
          { key: "oog", label: "OOG IQ" },
          { key: "scorecard", label: `Scorecard (${scorecardPerf.length})` },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{ padding: "6px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid " + (tab === t.key ? "rgba(0,212,170,0.4)" : "rgba(255,255,255,0.06)"), background: tab === t.key ? "rgba(0,212,170,0.08)" : "transparent", color: tab === t.key ? "#00D4AA" : "#8B95A8", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s ease" }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Dray IQ Tab (was Quote Builder) */}
      {tab === "dray" && (
        <div style={{ height: "calc(100vh - 180px)" }}>
          <QuoteBuilder />
        </div>
      )}

      {/* FTL IQ Tab */}
      {tab === "ftl" && (
        <div style={{ textAlign: "center", padding: 60, color: "#5A6478" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🚛</div>
          <h2 style={{ color: "#F0F2F5", fontWeight: 800, fontSize: 20, margin: "0 0 8px" }}>FTL IQ</h2>
          <div style={{ fontSize: 13 }}>Full Truckload quote builder — coming soon</div>
        </div>
      )}

      {/* OOG IQ Tab */}
      {tab === "oog" && (
        <OOGQuoteBuilder />
      )}

      {/* Scorecard Tab — Carrier Performance from completed loads */}
      {tab === "scorecard" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {scorecardPerf.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>
              No carrier performance data yet — data populates from completed loads.
            </div>
          )}
          {scorecardPerf.map((c, i) => {
            const isExpanded = expandedCarrier === c.carrier;
            const otColor = c.on_time_pct >= 90 ? "#34d399" : c.on_time_pct >= 70 ? "#FBBF24" : c.on_time_pct > 0 ? "#f87171" : "#8B95A8";
            const otBg = c.on_time_pct >= 90 ? "rgba(34,197,94,0.12)" : c.on_time_pct >= 70 ? "rgba(245,158,11,0.12)" : c.on_time_pct > 0 ? "rgba(239,68,68,0.12)" : "rgba(107,114,128,0.12)";

            return (
              <div key={i} className="glass" style={{ borderRadius: 12, overflow: "hidden", border: isExpanded ? "1px solid rgba(0,212,170,0.2)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setExpandedCarrier(isExpanded ? null : c.carrier)}
                  style={{ padding: "12px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: 16, transition: "background 0.15s ease" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.carrier}
                    </div>
                    <div style={{ fontSize: 9, color: "#5A6478", marginTop: 1 }}>
                      {c.primary_move_type || "—"}{c.last_delivery ? ` · Last: ${c.last_delivery}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center", flexShrink: 0 }}>
                    <div style={{ textAlign: "center", minWidth: 44 }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.total_loads}</div>
                      <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600, letterSpacing: "0.5px" }}>LOADS</div>
                    </div>
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 10, fontWeight: 700, background: otBg, color: otColor, border: `1px solid ${otColor}30` }}>
                      {c.on_time_pct}% OT
                    </span>
                    {c.avg_transit_days != null && (
                      <div style={{ textAlign: "center", minWidth: 44 }}>
                        <div style={{ fontSize: 14, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.avg_transit_days}</div>
                        <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600 }}>AVG DAYS</div>
                      </div>
                    )}
                    <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60a5fa", fontSize: 9, fontWeight: 700 }}>
                      {c.lanes_served} lane{c.lanes_served !== 1 ? "s" : ""}
                    </span>
                    <span style={{ color: "#5A6478", fontSize: 14, transition: "transform 0.2s", transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}>&#9660;</span>
                  </div>
                </div>
                {isExpanded && c.top_lanes?.length > 0 && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "10px 16px 14px" }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Top Lanes</div>
                    {c.top_lanes.map((tl, li) => (
                      <div key={li} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(255,255,255,0.02)", marginBottom: 3 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#00D4AA", flex: 1 }}>{tl.lane}</div>
                        <div style={{ fontSize: 12, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{tl.count}</div>
                        <div style={{ fontSize: 8, color: "#5A6478" }}>loads</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// BOL GENERATOR VIEW
// ═══════════════════════════════════════════════════════════════
function BOLGeneratorView({ loaded }) {
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
        setMessage(`Generated ${count} BOLs — downloading ZIP`);
        setMessageType("success");
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        setMessage(err.detail || `Generation failed (${res.status})`);
        setMessageType("error");
      }
    } catch (e) {
      setMessage("Generation error — check connection");
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
        setMessage(`Extracted ${data.line_count || 0} lines — review and adjust below`);
        setMessageType("success");
      } else {
        const err = await res.json().catch(() => ({ detail: "OCR failed" }));
        setMessage(err.detail || "Extraction failed");
        setMessageType("error");
      }
    } catch {
      setMessage("Extraction error — check connection");
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
            <label style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 6, display: "block", textTransform: "uppercase" }}>Account</label>
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
                style={{ padding: "5px 12px", borderRadius: 5, border: "none", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
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
                  <div style={{ fontSize: 10, color: "#5A6478", marginTop: 4 }}>{(file.size / 1024).toFixed(1)} KB — {rowCount} row{rowCount !== 1 ? "s" : ""} detected</div>
                  <button onClick={(e) => { e.stopPropagation(); handleClear(); }}
                    style={{ marginTop: 8, padding: "4px 12px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#8B95A8", fontSize: 10, cursor: "pointer", fontFamily: "inherit" }}>Clear</button>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>📄</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Drop CSV/XLSX or click to upload</div>
                  <div style={{ fontSize: 10, color: "#3D4557", marginTop: 4 }}>Piedra Solar pickup & delivery plan</div>
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
                  <span style={{ fontSize: 10, color: "#5A6478" }}>{rowCount} row{rowCount !== 1 ? "s" : ""} detected</span>
                  <button onClick={handleClear}
                    style={{ padding: "3px 10px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, color: "#8B95A8", fontSize: 10, cursor: "pointer", fontFamily: "inherit" }}>Clear</button>
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
                    <span style={{ fontSize: 9, fontWeight: 700, color: "#00D4AA", letterSpacing: "1px" }}>BOL {ri + 1}</span>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={() => duplicateManualRow(ri)} title="Duplicate"
                        style={{ padding: "2px 8px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4, color: "#8B95A8", fontSize: 9, cursor: "pointer", fontFamily: "inherit" }}>Copy</button>
                      {manualRows.length > 1 && (
                        <button onClick={() => removeManualRow(ri)} title="Remove"
                          style={{ padding: "2px 8px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 4, color: "#ef4444", fontSize: 9, cursor: "pointer", fontFamily: "inherit" }}>X</button>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                    {manualCols.map(col => (
                      <div key={col}>
                        <label style={{ fontSize: 8, fontWeight: 600, color: "#5A6478", letterSpacing: "0.5px", marginBottom: 2, display: "block" }}>{col}</label>
                        <input value={row[col] || ""} onChange={e => updateManualRow(ri, col, e.target.value)}
                          placeholder={col}
                          style={{ width: "100%", padding: "6px 10px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, color: "#F0F2F5", fontSize: 10, outline: "none", fontFamily: "'JetBrains Mono', monospace" }} />
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
                    <div style={{ fontSize: 10, color: "#5A6478" }}>Click to upload a different image</div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>📷</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#8B95A8" }}>Upload a screenshot</div>
                    <div style={{ fontSize: 10, color: "#3D4557", marginTop: 4 }}>Image of a spreadsheet or delivery plan</div>
                  </>
                )}
              </div>
              {screenshotPreview && !extracting && (
                <div style={{ fontSize: 10, color: "#5A6478", marginTop: 8, lineHeight: 1.5 }}>
                  OCR extracted text will appear in the Paste tab for review. Adjust column alignment as needed before generating.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Expected Format */}
        <div className="dash-panel" style={{ padding: 20 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 12, textTransform: "uppercase" }}>Expected CSV Columns</div>
          {selectedAccount ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {selectedAccount.columns.map((col, i) => {
                const isRequired = selectedAccount.required_columns.includes(col);
                return (
                  <div key={col} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: isRequired ? "#00D4AA" : "#2A3348", flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color: isRequired ? "#F0F2F5" : "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{col}</span>
                    {isRequired && <span style={{ fontSize: 8, color: "#00D4AA", fontWeight: 700, letterSpacing: "0.5px" }}>REQUIRED</span>}
                  </div>
                );
              })}
              {selectedAccount.combined_columns?.length > 0 && (
                <div style={{ marginTop: 6, padding: "6px 10px", background: "rgba(96,165,250,0.04)", borderRadius: 8, border: "1px solid rgba(96,165,250,0.1)" }}>
                  <div style={{ fontSize: 9, color: "#60a5fa", fontWeight: 700, letterSpacing: "0.5px", marginBottom: 4 }}>OR USE COMBINED COLUMNS</div>
                  {selectedAccount.combined_columns.map(col => (
                    <div key={col} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#60a5fa", flexShrink: 0 }} />
                      <span style={{ fontSize: 11, color: "#60a5fa", fontFamily: "'JetBrains Mono', monospace" }}>{col}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 9, color: "#5A6478", marginTop: 4 }}>Auto-splits "3/6 8:15" into date + time</div>
                </div>
              )}
              <div style={{ marginTop: 8, padding: "8px 10px", background: "rgba(0,212,170,0.04)", borderRadius: 8, border: "1px solid rgba(0,212,170,0.1)" }}>
                <div style={{ fontSize: 9, color: "#00D4AA", fontWeight: 700, letterSpacing: "0.5px", marginBottom: 4 }}>SAMPLE ROW</div>
                <div style={{ fontSize: 10, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.5 }}>
                  EFJ107251, BSTT-030226P, TT-P-0302-EV-1, 16, 528, 620, 3/2/2026, 7:30 AM, 3/4/2026, 8:00 AM
                </div>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 11, color: "#5A6478" }}>Select an account to see required columns</div>
          )}
        </div>
      </div>

      {/* Preview Table */}
      {previewRows && previewRows.length > 0 && !previewRows[0]?._info && (
        <div className="dash-panel" style={{ overflow: "hidden", marginBottom: 14 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase" }}>Preview</span>
            <span style={{ fontSize: 9, color: "#5A6478", marginLeft: 8 }}>{previewRows.length} row{previewRows.length !== 1 ? "s" : ""}</span>
          </div>
          <div style={{ overflow: "auto", maxHeight: 300 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 9, fontWeight: 600, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5 }}>#</th>
                  {previewHeaders.map(h => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 9, fontWeight: 600, color: "#8B95A8", letterSpacing: "1px", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "#0D1119", position: "sticky", top: 0, zIndex: 5, whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => (
                  <tr key={i} className="row-hover">
                    <td style={{ padding: "7px 12px", borderBottom: "1px solid rgba(255,255,255,0.02)", color: "#5A6478", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>{i + 1}</td>
                    {previewHeaders.map(h => (
                      <td key={h} style={{ padding: "7px 12px", borderBottom: "1px solid rgba(255,255,255,0.02)", color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, whiteSpace: "nowrap" }}>{row[h] || ""}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* XLSX file info */}
      {previewRows && previewRows[0]?._info && (
        <div className="dash-panel" style={{ padding: "14px 16px", marginBottom: 14, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, opacity: 0.4 }}>📊</span>
          <span style={{ fontSize: 12, color: "#F0F2F5", fontWeight: 600 }}>{previewRows[0]._info}</span>
          <span style={{ fontSize: 10, color: "#5A6478" }}>— preview not available for Excel files, will be parsed server-side</span>
        </div>
      )}

      {/* Generate button + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <button
          onClick={handleGenerate}
          disabled={!hasData || generating || !account}
          className="btn-primary"
          style={{
            padding: "12px 32px", border: "none", borderRadius: 10, color: "#fff", fontSize: 13, fontWeight: 700,
            cursor: hasData && !generating ? "pointer" : "not-allowed",
            opacity: hasData && !generating ? 1 : 0.5,
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            display: "flex", alignItems: "center", gap: 8,
          }}>
          {generating ? (
            <>
              <div style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)", borderTop: "2px solid #fff", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
              Generating...
            </>
          ) : (
            <>Generate {rowCount > 0 ? `${rowCount} ` : ""}BOL{rowCount !== 1 ? "s" : ""}</>
          )}
        </button>

        {message && (
          <div style={{ fontSize: 12, fontWeight: 600, color: messageType === "success" ? "#34d399" : "#f87171" }}>
            {messageType === "success" ? "✓" : "✕"} {message}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// ADD FORM
// ═══════════════════════════════════════════════════════════════
function AddForm({ onSubmit, onCancel, accounts }) {
  const accts = (accounts || ["All Accounts"]).filter(a => a !== "All Accounts");
  const [form, setForm] = useState({
    efj: "", status: "at_port", account: accts[0] || "", carrier: "", origin: "", destination: "",
    container: "", moveType: "Dray Import", eta: "", lfd: "", pickupDate: "", deliveryDate: "", notes: "",
    macropointUrl: "", carrierEmail: "", trailerNumber: "", driverPhone: "",
    bol: "", customerRef: "", equipmentType: "", rep: "",
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
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));
  const inputStyle = { width: "100%", padding: "10px 14px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", fontSize: 12, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" };
  const autoFilledStyle = { ...inputStyle, borderColor: "rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.04)" };
  const labelStyle = { fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", marginBottom: 6, display: "block", textTransform: "uppercase" };

  const isDray = form.moveType.startsWith("Dray");
  const isExport = form.moveType === "Dray Export";
  const isFTL = form.moveType === "FTL";
  const equipOpts = isFTL ? FTL_EQUIPMENT : DRAY_EQUIPMENT;

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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {error && <div style={{ padding: "8px 12px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, color: "#f87171", fontSize: 11, fontWeight: 600 }}>{error}</div>}

      {/* Row 1: EFJ + Container/Booking */}
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
              <button onClick={() => { if (newAccountName.trim()) { set("account", newAccountName.trim()); set("rep", newAccountRep); setAddingAccount(false); } }} style={{ padding: "8px 12px", background: "rgba(0,212,170,0.15)", border: "1px solid rgba(0,212,170,0.3)", borderRadius: 8, color: "#00D4AA", fontSize: 10, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>Add</button>
              <button onClick={() => { setAddingAccount(false); set("account", accts[0] || ""); }} style={{ padding: "8px 10px", background: "transparent", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, color: "#8B95A8", fontSize: 10, cursor: "pointer" }}>&#10005;</button>
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
            <div style={{ fontSize: 9, fontWeight: 700, color: "#14b8a6", letterSpacing: "1.5px", marginBottom: 10, textTransform: "uppercase" }}>FTL Details</div>
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
          <span style={{ fontSize: 9, fontWeight: 700, color: "#8B95A8", letterSpacing: "1.5px", textTransform: "uppercase" }}>Documents</span>
          <label style={{ padding: "5px 12px", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: 6, color: "#3B82F6", fontSize: 10, fontWeight: 600, cursor: "pointer" }}>
            + Add Files
            <input type="file" multiple onChange={handleFileAdd} style={{ display: "none" }} />
          </label>
        </div>
        {pendingDocs.length === 0 && (
          <label style={{ display: "block", padding: "28px 12px", borderRadius: 10, border: dragOver ? "2px dashed #3B82F6" : "2px dashed rgba(255,255,255,0.08)", background: dragOver ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.015)", textAlign: "center", transition: "all 0.15s", cursor: "pointer" }}>
            <div style={{ fontSize: 22, marginBottom: 6, opacity: dragOver ? 1 : 0.4 }}>{dragOver ? "\u{1F4E5}" : "\u{1F4CE}"}</div>
            <div style={{ fontSize: 11, color: dragOver ? "#3B82F6" : "#8B95A8", fontWeight: 600 }}>{dragOver ? "Drop files here" : "Drag & drop files here"}</div>
            <div style={{ fontSize: 9, color: "#5A6478", marginTop: 4 }}>PDFs, images, emails (.msg, .eml), or any document</div>
            <input type="file" multiple onChange={handleFileAdd} style={{ display: "none" }} />
          </label>
        )}
        {pendingDocs.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {pendingDocs.map((doc, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: "rgba(255,255,255,0.02)", borderRadius: 6, border: "1px solid rgba(255,255,255,0.04)" }}>
                <span style={{ fontSize: 10, color: "#F0F2F5", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.file.name}</span>
                <select value={doc.docType} onChange={e => { const updated = [...pendingDocs]; updated[i] = { ...doc, docType: e.target.value }; setPendingDocs(updated); }} style={{ padding: "3px 6px", background: "#0D1119", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 4, color: "#8B95A8", fontSize: 9 }}>
                  {DOC_TYPES_ADD.map(dt => <option key={dt} value={dt}>{DOC_TYPE_LABELS[dt] || dt}</option>)}
                </select>
                <button onClick={() => setPendingDocs(p => p.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "#EF4444", cursor: "pointer", fontSize: 12, padding: "0 4px" }}>&#10005;</button>
              </div>
            ))}
            <div style={{ padding: "8px", borderRadius: 6, border: dragOver ? "2px dashed #3B82F6" : "2px dashed rgba(255,255,255,0.04)", textAlign: "center", transition: "all 0.15s" }}>
              <div style={{ fontSize: 9, color: "#5A6478" }}>Drop more files here</div>
            </div>
          </div>
        )}
      </div>

      {/* Submit */}
      <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
        <button onClick={onCancel} style={{ flex: 1, padding: "11px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Cancel</button>
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
            macropoint_url: isFTL ? (form.macropointUrl || null) : null,
            driver_phone: form.driverPhone || null,
            trailer_number: form.trailerNumber || null,
            carrier_email: form.carrierEmail || null,
            pendingDocs,
          });
        }} className="btn-primary" style={{ flex: 1.5, padding: "11px", border: "none", borderRadius: 10, color: "#fff", fontSize: 12, fontWeight: 700, cursor: submitting ? "wait" : "pointer", opacity: submitting ? 0.6 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {submitting ? "Creating..." : "Add Load"}
        </button>
      </div>
    </div>
  );
}
