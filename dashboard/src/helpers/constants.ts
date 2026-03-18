import type { Shipment, StatusDef, StatusColor } from '../types';

// ─── Z-Index Scale ───
export const Z = {
  base: 0,           // ambient BG decorations
  table: 5,          // sticky table headers
  main: 10,          // main content area
  sidebar: 20,       // sidebar navigation
  inlineEdit: 30,    // inline cell status editors
  threadPanel: 35,   // inbox thread slide-over (no backdrop)
  panelBackdrop: 50, // slide-over backdrop overlays
  panel: 60,         // slide-over panels (LoadSlideOver, etc.)
  dropdown: 80,      // floating column filter dropdowns
  modal: 200,        // centered modals (AddForm, DocPreview, Macropoint)
  palette: 300,      // CommandPalette — always on top
};

// ─── Status Normalization ───
export const STATUS_MAP = {
  // Dray statuses (space + underscore variants for PG values)
  "at yard": "at_yard", "at_yard": "at_yard", "at pickup": "at_port", "at port": "at_port", "at_port": "at_port",
  "discharged": "released",
  "vessel": "on_vessel", "vessel arrived": "on_vessel", "vessel_arrived": "on_vessel", "on vessel": "on_vessel", "on_vessel": "on_vessel",
  "in transit": "in_transit", "intransit": "in_transit", "in_transit": "in_transit",
  "delivered": "delivered",
  "returned to port": "returned_to_port", "returned_to_port": "returned_to_port",
  "empty return": "empty_return", "empty_return": "empty_return",
  "hold": "on_hold", "on hold": "on_hold", "on_hold": "on_hold",
  "scheduled": "scheduled",
  "released": "released",
  "rail": "rail",
  "transload": "transload",
  "on site loading": "on_site_loading", "on-site loading": "on_site_loading", "on_site_loading": "on_site_loading",
  "picked up": "picked_up", "picked_up": "picked_up",
  // FTL statuses
  "unassigned": "unassigned",
  "assigned": "assigned",
  "picking up": "picking_up", "picking_up": "picking_up",
  "on-site": "on_site", "on site": "on_site", "on_site": "on_site",
  "out for delivery": "out_for_delivery", "out_for_delivery": "out_for_delivery",
  "at delivery": "out_for_delivery", "at_delivery": "out_for_delivery",
  "need pod": "need_pod", "need_pod": "need_pod",
  "pod rc'd": "pod_received", "pod received": "pod_received", "pod recd": "pod_received", "pod_received": "pod_received",
  "driver paid": "driver_paid", "driver_paid": "driver_paid",
  // Tolead hub statuses
  "cargo claim": "issue",
  // Cancelled statuses
  "cancelled": "cancelled",
  "cancelled tonu": "cancelled_tonu",
  "canceled": "cancelled",
  "canceled tonu": "cancelled_tonu",
  // Billing statuses (from Google Sheet column M dropdown)
  "ready to close out": "ready_to_close",
  "ready to close": "ready_to_close",
  "ready_to_close": "ready_to_close",
  "completed": "delivered",
  "missing invoice": "missing_invoice",
  "missing_invoice": "missing_invoice",
  "billed and closed": "billed_closed",
  "billed & closed": "billed_closed",
  "billed_closed": "billed_closed",
  "ppwk needed": "ppwk_needed",
  "ppwk_needed": "ppwk_needed",
  "waiting on confirmation": "waiting_confirmation",
  "waiting_confirmation": "waiting_confirmation",
  "waiting cx approval": "waiting_cx_approval",
  "waiting_cx_approval": "waiting_cx_approval",
  "cx approved": "cx_approved",
  "cx_approved": "cx_approved",
};

