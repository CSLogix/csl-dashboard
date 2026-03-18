import { useState, useEffect } from "react";
import { STATUS_MAP, STATUSES, FTL_STATUSES, REP_ACCOUNTS, ALERT_TYPES } from './constants';
import type { Shipment, RawShipment, TerminalNotes, TrackingSummary, Alert } from '../types';
import type { DocSummary, BillingReadiness } from '../types';

// Re-export move-type helpers from constants so views can import from utils
export { isFTLShipment, getStatusesForShipment, getStatusColors, resolveStatusLabel, resolveStatusColor } from './constants';

// ─── Status Normalization ───
export function normalizeStatus(raw: string | null | undefined, moveType: string): string {
  if (!raw) return moveType === "FTL" ? "unassigned" : "pending";
  const mapped = STATUS_MAP[raw.toLowerCase()];
  if (mapped) return mapped;
  return moveType === "FTL" ? "unassigned" : "pending";
}

// ─── Map backend shipment to frontend shape ───
export function mapShipment(s: RawShipment, idx: number): Shipment {
  return {
    id: idx + 1,
    efj: s.efj || "",
    loadNumber: s.efj ? (s.efj.startsWith("EFJ") ? s.efj : `EFJ ${s.efj}`) : `#${idx + 1}`,
    container: s.container || "",
    status: normalizeStatus(s.status, s.move_type || ""),
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
    driver: s.driver || null,
    driverPhone: s.driver_phone || null,
    carrierEmail: s.carrier_email || null,
    trailerNumber: s.trailer || null,
    notes: s.notes || "",
    truckType: s.truck_type || "",
    customerRate: s.customer_rate != null ? String(s.customer_rate) : "",
    carrierPay: s.carrier_pay != null ? String(s.carrier_pay) : "",
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
    playbookLaneCode: s.playbook_lane_code || null,
    synced: true,
  };
}

// ─── Terminal Bot Notes Parser ───
export function parseTerminalNotes(notes: string): TerminalNotes | null {
  if (!notes || !notes.includes("Avail:")) return null;
  const get = (key: string): string | null => {
    const m = notes.match(new RegExp(key + ":([^|\\n]+)", "i"));
    return m ? m[1].trim() : null;
  };
  const avail = get("Avail");
  const loc = get("Loc");
  const carrier = get("Carrier");
  const cbp = get("CBP") || get("Customs");
  const usda = get("USDA");
  const miscRaw = get("Misc");
  const vessel = get("Vessel");
  const holds: string[] = [];
  if (miscRaw && miscRaw !== "None" && miscRaw !== "(None)") {
    miscRaw.split(",").forEach(c => { const t = c.trim(); if (t) holds.push(t); });
  }
  if (carrier === "HOLD") holds.push("FRT");
  if (cbp === "HOLD") holds.push("CBP");
  if (usda === "HOLD") holds.push("USDA");
  const isReady = avail === "YES" && holds.length === 0;
  const hasHolds = holds.length > 0;
  return { avail, loc, carrier, cbp, usda, miscRaw, holds, vessel, isReady, hasHolds };
}

// ─── Rep helpers ───
export function getRepShipments(shipments: Shipment[], repName: string): Shipment[] {
  const accts = REP_ACCOUNTS[repName as keyof typeof REP_ACCOUNTS] || [];
  return (Array.isArray(shipments) ? shipments : []).filter(s =>
    accts.some(a => a.toLowerCase() === s.account.toLowerCase()) ||
    s.rep?.toLowerCase() === repName.toLowerCase()
  );
}

export function resolveRepForShipment(s: Pick<Shipment, 'rep' | 'account'>): string {
  if (s.rep) return s.rep;
  for (const [rep, accts] of Object.entries(REP_ACCOUNTS)) {
    if (accts.some(a => a.toLowerCase() === (s.account || "").toLowerCase())) return rep;
  }
  return "";
}

