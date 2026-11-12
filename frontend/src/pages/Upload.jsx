import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Spinner, useToast } from "../components.jsx";

const DRIVE = (id) => `https://drive.google.com/drive/folders/${id}`;

export default function Upload({ status, refresh }) {
  const toast = useToast();
  const [owner, setOwner] = useState("");
  const [toDrive, setToDrive] = useState(true);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [results, setResults] = useState([]);
  const [sync, setSync] = useState(null);
  const [syncErr, setSyncErr] = useState("");

  useEffect(() => { api.syncStatus().then(setSync).catch(() => {}); }, []);
  const driveOn = !!status?.drive.configured;

  async function send(files) {
    const list = [...files].filter((f) => f.name.endsWith(".json"));
    if (!list.length) { toast("Only n8n .json exports are accepted", "bad"); return; }
    setBusy(`Analyzing ${list.length} workflow${list.length > 1 ? "s" : ""} with AI…`);
    try {
      const r = await api.upload(list, owner, toDrive && driveOn);
      setResults(r); refresh?.();
      const ok = r.filter((x) => x.status === "created").length;
      toast(ok ? `${ok} workflow${ok > 1 ? "s" : ""} added to the catalog` : "Nothing new added", ok ? "ok" : "");
    } catch (e) { setResults([{ file: "upload", status: "error", error: e.message }]); }
    setBusy("");
  }
  async function runSync(reanalyze) {
    setBusy("Syncing registry: reading the sheet, pulling JSON files and docs…"); setSyncErr("");
    try { const r = await api.sync(reanalyze); setSync({ at: new Date().toISOString(), result: r }); refresh?.(); toast("Registry synced", "ok"); }
    catch (e) { setSyncErr(e.message); }
    setBusy("");
  }
  async function runMainAi() {
    setBusy("Triggering MAIN AI in n8n…");
    try { const r = await api.runMainAi(); toast(`MAIN AI triggered (HTTP ${r.status}) — sync again in a few minutes`, "ok"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  }

  const r = sync?.result;
  return (
    <div className="rise">
      <h1>Add workflows</h1>
      <p className="muted" style={{ marginTop: 6 }}>Two ways in: pull everything MAIN AI has documented, or drop an export directly.</p>

      <div className="card section">
        <div className="row between"><h2>🔄 Registry sync</h2>{sync?.at && <span className="faint small">last sync {new Date(sync.at).toLocaleString()}{status?.sync.interval_minutes > 0 ? ` · auto every ${status.sync.interval_minutes} min` : ""}</span>}</div>
        <div className="pipeline">
          <div className="pstep"><b>AI Project</b>n8n JSON exports <a href={DRIVE(status?.drive.folder_id)} target="_blank" rel="noreferrer">open ↗</a></div>
          <div className="pstep"><b>MAIN AI</b>Compass documents each new flow</div>
          <div className="pstep"><b>Sheet + AI DOC</b><a href={`https://docs.google.com/spreadsheets/d/${status?.drive.sheet_id}`} target="_blank" rel="noreferrer">All N8N Flows ↗</a> · <a href={DRIVE(status?.drive.docs_folder_id)} target="_blank" rel="noreferrer">docs ↗</a></div>
          <div className="pstep"><b>FlowHub</b>indexes it for search &amp; adaptation</div>
        </div>
        {!driveOn && <div className="alert warn">Google access is not configured: save the service-account key as <code>backend/service-account.json</code> and share the two folders and the sheet with its <code>client_email</code> (see README).</div>}
        <div className="row">
          <button className="primary" onClick={() => runSync(false)} disabled={!!busy || !driveOn}>Sync registry now</button>
          <button onClick={() => runSync(true)} disabled={!!busy || !driveOn}>Sync + re-analyze all</button>
          <button onClick={runMainAi} disabled={!!busy || !status?.main_ai.webhook} title={status?.main_ai.webhook ? "" : "Set MAIN_AI_WEBHOOK_URL (import samples/MAIN AI (webhook-enabled).json)"}>▶ Run MAIN AI</button>
          {status?.main_ai.editor_url && <a href={status.main_ai.editor_url} target="_blank" rel="noreferrer"><button className="ghost">Open MAIN AI in n8n ↗</button></a>}
        </div>
        {syncErr && <div className="alert bad">{syncErr}</div>}
        {r && (
          <div className="row" style={{ marginTop: 14 }}>
            <div className="stat"><b>{r.rows}</b><span>sheet rows</span></div>
            <div className="stat"><b>{r.files}</b><span>JSON files</span></div>
            <div className="stat"><b>{r.synced.filter((s) => s.status !== "unchanged").length}</b><span>new / updated</span></div>
            <div className="stat" style={r.undocumented.length ? { borderColor: "#fcdcb0" } : {}}><b>{r.undocumented.length}</b><span>awaiting MAIN AI</span></div>
            {r.missing_json.length > 0 && <div className="alert warn" style={{ margin: 0 }}>{r.missing_json.length} sheet row(s) without a JSON file: {r.missing_json.join(", ")}</div>}
            {r.errors.length > 0 && <div className="alert bad" style={{ margin: 0 }}>{r.errors.map((e, i) => <div key={i}>{e.name}: {e.error}</div>)}</div>}
          </div>
        )}
      </div>

      <div className="card section">
        <h2>⬆ Upload an n8n export</h2>
        <p className="muted small">In n8n: ··· menu → Download. The AI analyzes it right away; with the box ticked it's also stored in AI Project so MAIN AI documents it on its next run.</p>
        <div className="row" style={{ marginBottom: 12 }}>
          <input style={{ maxWidth: 280 }} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Owner (who built it)" />
          <label className="check"><input type="checkbox" checked={toDrive && driveOn} disabled={!driveOn} onChange={(e) => setToDrive(e.target.checked)} /> also store in Drive “AI Project”</label>
        </div>
        <div className={"drop" + (over ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files); }}>
          <div className="big">📥</div>
          <b>Drag &amp; drop</b> n8n workflow .json files here, or <label style={{ color: "var(--brand)", cursor: "pointer", fontWeight: 600 }}>browse<input type="file" multiple accept=".json" style={{ display: "none" }} onChange={(e) => send(e.target.files)} /></label>
        </div>
      </div>

      {busy && <div className="section"><Spinner text={busy} /></div>}
      {results.length > 0 && (
        <div className="card section rise">
          <h2>Results</h2>
          <table>
            <thead><tr><th>File</th><th>Status</th><th>Workflow</th><th>Drive</th></tr></thead>
            <tbody>
              {results.map((x, i) => (
                <tr key={i}>
                  <td>{x.file}</td>
                  <td><span className={"chip " + ({ created: "ok", updated: "ok", duplicate: "gray", error: "bad", failed: "bad" }[x.status] || "gray")}>{x.status}</span></td>
                  <td>{x.asset ? <Link to={`/workflow/${x.asset.id}`}>{x.asset.name}</Link> : <span className="muted">{x.error}</span>}</td>
                  <td>{x.drive?.webViewLink ? <a href={x.drive.webViewLink} target="_blank" rel="noreferrer">stored ↗</a> : <span className="faint">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
