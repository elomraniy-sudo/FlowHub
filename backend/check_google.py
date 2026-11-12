"""Verify the Google service-account setup.  Run from backend/:  python check_google.py"""
import json
import sys

from app.config import settings
from app.integrations import gdrive

print(f"backend: {settings.GOOGLE_BACKEND} | key file: {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
try:
    key = json.load(open(settings.GOOGLE_SERVICE_ACCOUNT_FILE))
    print(f"service account: {key['client_email']} (project {key['project_id']})")
except Exception as e:
    sys.exit(f"cannot read key file: {e}")

ok = True
for label, fn in [
    ("AI Project folder (JSON files)", lambda: [f["name"] for f in gdrive.list_json_files()]),
    ("All N8N Flows sheet (rows)", lambda: [r["Flow Name"] for r in gdrive.read_registry_sheet()]),
    ("AI DOC folder (docs)", lambda: [d["name"] for d in gdrive.list_docs()]),
]:
    try:
        items = fn()
        print(f"OK   {label}: {len(items)} -> {items[:6]}")
    except Exception as e:
        ok = False
        msg = str(e)
        hint = ""
        if "accessNotConfigured" in msg or "has not been used" in msg or "is disabled" in msg:
            hint = "  -> enable the Google Drive API for this project in Google Cloud console"
        elif "404" in msg or "notFound" in msg or "File not found" in msg:
            hint = f"  -> share it with {key['client_email']} (a service account cannot see unshared files)"
        elif "403" in msg:
            hint = f"  -> share it with {key['client_email']}, and check the Drive API is enabled"
        print(f"FAIL {label}: {msg[:300]}{hint}")

print("\nAll good — start the backend and click 'Sync registry now'." if ok else "\nFix the items above, then run this again.")
