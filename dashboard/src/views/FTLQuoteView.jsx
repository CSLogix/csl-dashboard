import React, { useState, useCallback, useEffect, useRef } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';

// ═══════════════════════════════════════════════════════════════
// FTL QUOTE CALCULATOR — SONAR + DAT market-input quoting tool
// Mirrors the Excel workflow: enter market data → calculate → quote
// ═══════════════════════════════════════════════════════════════

const mono = "'JetBrains Mono', monospace";
const fmt = (n) => { const num = parseFloat(n); return isNaN(num) ? "$0" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 }); };
const fmtDec = (n) => { const num = parseFloat(n); return isNaN(num) ? "$0.00" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
const fmtRpm = (n) => { const num = parseFloat(n); return isNaN(num) ? "$0.00" : "$" + num.toFixed(2); };

// ── Styled input component ──
function RateInput({ label, value, onChange, placeholder, small, prefix = "$" }) {
  return (
    <div style={{ flex: small ? "0 0 auto" : 1 }}>
      <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 3 }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        {prefix && (
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", fontSize: 12, color: "#5A6478", fontFamily: mono }}>
            {prefix}
          </span>
        )}
        <input
          type="number"
          step="any"
          value={value || ""}
          onChange={e => onChange(e.target.value ? parseFloat(e.target.value) : 0)}
          placeholder={placeholder || "0"}
          style={{
            width: small ? 100 : "100%",
            padding: prefix ? "8px 10px 8px 24px" : "8px 10px",
            background: "#14181d",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 8,
            color: "#34d399",
            fontSize: 13,
            fontFamily: mono,
            fontWeight: 600,
            outline: "none",
            transition: "border-color 0.15s",
            boxSizing: "border-box",
          }}
          onFocus={e => e.target.style.borderColor = "rgba(0,212,170,0.4)"}
          onBlur={e => e.target.style.borderColor = "rgba(255,255,255,0.08)"}
        />
      </div>
    </div>
  );
}

function TextInput({ label, value, onChange, placeholder }) {
  return (
    <div style={{ flex: 1 }}>
      <label style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 3 }}>
        {label}
      </label>
      <input
        type="text"
        value={value || ""}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder || ""}
        style={{
          width: "100%",
          padding: "8px 10px",
          background: "#14181d",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 8,
          color: "#F0F2F5",
          fontSize: 13,
          fontFamily: "inherit",
          fontWeight: 500,
          outline: "none",
          transition: "border-color 0.15s",
          boxSizing: "border-box",
        }}
        onFocus={e => e.target.style.borderColor = "rgba(0,212,170,0.4)"}
        onBlur={e => e.target.style.borderColor = "rgba(255,255,255,0.08)"}
      />
    </div>
  );
}

// ── Delta badge ──
function DeltaBadge({ label, value }) {
  if (!value || value === 0) return null;
  const isPositive = value > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
      <span style={{ fontSize: 11, color: "#8B95A8" }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 700, fontFamily: mono, color: isPositive ? "#34d399" : "#f87171" }}>
        {isPositive ? "+" : ""}{fmtDec(value)}
      </span>
    </div>
  );
}

// ── Result row ──
function ResultRow({ label, value, large, accent, sub, rpm }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: large ? "10px 0" : "6px 0", borderBottom: large ? "none" : "1px solid rgba(255,255,255,0.03)" }}>
      <div>
        <span style={{ fontSize: large ? 14 : 12, fontWeight: large ? 800 : 600, color: large ? (accent || "#F0F2F5") : "#C8D0DC" }}>
          {label}
        </span>
        {sub && <div style={{ fontSize: 10, color: "#5A6478", marginTop: 1 }}>{sub}</div>}
      </div>
      <div style={{ textAlign: "right" }}>
        <span style={{ fontSize: large ? 22 : 14, fontWeight: 700, fontFamily: mono, color: accent || "#F0F2F5" }}>
          {value}
        </span>
        {rpm && <div style={{ fontSize: 10, color: "#00b8d4", fontFamily: mono }}>{rpm}/mi</div>}
      </div>
    </div>
  );
}


