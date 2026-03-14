// ─── API Configuration ───
export const API_BASE = "";

export const apiFetch = (url, opts = {}) =>
  fetch(url, { ...opts, credentials: "include" }).then(res => {
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Session expired"); }
    return res;
  });
