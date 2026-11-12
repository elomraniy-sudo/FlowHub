"""Deterministic stand-in for the LLM (LLM_MOCK=true). Lets the app run and tests pass offline."""
import json
import re


def mock_chat(messages: list[dict]) -> str:
    system = messages[0]["content"]
    user = messages[-1]["content"]

    if "catalog entry" in system:  # analyze
        name = re.search(r"Workflow name: (.*)", user)
        creds = re.findall(r"- (.+?) \| (.+?) \| ([^\-\n]+)", user)
        customizable = []
        for node, _type, cred in creds:
            for ct in cred.split(","):
                ct = ct.strip()
                if ct:
                    customizable.append({"key": f"cred_{ct}".lower(), "label": f"{ct} credential", "node": node.strip(),
                                         "path": ct, "kind": "credential", "description": "credential", "example": ""})
        for m in re.finditer(r"  (.+?) :: (.+?) = (.+)", user):
            node, path, val = m.groups()
            if any(w in path.lower() for w in ("id", "url", "channel", "sheet", "table", "path", "email", "to")):
                customizable.append({"key": re.sub(r"\W+", "_", path).lower(), "label": path, "node": node,
                                     "path": path, "kind": "input", "description": f"Currently {val}", "example": val})
        return json.dumps({
            "summary": f"Mock summary for {name.group(1) if name else 'workflow'}.",
            "category": "Internal Tools & Utilities",
            "tags": ["mock", "n8n"], "use_cases": ["Mock use case"],
            "inputs": [{"name": "trigger", "node": "", "description": "mock"}],
            "outputs": [{"name": "result", "node": "", "description": "mock"}],
            "customizable": customizable[:12],
        })
    if "search engine" in system:  # rank
        ids = [int(i) for i in re.findall(r"\[id=(\d+)\]", user)]
        return json.dumps({"results": [{"id": i, "score": 90 - 10 * k, "reason": "mock match",
                                        "changes_needed": ["set credentials"]} for k, i in enumerate(ids[:3])],
                           "no_match_advice": ""})
    if "reuse an existing n8n workflow" in system:  # adapt
        keys = re.findall(r"key=(\S+)", user)
        return json.dumps({"fit": "good", "fit_explanation": "mock", "steps": ["Fill the fields", "Deploy"],
                           "fields": [{"key": k, "required": True, "suggested_value": "", "why": "mock"} for k in keys],
                           "structural_changes": ["Add a Gmail node after Slack"] if "email" in user.lower() else []})
    if "senior n8n engineer" in system:  # structural patch
        return json.dumps({"ops": [
            {"op": "add_node", "node": {"name": "Notify by email", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1,
                                        "parameters": {"sendTo": "<<RECIPIENT_EMAIL>>", "subject": "=Report", "message": "={{ $json.total }}"}},
             "connect_from": [{"from": "Post to Slack"}]}],
            "fields": [{"key": "recipient_email", "label": "Recipient email", "node": "Notify by email", "path": "sendTo",
                        "kind": "output", "description": "Who receives the report", "example": "team@example.com"},
                       {"key": "gmail_credential", "label": "Gmail credential", "node": "Notify by email", "path": "gmailOAuth2",
                        "kind": "credential", "description": "Your Gmail account in n8n", "example": ""}],
            "notes": []})
    return "{}"
