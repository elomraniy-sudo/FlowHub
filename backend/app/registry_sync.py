"""Sync FlowHub's index with the registry produced by the MAIN AI n8n workflow.

Ownership rules (keeps the two systems from fighting):
  - n8n JSON files live in the Drive "AI Project" folder. FlowHub uploads there; MAIN AI reads there.
  - MAIN AI is the ONLY writer of the sheet "All N8N Flows" and of the "AI DOC" folder.
  - FlowHub reads sheet + docs + JSON and builds the searchable, structured index (SQLite).

For every sheet row:  Flow Name -> "<Flow Name>.json" in AI Project -> ingest (structured analysis)
                      Flow ID / Small Description / Doc Link -> stored on the asset
                      Doc Link -> doc text exported and stored (search + adaptation context)
JSON files not yet in the sheet are ingested too and flagged "awaiting MAIN AI documentation".
"""
import logging
import threading
import time
from datetime import datetime

from sqlalchemy.orm import Session

from .config import settings
from .db import Asset, SessionLocal
from .ingest import ingest
from .integrations import gdrive

log = logging.getLogger("flowhub.sync")
_last: dict = {"at": None, "result": None, "running": False, "error": None}


def last_sync() -> dict:
    return _last


def sync_registry(db: Session, reanalyze: bool = False) -> dict:
    _last["running"] = True
    rows = gdrive.read_registry_sheet()
    files = gdrive.list_json_files()
    by_name = {f["name"].lower(): f for f in files}
    by_stem = {f["name"][:-5].lower() if f["name"].lower().endswith(".json") else f["name"].lower(): f for f in files}
    report = {"rows": len(rows), "files": len(files), "synced": [], "missing_json": [], "undocumented": [], "errors": []}
    seen_files: set[str] = set()

    for r in rows:
        name = r.get("Flow Name", "")
        f = by_stem.get(name.lower()) or by_name.get(name.lower())
        if not f:
            report["missing_json"].append(name)
            continue
        seen_files.add(f["id"])
        try:
            existing = db.query(Asset).filter(Asset.source_ref == f["id"]).first()
            # skip the expensive LLM step when nothing changed and we already have it
            if existing and existing.analysis_status == "done" and not reanalyze:
                asset, status = existing, "unchanged"
            else:
                raw = gdrive.download_text(f["id"])
                owner = (f.get("owners") or [{}])[0].get("emailAddress", "")
                # doc text first so the analyzer can use MAIN AI's documentation as context
                doc_text = _fetch_doc(r.get("Doc Link", ""), report, name)
                asset, status = ingest(db, raw, "drive", f["id"], owner, reanalyze=reanalyze, doc_text=doc_text)
                asset.doc_text = doc_text
            asset.n8n_workflow_id = r.get("Flow ID", "") or asset.n8n_workflow_id
            asset.sheet_description = r.get("Small Description", "")
            asset.doc_link = r.get("Doc Link", "")
            asset.in_registry = 1
            if asset.doc_link and not asset.doc_text:
                asset.doc_text = _fetch_doc(asset.doc_link, report, name)
            if not asset.name or asset.name == "Untitled workflow":
                asset.name = name
            db.add(asset); db.commit()
            report["synced"].append({"name": name, "status": status, "asset_id": asset.id})
        except Exception as e:
            log.exception("sync failed for %s", name)
            report["errors"].append({"name": name, "error": str(e)})

    # JSON files in the folder that MAIN AI has not documented yet
    for f in files:
        if f["id"] in seen_files:
            continue
        try:
            existing = db.query(Asset).filter(Asset.source_ref == f["id"]).first()
            if existing and existing.analysis_status == "done" and not reanalyze:
                asset, status = existing, "unchanged"
            else:
                raw = gdrive.download_text(f["id"])
                owner = (f.get("owners") or [{}])[0].get("emailAddress", "")
                asset, status = ingest(db, raw, "drive", f["id"], owner, reanalyze=reanalyze)
            asset.in_registry = 0
            db.add(asset); db.commit()
            report["undocumented"].append({"file": f["name"], "status": status, "asset_id": asset.id})
        except Exception as e:
            report["errors"].append({"name": f["name"], "error": str(e)})

    _last.update(at=datetime.utcnow().isoformat(), result=report, running=False, error=None)
    return report


def _fetch_doc(link: str, report: dict, name: str) -> str:
    if not link:
        return ""
    try:
        return gdrive.read_doc_text(link)
    except Exception as e:
        report["errors"].append({"name": name, "error": f"doc: {e}"})
        return ""


def _sync_once(reason: str) -> None:
    db = SessionLocal()
    try:
        r = sync_registry(db)
        log.info("registry sync (%s): %d rows, %d files, %d synced, %d undocumented, %d errors",
                 reason, r["rows"], r["files"], len(r["synced"]), len(r["undocumented"]), len(r["errors"]))
        for e in r["errors"]:
            log.warning("sync error for %s: %s", e["name"], e["error"])
    except Exception as e:
        _last.update(running=False, error=str(e))
        log.exception("registry sync failed (%s)", reason)
    finally:
        db.close()


def start_background_sync() -> None:
    """Sync once right after startup (so the catalog fills itself when Google is configured),
    then every SYNC_INTERVAL_MINUTES if > 0."""
    if not gdrive.configured():
        log.info("Google not configured - automatic registry sync disabled")
        return

    def loop():
        _sync_once("startup")
        while settings.SYNC_INTERVAL_MINUTES > 0:
            time.sleep(settings.SYNC_INTERVAL_MINUTES * 60)
            _sync_once("scheduled")

    threading.Thread(target=loop, daemon=True, name="flowhub-sync").start()
