import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';
import { useSWR } from '../helpers/useSWR';
import QuoteBuilder from '../QuoteBuilder';
import OOGQuoteBuilder from '../OOGQuoteBuilder';
import {
  LaneName, LaneCard, MarketRateCard, MarketBenchmarkCard,
  CarrierRateTable, HistoryTabContent,
} from '../components/rate-iq';
import {
  grad, fmt, fmtDec, PORT_CLUSTERS, STATE_ABBREVS,
  normalizeLocation, normalizePort, normalizeLaneCity, normalizeOrigin,
  MOVE_TYPE_STYLES, splitCityState,
} from '../components/rate-iq/constants';

// ═══════════════════════════════════════════════════════════════
// RATE IQ VIEW — Lane-centric redesign (DrayRates.ai-inspired)
// Views: browse | detail | quote | scorecard | directory | history | oog
// ═══════════════════════════════════════════════════════════════

// Constants, normalization functions, and sub-components imported from
// ../components/rate-iq/ — see constants.js and individual component files.

// HistoryTabContent — extracted to ../components/rate-iq/HistoryTabContent.jsx

// MarketRateCard — extracted to ../components/rate-iq/MarketRateCard.jsx

// MarketBenchmarkCard — extracted to ../components/rate-iq/MarketBenchmarkCard.jsx

// CarrierRateTable — extracted to ../components/rate-iq/CarrierRateTable.jsx

// LaneCard + MOVE_TYPE_STYLES — extracted to ../components/rate-iq/

