# FlowHub — internal automation catalog & reuse engine

> "Has someone already built this?" — one search box over every n8n workflow in the company,
> with an AI that explains what each one does and exactly what you'd change (credentials, sources,
> inputs, outputs) to reuse it for your case. Then it generates the adapted workflow, imports it
> into n8n and/or saves it to Google Drive.

## What it does

| Area | How |
|---|---|
| **Centralize** | Drop n8n workflow exports (JSON) on the Upload page, or scan a shared Google Drive folder. Duplicates are detected by content hash. |
| **Understand** | The LLM (Compass) reads each workflow and writes a summary, category, tags, use cases, inputs/outputs, and a list of *customizable points* (every credential + every source/destination/parameter a new user must change). |
| **Search** | Natural-language query → BM25 prefilter over the AI catalog text → LLM rerank that returns a match score, *why it matches* and *what you'd change*. If nothing fits, it says what would need to be built. |
| **Adapt** | Describe your use case → the AI returns fit (good/partial/poor), ordered steps, which fields are required, suggested values, and any structural edits that can't be solved by filling fields. A form is generated automatically. |
| **Generate & run** | Fills your values into a copy of the workflow (n8n resource-locator objects preserved, unfilled credentials stripped so n8n prompts for yours), then: download JSON, create it in n8n via the public API (optionally activate), save to Drive, deep-link to the n8n editor, call its webhook to run it. |
| **Scale later** | One `assets` table with a `kind` column and an `ANALYZERS` registry (`backend/app/ingest.py`). Adding scripts / web apps = add a parser + prompt for that kind. |

## How it fits with the MAIN AI n8n workflow

```
 colleague exports flow ──► Drive "AI Project" (JSON) ◄── FlowHub upload (box "also store in Drive")
                                   │
                        MAIN AI (n8n, manual/webhook trigger)
                        diff folder vs sheet by Flow Name → Compass → doc + row
                                   │                       │
                          Drive "AI DOC" (Google Doc)   Sheet "All N8N Flows"
                                   │   Flow Name · Flow ID · Small Description · Doc Link
                                   ▼                       ▼
                        FlowHub  POST /api/sync  (button "Sync registry now", or SYNC_INTERVAL_MINUTES)
                          reads sheet → downloads <Flow Name>.json → exports doc text
                          → structured analysis (category, tags, inputs/outputs, customizable fields)
                          → SQLite index  →  search · adapt · generate · deploy
```

Ownership is deliberately one-directional: **MAIN AI is the only writer of the sheet and the AI DOC folder;
FlowHub only reads them** and writes JSON files into AI Project. That means nothing can get out of sync in two
places, and the sheet/docs stay usable by people who never open FlowHub.

- Workflows in the sheet show an **"in registry"** badge, the Google Doc link, a **Documentation** tab with the
  doc text, and "Open original in n8n" (from Flow ID). JSON files in the folder that MAIN AI has not processed
  yet are indexed too and flagged **"awaiting MAIN AI doc"**.
- The doc text written by MAIN AI is fed to the search index and to the analyzer as context (its
  "VALUES TO CHANGE BEFORE USING" section makes the customizable-fields list more accurate).
- **Run MAIN AI** button: MAIN AI only has a manual trigger, which n8n's API cannot fire. Import
  `samples/MAIN AI (webhook-enabled).json` (same workflow + a Webhook trigger on path `flowhub-main-ai`),
  activate it, and put its production webhook URL in `MAIN_AI_WEBHOOK_URL`.

### Google access for the app (service account, default)
1. Google Cloud → create a project (or reuse one), enable the **Google Drive API**, create a **service
   account**, download its JSON key and save it as `backend/service-account.json`.
2. Share **AI Project**, **AI DOC** and the **All N8N Flows** sheet with the service account's
   `client_email` (Viewer is enough for sync; Editor on AI Project for uploads).
3. `backend/.env`: `GOOGLE_BACKEND=service_account`, `GOOGLE_SERVICE_ACCOUNT_FILE=./service-account.json`.
4. Check it: `cd backend && python check_google.py` — prints OK/FAIL per folder and sheet with the fix.

