import { useState, useEffect } from 'react';
import { apiFetch, API_BASE } from '../helpers/api';

export default function UserManagementView({ API_BASE, apiFetchFn }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ username: "", email: "", password: "", role: "rep", rep_name: "" });
  const [addError, setAddError] = useState(null);
  const [resetUserId, setResetUserId] = useState(null);
  const [resetPw, setResetPw] = useState("");

  const fetchUsers = useCallback(async () => {
    try {
      const res = await apiFetchFn(`${API_BASE}/api/users`);
      if (res.ok) { const data = await res.json(); setUsers(data); }
    } catch {} finally { setLoading(false); }
  }, [API_BASE, apiFetchFn]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleAddUser = async (e) => {
    e.preventDefault();
    setAddError(null);
    try {
      const res = await apiFetchFn(`${API_BASE}/api/users`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(addForm) });
      if (res.ok) { setShowAdd(false); setAddForm({ username: "", email: "", password: "", role: "rep", rep_name: "" }); fetchUsers(); }
      else { const d = await res.json(); setAddError(d.error || "Failed"); }
    } catch { setAddError("Network error"); }
  };

  const handleResetPassword = async (userId) => {
    if (resetPw.length < 8) return;
    try {
      await apiFetchFn(`${API_BASE}/api/users/${userId}/reset-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_password: resetPw }) });
      setResetUserId(null); setResetPw("");
    } catch {}
  };

  const handleToggleActive = async (user) => {
    if (user.role === "admin") return; // safety
    try {
      if (user.is_active) {
        await apiFetchFn(`${API_BASE}/api/users/${user.id}`, { method: "DELETE" });
      } else {
        await apiFetchFn(`${API_BASE}/api/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: true }) });
      }
      fetchUsers();
    } catch {}
  };

  const inputStyle = { width: "100%", padding: "8px 12px", background: "#0a0d12", border: "1px solid #1e2a3d", borderRadius: 8, color: "#e8ecf4", fontSize: 12, outline: "none", fontFamily: "inherit" };
  const labelStyle = { display: "block", fontSize: 11, color: "#7b8ba3", marginBottom: 3, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" };

  return (
    <div style={{ padding: "20px 0" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 800, color: "#F0F2F5", marginBottom: 2 }}>User Management</h2>
          <p style={{ fontSize: 11, color: "#7b8ba3" }}>{users.length} users configured</p>
        </div>
        <button onClick={() => setShowAdd(!showAdd)}
          style={{ padding: "8px 16px", background: "linear-gradient(135deg, #3b82f6, #2563eb)", border: "none", borderRadius: 8, color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
          + Add User
        </button>
      </div>

      {/* Add User Form */}
      {showAdd && (
        <div style={{ background: "#161e2c", border: "1px solid #1e2a3d", borderRadius: 12, padding: 20, marginBottom: 20 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: "#e8ecf4", marginBottom: 14 }}>New User</h3>
          {addError && <div style={{ padding: "8px 12px", borderRadius: 8, background: "rgba(239,68,68,0.1)", color: "#ef4444", fontSize: 11, marginBottom: 12 }}>{addError}</div>}
          <form onSubmit={handleAddUser} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div><label style={labelStyle}>Username</label><input value={addForm.username} onChange={e => setAddForm({ ...addForm, username: e.target.value })} required style={inputStyle} /></div>
            <div><label style={labelStyle}>Email</label><input type="email" value={addForm.email} onChange={e => setAddForm({ ...addForm, email: e.target.value })} style={inputStyle} /></div>
            <div><label style={labelStyle}>Password</label><input type="password" value={addForm.password} onChange={e => setAddForm({ ...addForm, password: e.target.value })} required minLength={8} style={inputStyle} /></div>
            <div><label style={labelStyle}>Rep Name</label><input value={addForm.rep_name} onChange={e => setAddForm({ ...addForm, rep_name: e.target.value })} style={inputStyle} placeholder="e.g. John F" /></div>
            <div>
              <label style={labelStyle}>Role</label>
              <select value={addForm.role} onChange={e => setAddForm({ ...addForm, role: e.target.value })} style={{ ...inputStyle, cursor: "pointer" }}>
                <option value="rep">Rep</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button type="submit" style={{ padding: "8px 20px", background: "linear-gradient(135deg, #22c55e, #16a34a)", border: "none", borderRadius: 8, color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>Create</button>
            </div>
          </form>
        </div>
      )}

      {/* Users Table */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 40, color: "#7b8ba3" }}>Loading...</div>
      ) : (
        <div style={{ background: "#161e2c", border: "1px solid #1e2a3d", borderRadius: 12, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                {["Username", "Email", "Role", "Rep Name", "Last Login", "Status", "Actions"].map(h => (
                  <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#7b8ba3", letterSpacing: "0.5px", textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", opacity: u.is_active ? 1 : 0.5 }}>
                  <td style={{ padding: "10px 14px", color: "#e8ecf4", fontWeight: 600 }}>{u.username}</td>
                  <td style={{ padding: "10px 14px", color: "#8B95A8" }}>{u.email || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: "0.5px",
                      background: u.role === "admin" ? "rgba(245,158,11,0.12)" : "rgba(59,130,246,0.12)",
                      color: u.role === "admin" ? "#f59e0b" : "#3b82f6" }}>
                      {u.role.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: "10px 14px", color: "#8B95A8" }}>{u.rep_name || "—"}</td>
                  <td style={{ padding: "10px 14px", color: "#7b8ba3", fontSize: 11 }}>{u.last_login ? new Date(u.last_login).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Never"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                      background: u.is_active ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.1)",
                      color: u.is_active ? "#22c55e" : "#ef4444" }}>
                      {u.is_active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <div style={{ display: "flex", gap: 6 }}>
                      {resetUserId === u.id ? (
                        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                          <input type="password" value={resetPw} onChange={e => setResetPw(e.target.value)} placeholder="New password (8+)" style={{ ...inputStyle, width: 140, padding: "4px 8px", fontSize: 11 }} />
                          <button onClick={() => handleResetPassword(u.id)} style={{ padding: "4px 8px", background: "#3b82f6", border: "none", borderRadius: 4, color: "#fff", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Set</button>
                          <button onClick={() => { setResetUserId(null); setResetPw(""); }} style={{ padding: "4px 8px", background: "none", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, color: "#8B95A8", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>X</button>
                        </div>
                      ) : (
                        <>
                          <button onClick={() => setResetUserId(u.id)} style={{ padding: "4px 8px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4, color: "#8B95A8", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>Reset PW</button>
                          <button onClick={() => handleToggleActive(u)} style={{ padding: "4px 8px", background: u.is_active ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.08)", border: `1px solid ${u.is_active ? "rgba(239,68,68,0.2)" : "rgba(34,197,94,0.2)"}`, borderRadius: 4, color: u.is_active ? "#ef4444" : "#22c55e", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
