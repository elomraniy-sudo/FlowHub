import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { ToastProvider } from "./components.jsx";
import Search from "./pages/Search.jsx";
import Catalog from "./pages/Catalog.jsx";
import Detail from "./pages/Detail.jsx";
import Upload from "./pages/Upload.jsx";

export default function App() {
  const [status, setStatus] = useState(null);
  const refresh = () => api.status().then(setStatus).catch(() => {});
  useEffect(() => { refresh(); }, []);
  const cls = ({ isActive }) => "link" + (isActive ? " active" : "");
  const Pill = ({ on, label, title }) => <span className="pill" title={title}><span className={"dot " + (on ? "on" : "")} />{label}</span>;
  return (
    <ToastProvider>
      <nav className="nav">
        <NavLink to="/" className="logo"><span className="logo-mark">⚡</span>FlowHub</NavLink>
        <NavLink to="/" end className={cls}>Search</NavLink>
        <NavLink to="/catalog" className={cls}>Catalog</NavLink>
        <NavLink to="/upload" className={cls}>Add workflows</NavLink>
        <span className="spacer" />
        {status && (
          <div className="status-pills">
            <Pill on={status.llm.configured || status.llm.mock} label={status.llm.mock ? "AI (mock)" : "AI"} title={status.llm.model} />
            <Pill on={status.n8n.configured} label="n8n" title={status.n8n.configured ? status.n8n.base_url : "Set N8N_BASE_URL / N8N_API_KEY"} />
            <Pill on={status.drive.configured} label="Drive" title={status.drive.configured ? "via n8n bridge" : "Set N8N_BRIDGE_URL"} />
            <span className="pill">{status.assets} workflows</span>
          </div>
        )}
      </nav>
      <main className="page">
        <Routes>
          <Route path="/" element={<Search />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/workflow/:id" element={<Detail status={status} />} />
          <Route path="/upload" element={<Upload status={status} refresh={refresh} />} />
        </Routes>
      </main>
    </ToastProvider>
  );
}
