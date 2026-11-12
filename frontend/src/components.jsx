import { createContext, useCallback, useContext, useState } from "react";
import { Link } from "react-router-dom";

/* ---------- toasts ---------- */
const ToastCtx = createContext(() => {});
export function ToastProvider({ children }) {
  const [list, setList] = useState([]);
  const push = useCallback((msg, kind = "") => {
    const id = Date.now() + Math.random();
    setList((l) => [...l, { id, msg, kind }]);
    setTimeout(() => setList((l) => l.filter((t) => t.id !== id)), 3800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">{list.map((t) => <div key={t.id} className={"toast " + t.kind}>{t.kind === "ok" ? "✓" : t.kind === "bad" ? "✕" : "•"} {t.msg}</div>)}</div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---------- small bits ---------- */
export function Chips({ items, cls = "" }) {
  if (!items?.length) return null;
  return <div className="chips">{items.map((t) => <span key={t} className={"chip " + cls}>{t}</span>)}</div>;
}

export function Spinner({ text }) {
  return <div className="thinking rise"><span className="spinner" />{text}</div>;
}

export function Skeleton({ n = 3 }) {
  return (
    <div className="grid">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="card"><div className="skel" style={{ width: "60%", height: 18 }} />
          <div className="skel" style={{ width: "40%", marginTop: 10 }} /><div className="skel" style={{ marginTop: 16 }} /><div className="skel" style={{ width: "85%", marginTop: 8 }} /></div>
      ))}
    </div>
  );
}

export function ScoreRing({ value }) {
  const c = value >= 75 ? "var(--ok)" : value >= 50 ? "var(--warn)" : "var(--bad)";
  return <div className="ring" style={{ "--p": value, "--ring-c": c }} title={`${value}% match`}><span>{value}%</span></div>;
}

export const TRIGGER_ICON = { webhook: "⚡", schedule: "⏰", manual: "▶", "app-event": "🔔" };

/* ---------- workflow card ---------- */
export function WorkflowCard({ a, result }) {
  return (
    <div className={"card hover " + (result ? "result" : "")}>
      <div className="result-head">
        {result && <ScoreRing value={a.score} />}
        <div className="grow">
          <h3><Link to={`/workflow/${a.id}`}>{a.name}</Link></h3>
          <div className="meta">
            <span className="chip cat">{a.category}</span>
            <span>{TRIGGER_ICON[a.trigger_type] || "•"} {a.trigger_type}</span>
            {a.owner && <span>by {a.owner.split("@")[0]}</span>}
            {a.doc_link && <a href={a.doc_link} target="_blank" rel="noreferrer">📄 doc</a>}
          </div>
        </div>
      </div>
      <p className="summary">{a.summary}</p>
      {result ? (
        <>
          <div className="reason">{a.reason}</div>
          {a.changes_needed?.length > 0 && <ul className="changes">{a.changes_needed.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          <div className="row" style={{ marginTop: 14 }}>
            <Link to={`/workflow/${a.id}?adapt=1`}><button className="primary sm">✨ Adapt for my use case</button></Link>
            <Link to={`/workflow/${a.id}`}><button className="ghost sm">Details</button></Link>
          </div>
        </>
      ) : (
        <Chips items={a.integrations} />
      )}
    </div>
  );
}
