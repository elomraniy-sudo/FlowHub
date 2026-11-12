"""FlowHub API — internal automation catalog (n8n first; other asset kinds pluggable)."""
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import ai
from .config import settings
from .db import Asset, RunLog, get_db, init_db
from .ingest import ingest
from .integrations import gdrive, n8n_client
from .n8n_parser import PatchError, apply_customizations, apply_patch, ensure_executable, trigger_type
from .registry_sync import last_sync, start_background_sync, sync_registry
from .search import ai_search

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="FlowHub", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS.split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    init_db()
    start_background_sync()


# ---------- schemas ----------
class SearchBody(BaseModel):
    query: str
    kind: str | None = None


class AdaptBody(BaseModel):
    use_case: str


class CustomizeBody(BaseModel):
    values: dict[str, Any]
    new_name: str | None = None
    action: str = "download"          # download | n8n | drive | n8n+drive
    activate: bool = False
    user: str = ""
    ops: list[dict] = []              # node operations from the plan (AI-generated), applied to the copy
    new_fields: list[dict] = []       # fields declared for the new/changed nodes (from the plan)
    use_case: str = ""                # fallback: regenerate ops server-side when structural_changes given without ops
    structural_changes: list[str] = []
    apply_structural: bool = True


class RunBody(BaseModel):
    workflow: dict                     # the adapted workflow JSON (from /customize)
    payload: dict | None = None        # input items for the execution
    user: str = ""


class TriggerBody(BaseModel):
    n8n_workflow_id: str | None = None
    payload: dict | None = None
    test: bool = False


# ---------- status ----------
@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    return {
        "llm": {"mock": settings.LLM_MOCK, "model": settings.COMPASS_MODEL, "configured": bool(settings.COMPASS_API_KEY)},
        "n8n": {"configured": n8n_client.configured(), "base_url": settings.N8N_BASE_URL},
        "drive": {"configured": gdrive.configured(), "folder_id": settings.GOOGLE_DRIVE_FOLDER_ID,
                  "docs_folder_id": settings.GOOGLE_DOCS_FOLDER_ID, "sheet_id": settings.GOOGLE_SHEET_ID},
        "runner": {"configured": bool(settings.N8N_RUN_WEBHOOK_URL),
                   "test_url": "/webhook-test/" in settings.N8N_RUN_WEBHOOK_URL},
        "main_ai": {"webhook": bool(settings.MAIN_AI_WEBHOOK_URL),
                    "editor_url": n8n_client.editor_url(settings.MAIN_AI_WORKFLOW_ID) if settings.MAIN_AI_WORKFLOW_ID and settings.N8N_BASE_URL else ""},
        "sync": {"interval_minutes": settings.SYNC_INTERVAL_MINUTES, **{k: v for k, v in last_sync().items() if k != "result"}},
        "assets": db.query(Asset).count(),
        "in_registry": db.query(Asset).filter(Asset.in_registry == 1).count(),
        "categories": ai.CATEGORIES,
    }


# ---------- catalog ----------
@app.get("/api/assets")
def list_assets(q: str = "", category: str = "", integration: str = "", kind: str = "",
                db: Session = Depends(get_db)):
    query = db.query(Asset)
    if category: query = query.filter(Asset.category == category)
    if kind: query = query.filter(Asset.kind == kind)
    rows = query.order_by(Asset.created_at.desc()).all()
    if integration:
        rows = [a for a in rows if integration in (a.integrations or [])]
    if q:
        ql = q.lower()
        rows = [a for a in rows if ql in (a.name or "").lower() or ql in (a.summary or "").lower()
                or any(ql in t for t in (a.tags or []))]
    return [a.to_dict() for a in rows]


@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: int, raw: bool = False, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    return a.to_dict(include_raw=raw)


@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    db.delete(a); db.commit()
    return {"ok": True}