// ─── Date/Time Utilities ───
export function parseDate(str: string | null | undefined): Date | null {
  if (!str) return null;
  const s = str.trim();
  if (/^[*\w]/.test(s) && !/^\d/.test(s)) return null;
  const year = new Date().getFullYear();
  let m = s.match(/^(\d{1,2})[/-](\d{1,2})$/);
  if (m) return new Date(year, +m[1] - 1, +m[2]);
  m = s.match(/^(\d{1,2})[/-](\d{1,2})\s+(.+)/);
  if (m && !/\d{4}/.test(m[3])) {
    const d = new Date(`${m[1]}/${m[2]}/${year} ${m[3].replace(/\s*(am|pm|to\s+.*)$/i, (x) => x.match(/am|pm/i)?.[0] || '')}`);
    if (!isNaN(d.getTime())) return d;
    return new Date(year, +m[1] - 1, +m[2]);
  }
  m = s.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2})(\d{2})$/);
  if (m) return new Date(`${m[1]}T${m[2]}:${m[3]}`);
  const d = new Date(s);
  if (!isNaN(d.getTime())) return d;
  const withYear = new Date(s + " " + year);
  if (!isNaN(withYear.getTime())) return withYear;
  return null;
}

export function relativeTime(str: string | null | undefined): string {
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

export function isDateToday(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
export function isDateTomorrow(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setDate(t.getDate() + 1);
  return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
export function isDateYesterday(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const y = new Date(); y.setDate(y.getDate() - 1);
  return d.getFullYear() === y.getFullYear() && d.getMonth() === y.getMonth() && d.getDate() === y.getDate();
}
export function isDatePast(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setHours(0,0,0,0); return d < t;
}
export function isDateFuture(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const t = new Date(); t.setHours(23,59,59,999); return d > t;
}
export function isDateThisWeek(str: string | null | undefined): boolean {
  const d = parseDate(str); if (!d) return false;
  const now = new Date(); const day = now.getDay(); const diff = now.getDate() - day + (day === 0 ? -6 : 1);
  const mon = new Date(now); mon.setDate(diff); mon.setHours(0,0,0,0);
  const sun = new Date(mon); sun.setDate(sun.getDate() + 6); sun.setHours(23,59,59,999);
  return d >= mon && d <= sun;
}

export function splitDateTime(str: string | null | undefined): { date: string; time: string } {
  if (!str) return { date: "", time: "" };
  const s = str.trim();
  const spaceIdx = s.indexOf(" ");
  if (spaceIdx > 0) {
    const afterSpace = s.slice(spaceIdx + 1).trim();
    if (/\d{1,2}:\d{2}/.test(afterSpace) || /[ap]m/i.test(afterSpace)) {
      return { date: s.slice(0, spaceIdx).trim(), time: afterSpace };
    }
  }
  return { date: s, time: "" };
}

export function calcMarginPct(customerRate: string | number, carrierPay: string | number): number | null {
  const cx = parseFloat(String(customerRate));
  const rc = parseFloat(String(carrierPay));
  if (!cx || !rc || cx <= 0) return null;
  return ((cx - rc) / cx) * 100;
}

export function formatDDMM(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const { date: dateOnly } = splitDateTime(dateStr);
  if (!dateOnly) return "";
  const s = dateOnly.trim();
  const ymd = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (ymd) return `${ymd[2]}/${ymd[3]}`;
  const mdy = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (mdy) return `${mdy[1].padStart(2, "0")}/${mdy[2].padStart(2, "0")}`;
  const mdNoYear = s.match(/^(\d{1,2})\/(\d{1,2})$/);
  if (mdNoYear) return `${mdNoYear[1].padStart(2, "0")}/${mdNoYear[2].padStart(2, "0")}`;
  if (/^\d{2}\/\d{2}$/.test(s)) return s;
  return s.slice(0, 5);
}

export function fmtDateDisplay(s: string | null | undefined): string {
  if (!s) return "\u2014";
  const norm = s.replace(/(\d{4})(\d{1,2}:)/, '$1 $2').trim();
  let m = norm.match(/(\d{1,2})\/(\d{1,2})(?:\/\d{2,4})?\s+(\d{1,2}:\d{2})/);
  if (m) return `${m[1]}/${m[2]} ${m[3].padStart(5, '0')}`;
  m = norm.match(/\d{4}-(\d{2})-(\d{2})\s+(\d{1,2}:\d{2})/);
  if (m) return `${parseInt(m[1])}/${parseInt(m[2])} ${m[3].padStart(5, '0')}`;
  m = norm.match(/^(\d{1,2})\/(\d{1,2})(?:\/\d{2,4})?$/);
  if (m) return `${m[1]}/${m[2]}`;
  m = norm.match(/^(\d{1,2})\/(\d{1,2})\s+(\d{1,2}:\d{2})/);
  if (m) return `${m[1]}/${m[2]} ${m[3].padStart(5, '0')}`;
  return norm;
}

export function parseDDMM(input: string): string | null {
  const digits = input.replace(/\D/g, "");
  if (digits.length !== 4) return null;
  const mm = digits.slice(0, 2);
  const dd = digits.slice(2, 4);
  const d = parseInt(dd, 10), m = parseInt(mm, 10);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const year = new Date().getFullYear();
  return `${year}-${mm}-${dd}`;
}

export function formatMMDD(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const s = dateStr.trim();
  const ymd = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (ymd) return `${ymd[2]}/${ymd[3]}`;
  const mdy = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (mdy) return `${mdy[1].padStart(2, "0")}/${mdy[2].padStart(2, "0")}`;
  if (/^\d{2}\/\d{2}$/.test(s)) return s;
  return s.slice(0, 5);
}

export function parseMMDD(input: string): string | null {
  const digits = input.replace(/\D/g, "");
  if (digits.length !== 4) return null;
  const mm = digits.slice(0, 2);
  const dd = digits.slice(2, 4);
  const m = parseInt(mm, 10), d = parseInt(dd, 10);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const year = new Date().getFullYear();
  return `${year}-${mm}-${dd}`;
}

export function timeAgo(ts: number): string {
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

// ─── Billing Readiness — doc-aware auto-advance logic ───
export function getBillingReadiness(efj: string, docSummary: DocSummary): BillingReadiness {
  if (!efj || !docSummary) return { ready: false, missing: ["carrier_invoice", "pod"], present: [] };
  const efjBare = (efj || "").replace(/^EFJ\s*/i, "");
  const efjNS = (efj || "").replace(/\s/g, "");
  const docs = docSummary[efjBare] || docSummary[efj] || docSummary[efjNS] || {};
  const required = ["carrier_invoice", "pod"];
  const present = required.filter(d => (docs[d] || 0) > 0);
  const missing = required.filter(d => !docs[d]);
  return { ready: missing.length === 0, missing, present };
}

// ─── Column Header Filter Helpers ───
export const COL_FILTER_KEY_MAP: Record<string, string> = {
  "Account": "account", "Status": "status", "Carrier": "carrier",
  "MP Status": "mpStatus", "Origin": "origin", "Destination": "destination",
  "Pickup": "pickup", "Delivery": "delivery", "PU": "pickup", "DEL": "delivery",
};
export const DATE_FILTER_PRESETS: string[] = ["Today", "Tomorrow", "This Week", "Past Due"];

export function matchesDatePreset(dateStr: string | null | undefined, preset: string): boolean {
  if (preset === "Today") return isDateToday(dateStr);
  if (preset === "Tomorrow") return isDateTomorrow(dateStr);
  if (preset === "This Week") return isDateThisWeek(dateStr);
  if (preset === "Past Due") return !!dateStr && isDatePast(dateStr);
  return true;
}

export function applyColFilters(data: Shipment[], filters: Record<string, string | null>, trackingSummary?: TrackingSummary): Shipment[] {
  const active = Object.entries(filters).filter(([, v]) => v != null);
  if (!active.length) return data;
  return data.filter(s => active.every(([key, val]) => {
    if (key === "pickup" || key === "delivery") return matchesDatePreset(key === "pickup" ? s.pickupDate : s.deliveryDate, val!);
    if (key === "status") return s.status === val;
    if (key === "mpStatus") { const e = (s.efj || "").replace(/^EFJ\s*/i, ""); return (s.mpDisplayStatus || trackingSummary?.[e]?.mpDisplayStatus || s.mpStatus || trackingSummary?.[e]?.mpStatus || "") === val; }
    return ((s as unknown as Record<string, unknown>)[key] || "") === val;
  }));
}

export function buildColFilterOptions(data: Shipment[], trackingSummary?: TrackingSummary): Record<string, unknown> {
  const opts: Record<string, unknown> = {};
  opts.account = [...new Set(data.map(s => s.account).filter(Boolean))].sort();
  opts.status = [...new Set(data.map(s => s.status).filter(Boolean))]
    .map(v => ({ value: v, label: [...STATUSES, ...FTL_STATUSES].find(st => st.key === v)?.label || v }))
    .sort((a, b) => a.label.localeCompare(b.label));
  opts.carrier = [...new Set(data.map(s => s.carrier).filter(Boolean))].sort();
  opts.mpStatus = [...new Set(data.map(s => { const e = (s.efj||"").replace(/^EFJ\s*/i,""); return s.mpDisplayStatus || trackingSummary?.[e]?.mpDisplayStatus || s.mpStatus || trackingSummary?.[e]?.mpStatus || ""; }).filter(Boolean))].sort();
  opts.origin = [...new Set(data.map(s => s.origin).filter(v => v && v !== "\u2014"))].sort();
  opts.destination = [...new Set(data.map(s => s.destination).filter(v => v && v !== "\u2014"))].sort();
  opts.pickup = DATE_FILTER_PRESETS;
  opts.delivery = DATE_FILTER_PRESETS;
  return opts;
}

// ─── Alert helpers ───
export function loadDismissedAlerts(): string[] {
  try { return JSON.parse(localStorage.getItem("csl_dismissed_alerts") || "[]"); } catch { return []; }
}
export function saveDismissedAlerts(ids: string[]): void {
  localStorage.setItem("csl_dismissed_alerts", JSON.stringify(ids.slice(-500)));
}

export function generateSnapshotAlerts(shipments: Shipment[], trackingSummary: TrackingSummary, docSummary: DocSummary): Alert[] {
  const alerts: Alert[] = [];
  if (!Array.isArray(shipments)) return alerts;
  for (const s of shipments) {
    const efjBare = s.efj?.replace(/^EFJ\s*/i, "");
    const rep = resolveRepForShipment(s);
    if (s.status === "delivered") {
      alerts.push({ id: `delivered_needs_billing-${s.efj}`, type: ALERT_TYPES.DELIVERED_NEEDS_BILLING as Alert['type'],
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} delivered \u2014 needs billing`,
        detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
    }
    const track = trackingSummary?.[efjBare] || trackingSummary?.[s.container];
    if (track && (track.behindSchedule || track.cantMakeIt)) {
      alerts.push({ id: `tracking_behind-${s.efj}`, type: ALERT_TYPES.TRACKING_BEHIND as Alert['type'],
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} ${track.cantMakeIt ? "cannot make it" : "behind schedule"}`,
        detail: `${s.account}${s.carrier ? " | " + s.carrier : ""}`, timestamp: Date.now(), shipmentId: s.id });
    }
    const docs = docSummary?.[efjBare] || docSummary?.[s.efj];
    if (docs?.pod && ["delivered", "need_pod"].includes(s.status)) {
      alerts.push({ id: `pod_received-${s.efj}`, type: ALERT_TYPES.POD_RECEIVED as Alert['type'],
        efj: s.efj, account: s.account, rep,
        message: `POD received for ${s.loadNumber || s.efj}`,
        detail: `${s.account} \u2014 update status`, timestamp: Date.now(), shipmentId: s.id });
    }
    if (!s.carrier && (isDateToday(s.pickupDate) || isDateTomorrow(s.pickupDate)) && !["delivered", "empty_return", "cancelled", "cancelled_tonu"].includes(s.status)) {
      alerts.push({ id: `needs_driver-${s.efj}`, type: ALERT_TYPES.NEEDS_DRIVER as Alert['type'],
        efj: s.efj, account: s.account, rep,
        message: `${s.loadNumber || s.efj} needs driver`,
        detail: `Pickup ${isDateToday(s.pickupDate) ? "today" : "tomorrow"} | ${s.account}`, timestamp: Date.now(), shipmentId: s.id });
    }
  }
  return alerts;
}

// ─── Mobile Detection ───
export function useIsMobile(breakpoint: number = 768): boolean {
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.innerWidth <= breakpoint);
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth <= breakpoint);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, [breakpoint]);
  return isMobile;
}
