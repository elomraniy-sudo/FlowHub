"""LLM-powered understanding: analyze, rank for search, explain adaptation."""
import json

from .llm import chat_json
from .n8n_parser import compact_for_llm

CATEGORIES = [
    "Data Sync & ETL", "Reporting & Dashboards", "Notifications & Alerts", "Approvals & HR",
    "Finance & Invoicing", "Sales & CRM", "Marketing & Social", "Customer Support",
    "DevOps & Monitoring", "Content & Documents", "AI & LLM Agents", "Scraping & Research",
    "Internal Tools & Utilities", "Other",
]

ANALYZE_SYSTEM = f"""You are an expert in n8n automation. You read a workflow definition and produce a precise,
structured catalog entry so colleagues can discover and reuse it. Respond with STRICT JSON only, no prose.

JSON schema:
{{
  "summary": "2-4 sentences: what the workflow does end to end, in business language",
  "category": one of {CATEGORIES},
  "tags": ["5-10 short lowercase keywords: tools, data objects, verbs"],
  "use_cases": ["3-5 concrete situations where someone would reuse this"],
  "inputs": [{{"name": "...", "node": "node name", "description": "where data comes from / what triggers it"}}],
  "outputs": [{{"name": "...", "node": "node name", "description": "where results go"}}],
  (inputs = ONLY the trigger and external data SOURCES (sheets, DBs, APIs read from); outputs = ONLY external
   DESTINATIONS (messages sent, files written, records updated). Never list stickyNote, code, set, if or other
   internal processing nodes as inputs or outputs.)
  "customizable": [
    {{"key": "snake_case_unique", "label": "Human label", "node": "exact node name",
      "path": "exact parameter path from the list OR credential type for kind=credential",
      "kind": "credential|input|output|parameter", "description": "what to put here and why",
      "example": "current value or example"}}
  ]
}}
Rules for "customizable": include EVERY credential listed in the Nodes table as its own item
(kind=credential, path = the credential type e.g. slackApi, label like "Slack credential (Post to Slack)"),
plus every parameter a new user would have to change to reuse the workflow for their own case:
source identifiers (sheet ids, database/table names, folder ids, URLs, channel names, email addresses,
file paths, webhook paths, queries, prompts). Do NOT include cosmetic/positional settings. Use the exact
`path` strings shown in the Parameters list."""


def analyze_workflow(parsed: dict) -> dict:
    data = chat_json(ANALYZE_SYSTEM, compact_for_llm(parsed), max_tokens=3000)
    if not isinstance(data, dict):
        raise ValueError("Analyzer returned non-object JSON")
    data.setdefault("category", "Other")
    if data["category"] not in CATEGORIES:
        data["category"] = "Other"
    for k in ("tags", "use_cases", "inputs", "outputs", "customizable"):
        data.setdefault(k, [])
    # snap parameter paths to real ones ('documentId' -> 'documentId.value' for resource locators)
    known = {(p["node"], p["path"]) for p in parsed["params_index"]}
    for c in data["customizable"]:
        if c.get("kind") != "credential" and (c.get("node"), c.get("path")) not in known:
            for suffix in (".value", ".__rl.value"):
                if (c.get("node"), c.get("path", "") + suffix) in known:
                    c["path"] = c["path"] + suffix
                    break
    # make sure credentials are always present as customizable items
    have = {(c.get("node"), c.get("path")) for c in data["customizable"] if c.get("kind") == "credential"}
    for cr in parsed["credentials_required"]:
        if (cr["node"], cr["type"]) not in have:
            data["customizable"].append({
                "key": f"cred_{cr['type']}_{cr['node']}".lower().replace(" ", "_"),
                "label": f"{cr['type']} credential for '{cr['node']}'", "node": cr["node"],
                "path": cr["type"], "kind": "credential",
                "description": "Select/enter the credential this node should use in your n8n.",
                "example": cr.get("name", ""),
            })
    # unique keys
    seen = set()
    for c in data["customizable"]:
        base = c.get("key") or "field"
        k, i = base, 1
        while k in seen:
            i += 1; k = f"{base}_{i}"
        c["key"] = k; seen.add(k)
    return data


RANK_SYSTEM = """You are the search engine of an internal automation catalog. Given a user's need and candidate
workflows, decide which ones actually solve (or nearly solve) the need. Respond with STRICT JSON:
{"results": [{"id": <int>, "score": 0-100, "reason": "one sentence why it matches",
              "changes_needed": ["short bullet of what must change to fit the user's case"]}],
 "no_match_advice": "if nothing fits well, say what would need to be built; else empty string"}
Only include candidates with score >= 35, best first, max 6."""


def rank_candidates(query: str, candidates: list[dict]) -> dict:
    lines = []
    for c in candidates:
        lines.append(f"[id={c['id']}] {c['name']} | category: {c['category']} | trigger: {c['trigger_type']}\n"
                     f"  summary: {c['summary']}\n  integrations: {', '.join(c['integrations'])}\n"
                     f"  use cases: {'; '.join(c['use_cases'][:4])}\n"
                     f"  inputs: {'; '.join(i.get('name','') for i in c['inputs'])} -> outputs: {'; '.join(o.get('name','') for o in c['outputs'])}")
    user = f"USER NEED:\n{query}\n\nCANDIDATES:\n" + "\n".join(lines)
    data = chat_json(RANK_SYSTEM, user, max_tokens=2000)
    data.setdefault("results", [])
    data.setdefault("no_match_advice", "")
    return data


