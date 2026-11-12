"""Central configuration. Everything comes from environment variables / .env."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # --- LLM (OpenAI-compatible chat completions endpoint) ---
    COMPASS_API_KEY: str = ""
    COMPASS_BASE_URL: str = "https://compass.llm.shopee.io/compass-api/v1"
    COMPASS_MODEL: str = "compass-max"
    LLM_TIMEOUT: int = 120
    LLM_MOCK: bool = False  # True => deterministic fake answers (tests / offline demo)

    # --- Storage ---
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'flowhub.db'}"

    # --- n8n ---
    N8N_BASE_URL: str = ""      # e.g. https://n8n.company.com
    N8N_API_KEY: str = ""       # n8n public API key (Settings > n8n API)
    # Webhook of the "FlowHub Runner" workflow (samples/FlowHub Runner.json). FlowHub POSTs the adapted
    # workflow JSON there; the Runner creates it in n8n and executes/activates it, then replies.
    N8N_RUN_WEBHOOK_URL: str = ""
    N8N_RUN_TIMEOUT: int = 300

    # --- Google Drive / MAIN AI registry ---
    GOOGLE_BACKEND: str = "service_account"  # service_account = direct Google APIs with a key file
                                             # n8n = call the "FlowHub Bridge" n8n workflow instead
    N8N_BRIDGE_URL: str = ""           # production URL of the bridge webhook, e.g. https://n8n.x.com/webhook/flowhub-bridge
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""                            # path to service-account JSON (service_account mode)
    GOOGLE_DRIVE_FOLDER_ID: str = "1WzwOoFR_lBZqaST2ZN4F4f9ZwXZn6CdX"  # "AI Project": n8n JSON exports
    GOOGLE_DOCS_FOLDER_ID: str = "1mz3y3EkVInEnt0GOaggF6715qbVeKFhm"   # "AI DOC": docs written by MAIN AI
    GOOGLE_SHEET_ID: str = "1Cenq497IektpOrMDtyELOmE5cYsALmTMUo5j2m2EA44"  # "All N8N Flows" registry
    MAIN_AI_WEBHOOK_URL: str = ""      # webhook of the MAIN AI workflow (see samples/MAIN AI (webhook-enabled).json)
    MAIN_AI_WORKFLOW_ID: str = ""      # its id in n8n, for the "open MAIN AI" link
    SYNC_INTERVAL_MINUTES: int = 0     # >0 => sync the registry automatically in the background

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
