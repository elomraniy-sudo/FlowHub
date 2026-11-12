import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Chips, Spinner, TRIGGER_ICON, useToast } from "../components.jsx";

const KIND = { credential: "🔑", input: "⬇", output: "⬆", parameter: "⚙" };

export default function Detail({ status }) {
  const { id } = useParams();
  const [params] = useSearchParams();
  const toast = useToast();
  const [a, setA] = useState(null);
  const [tab, setTab] = useState(params.get("adapt") ? "adapt" : "overview");
  const [raw, setRaw] = useState(null);

  useEffect(() => { api.asset(id).then(setA); }, [id]);
  useEffect(() => { if ((tab === "json" || tab === "doc") && !raw) api.asset(id, true).then(setRaw); }, [tab]);

  if (!a) return <Spinner text="Loading workflow…" />;
  const n8nUrl = a.n8n_workflow_id && status?.n8n.base_url ? `${status.n8n.base_url.replace(/\/$/, "")}/workflow/${a.n8n_workflow_id}` : "";
  const TABS = [["overview", "Overview"], ["adapt", "✨ Adapt for my use case"], ["history", "🕘 History"], ...(a.has_doc ? [["doc", "📄 Documentation"]] : []), ["json", "JSON"]];

  return (
    <div className="rise">
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div>
          <h1>{a.name}</h1>
          <div className="meta" style={{ marginTop: 8 }}>
            <span className="chip cat">{a.category}</span>
            <span>{TRIGGER_ICON[a.trigger_type]} {a.trigger_type}</span>
            {a.owner && <span>built by <b>{a.owner}</b></span>}
            {a.in_registry ? <span className="chip ok">in registry · MAIN AI</span> : a.source === "drive" && <span className="chip warn">awaiting MAIN AI doc</span>}
            {a.n8n_workflow_id && <span>n8n <code>{a.n8n_workflow_id}</code></span>}
            {a.analysis_status !== "done" && <span className="chip bad">analysis {a.analysis_status}</span>}
          </div>
        </div>
        <div className="row">
          {a.doc_link && <a href={a.doc_link} target="_blank" rel="noreferrer"><button className="sm">📄 Google Doc</button></a>}
          {n8nUrl && <a href={n8nUrl} target="_blank" rel="noreferrer"><button className="sm">Open original in n8n ↗</button></a>}
        </div>
      </div>

      <div className="tabs">{TABS.map(([t, l]) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{l}</button>)}</div>

      {tab === "overview" && <Overview a={a} goAdapt={() => setTab("adapt")} />}
      {tab === "adapt" && <Adapt a={a} status={status} />}
      {tab === "history" && <History a={a} status={status} />}
      {tab === "doc" && (raw ? (
        <div className="card">
          <div className="muted small" style={{ marginBottom: 12 }}>Written by the MAIN AI workflow (Compass) · <a href={a.doc_link} target="_blank" rel="noreferrer">open in Google Docs ↗</a></div>
          <div className="doc">{raw.doc_text}</div>
        </div>
      ) : <Spinner text="Loading…" />)}
      {tab === "json" && (raw ? (
        <>
          <div className="row" style={{ marginBottom: 10 }}>
            <button className="sm" onClick={() => { navigator.clipboard.writeText(JSON.stringify(raw.raw, null, 2)); toast("JSON copied", "ok"); }}>⧉ Copy</button>
            <button className="sm" onClick={() => dl(raw.raw, a.name)}>⬇ Download</button>
          </div>
          <pre>{JSON.stringify(raw.raw, null, 2)}</pre>
        </>
      ) : <Spinner text="Loading…" />)}
    </div>
  );
}

function dl(obj, name) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const u = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: u, download: name.replace(/[^\w.-]+/g, "_") + ".json" }).click();
  URL.revokeObjectURL(u);
}

