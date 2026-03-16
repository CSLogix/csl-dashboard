import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../store";
import { apiFetch, API_BASE } from "../helpers/api";
import {
  STATUSES, FTL_STATUSES, BILLING_STATUSES, BILLING_STATUS_COLORS,
  DOC_TYPES_ADD, DOC_TYPE_LABELS, Z, DRAY_EQUIPMENT, FTL_EQUIPMENT, TRUCK_TYPES,
} from "../helpers/constants";
import {
  isFTLShipment, getStatusesForShipment, getStatusColors, resolveStatusLabel, resolveStatusColor,
  calcMarginPct, formatDDMM, fmtDateDisplay, splitDateTime, parseDDMM, parseMMDD, formatMMDD,
  getBillingReadiness, useIsMobile, parseTerminalNotes,
} from "../helpers/utils";
import TerminalBadge from "../components/TerminalBadge";
import DocIndicators from "../components/DocIndicators";
import TrackingBadge from "../components/TrackingBadge";

export default function LoadSlideOver({ selectedShipment, setSelectedShipment, shipments, setShipments, handleStatusUpdate, editField, setEditField, editValue, setEditValue, handleFieldEdit, addSheetLog, carrierDirectory, onDocChange, isMobile, expandEmailsOnOpen, onConsumeExpandEmails, handleFieldUpdate, handleMetadataUpdate, handleApplyRate }) {
  const docInputRef = useRef(null);
  const emailsSectionRef = useRef(null);

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
  const [copiedLink, setCopiedLink] = useState(false);
  const [linkGenerating, setLinkGenerating] = useState(false);

  // Driver contact state
  const [driverInfo, setDriverInfo] = useState({ driverName: "", driverPhone: "", driverEmail: "", carrierEmail: "", trailerNumber: "", macropointUrl: "" });
  const [driverEditing, setDriverEditing] = useState(null); // which field is being edited
  const [driverEditVal, setDriverEditVal] = useState("");
  const [driverSaving, setDriverSaving] = useState(false);
  const [statusExpanded, setStatusExpanded] = useState(false);
  const [emailsCollapsed, setEmailsCollapsed] = useState(false);
  const [aiSummary, setAiSummary] = useState(null);
  const [aiSummaryLoading, setAiSummaryLoading] = useState(false);

  // Timestamped notes log state
  const [loadNotes, setLoadNotes] = useState([]);
  const [noteInput, setNoteInput] = useState("");
  const [noteSubmitting, setNoteSubmitting] = useState(false);

  // Rate quote suggestions (Margin Bridge)
  const [loadRateQuotes, setLoadRateQuotes] = useState([]);
  const [rateApplied, setRateApplied] = useState(false);
  const [rateDismissed, setRateDismissed] = useState(false);

  // EFJ edit state
  const [editingEfj, setEditingEfj] = useState(false);
  const [efjEditVal, setEfjEditVal] = useState("");
  // Macropoint URL edit state
  const [editingMpUrl, setEditingMpUrl] = useState(false);
  const [mpUrlVal, setMpUrlVal] = useState("");
  // Overflow menu state
  const [showOverflow, setShowOverflow] = useState(false);
  const overflowRef = useRef(null);
  // Delete confirmation state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Save feedback toast
  const [saveToast, setSaveToast] = useState(null); // { message, type: "success"|"error" }
  const saveToastTimer = useRef(null);
  const showSaveToast = (message, type = "success") => {
    if (saveToastTimer.current) clearTimeout(saveToastTimer.current);
    setSaveToast({ message, type });
    saveToastTimer.current = setTimeout(() => setSaveToast(null), 2200);
  };

  // Close overflow menu on outside click
  useEffect(() => {
    if (!showOverflow) return;
    const handler = (e) => { if (overflowRef.current && !overflowRef.current.contains(e.target)) setShowOverflow(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showOverflow]);

  // Auto-expand emails section + scroll when opened from NEEDS REPLY
  useEffect(() => {
    if (expandEmailsOnOpen && loadEmails.length > 0) {
      setEmailsCollapsed(false);
      onConsumeExpandEmails?.();
      // Wait a tick for the section to render, then scroll
      requestAnimationFrame(() => {
        emailsSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [expandEmailsOnOpen, loadEmails.length]);

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
      setLoadRateQuotes([]);
      setRateApplied(false);
      setRateDismissed(false);
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
    // Fetch rate quotes for Margin Bridge suggestions
    apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/rate-quotes`)
      .then(r => r.ok ? r.json() : { quotes: [] })
      .then(data => { setLoadRateQuotes(data.quotes || []); setRateApplied(false); setRateDismissed(false); })
      .catch(() => setLoadRateQuotes([]));
    // Fetch tracking for FTL loads — sync back to global trackingSummary
    if (selectedShipment.moveType === "FTL" || selectedShipment.macropointUrl) {
      setTrackingLoading(true);
      apiFetch(`${API_BASE}/api/macropoint/${selectedShipment.efj}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data) {
            setTrackingData(data);
            // Push fresh MP data into global store so dispatch table updates immediately
            const efjBare = (selectedShipment.efj || "").replace(/^EFJ\s*/i, "");
            const { setTrackingSummary } = useAppStore.getState();
            setTrackingSummary(prev => ({ ...prev, [efjBare]: { ...prev[efjBare], mpStatus: data.mpStatus || data.status, mpDisplayStatus: data.mpDisplayStatus || data.display_status, mpDisplayDetail: data.mpDisplayDetail || data.display_detail, mpLastUpdated: data.mpLastUpdated || data.last_updated } }));
          }
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

  const DRIVER_LABELS = { driverName: "Driver", driverPhone: "Phone", driverEmail: "Driver Email", carrierEmail: "Carrier Email", trailerNumber: "Trailer", macropointUrl: "MP URL" };
  const saveDriverField = async (field, value) => {
    if (!selectedShipment?.efj) return;
    setDriverSaving(true);
    try {
      const r = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/driver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      if (r.ok) {
        setDriverInfo(prev => ({ ...prev, [field]: value }));
        showSaveToast?.(`${DRIVER_LABELS[field] || field} saved`);
      } else { showSaveToast?.(`Failed to save ${DRIVER_LABELS[field] || field}`, "error"); }
    } catch { showSaveToast?.(`Failed to save ${DRIVER_LABELS[field] || field}`, "error"); }
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

  const handleDeleteLoad = async () => {
    setDeleting(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/v2/load/${selectedShipment.efj}`, { method: "DELETE" });
      if (!res.ok) { const txt = await res.text(); throw new Error(txt); }
      addSheetLog(`Deleted load | ${selectedShipment.efj}`);
      // Remove from local state
      setShipments(prev => prev.filter(s => s.efj !== selectedShipment.efj));
      setSelectedShipment(null);
      setShowDeleteConfirm(false);
    } catch (err) {
      showSaveToast(`Delete failed: ${err.message}`, "error");
    }
    setDeleting(false);
  };

  const handleShareLink = async () => {
    if (linkGenerating) return;
    setLinkGenerating(true);
    try {
      const r = await apiFetch(`/api/shipments/${selectedShipment.efj}/generate-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ show_driver: false }),
      });
      if (r.ok) {
        const data = await r.json();
        navigator.clipboard.writeText(data.url);
        setCopiedLink(true);
        setTimeout(() => setCopiedLink(false), 2000);
      }
    } catch (e) {
      console.error("Share link failed", e);
    } finally {
      setLinkGenerating(false);
    }
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
          subject: e.subject, sender: e.sender, body_preview: e.body_text || e.body_preview,
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
        const rData = await r.json();
        setDocUploadMsg("Uploaded");
        // Refresh doc list
        const listRes = await apiFetch(`${API_BASE}/api/load/${selectedShipment.efj}/documents`);
        if (listRes.ok) { const data = await listRes.json(); setLoadDocs(data.documents || []); }
        addSheetLog(`Doc uploaded | ${selectedShipment.loadNumber}`);
        onDocChange?.();
        // Auto-status advance (e.g., POD upload → pod_received)
        if (rData.auto_status) {
          handleStatusUpdate(selectedShipment.efj, rData.auto_status);
          setDocUploadMsg(`Uploaded — status → ${rData.auto_status.replace(/_/g, " ")}`);
        }
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
      <div aria-hidden="true" onClick={() => setSelectedShipment(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: Z.panelBackdrop, animation: "fade-in 0.2s ease" }} />
      <div role="dialog" aria-modal="true" aria-label={`Shipment details — ${selectedShipment.loadNumber}`} className="glass-strong" style={{ position: "fixed", top: 0, right: 0, width: isMobile ? "100vw" : 380, height: "100vh", zIndex: Z.panel, display: "flex", flexDirection: "column", overflow: "hidden", animation: "slide-right 0.3s ease", borderLeft: isMobile ? "none" : "1px solid rgba(255,255,255,0.08)" }}>
        <div style={{ flex: 1, overflow: "auto" }}>
          {/* Header */}
          <div style={{ padding: "18px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              {editingEfj ? (
                <input autoFocus value={efjEditVal} onChange={e => setEfjEditVal(e.target.value)}
                  onBlur={() => { if (efjEditVal.trim() && efjEditVal !== selectedShipment.efj) { handleFieldUpdate(selectedShipment, "efj", efjEditVal, { toast: showSaveToast }); } setEditingEfj(false); }}
                  onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditingEfj(false); }}
                  style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 800, color: "#00D4AA", background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, padding: "2px 8px", outline: "none", width: "100%" }} />
              ) : (
                <div onClick={() => { setEditingEfj(true); setEfjEditVal(selectedShipment.efj || ""); }}
                  style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 800, color: "#F0F2F5", cursor: "text" }} title="Click to edit EFJ #">{selectedShipment.loadNumber}</div>
              )}
              <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 2 }}>{selectedShipment.container} | {selectedShipment.moveType}</div>
              {selectedShipment.playbookLaneCode && (
                <div style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 4, padding: "2px 8px", borderRadius: 4, background: "rgba(0,212,170,0.12)", border: "1px solid rgba(0,212,170,0.25)", cursor: "pointer" }} title={`Playbook: ${selectedShipment.playbookLaneCode}`} onClick={() => { /* Could nav to playbook */ }}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#00D4AA" strokeWidth="2.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#00D4AA", letterSpacing: "0.03em" }}>{selectedShipment.playbookLaneCode}</span>
                </div>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: selectedShipment.synced ? "#34d399" : "#fbbf24", animation: selectedShipment.synced ? "none" : "pulse 1s ease infinite" }} />
                <span style={{ fontSize: 11, color: selectedShipment.synced ? "#34d399" : "#fbbf24", fontWeight: 600 }}>{selectedShipment.synced ? "All changes saved" : "Saving..."}</span>
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
            <button onClick={() => setSelectedShipment(null)} aria-label="Close shipment details" style={{ background: "rgba(255,255,255,0.05)", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 14, width: 28, height: 28, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>&#x2715;</button>
          </div>

          {/* Quick Action Strip — 4 primary + overflow */}
          <div style={{ padding: "8px 20px 10px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", gap: 6, alignItems: "center" }}>
            {[
              { icon: "\u2726", label: aiSummaryLoading ? "Thinking..." : "AI Summary",
                color: aiSummaryLoading ? "#fbbf24" : "#00D4AA",
                onClick: () => { requestAiSummary(); }, enabled: !aiSummaryLoading },
              { icon: "\u{1F4CD}", label: "Tracking", color: "#3B82F6",
                onClick: () => { const url = trackingData?.macropointUrl || driverInfo.macropointUrl || selectedShipment.macropointUrl; if (url) window.open(url, '_blank'); },
                enabled: !!(trackingData?.macropointUrl || driverInfo.macropointUrl || selectedShipment.macropointUrl) },
              { icon: "\u{1F4DE}", label: "Call", color: "#10b981",
                onClick: () => { if (driverInfo.driverPhone) window.open(`tel:${driverInfo.driverPhone.replace(/\D/g, "")}`); },
                enabled: !!driverInfo.driverPhone },
            ].map((btn, i) => (
              <button key={i} onClick={btn.enabled ? btn.onClick : undefined}
                style={{ background: btn.enabled ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.02)", border: `1px solid ${btn.enabled ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.04)"}`,
                  borderRadius: 6, padding: "5px 10px", cursor: btn.enabled ? "pointer" : "default",
                  color: btn.enabled ? btn.color : "rgba(255,255,255,0.2)", fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 600,
                  transition: "all 0.15s ease", opacity: btn.enabled ? 1 : 0.5 }}
                title={!btn.enabled ? "Not available" : btn.label}
              >{btn.icon} {btn.label}</button>
            ))}
            {/* Overflow menu */}
            <div ref={overflowRef} style={{ position: "relative", marginLeft: "auto" }}>
              <button onClick={() => setShowOverflow(v => !v)}
                style={{ background: showOverflow ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)",
                  borderRadius: 6, padding: "5px 10px", cursor: "pointer", color: "rgba(255,255,255,0.5)", fontSize: 12, fontWeight: 700,
                  fontFamily: "'Plus Jakarta Sans', sans-serif", transition: "all 0.15s ease", letterSpacing: 1 }}
                title="More actions">{"\u22EF"}</button>
              {showOverflow && (
                <div style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", background: "#1E2536", border: "1px solid rgba(255,255,255,0.10)",
                  borderRadius: 8, padding: 4, minWidth: 170, zIndex: 50, boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}>
                  {[
                    { icon: "\u{1F4CB}", label: copiedEfj ? "Copied!" : "Copy EFJ", color: copiedEfj ? "#34d399" : "rgba(255,255,255,0.6)",
                      onClick: () => { navigator.clipboard.writeText(selectedShipment.efj); setCopiedEfj(true); setTimeout(() => setCopiedEfj(false), 1500); setShowOverflow(false); }, enabled: true },
                    { icon: "\u{1F4E7}", label: "Email", color: "#00D4AA",
                      onClick: () => { const email = driverInfo.carrierEmail || driverInfo.driverEmail; if (email) { window.open(`mailto:${email}?subject=${encodeURIComponent(`${selectedShipment.loadNumber} - ${selectedShipment.container} Update`)}`); setShowOverflow(false); } },
                      enabled: !!(driverInfo.carrierEmail || driverInfo.driverEmail) },
                    { icon: "\u{1F4C4}", label: "View BOL", color: "rgba(255,255,255,0.6)",
                      onClick: () => { const bol = loadDocs.find(d => d.doc_type === 'bol'); if (bol) { setPreviewDoc(bol); setShowOverflow(false); } },
                      enabled: loadDocs.some(d => d.doc_type === 'bol') },
                    { icon: "\u{1F517}", label: linkGenerating ? "Generating..." : copiedLink ? "Copied!" : "Share Link",
                      color: copiedLink ? "#34d399" : linkGenerating ? "#fbbf24" : "#a78bfa",
                      onClick: () => { handleShareLink(); }, enabled: !linkGenerating },
                    { icon: "\u270F\uFE0F", label: editingMpUrl ? "Cancel Edit URL" : "Edit MP URL", color: "#8B5CF6",
                      onClick: () => { if (editingMpUrl) { setEditingMpUrl(false); } else { setMpUrlVal(driverInfo.macropointUrl || selectedShipment.macropointUrl || ""); setEditingMpUrl(true); } setShowOverflow(false); },
                      enabled: true },
                    { icon: "\u{1F5D1}\uFE0F", label: "Delete Load", color: "#EF4444",
                      onClick: () => { setShowDeleteConfirm(true); setShowOverflow(false); },
                      enabled: true },
                  ].map((item, i) => (
                    <button key={i} onClick={item.enabled ? item.onClick : undefined}
                      style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", background: "transparent", border: "none",
                        borderRadius: 6, padding: "7px 10px", cursor: item.enabled ? "pointer" : "default", color: item.enabled ? item.color : "rgba(255,255,255,0.2)",
                        fontSize: 11, fontFamily: "'Plus Jakarta Sans', sans-serif", fontWeight: 500, textAlign: "left", opacity: item.enabled ? 1 : 0.5,
                        transition: "background 0.12s" }}
                      onMouseEnter={e => { if (item.enabled) e.target.style.background = "rgba(255,255,255,0.06)"; }}
                      onMouseLeave={e => { e.target.style.background = "transparent"; }}
                    ><span style={{ fontSize: 13 }}>{item.icon}</span> {item.label}</button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* MP URL Edit — inline input */}
          {editingMpUrl && (
            <div style={{ padding: "8px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", gap: 6, alignItems: "center" }}>
              <input value={mpUrlVal} onChange={e => setMpUrlVal(e.target.value)} placeholder="https://visibility.macropoint.com/..."
                style={{ flex: 1, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(139,92,246,0.3)", borderRadius: 6, padding: "6px 10px", color: "#F0F2F5", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none" }}
                onKeyDown={e => { if (e.key === "Enter") { saveDriverField("macropointUrl", mpUrlVal); setEditingMpUrl(false); } if (e.key === "Escape") setEditingMpUrl(false); }}
                autoFocus />
              <button onClick={() => { saveDriverField("macropointUrl", mpUrlVal); setEditingMpUrl(false); }}
                style={{ background: "#8B5CF6", border: "none", borderRadius: 6, padding: "6px 12px", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Save</button>
            </div>
          )}

          {/* AI Summary — inline section */}
          {(aiSummary || aiSummaryLoading) && (
            <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              {aiSummaryLoading ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 8, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}>
                  <div style={{ width: 12, height: 12, border: "2px solid rgba(0,212,170,0.2)", borderTop: "2px solid #00D4AA", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
                  <span style={{ fontSize: 11, color: "#00D4AA", fontWeight: 600 }}>Generating AI summary...</span>
                </div>
              ) : (
                <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)", position: "relative" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#00D4AA", textTransform: "uppercase", letterSpacing: "0.05em" }}>AI Summary</span>
                    <button onClick={() => setAiSummary(null)} style={{ background: "none", border: "none", color: "#5A6478", cursor: "pointer", fontSize: 12, padding: "0 2px", lineHeight: 1 }} title="Dismiss">&#x2715;</button>
                  </div>
                  <div style={{ fontSize: 11, color: "#C8CED8", lineHeight: 1.6, whiteSpace: "pre-line" }}>{aiSummary}</div>
                </div>
              )}
            </div>
          )}

          {/* Behind schedule / Can't make it warnings — FTL only */}
          {selectedShipment.moveType === "FTL" && trackingData?.cantMakeIt && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#f87171", fontWeight: 600 }}>
                {"\u26A0"} {trackingData.cantMakeIt}
              </div>
            </div>
          )}
          {selectedShipment.moveType === "FTL" && trackingData?.behindSchedule && !trackingData?.cantMakeIt && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(251,146,60,0.12)", border: "1px solid rgba(251,146,60,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#fb923c", fontWeight: 600 }}>
                {"\u23F1"} Behind Schedule{trackingData?.mpDisplayDetail ? ` \u2014 ${trackingData.mpDisplayDetail}` : ""}
              </div>
            </div>
          )}
          {selectedShipment.moveType === "FTL" && trackingData?.mpDisplayStatus === "On Time" && !trackingData?.cantMakeIt && !trackingData?.behindSchedule && trackingData?.mpDisplayDetail && (
            <div style={{ padding: "0 20px 8px" }}>
              <div style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)", display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#22C55E", fontWeight: 600 }}>
                {"\u2713"} On Time {"\u2014"} {trackingData.mpDisplayDetail}
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
            const mono = { fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 600 };
            const headerCell = { fontSize: 7, fontWeight: 700, color: "#5A6478", letterSpacing: "1px", textTransform: "uppercase", padding: "0 0 3px", textAlign: "right" };
            const valCell = { ...mono, padding: "2px 0", textAlign: "right" };
            return (
            <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Schedule & Tracking</div>
              <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr 1fr", gap: "0 10px", alignItems: "center" }}>
                {/* Header row */}
                <div />
                <div style={headerCell}>Sched</div>
                <div style={headerCell}>Arrived</div>
                <div style={headerCell}>Departed</div>
                {/* Pickup row */}
                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#f59e0b", flexShrink: 0 }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#F0F2F5" }}>PU</span>
                  {origin && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{origin.length > 18 ? origin.slice(0, 18) + "\u2026" : origin}</span>}
                </div>
                <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.pickupDate) || "\u2014"}</div>
                <div style={{ ...valCell, color: parsedStops.pickup.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.pickup.arrived) || "\u2014"}</div>
                <div style={{ ...valCell, color: parsedStops.pickup.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.pickup.departed) || "\u2014"}</div>
                {/* Delivery row */}
                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 0", whiteSpace: "nowrap" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#10b981", flexShrink: 0 }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#F0F2F5" }}>DEL</span>
                  {dest && <span style={{ fontSize: 8, color: "#5A6478", overflow: "hidden", textOverflow: "ellipsis" }}>{dest.length > 18 ? dest.slice(0, 18) + "\u2026" : dest}</span>}
                </div>
                <div style={{ ...valCell, color: "#C8CED8" }}>{fmtTs(selectedShipment.deliveryDate) || "\u2014"}</div>
                <div style={{ ...valCell, color: parsedStops.delivery.arrived ? "#34d399" : "#2A3040" }}>{fmtTs(parsedStops.delivery.arrived) || "\u2014"}</div>
                <div style={{ ...valCell, color: parsedStops.delivery.departed ? "#60a5fa" : "#2A3040" }}>{fmtTs(parsedStops.delivery.departed) || "\u2014"}</div>
              </div>
              {/* Delivered confirmation */}
              {parsedStops.delivered && (
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#00D4AA", flexShrink: 0 }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#00D4AA" }}>Delivered</span>
                  {parsedStops.deliveredLocation && <span style={{ fontSize: 8, color: "#5A6478" }}>{parsedStops.deliveredLocation}</span>}
                  <span style={{ marginLeft: "auto", ...mono, fontSize: 11, color: "#8B95A8" }}>{fmtTs(parsedStops.delivered)}</span>
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
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>Status</span>
                    {!statusExpanded && activeStatus && (
                      <span style={{ padding: "3px 10px", fontSize: 11, fontWeight: 700, borderRadius: 20,
                        border: `1px solid ${activeColor}66`, background: `${activeColor}18`, color: activeColor,
                        fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{activeStatus.label}</span>
                    )}
                  </div>
                  <span style={{ fontSize: 11, color: "#5A6478", transition: "transform 0.15s" }}>{statusExpanded ? "\u25BE" : "\u25B8"}</span>
                </div>
                {statusExpanded && (
                  <>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
                      {getStatusesForShipment(selectedShipment).filter(s => s.key !== "all").map(s => {
                        const isActive = selectedShipment.status === s.key;
                        const sc2 = getStatusColors(selectedShipment)[s.key] || { main: "#94a3b8" };
                        return (
                          <button key={s.key} onClick={() => handleStatusUpdate(selectedShipment.id, s.key)}
                            style={{ padding: "4px 10px", fontSize: 11, fontWeight: 700, borderRadius: 20,
                              border: `1px solid ${isActive ? sc2.main + "66" : "rgba(255,255,255,0.06)"}`,
                              background: isActive ? `${sc2.main}18` : "transparent",
                              color: isActive ? sc2.main : "#64748b", cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{s.label}</button>
                        );
                      })}
                    </div>
                    {(true) && (
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
                ];
              })(),
              { label: "Move Type", field: "moveType", val: selectedShipment.moveType },
              { label: "Origin", field: "origin", val: selectedShipment.origin },
              { label: "Destination", field: "destination", val: selectedShipment.destination },
              ...(selectedShipment.moveType !== "FTL" ? [
                { label: "ETA", field: "eta", val: selectedShipment.eta },
                { label: "LFD", field: "lfd", val: selectedShipment.lfd },
              ] : []),
              { label: "Pickup", field: "pickupDate", val: fmtDateDisplay(selectedShipment.pickupDate) },
              { label: "Delivery", field: "deliveryDate", val: fmtDateDisplay(selectedShipment.deliveryDate) },
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
                <span style={{ fontSize: 11, color: "#8B95A8", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{item.label}</span>
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
                        if (pgField && selectedShipment.efj) { handleFieldUpdate(selectedShipment, pgField, v, { toast: showSaveToast }); }
                        else { handleFieldEdit(selectedShipment.id, item.field, v); }
                      }
                      setEditField(null);
                    }}
                    onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditField(null); }}
                    style={{ background: "rgba(0,212,170,0.1)", border: "1px solid #00D4AA44", borderRadius: 6, color: "#F0F2F5", padding: "3px 8px", fontSize: 11, width: 140, textAlign: "right", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
                ) : (
                  <span onClick={(e) => { e.stopPropagation(); setEditField(`${selectedShipment.id}-${item.field}`); setEditValue(String(item.val || "")); }}
                    style={{ fontSize: 11, color: "#F0F2F5", cursor: "pointer", padding: "2px 6px", borderRadius: 4, fontWeight: 500 }}
                    title="Click to edit">{item.val || "\u2014"}</span>
                )}
              </div>
            ))}
          </div>

          {/* Terminal Ground Truth */}
          {parseTerminalNotes(selectedShipment.botAlert) && (() => {
            const t = parseTerminalNotes(selectedShipment.botAlert);
            const hasHold = t.hasHolds;
            return (
              <div style={{ padding: "10px 20px 12px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <div style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  background: hasHold ? "rgba(239,68,68,0.08)" : "rgba(56,189,248,0.08)",
                  border: `1px solid ${hasHold ? "rgba(239,68,68,0.25)" : "rgba(56,189,248,0.25)"}`,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.1em", color: hasHold ? "#f87171" : "#38bdf8" }}>
                      Terminal Ground Truth
                    </span>
                    <TerminalBadge notes={selectedShipment.notes} />
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#E5E7EB", lineHeight: 1.5 }}>
                    {selectedShipment.notes}
                  </div>
                  {t.vessel && (
                    <div style={{ marginTop: 8, fontSize: 11, color: "#9CA3AF" }}>
                      <strong style={{ color: "#6B7280" }}>Vessel:</strong> {t.vessel}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          {/* Financials */}
          <div style={{ padding: "8px 20px 12px" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>Financials</div>
            {/* Rate Quote Suggestion Banner (Margin Bridge) */}
            {(() => {
              const currentPay = shipments.find(s => s.id === selectedShipment.id)?.carrierPay;
              const bestQuote = loadRateQuotes.find(q => q.rate_amount && q.status === "accepted") || loadRateQuotes.find(q => q.rate_amount);
              if (!bestQuote || currentPay || rateApplied || rateDismissed) return null;
              const otherCount = loadRateQuotes.filter(q => q.rate_amount).length - 1;
              return (
                <div style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", marginBottom: 10,
                  background: "rgba(249,115,22,0.08)", borderLeft: "3px solid #F97316", borderRadius: 8,
                  animation: "fadeIn 0.3s ease"
                }}>
                  <span style={{ fontSize: 14 }}>{"\u{1F4A1}"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: "#E5E7EB", fontWeight: 600 }}>
                      {bestQuote.carrier_name || "Carrier"} {"\u2014"} <span style={{ color: "#F97316", fontFamily: "'JetBrains Mono', monospace" }}>${Number(bestQuote.rate_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 2 }}>
                      Rate detected from email{bestQuote.status === "accepted" ? " (accepted)" : ""}{otherCount > 0 ? ` \u00B7 +${otherCount} more` : ""}
                    </div>
                  </div>
                  <button
                    onClick={() => handleApplyRate(bestQuote, { onApplied: () => setRateApplied(true) })}
                    style={{
                      background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 6,
                      color: "#22C55E", fontSize: 11, fontWeight: 700, padding: "5px 10px", cursor: "pointer",
                      whiteSpace: "nowrap"
                    }}
                    onMouseEnter={e => { e.target.style.background = "rgba(34,197,94,0.25)"; }}
                    onMouseLeave={e => { e.target.style.background = "rgba(34,197,94,0.15)"; }}
                  >{"\u2713"} Apply</button>
                  <button
                    onClick={() => setRateDismissed(true)}
                    style={{
                      background: "transparent", border: "none", color: "#5A6478", fontSize: 12, cursor: "pointer",
                      padding: "2px 6px", lineHeight: 1
                    }}
                  >&#x2715;</button>
                </div>
              );
            })()}
            {/* Customer Rate Suggestion Banner */}
            {(() => {
              const currentCxRate = shipments.find(s => s.id === selectedShipment.id)?.customerRate;
              const cxQuote = loadRateQuotes.find(q => q.rate_amount && q.rate_type === "customer" && q.status !== "rejected");
              if (!cxQuote || currentCxRate || rateApplied || rateDismissed) return null;
              return (
                <div style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", marginBottom: 10,
                  background: "rgba(34,197,94,0.08)", borderLeft: "3px solid #22C55E", borderRadius: 8,
                  animation: "fadeIn 0.3s ease"
                }}>
                  <span style={{ fontSize: 14 }}>{"\u{1F4B0}"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: "#E5E7EB", fontWeight: 600 }}>
                      Customer Rate {"\u2014"} <span style={{ color: "#22C55E", fontFamily: "'JetBrains Mono', monospace" }}>${Number(cxQuote.rate_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "#8B95A8", marginTop: 2 }}>Extracted from customer email</div>
                  </div>
                  <button onClick={() => handleApplyRate({ ...cxQuote, _field: "customer_rate" }, { onApplied: () => setRateApplied(true) })}
                    style={{ background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 6,
                      color: "#22C55E", fontSize: 11, fontWeight: 700, padding: "5px 10px", cursor: "pointer", whiteSpace: "nowrap" }}>
                    {"\u2713"} Apply CX Rate
                  </button>
                  <button onClick={() => setRateDismissed(true)}
                    style={{ background: "transparent", border: "none", color: "#5A6478", fontSize: 12, cursor: "pointer", padding: "2px 6px", lineHeight: 1 }}>&#x2715;</button>
                </div>
              );
            })()}
            <div style={{ display: "flex", gap: 10 }}>
              {[
                { key: "customerRate", label: "CX Rate", color: "#22C55E" },
                { key: "carrierPay",   label: "RC Pay",  color: "#F97316" },
              ].map(({ key, label, color }) => {
                const live = shipments.find(s => s.id === selectedShipment.id)?.[key] || "";
                const margin = (() => {
                  const cx = parseFloat(shipments.find(s => s.id === selectedShipment.id)?.customerRate);
                  const rc = parseFloat(shipments.find(s => s.id === selectedShipment.id)?.carrierPay);
                  if (!cx || !rc || cx === 0) return null;
                  return ((cx - rc) / cx * 100).toFixed(1);
                })();
                return (
                  <div key={key} style={{ flex: 1 }}>
                    <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 4, fontWeight: 600 }}>{label}</div>
                    <div style={{ position: "relative" }}>
                      <span style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "#5A6478", fontSize: 11, pointerEvents: "none" }}>$</span>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        defaultValue={live}
                        key={live}
                        onBlur={e => { const v = e.target.value.trim(); handleMetadataUpdate(selectedShipment, key, v || null, { toast: showSaveToast }); }}
                        placeholder="0.00"
                        style={{ width: "100%", background: "rgba(255,255,255,0.04)", border: `1px solid rgba(255,255,255,0.08)`, borderRadius: 8, color: live ? color : "#5A6478", padding: "7px 10px 7px 20px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, outline: "none", boxSizing: "border-box" }}
                        onFocus={e => e.target.style.borderColor = color + "66"}
                        onBlurCapture={e => e.target.style.borderColor = "rgba(255,255,255,0.08)"}
                      />
                    </div>
                  </div>
                );
              })}
              {(() => {
                const cx = parseFloat(shipments.find(s => s.id === selectedShipment.id)?.customerRate);
                const rc = parseFloat(shipments.find(s => s.id === selectedShipment.id)?.carrierPay);
                if (!cx || !rc) return null;
                const margin = ((cx - rc) / cx * 100);
                const color = margin < 0 ? "#EF4444" : margin < 10 ? "#F97316" : "#22C55E";
                return (
                  <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", minWidth: 52 }}>
                    <div style={{ fontSize: 11, color: "#5A6478", marginBottom: 4, fontWeight: 600 }}>MARGIN</div>
                    <div style={{ fontSize: 13, fontWeight: 800, color, fontFamily: "'JetBrains Mono', monospace" }}>
                      {margin.toFixed(1)}%
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>

          {/* Notes */}
          <div style={{ padding: "8px 20px 14px" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 6, textTransform: "uppercase" }}>Notes</div>
            <textarea
              value={shipments.find(s => s.id === selectedShipment.id)?.notes || ""}
              onChange={e => { const v = e.target.value; setShipments(prev => prev.map(s => s.id === selectedShipment.id ? { ...s, notes: v } : s)); }}
              onBlur={(e) => handleMetadataUpdate(selectedShipment, "notes", e.target.value, { toast: showSaveToast })}
              placeholder="Add notes..."
              style={{ width: "100%", minHeight: 50, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, color: "#F0F2F5", padding: 10, fontSize: 11, resize: "vertical", outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif" }} />
          </div>

          {/* Timestamped Notes Log */}
          <div style={{ padding: "4px 20px 14px" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", marginBottom: 8, textTransform: "uppercase" }}>
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
                style={{ background: noteInput.trim() ? "#00D4AA" : "rgba(255,255,255,0.06)", color: noteInput.trim() ? "#0A0E17" : "#5A6478", border: "none", borderRadius: 8, padding: "6px 14px", fontSize: 11, fontWeight: 700, cursor: noteInput.trim() ? "pointer" : "default", opacity: noteSubmitting ? 0.5 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {noteSubmitting ? "..." : "Add"}
              </button>
            </div>
            {loadNotes.length > 0 && (
              <div style={{ maxHeight: 180, overflow: "auto", borderLeft: "2px solid rgba(0,212,170,0.15)", paddingLeft: 12 }}>
                {loadNotes.map(n => (
                  <div key={n.id} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                    <div style={{ fontSize: 11, color: "#F0F2F5", lineHeight: 1.4 }}>{n.note_text}</div>
                    <div style={{ fontSize: 11, color: "#5A6478", marginTop: 3 }}>
                      {n.created_by} &middot; {new Date(n.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Email History (collapsible) */}
          {loadEmails.length > 0 && (
            <div ref={emailsSectionRef} style={{ padding: "8px 20px 12px" }}>
              <div onClick={() => setEmailsCollapsed(prev => !prev)}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>
                  Emails <span style={{ color: "#8B95A8" }}>({loadEmails.length})</span>
                </div>
                <span style={{ fontSize: 11, color: "#5A6478", transition: "transform 0.2s", transform: emailsCollapsed ? "rotate(0deg)" : "rotate(180deg)" }}>&#9660;</span>
              </div>
              {!emailsCollapsed && (
                <div style={{ maxHeight: 200, overflow: "auto", marginTop: 8 }}>
                  {loadEmails.map(em => (
                    <div key={em.id} style={{ display: "flex", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1 }}>{em.has_attachments ? "\u{1F4CE}" : "\u2709"}</span>
                      {em.priority && <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginTop: 5, background: em.priority >= 5 ? "#EF4444" : em.priority >= 4 ? "#F97316" : em.priority >= 3 ? "#3B82F6" : "#6B7280" }} />}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <div style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
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
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "2px", textTransform: "uppercase" }}>
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
                  const icon = doc.doc_type === "carrier_invoice" ? "\u{1F9FE}" : doc.doc_type.includes("rate") ? "\u{1F4B0}" : doc.doc_type === "pod" ? "\u{1F4F8}" : doc.doc_type === "bol" ? "\u{1F4CB}" : doc.doc_type === "packing_list" ? "\u{1F4E6}" : doc.doc_type === "screenshot" ? "\u{1F5BC}" : doc.doc_type === "email" ? "\u2709" : "\u{1F4C4}";
                  const size = doc.size_bytes < 1024 ? `${doc.size_bytes}B` : doc.size_bytes < 1048576 ? `${Math.round(doc.size_bytes / 1024)}KB` : `${(doc.size_bytes / 1048576).toFixed(1)}MB`;
                  const date = doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString("en-US", { month: "numeric", day: "numeric" }) : "";
                  return (
                    <div key={doc.id} draggable="true"
                      onDragStart={e => {
                        e.dataTransfer.setData("application/json", JSON.stringify({ type: "document", efj: selectedShipment?.efj, doc_id: doc.id, doc_type: doc.doc_type, original_name: doc.original_name }));
                        e.dataTransfer.effectAllowed = "copy";
                        e.currentTarget.style.opacity = "0.5";
                      }}
                      onDragEnd={e => { e.currentTarget.style.opacity = "1"; }}
                      style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, cursor: "pointer" }}
                        onClick={() => setPreviewDoc(doc)}>
                        <span style={{ fontSize: 12, flexShrink: 0 }}>{icon}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, color: "#F0F2F5", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.original_name}</div>
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
                                <option value="packing_list">Packing List</option>
                                <option value="screenshot">Screenshot</option>
                                <option value="email">Email</option>
                                <option value="other">Other</option>
                              </select>
                            ) : (
                              <span onClick={e => { e.stopPropagation(); setReclassDocId(doc.id); }}
                                style={{ cursor: "pointer", background: "rgba(0,212,170,0.08)", border: "1px solid rgba(0,212,170,0.25)", borderRadius: 3, padding: "2px 6px", color: "#00D4AA", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }}
                                title="Click to change type">
                                {doc.doc_type.replace("_", " ")} <span style={{ fontSize: 11, opacity: 0.7 }}>{"\u25BC"}</span>
                              </span>
                            )}
                            <span>{"\u00B7"} {size} {"\u00B7"} {date}</span>
                          </div>
                        </div>
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${doc.id}/download`, '_blank'); }}
                        style={{ background: "none", border: "none", color: "#00D4AA", cursor: "pointer", fontSize: 11, padding: "2px 4px", flexShrink: 0 }}>{"\u2193"}</button>
                      <button onClick={(e) => { e.stopPropagation(); handleDocDelete(doc.id); }}
                        style={{ background: "none", border: "none", color: "#3D4557", cursor: "pointer", fontSize: 11, padding: "2px 4px", flexShrink: 0 }}
                        onMouseEnter={e => e.target.style.color = "#f87171"} onMouseLeave={e => e.target.style.color = "#334155"}>&#x2715;</button>
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
                style={{ flex: 1, padding: "6px 8px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, color: "#8B95A8", fontSize: 11, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", cursor: "pointer" }}>
                <option value="customer_rate" style={{ background: "#0D1119" }}>Customer Rate</option>
                <option value="carrier_rate" style={{ background: "#0D1119" }}>Carrier Rate</option>
                <option value="pod" style={{ background: "#0D1119" }}>POD</option>
                <option value="bol" style={{ background: "#0D1119" }}>BOL</option>
                <option value="carrier_invoice" style={{ background: "#0D1119" }}>Carrier Invoice</option>
                <option value="packing_list" style={{ background: "#0D1119" }}>Packing List</option>
                <option value="screenshot" style={{ background: "#0D1119" }}>Screenshot</option>
                <option value="email" style={{ background: "#0D1119" }}>Email</option>
                <option value="other" style={{ background: "#0D1119" }}>Other</option>
              </select>
              <button onClick={() => docInputRef.current?.click()} disabled={docUploading}
                style={{ padding: "6px 14px", borderRadius: 6, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: docUploading ? "default" : "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif", opacity: docUploading ? 0.6 : 1 }}>
                {docUploading ? "..." : "+ Upload"}
              </button>
            </div>
            <div onClick={() => !docUploading && docInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={e => { e.preventDefault(); e.stopPropagation(); if (e.dataTransfer?.files?.[0]) handleDocUpload(e.dataTransfer.files[0]); }}
              style={{ padding: "12px 14px", borderRadius: 8, background: "rgba(255,255,255,0.02)", border: "1px dashed rgba(255,255,255,0.1)", color: "#8B95A8", fontSize: 11, textAlign: "center", cursor: docUploading ? "default" : "pointer" }}>
              Drop files here {"\u2014"} PDF, images, Excel, Word, email
            </div>
            {docUploadMsg && (
              <div style={{ marginTop: 6, fontSize: 11, fontWeight: 600, color: docUploadMsg === "Uploaded" ? "#34d399" : "#f87171", textAlign: "center" }}>
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
          zIndex: Z.modal, padding: 20,
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
                  {previewDoc.doc_type === "carrier_invoice" ? "\u{1F9FE}" : previewDoc.doc_type.includes("rate") ? "\u{1F4B0}" : previewDoc.doc_type === "pod" ? "\u{1F4F8}" : previewDoc.doc_type === "bol" ? "\u{1F4CB}" : previewDoc.doc_type === "screenshot" ? "\u{1F5BC}" : previewDoc.doc_type === "email" ? "\u2709" : "\u{1F4C4}"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {previewDoc.original_name}
                  </div>
                  <div style={{ fontSize: 11, color: "#8B95A8" }}>
                    {previewDoc.doc_type.replace("_", " ")} {"\u00B7"} {previewDoc.size_bytes < 1048576 ? `${Math.round(previewDoc.size_bytes / 1024)}KB` : `${(previewDoc.size_bytes / 1048576).toFixed(1)}MB`}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button onClick={() => window.open(`${API_BASE}/api/load/${selectedShipment.efj}/documents/${previewDoc.id}/download`, '_blank')}
                  style={{ padding: "6px 14px", borderRadius: 8, background: "linear-gradient(135deg, #00D4AA, #0088E8)", border: "none", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                  Download
                </button>
                <button onClick={() => setPreviewDoc(null)}
                  aria-label="Close document preview"
                  style={{ background: "rgba(255,255,255,0.06)", border: "none", color: "#8B95A8", cursor: "pointer", fontSize: 14, width: 32, height: 32, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  &#x2715;
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
                  <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>{"\u{1F4C4}"}</div>
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
      {/* Save toast notification */}
      {saveToast && (
        <div style={{
          position: "fixed", bottom: 24, right: isMobile ? 16 : 16, zIndex: Z.panel + 10,
          display: "flex", alignItems: "center", gap: 8,
          background: saveToast.type === "error" ? "rgba(239,68,68,0.95)" : "rgba(16,185,129,0.95)",
          color: "#fff", padding: "10px 18px", borderRadius: 10,
          fontSize: 12, fontWeight: 700, fontFamily: "'Plus Jakarta Sans', sans-serif",
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          animation: "fade-in 0.15s ease",
          backdropFilter: "blur(8px)",
          maxWidth: isMobile ? "calc(100vw - 32px)" : 340,
        }}>
          <span style={{ fontSize: 16 }}>{saveToast.type === "error" ? "\u26A0" : "\u2713"}</span>
          {saveToast.message}
        </div>
      )}

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <>
          <div aria-hidden="true" onClick={() => setShowDeleteConfirm(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: Z.panel + 10 }} />
          <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: Z.panel + 11, background: "#1A2236", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 12, padding: "24px 28px", width: 360, boxShadow: "0 12px 40px rgba(0,0,0,0.5)" }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#F0F2F5", marginBottom: 8 }}>Delete Load?</div>
            <div style={{ fontSize: 12, color: "#8B95A8", lineHeight: 1.5, marginBottom: 6 }}>
              Are you sure you want to delete <span style={{ color: "#F0F2F5", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{selectedShipment.efj}</span> from the dashboard?
            </div>
            <div style={{ fontSize: 11, color: "#EF4444", marginBottom: 18, padding: "6px 10px", background: "rgba(239,68,68,0.08)", borderRadius: 6, border: "1px solid rgba(239,68,68,0.15)" }}>
              This will permanently remove the load, all documents, emails, and rate quotes associated with it.
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={() => setShowDeleteConfirm(false)} disabled={deleting}
                style={{ flex: 1, padding: "10px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#8B95A8", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                Cancel
              </button>
              <button onClick={handleDeleteLoad} disabled={deleting}
                style={{ flex: 1, padding: "10px", background: deleting ? "#7f1d1d" : "#DC2626", border: "none", borderRadius: 8, color: "#fff", fontSize: 12, fontWeight: 700, cursor: deleting ? "wait" : "pointer", opacity: deleting ? 0.7 : 1, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {deleting ? "Deleting..." : "Yes, Delete Load"}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
