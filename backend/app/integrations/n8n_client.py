"""n8n public REST API (Settings > n8n API > create key). Base: {N8N_BASE_URL}/api/v1"""
import httpx

from ..config import settings


class N8nError(RuntimeError):
    pass


def _check():
    if not settings.N8N_BASE_URL or not settings.N8N_API_KEY:
        raise N8nError("N8N_BASE_URL / N8N_API_KEY not configured")


def _client() -> httpx.Client:
    _check()
    return httpx.Client(base_url=settings.N8N_BASE_URL.rstrip("/") + "/api/v1",
                        headers={"X-N8N-API-KEY": settings.N8N_API_KEY}, timeout=60)


def configured() -> bool:
    return bool(settings.N8N_BASE_URL and settings.N8N_API_KEY)


def editor_url(workflow_id: str) -> str:
    return f"{settings.N8N_BASE_URL.rstrip('/')}/workflow/{workflow_id}"


def create_workflow(wf: dict) -> dict:
    """Creates a new (inactive) workflow. n8n's API only accepts a whitelisted set of fields."""
    body = {"name": wf.get("name", "Imported from FlowHub"), "nodes": wf["nodes"],
            "connections": wf.get("connections", {}), "settings": wf.get("settings") or {}}
    if wf.get("staticData"):
        body["staticData"] = wf["staticData"]
    with _client() as c:
        r = c.post("/workflows", json=body)
        if r.status_code >= 400:
            raise N8nError(f"n8n create failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
    data["editor_url"] = editor_url(data["id"])
    return data


def activate_workflow(workflow_id: str, active: bool = True) -> dict:
    with _client() as c:
        r = c.post(f"/workflows/{workflow_id}/{'activate' if active else 'deactivate'}")
        if r.status_code >= 400:
            raise N8nError(f"n8n activate failed ({r.status_code}): {r.text[:300]}")
        return r.json()


def list_workflows() -> list[dict]:
    with _client() as c:
        r = c.get("/workflows", params={"limit": 250})
        r.raise_for_status()
        return r.json().get("data", [])


def get_workflow(workflow_id: str) -> dict:
    with _client() as c:
        r = c.get(f"/workflows/{workflow_id}")
        r.raise_for_status()
        return r.json()


def trigger_webhook(wf: dict, payload: dict | None = None, test: bool = False) -> dict:
    """The public API has no 'execute' endpoint; webhook-triggered workflows are run by calling
    their webhook URL. Returns the HTTP response of the webhook."""
    hook = next((n for n in wf["nodes"] if n.get("type", "").endswith(".webhook")), None)
    if not hook:
        raise N8nError("Workflow has no Webhook trigger; run it from the n8n editor instead")
    path = hook.get("parameters", {}).get("path") or hook.get("webhookId")
    method = (hook.get("parameters", {}).get("httpMethod") or "POST").upper()
    url = f"{settings.N8N_BASE_URL.rstrip('/')}/{'webhook-test' if test else 'webhook'}/{path}"
    r = httpx.request(method, url, json=payload or {}, timeout=120)
    try:
        body = r.json()
    except ValueError:
        body = r.text[:2000]
    return {"status": r.status_code, "url": url, "body": body}