@app.post("/api/assets/{asset_id}/reanalyze")
def reanalyze(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    asset, st = ingest(db, a.raw, a.source, a.source_ref, a.owner, a.kind, reanalyze=True)
    return {"status": st, "asset": asset.to_dict()}


@app.get("/api/facets")
def facets(db: Session = Depends(get_db)):
    rows = db.query(Asset).all()
    cats: dict[str, int] = {}; ints: dict[str, int] = {}
    for a in rows:
        cats[a.category or "Other"] = cats.get(a.category or "Other", 0) + 1
        for i in a.integrations or []:
            ints[i] = ints.get(i, 0) + 1
    return {"categories": sorted(cats.items(), key=lambda t: -t[1]),
            "integrations": sorted(ints.items(), key=lambda t: -t[1])}


# ---------- ingestion ----------
@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), owner: str = Form(""), to_drive: bool = Form(False),
                 db: Session = Depends(get_db)):
    """Ingest + analyze. With to_drive=true the file is also stored in the 'AI Project' folder so the
    MAIN AI workflow documents it (sheet row + Google Doc) on its next run."""
    out = []
    for f in files:
        try:
            raw = (await f.read()).decode("utf-8")
            wf = json.loads(raw)
            drive_file = None
            if to_drive:
                drive_file = gdrive.upload_json(f.filename or wf.get("name", "workflow"), wf)
            asset, st = ingest(db, raw, "drive" if drive_file else "upload", drive_file["id"] if drive_file else (f.filename or ""), owner)
            out.append({"file": f.filename, "status": st, "asset": asset.to_dict(), "drive": drive_file})
        except Exception as e:
            out.append({"file": f.filename, "status": "error", "error": str(e)})
    return out


@app.post("/api/sync")
def sync(reanalyze: bool = False, db: Session = Depends(get_db)):
    """Pull the MAIN AI registry: sheet rows -> JSON in AI Project -> Google Doc text -> index."""
    try:
        return sync_registry(db, reanalyze=reanalyze)
    except gdrive.DriveError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Sync failed: {e}")


@app.get("/api/sync")
def sync_status():
    return last_sync()


@app.post("/api/main-ai/run")
def run_main_ai():
    """Fire the MAIN AI workflow through its webhook (import samples/'MAIN AI (webhook-enabled).json')."""
    if not settings.MAIN_AI_WEBHOOK_URL:
        raise HTTPException(400, "MAIN_AI_WEBHOOK_URL not configured. Import the webhook-enabled MAIN AI "
                                 "workflow from samples/ and set its production webhook URL.")
    import httpx
    try:
        r = httpx.post(settings.MAIN_AI_WEBHOOK_URL, json={"source": "flowhub"}, timeout=300)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"MAIN AI webhook failed: {e}")
    return {"status": r.status_code, "body": r.text[:1000]}


@app.post("/api/drive/scan")
def drive_scan(folder_id: str = "", db: Session = Depends(get_db)):
    """Index every JSON in a Drive folder (no sheet/doc enrichment; use /api/sync for the registry)."""
    try:
        files = gdrive.list_json_files(folder_id or None)
    except gdrive.DriveError as e:
        raise HTTPException(400, str(e))
    out = []
    for f in files:
        try:
            raw = gdrive.download_text(f["id"])
            owner = (f.get("owners") or [{}])[0].get("emailAddress", "")
            asset, st = ingest(db, raw, "drive", f["id"], owner)
            out.append({"file": f["name"], "status": st, "asset_id": asset.id})
        except Exception as e:
            out.append({"file": f["name"], "status": "error", "error": str(e)})
    return out


# ---------- AI search ----------
@app.post("/api/search")
def search(body: SearchBody, db: Session = Depends(get_db)):
    if not body.query.strip():
        raise HTTPException(400, "Empty query")
    try:
        return ai_search(db, body.query, body.kind)
    except Exception as e:
        raise HTTPException(502, f"Search failed: {e}")