/* ---------------- overview ---------------- */
function Overview({ a, goAdapt }) {
  const mustChange = (a.customizable || []).filter((c) => c.kind !== "parameter" || /id|url|path|channel|email|table|sheet|folder|query/i.test(c.path || ""));
  return (
    <div className="two">
      <div>
        <div className="card">
          <h2>What it does</h2>
          <p style={{ fontSize: 15, color: "var(--ink-2)" }}>{a.summary}</p>
          {a.sheet_description && a.sheet_description !== a.summary && <p className="muted small">Registry description: {a.sheet_description}</p>}
          <Chips items={a.tags} cls="gray" />
        </div>
        <div className="card section">
          <h2>Inputs → outputs</h2>
          <div className="io">
            {a.inputs.map((x, i) => <div key={"i" + i} className="io-item in"><div className="ic">⬇</div><div><b>{x.name}</b><span>{x.description}</span></div></div>)}
            {a.outputs.map((x, i) => <div key={"o" + i} className="io-item out"><div className="ic">⬆</div><div><b>{x.name}</b><span>{x.description}</span></div></div>)}
          </div>
        </div>
        <div className="card section">
          <h2>Typical use cases</h2>
          <ul style={{ margin: 0 }}>{a.use_cases.map((u, i) => <li key={i}>{u}</li>)}</ul>
        </div>
      </div>
      <div>
        <div className="card" style={{ background: "linear-gradient(135deg,#fff,#f5f3ff)" }}>
          <h2>To reuse it you'd change</h2>
          <p className="muted small">Everything else stays as is.</p>
          <div className="node-list">
            {mustChange.map((c) => (
              <div key={c.key} className="node"><span>{KIND[c.kind]} {c.label}</span><code>{c.node}</code></div>
            ))}
          </div>
          <button className="primary" style={{ marginTop: 14 }} onClick={goAdapt}>✨ Adapt it for my use case</button>
        </div>
        <div className="card section">
          <h2>Integrations</h2>
          <Chips items={a.integrations} />
          {a.credentials_required.length > 0 && <><h4 style={{ margin: "14px 0 8px" }}>Credentials</h4>
            <div className="node-list">{a.credentials_required.map((c, i) => <div key={i} className="node"><span>🔑 {c.type}</span><code>{c.node}</code></div>)}</div></>}
        </div>
        <details className="section"><summary>Nodes ({a.nodes.filter((n) => n.type !== "stickyNote").length})</summary>
          <div className="node-list" style={{ marginTop: 10 }}>{a.nodes.filter((n) => n.type !== "stickyNote").map((n, i) => <div key={i} className="node"><span>{n.name}</span><code>{n.type}</code></div>)}</div>
        </details>
      </div>
    </div>
  );
}

