"""Google Drive / Sheets / Docs access, two interchangeable backends (GOOGLE_BACKEND):

  n8n (default)     Every call is a POST to the "FlowHub Bridge" n8n workflow (samples/FlowHub Bridge.json),
                    which runs with n8n's existing Google OAuth credentials. Nothing to set up in Google Cloud.
                    Actions: registry | file | doc | upload.
  service_account   Direct Google APIs with a service-account key. Share the AI Project / AI DOC folders
                    and the All N8N Flows sheet with its client_email.
"""
import csv
import io
import json
import re

import httpx

from ..config import settings

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveError(RuntimeError):
    pass


def _use_bridge() -> bool:
    return settings.GOOGLE_BACKEND.lower() == "n8n"


def configured() -> bool:
    if _use_bridge():
        return bool(settings.N8N_BRIDGE_URL)
    return bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE and settings.GOOGLE_DRIVE_FOLDER_ID)


def _bridge(action: str, **payload) -> dict:
    if not settings.N8N_BRIDGE_URL:
        raise DriveError("N8N_BRIDGE_URL not configured: import samples/'FlowHub Bridge.json' into n8n, "
                         "activate it and set its production webhook URL")
    try:
        r = httpx.post(settings.N8N_BRIDGE_URL, json={"action": action, **payload}, timeout=180)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise DriveError(f"n8n bridge '{action}' failed: {e}") from e
    except ValueError as e:
        raise DriveError(f"n8n bridge '{action}' returned non-JSON: {r.text[:200]}") from e
    if isinstance(data, list):   # n8n may wrap a single item in a list
        data = data[0] if data else {}
    return data


_registry_cache: dict = {}


def _registry() -> dict:
    """One bridge call returns sheet rows + folder listing; cached briefly so sync makes a single call."""
    import time
    if _registry_cache.get("at", 0) > time.time() - 20:
        return _registry_cache["data"]
    data = _bridge("registry")
    _registry_cache.update(at=time.time(), data=data)
    return data


def _service():
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        raise DriveError("GOOGLE_SERVICE_ACCOUNT_FILE not configured")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        raise DriveError("google-api-python-client not installed") from e
    creds = service_account.Credentials.from_service_account_file(settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------- files in the AI Project folder ----------

def list_json_files(folder_id: str | None = None) -> list[dict]:
    if _use_bridge():
        return _registry().get("files", [])
    svc = _service()
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise DriveError("GOOGLE_DRIVE_FOLDER_ID not configured")
    files, page = [], None
    q = f"'{folder_id}' in parents and trashed=false and (mimeType='application/json' or name contains '.json')"
    while True:
        res = svc.files().list(q=q, fields="nextPageToken, files(id,name,modifiedTime,owners(emailAddress))",
                               pageToken=page, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files.extend(res.get("files", []))
        page = res.get("nextPageToken")
        if not page:
            return files


def download_text(file_id: str) -> str:
    if _use_bridge():
        content = _bridge("file", id=file_id).get("content")
        if content is None:
            raise DriveError(f"bridge returned no content for file {file_id}")
        return content if isinstance(content, str) else json.dumps(content)
    from googleapiclient.http import MediaIoBaseDownload
    svc = _service()
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id, supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8")


def upload_json(name: str, content: dict, folder_id: str | None = None) -> dict:
    """Upload into the AI Project folder -> MAIN AI documents it on its next run."""
    if _use_bridge():
        return _bridge("upload", name=name, content=content)
    from googleapiclient.http import MediaIoBaseUpload
    svc = _service()
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not name.endswith(".json"):
        name += ".json"
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(content, indent=2).encode()), mimetype="application/json")
    return svc.files().create(body={"name": name, "parents": [folder_id]}, media_body=media,
                              fields="id,name,webViewLink", supportsAllDrives=True).execute()


# ---------- registry written by the MAIN AI workflow ----------

def _export(file_id: str, mime: str) -> str:
    svc = _service()
    return svc.files().export(fileId=file_id, mimeType=mime).execute().decode("utf-8")


def read_registry_sheet(sheet_id: str | None = None) -> list[dict]:
    """Rows of 'All N8N Flows' (first tab) as dicts: Flow Name, Flow ID, Small Description, Doc Link."""
    if _use_bridge():
        rows = _registry().get("rows", [])
        return [{str(k).strip(): str(v or "").strip() for k, v in r.items()} for r in rows if (r.get("Flow Name") or "").strip()]
    sheet_id = sheet_id or settings.GOOGLE_SHEET_ID
    if not sheet_id:
        raise DriveError("GOOGLE_SHEET_ID not configured")
    rows = list(csv.DictReader(io.StringIO(_export(sheet_id, "text/csv"))))
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in rows if (r.get("Flow Name") or "").strip()]


DOC_ID_RE = re.compile(r"/document/d/([A-Za-z0-9_-]+)")


def doc_id_from_link(link: str) -> str | None:
    m = DOC_ID_RE.search(link or "")
    return m.group(1) if m else None


def read_doc_text(doc_link_or_id: str) -> str:
    doc_id = doc_id_from_link(doc_link_or_id) or doc_link_or_id
    if _use_bridge():
        return _bridge("doc", id=doc_id).get("text", "") or ""
    return _export(doc_id, "text/plain")


def list_docs(folder_id: str | None = None) -> list[dict]:
    if _use_bridge():
        raise DriveError("list_docs is not needed in n8n mode (docs are reached through the sheet's Doc Link)")
    svc = _service()
    folder_id = folder_id or settings.GOOGLE_DOCS_FOLDER_ID
    res = svc.files().list(q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.document'",
                           fields="files(id,name,webViewLink,modifiedTime)", pageSize=1000,
                           supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    return res.get("files", [])
