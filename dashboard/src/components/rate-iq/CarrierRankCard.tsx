import React from 'react';
import { fmt } from './constants';

/**
 * Compute the CSL Score for a carrier (0-100).
 * Weights: Rate 50%, Reliability 30%, Equipment Match 20%.
 */
export function computeCSLScore(carrier, allCarriers, carrierCaps, requiredCaps) {
  const rates = allCarriers.map(c => parseFloat(c.total || c.dray_rate || 0)).filter(r => r > 0);
  const minRate = Math.min(...rates);
  const maxRate = Math.max(...rates);
  const carrierRate = parseFloat(carrier.total || carrier.dray_rate || 0);

  // Rate score: cheapest = 100, most expensive = 0
  let rateScore = 50;
  if (rates.length > 1 && maxRate > minRate && carrierRate > 0) {
    rateScore = 100 - ((carrierRate - minRate) / (maxRate - minRate)) * 100;
  } else if (carrierRate > 0) {
    rateScore = 75; // single carrier gets decent score
  }

  // Reliability score: based on load history count
  const historyCount = carrier.load_count || carrier.history_count || 0;
  const reliabilityScore = historyCount >= 10 ? 100 : historyCount >= 5 ? 80 : historyCount >= 3 ? 60 : historyCount >= 1 ? 40 : 20;

  // Equipment score: check capability match
  const caps = carrierCaps || {};
  const needed = requiredCaps || [];
  let equipmentScore = 100;
  if (needed.length > 0) {
    const matched = needed.filter(cap => caps[cap]);
    equipmentScore = (matched.length / needed.length) * 100;
  }

  return Math.round(rateScore * 0.50 + reliabilityScore * 0.30 + equipmentScore * 0.20);
}

/**
 * Ranked carrier card for the Command Center left pane.
 */
export default function CarrierRankCard({ carrier, rank, score, moveType, carrierCaps, onSelect }) {
  const rate = parseFloat(carrier.total || carrier.dray_rate || 0);
  const caps = carrierCaps || {};
  const lastDate = carrier.created_at ? new Date(carrier.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : null;

  return (
    <div
      onClick={() => onSelect && onSelect(carrier)}
      style={{
        border: "1px solid rgba(255,255,255,0.05)",
        background: "#111418",
        padding: "14px 16px",
        borderRadius: 12,
        cursor: "pointer",
        transition: "all 0.15s ease",
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "#00c853"; e.currentTarget.style.background = "#131820"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.05)"; e.currentTarget.style.background = "#111418"; }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{
            fontSize: 20, fontWeight: 700, color: "#3D4557",
            fontFamily: "'JetBrains Mono', monospace", minWidth: 36,
          }}>
            #{rank}
          </span>
          <div>
            <h4 style={{
              fontSize: 13, fontWeight: 700, color: "#F0F2F5",
              textTransform: "uppercase", margin: 0, letterSpacing: "0.02em",
            }}>
              {carrier.carrier_name || "Unknown Carrier"}
            </h4>
            <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
              {moveType && (
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                  background: "rgba(41,121,255,0.15)", color: "#2979ff",
                }}>
                  {moveType.toUpperCase()}
                </span>
              )}
              {caps.triaxle && (
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                  background: "rgba(0,200,83,0.15)", color: "#00c853",
                }}>
                  TRI-AXLE
                </span>
              )}
              {caps.hazmat && (
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                  background: "rgba(255,152,0,0.15)", color: "#ff9800",
                }}>
                  HAZMAT
                </span>
              )}
              {caps.overweight && (
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                  background: "rgba(156,39,176,0.15)", color: "#ce93d8",
                }}>
                  OVERWEIGHT
                </span>
              )}
              {caps.reefer && (
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                  background: "rgba(0,188,212,0.15)", color: "#00bcd4",
                }}>
                  REEFER
                </span>
              )}
            </div>
          </div>
        </div>

        <div style={{ textAlign: "right" }}>
          <p style={{
            fontSize: 20, fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 700, color: "#00c853", margin: 0,
            fontVariantNumeric: "tabular-nums",
          }}>
            {rate > 0 ? fmt(rate) : "\u2014"}
          </p>
          <div style={{
            fontSize: 10, color: "#5A6478", marginTop: 4,
            textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600,
          }}>
            Apply to Quote \u2192
          </div>
        </div>
      </div>

      {/* Score bar + metadata row */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{
            height: 4, borderRadius: 2, background: "rgba(255,255,255,0.06)", overflow: "hidden",
          }}>
            <div style={{
              height: "100%", borderRadius: 2, width: `${score}%`,
              background: score >= 75 ? "#00c853" : score >= 50 ? "#FBBF24" : "#fb923c",
              transition: "width 0.3s ease",
            }} />
          </div>
        </div>
        <span style={{
          fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 600, color: score >= 75 ? "#00c853" : score >= 50 ? "#FBBF24" : "#fb923c",
          minWidth: 28,
        }}>
          {score}
        </span>
        {lastDate && (
          <span style={{ fontSize: 10, color: "#5A6478" }}>
            Last: {lastDate}
          </span>
        )}
      </div>
    </div>
  );
}
