"""Structural patches on the adapted copy + 'run in n8n' through a fake Runner webhook (mock LLM)."""
import json
import os
from pathlib import Path

os.environ["LLM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_patch.db"

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, engine
from app.main import app
from app.n8n_parser import PatchError, apply_patch, ensure_executable

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
received: list[dict] = []


def fake_runner(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content); received.append(body)
    if body["mode"] == "execute":
        return httpx.Response(200, json={"ok": True, "action": "executed", "workflowId": "W1", "workflowName": body["name"], "output": [{"x": 1}], "outputCount": 1})
    return httpx.Response(200, json={"ok": True, "action": "activated", "workflowId": "W2", "workflowName": body["name"], "active": True, "webhookUrl": "https://n8n/webhook/invoice-intake"})


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "N8N_RUN_WEBHOOK_URL", "https://n8n.test/webhook/flowhub-run")
    monkeypatch.setattr(settings, "N8N_BASE_URL", "https://n8n.test")
    transport = httpx.MockTransport(fake_runner)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    with TestClient(app) as c:
        files = [("files", (f.name, f.read_bytes(), "application/json")) for f in SAMPLES.glob("*.json") if not f.name.startswith(("MAIN", "FlowHub"))]
        c.post("/api/upload", files=files)
        yield c


def test_apply_patch_ops():
    wf = json.loads((SAMPLES / "sheets_to_slack_report.json").read_text())
    log = apply_patch(wf, [
        {"op": "add_node", "node": {"name": "Email", "type": "n8n-nodes-base.gmail", "parameters": {"sendTo": "a@b.c"}}, "connect_from": [{"from": "Post to Slack"}]},
        {"op": "update_node", "name": "Sum amounts", "parameters": {"jsCode": "return [];"}},
        {"op": "remove_node", "name": "Sum amounts", "bridge": True},
        {"op": "update_node", "name": "Every morning", "rename": "Daily 9am"},
    ])
    names = [n["name"] for n in wf["nodes"]]
    assert "Email" in names and "Sum amounts" not in names and "Daily 9am" in names
    assert {c["node"] for c in wf["connections"]["Read orders sheet"]["main"][0]} == {"Post to Slack"}   # bridged
    assert wf["connections"]["Post to Slack"]["main"][0][0]["node"] == "Email"
    assert wf["connections"]["Daily 9am"]["main"][0][0]["node"] == "Read orders sheet"
    assert len(log) == 4
    with pytest.raises(PatchError):
        apply_patch(wf, [{"op": "add_node", "node": {"name": "X", "type": "evil.node"}}])
    with pytest.raises(PatchError):
        apply_patch(wf, [{"op": "connect", "from": "Email", "to": "Nope"}])


def test_ensure_executable():
    wf = {"nodes": [{"name": "M", "type": "n8n-nodes-base.manualTrigger", "position": [0, 0]}, {"name": "B", "type": "n8n-nodes-base.set"}],
          "connections": {"M": {"main": [[{"node": "B", "type": "main", "index": 0}]]}}}
    assert ensure_executable(wf) is True and ensure_executable(wf) is False
    assert wf["connections"]["Run from FlowHub"]["main"][0][0]["node"] == "B"


def test_plan_builds_nodes_and_exposes_their_fields(client):
    a = next(x for x in client.get("/api/assets").json() if "Daily Sales" in x["name"])
    original = client.get(f"/api/assets/{a['id']}?raw=true").json()["raw"]
    plan = client.post(f"/api/assets/{a['id']}/adapt", json={"use_case": "also email the team the report"}).json()
    assert plan["structural_changes"] and plan["ops"]
    assert plan["node_changes"] == ["Added node 'Notify by email' (n8n-nodes-base.gmail)"]
    assert [f["key"] for f in plan["new_fields"]] == ["recipient_email", "gmail_credential"]
    assert all(f["new_node"] for f in plan["new_fields"])

    # generate: ops applied + the new node's placeholder replaced by the user's value, in one go
    r = client.post(f"/api/assets/{a['id']}/customize", json={
        "values": {"recipient_email": "sales@garena.com", "gmail_credential": {"name": "My Gmail", "id": "5"}},
        "new_name": "Sales + email", "ops": plan["ops"], "new_fields": plan["new_fields"], "apply_structural": True}).json()
    assert r["node_changes"] == plan["node_changes"] and r["runnable"] is True and r["unfilled"] == []
    gmail = next(n for n in r["workflow"]["nodes"] if n["name"] == "Notify by email")
    assert gmail["parameters"]["sendTo"] == "sales@garena.com"
    assert gmail["credentials"]["gmailOAuth2"] == {"id": "5", "name": "My Gmail"}
    # left empty -> reported, placeholder stays visible
    r2 = client.post(f"/api/assets/{a['id']}/customize", json={"values": {}, "ops": plan["ops"], "new_fields": plan["new_fields"]}).json()
    assert r2["unfilled"] == ["Recipient email"]
    assert next(n for n in r2["workflow"]["nodes"] if n["name"] == "Notify by email")["parameters"]["sendTo"] == "<<RECIPIENT_EMAIL>>"
    # the catalog copy is untouched
    again = client.get(f"/api/assets/{a['id']}?raw=true").json()["raw"]
    assert again == original and not any(n["name"] == "Notify by email" for n in again["nodes"])
    # opt-out leaves the copy structurally identical
    r3 = client.post(f"/api/assets/{a['id']}/customize", json={"values": {}, "ops": plan["ops"], "new_fields": plan["new_fields"], "apply_structural": False}).json()
    assert r3["node_changes"] == [] and len(r3["workflow"]["nodes"]) == len(original["nodes"])


def test_run_in_n8n(client):
    assets = client.get("/api/assets").json()
    sales = next(x for x in assets if "Daily Sales" in x["name"])       # schedule -> activate
    invoice = next(x for x in assets if "Invoice" in x["name"])         # webhook -> activate
    wf = client.post(f"/api/assets/{sales['id']}/customize", json={"values": {}}).json()["workflow"]
    r = client.post(f"/api/assets/{sales['id']}/run", json={"workflow": wf}).json()
    assert r["mode"] == "activate" and r["n8n"]["workflowId"] == "W2" and r["editor_url"].endswith("/workflow/W2")
    assert received[-1]["workflow"]["nodes"] and "id" not in received[-1]["workflow"]
    # manual-trigger workflow -> execute, with the execute-trigger injected
    manual = {"name": "M", "nodes": [{"name": "Start", "type": "n8n-nodes-base.manualTrigger", "position": [0, 0], "parameters": {}},
                                     {"name": "Set", "type": "n8n-nodes-base.set", "parameters": {}}],
              "connections": {"Start": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}}}
    r = client.post(f"/api/assets/{invoice['id']}/run", json={"workflow": manual}).json()
    assert r["mode"] == "execute" and r["n8n"]["outputCount"] == 1
    assert any(n["type"] == "n8n-nodes-base.executeWorkflowTrigger" for n in received[-1]["workflow"]["nodes"])
    runs = client.get(f"/api/assets/{sales['id']}/runs").json()
    assert runs[0]["action"] == "run"