# ---------- adaptation ----------
@app.post("/api/assets/{asset_id}/adapt")
def adapt(asset_id: int, body: AdaptBody, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    try:
        plan = ai.adaptation_plan(a.to_dict(), body.use_case)
    except Exception as e:
        raise HTTPException(502, f"LLM failed: {e}")
    by_key = {c["key"]: c for c in a.customizable or []}
    plan["fields"] = [{**by_key[f["key"]], **f} for f in plan["fields"]]
    # fields the LLM did not mention are still offered as optional
    mentioned = {f["key"] for f in plan["fields"]}
    plan["other_fields"] = [c for c in a.customizable or [] if c["key"] not in mentioned]

    # structural changes: have the AI write the node operations NOW, so every value the new nodes need
    # shows up in the same form (no "edit the JSON by hand" afterwards)
    plan["ops"], plan["new_fields"], plan["node_changes"], plan["notes"] = [], [], [], []
    if plan["structural_changes"]:
        try:
            patch = ai.structural_patch(json.loads(a.raw), body.use_case, plan["structural_changes"])
            trial = json.loads(a.raw)
            plan["node_changes"] = apply_patch(trial, patch["ops"])
            nodes_after = {n["name"] for n in trial["nodes"]}
            existing_keys = {f["key"] for f in plan["fields"]}
            plan["new_fields"] = [f for f in patch["fields"] if f["node"] in nodes_after and f["key"] not in existing_keys]
            plan["ops"] = patch["ops"]; plan["notes"] = patch.get("notes", [])
            # fields of nodes the AI removed/replaced no longer need the user's input
            plan["removed_fields"] = [f["label"] for f in plan["fields"] if f.get("node") not in nodes_after]
            plan["fields"] = [f for f in plan["fields"] if f.get("node") in nodes_after]
        except PatchError as e:
            plan["patch_error"] = f"The AI's node changes were rejected ({e}). You can still adapt the fields below."
        except Exception as e:
            plan["patch_error"] = f"Could not generate node changes: {e}"
    return plan


@app.post("/api/assets/{asset_id}/customize")
def customize(asset_id: int, body: CustomizeBody, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    # Always a COPY of the original (the catalog entry is never modified)
    wf = json.loads(a.raw)
    result: dict[str, Any] = {"node_changes": [], "notes": []}
    ops, new_fields = (body.ops, body.new_fields) if body.apply_structural else ([], [])

    # 1. node changes (ops generated at plan time; regenerate only if the client sent none)
    if body.apply_structural and not ops and body.structural_changes:
        try:
            patch = ai.structural_patch(wf, body.use_case, body.structural_changes)
            ops, new_fields, result["notes"] = patch["ops"], patch["fields"], patch.get("notes", [])
        except Exception as e:
            result["patch_error"] = f"Could not generate node changes: {e}"
    if ops:
        try:
            trial = json.loads(json.dumps(wf))
            result["node_changes"] = apply_patch(trial, ops)
            wf = trial
        except PatchError as e:
            result["patch_error"] = f"AI-generated node changes were rejected ({e}); workflow left unchanged for these."
            new_fields = []

    # 2. the user's values: original customizable fields + fields of the new nodes, in one pass
    spec = (a.customizable or []) + [f for f in new_fields if f.get("node") and f.get("path")]
    wf = apply_customizations(wf, body.values, spec, body.new_name)
    result["workflow"] = wf
    result["unfilled"] = [f["label"] for f in new_fields if f.get("kind") != "credential"
                          and body.values.get(f["key"]) in (None, "")]
    result["trigger_type"] = trigger_type(wf["nodes"])
    result["runnable"] = bool(settings.N8N_RUN_WEBHOOK_URL)

    if "n8n" in body.action:
        try:
            created = n8n_client.create_workflow(wf)
            if body.activate:
                n8n_client.activate_workflow(created["id"])
            result["n8n"] = {"id": created["id"], "editor_url": created["editor_url"], "active": body.activate}
            db.add(RunLog(asset_id=a.id, action="deploy", user=body.user, detail=result["n8n"]))
        except n8n_client.N8nError as e:
            result["n8n_error"] = str(e)
    if "drive" in body.action:
        try:
            f = gdrive.upload_json(wf["name"], wf)
            result["drive"] = f
            db.add(RunLog(asset_id=a.id, action="drive_upload", user=body.user, detail=f))
        except gdrive.DriveError as e:
            result["drive_error"] = str(e)
    db.commit()
    return result


@app.post("/api/assets/{asset_id}/run")
def run_in_n8n(asset_id: int, body: RunBody, db: Session = Depends(get_db)):
    """Send the adapted workflow to the 'FlowHub Runner' webhook in n8n, which creates it there and
    executes it (manual / execute-trigger workflows) or activates it (webhook / schedule / app-event).
    The user never has to open n8n."""
    if not settings.N8N_RUN_WEBHOOK_URL:
        raise HTTPException(400, "N8N_RUN_WEBHOOK_URL not configured (import samples/'FlowHub Runner.json' in n8n)")
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    wf = json.loads(json.dumps(body.workflow))
    ttype = trigger_type(wf["nodes"])
    ensure_executable(wf)
    mode = "activate" if ttype in ("webhook", "schedule", "app-event") else "execute"
    payload = {"source": "flowhub", "mode": mode, "name": wf.get("name", a.name), "user": body.user,
               "input": body.payload or {}, "workflow": {"name": wf.get("name", a.name), "nodes": wf["nodes"],
                                                          "connections": wf.get("connections", {}), "settings": wf.get("settings") or {}}}
    import httpx
    try:
        r = httpx.post(settings.N8N_RUN_WEBHOOK_URL, json=payload, timeout=settings.N8N_RUN_TIMEOUT)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"n8n webhook unreachable: {e}")
    try:
        out = r.json()
    except ValueError:
        out = {"raw": r.text[:2000]}
    if isinstance(out, list):
        out = out[0] if out else {}
    res = {"status": r.status_code, "mode": mode, "trigger_type": ttype, "n8n": out}
    if isinstance(out, dict) and out.get("workflowId") and settings.N8N_BASE_URL:
        res["editor_url"] = n8n_client.editor_url(out["workflowId"])
    if r.status_code >= 400:
        res["error"] = f"n8n answered HTTP {r.status_code}. If you are using a /webhook-test/ URL, the Runner must be in 'Listen for test event'; activate it and use the /webhook/ URL instead."
    db.add(RunLog(asset_id=a.id, action="run", user=body.user, detail={k: v for k, v in res.items() if k != "n8n"} | {"workflowId": (out or {}).get("workflowId") if isinstance(out, dict) else None}))
    db.commit()
    return res


@app.post("/api/assets/{asset_id}/trigger")
def trigger(asset_id: int, body: TriggerBody, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Not found")
    try:
        wf = n8n_client.get_workflow(body.n8n_workflow_id) if body.n8n_workflow_id else json.loads(a.raw)
        res = n8n_client.trigger_webhook(wf, body.payload, body.test)
    except n8n_client.N8nError as e:
        raise HTTPException(400, str(e))
    db.add(RunLog(asset_id=a.id, action="trigger", detail={"status": res["status"], "url": res["url"]}))
    db.commit()
    return res


@app.get("/api/assets/{asset_id}/runs")
def runs(asset_id: int, db: Session = Depends(get_db)):
    rows = db.query(RunLog).filter(RunLog.asset_id == asset_id).order_by(RunLog.created_at.desc()).all()
    return [{"action": r.action, "user": r.user, "detail": r.detail, "at": r.created_at.isoformat()} for r in rows]


# ---------- serve built frontend (optional, after `npm run build`) ----------
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="static")

    @app.get("/{path:path}")
    def spa(path: str):
        file = DIST / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
