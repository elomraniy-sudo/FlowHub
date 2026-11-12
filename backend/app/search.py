"""Hybrid search: cheap lexical prefilter (BM25 over the AI-generated catalog text) -> LLM rerank
that also explains *why* and *what to change*. Keeps the LLM call small no matter how big the catalog grows."""
import re

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from .ai import rank_candidates
from .db import Asset

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _doc_text(a: Asset) -> str:
    parts = [a.name, a.category, a.summary, " ".join(a.tags or []), " ".join(a.use_cases or []),
             " ".join(a.integrations or []), a.trigger_type,
             " ".join(i.get("name", "") + " " + i.get("description", "") for i in (a.inputs or [])),
             " ".join(o.get("name", "") + " " + o.get("description", "") for o in (a.outputs or [])),
             " ".join(n.get("name", "") + " " + n.get("type", "") for n in (a.nodes or [])),
             a.sheet_description or "", (a.doc_text or "")[:4000]]
    return " ".join(p for p in parts if p)


def lexical_prefilter(db: Session, query: str, k: int = 15, kind: str | None = None) -> list[Asset]:
    q = db.query(Asset).filter(Asset.analysis_status == "done")
    if kind:
        q = q.filter(Asset.kind == kind)
    assets = q.all()
    if not assets:
        return []
    bm25 = BM25Okapi([_tokens(_doc_text(a)) for a in assets])
    scores = bm25.get_scores(_tokens(query))
    ranked = sorted(zip(scores, assets), key=lambda t: t[0], reverse=True)
    top = [a for s, a in ranked if s > 0][:k]
    # when the query shares no vocabulary with the catalog, still let the LLM look at the newest few
    return top or [a for _, a in ranked][: min(k, 8)]


def ai_search(db: Session, query: str, kind: str | None = None) -> dict:
    cands = lexical_prefilter(db, query, kind=kind)
    if not cands:
        return {"results": [], "no_match_advice": "The catalog is empty. Upload workflows first."}
    ranked = rank_candidates(query, [a.to_dict() for a in cands])
    by_id = {a.id: a for a in cands}
    results = []
    for r in ranked["results"]:
        a = by_id.get(r.get("id"))
        if a:
            results.append({**a.to_dict(), "score": r.get("score", 0), "reason": r.get("reason", ""),
                            "changes_needed": r.get("changes_needed", [])})
    results.sort(key=lambda x: -x["score"])
    return {"results": results, "no_match_advice": ranked.get("no_match_advice", "")}
