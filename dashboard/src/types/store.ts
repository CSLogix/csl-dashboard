import type { Shipment } from './shipment';
import type { TrackingSummary } from './shipment';
import type { EmailThread, InboxStats } from './email';
import type { DocSummary } from './documents';
import type { UnbilledOrder, UnbilledStats } from './billing';
import type { EventAlert } from './alerts';

export interface ApiStats {
  active: number;
  on_schedule: number;
  eta_changed: number;
  at_risk: number;
  completed_today: number;
}

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  role: string;
  rep_name: string;
}

export interface DraftToast {
  id: string;
  efj: string;
  subject: string;
}

type Setter<T> = (v: T) => void;
type FnSetter<T> = (v: T | ((prev: T) => T)) => void;

export interface AppState {
  // ── Data ──
  shipments: Shipment[];
  accounts: string[];
  botStatus: unknown[];
  botHealth: unknown | null;
  cronStatus: unknown | null;
  apiStats: ApiStats;
  accountOverview: unknown[];
  trackingSummary: TrackingSummary;
  docSummary: DocSummary;
  unbilledOrders: UnbilledOrder[];
  unbilledStats: UnbilledStats;
  repProfiles: Record<string, unknown>;
  accountHealth: unknown[];
  eventAlerts: EventAlert[];
  sheetLog: string[];
  lastSyncTime: string | null;
  loaded: boolean;
  apiError: string | null;

  // ── Inbox ──
  inboxThreads: EmailThread[];
  inboxStats: InboxStats;
  inboxInitialTab: string | null;
  inboxInitialSearch: string | null;
  inboxInitialRep: string | null;

  // ── User ──
  currentUser: CurrentUser | null;

  // ── Ask AI ──
  askAIOpen: boolean;
  askAIInitialQuery: string | null;
  askAIInitialFiles: unknown[] | null;

  // ── Email Drafts ──
  emailDrafts: unknown[];
  draftToast: DraftToast | null;

  // ── System ──
  dataSource: "postgres" | "sheets";
  systemHealth: unknown | null;

  // ── Navigation ──
  activeView: string;
  selectedRep: string | null;
  selectedShipment: Shipment | null;
  expandEmailsOnOpen: boolean;
  highlightedEfj: string | null;

  // ── Filters ──
  activeStatus: string;
  activeAccount: string;
  activeRep: string;
  searchQuery: string;
  moveTypeFilter: "all" | "ftl" | "dray";
  dateFilter: string | null;
  dateRangeField: string | null;
  dateRangeStart: string;
  dateRangeEnd: string;

  // ── Setters ──
  setShipments: FnSetter<Shipment[]>;
  setAccounts: Setter<string[]>;
  setBotStatus: Setter<unknown[]>;
  setBotHealth: Setter<unknown | null>;
  setCronStatus: Setter<unknown | null>;
  setApiStats: Setter<ApiStats>;
  setAccountOverview: Setter<unknown[]>;
  setTrackingSummary: FnSetter<TrackingSummary>;
  setDocSummary: Setter<DocSummary>;
  setUnbilledOrders: Setter<UnbilledOrder[]>;
  setUnbilledStats: Setter<UnbilledStats>;
  setRepProfiles: Setter<Record<string, unknown>>;
  setAccountHealth: Setter<unknown[]>;
  setEventAlerts: FnSetter<EventAlert[]>;
  setSheetLog: Setter<string[]>;
  setLastSyncTime: Setter<string | null>;
  setLoaded: Setter<boolean>;
  setApiError: Setter<string | null>;
  setInboxThreads: Setter<EmailThread[]>;
  setInboxStats: Setter<InboxStats>;
  setInboxInitialTab: Setter<string | null>;
  setInboxInitialSearch: Setter<string | null>;
  setInboxInitialRep: Setter<string | null>;
  setCurrentUser: Setter<CurrentUser | null>;
  setAskAIOpen: Setter<boolean>;
  setAskAIInitialQuery: Setter<string | null>;
  setAskAIInitialFiles: Setter<unknown[] | null>;
  setEmailDrafts: Setter<unknown[]>;
  setDraftToast: Setter<DraftToast | null>;
  setDataSource: Setter<"postgres" | "sheets">;
  setSystemHealth: Setter<unknown | null>;
  setActiveView: Setter<string>;
  setSelectedRep: Setter<string | null>;
  setSelectedShipment: FnSetter<Shipment | null>;
  setExpandEmailsOnOpen: Setter<boolean>;
  setHighlightedEfj: Setter<string | null>;
  setActiveStatus: Setter<string>;
  setActiveAccount: Setter<string>;
  setActiveRep: Setter<string>;
  setSearchQuery: Setter<string>;
  setMoveTypeFilter: Setter<"all" | "ftl" | "dray">;
  setDateFilter: Setter<string | null>;
  setDateRangeField: Setter<string | null>;
  setDateRangeStart: Setter<string>;
  setDateRangeEnd: Setter<string>;
}
