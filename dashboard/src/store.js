import { create } from 'zustand'

// ─── Core App Store ───
// Shared state accessible from any component via useAppStore()
// Existing views still receive these as props from DispatchDashboard (gradual migration)
// New components (QuoteBuilder, etc.) can import useAppStore() directly

export const useAppStore = create((set) => ({
  // ── Data ──
  shipments: [],
  accounts: ["All Accounts"],
  botStatus: [],
  botHealth: null,
  cronStatus: null,
  apiStats: { active: 0, on_schedule: 0, eta_changed: 0, at_risk: 0, completed_today: 0 },
  accountOverview: [],
  trackingSummary: {},
  docSummary: {},
  unbilledOrders: [],
  unbilledStats: { count: 0, oldest_age: 0 },
  repProfiles: {},
  accountHealth: [],
  eventAlerts: [],
  sheetLog: [],
  lastSyncTime: null,
  loaded: false,
  apiError: null,

  // ── Inbox Command Center ──
  inboxThreads: [],
  inboxStats: { total_threads: 0, needs_reply: 0, unmatched: 0, high_priority: 0 },
  inboxInitialTab: null,   // set before navigating to inbox to pre-select a tab
  inboxInitialSearch: null, // set before navigating to inbox to pre-fill search
  inboxInitialRep: null,   // set before navigating to inbox to filter by rep

  // ── Current User ──
  currentUser: null,  // { id, username, email, role, rep_name }

  // ── Email Drafts ──
  emailDrafts: [],
  draftToast: null,  // { id, efj, subject } — shown briefly after milestone status change

  // ── Data Source Fallback ──
  dataSource: "postgres",  // "postgres" or "sheets"
  systemHealth: null,

  // ── Navigation ──
  activeView: "dashboard",
  selectedRep: null,
  selectedShipment: null,
  expandEmailsOnOpen: false,  // when true, LoadSlideOver auto-expands emails section
  highlightedEfj: null,       // EFJ to pulse-highlight in dispatch table rows

  // ── Filters ──
  activeStatus: "all",
  activeAccount: "All Accounts",
  activeRep: "All Reps",
  searchQuery: "",
  moveTypeFilter: "all",
  dateFilter: null,
  dateRangeField: null,
  dateRangeStart: "",
  dateRangeEnd: "",

  // ── Actions ──
  setShipments: (v) => set(typeof v === 'function' ? (state) => ({ shipments: v(state.shipments) }) : { shipments: Array.isArray(v) ? v : [] }),
  setAccounts: (v) => set({ accounts: v }),
  setBotStatus: (v) => set({ botStatus: v }),
  setBotHealth: (v) => set({ botHealth: v }),
  setCronStatus: (v) => set({ cronStatus: v }),
  setApiStats: (v) => set({ apiStats: v }),
  setAccountOverview: (v) => set({ accountOverview: v }),
  setTrackingSummary: (v) => set({ trackingSummary: v }),
  setDocSummary: (v) => set({ docSummary: v }),
  setUnbilledOrders: (v) => set({ unbilledOrders: v }),
  setUnbilledStats: (v) => set({ unbilledStats: v }),
  setRepProfiles: (v) => set({ repProfiles: v }),
  setAccountHealth: (v) => set({ accountHealth: Array.isArray(v) ? v : [] }),
  setEventAlerts: (v) => set(typeof v === 'function' ? (state) => ({ eventAlerts: v(state.eventAlerts) }) : { eventAlerts: v }),
  setSheetLog: (v) => set({ sheetLog: v }),
  setLastSyncTime: (v) => set({ lastSyncTime: v }),
  setLoaded: (v) => set({ loaded: v }),
  setApiError: (v) => set({ apiError: v }),
  setInboxThreads: (v) => set({ inboxThreads: Array.isArray(v) ? v : [] }),
  setInboxStats: (v) => set({ inboxStats: v }),
  setInboxInitialTab: (v) => set({ inboxInitialTab: v }),
  setInboxInitialSearch: (v) => set({ inboxInitialSearch: v }),
  setInboxInitialRep: (v) => set({ inboxInitialRep: v }),
  setCurrentUser: (v) => set({ currentUser: v }),
  setEmailDrafts: (v) => set({ emailDrafts: Array.isArray(v) ? v : [] }),
  setDraftToast: (v) => set({ draftToast: v }),
  setDataSource: (v) => set({ dataSource: v }),
  setSystemHealth: (v) => set({ systemHealth: v }),

  setActiveView: (v) => set({ activeView: v }),
  setSelectedRep: (v) => set({ selectedRep: v }),
  setSelectedShipment: (v) => set(typeof v === 'function' ? (state) => ({ selectedShipment: v(state.selectedShipment) }) : { selectedShipment: v }),
  setExpandEmailsOnOpen: (v) => set({ expandEmailsOnOpen: v }),
  setHighlightedEfj: (v) => set({ highlightedEfj: v }),

  setActiveStatus: (v) => set({ activeStatus: v }),
  setActiveAccount: (v) => set({ activeAccount: v }),
  setActiveRep: (v) => set({ activeRep: v }),
  setSearchQuery: (v) => set({ searchQuery: v }),
  setMoveTypeFilter: (v) => set({ moveTypeFilter: v }),
  setDateFilter: (v) => set({ dateFilter: v }),
  setDateRangeField: (v) => set({ dateRangeField: v }),
  setDateRangeStart: (v) => set({ dateRangeStart: v }),
  setDateRangeEnd: (v) => set({ dateRangeEnd: v }),
}))
