// ─── Status Keys ───

export type DrayStatusKey =
  | "at_port" | "on_vessel" | "in_transit" | "out_for_delivery"
  | "delivered" | "empty_return" | "pending" | "on_hold"
  | "scheduled" | "released" | "returned_to_port" | "at_yard"
  | "rail" | "transload" | "on_site_loading" | "picked_up"
  | "need_pod" | "pod_received" | "issue"
  | "cancelled" | "cancelled_tonu";

export type FTLStatusKey =
  | "unassigned" | "assigned" | "scheduled" | "picking_up"
  | "in_transit" | "on_site" | "delivered"
  | "need_pod" | "pod_received" | "driver_paid"
  | "cancelled" | "cancelled_tonu";

export type BillingStatusKey =
  | "ready_to_close" | "missing_invoice" | "billed_closed"
  | "ppwk_needed" | "waiting_confirmation" | "waiting_cx_approval" | "cx_approved";

export type StatusKey = DrayStatusKey | FTLStatusKey | BillingStatusKey | "all";

export interface StatusDef {
  key: StatusKey;
  label: string;
  icon: string;
  grad: string;
}

export interface StatusColor {
  main: string;
  glow: string;
}

// ─── Move Type ───

export type MoveType = "Dray Import" | "Dray Export" | "FTL" | "";

// ─── Shipment (frontend shape from mapShipment) ───

export interface Shipment {
  id: number;
  efj: string;
  loadNumber: string;
  container: string;
  status: string;
  rawStatus: string;
  account: string;
  carrier: string;
  moveType: string;
  origin: string;
  destination: string;
  eta: string;
  lfd: string;
  pickupDate: string;
  deliveryDate: string;
  macropointUrl: string | null;
  driver: string | null;
  driverPhone: string | null;
  carrierEmail: string | null;
  trailerNumber: string | null;
  notes: string;
  truckType: string;
  customerRate: string;
  carrierPay: string;
  botAlert: string;
  rep: string;
  bol: string;
  ssl: string;
  returnPort: string;
  project: string;
  hub: string;
  mpStatus: string;
  mpDisplayStatus: string;
  mpDisplayDetail: string;
  mpLastUpdated: string;
  email_count: number;
  email_max_priority: number;
  playbookLaneCode: string | null;
  synced: boolean;
  // Billing-specific runtime fields
  _invoiced?: boolean;
}

// ─── Raw backend shipment (snake_case API response) ───

export interface RawShipment {
  id?: number;
  efj?: string;
  container?: string;
  status?: string;
  account?: string;
  carrier?: string;
  move_type?: string;
  origin?: string;
  destination?: string;
  eta?: string;
  lfd?: string;
  pickup?: string;
  delivery?: string;
  container_url?: string;
  driver?: string;
  driver_phone?: string;
  carrier_email?: string;
  trailer?: string;
  notes?: string;
  truck_type?: string;
  customer_rate?: number | string | null;
  carrier_pay?: number | string | null;
  bot_alert?: string;
  rep?: string;
  bol?: string;
  ssl?: string;
  return_port?: string;
  project?: string;
  hub?: string;
  mp_status?: string;
  mp_display_status?: string;
  mp_display_detail?: string;
  mp_last_updated?: string;
  email_count?: number;
  email_max_priority?: number;
  playbook_lane_code?: string;
}

// ─── Macropoint ───

export interface ProgressStep {
  label: string;
  done: boolean;
}

export interface MacropointData {
  loadId: string;
  carrier: string;
  driver: string;
  phone: string;
  email: string;
  trackingStatus: string;
  progress: ProgressStep[];
}

// ─── Terminal Notes ───

export interface TerminalNotes {
  avail: string | null;
  loc: string | null;
  carrier: string | null;
  cbp: string | null;
  usda: string | null;
  miscRaw: string | null;
  holds: string[];
  vessel: string | null;
  isReady: boolean;
  hasHolds: boolean;
}

// ─── Tracking Summary ───

export interface TrackingEntry {
  mpDisplayStatus?: string;
  mpStatus?: string;
  behindSchedule?: boolean;
  cantMakeIt?: boolean;
  lastUpdate?: string;
}

export type TrackingSummary = Record<string, TrackingEntry>;