/* ---------------- adapt wizard ---------------- */
function Adapt({ a, status }) {
  const toast = useToast();
  const [useCase, setUseCase] = useState("");
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState("");
  const [values, setValues] = useState({});
  const [name, setName] = useState(a.name + " — my copy");
  const [action, setAction] = useState("download");
  const activate = false;
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [applyStructural, setApplyStructural] = useState(true);
  const [run, setRun] = useState(null);
  const step = result ? 3 : plan ? 2 : 1;

  // only what the AI says must change for THIS use case; required first; then values the NEW nodes need
  const baseFields = useMemo(() => (plan?.fields || []).slice().sort((x, y) => (y.required ? 1 : 0) - (x.required ? 1 : 0)), [plan]);
  const newFields = useMemo(() => (applyStructural ? plan?.new_fields || [] : []).map((f) => ({ ...f, required: true })), [plan, applyStructural]);
  const fields = useMemo(() => [...baseFields, ...newFields], [baseFields, newFields]);
  const filled = (f) => { const v = values[f.key]; return f.kind === "credential" ? !!v?.name : v !== undefined && v !== ""; };
  const requiredLeft = fields.filter((f) => f.required && !filled(f)).length;
  const progress = fields.length ? Math.round((fields.filter(filled).length / fields.length) * 100) : 0;

  async function analyze() {
    if (!useCase.trim()) return;
    setBusy("Comparing your use case with the workflow…"); setErr(""); setResult(null); setPlan(null);
    try {
      const p = await api.adapt(a.id, useCase);
      setPlan(p);
      const v = {};
      p.fields.forEach((f) => { if (f.suggested_value) v[f.key] = f.kind === "credential" ? { name: f.suggested_value } : f.suggested_value; });
      setValues(v);
    } catch (e) { setErr(e.message); }
    setBusy("");
  }
  async function generate() {
    setBusy("Generating your workflow…"); setErr(""); setRun(null);
    try {
      const r = await api.customize(a.id, { values, new_name: name, action, activate, use_case: useCase, apply_structural: applyStructural,
        ops: applyStructural ? plan?.ops || [] : [], new_fields: applyStructural ? plan?.new_fields || [] : [] });
      setResult(r); toast("Workflow generated", "ok");
    } catch (e) { setErr(e.message); }
    setBusy("");
  }
  async function runNow() {
    setBusy("Sending to n8n and running…"); setRun(null);
    try { const r = await api.run(a.id, { workflow: result.workflow }); setRun(r); toast(r.error ? "n8n returned an error" : r.mode === "execute" ? "Executed in n8n" : "Created and activated in n8n", r.error ? "bad" : "ok"); }
    catch (e) { setRun({ error: e.message }); }
    setBusy("");
  }

  return (
    <>
      <div className="stepper">
        {["Describe your use case", "Fill in what changes", "Get your workflow"].map((l, i) => (
          <div key={l} className={"step " + (step === i + 1 ? "active" : step > i + 1 ? "done" : "")}><span className="num">{step > i + 1 ? "✓" : i + 1}</span>{l}</div>
        ))}
      </div>

      <div className="two">
        <div>
          <div className="card">
            <h2>What do you want it to do for you?</h2>
            <p className="muted small">Mention your sources, destinations, names, schedule — anything that differs from the original.</p>
            <textarea value={useCase} onChange={(e) => setUseCase(e.target.value)}
              placeholder="e.g. Same thing but reading the Marketing team's sheet (tab 'Campaigns') and posting to #marketing-daily at 9am" />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="primary" onClick={analyze} disabled={!!busy || !useCase.trim()}>{plan ? "↻ Re-check" : "Tell me what to change"}</button>
              {plan && <span className="faint small">{fields.length} field{fields.length === 1 ? "" : "s"} need your input</span>}
            </div>
          </div>
          {busy && <div className="section"><Spinner text={busy} /></div>}
          {err && <div className="alert bad">{err}</div>}
          {plan && (
            <div className="card section rise">
              <div className={"fit " + plan.fit}>
                <div className="big">{{ good: "🎯", partial: "🧩", poor: "🚧" }[plan.fit] || "🧩"}</div>
                <div><b style={{ textTransform: "capitalize" }}>{plan.fit} fit.</b> {plan.fit_explanation}</div>
              </div>
              {plan.steps.length > 0 && <><h4 style={{ margin: "16px 0 6px" }}>How to adapt it</h4><ol className="steps">{plan.steps.map((s, i) => <li key={i}>{s}</li>)}</ol></>}
              {plan.structural_changes.length > 0 && (
                <div className={"alert " + (plan.patch_error ? "bad" : "info")} style={{ marginBottom: 0 }}>
                  <b>Node changes {plan.patch_error ? "requested" : "the AI built for your copy"}:</b>
                  <ul style={{ margin: "6px 0 8px" }}>{(plan.node_changes?.length ? plan.node_changes : plan.structural_changes).map((s, i) => <li key={i}>{s}</li>)}</ul>
                  {plan.patch_error ? <span className="small">{plan.patch_error}</span> : (
                    <label className="check"><input type="checkbox" checked={applyStructural} onChange={(e) => setApplyStructural(e.target.checked)} /> include these node changes in my copy{plan.new_fields?.length ? ` (${plan.new_fields.length} value${plan.new_fields.length > 1 ? "s" : ""} to fill on the right)` : ""}</label>
                  )}
                  {plan.notes?.length > 0 && <div className="small" style={{ marginTop: 8 }}><b>Note:</b> {plan.notes.join(" · ")}</div>}
                </div>
              )}
            </div>
          )}
        </div>

        <div>
          {!plan && (
            <div className="card" style={{ borderStyle: "dashed", background: "transparent", boxShadow: "none" }}>
              <div className="empty" style={{ padding: 30 }}><div className="big">✨</div>Describe your case and the AI lists only the fields you must change — credentials, sources, destinations. Nothing else.</div>
            </div>
          )}
          {plan && !result && (
            <div className="card rise">
              <div className="row between"><h2>Fill in what changes</h2><span className="faint small">{progress}%</span></div>
              <div className="progress"><div style={{ width: progress + "%" }} /></div>
              <div className={"field " + (name ? "filled" : "")}><label>New workflow name</label><input value={name} onChange={(e) => setName(e.target.value)} /></div>
              {fields.length === 0 && <div className="alert ok">Nothing needs to change — you can use this workflow as is.</div>}
              {baseFields.map((f) => <Field key={f.key} f={f} values={values} setValues={setValues} filled={filled(f)} />)}
              {newFields.length > 0 && (
                <>
                  <h4 style={{ margin: "18px 0 8px" }}>✚ For the new nodes</h4>
                  <p className="muted small" style={{ marginTop: -4 }}>The nodes the AI added need these values. They are written straight into the workflow — nothing to edit by hand.</p>
                  {newFields.map((f) => <Field key={f.key} f={f} values={values} setValues={setValues} filled={filled(f)} />)}
                </>
              )}

              <div className="row" style={{ marginTop: 18 }}>
                <label className="check" title={status?.drive.configured ? "" : "Google Drive not configured"}>
                  <input type="checkbox" disabled={!status?.drive.configured} checked={action === "drive"} onChange={(e) => setAction(e.target.checked ? "drive" : "download")} />
                  also save a copy to Google Drive (AI Project) so MAIN AI documents it
                </label>
              </div>
              <div className="row" style={{ marginTop: 14 }}>
                <button className="primary" onClick={generate} disabled={!!busy}>Generate workflow →</button>
                {requiredLeft > 0 && <span className="small" style={{ color: "var(--warn)" }}>{requiredLeft} required field{requiredLeft > 1 ? "s" : ""} still empty — blank credentials will be asked for in n8n</span>}
              </div>
            </div>
          )}
          {result && (
            <div className="success-card rise">
              <h2>🎉 Your workflow is ready</h2>
              <p className="muted small">A new copy was created — the original in the catalog is untouched. Credentials you left blank were removed, so n8n will ask you to pick yours.</p>
              {result.node_changes?.length > 0 && (
                <div className="alert ok"><b>Node changes applied:</b><ul style={{ margin: "6px 0 0" }}>{result.node_changes.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
              )}
              {result.unfilled?.length > 0 && <div className="alert warn"><b>Left empty</b> (still a placeholder in the workflow): {result.unfilled.join(", ")} — <a onClick={() => { setResult(null); setRun(null); }} style={{ cursor: "pointer" }}>go back and fill them</a>.</div>}
              {result.notes?.length > 0 && <div className="alert warn"><b>Note:</b><ul style={{ margin: "6px 0 0" }}>{result.notes.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
              {result.patch_error && <div className="alert bad">{result.patch_error}</div>}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="primary" onClick={runNow} disabled={!result.runnable || !!busy} title={result.runnable ? "" : "Set N8N_RUN_WEBHOOK_URL (import samples/FlowHub Runner.json)"}>
                  {result.trigger_type === "manual" ? "▶ Run in n8n now" : "▶ Deploy & activate in n8n"}
                </button>
                <button onClick={() => dl(result.workflow, name)}>⬇ Download JSON</button>
                {result.drive?.webViewLink && <a href={result.drive.webViewLink} target="_blank" rel="noreferrer"><button>Open in Drive ↗</button></a>}
                <button className="ghost" onClick={() => { setResult(null); setRun(null); }}>← Edit values</button>
              </div>
              {!result.runnable && <p className="faint tiny" style={{ marginTop: 8 }}>Running from here needs the FlowHub Runner workflow in n8n (see README).</p>}
              {busy && <div style={{ marginTop: 10 }}><Spinner text={busy} /></div>}
              {run && (
                <div className={"alert " + (run.error || run.n8n?.ok === false ? "bad" : "ok")} style={{ marginBottom: 0 }}>
                  {run.error ? run.error : run.n8n?.ok === false ? <><b>n8n ran it but it failed:</b> {run.n8n.error}</> : (
                    <>
                      <b>{run.mode === "execute" ? "Executed in n8n." : "Created and activated in n8n."}</b>
                      {run.n8n?.workflowName && <> Workflow <code>{run.n8n.workflowName}</code>{run.n8n.workflowId && <> (id {run.n8n.workflowId})</>}.</>}
                      {run.n8n?.outputCount !== undefined && <> Produced {run.n8n.outputCount} item{run.n8n.outputCount === 1 ? "" : "s"}.</>}
                      {run.n8n?.webhookUrl && <> Live at <code>{run.n8n.webhookUrl}</code>.</>}
                      {run.editor_url && <> <a href={run.editor_url} target="_blank" rel="noreferrer">open in n8n ↗</a></>}
                    </>
                  )}
                  {run.n8n?.output?.length > 0 && <details style={{ marginTop: 8 }}><summary>Output</summary><pre style={{ marginTop: 8, maxHeight: 260 }}>{JSON.stringify(run.n8n.output, null, 2)}</pre></details>}
                </div>
              )}
              {result.drive_error && <div className="alert bad">Drive: {result.drive_error}</div>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Field({ f, values, setValues, filled }) {
  const v = values[f.key];
  return (
    <div className={"field " + (f.required ? "required " : "") + (filled ? "filled" : "")}>
      <label><span>{KIND[f.kind]}</span>{f.label}<span className="chip gray" style={{ fontWeight: 500 }}>{f.node}</span></label>
      {f.kind === "credential" ? (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input placeholder="Credential name in your n8n (blank = choose in n8n)" value={v?.name || ""}
            onChange={(e) => setValues({ ...values, [f.key]: { ...(v || {}), name: e.target.value } })} />
          <input style={{ width: 150, flex: "0 0 auto" }} placeholder="id (optional)" value={v?.id || ""}
            onChange={(e) => setValues({ ...values, [f.key]: { ...(v || {}), id: e.target.value } })} />
        </div>
      ) : (
        <input placeholder={f.example ? `e.g. ${f.example}` : "Your value"} value={v ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
      )}
      <div className="hint">{f.why || f.description}</div>
      {f.example && <div className="current">currently: <code>{String(f.example)}</code></div>}
    </div>
  );
}

/* ---------------- history ---------------- */
const ACTION = { run: ["▶", "Ran in n8n"], deploy: ["🚀", "Created in n8n"], drive_upload: ["☁", "Saved to Drive"], trigger: ["⚡", "Webhook called"] };

function History({ a, status }) {
  const [runs, setRuns] = useState(null);
  useEffect(() => { api.runs(a.id).then(setRuns); }, [a.id]);
  const n8nBase = status?.n8n.base_url?.replace(/\/$/, "");
  return (
    <div className="card">
      <h2>What was generated from this workflow</h2>
      <p className="muted small">Every copy adapted here and sent to n8n or Drive. The original workflow is never changed.</p>
      {!runs ? <Spinner text="Loading…" /> : runs.length === 0 ? (
        <div className="empty" style={{ padding: 24 }}>Nothing yet — use <b>Adapt for my use case</b> to create and run a copy.</div>
      ) : (
        <table>
          <thead><tr><th>When</th><th>Action</th><th>Result</th><th>Who</th></tr></thead>
          <tbody>{runs.map((r, i) => {
            const [ic, label] = ACTION[r.action] || ["•", r.action];
            const d = r.detail || {};
            const wfId = d.workflowId || d.id;
            return (
              <tr key={i}>
                <td className="muted small" style={{ whiteSpace: "nowrap" }}>{new Date(r.at + "Z").toLocaleString()}</td>
                <td>{ic} {label}{d.mode ? <span className="muted small"> · {d.mode}</span> : null}</td>
                <td className="small">
                  {d.error ? <span style={{ color: "var(--bad)" }}>{String(d.error).slice(0, 120)}</span> : d.status ? `HTTP ${d.status}` : d.webViewLink ? <a href={d.webViewLink} target="_blank" rel="noreferrer">open in Drive ↗</a> : "ok"}
                  {wfId && n8nBase && <> · <a href={`${n8nBase}/workflow/${wfId}`} target="_blank" rel="noreferrer">open in n8n ↗</a></>}
                </td>
                <td className="muted small">{r.user || "—"}</td>
              </tr>
            );
          })}</tbody>
        </table>
      )}
    </div>
  );
}
