"""Registry sync with Google APIs stubbed out (mock LLM)."""
import os
from pathlib import Path

os.environ["LLM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_sync.db"

import pytest
from fastapi.testclient import TestClient

from app import registry_sync
from app.db import Base, engine
from app.integrations import gdrive
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
DOC = "sheets_to_slack_report\n\nOVERVIEW\n\nPosts yesterday's orders to Slack.\n\nVALUES TO CHANGE BEFORE USING\n\n- Post to Slack | channelId | #sales-daily"


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    files = {"f1": ("sheets_to_slack_report.json", SAMPLES / "sheets_to_slack_report.json"),
             "f2": ("jira_ticket_ai_triage.json", SAMPLES / "jira_ticket_ai_triage.json")}
    monkeypatch.setattr(gdrive, "read_registry_sheet", lambda sheet_id=None: [
        {"Flow Name": "sheets_to_slack_report", "Flow ID": "abc123", "Small Description": "Daily sales to Slack",
         "Doc Link": "https://docs.google.com/document/d/DOC1/edit"},
        {"Flow Name": "ghost_flow", "Flow ID": "zzz", "Small Description": "no json", "Doc Link": ""},
    ])
    monkeypatch.setattr(gdrive, "list_json_files", lambda folder_id=None: [
        {"id": k, "name": v[0], "owners": [{"emailAddress": "amala@garena.com"}]} for k, v in files.items()])
    monkeypatch.setattr(gdrive, "download_text", lambda fid: files[fid][1].read_text())
    monkeypatch.setattr(gdrive, "read_doc_text", lambda link: DOC if "DOC1" in link else "")
    with TestClient(app) as c:
        yield c


def test_sync_registry(client):
    r = client.post("/api/sync").json()
    assert r["rows"] == 2 and r["files"] == 2
    assert [s["name"] for s in r["synced"]] == ["sheets_to_slack_report"]
    assert r["missing_json"] == ["ghost_flow"]
    assert [u["file"] for u in r["undocumented"]] == ["jira_ticket_ai_triage.json"]

    a = client.get(f"/api/assets/{r['synced'][0]['asset_id']}?raw=true").json()
    assert a["in_registry"] is True and a["n8n_workflow_id"] == "abc123"
    assert a["doc_link"].endswith("DOC1/edit") and "OVERVIEW" in a["doc_text"] and a["has_doc"]
    assert a["owner"] == "amala@garena.com"
    u = client.get(f"/api/assets/{r['undocumented'][0]['asset_id']}").json()
    assert u["in_registry"] is False

    # doc text is searchable
    s = client.post("/api/search", json={"query": "yesterday's orders slack"}).json()
    assert s["results"][0]["name"].startswith("Daily Sales")

    # second sync is cheap: nothing re-analyzed
    r2 = client.post("/api/sync").json()
    assert all(s["status"] == "unchanged" for s in r2["synced"])
    assert client.get("/api/status").json()["in_registry"] == 1
