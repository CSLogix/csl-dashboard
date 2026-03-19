// ─── API Configuration ───
export const API_BASE: string = "";

export const apiFetch = (url: string, opts: RequestInit = {}): Promise<Response> =>
  fetch(url, { ...opts, credentials: "include" }).then(res => {
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Session expired"); }
    return res;
  });
