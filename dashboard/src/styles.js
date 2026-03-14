// Global CSS injected by DispatchDashboard — extracted for readability
export const GLOBAL_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
  :root { --bg-base: #0A0E17; --bg-card: #141A28; --bg-elevated: #1A2236; --bg-input: #0D1119; --border-card: rgba(255,255,255,0.10); --border-emphasis: rgba(255,255,255,0.16); --text-primary: #F0F2F5; --text-secondary: #8B95A8; --text-tertiary: #5A6478; --text-muted: #3D4557; --brand-green: #00D4AA; --brand-cyan: #00A8CC; --brand-blue: #0088E8; --brand-gradient: linear-gradient(135deg, #00D4AA, #00A8CC, #0088E8); --radius-card: 14px; --shadow-card: 0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2); --shadow-elevated: 0 4px 16px rgba(0,0,0,0.4), 0 8px 32px rgba(0,0,0,0.2); }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  ::-webkit-scrollbar { width: 5px; height: 5px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #ffffff15; border-radius: 10px; }
  .dispatch-table-wrap { scrollbar-color: #3D4557 rgba(255,255,255,0.04); }
  .dispatch-table-wrap::-webkit-scrollbar { height: 12px; width: 6px; }
  .dispatch-table-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,0.04); border-radius: 10px; }
  .dispatch-table-wrap::-webkit-scrollbar-thumb { background: #3D4557; border-radius: 10px; min-width: 40px; }
  .dispatch-table-wrap::-webkit-scrollbar-thumb:hover { background: #5A6478; }
  .dispatch-table-wrap::-webkit-scrollbar-corner { background: transparent; }
  input, select, textarea { font-family: 'Plus Jakarta Sans', sans-serif; }
  @keyframes pulse-glow { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
  @keyframes slide-up { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes slide-down { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes slide-right { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
  @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  @keyframes glow-pulse { 0%, 100% { box-shadow: 0 0 16px rgba(0,222,180,0.08); } 50% { box-shadow: 0 0 28px rgba(0,222,180,0.18); } }
  @keyframes alert-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 6px rgba(239,68,68,0.5); } 50% { opacity: 0.6; box-shadow: 0 0 12px rgba(239,68,68,0.3); } }
  @keyframes unbilled-pulse { 0%, 100% { box-shadow: 0 0 8px rgba(249,115,22,0.15); border-color: rgba(249,115,22,0.4); } 50% { box-shadow: 0 0 20px rgba(249,115,22,0.3); border-color: rgba(249,115,22,0.7); } }
  @keyframes row-highlight { 0% { background: rgba(0,212,170,0.25); } 100% { background: transparent; } }
  .row-highlight-pulse { animation: row-highlight 3s ease-out forwards; }
  .glass { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: var(--radius-card); box-shadow: var(--shadow-card); position: relative; }
  .glass::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); border-radius: var(--radius-card) var(--radius-card) 0 0; pointer-events: none; }
  .glass-strong { background: var(--bg-elevated); border: 1px solid var(--border-emphasis); border-radius: var(--radius-card); box-shadow: var(--shadow-elevated); position: relative; }
  .glass-strong::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent); border-radius: var(--radius-card) var(--radius-card) 0 0; pointer-events: none; }
  .row-hover { transition: all 0.2s ease; } .row-hover:hover { background: rgba(255,255,255,0.04) !important; }
  .btn-primary { background: var(--brand-gradient); transition: all 0.3s ease; position: relative; overflow: hidden; }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 30px -5px #00D4AA55; }
  .dash-panel { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: var(--radius-card); box-shadow: var(--shadow-card); position: relative; overflow: hidden; }
  .dash-panel::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); pointer-events: none; z-index: 1; }
  .dash-panel-title { font-size: 14px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.3px; }
  .nav-item { transition: all 0.2s ease; cursor: pointer; border: none; background: none; }
  .nav-item:hover { background: rgba(0,212,170,0.06) !important; }
  .rep-card { transition: all 0.25s ease; cursor: pointer; }
  .rep-card:hover { transform: translateY(-2px); border-color: rgba(0,212,170,0.3) !important; background: rgba(0,212,170,0.04) !important; }
  .acct-card { transition: all 0.2s ease; cursor: pointer; }
  .acct-card:hover { border-color: rgba(0,212,170,0.3) !important; background: rgba(0,212,170,0.05) !important; }
  .status-card { transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; }
  .status-card:hover { transform: translateY(-3px) scale(1.02); }
  .metric-card { position: relative; overflow: hidden; }
  input[type="date"]::-webkit-calendar-picker-indicator, input[type="time"]::-webkit-calendar-picker-indicator { filter: invert(0.7); cursor: pointer; padding: 4px; }
  input[type="date"], input[type="time"] { min-height: 32px; }
  @media (max-width: 768px) {
    .dash-grid-2 { grid-template-columns: 1fr !important; }
    .dash-sidebar { display: none !important; }
    .dash-topbar { padding: 8px 12px !important; }
    .dash-content-area { padding: 0 10px 66px !important; }
    .dash-stat-row { display: flex !important; overflow-x: auto !important; scroll-snap-type: x mandatory !important; -webkit-overflow-scrolling: touch !important; gap: 8px !important; flex-wrap: nowrap !important; padding-bottom: 4px !important; }
    .dash-stat-row > div { flex: 0 0 auto !important; min-width: 110px !important; scroll-snap-align: start !important; }
    .mobile-bottom-nav { display: flex !important; }
    .mobile-card-view { display: block !important; }
    .desktop-table-view { display: none !important; }
    .inbox-thread-panel { width: 100vw !important; border-left: none !important; }
  }
  @media (min-width: 769px) {
    .mobile-bottom-nav { display: none !important; }
    .mobile-card-view { display: none !important; }
  }
  @media (max-width: 480px) {
    .dash-stat-row > div { padding: 10px 8px !important; min-width: 100px !important; }
    .dash-stat-row .stat-value { font-size: 22px !important; }
    .dash-stat-row .stat-label { font-size: 9px !important; }
  }
`;
