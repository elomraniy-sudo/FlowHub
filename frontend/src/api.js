async function req(path, opts = {}) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  status: () => req("/api/status"),
  facets: () => req("/api/facets"),
  assets: (params = {}) => req("/api/assets?" + new URLSearchParams(params)),
  asset: (id, raw = false) => req(`/api/assets/${id}${raw ? "?raw=true" : ""}`),
  remove: (id) => req(`/api/assets/${id}`, { method: "DELETE" }),
  reanalyze: (id) => req(`/api/assets/${id}/reanalyze`, { method: "POST" }),
  search: (query) => req("/api/search", json("POST", { query })),
  adapt: (id, use_case) => req(`/api/assets/${id}/adapt`, json("POST", { use_case })),
  customize: (id, body) => req(`/api/assets/${id}/customize`, json("POST", body)),
  run: (id, body) => req(`/api/assets/${id}/run`, json("POST", body)),
  trigger: (id, body) => req(`/api/assets/${id}/trigger`, json("POST", body)),
  runs: (id) => req(`/api/assets/${id}/runs`),
  upload: (files, owner, toDrive) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("owner", owner || "");
    fd.append("to_drive", toDrive ? "true" : "false");
    return req("/api/upload", { method: "POST", body: fd });
  },
  sync: (reanalyze = false) => req("/api/sync?reanalyze=" + reanalyze, { method: "POST" }),
  syncStatus: () => req("/api/sync"),
  runMainAi: () => req("/api/main-ai/run", { method: "POST" }),
  driveScan: (folder_id = "") => req("/api/drive/scan?" + new URLSearchParams({ folder_id }), { method: "POST" }),
};