Alternative with no Google Cloud setup: `GOOGLE_BACKEND=n8n` + `N8N_BRIDGE_URL` routes every Google call
through `samples/FlowHub Bridge.json` (an n8n workflow using n8n's own Google OAuth credentials). Both
backends live in `backend/app/integrations/gdrive.py`.

## Adapting a workflow: what actually happens
- **The original is never modified.** Adapt works on a copy: `id`/`versionId` are stripped, it gets a new
  name, your values are written into the copy's parameters, credentials you did not fill are removed so n8n
  asks you for yours. The catalog entry keeps the original JSON.
- **Field changes** (sources, destinations, credentials) come from the adaptation plan; only fields that must
  change for *your* use case are shown.
- **Node changes** (new node, different trigger, replaced output…) are listed by the plan as "structural
  changes". When you generate, the AI writes them as node operations — `add_node`, `remove_node`,
  `update_node` (parameters / replace / rename), `connect`, `disconnect` — and the backend applies them to the
  copy with validation (real node types only, no dangling connections; a bad patch is rejected and reported
  instead of producing a broken workflow). The result lists exactly what was added/removed/rewired, plus any
  step left for you (typically: pick a credential on a new node). Untick the box in the wizard to skip this.

## Running the adapted workflow from the web app
n8n's public API can create/activate workflows but cannot *execute* one, so FlowHub sends the adapted JSON to
a tiny n8n workflow, **FlowHub Runner** (`samples/FlowHub Runner.json`), which does it from inside n8n:

```
FlowHub  ──POST {mode, workflow}──►  Webhook (Runner)
                                        │  "n8n" node: create workflow (needs an n8n API credential)
                                        ├─ mode=execute  → Execute Workflow (by id, wait) → reply with output
                                        └─ mode=activate → "n8n" node: activate → reply with webhook URL
```

- `mode=execute` for manual-trigger workflows (FlowHub injects an *Execute Workflow Trigger* wired like the
  manual trigger so the Runner can start it); `mode=activate` for webhook / schedule / app-event workflows,
  which then run on their own trigger.
- **n8n setup (once):** Settings → n8n API → create an API key; Credentials → new **n8n API** credential
  with that key and your base URL; Import `samples/FlowHub Runner.json`; open the two "n8n" nodes and pick
  that credential; **activate** the Runner; copy the webhook node's **Production URL** into
  `N8N_RUN_WEBHOOK_URL`. (The `/webhook-test/…` URL only answers while the editor is in "Listen for test
  event" — fine for a first try, not for daily use.)
- Each run creates a new workflow in n8n named after your copy (so you can find it later); the UI shows the
  execution output or the live webhook URL, and "open in n8n ↗" if `N8N_BASE_URL` is set.

Security note: Runner and Bridge webhooks are open to anyone who knows the URL. Keep n8n on the internal
network, or add "Header Auth" to the webhook nodes and send the matching header from the backend.

### Why SQLite (and not just the Google Sheet)?
The sheet is the human-readable *registry*: 4 columns, one row per flow, maintained by MAIN AI. FlowHub needs
a *machine index* on top of it: the raw workflow JSON (to generate adapted copies), nested structured data
(customizable fields with exact JSON paths, inputs/outputs, nodes, credentials), the doc text for full-text
search, the BM25 index, run/deploy logs, and sub-second filtering by category/integration. Keeping that in a
sheet would mean a Google API round-trip (and quota) on every page load, no proper querying, and JSON stuffed
into cells. SQLite is a single file, zero setup, rebuildable at any time from Drive + sheet (`Sync +
re-analyze all`), so it is a cache/index, not a second source of truth. When several people use it
concurrently from one server it is still fine; switch `DATABASE_URL` to Postgres if you ever outgrow it.

## Run it

```bash
# backend
cd backend
cp .env.example .env            # fill COMPASS_API_KEY (and n8n / Drive when ready)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (dev, separate terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173  (proxies /api -> :8000)
```

Production-style single process: `cd frontend && npm run build`, then the FastAPI app serves
`frontend/dist` itself at http://localhost:8000.

Windows: `start.ps1` does all of the above.

Try it: open **Add workflows** and drop the three files in `samples/`, then search
"save supplier invoices to drive and tell accounting".

## Configuration (`backend/.env`)

| Variable | Purpose |
|---|---|
| `COMPASS_API_KEY`, `COMPASS_BASE_URL`, `COMPASS_MODEL` | LLM gateway (OpenAI-compatible `/chat/completions`). Any OpenAI-compatible endpoint works. |
| `LLM_MOCK=true` | Deterministic fake LLM for offline demos/tests. |
| `N8N_BASE_URL`, `N8N_API_KEY` | n8n instance + public API key (n8n → Settings → n8n API). Enables "Create in n8n", activate, open-in-editor, webhook run. |
| `GOOGLE_BACKEND`, `N8N_BRIDGE_URL` | `n8n` (default) + the FlowHub Bridge webhook URL, or `service_account`. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Service-account JSON key (service_account mode only). |
| `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_DOCS_FOLDER_ID`, `GOOGLE_SHEET_ID` | AI Project folder, AI DOC folder, All N8N Flows sheet (defaults already point at yours). |
| `MAIN_AI_WEBHOOK_URL`, `MAIN_AI_WORKFLOW_ID`, `SYNC_INTERVAL_MINUTES` | Run-MAIN-AI button, open-in-n8n link, automatic background sync. |

## API

| Method & path | Purpose |
|---|---|
| `GET /api/status` | Which integrations are configured, catalog size |
| `POST /api/upload` (multipart `files[]`, `owner`) | Ingest + analyze workflow JSON |
| `POST /api/sync?reanalyze=` · `GET /api/sync` | Pull the MAIN AI registry (sheet + JSON + docs) / last result |
| `POST /api/main-ai/run` | Fire MAIN AI via its webhook |
| `POST /api/drive/scan?folder_id=` | Ingest every JSON in a Drive folder (no sheet/doc enrichment) |
| `GET /api/assets?q=&category=&integration=` · `GET /api/facets` | Browse catalog |
| `GET /api/assets/{id}?raw=true` · `DELETE` · `POST .../reanalyze` | Detail / manage |
| `POST /api/search` `{query}` | AI search with reasons + changes needed |
| `POST /api/assets/{id}/adapt` `{use_case}` | Adaptation plan + required fields |
| `POST /api/assets/{id}/customize` `{values, new_name, action: download/n8n/drive/n8n+drive, activate}` | Generate adapted workflow and deliver it |
| `POST /api/assets/{id}/run` `{workflow, payload?}` | Send the adapted JSON to the FlowHub Runner (create + execute/activate in n8n) |
| `POST /api/assets/{id}/trigger` `{n8n_workflow_id?, payload?, test?}` | Call an existing workflow's webhook |
| `GET /api/assets/{id}/runs` | Deploy / run history |

## Tests

```bash
cd backend && LLM_MOCK=true pytest -q      # 5 tests: parser, upload+dedupe, search, adapt+customize, path setter
```

## Known limits / next steps

- AI-written node changes use n8n's current parameter schemas as the model knows them; a node parameter name can lag a `typeVersion` bump. The patch engine guarantees a structurally valid workflow, not that every new node's parameters are perfect — open the result once in n8n if a new node looks empty.
- Credentials are never copied between users. The form takes a credential *name/id from your own n8n*; left blank, n8n asks you on first open.
- Search is BM25 + LLM rerank (no vector DB needed). Past ~1–2k workflows, add an embedding index in `search.py`'s `lexical_prefilter`.
- No auth yet — put it behind your SSO proxy; `owner`/`user` fields are free text for now.
- Roadmap: sync directly from the n8n API (`n8n_client.list_workflows` is already there), scripts & web apps as new `kind`s, usage analytics ("most reused workflows"), ratings/comments.
