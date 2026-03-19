import React, { useState } from 'react';

/**
 * Render a carrier rates table with inline editing, live RPM calculation, and per-row actions.
 *
 * Renders carrier rows with capability badges, editable MC number and dispatch email, editable numeric rate cells,
 * an RPM column computed from rates and provided miles (doubled for dray move type), and row-level actions for quoting,
 * copying email/MC, and deleting rates.
 *
 * @param {Object} props - Component props.
 * @param {Array<Object>} props.carriers - Array of carrier rate objects to display.
 * @param {Object<string, Object>} props.carrierCapMap - Lookup of carrier capabilities keyed by lowercased carrier_name.
 * @param {number|null} props.editingLaneRateId - ID of the rate row currently being edited, or null.
 * @param {string|null} props.editingLaneField - Field key currently being edited (e.g., "total", "dray_rate"), or null.
 * @param {string} props.editingLaneValue - Current string value for the inline rate edit input.
 * @param {Function} props.setEditingLaneRateId - Setter to change the editingLaneRateId.
 * @param {Function} props.setEditingLaneField - Setter to change the editingLaneField.
 * @param {Function} props.setEditingLaneValue - Setter to change the editingLaneValue.
 * @param {Function} props.handleLaneRateUpdate - Callback invoked to persist a rate change: (rateId, field, value) => void.
 * @param {string} props.laneOrigin - Origin identifier for the lane (display/context only).
 * @param {string} props.laneDestination - Destination identifier for the lane (display/context only).
 * @param {number|null} props.miles - One-way miles used to compute RPM; if null RPM is not shown. For moveType "dray", miles are doubled.
 * @param {string} props.moveType - Move type affecting RPM ("dray" | "ftl" | "transload"); treated case-insensitively.
 * @param {Function} [props.onUseRate] - Optional callback when a row's "Quote" action is used: (carrierRate) => void.
 * @param {Function} [props.onUpdateCarrierInfo] - Optional callback to persist carrier info edits: (carrierName, field, value) => Promise.
 * @param {Function} [props.onDeleteRate] - Optional callback to delete a rate: (rateId) => Promise<boolean>.
 * @returns {JSX.Element} The rendered carrier rates table component.
 */
