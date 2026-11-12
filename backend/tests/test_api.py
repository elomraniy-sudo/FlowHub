"""End-to-end API tests using the mock LLM (no network). Run: LLM_MOCK=true pytest"""
import json
import os
from pathlib import Path

os.environ["LLM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_flowhub.db"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app
from app.n8n_parser import apply_customizations, parse_workflow

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def test_parser_extracts_structure():
    p = parse_workflow((SAMPLES / "sheets_to_slack_report.json").read_text())
    assert p["trigger_type"] == "schedule"
    assert set(p["integrations"]) == {"googleSheets", "slack"}
    assert {c["type"] for c in p["credentials_required"]} == {"googleSheetsOAuth2Api", "slackApi"}
    assert any(x["path"] == "channelId.value" and x["value"] == "#sales-daily" for x in p["params_index"])


def test_upload_and_catalog(client):
    files = [("files", (f.name, f.read_bytes(), "application/json")) for f in SAMPLES.glob("*.json")]
    r = client.post("/api/upload", files=files, data={"owner": "yasser"})
    assert r.status_code == 200
    assert {x["status"] for x in r.json()} == {"created"}
    # duplicate detection
    r2 = client.post("/api/upload", files=files[:1])
    assert r2.json()[0]["status"] == "duplicate"
    assert client.get("/api/status").json()["assets"] == len(files)
    assert len(client.get("/api/assets?integration=slack").json()) == 1


def test_search(client):
    r = client.post("/api/search", json={"query": "post a daily summary from a spreadsheet to slack"})
    assert r.status_code == 200
    res = r.json()["results"]
    assert res and res[0]["name"].startswith("Daily Sales Report")
    assert "reason" in res[0] and "changes_needed" in res[0]


def test_adapt_and_customize(client):
    a = next(x for x in client.get("/api/assets").json() if "Daily Sales" in x["name"])
    plan = client.post(f"/api/assets/{a['id']}/adapt", json={"use_case": "same but for the marketing team sheet"}).json()
    keys = {f["key"] for f in plan["fields"]}
    assert "cred_slackapi" in keys
    chan_key = next(f["key"] for f in plan["fields"] if f["path"] == "channelId.value")
    out = client.post(f"/api/assets/{a['id']}/customize", json={
        "values": {chan_key: "#marketing-daily", "cred_slackapi": {"id": "99", "name": "Marketing bot"}},
        "new_name": "Marketing daily report", "action": "download"}).json()
    wf = out["workflow"]
    slack = next(n for n in wf["nodes"] if n["name"] == "Post to Slack")
    assert slack["parameters"]["channelId"]["value"] == "#marketing-daily"
    assert slack["credentials"]["slackApi"] == {"id": "99", "name": "Marketing bot"}
    sheets = next(n for n in wf["nodes"] if n["name"] == "Read orders sheet")
    assert sheets.get("credentials") == {}  # unfilled credential stripped
    assert wf["name"] == "Marketing daily report"
    # n8n not configured -> graceful error, not crash
    out2 = client.post(f"/api/assets/{a['id']}/customize", json={"values": {}, "action": "n8n+drive"}).json()
    assert "n8n_error" in out2 and "drive_error" in out2


def test_apply_customizations_nested_path():
    wf = {"nodes": [{"name": "A", "type": "x", "parameters": {"list": [{"k": 1}]}}]}
    out = apply_customizations(wf, {"f": "v"}, [{"key": "f", "node": "A", "path": "list[0].k", "kind": "input"}])
    assert out["nodes"][0]["parameters"]["list"][0]["k"] == "v"