export default function FTLQuoteView() {
  // ── Lane inputs ──
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [mileage, setMileage] = useState(0);

  // ── SONAR inputs ──
  const [tracCurrent, setTracCurrent] = useState(0);
  const [tracLow, setTracLow] = useState(0);
  const [tracHigh, setTracHigh] = useState(0);
  const [tracContract, setTracContract] = useState(0);

  // ── DAT inputs ──
  const [datLow, setDatLow] = useState(0);
  const [datHigh, setDatHigh] = useState(0);
  const [dat7d, setDat7d] = useState(0);
  const [dat15d, setDat15d] = useState(0);
  const [dat90d, setDat90d] = useState(0);

  // ── Deadhead comp inputs ──
  const [dhOriginRate, setDhOriginRate] = useState(0);
  const [dhDestRate, setDhDestRate] = useState(0);

  // ── Margin ──
  const [marginUsd, setMarginUsd] = useState(300);
  const [marginSource, setMarginSource] = useState("fixed"); // fixed | pct
  const [marginPct, setMarginPct] = useState(15);

  // ── Results ──
  const [result, setResult] = useState(null);
  const [calculating, setCalculating] = useState(false);

  // ── Lane comps ──
  const [comps, setComps] = useState([]);
  const [compsLoading, setCompsLoading] = useState(false);

  // ── Quote history ──
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);

  // ── Notes ──
  const [notes, setNotes] = useState("");

  // ── AI Assistant ──
  const [aiMessages, setAiMessages] = useState([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiInput, setAiInput] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const aiChatRef = useRef(null);

  const askAI = useCallback(async (question) => {
    if (!question.trim()) return;
    setAiMessages(prev => [...prev, { role: "user", text: question }]);
    setAiInput("");
    setAiLoading(true);
    try {
      // Build FTL-specific context
      const contextParts = [];
      if (origin || destination) contextParts.push(`Lane: ${origin || "?"} → ${destination || "?"}`);
      if (mileage > 0) contextParts.push(`Mileage: ${mileage}`);
      if (tracCurrent > 0) contextParts.push(`SONAR Spot: $${tracCurrent} (Low: $${tracLow}, High: $${tracHigh})`);
      if (tracContract > 0) contextParts.push(`SONAR Contract: $${tracContract}`);
      if (dat7d > 0) contextParts.push(`DAT 7-day: $${dat7d}`);
      if (dat15d > 0) contextParts.push(`DAT 15-day: $${dat15d}`);
      if (dat90d > 0) contextParts.push(`DAT 90-day: $${dat90d}`);
      if (datLow > 0 || datHigh > 0) contextParts.push(`DAT Spot Range: $${datLow} – $${datHigh}`);
      if (dhOriginRate > 0) contextParts.push(`DH-Origin Comp: $${dhOriginRate}`);
      if (dhDestRate > 0) contextParts.push(`DH-Dest Comp: $${dhDestRate}`);
      if (result) {
        contextParts.push(`\nCalculated:`);
        contextParts.push(`Market Average: $${result.avg_all} (from ${result.avg_inputs_count} inputs: ${(result.avg_inputs_used || []).join(", ")})`);
        contextParts.push(`Carrier Target: $${result.carrier_target} (${fmtRpm(result.carrier_rpm)}/mi)`);
        contextParts.push(`Margin: $${result.margin_usd} (${result.margin_pct}%)`);
        contextParts.push(`Customer Quote: $${result.quote_customer} (${fmtRpm(result.quoted_rpm)}/mi)`);
      }
      if (comps.length > 0) {
        contextParts.push(`\nLane Comps (${comps.length} results):`);
        comps.slice(0, 10).forEach(c => {
          contextParts.push(`- ${c.origin} → ${c.destination}: Carrier Pay $${c.carrier_pay}${c.customer_rate ? `, CX Rate $${c.customer_rate}` : ""} (${c.carrier || "unknown"}, ${c.source})`);
        });
      }

      const systemContext = contextParts.join("\n");
      const fullQuestion = `You are an FTL freight rate analyst assistant for a brokerage (Evans Delivery / EFJ Operations). You help with quoting FTL loads. Answer concisely and practically — this is for operational use, not academic analysis. Reference specific numbers from the context when relevant.\n\nCurrent Quote Context:\n${systemContext}\n\nUser question: ${question}`;

      const res = await apiFetch(`${API_BASE}/api/ask-ai`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: fullQuestion,
          context: { mode: "ftl_quote", origin, destination, mileage, result, comps_count: comps.length },
        }),
      }).then(r => r.json());
      const answer = res.answer || res.response || res.text || JSON.stringify(res);
      setAiMessages(prev => [...prev, { role: "assistant", text: answer }]);
    } catch (e) {
      setAiMessages(prev => [...prev, { role: "assistant", text: "Sorry, I couldn't process that. " + (e.message || "") }]);
    }
    setAiLoading(false);
    setTimeout(() => { if (aiChatRef.current) aiChatRef.current.scrollTop = aiChatRef.current.scrollHeight; }, 50);
  }, [origin, destination, mileage, tracCurrent, tracLow, tracHigh, tracContract, dat7d, dat15d, dat90d, datLow, datHigh, dhOriginRate, dhDestRate, result, comps]);

  // ── Calculate quote ──
  const calculate = useCallback(async () => {
    setCalculating(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/ftl-quote/calculate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin, destination, mileage,
          trac_spot_current: tracCurrent, trac_spot_low: tracLow,
          trac_spot_high: tracHigh, trac_contract: tracContract,
          dat_spot_low: datLow, dat_spot_high: datHigh,
          dat_7day: dat7d, dat_15day: dat15d, dat_90day: dat90d,
          dh_origin_rate: dhOriginRate, dh_dest_rate: dhDestRate,
          margin_usd: marginUsd, margin_source: marginSource, margin_pct: marginPct,
        }),
      });
      const data = await res.json();
      setResult(data);
    } catch (e) {
      console.error("FTL quote calc error:", e);
    }
    setCalculating(false);
  }, [origin, destination, mileage, tracCurrent, tracLow, tracHigh, tracContract, datLow, datHigh, dat7d, dat15d, dat90d, dhOriginRate, dhDestRate, marginUsd, marginSource, marginPct]);

  // ── Auto-calculate on input change (debounced) ──
  useEffect(() => {
    const hasInput = tracCurrent > 0 || dat7d > 0 || datHigh > 0 || dhOriginRate > 0 || dhDestRate > 0;
    if (!hasInput) return;
    const timer = setTimeout(() => calculate(), 300);
    return () => clearTimeout(timer);
  }, [tracCurrent, tracLow, tracHigh, tracContract, datLow, datHigh, dat7d, dat15d, dat90d, dhOriginRate, dhDestRate, marginUsd, marginSource, marginPct, mileage]);

  // ── Fetch lane comps ──
  const fetchComps = useCallback(async () => {
    if (!origin && !destination) return;
    setCompsLoading(true);
    try {
      const params = new URLSearchParams();
      if (origin) params.set("origin", origin);
      if (destination) params.set("destination", destination);
      const res = await apiFetch(`${API_BASE}/api/ftl-quote/lane-comps?${params}`);
      const data = await res.json();
      setComps(data.comps || []);
    } catch (e) {
      console.error("Lane comps error:", e);
    }
    setCompsLoading(false);
  }, [origin, destination]);

  // ── Fetch history ──
  useEffect(() => {
    apiFetch(`${API_BASE}/api/ftl-quote/history?limit=10`)
      .then(r => r.json())
      .then(d => setHistory(d.quotes || []))
      .catch(() => {});
  }, []);

  // ── Save quote ──
  const saveQuote = async () => {
    if (!result) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await apiFetch(`${API_BASE}/api/ftl-quote/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin, destination, mileage,
          carrier_target: result.carrier_target,
          quote_customer: result.quote_customer,
          margin_usd: result.margin_usd,
          margin_pct: result.margin_pct,
          quoted_rpm: result.quoted_rpm,
          notes,
          inputs_json: {
            trac_spot_current: tracCurrent, trac_spot_high: tracHigh, trac_contract: tracContract,
            dat_7day: dat7d, dat_15day: dat15d, dat_90day: dat90d,
            dh_origin_rate: dhOriginRate, dh_dest_rate: dhDestRate,
          },
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setSaveMsg(`Saved as ${data.quote_number}`);
        // Refresh history
        apiFetch(`${API_BASE}/api/ftl-quote/history?limit=10`)
          .then(r => r.json())
          .then(d => setHistory(d.quotes || []))
          .catch(() => {});
      } else {
        setSaveMsg("Save failed");
      }
    } catch (e) {
      setSaveMsg("Save failed");
    }
    setSaving(false);
  };

  // ── Clear all inputs ──
  const clearAll = () => {
    setTracCurrent(0); setTracLow(0); setTracHigh(0); setTracContract(0);
    setDatLow(0); setDatHigh(0); setDat7d(0); setDat15d(0); setDat90d(0);
    setDhOriginRate(0); setDhDestRate(0);
    setResult(null); setComps([]); setNotes("");
  };

  return (
    <div style={{ padding: "0 24px 24px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "#F0F2F5", margin: 0 }}>FTL Quote Calculator</h2>
          <div style={{ fontSize: 11, color: "#5A6478", marginTop: 2 }}>SONAR + DAT market inputs &rarr; carrier target &rarr; customer quote</div>
        </div>
        <button onClick={clearAll}
          style={{ padding: "6px 16px", fontSize: 11, fontWeight: 700, borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "transparent", color: "#8B95A8", cursor: "pointer", fontFamily: "inherit" }}>
          Clear All
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
        {/* LEFT COLUMN — Inputs */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Lane Info */}
          <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12, textTransform: "uppercase" }}>Lane</div>
            <div style={{ display: "flex", gap: 12 }}>
              <TextInput label="Origin" value={origin} onChange={setOrigin} placeholder="Lakeland, FL" />
              <span style={{ color: "#5A6478", alignSelf: "flex-end", paddingBottom: 8, fontSize: 16 }}>&rarr;</span>
              <TextInput label="Destination" value={destination} onChange={setDestination} placeholder="Cressona, PA" />
              <RateInput label="Miles" value={mileage} onChange={setMileage} placeholder="1070" prefix="" small />
            </div>
            {origin && destination && (
              <button onClick={fetchComps}
                style={{ marginTop: 10, padding: "5px 14px", fontSize: 10, fontWeight: 700, borderRadius: 6, border: "1px solid rgba(0,212,170,0.3)", background: "rgba(0,212,170,0.08)", color: "#00D4AA", cursor: "pointer", fontFamily: "inherit" }}>
                {compsLoading ? "Loading..." : "Pull Lane Comps"}
              </button>
            )}
          </div>

          {/* SONAR Inputs */}
          <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#8b5cf6" }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", textTransform: "uppercase" }}>SONAR (TRAC Spot)</span>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <RateInput label="Current" value={tracCurrent} onChange={setTracCurrent} placeholder="1755" />
              <RateInput label="Low" value={tracLow} onChange={setTracLow} placeholder="1712" />
              <RateInput label="High" value={tracHigh} onChange={setTracHigh} placeholder="1798" />
              <RateInput label="Contract" value={tracContract} onChange={setTracContract} placeholder="2119" />
            </div>
            {tracCurrent > 0 && mileage > 0 && (
              <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 10, color: "#5A6478" }}>
                <span>Spot RPM: <span style={{ color: "#a78bfa", fontFamily: mono }}>{fmtRpm(tracCurrent / mileage)}</span></span>
                {tracContract > 0 && <span>Contract RPM: <span style={{ color: "#a78bfa", fontFamily: mono }}>{fmtRpm(tracContract / mileage)}</span></span>}
              </div>
            )}
          </div>

          {/* DAT Inputs */}
          <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#3b82f6" }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", textTransform: "uppercase" }}>DAT RateView</span>
            </div>
            <div style={{ display: "flex", gap: 12, marginBottom: 10 }}>
              <RateInput label="7-Day Avg" value={dat7d} onChange={setDat7d} placeholder="1926" />
              <RateInput label="15-Day" value={dat15d} onChange={setDat15d} placeholder="2023" />
              <RateInput label="90-Day" value={dat90d} onChange={setDat90d} placeholder="1991" />
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <RateInput label="Spot Low" value={datLow} onChange={setDatLow} placeholder="1743" />
              <RateInput label="Spot High" value={datHigh} onChange={setDatHigh} placeholder="2044" />
            </div>
            {dat7d > 0 && mileage > 0 && (
              <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 10, color: "#5A6478" }}>
                <span>7d RPM: <span style={{ color: "#60a5fa", fontFamily: mono }}>{fmtRpm(dat7d / mileage)}</span></span>
                {dat15d > 0 && <span>15d RPM: <span style={{ color: "#60a5fa", fontFamily: mono }}>{fmtRpm(dat15d / mileage)}</span></span>}
              </div>
            )}
          </div>

          {/* Deadhead Comps */}
          <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b" }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", textTransform: "uppercase" }}>Deadhead Comps (DAT Loadboard)</span>
            </div>
            <div style={{ fontSize: 10, color: "#5A6478", marginBottom: 12 }}>Best matching rates from DH-O / DH-D sorted results</div>
            <div style={{ display: "flex", gap: 12 }}>
              <RateInput label="DH-Origin Comp" value={dhOriginRate} onChange={setDhOriginRate} placeholder="Closest DH-O rate" />
              <RateInput label="DH-Dest Comp" value={dhDestRate} onChange={setDhDestRate} placeholder="Closest DH-D rate" />
            </div>
          </div>

          {/* Margin Control */}
          <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", textTransform: "uppercase" }}>Margin</span>
              <div style={{ display: "flex", gap: 4, background: "#14181d", borderRadius: 6, padding: 2 }}>
                {["fixed", "pct"].map(m => (
                  <button key={m} onClick={() => setMarginSource(m)}
                    style={{ padding: "4px 12px", fontSize: 10, fontWeight: 700, borderRadius: 4, border: "none", background: marginSource === m ? "rgba(0,212,170,0.15)" : "transparent", color: marginSource === m ? "#00D4AA" : "#5A6478", cursor: "pointer", fontFamily: "inherit" }}>
                    {m === "fixed" ? "$ Fixed" : "% of Avg"}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: 12, maxWidth: 300 }}>
              {marginSource === "fixed" ? (
                <RateInput label="Margin $" value={marginUsd} onChange={setMarginUsd} placeholder="300" />
              ) : (
                <RateInput label="Margin %" value={marginPct} onChange={setMarginPct} placeholder="15" prefix="%" />
              )}
            </div>
          </div>

          {/* Lane Comps */}
          {comps.length > 0 && (
            <div className="glass" style={{ borderRadius: 12, padding: 20, border: "1px solid rgba(255,255,255,0.06)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 12, textTransform: "uppercase" }}>
                Lane Comps ({comps.length} results)
              </div>
              <div style={{ maxHeight: 300, overflow: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                      <th style={{ padding: "6px 8px", textAlign: "left", color: "#5A6478", fontWeight: 700 }}>Lane</th>
                      <th style={{ padding: "6px 8px", textAlign: "left", color: "#5A6478", fontWeight: 700 }}>Carrier</th>
                      <th style={{ padding: "6px 8px", textAlign: "right", color: "#5A6478", fontWeight: 700 }}>Carrier Pay</th>
                      <th style={{ padding: "6px 8px", textAlign: "right", color: "#5A6478", fontWeight: 700 }}>CX Rate</th>
                      <th style={{ padding: "6px 8px", textAlign: "left", color: "#5A6478", fontWeight: 700 }}>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comps.map((c, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                        <td style={{ padding: "6px 8px", color: "#C8D0DC" }}>{c.origin} &rarr; {c.destination}</td>
                        <td style={{ padding: "6px 8px", color: "#8B95A8" }}>{c.carrier || "—"}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontFamily: mono, fontWeight: 700, color: "#34d399" }}>
                          {c.carrier_pay ? fmtDec(c.carrier_pay) : "—"}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontFamily: mono, color: "#60a5fa" }}>
                          {c.customer_rate ? fmtDec(c.customer_rate) : "—"}
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: c.source === "shipment" ? "rgba(52,211,153,0.12)" : "rgba(167,139,250,0.12)", color: c.source === "shipment" ? "#34d399" : "#a78bfa" }}>
                            {c.source === "shipment" ? "LOAD" : "RATE"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* AI Rate Assistant */}
          <div className="glass" style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,0.06)", overflow: "hidden" }}>
            <button onClick={() => setAiOpen(!aiOpen)}
              style={{ width: "100%", padding: "14px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", background: "transparent", border: "none", cursor: "pointer", fontFamily: "inherit" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 24, height: 24, borderRadius: 6, background: "linear-gradient(135deg, #00c853, #00b8d4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>AI</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#F0F2F5", textAlign: "left" }}>FTL Rate Assistant</div>
                  <div style={{ fontSize: 10, color: "#5A6478", textAlign: "left" }}>Ask about pricing strategy, lane analysis, market conditions</div>
                </div>
              </div>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5A6478" strokeWidth="2" style={{ transform: aiOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}>
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {aiOpen && (
              <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: 16 }}>
                {/* Quick-ask buttons */}
                {aiMessages.length === 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", marginBottom: 8 }}>Quick questions:</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {[
                        "Is this a good lane to quote aggressively?",
                        "What should my carrier target be?",
                        "How do the SONAR and DAT rates compare?",
                        "What margin should I target?",
                        "Analyze the deadhead comp rates",
                        "Is the market trending up or down?",
                      ].map((q, i) => (
                        <button key={i} onClick={() => askAI(q)}
                          style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid rgba(0,212,170,0.15)", background: "rgba(0,212,170,0.04)", color: "#00D4AA", fontSize: 10, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(0,212,170,0.1)"}
                          onMouseLeave={e => e.currentTarget.style.background = "rgba(0,212,170,0.04)"}>
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Chat messages */}
                <div ref={aiChatRef} style={{ maxHeight: 400, overflow: "auto", marginBottom: 12 }}>
                  {aiMessages.map((msg, i) => (
                    <div key={i} style={{ marginBottom: 10, display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>
                      <div style={{
                        padding: "10px 14px", borderRadius: 10, maxWidth: "90%", fontSize: 12, lineHeight: 1.6,
                        background: msg.role === "user" ? "rgba(0,212,170,0.12)" : "rgba(255,255,255,0.04)",
                        color: msg.role === "user" ? "#00D4AA" : "#C8D0DC",
                        border: `1px solid ${msg.role === "user" ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.06)"}`,
                        whiteSpace: "pre-wrap",
                      }}>
                        {msg.text}
                      </div>
                    </div>
                  ))}
                  {aiLoading && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0" }}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#00D4AA", animation: "pulse 1s infinite" }} />
                      <span style={{ fontSize: 11, color: "#5A6478" }}>Analyzing...</span>
                    </div>
                  )}
                </div>

                {/* Input */}
                <div style={{ display: "flex", gap: 8 }}>
                  <input value={aiInput} onChange={e => setAiInput(e.target.value)}
                    placeholder="Ask about this lane, pricing strategy, market..."
                    onKeyDown={e => { if (e.key === "Enter" && aiInput.trim() && !aiLoading) askAI(aiInput); }}
                    style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)", color: "#F0F2F5", fontSize: 11, fontFamily: "inherit", outline: "none" }} />
                  <button onClick={() => { if (aiInput.trim() && !aiLoading) askAI(aiInput); }}
                    disabled={aiLoading || !aiInput.trim()}
                    style={{ padding: "8px 16px", borderRadius: 8, border: "none", background: aiInput.trim() ? "linear-gradient(135deg, #00c853, #00b8d4)" : "rgba(255,255,255,0.06)", color: aiInput.trim() ? "#0a0d10" : "#5A6478", fontSize: 11, fontWeight: 700, cursor: aiInput.trim() ? "pointer" : "default", fontFamily: "inherit" }}>
                    Ask
                  </button>
                </div>
                {aiMessages.length > 0 && (
                  <button onClick={() => setAiMessages([])}
                    style={{ marginTop: 8, padding: "4px 10px", borderRadius: 4, border: "1px solid rgba(255,255,255,0.06)", background: "transparent", color: "#5A6478", fontSize: 10, cursor: "pointer", fontFamily: "inherit" }}>
                    Clear chat
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN — Output */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, position: "sticky", top: 20 }}>

          {/* Quote Output Card */}
          <div style={{ borderRadius: 14, overflow: "hidden", border: "1.5px solid transparent", backgroundImage: "linear-gradient(#0d1117, #0d1117), linear-gradient(135deg, #00c853, #00b8d4, #2979ff)", backgroundOrigin: "border-box", backgroundClip: "padding-box, border-box" }}>
            <div style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 16, textTransform: "uppercase" }}>
                Quote Output
              </div>

              {!result ? (
                <div style={{ textAlign: "center", padding: "40px 0", color: "#3D4654" }}>
                  <div style={{ fontSize: 32, marginBottom: 8 }}>&#x1F4CA;</div>
                  <div style={{ fontSize: 12 }}>Enter market inputs to calculate</div>
                </div>
              ) : (
                <>
                  {/* Lane header */}
                  {(origin || destination) && (
                    <div style={{ fontSize: 13, color: "#C8D0DC", marginBottom: 12, fontWeight: 600 }}>
                      {origin || "?"} &rarr; {destination || "?"}{mileage > 0 && <span style={{ color: "#5A6478", fontWeight: 400 }}> &middot; {mileage.toLocaleString()} mi</span>}
                    </div>
                  )}

                  {/* Deltas */}
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", letterSpacing: "0.5px", marginBottom: 6 }}>DELTAS</div>
                    <DeltaBadge label="SONAR Spot Delta (High - Current)" value={result.sonar_spot_delta} />
                    <DeltaBadge label="DAT Spot Range" value={result.dat_spot_delta} />
                    <DeltaBadge label="DAT High vs SONAR High" value={result.sonar_vs_dat_high} />
                  </div>

                  {/* Market Average */}
                  <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 10, padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", letterSpacing: "0.5px", marginBottom: 8 }}>
                      MARKET AVERAGE ({result.avg_inputs_count} inputs)
                    </div>
                    <div style={{ fontSize: 36, fontWeight: 800, color: "#F0F2F5", fontFamily: mono, lineHeight: 1 }}>
                      {fmt(result.avg_all)}
                    </div>
                    {mileage > 0 && (
                      <div style={{ fontSize: 11, color: "#5A6478", fontFamily: mono, marginTop: 4 }}>
                        {fmtRpm(result.carrier_rpm)}/mi
                      </div>
                    )}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                      {(result.avg_inputs_used || []).map((label, i) => (
                        <span key={i} style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "rgba(0,212,170,0.1)", color: "#00D4AA", border: "1px solid rgba(0,212,170,0.15)" }}>
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Pricing Breakdown */}
                  <div style={{ marginBottom: 16 }}>
                    <ResultRow label="Carrier Target" value={fmtDec(result.carrier_target)} rpm={mileage > 0 ? fmtRpm(result.carrier_rpm) : null} />
                    <ResultRow label="Margin" value={`+${fmtDec(result.margin_usd)}`} sub={`${result.margin_pct}%`} accent="#FBBF24" />
                    <div style={{ height: 1, background: "linear-gradient(90deg, transparent, rgba(0,212,170,0.3), transparent)", margin: "4px 0" }} />
                    <ResultRow label="Customer Quote" value={fmtDec(result.quote_customer)} rpm={mileage > 0 ? fmtRpm(result.quoted_rpm) : null} large accent="#00c853" />
                  </div>

                  {/* RPM Comparison */}
                  {mileage > 0 && (
                    <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 10, padding: 12, marginBottom: 16 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "#5A6478", letterSpacing: "0.5px", marginBottom: 8 }}>RPM COMPARISON</div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, textAlign: "center" }}>
                        {result.sonar_rpm > 0 && (
                          <div>
                            <div style={{ fontSize: 15, fontWeight: 700, fontFamily: mono, color: "#a78bfa" }}>{fmtRpm(result.sonar_rpm)}</div>
                            <div style={{ fontSize: 9, color: "#5A6478" }}>SONAR</div>
                          </div>
                        )}
                        {result.dat_rpm > 0 && (
                          <div>
                            <div style={{ fontSize: 15, fontWeight: 700, fontFamily: mono, color: "#60a5fa" }}>{fmtRpm(result.dat_rpm)}</div>
                            <div style={{ fontSize: 9, color: "#5A6478" }}>DAT 7d</div>
                          </div>
                        )}
                        <div>
                          <div style={{ fontSize: 15, fontWeight: 700, fontFamily: mono, color: "#00c853" }}>{fmtRpm(result.quoted_rpm)}</div>
                          <div style={{ fontSize: 9, color: "#5A6478" }}>Your Quote</div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Notes + Save */}
                  <div>
                    <textarea
                      value={notes}
                      onChange={e => setNotes(e.target.value)}
                      placeholder="Notes (optional)..."
                      rows={2}
                      style={{ width: "100%", padding: 10, background: "#14181d", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, color: "#C8D0DC", fontSize: 12, fontFamily: "inherit", resize: "vertical", outline: "none", boxSizing: "border-box" }}
                    />
                    <button onClick={saveQuote} disabled={saving}
                      style={{ width: "100%", marginTop: 8, padding: "10px 0", fontSize: 12, fontWeight: 700, borderRadius: 8, border: "none", background: "linear-gradient(135deg, #00c853, #00b8d4)", color: "#0a0d10", cursor: saving ? "wait" : "pointer", fontFamily: "inherit", transition: "opacity 0.15s", opacity: saving ? 0.5 : 1 }}>
                      {saving ? "Saving..." : "Save Quote"}
                    </button>
                    {saveMsg && <div style={{ fontSize: 11, color: "#00D4AA", textAlign: "center", marginTop: 6 }}>{saveMsg}</div>}
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Recent FTL Quotes */}
          {history.length > 0 && (
            <div className="glass" style={{ borderRadius: 12, padding: 16, border: "1px solid rgba(255,255,255,0.06)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#8B95A8", letterSpacing: "0.5px", marginBottom: 10, textTransform: "uppercase" }}>
                Recent FTL Quotes
              </div>
              {history.map((q, i) => (
                <div key={q.id || i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", borderBottom: i < history.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none" }}>
                  <div>
                    <div style={{ fontSize: 11, color: "#C8D0DC" }}>{q.origin || "?"} &rarr; {q.destination || "?"}</div>
                    <div style={{ fontSize: 9, color: "#5A6478" }}>{q.quote_number} &middot; {q.created_at}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 12, fontWeight: 700, fontFamily: mono, color: "#00c853" }}>{fmtDec(q.customer_total)}</div>
                    <div style={{ fontSize: 9, color: "#5A6478" }}>{q.margin_pct}% margin</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