export default function CarrierRateTable({ carriers, carrierCapMap, editingLaneRateId, editingLaneField, editingLaneValue, setEditingLaneRateId, setEditingLaneField, setEditingLaneValue, handleLaneRateUpdate, laneOrigin, laneDestination, miles, moveType, onUseRate, onUpdateCarrierInfo, onDeleteRate }) {
  const [showAllCols, setShowAllCols] = useState(false);
  const [copiedMC, setCopiedMC] = useState(null);
  const [hoveredRow, setHoveredRow] = useState(null);
  const [editingCarrierInfo, setEditingCarrierInfo] = useState(null);
  const [savingCarrierInfo, setSavingCarrierInfo] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [copiedEmail, setCopiedEmail] = useState(null);

  // RPM calculation
  const isDray = (moveType || "dray").toLowerCase() === "dray";
  const effectiveMiles = miles ? (isDray ? miles * 2 : miles) : null;

  const primaryCols = ["Carrier", "Linehaul", "FSC", "Total", "RPM", "Chassis/day", "Prepull", "OW", ""];
  const secondaryCols = ["Storage/day", "Detention", "Split", "Tolls", "HAZ", "Triaxle", "Reefer", "Bond"];
  const visibleCols = showAllCols ? ["Carrier", "Linehaul", "FSC", "Total", "RPM", "Chassis/day", "Prepull", "OW", ...secondaryCols, ""] : primaryCols;

  const fieldMap = {
    "Linehaul": "dray_rate", "FSC": "fsc", "Total": "total", "Chassis/day": "chassis_per_day",
    "Prepull": "prepull", "OW": "overweight", "Storage/day": "storage_per_day", "Detention": "detention",
    "Split": "chassis_split", "Tolls": "tolls", "HAZ": "hazmat", "Triaxle": "triaxle", "Reefer": "reefer", "Bond": "bond_fee",
  };

  const copyMC = (mc) => {
    navigator.clipboard.writeText(mc).then(() => { setCopiedMC(mc); setTimeout(() => setCopiedMC(null), 1500); });
  };
  const copyEmail = (carrier) => {
    const caps = carrierCapMap[(carrier.carrier_name || "").toLowerCase()] || {};
    const email = caps.contact_email || carrier.contact_email;
    if (!email) return;
    navigator.clipboard.writeText(email).then(() => { setCopiedEmail(email); setTimeout(() => setCopiedEmail(null), 1500); });
  };

  const computeRPM = (cr) => {
    // Use editing value if currently editing total/dray_rate for this row
    let rate = parseFloat(cr.total || cr.dray_rate || 0);
    if (editingLaneRateId === cr.id && (editingLaneField === "total" || editingLaneField === "dray_rate")) {
      const editVal = parseFloat(editingLaneValue);
      if (!isNaN(editVal)) rate = editVal;
    }
    if (!rate || !effectiveMiles) return null;
    return (rate / effectiveMiles).toFixed(2);
  };

  return (
    <div className="glass" style={{ borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.10)" }}>
      <div style={{ padding: "14px 20px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", background: "linear-gradient(90deg, rgba(0,212,170,0.03), transparent)" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px" }}>CARRIER RATES</span>
        <button onClick={() => setShowAllCols(!showAllCols)}
          style={{ padding: "3px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)", background: showAllCols ? "rgba(0,212,170,0.08)" : "transparent", color: showAllCols ? "#00D4AA" : "#5A6478", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
          {showAllCols ? "Show Less" : `+${secondaryCols.length} More Columns`}
        </button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
              {visibleCols.map(h => (
                <th key={h} style={{ padding: "8px 10px", textAlign: h === "Carrier" ? "left" : "center", color: "#5A6478", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.03em", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {carriers.map((cr, ci) => {
              const caps = carrierCapMap[(cr.carrier_name || "").toLowerCase()] || {};
              const capBadges = [
                caps.can_hazmat && { label: "\uD83D\uDD25", title: "Hazmat", color: "#f87171" },
                caps.can_overweight && { label: "\u2696", title: "Overweight", color: "#FBBF24" },
                caps.can_reefer && { label: "\u2744", title: "Reefer", color: "#60a5fa" },
                caps.can_bonded && { label: "\uD83D\uDD12", title: "Bonded", color: "#a78bfa" },
                caps.can_transload && { label: "\uD83D\uDD04", title: "Transload", color: "#38bdf8" },
              ].filter(Boolean);
              const tierColor = caps.tier_rank === 1 ? "#22c55e" : caps.tier_rank === 2 ? "#FBBF24" : caps.tier_rank === 3 ? "#fb923c" : null;
              const daysSince = cr.created_at ? Math.floor((Date.now() - new Date(cr.created_at).getTime()) / 86400000) : null;
              const isAged = daysSince !== null && daysSince > 30;
              const mcNumber = caps.mc_number || cr.mc_number;
              const dispatchEmail = caps.contact_email || cr.carrier_email || cr.contact_email;
              const isHovered = hoveredRow === ci;
              const rpm = computeRPM(cr);

              return (
                <tr key={ci} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)", transition: "background 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; setHoveredRow(ci); }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; setHoveredRow(null); }}>
                  {/* Carrier cell */}
                  <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: mcNumber || dispatchEmail ? 2 : 0 }}>
                      {tierColor && <span title={`Tier ${caps.tier_rank}`} style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: tierColor, flexShrink: 0 }} />}
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#F0F2F5" }}>{cr.carrier_name}</span>
                      {capBadges.map((b, bi) => <span key={bi} title={b.title} style={{ fontSize: 11, opacity: 0.8 }}>{b.label}</span>)}
                      {daysSince !== null && (
                        <span style={{ fontSize: 11, color: isAged ? "#FBBF24" : "#5A6478", fontStyle: "italic" }}>
                          {isAged ? "\u26A0 " : ""}{daysSince === 0 ? "today" : daysSince < 7 ? `${daysSince}d` : daysSince < 30 ? `${Math.floor(daysSince / 7)}w` : `${Math.floor(daysSince / 30)}mo`}
                        </span>
                      )}
                    </div>
                    {/* MC Number — inline editable */}
                    {editingCarrierInfo?.carrierName === cr.carrier_name && editingCarrierInfo?.field === "mc_number" ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <span style={{ fontSize: 11, color: "#5A6478" }}>MC-</span>
                        <input autoFocus type="text" value={editingCarrierInfo.value}
                          onChange={e => setEditingCarrierInfo(prev => ({ ...prev, value: e.target.value }))}
                          onBlur={() => { if (onUpdateCarrierInfo) { setSavingCarrierInfo(true); onUpdateCarrierInfo(cr.carrier_name, "mc_number", editingCarrierInfo.value).finally(() => setSavingCarrierInfo(false)); } setEditingCarrierInfo(null); }}
                          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditingCarrierInfo(null); }}
                          onClick={e => e.stopPropagation()}
                          placeholder="Enter MC#"
                          style={{ width: 90, padding: "2px 4px", borderRadius: 4, border: "1px solid rgba(0,212,170,0.4)", background: "rgba(0,212,170,0.06)", color: "#F0F2F5", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none" }} />
                      </div>
                    ) : (
                      <div onClick={e => { e.stopPropagation(); setEditingCarrierInfo({ carrierName: cr.carrier_name, field: "mc_number", value: mcNumber || "" }); }}
                        style={{ display: "flex", alignItems: "center", gap: 4, cursor: "text", minHeight: 16 }}>
                        {mcNumber ? (
                          <>
                            <span style={{ fontSize: 11, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>MC-{mcNumber}</span>
                            <span onClick={e => { e.stopPropagation(); copyMC(mcNumber); }}
                              title="Copy MC#" style={{ fontSize: 11, cursor: "pointer", color: copiedMC === mcNumber ? "#34d399" : "#3D4654", transition: "color 0.15s" }}>
                              {copiedMC === mcNumber ? "\u2713" : "\u2398"}
                            </span>
                          </>
                        ) : (
                          <span style={{ fontSize: 11, color: "#3D4654", fontStyle: "italic" }}>+ MC#</span>
                        )}
                      </div>
                    )}
                    {/* Dispatch email — inline editable */}
                    {editingCarrierInfo?.carrierName === cr.carrier_name && editingCarrierInfo?.field === "contact_email" ? (
                      <input autoFocus type="email" value={editingCarrierInfo.value}
                        onChange={e => setEditingCarrierInfo(prev => ({ ...prev, value: e.target.value }))}
                        onBlur={() => { if (onUpdateCarrierInfo) { setSavingCarrierInfo(true); onUpdateCarrierInfo(cr.carrier_name, "contact_email", editingCarrierInfo.value).finally(() => setSavingCarrierInfo(false)); } setEditingCarrierInfo(null); }}
                        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditingCarrierInfo(null); }}
                        onClick={e => e.stopPropagation()}
                        placeholder="dispatch@carrier.com"
                        style={{ width: 180, padding: "2px 4px", borderRadius: 4, border: "1px solid rgba(0,212,170,0.4)", background: "rgba(0,212,170,0.06)", color: "#F0F2F5", fontSize: 11, outline: "none", marginTop: 1 }} />
                    ) : (
                      <div onClick={e => { e.stopPropagation(); setEditingCarrierInfo({ carrierName: cr.carrier_name, field: "contact_email", value: dispatchEmail || "" }); }}
                        style={{ cursor: "text", minHeight: 16, marginTop: 1 }}>
                        {dispatchEmail ? (
                          <a href={`mailto:${dispatchEmail}`} onClick={e => e.stopPropagation()}
                            style={{ fontSize: 11, color: "#60a5fa", textDecoration: "none", display: "block", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                            onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
                            {dispatchEmail}
                          </a>
                        ) : (
                          <span style={{ fontSize: 11, color: "#3D4654", fontStyle: "italic" }}>+ email</span>
                        )}
                      </div>
                    )}
                  </td>
                  {/* Rate columns (skip Carrier and actions) */}
                  {visibleCols.slice(1, -1).map((col, vi) => {
                    if (col === "RPM") {
                      return (
                        <td key="rpm" style={{ padding: "10px 8px", textAlign: "center", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: rpm ? "#00D4AA" : "#2D3340", verticalAlign: "middle", fontFeatureSettings: "'tnum'", fontWeight: rpm ? 600 : 400 }}>
                          {rpm ? `$${rpm}/mi` : "\u2014"}
                        </td>
                      );
                    }
                    const f = fieldMap[col];
                    const v = cr[f];
                    const isEditingThis = editingLaneRateId === cr.id && editingLaneField === f;
                    return (
                      <td key={vi} onClick={e => { e.stopPropagation(); setEditingLaneRateId(cr.id); setEditingLaneField(f); setEditingLaneValue(v != null && v !== "" ? String(v) : ""); }}
                        style={{ padding: "10px 8px", textAlign: "center", cursor: "text", fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
                          color: isEditingThis ? "#F0F2F5" : v ? "#C8D0DC" : "#2D3340", verticalAlign: "middle", fontFeatureSettings: "'tnum'" }}>
                        {isEditingThis ? (
                          <input autoFocus type="number" step="0.01" value={editingLaneValue}
                            onChange={e => setEditingLaneValue(e.target.value)}
                            onBlur={() => handleLaneRateUpdate(cr.id, f, editingLaneValue)}
                            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setEditingLaneRateId(null); setEditingLaneField(null); } }}
                            onClick={e => e.stopPropagation()}
                            style={{ width: 60, padding: "3px 4px", textAlign: "center", borderRadius: 4, border: "1px solid rgba(0,212,170,0.4)", background: "rgba(0,212,170,0.06)", color: "#F0F2F5", fontSize: 11, fontFamily: "'JetBrains Mono', monospace", outline: "none" }} />
                        ) : (
                          v ? (typeof v === "number" || !isNaN(v) ? `$${parseFloat(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}` : v) : "\u2014"
                        )}
                      </td>
                    );
                  })}
                  {/* Actions column */}
                  <td style={{ padding: "10px 8px", textAlign: "center", verticalAlign: "middle", whiteSpace: "nowrap" }}>
                    {isHovered && (
                      <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>
                        {onUseRate && (cr.total || cr.dray_rate) && (
                          <button onClick={e => { e.stopPropagation(); onUseRate(cr); }}
                            title="Use this rate in Quote Builder"
                            style={{ padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap", transition: "all 0.15s" }}
                            onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,212,170,0.15)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,212,170,0.08)"; }}>
                            Quote
                          </button>
                        )}
                        {dispatchEmail && (
                          <button onClick={e => { e.stopPropagation(); copyEmail(cr); }}
                            title={`Copy ${dispatchEmail}`}
                            style={{ padding: "4px 8px", borderRadius: 5, border: `1px solid ${copiedEmail === dispatchEmail ? "rgba(52,211,153,0.3)" : "rgba(59,130,246,0.3)"}`, background: copiedEmail === dispatchEmail ? "rgba(52,211,153,0.08)" : "rgba(59,130,246,0.08)", color: copiedEmail === dispatchEmail ? "#34d399" : "#60a5fa", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap", transition: "all 0.15s" }}
                            onMouseEnter={e => { if (copiedEmail !== dispatchEmail) e.currentTarget.style.background = "rgba(59,130,246,0.15)"; }}
                            onMouseLeave={e => { if (copiedEmail !== dispatchEmail) e.currentTarget.style.background = "rgba(59,130,246,0.08)"; }}>
                            {copiedEmail === dispatchEmail ? "\u2713 Copied" : "Email"}
                          </button>
                        )}
                        {onDeleteRate && cr.id && deleteConfirmId !== cr.id && (
                          <button onClick={e => { e.stopPropagation(); setDeleteConfirmId(cr.id); }}
                            title="Delete this rate"
                            style={{ padding: "4px 6px", borderRadius: 5, border: "1px solid rgba(248,113,113,0.3)", background: "rgba(248,113,113,0.08)", color: "#f87171", fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap", transition: "all 0.15s" }}
                            onMouseEnter={e => { e.currentTarget.style.background = "rgba(248,113,113,0.15)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "rgba(248,113,113,0.08)"; }}>
                            &#128465;
                          </button>
                        )}
                        {onDeleteRate && deleteConfirmId === cr.id && (
                          <>
                            <button onClick={async e => { e.stopPropagation(); setDeletingId(cr.id); const ok = await onDeleteRate(cr.id); if (ok) setDeleteConfirmId(null); setDeletingId(null); }}
                              disabled={deletingId === cr.id}
                              style={{ padding: "4px 8px", borderRadius: 5, border: "1px solid rgba(248,113,113,0.4)", background: "rgba(248,113,113,0.15)", color: "#f87171", fontSize: 10, fontWeight: 700, cursor: deletingId === cr.id ? "wait" : "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>
                              {deletingId === cr.id ? "..." : "Delete?"}
                            </button>
                            <button onClick={e => { e.stopPropagation(); setDeleteConfirmId(null); }}
                              style={{ padding: "4px 6px", borderRadius: 5, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#5A6478", fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                              No
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