// ─── Statuses ───
export const STATUSES = [
  { key: "all", label: "All", icon: "\u25CE", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "at_port", label: "At Port", icon: "\u2693", grad: "linear-gradient(135deg, #F97316, #FB923C)" },
  { key: "on_vessel", label: "On Vessel", icon: "\uD83D\uDEA2", grad: "linear-gradient(135deg, #2563EB, #3B82F6)" },
  { key: "in_transit", label: "In Transit", icon: "\u25C8", grad: "linear-gradient(135deg, #3B82F6, #60A5FA)" },
  { key: "out_for_delivery", label: "Out for Delivery", icon: "\uD83D\uDE9B", grad: "linear-gradient(135deg, #A855F7, #C084FC)" },
  { key: "delivered", label: "Delivered", icon: "\u2726", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "empty_return", label: "Empty Return", icon: "\u21A9", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "pending", label: "Pending", icon: "\u25C6", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "on_hold", label: "On Hold", icon: "\u23F8", grad: "linear-gradient(135deg, #D97706, #F59E0B)" },
  { key: "scheduled", label: "Scheduled", icon: "\uD83D\uDCC5", grad: "linear-gradient(135deg, #8B5CF6, #A78BFA)" },
  { key: "released", label: "Released", icon: "\u2713", grad: "linear-gradient(135deg, #059669, #10B981)" },
  { key: "returned_to_port", label: "Returned to Port", icon: "\u21A9", grad: "linear-gradient(135deg, #0891B2, #06B6D4)" },
  { key: "at_yard", label: "At Yard", icon: "\u25C6", grad: "linear-gradient(135deg, #4F46E5, #6366F1)" },
  { key: "rail", label: "Rail", icon: "\u25C8", grad: "linear-gradient(135deg, #475569, #64748B)" },
  { key: "transload", label: "Transload", icon: "\u21C4", grad: "linear-gradient(135deg, #7C3AED, #8B5CF6)" },
  { key: "picked_up", label: "Picked Up", icon: "\uD83D\uDE9B", grad: "linear-gradient(135deg, #7C3AED, #A78BFA)" },
  { key: "on_site_loading", label: "On Site Loading", icon: "\u25B2", grad: "linear-gradient(135deg, #B45309, #D97706)" },
  { key: "need_pod", label: "Need POD", icon: "\uD83D\uDCCB", grad: "linear-gradient(135deg, #EAB308, #FACC15)" },
  { key: "pod_received", label: "POD Rc'd", icon: "\u2713", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "issue", label: "Exception", icon: "\u26A0", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
  { key: "cancelled", label: "Cancelled", icon: "\u2715", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "cancelled_tonu", label: "TONU", icon: "\u26A0", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
];

// Billing statuses (shared across Dray + FTL, shown as separate group in status selector)
export const BILLING_STATUSES = [
  { key: "ready_to_close", label: "Ready to Close", icon: "\u2713", grad: "linear-gradient(135deg, #F59E0B, #FBBF24)" },
  { key: "missing_invoice", label: "Missing Invoice", icon: "!", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
  { key: "billed_closed", label: "Billed & Closed", icon: "\u2726", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "ppwk_needed", label: "PPWK Needed", icon: "\u25C6", grad: "linear-gradient(135deg, #EAB308, #FACC15)" },
  { key: "waiting_confirmation", label: "Waiting Confirm", icon: "\u25C7", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "waiting_cx_approval", label: "CX Approval", icon: "\u25C8", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "cx_approved", label: "CX Approved", icon: "\u25CF", grad: "linear-gradient(135deg, #14B8A6, #2DD4BF)" },
];

export const BILLING_STATUS_COLORS = {
  ready_to_close: { main: "#F59E0B", glow: "#F59E0B33" },
  missing_invoice: { main: "#EF4444", glow: "#EF444433" },
  billed_closed: { main: "#22C55E", glow: "#22C55E33" },
  ppwk_needed: { main: "#EAB308", glow: "#EAB30833" },
  waiting_confirmation: { main: "#6B7280", glow: "#6B728033" },
  waiting_cx_approval: { main: "#06B6D4", glow: "#06B6D433" },
  cx_approved: { main: "#14B8A6", glow: "#14B8A633" },
};

// Unbilled orders billing workflow
export const UNBILLED_BILLING_FLOW = [
  { key: "ready_to_bill", label: "Ready to Bill", color: "#fbbf24" },
  { key: "billed_cx", label: "Billed CX", color: "#3b82f6" },
  { key: "driver_paid", label: "Driver Paid", color: "#f97316" },
  { key: "closed", label: "Closed", color: "#34d399" },
];

export const STATUS_COLORS = {
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
  picked_up: { main: "#7C3AED", glow: "#7C3AED33" },
  on_site_loading: { main: "#B45309", glow: "#B4530933" },
  need_pod: { main: "#EAB308", glow: "#EAB30833" },
  pod_received: { main: "#06B6D4", glow: "#06B6D433" },
  issue: { main: "#F87171", glow: "#EF444433" },
  cancelled: { main: "#6B7280", glow: "#6B728033" },
  cancelled_tonu: { main: "#EF4444", glow: "#EF444433" },
  ...BILLING_STATUS_COLORS,
};

// ─── FTL Statuses ───
export const FTL_STATUSES = [
  { key: "all", label: "All", icon: "\u25CE", grad: "linear-gradient(135deg, #4B5563, #6B7280)" },
  { key: "unassigned", label: "Unassigned", icon: "\u25CB", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "assigned", label: "Assigned", icon: "\u25CF", grad: "linear-gradient(135deg, #F59E0B, #FBBF24)" },
  { key: "scheduled", label: "Scheduled", icon: "\uD83D\uDCC5", grad: "linear-gradient(135deg, #8B5CF6, #A78BFA)" },
  { key: "picking_up", label: "Picking Up", icon: "\uD83D\uDE9B", grad: "linear-gradient(135deg, #A855F7, #C084FC)" },
  { key: "in_transit", label: "In Transit", icon: "\u25C8", grad: "linear-gradient(135deg, #3B82F6, #60A5FA)" },
  { key: "on_site", label: "On-Site", icon: "\uD83D\uDCCD", grad: "linear-gradient(135deg, #F97316, #FB923C)" },
  { key: "delivered", label: "Delivered", icon: "\u2726", grad: "linear-gradient(135deg, #22C55E, #4ADE80)" },
  { key: "need_pod", label: "Need POD", icon: "\uD83D\uDCCB", grad: "linear-gradient(135deg, #EAB308, #FACC15)" },
  { key: "pod_received", label: "POD Rc'd", icon: "\u2713", grad: "linear-gradient(135deg, #06B6D4, #22D3EE)" },
  { key: "driver_paid", label: "Driver Paid", icon: "\uD83D\uDCB2", grad: "linear-gradient(135deg, #10B981, #34D399)" },
  { key: "cancelled", label: "Cancelled", icon: "\u2715", grad: "linear-gradient(135deg, #6B7280, #9CA3AF)" },
  { key: "cancelled_tonu", label: "TONU", icon: "\u26A0", grad: "linear-gradient(135deg, #EF4444, #F87171)" },
];

export const FTL_STATUS_COLORS = {
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

// ─── Post-delivery statuses (load is "done" for scheduling/tracking purposes) ───
export const POST_DELIVERY_STATUSES = new Set([
  "delivered", "need_pod", "pod_received", "empty_return", "returned_to_port",
  "ready_to_close", "missing_invoice", "billed_closed", "ppwk_needed",
  "waiting_confirmation", "waiting_cx_approval", "cx_approved", "driver_paid",
]);
export function isPostDelivery(status: string): boolean {
  return POST_DELIVERY_STATUSES.has(status);
}

// ─── Move-type helpers ───
export function isFTLShipment(s: Pick<Shipment, 'moveType' | 'account'>): boolean {
  return s.moveType === "FTL" || s.account === "Boviet" || s.account === "Tolead";
}
export function getStatusesForShipment(s: Pick<Shipment, 'moveType' | 'account'>) {
  return isFTLShipment(s) ? FTL_STATUSES : STATUSES;
}
export function getStatusColors(s: Pick<Shipment, 'moveType' | 'account'>) {
  return isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS;
}
export function resolveStatusLabel(s: Pick<Shipment, 'moveType' | 'account' | 'status' | 'rawStatus'>): string {
  const list = isFTLShipment(s) ? FTL_STATUSES : STATUSES;
  return list.find(st => st.key === s.status)?.label || BILLING_STATUSES.find(st => st.key === s.status)?.label || s.rawStatus || s.status;
}
export function resolveStatusColor(s: Pick<Shipment, 'moveType' | 'account' | 'status'>): StatusColor {
  const colors: Record<string, StatusColor> = isFTLShipment(s) ? FTL_STATUS_COLORS : STATUS_COLORS;
  return colors[s.status] || { main: "#94a3b8", glow: "#94a3b833" };
}

// Merge both status lists for "All" mode in filter bar
export const ALL_STATUSES_COMBINED = (() => {
  const seen = new Set();
  const merged = [];
  for (const s of [...STATUSES, ...FTL_STATUSES]) {
    if (!seen.has(s.key)) { seen.add(s.key); merged.push(s); }
  }
  return merged;
})();

export const ACCOUNT_COLORS = ["#ef4444", "#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#a855f7"];

export const MACROPOINT_FALLBACK = {
  loadId: "", carrier: "Evans Delivery Company, Inc.", driver: "",
  phone: "(443) 761-4954", email: "efj-operations@evansdelivery.com",
  trackingStatus: "Unknown",
  progress: [
    { label: "Driver Assigned", done: false }, { label: "Ready To Track", done: false },
    { label: "Arrived At Origin", done: false }, { label: "Departed Origin", done: false },
    { label: "At Delivery", done: false }, { label: "Delivered", done: false },
  ],
};

export const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { key: "quotes", label: "Rate IQ", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { key: "billing", label: "Billing", icon: "M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2zM10 8.5a.5.5 0 11-1 0 .5.5 0 011 0zm5 5a.5.5 0 11-1 0 .5.5 0 011 0z" },
  { key: "playbooks", label: "Playbooks", icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" },
  { key: "bol", label: "BOL Gen", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { key: "inbox", label: "Inbox", icon: "M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
  { key: "history", label: "History", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
  { key: "analytics", label: "Analytics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
];

// ─── Rep-to-Account Mapping (from Account Rep lookup table) ───
// Default mapping — overridden at runtime by /api/rep-accounts if available
export let REP_ACCOUNTS: Record<string, string[]> = {
  Radka: ["Allround", "Cadi", "IWS", "Kripke", "MGF", "Meiko", "Sutton", "Tanera", "TCR", "Texas International", "USHA", "Prolog", "Talatrans", "LS Cargo"],
  "John F": ["DHL", "DSV", "EShipping", "Kishco", "MAO", "Mamata", "Rose", "SEI Acquisition", "GW-World", "Mitchell's Transport"],
  Janice: ["CNL"],
  Allie: ["Tolead", "MD Metal"],
  "John N": ["Boviet"],
  Amanda: ["Boviet"],
  Boviet: ["Boviet"],
  Tolead: ["Tolead"],
};
export const REP_COLORS: Record<string, string> = {
  Radka: "#ef4444", "John F": "#10b981", Janice: "#ec4899",
  Allie: "#F59E0B", "John N": "#0891B2", Amanda: "#7C3AED",
  Boviet: "#8b5cf6", Tolead: "#06b6d4",
};
export let ALL_REP_NAMES = Object.keys(REP_ACCOUNTS);
export const MASTER_REPS = ["Radka", "John F", "Janice", "Allie", "John N", "Amanda"];

/** Update REP_ACCOUNTS at runtime from backend data. */
export function setRepAccounts(data: Record<string, string[]>) {
  REP_ACCOUNTS = data;
  ALL_REP_NAMES = Object.keys(data);
}
export const TRUCK_TYPES = ["", "53' Solo", "53' Team", "Flat Bed", "26' Box"];

export const DRAY_EQUIPMENT = ["", "20'", "40' Standard", "40' HC", "40' HC Reefer", "Flatrack", "Flatrack OOG", "LCL"];
export const FTL_EQUIPMENT = ["", "53' Van", "53' Team", "Box Truck", "Sprinter Van", "53' Reefer", "48ft Flatbed", "48ft Flatbed (Tarps)", "53' Flatbed", "53' Flatbed (Tarps)", "Flatbed Hotshot"];
export const DOC_TYPES_ADD = ["customer_rate", "carrier_rate", "pod", "bol", "booking", "delivery_order", "carrier_invoice", "packing_list", "msds", "email", "other"];
export const DOC_TYPE_LABELS = { customer_rate: "CX Rate", carrier_rate: "RC", pod: "POD", bol: "BOL", booking: "Booking", delivery_order: "D/O", carrier_invoice: "Carrier Inv", packing_list: "Packing List", msds: "MSDS", email: "Email", other: "Other" };

export const ALERT_TYPES = {
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
export const ALERT_TYPE_CONFIG = {
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

export const CMD_STATUS_COLORS = {
  at_port: "#F97316", on_vessel: "#2563EB", in_transit: "#3B82F6", out_for_delivery: "#A855F7",
  delivered: "#22C55E", empty_return: "#06B6D4", pending: "#6B7280", on_hold: "#D97706",
  scheduled: "#8B5CF6", released: "#059669", at_yard: "#4F46E5", picked_up: "#7C3AED", unassigned: "#6B7280",
  assigned: "#F59E0B", picking_up: "#A855F7", on_site: "#F97316", need_pod: "#EAB308",
  pod_received: "#06B6D4", driver_paid: "#10B981", cancelled: "#6B7280", cancelled_tonu: "#EF4444",
  ...Object.fromEntries(Object.entries(BILLING_STATUS_COLORS).map(([k, v]) => [k, v.main])),
};

export const INBOX_TABS = [
  { key: "all", label: "All" },
  { key: "needs_reply", label: "Needs Reply" },
  { key: "unmatched", label: "Unmatched" },
  { key: "high_priority", label: "Priority" },
];

export const EMAIL_TYPE_COLORS = {
  rate_confirmation: "#22C55E",
  carrier_rate_confirmation: "#10B981",
  customer_rate_confirmation: "#3B82F6",
  pod: "#06B6D4",
  delivery_confirmation: "#22C55E",
  carrier_invoice: "#F59E0B",
  booking_confirmation: "#8B5CF6",
  pickup_confirmation: "#A855F7",
  eta_update: "#3B82F6",
  tracking_update: "#0891B2",
  general: "#6B7280",
  payment_escalation: "#EF4444",
  bol: "#7C3AED",
  packing_list: "#14B8A6",
  customer_correspondence: "#EC4899",
  internal: "#475569",
  customs_doc: "#D97706",
  detention_demurrage: "#DC2626",
};

export const INBOX_TYPE_LABELS = {
  rate_confirmation: "Rate Confirm",
  carrier_rate_confirmation: "Carrier Rate",
  customer_rate_confirmation: "CX Rate",
  pod: "POD",
  delivery_confirmation: "Delivery",
  carrier_invoice: "Invoice",
  booking_confirmation: "Booking",
  pickup_confirmation: "Pickup",
  eta_update: "ETA Update",
  tracking_update: "Tracking",
  general: "General",
  payment_escalation: "Payment",
  bol: "BOL",
  packing_list: "Packing",
  customer_correspondence: "Customer",
  internal: "Internal",
  customs_doc: "Customs",
  detention_demurrage: "D&D",
};
