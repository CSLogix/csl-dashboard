import { useState, useEffect } from "react";

export default function ClockDisplay({ lastSyncTime, apiError }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const i = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(i); }, []);
  const timeStr = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true });
  const syncAgo = lastSyncTime ? Math.floor((now - lastSyncTime) / 1000) : null;
  const syncLabel = syncAgo !== null ? (syncAgo < 60 ? "just now" : syncAgo < 3600 ? `${Math.floor(syncAgo / 60)}m ago` : `${Math.floor(syncAgo / 3600)}h ago`) : "...";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <div style={{ width: 6, height: 6, borderRadius: "50%", background: apiError ? "#EF4444" : syncAgo !== null && syncAgo < 120 ? "#22C55E" : "#F59E0B", animation: apiError ? "alert-pulse 1.5s ease infinite" : "none" }} />
        <span style={{ fontSize: 11, color: "#8B95A8", fontFamily: "'JetBrains Mono', monospace" }}>{timeStr}</span>
      </div>
      <span style={{ fontSize: 11, color: "#5A6478", fontFamily: "'JetBrains Mono', monospace" }}>sync {syncLabel}</span>
    </div>
  );
}
