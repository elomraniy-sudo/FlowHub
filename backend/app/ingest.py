"""Ingestion pipeline: raw JSON -> deterministic parse -> LLM analysis -> catalog row.
`ANALYZERS` is the extension point for future asset kinds (scripts, web apps, ...)."""
import json
import logging

from sqlalchemy.orm import Session

from .ai import analyze_workflow
from .db import Asset
from .n8n_parser import parse_workflow

log = logging.getLogger("flowhub.ingest")


def _analyze_n8n(raw: str) -> tuple[dict, dict]:
    parsed = parse_workflow(raw)
    return parsed, analyze_workflow(parsed)


ANALYZERS = {"n8n_workflow": _analyze_n8n}


def ingest(db: Session, raw: str, source: str, source_ref: str, owner: str = "",
           kind: str = "n8n_workflow", reanalyze: bool = False, doc_text: str = "") -> tuple[Asset, str]:
    """Returns (asset, status) where status in created|updated|duplicate|failed.
    doc_text: optional documentation written by the MAIN AI workflow, given to the analyzer as context."""
    parsed = parse_workflow(raw)
    parsed["doc_text"] = doc_text
    existing = db.query(Asset).filter(Asset.content_hash == parsed["content_hash"]).first()
    if existing and existing.analysis_status == "done" and not reanalyze:
        return existing, "duplicate"

    asset = existing or Asset(kind=kind)
    asset.name = parsed["name"]; asset.owner = owner or asset.owner or ""
    asset.source = source; asset.source_ref = source_ref
    asset.content_hash = parsed["content_hash"]
    asset.raw = raw if isinstance(raw, str) else json.dumps(raw)
    asset.nodes = parsed["nodes"]; asset.integrations = parsed["integrations"]
    asset.trigger_type = parsed["trigger_type"]; asset.credentials_required = parsed["credentials_required"]
    if doc_text:
        asset.doc_text = doc_text

    try:
        enriched = analyze_workflow(parsed)
        asset.summary = enriched["summary"]; asset.category = enriched["category"]
        asset.tags = enriched["tags"]; asset.use_cases = enriched["use_cases"]
        asset.inputs = enriched["inputs"]; asset.outputs = enriched["outputs"]
        asset.customizable = enriched["customizable"]
        asset.analysis_status = "done"
        status = "updated" if existing else "created"
    except Exception as e:  # keep the row so it is visible + re-analyzable
        log.exception("analysis failed for %s", asset.name)
        asset.analysis_status = "failed"
        asset.summary = f"AI analysis failed: {e}"
        status = "failed"

    db.add(asset); db.commit(); db.refresh(asset)
    return asset, status
