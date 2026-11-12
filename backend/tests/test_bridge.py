"""Sync + upload through the n8n bridge backend, against a fake bridge webhook (mock LLM)."""
import json
import os
from pathlib import Path

os.environ["LLM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_bridge.db"
os.environ["GOOGLE_BACKEND"] = "n8n"
os.environ["N8N_BRIDGE_URL"] = "https://n8n.test/webhook/flowhub-bridge"

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.integrations import gdrive
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
FILES = {"f1": "sheets_to_slack_report.json"}
uploaded: list[dict] = []


def fake_bridge(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    a = body["action"]
    if a == "registry":
        return httpx.Response(200, json={"rows": [{"Flow Name": "sheets_to_slack_report", "Flow ID": "n8n1",
                                                    "Small Description": "d", "Doc Link": "https://docs.google.com/document/d/D1/edit"}],
                                         "files": [{"id": k, "name": v, "owners": []} for k, v in FILES.items()]})
    if a == "file":
        return httpx.Response(200, json=[{"content": json.loads((SAMPLES / FILES[body["id"]]).read_text())}])
    if a == "doc":
        return httpx.Response(200, json={"text": f"DOC {body['id']}\n\nOVERVIEW\n\nsales to slack"})
    if a == "upload":
        uploaded.append(body)
        return httpx.Response(200, json={"id": "new1", "name": body["name"], "webViewLink": "https://drive/new1"})
    return httpx.Response(400, json={"error": "bad action"})


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    gdrive._registry_cache.clear()
    from app.config import settings
    monkeypatch.setattr(settings, "GOOGLE_BACKEND", "n8n")
    monkeypatch.setattr(settings, "N8N_BRIDGE_URL", "https://n8n.test/webhook/flowhub-bridge")
    transport = httpx.MockTransport(fake_bridge)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    with TestClient(app) as c:
        yield c


def test_sync_via_bridge(client):
    assert client.get("/api/status").json()["drive"]["configured"] is True
    r = client.post("/api/sync").json()
    assert [s["name"] for s in r["synced"]] == ["sheets_to_slack_report"] and not r["errors"]
    a = client.get(f"/api/assets/{r['synced'][0]['asset_id']}?raw=true").json()
    assert a["n8n_workflow_id"] == "n8n1" and "OVERVIEW" in a["doc_text"] and a["in_registry"]


def test_upload_to_drive_via_bridge(client):
    f = SAMPLES / "jira_ticket_ai_triage.json"
    r = client.post("/api/upload", files=[("files", (f.name, f.read_bytes(), "application/json"))],
                    data={"owner": "yasser", "to_drive": "true"}).json()[0]
    assert r["status"] == "created" and r["drive"]["id"] == "new1" and r["asset"]["source"] == "drive"
    assert uploaded[-1]["name"] == f.name and uploaded[-1]["content"]["name"].startswith("Jira")
