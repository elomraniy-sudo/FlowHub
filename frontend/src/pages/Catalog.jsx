import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Skeleton, WorkflowCard } from "../components.jsx";

export default function Catalog() {
  const [facets, setFacets] = useState({ categories: [], integrations: [] });
  const [filter, setFilter] = useState({ category: "", integration: "", q: "" });
  const [rows, setRows] = useState(null);
  const [sync, setSync] = useState(null);

  const load = () => { api.facets().then(setFacets); api.assets(filter).then(setRows); };
  useEffect(() => {
    setRows(null);
    const t = setTimeout(load, filter.q ? 250 : 0);
    return () => clearTimeout(t);
  }, [filter]);
  // poll the sync state while a sync is running so the catalog fills in by itself
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await api.syncStatus();
        if (!alive) return;
        setSync((prev) => { if (prev?.running && !s.running) load(); return s; });
      } catch {}
    };
    tick();
    const t = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const toggle = (k, v) => setFilter((f) => ({ ...f, [k]: f[k] === v ? "" : v }));
  const active = filter.category || filter.integration || filter.q;

  return (
    <div className="catalog rise">
      <aside className="sidebar">
        <div className="facet"><input placeholder="🔍 Filter by name…" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} /></div>
        <div className="facet">
          <h4>Category</h4>
          {facets.categories.map(([c, n]) => (
            <button key={c} className={filter.category === c ? "active" : ""} onClick={() => toggle("category", c)}><span>{c}</span><span className="n">{n}</span></button>
          ))}
        </div>
        <div className="facet">
          <h4>Integration</h4>
          {facets.integrations.slice(0, 18).map(([c, n]) => (
            <button key={c} className={filter.integration === c ? "active" : ""} onClick={() => toggle("integration", c)}><span>{c}</span><span className="n">{n}</span></button>
          ))}
        </div>
        {active && <button className="ghost sm" onClick={() => setFilter({ category: "", integration: "", q: "" })}>✕ Clear filters</button>}
      </aside>
      <section>
        <div className="row between" style={{ marginBottom: 14 }}>
          <h2>{rows ? `${rows.length} workflow${rows.length === 1 ? "" : "s"}` : "Catalog"}</h2>
          <div className="row">
            {sync?.at && !sync.running && <span className="faint small">Drive sync {new Date(sync.at + "Z").toLocaleTimeString()}</span>}
            <Link to="/upload"><button className="sm">＋ Add workflow</button></Link>
          </div>
        </div>
        {sync?.running && <div className="alert info"><span className="spinner" />Syncing with Google Drive — the AI is reading and categorizing the workflows. This page updates by itself.</div>}
        {sync?.error && <div className="alert bad">Last Drive sync failed: {sync.error}</div>}
        {sync?.result?.errors?.length > 0 && !sync.running && (
          <div className="alert warn">{sync.result.errors.length} file(s) could not be synced: {sync.result.errors.map((e) => `${e.name} (${e.error.slice(0, 80)})`).join("; ")}</div>
        )}
        {!rows ? <Skeleton n={4} /> : rows.length === 0 ? (
          <div className="empty"><div className="big">📭</div>{active ? "Nothing matches these filters." : <>No workflows yet. <Link to="/upload">Add the first one</Link>.</>}</div>
        ) : (
          <div className="grid stagger">{rows.map((a) => <WorkflowCard key={a.id} a={a} />)}</div>
        )}
      </section>
    </div>
  );
}