ADAPT_SYSTEM = """You help a colleague reuse an existing n8n workflow for their own use case. You know the
workflow (summary, nodes, customizable fields). Respond with STRICT JSON:
{"fit": "good|partial|poor", "fit_explanation": "2 sentences",
 "steps": ["ordered, concrete steps to adapt the workflow"],
 "fields": [{"key": "<customizable key>", "required": true|false, "suggested_value": "value or empty",
             "why": "why this must change for this use case"}],
 "structural_changes": ["things that cannot be solved by filling fields (e.g. add a node, change trigger)"]}
`fields` must reference ONLY keys that exist in the customizable list. Mark credentials as required."""


def adaptation_plan(asset: dict, use_case: str) -> dict:
    desc = (f"Workflow: {asset['name']}\nSummary: {asset['summary']}\nTrigger: {asset['trigger_type']}\n"
            f"Nodes: {', '.join(n['name'] + ' (' + n['type'] + ')' for n in asset['nodes'])}\n"
            f"Inputs: {asset['inputs']}\nOutputs: {asset['outputs']}\n"
            f"Customizable fields:\n" +
            "\n".join(f"  - key={c['key']} | {c['label']} | kind={c['kind']} | node={c['node']} | {c['description']} | current={c.get('example','')}"
                      for c in asset["customizable"]))
    data = chat_json(ADAPT_SYSTEM, f"{desc}\n\nUSER'S USE CASE:\n{use_case}", max_tokens=2500)
    valid = {c["key"] for c in asset["customizable"]}
    data["fields"] = [f for f in data.get("fields", []) if f.get("key") in valid]
    data.setdefault("steps", []); data.setdefault("structural_changes", [])
    data.setdefault("fit", "partial"); data.setdefault("fit_explanation", "")
    return data


PATCH_SYSTEM = """You are a senior n8n engineer. You receive an n8n workflow export (JSON), the user's use case and
a list of structural changes that filling parameters cannot achieve. You must IMPLEMENT those changes as node
operations. Respond with STRICT JSON:
{"ops": [
  {"op": "add_node", "node": {"name": "...", "type": "n8n-nodes-base.<node>", "typeVersion": <number>,
                              "parameters": {...}, "position": [x, y]},
   "connect_from": [{"from": "<existing node name>", "from_index": 0, "to_index": 0}],
   "connect_to":   [{"to": "<existing node name>", "from_index": 0, "to_index": 0}]},
  {"op": "remove_node", "name": "...", "bridge": true},
  {"op": "update_node", "name": "...", "parameters": {...}}                      (merge parameters)
  {"op": "update_node", "name": "...", "type": "n8n-nodes-base.<node>", "typeVersion": 1, "parameters": {...}} (replace)
  {"op": "connect", "from": "...", "to": "...", "from_index": 0, "to_index": 0},
  {"op": "disconnect", "from": "...", "to": "..."}
 ],
 "fields": [
   {"key": "snake_case_unique", "label": "Discord webhook URL", "node": "<name of the new/changed node>",
    "path": "<exact parameter path inside that node's parameters, e.g. webhookUri or channelId.value>",
    "kind": "input|output|parameter|credential", "description": "what to enter", "example": "https://discord.com/api/webhooks/..."}
 ],
 "notes": ["only things that truly cannot be captured as a field"]}
Rules: use real n8n node types and CURRENT parameter schemas (copy conventions from the existing nodes:
resource locators are {"__rl":true,"value":...,"mode":...}; expressions start with "="). Keep node names
unique. For a new trigger, remove the old trigger node and connect the new one to the same next nodes.
Use `update_node` with `parameters` for Code nodes (key `jsCode`) and write complete, working JavaScript.
NEVER leave a placeholder for the user to edit by hand: every URL, id, token, email, channel, folder, sheet,
path or other value that only the user knows must be (a) written in the node parameters as a clearly
marked placeholder string such as "<<DISCORD_WEBHOOK_URL>>" and (b) declared in `fields` with the node
name and the exact parameter path so the app can fill it in. Every credential a new node needs is also a
field with kind=credential and path = the n8n credential type (e.g. slackApi, gmailOAuth2, discordWebhookApi);
do not set credentials on nodes yourself. Produce the minimal set of ops; empty ops if the changes are not
implementable, and explain in notes."""


def structural_patch(wf: dict, use_case: str, structural_changes: list[str]) -> dict:
    slim = {"name": wf.get("name"), "nodes": [{k: v for k, v in n.items() if k not in ("id", "webhookId", "credentials")}
                                              for n in wf["nodes"]], "connections": wf.get("connections", {})}
    body = json.dumps(slim)
    if len(body) > 40000:
        body = body[:40000] + "…(truncated)"
    user = (f"WORKFLOW JSON:\n{body}\n\nUSER'S USE CASE:\n{use_case}\n\nSTRUCTURAL CHANGES TO IMPLEMENT:\n" +
            "\n".join(f"- {s}" for s in structural_changes))
    data = chat_json(PATCH_SYSTEM, user, max_tokens=6000)
    data.setdefault("ops", []); data.setdefault("notes", []); data.setdefault("fields", [])
    seen: set[str] = set()
    clean = []
    for f in data["fields"]:
        if not (f.get("key") and f.get("node") and f.get("path")):
            continue
        k, base, i = f["key"], f["key"], 1
        while k in seen:
            i += 1; k = f"{base}_{i}"
        seen.add(k); f["key"] = k
        f.setdefault("kind", "parameter"); f.setdefault("label", k); f.setdefault("description", ""); f.setdefault("example", "")
        f["new_node"] = True
        clean.append(f)
    data["fields"] = clean
    return data