// ═══════════════════════════════════════════════════════════════
// MAIN: RATE IQ VIEW
// ═══════════════════════════════════════════════════════════════
export default function RateIQView() {
  // ── View state ──
  const [view, setView] = useState("browse"); // browse | detail | intake | build-quote | scorecard | directory | history | oog
  const [selectedLane, setSelectedLane] = useState(null); // { origin, destination }

  // ── Data state ──
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [laneStats, setLaneStats] = useState([]);
  const [rateLaneSummaries, setRateLaneSummaries] = useState([]); // from lane-rates (actual rate data)
  const [expandedOrigins, setExpandedOrigins] = useState({}); // { "Chicago": true, ... }
  const [scorecardPerf, setScorecardPerf] = useState([]);
  const [expandedCarrier, setExpandedCarrier] = useState(null);
  const [dirCarriers, setDirCarriers] = useState([]);
  const [portGroups, setPortGroups] = useState([]);
  const [rateHistory, setRateHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ── Manual intake state ──
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [intakeText, setIntakeText] = useState("");
  const [intakeMoveType, setIntakeMoveType] = useState("dray");
  const [intakeProcessing, setIntakeProcessing] = useState(false);
  const [intakeResult, setIntakeResult] = useState(null); // { ok, extracted } or { error }
  const [intakeFile, setIntakeFile] = useState(null);
  const [intakeDragOver, setIntakeDragOver] = useState(false);
  const [intakePreview, setIntakePreview] = useState(null); // extracted data for review before save
  const [intakeSaving, setIntakeSaving] = useState(false);
  const intakeFileRef = useRef(null);

  // ── Market rates paste state ──
  const [marketRateOpen, setMarketRateOpen] = useState(false);
  const [marketRateOrigin, setMarketRateOrigin] = useState("");
  const [marketRateDest, setMarketRateDest] = useState("");
  const [marketRateText, setMarketRateText] = useState("");
  const [marketRateFile, setMarketRateFile] = useState(null);
  const [marketRateDragOver, setMarketRateDragOver] = useState(false);
  const marketRateFileRef = useRef(null);
  const [marketRateMoveType, setMarketRateMoveType] = useState("dray");
  const [marketRateProcessing, setMarketRateProcessing] = useState(false);
  const [marketRateResult, setMarketRateResult] = useState(null);
  const [marketBenchmark, setMarketBenchmark] = useState(null);

  // ── AI Rate Assistant state ──
  const [aiMessages, setAiMessages] = useState([]); // { role: "user"|"assistant", text }
  const [aiLoading, setAiLoading] = useState(false);
  const [aiInput, setAiInput] = useState("");
  const aiChatRef = useRef(null);

  const askAI = useCallback(async (question, laneData) => {
    if (!question.trim()) return;
    setAiMessages(prev => [...prev, { role: "user", text: question }]);
    setAiInput("");
    setAiLoading(true);
    try {
      // Build rich context from lane data
      const carriers = (laneData?.carriers || []).map(c => ({
        name: c.carrier_name,
        rate: c.total || c.dray_rate,
        fsc: c.fsc,
        chassis: c.chassis_per_day,
        prepull: c.prepull,
        overweight: c.overweight,
        date: c.created_at,
      }));
      const avgRate = laneData?.count > 0 ? Math.round(laneData.total / laneData.count) : null;
      const context = {
        lane: `${laneData?.port || ""} → ${laneData?.destination || ""}`,
        carrier_count: carriers.length,
        avg_rate: avgRate,
        floor: laneData?.minRate !== Infinity ? laneData?.minRate : null,
        ceiling: laneData?.maxRate > 0 ? laneData?.maxRate : null,
        carriers,
        market_benchmark: marketBenchmark ? {
          avg: marketBenchmark.stats?.avg,
          min: marketBenchmark.stats?.min,
          max: marketBenchmark.stats?.max,
          trend_pct: marketBenchmark.stats?.trend_pct,
        } : null,
      };
      const res = await apiFetch(`${API_BASE}/api/ask-ai`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: `You are a dray/freight rate analyst assistant. Answer concisely about this lane.\n\nLane: ${context.lane}\nCarrier rates on file: ${carriers.length}\nAvg rate: $${avgRate || "N/A"}\nFloor: $${context.floor || "N/A"} | Ceiling: $${context.ceiling || "N/A"}\n${context.market_benchmark ? `Market benchmark avg: $${context.market_benchmark.avg}, trend: ${context.market_benchmark.trend_pct > 0 ? "+" : ""}${context.market_benchmark.trend_pct?.toFixed(1) || 0}%` : ""}\n\nCarrier details:\n${carriers.map(c => `- ${c.name}: $${c.rate} (${c.date ? new Date(c.date).toLocaleDateString() : "no date"})`).join("\n")}\n\nUser question: ${question}`,
          context,
        }),
      }).then(r => r.json());
      const answer = res.answer || res.response || res.text || JSON.stringify(res);
      setAiMessages(prev => [...prev, { role: "assistant", text: answer }]);
    } catch (e) {
      setAiMessages(prev => [...prev, { role: "assistant", text: "Sorry, I couldn't process that request. " + (e.message || "") }]);
    }
    setAiLoading(false);
    setTimeout(() => { if (aiChatRef.current) aiChatRef.current.scrollTop = aiChatRef.current.scrollHeight; }, 50);
  }, [marketBenchmark]);

  // Reset AI chat when lane changes
  useEffect(() => { setAiMessages([]); setAiInput(""); }, [selectedLane]);

  // ── Lane Search state ──
  const [searchOrigin, setSearchOrigin] = useState("");
  const [searchDest, setSearchDest] = useState("");
  const [laneResults, setLaneResults] = useState([]);
  const [laneSearching, setLaneSearching] = useState(false);
  const [moveTypeFilter, setMoveTypeFilter] = useState("dray"); // all | dray | ftl | transload
  const [laneMiles, setLaneMiles] = useState({}); // "origin|dest" → { miles, loading }
  const [editingLaneRateId, setEditingLaneRateId] = useState(null);
  const [editingLaneField, setEditingLaneField] = useState(null);
  const [editingLaneValue, setEditingLaneValue] = useState("");

  // ── Autocomplete + recent searches ──
  const [originFocused, setOriginFocused] = useState(false);
  const [destFocused, setDestFocused] = useState(false);
  const originRef = useRef(null);
  const destRef = useRef(null);
  const [recentSearches, setRecentSearches] = useState(() => {
    try { return JSON.parse(localStorage.getItem("rateiq_recent") || "[]"); } catch { return []; }
  });
  const saveRecent = useCallback((origin, destination) => {
    setRecentSearches(prev => {
      const key = `${origin}→${destination}`;
      const next = [{ origin, destination, key }, ...prev.filter(r => r.key !== key)].slice(0, 5);
      localStorage.setItem("rateiq_recent", JSON.stringify(next));
      return next;
    });
  }, []);
  const fetchLaneMiles = useCallback(async (origin, destination, rawOrigin, rawDest) => {
    const key = `${origin}|${destination}`;
    setLaneMiles(prev => {
      if (prev[key]) return prev; // already fetched or loading
      return { ...prev, [key]: { miles: null, loading: true } };
    });
    try {
      // Use raw (un-normalized) values for accurate geocoding
      const o = encodeURIComponent(rawOrigin || origin);
      const d = encodeURIComponent(rawDest || destination);
      const res = await apiFetch(`${API_BASE}/api/quotes/distance?origin=${o}&destination=${d}`).then(r => r.json());
      setLaneMiles(prev => ({ ...prev, [key]: { miles: res.one_way_miles, loading: false } }));
    } catch {
      setLaneMiles(prev => ({ ...prev, [key]: { miles: null, loading: false } }));
    }
  }, []);
  const originSuggestions = useMemo(() => {
    if (!searchOrigin || searchOrigin.length < 2) return [];
    const q = searchOrigin.toLowerCase();
    const seen = new Set();
    // Check if query matches a port cluster alias — if so, match all ports in that cluster
    const clusterMatch = PORT_CLUSTERS[q] || Object.entries(PORT_CLUSTERS).find(([a]) => a.includes(q) || q.includes(a))?.[1];
    return rateLaneSummaries
      .filter(ls => {
        const p = (ls.port || "").toLowerCase();
        const matches = p.includes(q) || (clusterMatch && normalizeOrigin(ls.port) === clusterMatch);
        // Group by normalized port name
        const normP = normalizeOrigin(ls.port || "").toLowerCase();
        if (!matches || seen.has(normP)) return false;
        seen.add(normP);
        return true;
      })
      .slice(0, 6)
      .map(ls => {
        const normP = normalizeOrigin(ls.port || "");
        const matching = rateLaneSummaries.filter(l => normalizeOrigin(l.port || "") === normP);
        const totalRates = matching.reduce((s, l) => s + l.load_count, 0);
        const avgAll = matching.length > 0 ? Math.round(matching.reduce((s, l) => s + l.avg_rate * l.load_count, 0) / totalRates) : 0;
        return { port: normP, lanes: matching.length, avg: avgAll };
      });
  }, [searchOrigin, rateLaneSummaries]);
  const destSuggestions = useMemo(() => {
    if (!searchDest || searchDest.length < 2) return [];
    const q = searchDest.toLowerCase();
    const seen = new Set();
    const clusterMatch = PORT_CLUSTERS[q] || Object.entries(PORT_CLUSTERS).find(([a]) => a.includes(q) || q.includes(a))?.[1];
    return rateLaneSummaries
      .filter(ls => {
        const d = (ls.destination || "").toLowerCase();
        const matches = d.includes(q) || (clusterMatch && normalizeLaneCity(ls.destination) === clusterMatch);
        const normD = normalizeLaneCity(ls.destination || "").toLowerCase();
        if (!matches || seen.has(normD)) return false;
        seen.add(normD);
        return true;
      })
      .slice(0, 6)
      .map(ls => {
        const normD = normalizeLaneCity(ls.destination || "");
        const matching = rateLaneSummaries.filter(l => normalizeLaneCity(l.destination || "") === normD);
        const totalRates = matching.reduce((s, l) => s + l.load_count, 0);
        const avgAll = matching.length > 0 ? Math.round(matching.reduce((s, l) => s + l.avg_rate * l.load_count, 0) / totalRates) : 0;
        return { destination: normD, lanes: matching.length, avg: avgAll, origin: searchOrigin || matching[0]?.port || "" };
      });
  }, [searchDest, searchOrigin, rateLaneSummaries]);

  // ── Directory state ──
  const [dirSearch, setDirSearch] = useState("");
  const [dirMarket, setDirMarket] = useState("all");
  const [dirCaps, setDirCaps] = useState([]);
  const [dirHideDnu, setDirHideDnu] = useState(true);
  const [dirPort, setDirPort] = useState("all");
  const [dirExpanded, setDirExpanded] = useState(null);
  const [editingCarrierId, setEditingCarrierId] = useState(null);
  const [showAddCarrier, setShowAddCarrier] = useState(false);
  const [newCarrier, setNewCarrier] = useState({ carrier_name: "", mc_number: "", pickup_area: "" });
  const [addCarrierSaving, setAddCarrierSaving] = useState(false);
  const [dirScreenshotFile, setDirScreenshotFile] = useState(null);
  const [dirScreenshotResult, setDirScreenshotResult] = useState(null);
  const [dirScreenshotProcessing, setDirScreenshotProcessing] = useState(false);
  const dirScreenshotRef = useRef(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  // ── Detail navigation ──
  const [laneIndex, setLaneIndex] = useState(0); // for prev/next within grouped results

  const CAP_OPTIONS = [
    { key: "can_hazmat", label: "HAZ", color: "#f87171" },
    { key: "can_overweight", label: "OWT", color: "#FBBF24" },
    { key: "can_reefer", label: "Reefer", color: "#60a5fa" },
    { key: "can_bonded", label: "Bonded", color: "#a78bfa" },
    { key: "can_oog", label: "OOG", color: "#fb923c" },
    { key: "can_transload", label: "Transload", color: "#38bdf8", sync: "can_warehousing" },
  ];

  // ── Carrier capability lookup ──
  const carrierCapMap = useMemo(() => {
    const m = {};
    dirCarriers.forEach(c => {
      m[(c.carrier_name || "").toLowerCase()] = {
        id: c.id, can_hazmat: c.can_hazmat, can_overweight: c.can_overweight, can_reefer: c.can_reefer,
        can_bonded: c.can_bonded, can_oog: c.can_oog, can_warehousing: c.can_warehousing,
        can_transload: c.can_transload, tier_rank: c.tier_rank, dnu: c.dnu, mc_number: c.mc_number,
        contact_email: c.contact_email || c.email, contact_phone: c.contact_phone || c.phone,
      };
    });
    return m;
  }, [dirCarriers]);

  // ── Directory filtering ──
  const allMarkets = useMemo(() => {
    const s = new Set();
    dirCarriers.forEach(c => (c.markets || []).forEach(m => s.add(m)));
    return [...s].sort();
  }, [dirCarriers]);

  const filteredDir = useMemo(() => {
    return dirCarriers.filter(c => {
      if (dirHideDnu && c.dnu) return false;
      if (dirSearch) {
        const q = dirSearch.toLowerCase();
        if (!(c.carrier_name || "").toLowerCase().includes(q) && !(c.mc_number || "").toLowerCase().includes(q) && !(c.contact_email || "").toLowerCase().includes(q)) return false;
      }
      if (dirMarket !== "all" && !(c.markets || []).includes(dirMarket)) return false;
      if (dirPort !== "all") {
        const pg = portGroups.find(g => g.name === dirPort);
        if (pg) {
          const members = pg.members.map(m => m.toLowerCase());
          const areas = ((c.pickup_area || "") + " " + (c.ports || "") + " " + (c.regions || "")).toLowerCase();
          if (!members.some(m => areas.includes(m.split(",")[0]))) return false;
        }
      }
      for (const cap of dirCaps) { if (!c[cap]) return false; }
      return true;
    });
  }, [dirCarriers, dirSearch, dirMarket, dirCaps, dirHideDnu, dirPort, portGroups]);

  // ── Group filtered carriers by region/city for organized geographic browse ──
  const groupedDir = useMemo(() => {
    // Map common market/city names to state for geographic grouping
    const CITY_STATE_MAP = {
      "houston": "TX", "dallas": "TX", "san antonio": "TX", "ft worth": "TX", "fort worth": "TX", "el paso": "TX", "laredo": "TX",
      "los angeles": "CA", "long beach": "CA", "oakland": "CA", "san francisco": "CA",
      "chicago": "IL",
      "savannah": "GA", "atlanta": "GA",
      "new york": "NY", "newark": "NY/NJ", "elizabeth": "NY/NJ", "ny/nj": "NY/NJ",
      "charleston": "SC",
      "norfolk": "VA", "richmond": "VA",
      "baltimore": "MD",
      "boston": "MA",
      "seattle": "WA", "tacoma": "WA",
      "portland": "OR",
      "miami": "FL", "jacksonville": "FL", "tampa": "FL", "port everglades": "FL",
      "new orleans": "LA", "mobile": "AL", "memphis": "TN", "nashville": "TN",
      "charlotte": "NC", "wilmington": "NC",
      "philadelphia": "PA",
      "detroit": "MI",
      "cleveland": "OH", "columbus": "OH", "cincinnati": "OH",
      "indianapolis": "IN",
      "minneapolis": "MN", "st paul": "MN",
      "kansas city": "MO", "st louis": "MO",
      "louisville": "KY",
      "denver": "CO",
      "salt lake city": "UT",
      "phoenix": "AZ",
      "las vegas": "NV",
    };
    const inferState = (c) => {
      // Try pickup_area first (e.g. "Houston, TX")
      if (c.pickup_area) {
        const parts = c.pickup_area.split(",").map(s => s.trim());
        if (parts.length >= 2 && parts[1].length <= 5) return parts[1].toUpperCase();
      }
      // Try markets
      for (const m of (c.markets || [])) {
        const st = CITY_STATE_MAP[m.toLowerCase()];
        if (st) return st;
      }
      return null;
    };
    const inferCity = (c) => {
      if (c.pickup_area) return c.pickup_area.split(",")[0].trim();
      if (c.markets?.length > 0) return c.markets[0];
      return null;
    };

    // Build state → city → carriers hierarchy
    const stateMap = {};
    filteredDir.forEach(c => {
      const state = inferState(c) || "Other";
      const city = inferCity(c) || "Unassigned";
      if (!stateMap[state]) stateMap[state] = { state, cities: {}, totalCarriers: 0, totalTrucks: 0, tierCounts: { 1: 0, 2: 0, 3: 0 } };
      if (!stateMap[state].cities[city]) stateMap[state].cities[city] = [];
      stateMap[state].cities[city].push(c);
      stateMap[state].totalCarriers++;
      if (c.trucks) stateMap[state].totalTrucks += c.trucks;
      if (c.tier_rank >= 1 && c.tier_rank <= 3) stateMap[state].tierCounts[c.tier_rank]++;
    });
    return Object.values(stateMap)
      .map(s => ({
        ...s,
        cities: Object.entries(s.cities)
          .map(([city, carriers]) => ({ city, carriers: carriers.sort((a, b) => (a.tier_rank || 99) - (b.tier_rank || 99)) }))
          .sort((a, b) => b.carriers.length - a.carriers.length),
      }))
      .sort((a, b) => b.totalCarriers - a.totalCarriers);
  }, [filteredDir]);

  const [dirGroupView, setDirGroupView] = useState(true); // default to grouped
  const [expandedMarkets, setExpandedMarkets] = useState({});

  // ── Group lane results by origin ↔ destination (bidirectional, normalized) ──
  // Merges A→B and B→A into a single lane card so round-trip lanes aren't split
  const groupedLanes = useMemo(() => {
    const map = {};
    (Array.isArray(laneResults) ? laneResults : []).forEach(r => {
      const normOrigin = normalizeLaneCity(r.port || "");
      const normDest = normalizeLaneCity(r.destination || "");
      // Bidirectional key: sort endpoints alphabetically so A→B and B→A share a key
      const endpoints = [normOrigin, normDest].sort();
      const biKey = `${endpoints[0]} ↔ ${endpoints[1]}`;
      if (!map[biKey]) map[biKey] = { port: normOrigin, destination: normDest, rawPort: null, rawDest: null, carriers: [], minRate: Infinity, maxRate: 0, total: 0, count: 0, miles: null, origin_zip: null, dest_zip: null, origin_state: null, dest_state: null, moveTypes: {}, directions: {} };
      if (!map[biKey].rawPort && r.port) map[biKey].rawPort = r.port;
      if (!map[biKey].rawDest && r.destination) map[biKey].rawDest = r.destination;
      map[biKey].carriers.push(r);
      if (!map[biKey].miles && r.miles) map[biKey].miles = r.miles;
      if (!map[biKey].origin_zip && r.origin_zip) map[biKey].origin_zip = r.origin_zip;
      if (!map[biKey].dest_zip && r.dest_zip) map[biKey].dest_zip = r.dest_zip;
      if (!map[biKey].origin_state && r.origin_state) map[biKey].origin_state = r.origin_state;
      if (!map[biKey].dest_state && r.dest_state) map[biKey].dest_state = r.dest_state;
      const rate = parseFloat(r.total || r.dray_rate || 0);
      if (rate > 0) { map[biKey].minRate = Math.min(map[biKey].minRate, rate); map[biKey].maxRate = Math.max(map[biKey].maxRate, rate); map[biKey].total += rate; map[biKey].count++; }
      const mt = (r.move_type || "dray").toLowerCase();
      map[biKey].moveTypes[mt] = (map[biKey].moveTypes[mt] || 0) + 1;
      // Track direction counts for display
      const dirKey = `${normOrigin} → ${normDest}`;
      map[biKey].directions[dirKey] = (map[biKey].directions[dirKey] || 0) + 1;
    });
    return Object.values(map).map(g => {
      const mtEntries = Object.entries(g.moveTypes);
      g.move_type = mtEntries.length > 0 ? mtEntries.sort((a, b) => b[1] - a[1])[0][0] : "dray";
      // Use the most common direction as the primary display
      const dirEntries = Object.entries(g.directions);
      if (dirEntries.length > 1) g.bidirectional = true;
      if (dirEntries.length > 0) {
        const primary = dirEntries.sort((a, b) => b[1] - a[1])[0][0];
        const [pOrig, pDest] = primary.split(" → ");
        if (pOrig) g.port = pOrig;
        if (pDest) g.destination = pDest;
      }
      // Dedup carriers: same carrier_name + same total → keep the one with more data
      const seen = {};
      g.carriers = g.carriers.filter(cr => {
        const dk = `${(cr.carrier_name || "").toLowerCase()}|${cr.total || cr.dray_rate || 0}`;
        if (seen[dk]) {
          // Merge: keep whichever has more populated fields
          const prev = seen[dk];
          const prevFields = Object.values(prev).filter(v => v != null && v !== "" && v !== 0).length;
          const curFields = Object.values(cr).filter(v => v != null && v !== "" && v !== 0).length;
          if (curFields > prevFields) { Object.assign(prev, cr); }
          return false;
        }
        seen[dk] = cr;
        return true;
      });
      // Recalculate stats after dedup
      g.count = 0; g.total = 0; g.minRate = Infinity; g.maxRate = 0;
      g.carriers.forEach(cr => {
        const rate = parseFloat(cr.total || cr.dray_rate || 0);
        if (rate > 0) { g.minRate = Math.min(g.minRate, rate); g.maxRate = Math.max(g.maxRate, rate); g.total += rate; g.count++; }
      });
      return g;
    }).sort((a, b) => b.count - a.count);
  }, [laneResults]);

  // ── Group rateLaneSummaries by origin city for collapsible browse view (port-cluster aware) ──
  const originGroups = useMemo(() => {
    const filtered = rateLaneSummaries.filter(ls => moveTypeFilter === "all" || ls.move_type === moveTypeFilter);
    const map = {};
    filtered.forEach(ls => {
      const origin = normalizeOrigin(ls.port || ls.origin_city || "Unknown");
      if (!map[origin]) map[origin] = { origin, lanes: [], totalRate: 0, rateCount: 0, totalLoads: 0 };
      map[origin].lanes.push(ls);
      map[origin].totalLoads += (ls.load_count || 0);
      if (ls.avg_rate > 0) { map[origin].totalRate += ls.avg_rate * (ls.load_count || 1); map[origin].rateCount += (ls.load_count || 1); }
    });
    return Object.values(map)
      .map(g => {
        const avgRate = g.rateCount > 0 ? Math.round(g.totalRate / g.rateCount) : 0;
        // Calculate weighted average miles across lanes for RPM
        let totalMilesWeighted = 0, milesWeightCount = 0;
        g.lanes.forEach(ls => {
          if (ls.miles && ls.miles > 0 && ls.avg_rate > 0) {
            const w = ls.load_count || 1;
            totalMilesWeighted += ls.miles * w;
            milesWeightCount += w;
          }
        });
        const avgMiles = milesWeightCount > 0 ? totalMilesWeighted / milesWeightCount : 0;
        const avgRpm = avgMiles > 0 && avgRate > 0 ? (avgRate / avgMiles).toFixed(2) : null;
        return { ...g, avgRate, avgMiles: Math.round(avgMiles), avgRpm };
      })
      .sort((a, b) => b.totalLoads - a.totalLoads);
  }, [rateLaneSummaries, moveTypeFilter]);

  // ── API: Manual intake — paste email text, AI extracts rate ──
  // ── API: Carrier update ──
  const handleCarrierUpdate = async (carrierId, field, value) => {
    // Sync WHS/Transload — treat as synonyms
    const capDef = CAP_OPTIONS.find(c => c.key === field);
    const updates = { [field]: value };
    if (capDef?.sync) updates[capDef.sync] = value;
    const snapshot = dirCarriers;
    setDirCarriers(prev => prev.map(c => c.id === carrierId ? { ...c, ...updates } : c));
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers/${carrierId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) {
      console.error("Carrier update failed:", e);
      setDirCarriers(snapshot);
      alert(`Failed to update carrier: ${e.message || "server error"}`);
    }
  };

  // ── API: Add carrier ──
  const handleAddCarrier = async () => {
    if (!newCarrier.carrier_name.trim()) return;
    setAddCarrierSaving(true);
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newCarrier, source: "manual" }),
      });
      if (r.ok) {
        const data = await r.json();
        const addedName = (data.carrier || data).carrier_name || newCarrier.carrier_name;
        setDirCarriers(prev => [data.carrier || data, ...prev]);
        setNewCarrier({ carrier_name: "", mc_number: "", pickup_area: "" });
        setShowAddCarrier(false);
        // Clear filters so the newly added carrier is visible
        setDirMarket("all");
        setDirPort("all");
        setDirCaps([]);
        setDirSearch(addedName);
      } else {
        const txt = await r.text().catch(() => "");
        const msg = txt.includes("unique") || txt.includes("duplicate") ? "MC# already exists in directory" : `Save failed (${r.status})`;
        alert(msg);
      }
    } catch (e) { console.error("Add carrier failed:", e); alert(`Failed to add carrier: ${e.message || "server error"}`); }
    setAddCarrierSaving(false);
  };

  // ── API: Delete carrier ──
  const handleDeleteCarrier = async (carrierId) => {
    try {
      const r = await apiFetch(`${API_BASE}/api/carriers/${carrierId}`, { method: "DELETE" });
      if (r.ok) {
        setDirCarriers(prev => prev.filter(c => c.id !== carrierId));
        setDeleteConfirm(null);
        setEditingCarrierId(null);
      }
    } catch (e) { console.error("Delete carrier failed:", e); }
  };

  // ── API: LoadMatch screenshot import ──
  const handleDirScreenshot = async () => {
    if (!dirScreenshotFile) return;
    setDirScreenshotProcessing(true);
    setDirScreenshotResult(null);
    try {
      const formData = new FormData();
      formData.append("file", dirScreenshotFile);
      const r = await apiFetch(`${API_BASE}/api/carriers/extract`, { method: "POST", body: formData });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setDirScreenshotResult(data);
      // If carriers were extracted and saved, refresh directory
      if (data.carriers?.length > 0 || data.saved?.length > 0) {
        const res = await apiFetch(`${API_BASE}/api/carriers?exclude_dnu=false`);
        if (res.ok) { const d = await res.json(); setDirCarriers(d.carriers || d || []); }
      }
    } catch (e) {
      setDirScreenshotResult({ error: e.message || "Screenshot extraction failed" });
    }
    setDirScreenshotProcessing(false);
  };

  // ── API: Lane rate update ──
  const handleLaneRateUpdate = async (rateId, field, value) => {
    const numVal = value === "" || value === null ? null : parseFloat(value);
    setLaneResults(prev => prev.map(r => ({
      ...r, carriers: (r.carriers || []).map(cr => cr.id === rateId ? { ...cr, [field]: numVal } : cr),
    })));
    try {
      const r = await apiFetch(`${API_BASE}/api/lane-rates/${rateId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: numVal }),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) { console.error("Lane rate update failed:", e); }
    setEditingLaneRateId(null);
    setEditingLaneField(null);
  };

  const handleDeleteLaneRate = async (rateId) => {
    try {
      const r = await apiFetch(`${API_BASE}/api/lane-rates/${rateId}`, { method: "DELETE" });
      if (r.ok) {
        setLaneResults(prev => prev.filter(r => r.id !== rateId));
        return true;
      }
    } catch (e) { console.error("Lane rate delete failed:", e); }
    return false;
  };

  // ── Update carrier directory info (MC#, email) from lane card ──
  const handleUpdateCarrierInfo = useCallback(async (carrierName, field, value) => {
    const key = (carrierName || "").toLowerCase();
    const existing = carrierCapMap[key];
    try {
      if (existing?.id) {
        // Update existing carrier in directory
        await apiFetch(`${API_BASE}/api/carriers/${existing.id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: value || null }),
        });
      } else {
        // Create new carrier in directory
        await apiFetch(`${API_BASE}/api/carriers`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ carrier_name: carrierName, [field]: value || null, source: "rate_card" }),
        });
      }
      // Refresh carriers to update capMap
      const res = await apiFetch(`${API_BASE}/api/carriers`).then(r => r.json());
      setDirCarriers(res.carriers || res || []);
    } catch (e) { console.error("Carrier info update failed:", e); }
  }, [carrierCapMap]);

  // ── API: Fetch all data ──
  const fetchData = useCallback(async () => {
    try {
      const [rateRes, perfRes, laneRes, carrierRes, pgRes, laneRatesRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/rate-iq`).then(r => r.json()),
        apiFetch(`${API_BASE}/api/carriers/scorecard`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/lane-stats`).then(r => r.json()).catch(() => ({ lanes: [] })),
        apiFetch(`${API_BASE}/api/carriers?include_lanes=true`).then(r => r.json()).catch(() => ({ carriers: [] })),
        apiFetch(`${API_BASE}/api/port-groups`).then(r => r.json()).catch(() => ({ groups: [] })),
        apiFetch(`${API_BASE}/api/lane-rates${moveTypeFilter && moveTypeFilter !== "all" ? `?move_type=${moveTypeFilter}` : ""}`).then(r => r.json()).catch(() => ({ lane_rates: [] })),
      ]);
      setData(rateRes);
      setScorecardPerf(perfRes.carriers || []);
      setLaneStats(laneRes.lanes || []);
      setDirCarriers(carrierRes.carriers || carrierRes || []);
      setPortGroups(pgRes.groups || []);

      // Build lane summaries from rate data (with trend detection + port cluster normalization)
      const allRates = laneRatesRes.lane_rates || (Array.isArray(laneRatesRes) ? laneRatesRes : []);
      const now = Date.now();
      const thirtyDaysAgo = now - 30 * 86400000;
      const laneMap = {};
      allRates.forEach(r => {
        const normPort = normalizeLaneCity(r.port || "");
        const normDest = normalizeLaneCity(r.destination || "");
        const key = `${normPort}|${normDest}`;
        if (!laneMap[key]) laneMap[key] = { port: normPort, destination: normDest, rawPort: r.port || "", rawDest: r.destination || "", count: 0, totalRate: 0, carriers: new Set(), rawRates: [], recentTotal: 0, recentCount: 0, olderTotal: 0, olderCount: 0, miles: null, origin_zip: null, dest_zip: null, origin_state: null, dest_state: null, moveTypes: {} };
        laneMap[key].rawRates.push(r);
        if (!laneMap[key].miles && r.miles) laneMap[key].miles = r.miles;
        if (!laneMap[key].origin_zip && r.origin_zip) laneMap[key].origin_zip = r.origin_zip;
        if (!laneMap[key].dest_zip && r.dest_zip) laneMap[key].dest_zip = r.dest_zip;
        if (!laneMap[key].origin_state && r.origin_state) laneMap[key].origin_state = r.origin_state;
        if (!laneMap[key].dest_state && r.dest_state) laneMap[key].dest_state = r.dest_state;
        laneMap[key].count++;
        const rate = parseFloat(r.total || r.dray_rate || 0);
        if (rate > 0) {
          laneMap[key].totalRate += rate;
          const ts = r.created_at ? new Date(r.created_at).getTime() : 0;
          if (ts >= thirtyDaysAgo) { laneMap[key].recentTotal += rate; laneMap[key].recentCount++; }
          else { laneMap[key].olderTotal += rate; laneMap[key].olderCount++; }
        }
        if (r.carrier_name) laneMap[key].carriers.add(r.carrier_name);
        const mt = (r.move_type || "dray").toLowerCase();
        laneMap[key].moveTypes[mt] = (laneMap[key].moveTypes[mt] || 0) + 1;
      });
      const summaries = Object.values(laneMap)
        .filter(l => l.port && l.destination)
        .map(l => {
          const avg_rate = l.count > 0 ? Math.round(l.totalRate / l.count) : 0;
          const recentAvg = l.recentCount > 0 ? l.recentTotal / l.recentCount : null;
          const olderAvg = l.olderCount > 0 ? l.olderTotal / l.olderCount : null;
          const trend_pct = (recentAvg && olderAvg && olderAvg > 0) ? ((recentAvg - olderAvg) / olderAvg) * 100 : null;
          // Determine primary move type (most common across rates for this lane)
          const mtEntries = Object.entries(l.moveTypes);
          const primary_move_type = mtEntries.length > 0 ? mtEntries.sort((a, b) => b[1] - a[1])[0][0] : "dray";
          return { port: l.port, destination: l.destination, rawPort: l.rawPort, rawDest: l.rawDest, load_count: l.count, avg_rate, carrier_count: l.carriers.size, trend_pct, miles: l.miles, origin_zip: l.origin_zip, dest_zip: l.dest_zip, origin_state: l.origin_state, dest_state: l.dest_state, move_type: primary_move_type, rawRates: l.rawRates };
        })
        .sort((a, b) => b.load_count - a.load_count);
      setRateLaneSummaries(summaries);
    } catch (e) { console.error("Rate IQ fetch:", e); }
    setLoading(false);
  }, [moveTypeFilter]);

  useEffect(() => { fetchData(); const iv = setInterval(fetchData, 60000); return () => clearInterval(iv); }, [fetchData]);

  // ── Fetch market benchmark for current lane search ──
  const fetchMarketBenchmark = useCallback(async (o, d) => {
    if (!o && !d) { setMarketBenchmark(null); return; }
    try {
      const params = new URLSearchParams();
      if (o) params.set("origin", o);
      if (d) params.set("destination", d);
      const res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates?${params.toString()}`).then(r => r.json());
      setMarketBenchmark(res.stats ? { stats: res.stats, rates: res.rates } : null);
    } catch { setMarketBenchmark(null); }
  }, []);

  // ── Lane search ──
  const searchLanes = useCallback(async (origin, dest) => {
    const o = origin ?? searchOrigin;
    const d = dest ?? searchDest;
    if (!o && !d) return;
    setLaneSearching(true);
    try {
      const params = new URLSearchParams();
      if (o) params.set("port", o);
      if (d) params.set("destination", d);
      if (moveTypeFilter && moveTypeFilter !== "all") params.set("move_type", moveTypeFilter);
      const res = await apiFetch(`${API_BASE}/api/lane-rates?${params.toString()}`).then(r => r.json());
      setLaneResults(res.lane_rates || (Array.isArray(res) ? res : []));
      fetchMarketBenchmark(o, d);
    } catch (e) { console.error("Lane search:", e); setLaneResults([]); }
    setLaneSearching(false);
  }, [searchOrigin, searchDest, moveTypeFilter, fetchMarketBenchmark]);

  // Debounced auto-search: fires 400ms after user stops typing (browse view only)
  const viewRef = useRef(view);
  viewRef.current = view;
  useEffect(() => {
    if (viewRef.current === "detail") return; // Don't re-fetch when navigating to detail with existing data
    if (!searchOrigin && !searchDest) {
      // User cleared both fields — reset results immediately
      setLaneResults([]);
      return;
    }
    const timer = setTimeout(() => {
      searchLanes();
      if (searchOrigin && searchDest) saveRecent(searchOrigin, searchDest);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchOrigin, searchDest, moveTypeFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── API: Manual intake — paste email text OR upload file, AI extracts rate ──
  const handleManualIntake = useCallback(async (file) => {
    const f = file || intakeFile;
    if (!intakeText.trim() && !f) return;
    setIntakeProcessing(true);
    setIntakeResult(null);
    setIntakePreview(null);
    try {
      let res;
      if (f) {
        const formData = new FormData();
        formData.append("file", f);
        formData.append("move_type", intakeMoveType);
        if (intakeText.trim()) formData.append("text", intakeText);
        res = await apiFetch(`${API_BASE}/api/rate-iq/extract-preview`, { method: "POST", body: formData });
      } else {
        res = await apiFetch(`${API_BASE}/api/rate-iq/extract-preview`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: intakeText, move_type: intakeMoveType }),
        });
      }
      const data = await res.json();
      if (res.ok && data.ok) {
        setIntakePreview(data.extracted);
        setIntakeText("");
        setIntakeFile(null);
      } else {
        setIntakeResult({ error: data.error || "Extraction failed", extracted: data.extracted });
      }
    } catch (e) {
      setIntakeResult({ error: e.message });
    }
    setIntakeProcessing(false);
  }, [intakeText, intakeFile, intakeMoveType]);

  const handleIntakeSave = useCallback(async () => {
    if (!intakePreview) return;
    setIntakeSaving(true);
    setIntakeResult(null);
    try {
      const res = await apiFetch(`${API_BASE}/api/rate-iq/manual-intake`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ extracted: intakePreview, move_type: intakePreview.shipment_type || intakeMoveType }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setIntakeResult({ ok: true, extracted: data.extracted, duplicate_skipped: data.duplicate_skipped });
        setIntakePreview(null);
        fetchData();
      } else {
        setIntakeResult({ error: data.error || "Save failed" });
      }
    } catch (e) {
      setIntakeResult({ error: e.message });
    }
    setIntakeSaving(false);
  }, [intakePreview, intakeMoveType, fetchData]);

  // ── API: Market rates — paste text OR upload screenshot ──
  const handleMarketRatePaste = useCallback(async (file) => {
    const f = file || marketRateFile;
    if (!marketRateText.trim() && !f) return;
    if (!f && (!marketRateOrigin.trim() || !marketRateDest.trim())) return;
    setMarketRateProcessing(true);
    setMarketRateResult(null);
    try {
      let res;
      if (f) {
        const formData = new FormData();
        formData.append("file", f);
        if (marketRateOrigin.trim()) formData.append("origin", marketRateOrigin);
        if (marketRateDest.trim()) formData.append("destination", marketRateDest);
        formData.append("move_type", marketRateMoveType);
        if (marketRateText.trim()) formData.append("text", marketRateText);
        res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates`, { method: "POST", body: formData });
      } else {
        res = await apiFetch(`${API_BASE}/api/rate-iq/market-rates`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ origin: marketRateOrigin, destination: marketRateDest, move_type: marketRateMoveType, text: marketRateText }),
        });
      }
      const data = await res.json();
      if (res.ok && data.ok) {
        setMarketRateResult({ ok: true, inserted: data.inserted, skipped: data.skipped });
        setMarketRateText("");
        setMarketRateFile(null);
        // Auto-refresh benchmark if we have an active lane search
        if (searchOrigin || searchDest) fetchMarketBenchmark(searchOrigin, searchDest);
      } else {
        setMarketRateResult({ error: data.error || "Parse failed", errors: data.errors });
      }
    } catch (e) {
      setMarketRateResult({ error: e.message });
    }
    setMarketRateProcessing(false);
  }, [marketRateOrigin, marketRateDest, marketRateMoveType, marketRateText, marketRateFile, searchOrigin, searchDest, fetchMarketBenchmark]);

  // ── API: Reclassify lane move type (bulk update all rates in a lane) ──
  const [dragOverType, setDragOverType] = useState(null);
  const handleReclassifyLane = useCallback(async (port, destination, rateIds, newMoveType) => {
    if (!rateIds?.length && !port) return;
    if (rateIds?.length) {
      await Promise.all(rateIds.map(id =>
        apiFetch(`${API_BASE}/api/lane-rates/${id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ move_type: newMoveType }),
        }).catch(e => console.error("Reclassify failed for", id, e))
      ));
    } else {
      const res = await apiFetch(`${API_BASE}/api/lane-rates?port=${encodeURIComponent(port)}&destination=${encodeURIComponent(destination)}`).then(r => r.json());
      const ids = (res.lane_rates || []).map(r => r.id);
      await Promise.all(ids.map(id =>
        apiFetch(`${API_BASE}/api/lane-rates/${id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ move_type: newMoveType }),
        }).catch(e => console.error("Reclassify failed for", id, e))
      ));
    }
    fetchData();
    if (searchOrigin || searchDest) searchLanes();
  }, [fetchData, searchLanes, searchOrigin, searchDest]);

  const handleMoveTypeDrop = useCallback((e, targetType) => {
    e.preventDefault();
    setDragOverType(null);
    try {
      const data = JSON.parse(e.dataTransfer.getData("application/json"));
      if (data.port || data.destination) {
        handleReclassifyLane(data.port, data.destination, data.rateIds, targetType);
      }
    } catch (err) { console.error("Drop parse error:", err); }
  }, [handleReclassifyLane]);

  // ── Navigate to lane detail ──
  const openLaneDetail = useCallback(async (origin, destination, idx = 0, existingCarriers = null) => {
    setSelectedLane({ origin, destination });
    setSearchOrigin(origin || "");
    setSearchDest(destination || "");
    setLaneIndex(idx);
    setView("detail");
    if (origin && destination) saveRecent(origin, destination);
    // If we already have carrier data from the grouped search results, use it directly
    if (existingCarriers && existingCarriers.length > 0) {
      setLaneResults(existingCarriers);
      fetchMarketBenchmark(origin, destination);
      return;
    }
    // Otherwise fetch from API — use raw origin/dest for query
    setLaneSearching(true);
    try {
      const params = new URLSearchParams();
      if (origin) params.set("port", origin);
      if (destination) params.set("destination", destination);
      if (moveTypeFilter && moveTypeFilter !== "all") params.set("move_type", moveTypeFilter);
      const res = await apiFetch(`${API_BASE}/api/lane-rates?${params.toString()}`).then(r => r.json());
      setLaneResults(res.lane_rates || (Array.isArray(res) ? res : []));
      fetchMarketBenchmark(origin, destination);
    } catch (e) { console.error("Lane search:", e); setLaneResults([]); }
    setLaneSearching(false);
  }, [moveTypeFilter, fetchMarketBenchmark]);

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#8B95A8" }}>Loading Rate IQ...</div>;

  // ═════════════════════════════════════════════════════════════
  // BROWSE VIEW — Lane search landing page
  // ═════════════════════════════════════════════════════════════
  if (view === "browse") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate IQ</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
              {data?.total_rate_quotes || 0} quotes | {data?.total_carrier_quotes || 0} carrier emails | {rateLaneSummaries.length} lanes with rates
            </div>
          </div>
          {/* Secondary nav */}
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { key: "intake", label: "Rate Intake", icon: "📥" },
              { key: "oog", label: "OOG IQ", icon: "📦" },
              { key: "directory", label: `Directory (${dirCarriers.length})`, icon: "📖" },
              { key: "scorecard", label: "Scorecard", icon: "🏆" },
              { key: "history", label: "History", icon: "📊" },
            ].map(t => (
              <button key={t.key} onClick={() => setView(t.key)}
                style={{ padding: "6px 14px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#8B95A8", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 4 }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = "rgba(0,212,170,0.3)"; e.currentTarget.style.color = "#F0F2F5"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; e.currentTarget.style.color = "#8B95A8"; }}>
                <span style={{ fontSize: 12 }}>{t.icon}</span> {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Search Bar */}
        <div className="glass" style={{ borderRadius: 14, padding: "20px 24px", marginBottom: 24, border: "1px solid rgba(255,255,255,0.06)" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12 }}>SEARCH LANES</div>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
            <div style={{ flex: 1, position: "relative" }} ref={originRef}>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Origin / Port</label>
              <input value={searchOrigin} onChange={e => setSearchOrigin(e.target.value)} placeholder="e.g. Houston, NYNJ, Savannah..."
                style={{ width: "100%", padding: "10px 16px", borderRadius: 10, border: `1px solid ${originFocused ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 13, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onFocus={() => setOriginFocused(true)} onBlur={() => setTimeout(() => setOriginFocused(false), 150)} />
              {originFocused && originSuggestions.length > 0 && (
                <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, marginTop: 4, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "#151922", boxShadow: "0 12px 32px rgba(0,0,0,0.5)", overflow: "hidden" }}>
                  {originSuggestions.map((s, i) => (
                    <div key={i} onClick={() => { setSearchOrigin(s.port); setOriginFocused(false); }}
                      style={{ padding: "10px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: i < originSuggestions.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none", transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "#F0F2F5" }}>{s.port}</span>
                      <span style={{ fontSize: 11, color: "#5A6478" }}>{s.lanes} lane{s.lanes !== 1 ? "s" : ""} · {fmt(s.avg)} avg</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ fontSize: 18, color: "#5A6478", padding: "0 4px 10px" }}>→</div>
            <div style={{ flex: 1, position: "relative" }} ref={destRef}>
              <label style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 4 }}>Destination</label>
              <input value={searchDest} onChange={e => setSearchDest(e.target.value)} placeholder="e.g. Dallas, Chicago..."
                style={{ width: "100%", padding: "10px 16px", borderRadius: 10, border: `1px solid ${destFocused ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 13, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                onFocus={() => setDestFocused(true)} onBlur={() => setTimeout(() => setDestFocused(false), 150)} />
              {destFocused && destSuggestions.length > 0 && (
                <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, marginTop: 4, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "#151922", boxShadow: "0 12px 32px rgba(0,0,0,0.5)", overflow: "hidden" }}>
                  {destSuggestions.map((s, i) => (
                    <div key={i} onClick={() => { setSearchDest(s.destination); setDestFocused(false); }}
                      style={{ padding: "10px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: i < destSuggestions.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none", transition: "background 0.1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div>
                        <span style={{ fontSize: 13, fontWeight: 600, color: "#F0F2F5" }}>{searchOrigin || "•"} → {s.destination}</span>
                      </div>
                      <span style={{ fontSize: 11, color: "#5A6478" }}>{fmt(s.avg)} avg</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {laneSearching && (
              <div style={{ padding: "10px 0", color: "#5A6478", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>Searching...</div>
            )}
          </div>

          {/* Recent Searches */}
          {recentSearches.length > 0 && !searchOrigin && !searchDest && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12, alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", marginRight: 4 }}>Recent:</span>
              {recentSearches.map((r, i) => (
                <button key={i} onClick={() => { setSearchOrigin(r.origin); setSearchDest(r.destination); setTimeout(() => searchLanes(r.origin, r.destination), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(59,130,246,0.15)", background: "rgba(59,130,246,0.06)", color: "#60a5fa", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(59,130,246,0.12)"; e.currentTarget.style.borderColor = "rgba(59,130,246,0.3)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "rgba(59,130,246,0.06)"; e.currentTarget.style.borderColor = "rgba(59,130,246,0.15)"; }}>
                  {r.origin} → {r.destination}
                </button>
              ))}
            </div>
          )}

          {/* Port Group Quick Filters */}
          {portGroups.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", marginRight: 4 }}>Quick:</span>
              {portGroups.filter(g => !g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setSearchOrigin(g.name); setSearchDest(""); setTimeout(() => searchLanes(g.name, ""), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(0,212,170,0.15)", background: searchOrigin === g.name ? "rgba(0,212,170,0.10)" : "rgba(255,255,255,0.02)", color: searchOrigin === g.name ? "#00D4AA" : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
              {portGroups.filter(g => g.is_rail).length > 0 && <span style={{ color: "#2D3340", margin: "0 4px" }}>|</span>}
              {portGroups.filter(g => g.is_rail).map(g => (
                <button key={g.name} onClick={() => { setSearchOrigin(g.name); setSearchDest(""); setTimeout(() => searchLanes(g.name, ""), 50); }}
                  style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(167,139,250,0.15)", background: searchOrigin === g.name ? "rgba(167,139,250,0.10)" : "rgba(255,255,255,0.02)", color: searchOrigin === g.name ? "#A78BFA" : "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}>
                  {g.name}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Move Type Filter */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {[
            { key: "all", label: "All Types" },
            { key: "dray", label: "Dray", color: "#60a5fa" },
            { key: "ftl", label: "FTL", color: "#FBBF24" },
            { key: "transload", label: "Transload", color: "#a78bfa" },
          ].map(t => {
            const active = moveTypeFilter === t.key;
            const c = t.color || "#8B95A8";
            const isDropTarget = t.key !== "all" && dragOverType === t.key;
            return (
              <button key={t.key} onClick={() => setMoveTypeFilter(t.key)}
                onDragOver={t.key !== "all" ? (e => { e.preventDefault(); setDragOverType(t.key); }) : undefined}
                onDragLeave={t.key !== "all" ? (() => setDragOverType(null)) : undefined}
                onDrop={t.key !== "all" ? (e => handleMoveTypeDrop(e, t.key)) : undefined}
                style={{ padding: "5px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8,
                  border: `1px solid ${isDropTarget ? (t.color || "#00D4AA") : active ? (t.color ? t.color + "55" : "rgba(0,212,170,0.3)") : "rgba(255,255,255,0.06)"}`,
                  background: isDropTarget ? (t.color ? t.color + "30" : "rgba(0,212,170,0.20)") : active ? (t.color ? t.color + "18" : "rgba(0,212,170,0.08)") : "transparent",
                  color: active || isDropTarget ? (t.color || "#00D4AA") : "#5A6478", cursor: "pointer", fontFamily: "inherit",
                  transition: "all 0.15s", transform: isDropTarget ? "scale(1.08)" : "scale(1)" }}>
                {isDropTarget ? `→ ${t.label}` : t.label}
              </button>
            );
          })}
        </div>

        {/* Search Results */}
        {groupedLanes.filter(g => moveTypeFilter === "all" || g.move_type === moveTypeFilter).length > 0 && (
          <div style={{ marginBottom: 24 }}>
            {(() => { const filtered = groupedLanes.filter(g => moveTypeFilter === "all" || g.move_type === moveTypeFilter); return <>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12 }}>
              SEARCH RESULTS — {filtered.length} lane{filtered.length !== 1 ? "s" : ""}{moveTypeFilter !== "all" ? ` (${moveTypeFilter.toUpperCase()})` : ""}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 12 }}>
              {filtered.map((group, gi) => {
                const mKey = `${group.port}|${group.destination}`;
                const resolvedMiles = group.miles || laneMiles[mKey]?.miles || null;
                if (!resolvedMiles && !laneMiles[mKey] && group.port && group.destination) {
                  fetchLaneMiles(group.port, group.destination, group.rawPort || group.port, group.rawDest || group.destination);
                }
                return <LaneCard key={gi} lane={{
                  origin_city: group.port, dest_city: group.destination, port: group.rawPort || group.port, destination: group.rawDest || group.destination,
                  origin_state: group.origin_state, dest_state: group.dest_state,
                  load_count: group.count, avg_rate: group.count > 0 ? Math.round(group.total / group.count) : 0,
                  carrier_count: group.carriers.length,
                  miles: resolvedMiles, origin_zip: group.origin_zip, dest_zip: group.dest_zip,
                  move_type: group.move_type,
                  bidirectional: group.bidirectional,
                }} onClick={() => openLaneDetail(group.port, group.destination, gi, group.carriers)}
                  rateIds={(group.carriers || []).map(c => c.id).filter(Boolean)}
                  onReclassify={mt => handleReclassifyLane(group.port, group.destination, (group.carriers || []).map(c => c.id).filter(Boolean), mt)}
                  onQuickQuote={() => { setSelectedLane({ origin: group.port, destination: group.destination }); setView("build-quote"); }} />;
              })}
            </div>
            </>; })()}
          </div>
        )}

        {/* Lane Analysis — grouped by origin, collapsible */}
        {originGroups.length > 0 && groupedLanes.length === 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
              LANE ANALYSIS
              <span style={{ fontSize: 11, color: "#5A6478", fontWeight: 500 }}>— {originGroups.length} origin{originGroups.length !== 1 ? "s" : ""}, {originGroups.reduce((s, g) => s + g.lanes.length, 0)} lanes{moveTypeFilter !== "all" ? ` (${moveTypeFilter.toUpperCase()})` : ""}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {originGroups.map(group => {
                const isOpen = !!expandedOrigins[group.origin];
                return (
                  <div key={group.origin} className="glass" style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", overflow: "hidden" }}>
                    {/* Origin header row */}
                    <div onClick={() => {
                        const wasOpen = !!expandedOrigins[group.origin];
                        setExpandedOrigins(prev => ({ ...prev, [group.origin]: !prev[group.origin] }));
                        if (!wasOpen) {
                          group.lanes.forEach(ls => {
                            if (!ls.miles && ls.destination) {
                              // Use raw (un-normalized) values for accurate distance lookup
                              const rawO = ls.rawPort || group.origin;
                              const rawD = ls.rawDest || ls.destination;
                              const key = `${group.origin}|${ls.destination}`;
                              if (!laneMiles[key]) fetchLaneMiles(group.origin, ls.destination, rawO, rawD);
                            }
                          });
                        }
                      }}
                      style={{ padding: "14px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", transition: "background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <span style={{ fontSize: 12, color: "#5A6478", transform: isOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s", display: "inline-block" }}>▼</span>
                        <div>
                          <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5" }}>{group.origin}</div>
                          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 1 }}>
                            {group.lanes.length} lane{group.lanes.length !== 1 ? "s" : ""} · {group.totalLoads} rate{group.totalLoads !== 1 ? "s" : ""} on file
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                        {group.avgRpm && (
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>${group.avgRpm}</div>
                            <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 600 }}>avg rpm</div>
                          </div>
                        )}
                        {group.avgRate > 0 && (
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 18, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(group.avgRate)}</div>
                            <div style={{ fontSize: 10, color: "#5A6478", fontWeight: 600 }}>avg rate</div>
                          </div>
                        )}
                      </div>
                    </div>
                    {/* Expanded lanes */}
                    {isOpen && (
                      <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                        {group.lanes
                          .sort((a, b) => (b.load_count || 0) - (a.load_count || 0))
                          .map((ls, li) => {
                            const avgRate = ls.avg_rate || ls.average || 0;
                            const mtStyle = MOVE_TYPE_STYLES[(ls.move_type || "dray").toLowerCase()] || MOVE_TYPE_STYLES.dray;
                            return (
                              <div key={li} onClick={() => openLaneDetail(ls.port, ls.destination, 0, ls.rawRates)}
                                style={{ padding: "12px 20px 12px 44px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.03)", transition: "background 0.1s" }}
                                onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                  <span style={{ fontSize: 13, color: "#C8D0DC", fontWeight: 600 }}>→ {ls.destination || ls.dest_city || "—"}{ls.dest_state ? <span style={{ color: "#5A6478", fontSize: 11, fontWeight: 500, marginLeft: 3 }}>{ls.dest_state}</span> : null}</span>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: mtStyle.bg, color: mtStyle.color, border: `1px solid ${mtStyle.border}` }}>{mtStyle.label}</span>
                                  <span style={{ fontSize: 11, color: "#5A6478" }}>{ls.load_count || 0} rate{(ls.load_count || 0) !== 1 ? "s" : ""}</span>
                                  {ls.carrier_count > 0 && <span style={{ fontSize: 11, color: "#5A6478" }}>{ls.carrier_count} carrier{ls.carrier_count !== 1 ? "s" : ""}</span>}
                                  {(() => {
                                    const mKey = `${group.origin}|${ls.destination}`;
                                    const m = ls.miles || (laneMiles[mKey] && laneMiles[mKey].miles);
                                    if (m > 0) return <span style={{ fontSize: 11, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{m.toLocaleString()} mi</span>;
                                    if (laneMiles[mKey]?.loading) return <span style={{ fontSize: 11, color: "#5A6478" }}>...</span>;
                                    return null;
                                  })()}
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                  {ls.trend_pct != null && Math.abs(ls.trend_pct) > 2 && (
                                    <span style={{ fontSize: 11, fontWeight: 700, color: ls.trend_pct > 0 ? "#f87171" : "#34d399" }}>
                                      {ls.trend_pct > 0 ? "↑" : "↓"} {Math.abs(ls.trend_pct).toFixed(1)}%
                                    </span>
                                  )}
                                  {(() => {
                                    const mKey = `${group.origin}|${ls.destination}`;
                                    const mi = ls.miles || (laneMiles[mKey] && laneMiles[mKey].miles);
                                    if (mi > 0 && avgRate > 0) return <span style={{ fontSize: 11, fontWeight: 600, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>${(avgRate / mi).toFixed(2)}/mi</span>;
                                    return null;
                                  })()}
                                  {avgRate > 0 && (
                                    <span style={{ fontSize: 15, fontWeight: 800, color: "#34d399", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(avgRate)}</span>
                                  )}
                                  <span style={{ fontSize: 11, color: "#5A6478" }}>→</span>
                                </div>
                              </div>
                            );
                          })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {rateLaneSummaries.length === 0 && groupedLanes.length === 0 && !laneSearching && (
          <div style={{ padding: 60, textAlign: "center", color: "#5A6478" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#F0F2F5" }}>Search for a lane to get started</div>
            <div style={{ fontSize: 12, marginTop: 6 }}>Enter an origin and destination above, or click a port quick filter</div>
          </div>
        )}
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // DETAIL VIEW — Lane rate intelligence (DrayRates-inspired)
  // ═════════════════════════════════════════════════════════════
  if (view === "detail") {
    const currentGroup = groupedLanes[laneIndex] || groupedLanes[0] || null;
    const laneName = selectedLane ? `${selectedLane.origin || "—"} → ${selectedLane.destination || "—"}` : "—";

    return (
      <div style={{ padding: "0 24px 24px" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <button onClick={() => setView("browse")}
              style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}
              onMouseEnter={e => e.currentTarget.style.color = "#F0F2F5"} onMouseLeave={e => e.currentTarget.style.color = "#8B95A8"}>
              ←
            </button>
            <div>
              <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>{laneName}</h2>
              {currentGroup && (
                <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>
                  {currentGroup.carriers.length} carrier rate{currentGroup.carriers.length !== 1 ? "s" : ""} on file
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {/* Prev / Next */}
            {groupedLanes.length > 1 && (
              <div style={{ display: "flex", gap: 4, marginRight: 8 }}>
                <button disabled={laneIndex <= 0} onClick={() => { const ni = laneIndex - 1; setLaneIndex(ni); const g = groupedLanes[ni]; if (g) setSelectedLane({ origin: g.port, destination: g.destination }); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: laneIndex > 0 ? "#F0F2F5" : "#2D3340", fontSize: 11, fontWeight: 600, cursor: laneIndex > 0 ? "pointer" : "default", fontFamily: "inherit" }}>
                  ← Previous
                </button>
                <button disabled={laneIndex >= groupedLanes.length - 1} onClick={() => { const ni = laneIndex + 1; setLaneIndex(ni); const g = groupedLanes[ni]; if (g) setSelectedLane({ origin: g.port, destination: g.destination }); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: laneIndex < groupedLanes.length - 1 ? "#F0F2F5" : "#2D3340", fontSize: 11, fontWeight: 600, cursor: laneIndex < groupedLanes.length - 1 ? "pointer" : "default", fontFamily: "inherit" }}>
                  Next →
                </button>
              </div>
            )}
            <button onClick={() => setView("build-quote")}
              style={{ padding: "8px 20px", borderRadius: 10, border: "none", background: grad, color: "#0A0F1C", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 6 }}>
              Build Quote
            </button>
          </div>
        </div>

        {laneSearching && <div style={{ padding: 40, textAlign: "center", color: "#5A6478" }}>Searching lane rates...</div>}

        {!laneSearching && currentGroup && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20 }}>
            {/* Left column — Market Rate + Carrier Table */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <MarketRateCard laneGroup={currentGroup} carrierCapMap={carrierCapMap} />

              {marketBenchmark && <MarketBenchmarkCard benchmark={marketBenchmark} carrierAvg={currentGroup.count > 0 ? Math.round(currentGroup.total / currentGroup.count) : 0} />}

              {/* Cost Analysis */}
              <div className="glass" style={{ borderRadius: 14, padding: "18px 24px", border: "1px solid rgba(255,255,255,0.06)" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 16 }}>COST ANALYSIS</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Avg Carrier Cost</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>
                      {fmt(currentGroup.count > 0 ? Math.round(currentGroup.total / currentGroup.count) : 0)}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>based on {currentGroup.count} data point{currentGroup.count !== 1 ? "s" : ""}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Floor Rate</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#60a5fa", fontFamily: "'JetBrains Mono', monospace" }}>
                      {currentGroup.minRate !== Infinity ? fmt(currentGroup.minRate) : "—"}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>lowest on file</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "#5A6478", fontWeight: 600, marginBottom: 4 }}>Ceiling Rate</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: "#fb923c", fontFamily: "'JetBrains Mono', monospace" }}>
                      {currentGroup.maxRate > 0 ? fmt(currentGroup.maxRate) : "—"}
                    </div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>highest on file</div>
                  </div>
                </div>
              </div>

              <CarrierRateTable
                carriers={currentGroup.carriers}
                carrierCapMap={carrierCapMap}
                editingLaneRateId={editingLaneRateId} editingLaneField={editingLaneField} editingLaneValue={editingLaneValue}
                setEditingLaneRateId={setEditingLaneRateId} setEditingLaneField={setEditingLaneField} setEditingLaneValue={setEditingLaneValue}
                handleLaneRateUpdate={handleLaneRateUpdate}
                laneOrigin={currentGroup.port} laneDestination={currentGroup.destination}
                miles={currentGroup.miles || laneMiles[`${currentGroup.port}|${currentGroup.destination}`]?.miles}
                moveType={currentGroup.move_type || "dray"}
                onUpdateCarrierInfo={handleUpdateCarrierInfo}
                onDeleteRate={handleDeleteLaneRate}
                onUseRate={(cr) => {
                  // Build linehaul items from carrier rate fields
                  const items = [];
                  if (cr.dray_rate) items.push({ description: "Linehaul", rate: String(cr.dray_rate) });
                  if (cr.fsc) items.push({ description: "Fuel Surcharge", rate: String(cr.fsc) });
                  if (cr.prepull) items.push({ description: "Pre-Pull", rate: String(cr.prepull) });
                  if (cr.chassis_per_day) items.push({ description: "Chassis", rate: String(cr.chassis_per_day) });
                  if (cr.overweight) items.push({ description: "Overweight", rate: String(cr.overweight) });
                  if (cr.tolls) items.push({ description: "Tolls", rate: String(cr.tolls) });
                  // Build accessorials from optional fields
                  const accessorials = {};
                  if (cr.storage_per_day) accessorials.storage = String(cr.storage_per_day);
                  if (cr.detention) accessorials.detention = String(cr.detention);
                  if (cr.chassis_split) accessorials.chassis_split = String(cr.chassis_split);
                  if (cr.hazmat) accessorials.hazmat = String(cr.hazmat);
                  if (cr.reefer) accessorials.reefer = String(cr.reefer);
                  if (cr.bond_fee) accessorials.bond = String(cr.bond_fee);
                  if (cr.triaxle) accessorials.triaxle = String(cr.triaxle);
                  setSelectedLane({
                    origin: currentGroup.port,
                    destination: currentGroup.destination,
                    carrier: cr.carrier_name,
                    linehaul: items.length > 0 ? items : undefined,
                    accessorials: Object.keys(accessorials).length > 0 ? accessorials : undefined,
                    miles: currentGroup.miles,
                  });
                  setView("build-quote");
                }}
              />
            </div>

            {/* Right column — AI Rate Assistant */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="glass" style={{ borderRadius: 14, border: "1px solid rgba(255,255,255,0.06)", flex: 1, display: "flex", flexDirection: "column", maxHeight: "calc(100vh - 200px)" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 32, height: 32, borderRadius: "50%", background: "rgba(0,212,170,0.12)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🤖</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5" }}>AI Rate Assistant</div>
                    <div style={{ fontSize: 11, color: "#5A6478" }}>Lane intelligence for {selectedLane?.origin || "—"} → {selectedLane?.destination || "—"}</div>
                  </div>
                  {aiMessages.length > 0 && (
                    <button onClick={() => setAiMessages([])} title="Clear chat"
                      style={{ padding: "4px 8px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>
                      Clear
                    </button>
                  )}
                </div>
                <div ref={aiChatRef} style={{ padding: "16px 20px", flex: 1, overflowY: "auto" }}>
                  {/* Auto-generated data insights (always shown) */}
                  {currentGroup.count >= 2 && (() => {
                    const sorted = [...currentGroup.carriers].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
                    const rates = sorted.map(c => parseFloat(c.total || c.dray_rate || 0)).filter(r => r > 0);
                    const recentAvg = sorted.slice(-3).reduce((s, c) => s + parseFloat(c.total || c.dray_rate || 0), 0) / Math.min(sorted.length, 3);
                    const oldAvg = sorted.slice(0, 3).reduce((s, c) => s + parseFloat(c.total || c.dray_rate || 0), 0) / Math.min(sorted.length, 3);
                    const trend = recentAvg > oldAvg ? "rising" : recentAvg < oldAvg ? "falling" : "stable";
                    const trendColor = trend === "rising" ? "#f87171" : trend === "falling" ? "#34d399" : "#8B95A8";
                    const pctChange = oldAvg > 0 ? Math.abs(((recentAvg - oldAvg) / oldAvg) * 100).toFixed(0) : 0;
                    // Find cheapest carrier
                    const cheapest = sorted.reduce((best, c) => {
                      const r = parseFloat(c.total || c.dray_rate || 0);
                      return r > 0 && (!best || r < best.rate) ? { name: c.carrier_name, rate: r } : best;
                    }, null);
                    // Rate spread
                    const spread = rates.length >= 2 ? Math.round(Math.max(...rates) - Math.min(...rates)) : 0;
                    // Freshest rate age
                    const newest = sorted[sorted.length - 1];
                    const newestDays = newest?.created_at ? Math.floor((Date.now() - new Date(newest.created_at).getTime()) / 86400000) : null;
                    // Accessorials present in data
                    const accPresent = [];
                    const hasAcc = (field) => sorted.some(c => c[field] && parseFloat(c[field]) > 0);
                    if (hasAcc("chassis_per_day")) accPresent.push("Chassis");
                    if (hasAcc("prepull")) accPresent.push("Pre-Pull");
                    if (hasAcc("storage_per_day")) accPresent.push("Storage");
                    if (hasAcc("detention")) accPresent.push("Detention");
                    if (hasAcc("overweight")) accPresent.push("Overweight");
                    if (hasAcc("hazmat")) accPresent.push("Hazmat");
                    if (hasAcc("reefer")) accPresent.push("Reefer");

                    return (
                      <div style={{ marginBottom: 16 }}>
                        {/* Trend */}
                        <div style={{ padding: "10px 14px", borderRadius: 10, background: trendColor + "08", border: `1px solid ${trendColor}20`, marginBottom: 10 }}>
                          <div style={{ fontSize: 11, color: "#C8D0DC", lineHeight: 1.5 }}>
                            Rates are <span style={{ fontWeight: 700, color: trendColor }}>{trend}</span>
                            {pctChange > 2 && <span> ({pctChange}% {trend === "rising" ? "increase" : "decrease"})</span>}.
                            {trend === "rising" && " Consider locking in rates soon."}
                            {trend === "falling" && " Good opportunity to negotiate."}
                          </div>
                        </div>
                        {/* Key metrics */}
                        <div style={{ fontSize: 11, color: "#C8D0DC", lineHeight: 1.8, padding: "0 4px" }}>
                          {cheapest && <div><span style={{ color: "#5A6478" }}>Best rate:</span> <span style={{ fontWeight: 700, color: "#34d399" }}>{fmt(cheapest.rate)}</span> ({cheapest.name})</div>}
                          {spread > 50 && <div><span style={{ color: "#5A6478" }}>Rate spread:</span> <span style={{ fontWeight: 700, color: "#FBBF24" }}>{fmt(spread)}</span> — room to negotiate</div>}
                          {newestDays !== null && <div><span style={{ color: "#5A6478" }}>Freshest rate:</span> {newestDays === 0 ? "today" : newestDays < 7 ? `${newestDays}d ago` : newestDays < 30 ? `${Math.floor(newestDays / 7)}w ago` : `${Math.floor(newestDays / 30)}mo ago`}{newestDays > 30 && <span style={{ color: "#FBBF24" }}> — consider refreshing</span>}</div>}
                          {marketBenchmark?.stats?.avg && <div><span style={{ color: "#5A6478" }}>vs Market:</span> {(() => {
                            const avg = currentGroup.count > 0 ? currentGroup.total / currentGroup.count : 0;
                            const diff = avg - marketBenchmark.stats.avg;
                            const pct = marketBenchmark.stats.avg > 0 ? Math.abs(diff / marketBenchmark.stats.avg * 100).toFixed(0) : 0;
                            return diff > 0
                              ? <span style={{ color: "#f87171" }}>{pct}% above market avg ({fmt(marketBenchmark.stats.avg)})</span>
                              : <span style={{ color: "#34d399" }}>{pct}% below market avg ({fmt(marketBenchmark.stats.avg)})</span>;
                          })()}</div>}
                          {accPresent.length > 0 && <div><span style={{ color: "#5A6478" }}>Accessorials on file:</span> {accPresent.join(", ")}</div>}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Quick-ask buttons */}
                  {aiMessages.length === 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#5A6478", marginBottom: 8 }}>Ask about this lane:</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {[
                          "Which carrier should I use?",
                          "What's a fair rate for this lane?",
                          "Compare my rates to market",
                          "Any red flags on this lane?",
                        ].map((q, i) => (
                          <button key={i} onClick={() => askAI(q, currentGroup)}
                            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(0,212,170,0.15)", background: "rgba(0,212,170,0.04)", color: "#00D4AA", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                            onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.1)"}
                            onMouseLeave={e => e.currentTarget.style.background = "rgba(0,212,170,0.04)"}>
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Chat messages */}
                  {aiMessages.map((msg, i) => (
                    <div key={i} style={{ marginBottom: 12, display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>
                      <div style={{
                        padding: "10px 14px", borderRadius: 12, maxWidth: "90%", fontSize: 12, lineHeight: 1.6,
                        background: msg.role === "user" ? "rgba(59,130,246,0.12)" : "rgba(0,212,170,0.06)",
                        border: `1px solid ${msg.role === "user" ? "rgba(59,130,246,0.2)" : "rgba(0,212,170,0.15)"}`,
                        color: "#C8D0DC", whiteSpace: "pre-wrap",
                      }}>
                        {msg.text}
                      </div>
                    </div>
                  ))}
                  {aiLoading && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0" }}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#00D4AA", animation: "pulse 1s infinite" }} />
                      <span style={{ fontSize: 11, color: "#5A6478" }}>Analyzing lane data...</span>
                    </div>
                  )}
                </div>

                {/* AI Chat Input */}
                <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input value={aiInput} onChange={e => setAiInput(e.target.value)}
                      placeholder="Ask about rates, carriers, trends..."
                      onKeyDown={e => { if (e.key === "Enter" && aiInput.trim() && !aiLoading) askAI(aiInput, currentGroup); }}
                      style={{ flex: 1, padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                    <button onClick={() => { if (aiInput.trim() && !aiLoading) askAI(aiInput, currentGroup); }}
                      disabled={aiLoading || !aiInput.trim()}
                      style={{ padding: "8px 14px", borderRadius: 8, border: "none", background: aiInput.trim() ? "rgba(0,212,170,0.12)" : "rgba(255,255,255,0.04)", color: aiInput.trim() ? "#00D4AA" : "#3D4654", fontSize: 13, cursor: aiInput.trim() ? "pointer" : "default", transition: "all 0.15s" }}>→</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {!laneSearching && !currentGroup && (
          <div style={{ padding: 60, textAlign: "center", color: "#5A6478" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>📭</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#F0F2F5" }}>No rate data found for this lane</div>
            <div style={{ fontSize: 12, marginTop: 6 }}>Try a different origin or destination</div>
          </div>
        )}
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // RATE INTAKE VIEW (unified carrier rates + market rates)
  // ═════════════════════════════════════════════════════════════
  if (view === "intake") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate Intake</h2>
          <span style={{ fontSize: 11, color: "#5A6478" }}>Drop carrier rate emails, screenshots, or paste rate data</span>
        </div>

        {/* Hidden file inputs */}
        <input ref={intakeFileRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.msg,.eml,.html,.htm,.txt" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setIntakeFile(f); setIntakeResult(null); } e.target.value = ""; }} />
        <input ref={marketRateFileRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setIntakeFile(f); setIntakeResult(null); } e.target.value = ""; }} />

        {/* Unified Drag-Drop Zone */}
        <div className="glass" style={{ borderRadius: 14, padding: 32, marginBottom: 20,
          border: `2px dashed ${intakeDragOver ? "rgba(0,212,170,0.5)" : "rgba(255,255,255,0.1)"}`,
          background: intakeDragOver ? "rgba(0,212,170,0.04)" : "rgba(255,255,255,0.01)",
          textAlign: "center", transition: "all 0.2s", cursor: "pointer" }}
          onClick={() => intakeFileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIntakeDragOver(true); }}
          onDragLeave={() => setIntakeDragOver(false)}
          onDrop={e => {
            e.preventDefault(); e.stopPropagation(); setIntakeDragOver(false);
            const file = e.dataTransfer.files?.[0];
            if (file) { setIntakeFile(file); setIntakeResult(null); setMarketRateResult(null); return; }
            const text = e.dataTransfer.getData("text/plain");
            if (text) { setIntakeText(text); }
          }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.4 }}>&#128206;</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#8B95A8", marginBottom: 4 }}>
            Drop carrier quote or rate screenshot here
          </div>
          <div style={{ fontSize: 11, color: "#5A6478" }}>
            .msg / .eml emails, screenshots, PDFs, or paste text below
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <button onClick={e => { e.stopPropagation(); intakeFileRef.current?.click(); }}
              style={{ padding: "6px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#34d399", cursor: "pointer", fontFamily: "inherit" }}>
              Browse Files
            </button>
          </div>
        </div>

        {/* File badge */}
        {intakeFile && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", marginBottom: 12, borderRadius: 10, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}>
            <span style={{ fontSize: 11, color: "#34d399", fontWeight: 700 }}>File:</span>
            <span style={{ fontSize: 11, color: "#C8D0DC", fontFamily: "'JetBrains Mono', monospace" }}>{intakeFile.name}</span>
            <span style={{ fontSize: 10, color: "#5A6478" }}>({(intakeFile.size / 1024).toFixed(1)} KB)</span>
            <button onClick={() => setIntakeFile(null)} style={{ marginLeft: "auto", fontSize: 10, color: "#f87171", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}>Remove</button>
          </div>
        )}

        {/* Text paste area */}
        {!intakeFile && (
          <textarea value={intakeText} onChange={e => setIntakeText(e.target.value)}
            onPaste={e => {
              const items = e.clipboardData?.items;
              if (items) {
                for (const item of items) {
                  if (item.type.startsWith("image/")) {
                    e.preventDefault();
                    const file = item.getAsFile();
                    if (file) { setIntakeFile(file); setIntakeResult(null); }
                    return;
                  }
                }
              }
              const text = e.clipboardData.getData("text/plain");
              if (text && !intakeText) { e.preventDefault(); setIntakeText(text); }
            }}
            placeholder={"Paste carrier rate email, or tab-separated market rate data:\n\n2026-Mar-14\tLong Beach Container\t$2,600\t0%\t$2,600\n2026-Mar-12\tAPM Los Angeles\t$2,250\t0%\t$2,250"}
            style={{ width: "100%", minHeight: 120, maxHeight: 240, padding: 14, borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)", color: "#F0F2F5", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", outline: "none", resize: "vertical", boxSizing: "border-box", marginBottom: 12 }} />
        )}

        {/* Controls row */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          {/* Move type */}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Type:</span>
            {["dray", "transload", "ftl"].map(mt => {
              const active = intakeMoveType === mt;
              const s = MOVE_TYPE_STYLES[mt];
              return (
                <button key={mt} onClick={() => setIntakeMoveType(mt)}
                  style={{ padding: "4px 12px", fontSize: 11, fontWeight: 700, borderRadius: 6, border: `1px solid ${active ? s.color + "55" : "rgba(255,255,255,0.06)"}`, background: active ? s.color + "18" : "transparent", color: active ? s.color : "#5A6478", cursor: "pointer", fontFamily: "inherit" }}>
                  {s.label}
                </button>
              );
            })}
          </div>

          {/* Optional origin/dest for market rates */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
            <input value={marketRateOrigin} onChange={e => setMarketRateOrigin(e.target.value)} placeholder="Origin (optional)"
              style={{ width: 140, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
            <span style={{ color: "#5A6478", fontSize: 11 }}>→</span>
            <input value={marketRateDest} onChange={e => setMarketRateDest(e.target.value)} placeholder="Destination (optional)"
              style={{ width: 140, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
          </div>
        </div>

        {/* Extraction Review Card */}
        {intakePreview && (
          <div className="glass" style={{ borderRadius: 12, padding: 20, marginTop: 16, border: "1px solid rgba(0,212,170,0.2)", background: "rgba(0,212,170,0.03)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#34d399" }}>Review Extracted Data</span>
              <span style={{ fontSize: 10, color: "#5A6478" }}>Edit any field before saving</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Carrier
                <input value={intakePreview.carrier_name || ""} onChange={e => setIntakePreview(p => ({ ...p, carrier_name: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </label>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Rate Amount
                <input value={intakePreview.rate_amount ?? ""} onChange={e => setIntakePreview(p => ({ ...p, rate_amount: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", outline: "none", boxSizing: "border-box" }} />
              </label>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Origin
                <input value={intakePreview.origin || ""} onChange={e => setIntakePreview(p => ({ ...p, origin: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </label>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Destination
                <input value={intakePreview.destination || ""} onChange={e => setIntakePreview(p => ({ ...p, destination: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </label>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>MC#
                <input value={intakePreview.carrier_mc || ""} onChange={e => setIntakePreview(p => ({ ...p, carrier_mc: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", outline: "none", boxSizing: "border-box" }} />
              </label>
              <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Move Type
                <select value={intakePreview.shipment_type || intakeMoveType} onChange={e => setIntakePreview(p => ({ ...p, shipment_type: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}>
                  <option value="dray">Dray</option>
                  <option value="ftl">FTL</option>
                  <option value="transload">Transload</option>
                </select>
              </label>
            </div>
            {/* Linehaul items */}
            {(intakePreview.linehaul_items || []).length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Linehaul Items</span>
                {intakePreview.linehaul_items.map((item, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                    <input value={item.description || ""} onChange={e => setIntakePreview(p => {
                      const items = [...(p.linehaul_items || [])];
                      items[i] = { ...items[i], description: e.target.value };
                      return { ...p, linehaul_items: items };
                    })} style={{ flex: 1, padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#C8D0DC", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                    <input value={item.rate || ""} onChange={e => setIntakePreview(p => {
                      const items = [...(p.linehaul_items || [])];
                      items[i] = { ...items[i], rate: e.target.value };
                      return { ...p, linehaul_items: items };
                    })} style={{ width: 80, padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#C8D0DC", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none", textAlign: "right" }} />
                  </div>
                ))}
              </div>
            )}
            {/* Accessorials */}
            {(intakePreview.accessorials || []).length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase" }}>Accessorials</span>
                {intakePreview.accessorials.map((acc, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                    <input value={acc.charge || ""} onChange={e => setIntakePreview(p => {
                      const accs = [...(p.accessorials || [])];
                      accs[i] = { ...accs[i], charge: e.target.value };
                      return { ...p, accessorials: accs };
                    })} style={{ flex: 1, padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#C8D0DC", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                    <input value={acc.rate || ""} onChange={e => setIntakePreview(p => {
                      const accs = [...(p.accessorials || [])];
                      accs[i] = { ...accs[i], rate: e.target.value };
                      return { ...p, accessorials: accs };
                    })} style={{ width: 80, padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#C8D0DC", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none", textAlign: "right" }} />
                    <span style={{ fontSize: 10, color: "#5A6478", minWidth: 50 }}>{acc.frequency || "flat"}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
              <button onClick={() => setIntakePreview(null)}
                style={{ padding: "6px 16px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                Discard
              </button>
              <button onClick={handleIntakeSave} disabled={intakeSaving}
                style={{ padding: "6px 20px", borderRadius: 6, border: "none", background: grad, color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: intakeSaving ? "wait" : "pointer", fontFamily: "inherit", opacity: intakeSaving ? 0.6 : 1 }}>
                {intakeSaving ? "Saving..." : "Save Rate"}
              </button>
            </div>
          </div>
        )}

        {/* Results / Actions */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
          <div style={{ fontSize: 11, color: "#5A6478" }}>
            {intakeFile ? "Ready to extract from file" : intakeText.length > 0 ? `${intakeText.length.toLocaleString()} chars` : ""}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {intakeResult?.ok && intakeResult.duplicate_skipped && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#FBBF24" }}>
                ⚠ Duplicate rate already exists — {intakeResult.extracted?.carrier_name} {intakeResult.extracted?.origin} → {intakeResult.extracted?.destination} @ ${intakeResult.extracted?.rate_amount}
              </span>
            )}
            {intakeResult?.ok && !intakeResult.duplicate_skipped && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#34d399" }}>
                ✓ {intakeResult.extracted ? `Added: ${intakeResult.extracted.carrier_name} — ${intakeResult.extracted.origin} → ${intakeResult.extracted.destination}${intakeResult.extracted.rate_amount ? ` @ $${intakeResult.extracted.rate_amount}` : ""}` : `Saved ${intakeResult.inserted || 0} rate(s)`}
              </span>
            )}
            {intakeResult?.error && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#f87171" }}>✗ {intakeResult.error}</span>
            )}
            {marketRateResult?.ok && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#34d399" }}>
                ✓ Saved {marketRateResult.inserted} rate{marketRateResult.inserted !== 1 ? "s" : ""}{marketRateResult.skipped > 0 ? ` (${marketRateResult.skipped} skipped)` : ""}
              </span>
            )}
            {marketRateResult?.error && (
              <span style={{ fontSize: 11, fontWeight: 700, color: "#f87171" }}>✗ {marketRateResult.error}</span>
            )}
            {!intakePreview && (intakeText.trim() || intakeFile) && (
              <button onClick={() => {
                // Auto-detect: if text looks like tab-separated market data and has origin/dest, use market rate handler
                const isTabSeparated = intakeText && intakeText.includes("\t") && marketRateOrigin.trim() && marketRateDest.trim();
                if (isTabSeparated && !intakeFile) {
                  setMarketRateText(intakeText);
                  setMarketRateMoveType(intakeMoveType);
                  handleMarketRatePaste();
                } else {
                  handleManualIntake();
                }
              }} disabled={intakeProcessing || marketRateProcessing}
                style={{ padding: "8px 24px", borderRadius: 8, border: "none", background: grad, color: "#0A0F1C", fontSize: 12, fontWeight: 700, cursor: (intakeProcessing || marketRateProcessing) ? "wait" : "pointer", fontFamily: "inherit", opacity: (intakeProcessing || marketRateProcessing) ? 0.6 : 1 }}>
                {(intakeProcessing || marketRateProcessing) ? "Extracting..." : "Extract & Review"}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // BUILD QUOTE VIEW (from lane detail)
  // ═════════════════════════════════════════════════════════════
  if (view === "build-quote") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView(selectedLane ? "detail" : "browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Build Quote</h2>
          {selectedLane && <span style={{ fontSize: 12, color: "#5A6478" }}>{selectedLane.origin} → {selectedLane.destination}</span>}
        </div>
        <div style={{ height: "calc(100vh - 180px)" }}>
          <QuoteBuilder prefill={selectedLane || undefined} />
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // OOG IQ VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "oog") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>OOG IQ — Oversize Quote Builder</h2>
        </div>
        <OOGQuoteBuilder />
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // SCORECARD VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "scorecard") {
    return (
      <div style={{ padding: "0 24px 24px", maxWidth: 1200 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Carrier Scorecard</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>{scorecardPerf.length} carriers with performance data</div>
          </div>
        </div>
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
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.carrier}</div>
                    <div style={{ fontSize: 11, color: "#5A6478", marginTop: 1 }}>{c.primary_move_type || "—"}{c.last_delivery ? ` · Last: ${c.last_delivery}` : ""}</div>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center", flexShrink: 0 }}>
                    <div style={{ textAlign: "center", minWidth: 44 }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.total_loads}</div>
                      <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600, letterSpacing: "0.5px" }}>LOADS</div>
                    </div>
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: otBg, color: otColor, border: `1px solid ${otColor}30` }}>{c.on_time_pct}% OT</span>
                    {c.avg_transit_days != null && (
                      <div style={{ textAlign: "center", minWidth: 44 }}>
                        <div style={{ fontSize: 14, fontWeight: 800, color: "#F0F2F5", fontFamily: "'JetBrains Mono', monospace" }}>{c.avg_transit_days}</div>
                        <div style={{ fontSize: 8, color: "#5A6478", fontWeight: 600 }}>AVG DAYS</div>
                      </div>
                    )}
                    <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "#60a5fa", fontSize: 11, fontWeight: 700 }}>{c.lanes_served} lane{c.lanes_served !== 1 ? "s" : ""}</span>
                    <span style={{ color: "#5A6478", fontSize: 14, transition: "transform 0.2s", transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}>▼</span>
                  </div>
                </div>
                {isExpanded && c.top_lanes?.length > 0 && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "10px 16px 14px" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 8 }}>Top Lanes</div>
                    {c.top_lanes.map((tl, li) => (
                      <div key={li} onClick={() => openLaneDetail(tl.lane?.split("→")[0]?.trim(), tl.lane?.split("→")[1]?.trim(), 0)}
                        style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(255,255,255,0.02)", marginBottom: 3, cursor: "pointer", transition: "background 0.15s" }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.06)"} onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}>
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
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // DIRECTORY VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "directory") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Carrier Directory</h2>
            <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>{dirCarriers.length} carriers</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button onClick={() => setShowAddCarrier(!showAddCarrier)}
              style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid rgba(0,212,170,0.3)", background: showAddCarrier ? "rgba(0,212,170,0.1)" : "transparent", color: "#34d399", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
              + Add Carrier
            </button>
          </div>
        </div>

        {/* LoadMatch Screenshot Import */}
        <input ref={dirScreenshotRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.pdf" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) { setDirScreenshotFile(f); setDirScreenshotResult(null); } e.target.value = ""; }} />
        <div style={{ borderRadius: 10, padding: "12px 16px", marginBottom: 12,
          border: "1px dashed rgba(251,146,60,0.25)", background: "rgba(251,146,60,0.02)",
          display: "flex", alignItems: "center", gap: 12, cursor: "pointer" }}
          onClick={() => dirScreenshotRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) { setDirScreenshotFile(f); setDirScreenshotResult(null); } }}>
          <span style={{ fontSize: 11, color: "#fb923c", fontWeight: 700 }}>LOADMATCH IMPORT</span>
          <span style={{ fontSize: 11, color: "#5A6478" }}>— drop screenshot to extract carriers + capabilities</span>
          {dirScreenshotFile && (
            <span style={{ fontSize: 11, color: "#C8D0DC", fontFamily: "'JetBrains Mono', monospace", marginLeft: 8 }}>
              {dirScreenshotFile.name}
              <button onClick={e => { e.stopPropagation(); setDirScreenshotFile(null); setDirScreenshotResult(null); }} style={{ marginLeft: 6, fontSize: 10, color: "#f87171", background: "none", border: "none", cursor: "pointer" }}>×</button>
            </span>
          )}
          {dirScreenshotFile && !dirScreenshotProcessing && (
            <button onClick={e => { e.stopPropagation(); handleDirScreenshot(); }}
              style={{ marginLeft: "auto", padding: "4px 14px", borderRadius: 6, border: "none", background: "linear-gradient(135deg, #fb923c, #f59e0b)", color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
              Extract & Import
            </button>
          )}
          {dirScreenshotProcessing && <span style={{ marginLeft: "auto", fontSize: 11, color: "#fb923c" }}>Extracting...</span>}
          {dirScreenshotResult?.error && <span style={{ fontSize: 11, color: "#f87171", marginLeft: "auto" }}>✗ {dirScreenshotResult.error}</span>}
          {dirScreenshotResult?.carriers && <span style={{ fontSize: 11, color: "#34d399", marginLeft: "auto" }}>✓ Imported {dirScreenshotResult.carriers.length} carriers</span>}
          {dirScreenshotResult?.saved && <span style={{ fontSize: 11, color: "#34d399", marginLeft: "auto" }}>✓ Imported {dirScreenshotResult.saved.length} carriers</span>}
        </div>

        {/* Add Carrier Form */}
        {showAddCarrier && (
          <div className="glass" style={{ borderRadius: 10, padding: 16, marginBottom: 12, border: "1px solid rgba(0,212,170,0.2)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 180px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>Carrier Name *</label>
                <input value={newCarrier.carrier_name} onChange={e => setNewCarrier(p => ({ ...p, carrier_name: e.target.value }))} placeholder="Carrier name"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <div style={{ flex: "0 0 120px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>MC#</label>
                <input value={newCarrier.mc_number} onChange={e => setNewCarrier(p => ({ ...p, mc_number: e.target.value }))} placeholder="MC number"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <div style={{ flex: "1 1 140px" }}>
                <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", display: "block", marginBottom: 3 }}>City / State</label>
                <input value={newCarrier.pickup_area} onChange={e => setNewCarrier(p => ({ ...p, pickup_area: e.target.value }))} placeholder="e.g. Los Angeles, CA"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
              </div>
              <button onClick={handleAddCarrier} disabled={addCarrierSaving || !newCarrier.carrier_name.trim()}
                style={{ padding: "6px 16px", borderRadius: 6, border: "none", background: grad, color: "#0A0F1C", fontSize: 11, fontWeight: 700, cursor: (addCarrierSaving || !newCarrier.carrier_name.trim()) ? "default" : "pointer", fontFamily: "inherit", opacity: (addCarrierSaving || !newCarrier.carrier_name.trim()) ? 0.5 : 1 }}>
                {addCarrierSaving ? "Saving..." : "Add"}
              </button>
              <button onClick={() => setShowAddCarrier(false)}
                style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
          <input value={dirSearch} onChange={e => setDirSearch(e.target.value)} placeholder="Search carrier, MC#, email..."
            style={{ flex: "1 1 200px", minWidth: 200, padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
          <select value={dirMarket} onChange={e => setDirMarket(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "#151926", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
            <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Markets</option>
            {allMarkets.map(m => <option key={m} value={m} style={{ background: "#151926", color: "#F0F2F5" }}>{m}</option>)}
          </select>
          <select value={dirPort} onChange={e => setDirPort(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${dirPort !== "all" ? "rgba(0,212,170,0.3)" : "rgba(255,255,255,0.08)"}`, background: dirPort !== "all" ? "rgba(0,212,170,0.06)" : "#151926", color: dirPort !== "all" ? "#00D4AA" : "#F0F2F5", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>
            <option value="all" style={{ background: "#151926", color: "#F0F2F5" }}>All Ports/Rails</option>
            {portGroups.filter(g => !g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
            <option disabled style={{ background: "#151926", color: "#5A6478" }}>── Rail ──</option>
            {portGroups.filter(g => g.is_rail).map(g => <option key={g.name} value={g.name} style={{ background: "#151926", color: "#F0F2F5" }}>{g.name}</option>)}
          </select>
          {CAP_OPTIONS.map(cap => {
            const active = dirCaps.includes(cap.key);
            return <button key={cap.key} onClick={() => setDirCaps(prev => active ? prev.filter(c => c !== cap.key) : [...prev, cap.key])}
              style={{ padding: "5px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", border: `1px solid ${active ? cap.color + "60" : "rgba(255,255,255,0.06)"}`, background: active ? cap.color + "18" : "transparent", color: active ? cap.color : "#8B95A8", fontFamily: "inherit", transition: "all 0.15s" }}>
              {cap.label}
            </button>;
          })}
          <button onClick={() => setDirHideDnu(!dirHideDnu)}
            style={{ padding: "5px 12px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", border: `1px solid ${dirHideDnu ? "rgba(255,255,255,0.06)" : "rgba(239,68,68,0.4)"}`, background: dirHideDnu ? "transparent" : "rgba(239,68,68,0.1)", color: dirHideDnu ? "#8B95A8" : "#f87171", fontFamily: "inherit" }}>
            {dirHideDnu ? "Show DNU" : "Hide DNU"}
          </button>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "#5A6478" }}>{filteredDir.length} carriers · {allMarkets.length} markets</div>
          <button onClick={() => setDirGroupView(!dirGroupView)}
            style={{ padding: "4px 10px", borderRadius: 6, fontSize: 10, fontWeight: 700, cursor: "pointer", border: "1px solid rgba(255,255,255,0.08)", background: dirGroupView ? "rgba(0,212,170,0.08)" : "transparent", color: dirGroupView ? "#00D4AA" : "#8B95A8", fontFamily: "inherit" }}>
            {dirGroupView ? "⊞ Grouped" : "☰ Flat List"}
          </button>
        </div>

        {/* Carrier Cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {filteredDir.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "#5A6478", fontSize: 12 }}>No carriers match your filters.</div>}

          {/* ── Grouped by state/city view ── */}
          {dirGroupView && groupedDir.map(stateGroup => {
            const isStateOpen = !!expandedMarkets[`state:${stateGroup.state}`];
            return (
              <div key={stateGroup.state} className="glass" style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(255,255,255,0.06)" }}>
                {/* State header */}
                <div onClick={() => setExpandedMarkets(prev => ({ ...prev, [`state:${stateGroup.state}`]: !prev[`state:${stateGroup.state}`] }))}
                  style={{ padding: "14px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", transition: "background 0.15s", background: "rgba(255,255,255,0.015)" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.035)"}
                  onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.015)"}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: 11, color: "#5A6478", transform: isStateOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s", display: "inline-block" }}>▼</span>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 16, fontWeight: 800, color: "#F0F2F5" }}>{stateGroup.state}</span>
                        <span style={{ fontSize: 11, color: "#5A6478" }}>{stateGroup.cities.length} cit{stateGroup.cities.length !== 1 ? "ies" : "y"}</span>
                      </div>
                      <div style={{ fontSize: 10, color: "#5A6478", marginTop: 1 }}>
                        {stateGroup.totalCarriers} carrier{stateGroup.totalCarriers !== 1 ? "s" : ""}
                        {stateGroup.totalTrucks > 0 && <span> · {stateGroup.totalTrucks} trucks</span>}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {stateGroup.tierCounts[1] > 0 && <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 700, background: "rgba(34,197,94,0.12)", color: "#34d399" }}>T1: {stateGroup.tierCounts[1]}</span>}
                    {stateGroup.tierCounts[2] > 0 && <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 700, background: "rgba(245,158,11,0.12)", color: "#FBBF24" }}>T2: {stateGroup.tierCounts[2]}</span>}
                    {stateGroup.tierCounts[3] > 0 && <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 700, background: "rgba(251,146,60,0.12)", color: "#fb923c" }}>T3: {stateGroup.tierCounts[3]}</span>}
                  </div>
                </div>
                {/* Cities within state */}
                {isStateOpen && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                    {stateGroup.cities.map(cityGroup => {
                      const isCityOpen = !!expandedMarkets[`city:${stateGroup.state}:${cityGroup.city}`];
                      return (
                        <div key={cityGroup.city}>
                          {/* City sub-header */}
                          <div onClick={() => setExpandedMarkets(prev => ({ ...prev, [`city:${stateGroup.state}:${cityGroup.city}`]: !prev[`city:${stateGroup.state}:${cityGroup.city}`] }))}
                            style={{ padding: "8px 18px 8px 40px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.03)", transition: "background 0.1s" }}
                            onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ fontSize: 10, color: "#5A6478", transform: isCityOpen ? "rotate(90deg)" : "rotate(0)", transition: "transform 0.15s", display: "inline-block" }}>▶</span>
                              <span style={{ fontSize: 13, fontWeight: 600, color: "#C8D0DC" }}>{cityGroup.city}</span>
                              <span style={{ fontSize: 10, color: "#5A6478" }}>{cityGroup.carriers.length}</span>
                            </div>
                          </div>
                          {/* Carriers in city */}
                          {isCityOpen && cityGroup.carriers.map((c, ci) => {
                            const tierColors = { 1: { bg: "rgba(34,197,94,0.12)", color: "#34d399", label: "T1" }, 2: { bg: "rgba(245,158,11,0.12)", color: "#FBBF24", label: "T2" }, 3: { bg: "rgba(251,146,60,0.12)", color: "#fb923c", label: "T3" }, 0: { bg: "rgba(239,68,68,0.12)", color: "#f87171", label: "DNU" } };
                            const tier = tierColors[c.tier_rank] || { bg: "rgba(107,114,128,0.08)", color: "#6B7280", label: "—" };
                            const isExp = dirExpanded === c.id;
                            return (
                              <div key={c.id || ci}>
                                <div style={{ padding: "7px 18px 7px 64px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid rgba(255,255,255,0.02)", cursor: "pointer", transition: "background 0.1s" }}
                                  onClick={() => setDirExpanded(isExp ? null : c.id)}
                                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                      <span style={{ fontSize: 12, fontWeight: 600, color: c.dnu ? "#f87171" : "#F0F2F5", textDecoration: c.dnu ? "line-through" : "none" }}>{c.carrier_name}</span>
                                      {c.mc_number && <span style={{ fontSize: 10, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{c.mc_number}</span>}
                                    </div>
                                    <div style={{ display: "flex", gap: 3, marginTop: 2, flexWrap: "wrap" }}>
                                      {CAP_OPTIONS.filter(cap => c[cap.key]).map(cap => (
                                        <span key={cap.key} style={{ padding: "0px 5px", borderRadius: 3, fontSize: 7, fontWeight: 700, background: cap.color + "18", color: cap.color }}>{cap.label}</span>
                                      ))}
                                    </div>
                                  </div>
                                  <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 700, background: tier.bg, color: tier.color, flexShrink: 0 }}>{tier.label}</span>
                                  {c.trucks && <div style={{ textAlign: "center", minWidth: 28, flexShrink: 0 }}><div style={{ fontSize: 11, fontWeight: 800, color: "#F0F2F5" }}>{c.trucks}</div><div style={{ fontSize: 7, color: "#5A6478" }}>TRUCKS</div></div>}
                                  <span style={{ color: "#5A6478", fontSize: 10, transform: isExp ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.15s", flexShrink: 0 }}>▼</span>
                                </div>
                                {/* Expanded detail — full edit panel */}
                                {isExp && (() => {
                                  const isEdit = editingCarrierId === c.id;
                                  const iStyle = { width: "100%", padding: "3px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
                                  const editInput = (label, field, opts = {}) => {
                                    const val = c[field] || "";
                                    if (!isEdit && !val) return null;
                                    return (
                                      <div style={{ fontSize: 11, marginBottom: 4 }}>
                                        <span style={{ color: "#5A6478" }}>{label}: </span>
                                        {isEdit ? (
                                          <input defaultValue={val} key={val} onClick={e => e.stopPropagation()}
                                            onBlur={e => { const v = e.target.value.trim(); if (v !== (c[field] || "")) handleCarrierUpdate(c.id, field, v || null); }}
                                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                                            placeholder={opts.placeholder || ""} style={iStyle} />
                                        ) : (
                                          <span style={{ color: opts.color || "#C8D0DC", cursor: opts.copyable ? "pointer" : "default" }}
                                            onClick={opts.copyable ? (e => { e.stopPropagation(); navigator.clipboard.writeText(val); }) : undefined}>
                                            {val}{opts.copyable ? " 📋" : ""}
                                          </span>
                                        )}
                                      </div>
                                    );
                                  };
                                  return (
                                    <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "12px 18px 12px 64px", background: "rgba(0,0,0,0.1)" }}>
                                      {/* Capability badges (editable in edit mode) */}
                                      {isEdit && (
                                        <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
                                          {CAP_OPTIONS.map(cap => (
                                            <span key={cap.key} onClick={e => { e.stopPropagation(); handleCarrierUpdate(c.id, cap.key, !c[cap.key]); }}
                                              style={{ padding: "1px 7px", borderRadius: 4, fontSize: 8, fontWeight: 700, cursor: "pointer", transition: "all 0.15s",
                                                background: c[cap.key] ? cap.color + "18" : "rgba(255,255,255,0.02)", color: c[cap.key] ? cap.color : "#3D4557",
                                                border: `1px solid ${c[cap.key] ? cap.color + "30" : "rgba(255,255,255,0.06)"}` }}>{cap.label}</span>
                                          ))}
                                        </div>
                                      )}
                                      {/* Tier selector + trucks (in edit mode) */}
                                      {isEdit && (
                                        <div style={{ display: "flex", gap: 10, marginBottom: 8, alignItems: "center" }}>
                                          <div style={{ fontSize: 11 }}>
                                            <span style={{ color: "#5A6478" }}>Tier: </span>
                                            <select value={c.tier_rank ?? ""} onClick={e => e.stopPropagation()}
                                              onChange={e => { const v = e.target.value === "" ? null : parseInt(e.target.value); handleCarrierUpdate(c.id, "tier_rank", v); if (v === 0) handleCarrierUpdate(c.id, "dnu", true); else if (c.dnu) handleCarrierUpdate(c.id, "dnu", false); }}
                                              style={{ padding: "2px 6px", borderRadius: 4, fontSize: 11, background: "#151926", color: tier.color, border: `1px solid ${tier.color}30`, cursor: "pointer", fontFamily: "inherit" }}>
                                              <option value="">Unranked</option>
                                              <option value="1">Tier 1</option>
                                              <option value="2">Tier 2</option>
                                              <option value="3">Tier 3</option>
                                              <option value="0">DNU</option>
                                            </select>
                                          </div>
                                          <div style={{ fontSize: 11 }}>
                                            <span style={{ color: "#5A6478" }}>Trucks: </span>
                                            <input type="number" defaultValue={c.trucks || ""} key={c.trucks} onClick={e => e.stopPropagation()}
                                              onBlur={e => { const v = e.target.value.trim(); const n = v ? parseInt(v) : null; if (n !== c.trucks) handleCarrierUpdate(c.id, "trucks", n); }}
                                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                                              placeholder="0" style={{ width: 50, padding: "2px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                                          </div>
                                        </div>
                                      )}
                                      {/* Market badges */}
                                      {(c.markets || []).length > 0 && (
                                        <div style={{ display: "flex", gap: 3, marginBottom: 8, flexWrap: "wrap" }}>
                                          {c.markets.map(m => (
                                            <span key={m} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 600, background: "rgba(59,130,246,0.1)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.2)" }}>{m}</span>
                                          ))}
                                        </div>
                                      )}
                                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                                        <div>
                                          {editInput("Email", "contact_email", { color: "#00D4AA", copyable: true, placeholder: "carrier@email.com" })}
                                          {editInput("Phone", "contact_phone", { placeholder: "555-123-4567" })}
                                          {editInput("MC#", "mc_number", { placeholder: "MC number" })}
                                          {editInput("Equipment", "equipment_types", { placeholder: "Dry Van, Flatbed..." })}
                                          {editInput("Insurance", "insurance_info", { placeholder: "Insurance details" })}
                                        </div>
                                        <div>
                                          {editInput("Feedback", "service_feedback", { placeholder: "Good Rates, Reliable..." })}
                                          {editInput("Notes", "service_notes", { placeholder: "Operational notes" })}
                                          {editInput("Record", "service_record", { placeholder: "Worked with Previously" })}
                                          {editInput("Comments", "comments", { color: c.dnu ? "#f87171" : "#C8D0DC", placeholder: "General comments" })}
                                        </div>
                                      </div>
                                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 8 }}>
                                        <button onClick={e => { e.stopPropagation(); setEditingCarrierId(isEdit ? null : c.id); }}
                                          style={{ padding: "3px 10px", borderRadius: 5, border: isEdit ? "1px solid rgba(0,212,170,0.3)" : "1px solid rgba(255,255,255,0.06)", background: "transparent", color: isEdit ? "#00D4AA" : "#5A6478", fontSize: 10, cursor: "pointer", fontFamily: "inherit" }}>
                                          {isEdit ? "Done" : "Edit"}
                                        </button>
                                        {isEdit && (
                                          deleteConfirm === c.id ? (
                                            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                              <span style={{ fontSize: 10, color: "#f87171" }}>Delete?</span>
                                              <button onClick={e => { e.stopPropagation(); handleDeleteCarrier(c.id); }}
                                                style={{ padding: "3px 10px", borderRadius: 5, border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.15)", color: "#f87171", fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                                Confirm
                                              </button>
                                              <button onClick={e => { e.stopPropagation(); setDeleteConfirm(null); }}
                                                style={{ padding: "3px 10px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 10, cursor: "pointer", fontFamily: "inherit" }}>
                                                Cancel
                                              </button>
                                            </div>
                                          ) : (
                                            <button onClick={e => { e.stopPropagation(); setDeleteConfirm(c.id); }}
                                              style={{ padding: "3px 10px", borderRadius: 5, border: "1px solid rgba(239,68,68,0.2)", background: "transparent", color: "#f87171", fontSize: 10, cursor: "pointer", fontFamily: "inherit", opacity: 0.7 }}>
                                              Delete
                                            </button>
                                          )
                                        )}
                                      </div>
                                    </div>
                                  );
                                })()}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* ── Flat list view (original) ── */}
          {!dirGroupView && filteredDir.slice(0, 100).map((c, i) => {
            const isExp = dirExpanded === (c.id || i);
            const tierColors = { 1: { bg: "rgba(34,197,94,0.12)", color: "#34d399", label: "Tier 1" }, 2: { bg: "rgba(245,158,11,0.12)", color: "#FBBF24", label: "Tier 2" }, 3: { bg: "rgba(251,146,60,0.12)", color: "#fb923c", label: "Tier 3" }, 0: { bg: "rgba(239,68,68,0.12)", color: "#f87171", label: "DNU" } };
            const tier = tierColors[c.tier_rank] || { bg: "rgba(107,114,128,0.08)", color: "#6B7280", label: "Unranked" };
            const isEdit = editingCarrierId === c.id;
            return (
              <div key={c.id || i} className="glass" style={{ borderRadius: 10, overflow: "hidden", border: isExp ? "1px solid rgba(0,212,170,0.2)" : c.dnu ? "1px solid rgba(239,68,68,0.15)" : "1px solid rgba(255,255,255,0.04)" }}>
                <div onClick={() => setDirExpanded(isExp ? null : (c.id || i))} style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12, transition: "background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: c.dnu ? "#f87171" : "#F0F2F5", textDecoration: c.dnu ? "line-through" : "none" }}>{c.carrier_name}</span>
                      {c.mc_number && <span style={{ fontSize: 11, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{c.mc_number}</span>}
                    </div>
                    <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
                      {isEdit ? (
                        CAP_OPTIONS.map(cap => (
                          <span key={cap.key} onClick={e => { e.stopPropagation(); handleCarrierUpdate(c.id, cap.key, !c[cap.key]); }}
                            style={{ padding: "1px 7px", borderRadius: 4, fontSize: 8, fontWeight: 700, cursor: "pointer", transition: "all 0.15s",
                              background: c[cap.key] ? cap.color + "18" : "rgba(255,255,255,0.02)", color: c[cap.key] ? cap.color : "#3D4557",
                              border: `1px solid ${c[cap.key] ? cap.color + "30" : "rgba(255,255,255,0.06)"}` }}>{cap.label}</span>
                        ))
                      ) : (
                        CAP_OPTIONS.filter(cap => c[cap.key]).map(cap => (
                          <span key={cap.key} style={{ padding: "1px 7px", borderRadius: 4, fontSize: 8, fontWeight: 700, background: cap.color + "18", color: cap.color, border: `1px solid ${cap.color}30` }}>{cap.label}</span>
                        ))
                      )}
                    </div>
                  </div>
                  <button onClick={e => { e.stopPropagation(); setEditingCarrierId(isEdit ? null : c.id); if (!isExp) setDirExpanded(c.id || i); }}
                    title="Edit carrier" style={{ padding: "3px 8px", borderRadius: 6, border: isEdit ? "1px solid rgba(0,212,170,0.4)" : "1px solid rgba(255,255,255,0.06)", background: isEdit ? "rgba(0,212,170,0.1)" : "transparent", color: isEdit ? "#00D4AA" : "#5A6478", fontSize: 11, cursor: "pointer", fontFamily: "inherit", flexShrink: 0, transition: "all 0.15s" }}>
                    {isEdit ? "Done" : "✏️"}
                  </button>
                  {isEdit ? (
                    <select value={c.tier_rank ?? ""} onClick={e => e.stopPropagation()}
                      onChange={e => { const v = e.target.value === "" ? null : parseInt(e.target.value); handleCarrierUpdate(c.id, "tier_rank", v); if (v === 0) handleCarrierUpdate(c.id, "dnu", true); else if (c.dnu) handleCarrierUpdate(c.id, "dnu", false); }}
                      style={{ padding: "3px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: "#151926", color: tier.color, border: `1px solid ${tier.color}30`, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 }}>
                      <option value="" style={{ background: "#151926", color: "#6B7280" }}>Unranked</option>
                      <option value="1" style={{ background: "#151926", color: "#34d399" }}>Tier 1</option>
                      <option value="2" style={{ background: "#151926", color: "#FBBF24" }}>Tier 2</option>
                      <option value="3" style={{ background: "#151926", color: "#fb923c" }}>Tier 3</option>
                      <option value="0" style={{ background: "#151926", color: "#f87171" }}>DNU</option>
                    </select>
                  ) : (
                    <span style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, background: tier.bg, color: tier.color, border: `1px solid ${tier.color}30`, flexShrink: 0 }}>{tier.label}</span>
                  )}
                  <div style={{ display: "flex", gap: 3, flexShrink: 0, flexWrap: "wrap", maxWidth: 200 }}>
                    {(c.markets || []).slice(0, 4).map(m => (
                      <span key={m} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 8, fontWeight: 600, background: "rgba(59,130,246,0.1)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.2)" }}>{m}</span>
                    ))}
                    {(c.markets || []).length > 4 && <span style={{ fontSize: 8, color: "#5A6478" }}>+{c.markets.length - 4}</span>}
                  </div>
                  {c.trucks && <div style={{ textAlign: "center", minWidth: 36, flexShrink: 0 }}><div style={{ fontSize: 13, fontWeight: 800, color: "#F0F2F5" }}>{c.trucks}</div><div style={{ fontSize: 7, color: "#5A6478", fontWeight: 600 }}>TRUCKS</div></div>}
                  <span style={{ color: "#5A6478", fontSize: 12, transition: "transform 0.2s", transform: isExp ? "rotate(180deg)" : "rotate(0)", flexShrink: 0 }}>▼</span>
                </div>
                {isExp && (() => {
                  const editInput = (label, field, opts = {}) => {
                    const val = c[field] || "";
                    if (!isEdit && !val) return null;
                    const iStyle = { width: "100%", padding: "3px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
                    return (
                      <div style={{ fontSize: 11, marginBottom: 4 }}>
                        <span style={{ color: "#5A6478" }}>{label}: </span>
                        {isEdit ? (
                          <input defaultValue={val} key={val} onClick={e => e.stopPropagation()}
                            onBlur={e => { const v = e.target.value.trim(); if (v !== (c[field] || "")) handleCarrierUpdate(c.id, field, v || null); }}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                            placeholder={opts.placeholder || ""} style={iStyle} />
                        ) : (
                          <span style={{ color: opts.color || "#C8D0DC", cursor: opts.copyable ? "pointer" : "default" }}
                            onClick={opts.copyable ? (e => { e.stopPropagation(); navigator.clipboard.writeText(val); }) : undefined}>
                            {val}{opts.copyable ? " 📋" : ""}
                          </span>
                        )}
                      </div>
                    );
                  };
                  return (
                    <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", padding: "12px 14px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <div>
                        {editInput("Email", "contact_email", { color: "#00D4AA", copyable: true, placeholder: "carrier@email.com" })}
                        {editInput("Phone", "contact_phone", { placeholder: "555-123-4567" })}
                        {editInput("MC#", "mc_number", { placeholder: "MC number" })}
                        {editInput("Equipment", "equipment_types", { placeholder: "Dry Van, Flatbed..." })}
                        {editInput("Insurance", "insurance_info", { placeholder: "Insurance details" })}
                        {isEdit && (
                          <div style={{ fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: "#5A6478" }}>Trucks: </span>
                            <input type="number" defaultValue={c.trucks || ""} key={c.trucks} onClick={e => e.stopPropagation()}
                              onBlur={e => { const v = e.target.value.trim(); const n = v ? parseInt(v) : null; if (n !== c.trucks) handleCarrierUpdate(c.id, "trucks", n); }}
                              onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                              placeholder="0" style={{ width: 60, padding: "3px 6px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                          </div>
                        )}
                      </div>
                      <div>
                        {editInput("Feedback", "service_feedback", { placeholder: "Good Rates, Reliable..." })}
                        {editInput("Notes", "service_notes", { placeholder: "Operational notes" })}
                        {editInput("Record", "service_record", { placeholder: "Worked with Previously" })}
                        {editInput("Comments", "comments", { color: c.dnu ? "#f87171" : "#C8D0DC", placeholder: "General comments" })}
                      </div>
                      {isEdit && (
                        <div style={{ gridColumn: "1 / -1", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 8, display: "flex", justifyContent: "flex-end" }}>
                          {deleteConfirm === c.id ? (
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <span style={{ fontSize: 11, color: "#f87171" }}>Delete this carrier?</span>
                              <button onClick={e => { e.stopPropagation(); handleDeleteCarrier(c.id); }}
                                style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.15)", color: "#f87171", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                                Confirm Delete
                              </button>
                              <button onClick={e => { e.stopPropagation(); setDeleteConfirm(null); }}
                                style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button onClick={e => { e.stopPropagation(); setDeleteConfirm(c.id); }}
                              style={{ padding: "4px 12px", borderRadius: 6, border: "1px solid rgba(239,68,68,0.2)", background: "transparent", color: "#f87171", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", opacity: 0.7 }}>
                              Delete Carrier
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            );
          })}
          {!dirGroupView && filteredDir.length > 100 && <div style={{ padding: 12, textAlign: "center", color: "#5A6478", fontSize: 11 }}>Showing 100 of {filteredDir.length} carriers. Refine your search.</div>}
        </div>
      </div>
    );
  }

  // ═════════════════════════════════════════════════════════════
  // HISTORY VIEW
  // ═════════════════════════════════════════════════════════════
  if (view === "history") {
    return (
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <button onClick={() => setView("browse")}
            style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", fontSize: 16, cursor: "pointer", fontFamily: "inherit", lineHeight: 1 }}>
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>Rate History</h2>
        </div>
        <HistoryTabContent rateHistory={rateHistory} historyLoading={historyLoading}
          onLoad={async () => {
            if (rateHistory.length > 0) return;
            setHistoryLoading(true);
            try {
              const res = await apiFetch(`${API_BASE}/api/rate-history?limit=200`);
              const data = await res.json();
              setRateHistory(data.history || []);
            } catch (e) { console.error("Rate history fetch:", e); }
            setHistoryLoading(false);
          }} />
      </div>
    );
  }

  return null;
}
