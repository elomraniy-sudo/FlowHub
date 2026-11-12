import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Spinner, WorkflowCard } from "../components.jsx";

const EXAMPLES = [
  "Send a daily summary of a Google Sheet to Slack",
  "Save incoming PDFs to Drive and notify finance",
  "Label and assign new Jira tickets with AI",
  "Email me if revenue in a sheet drops week over week",
];
const PHASES = ["Reading your request…", "Scanning the catalog…", "Comparing inputs, outputs and triggers…", "Working out what you'd need to change…"];

export default function Search() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState(0);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [stats, setStats] = useState(null);
  const inputRef = useRef();

  useEffect(() => { api.status().then(setStats).catch(() => {}); }, []);
  useEffect(() => {
    if (!loading) return;
    setPhase(0);
    const t = setInterval(() => setPhase((p) => Math.min(p + 1, PHASES.length - 1)), 1800);
    return () => clearInterval(t);
  }, [loading]);

  async function run(query) {
    const text = (query ?? q).trim();
    if (!text) { inputRef.current?.focus(); return; }
    setQ(text); setLoading(true); setErr(""); setRes(null);
    try { setRes(await api.search(text)); } catch (e) { setErr(e.message); } finally { setLoading(false); }
  }

  return (
    <>
      <div className={"hero rise" + (res || loading ? " compact" : "")}>
        <h1>Has someone already built this?</h1>
        <p>Describe what you want to automate. FlowHub searches every workflow in the company and tells you exactly what to change to reuse it.</p>
        <form className="searchbar" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. post a weekly report from BigQuery to Slack" autoFocus />
          <button className="primary" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
        </form>
        <div className="examples">{EXAMPLES.map((e) => <button key={e} type="button" onClick={() => run(e)}>{e}</button>)}</div>
        {stats && !res && !loading && <p className="faint small" style={{ marginTop: 18 }}>{stats.assets} workflows indexed · {stats.in_registry} documented by MAIN AI</p>}
      </div>

      {loading && <div style={{ maxWidth: 560, margin: "0 auto" }}><Spinner text={PHASES[phase]} /></div>}
      {err && <div className="alert bad">{err}</div>}
      {res && (
        <div className="rise">
          {res.results.length === 0 ? (
            <div className="card" style={{ maxWidth: 680, margin: "0 auto", textAlign: "center" }}>
              <div className="big" style={{ fontSize: 36 }}>🧭</div>
              <h3 style={{ margin: "8px 0" }}>Nothing close enough exists yet</h3>
              <p className="muted">{res.no_match_advice || "No workflow in the catalog covers this."}</p>
              <p className="muted small">Build it in n8n, then <Link to="/upload">add it to FlowHub</Link> so the next person finds it.</p>
            </div>
          ) : (
            <>
              <div className="row between" style={{ marginBottom: 12 }}>
                <h2>{res.results.length} match{res.results.length > 1 ? "es" : ""} for “{q}”</h2>
                <span className="faint small">ranked by fit · click a card to adapt it</span>
              </div>
              {res.no_match_advice && <div className="alert info">{res.no_match_advice}</div>}
              <div className="grid stagger">{res.results.map((a) => <WorkflowCard key={a.id} a={a} result />)}</div>
            </>
          )}
        </div>
      )}
    </>
  );
}
