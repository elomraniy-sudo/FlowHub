"""Deterministic extraction from an n8n workflow export (no LLM needed)."""
import hashlib
import json
from typing import Any

CORE_NODES = {
    "set", "if", "switch", "merge", "noOp", "code", "function", "functionItem", "splitInBatches",
    "splitOut", "aggregate", "itemLists", "filter", "sort", "limit", "wait", "stickyNote",
    "executeWorkflow", "manualTrigger", "start", "dateTime", "crypto", "html", "xml", "markdown",
    "renameKeys", "removeDuplicates", "summarize", "compareDatasets", "editImage", "stopAndError",
    "respondToWebhook", "form", "formTrigger", "errorTrigger", "scheduleTrigger", "cron", "interval",
    "webhook", "httpRequest", "executionData", "compression", "readBinaryFile", "writeBinaryFile",
    "moveBinaryData", "spreadsheetFile", "extractFromFile", "convertToFile", "debugHelper",
}


def short_type(node_type: str) -> str:
    """'n8n-nodes-base.googleSheets' -> 'googleSheets'; '@n8n/n8n-nodes-langchain.agent' -> 'agent'"""
    return node_type.rsplit(".", 1)[-1]


def trigger_type(nodes: list[dict]) -> str:
    types = [short_type(n.get("type", "")) for n in nodes]
    if any(t in ("webhook", "formTrigger") for t in types):
        return "webhook"
    if any(t in ("scheduleTrigger", "cron", "interval") for t in types):
        return "schedule"
    if any(t.lower().endswith("trigger") and t not in ("manualTrigger", "executeWorkflowTrigger", "errorTrigger") for t in types):
        return "app-event"
    return "manual"


def _leaves(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    """Flatten parameters into (json.path, scalar) pairs; skip huge code blobs."""
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_leaves(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_leaves(v, f"{path}[{i}]"))
    elif obj not in (None, "", [], {}):
        s = str(obj)
        if len(s) > 400:  # code / long prompts -> keep a hint only
            s = s[:120] + "…"
        out.append((path, s))
    return out


def parse_workflow(raw: str | dict) -> dict:
    wf = json.loads(raw) if isinstance(raw, str) else raw
    if "nodes" not in wf or not isinstance(wf["nodes"], list):
        raise ValueError("Not an n8n workflow export: missing 'nodes' array")

    nodes_out, integrations, creds, params_index = [], [], [], []
    for n in wf["nodes"]:
        st = short_type(n.get("type", ""))
        node_creds = [{"node": n.get("name"), "type": ct, "name": (cv or {}).get("name", "")}
                      for ct, cv in (n.get("credentials") or {}).items()]
        creds.extend(node_creds)
        if st not in CORE_NODES and st not in integrations:
            integrations.append(st)
        nodes_out.append({"name": n.get("name"), "type": st, "credentials": [c["type"] for c in node_creds],
                          "notes": n.get("notes", "")})
        for path, val in _leaves(n.get("parameters", {})):
            params_index.append({"node": n.get("name"), "path": path, "value": val})

    canonical = json.dumps(wf.get("nodes", []), sort_keys=True) + json.dumps(wf.get("connections", {}), sort_keys=True)
    return {
        "name": wf.get("name") or "Untitled workflow",
        "nodes": nodes_out,
        "integrations": integrations,
        "trigger_type": trigger_type(wf["nodes"]),
        "credentials_required": creds,
        "params_index": params_index,       # fed to the LLM to pick customization points
        "content_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "sticky_notes": [n.get("parameters", {}).get("content", "") for n in wf["nodes"]
                         if short_type(n.get("type", "")) == "stickyNote"],
    }


def compact_for_llm(parsed: dict, max_params: int = 120) -> str:
    """A compact, token-cheap description of a workflow for prompts."""
    lines = [f"Workflow name: {parsed['name']}", f"Trigger: {parsed['trigger_type']}",
             "Nodes (name | type | credentials):"]
    for n in parsed["nodes"]:
        lines.append(f"  - {n['name']} | {n['type']} | {','.join(n['credentials']) or '-'}")
    if parsed.get("sticky_notes"):
        lines.append("Author notes: " + " / ".join(s[:300] for s in parsed["sticky_notes"] if s))
    lines.append("Parameters (node :: path = value):")
    for p in parsed["params_index"][:max_params]:
        lines.append(f"  {p['node']} :: {p['path']} = {p['value']}")
    if parsed.get("doc_text"):
        lines.append("\nExisting documentation written by a colleague (use it, but parameter paths must still come "
                     "from the Parameters list above):\n" + parsed["doc_text"][:6000])
    return "\n".join(lines)


# ---------- structural patches (AI-generated node changes) ----------

class PatchError(ValueError):
    pass


def _conn(wf: dict, src: str) -> list:
    return wf.setdefault("connections", {}).setdefault(src, {}).setdefault("main", [])


def _connect(wf: dict, src: str, dst: str, src_idx: int = 0, dst_idx: int = 0) -> None:
    outs = _conn(wf, src)
    while len(outs) <= src_idx:
        outs.append([])
    if not any(c.get("node") == dst and c.get("index", 0) == dst_idx for c in outs[src_idx]):
        outs[src_idx].append({"node": dst, "type": "main", "index": dst_idx})


def _disconnect(wf: dict, src: str, dst: str) -> None:
    for outs in (wf.get("connections", {}).get(src, {}).get("main") or []):
        outs[:] = [c for c in outs if c.get("node") != dst]


def _incoming(wf: dict, name: str) -> list[tuple[str, int, int]]:
    found = []
    for src, m in wf.get("connections", {}).items():
        for si, outs in enumerate(m.get("main") or []):
            for c in outs:
                if c.get("node") == name:
                    found.append((src, si, c.get("index", 0)))
    return found


def apply_patch(wf: dict, ops: list[dict]) -> list[str]:
    """Apply node operations produced by the LLM. Returns a human-readable change log.
    ops: add_node{node, connect_from[], connect_to[]} | remove_node{name, bridge} |
         update_node{name, parameters, type?, typeVersion?, rename?} |
         connect{from,to,from_index,to_index} | disconnect{from,to}"""
    log: list[str] = []
    by_name = lambda: {n["name"]: n for n in wf["nodes"]}
    for op in ops:
        kind = op.get("op")
        if kind == "add_node":
            n = op.get("node") or {}
            if not n.get("name") or not n.get("type"):
                raise PatchError("add_node needs node.name and node.type")
            if not (n["type"].startswith("n8n-nodes-base.") or n["type"].startswith("@n8n/")):
                raise PatchError(f"unknown node type {n['type']}")
            if n["name"] in by_name():
                raise PatchError(f"node '{n['name']}' already exists")
            n.setdefault("typeVersion", 1); n.setdefault("parameters", {})
            if "position" not in n:
                xs = [nn.get("position", [0, 0])[0] for nn in wf["nodes"]] or [0]
                n["position"] = [max(xs) + 240, 300]
            wf["nodes"].append(n)
            log.append(f"Added node '{n['name']}' ({n['type']})")
            for c in op.get("connect_from") or []:
                _connect(wf, c["from"], n["name"], c.get("from_index", 0), c.get("to_index", 0))
            for c in op.get("connect_to") or []:
                _connect(wf, n["name"], c["to"], c.get("from_index", 0), c.get("to_index", 0))
        elif kind == "remove_node":
            name = op.get("name")
            if name not in by_name():
                raise PatchError(f"remove_node: no node '{name}'")
            ins = _incoming(wf, name)
            outs = [c for o in (wf.get("connections", {}).get(name, {}).get("main") or []) for c in o]
            wf["nodes"] = [n for n in wf["nodes"] if n["name"] != name]
            wf.get("connections", {}).pop(name, None)
            for src, *_ in ins:
                _disconnect(wf, src, name)
            if op.get("bridge", True):
                for src, si, _ in ins:
                    for c in outs:
                        _connect(wf, src, c["node"], si, c.get("index", 0))
            log.append(f"Removed node '{name}'" + (" (connections bridged)" if op.get("bridge", True) and ins and outs else ""))
        elif kind == "update_node":
            name = op.get("name")
            node = by_name().get(name)
            if not node:
                raise PatchError(f"update_node: no node '{name}'")
            if op.get("type"):
                node["type"] = op["type"]; node["typeVersion"] = op.get("typeVersion", node.get("typeVersion", 1))
                node["parameters"] = op.get("parameters", {})
                node.pop("credentials", None)
                log.append(f"Replaced node '{name}' with {op['type']}")
            elif op.get("parameters"):
                node.setdefault("parameters", {}).update(op["parameters"])
                log.append(f"Updated parameters of '{name}': {', '.join(op['parameters'].keys())}")
            if op.get("rename"):
                new = op["rename"]
                node["name"] = new
                wf.setdefault("connections", {})[new] = wf["connections"].pop(name, {"main": []})
                for m in wf["connections"].values():
                    for outs in m.get("main") or []:
                        for c in outs:
                            if c.get("node") == name:
                                c["node"] = new
                log.append(f"Renamed '{name}' to '{new}'")
        elif kind == "connect":
            names = by_name()
            if op["from"] not in names or op["to"] not in names:
                raise PatchError(f"connect: unknown node in {op['from']} -> {op['to']}")
            _connect(wf, op["from"], op["to"], op.get("from_index", 0), op.get("to_index", 0))
            log.append(f"Connected '{op['from']}' → '{op['to']}'")
        elif kind == "disconnect":
            _disconnect(wf, op["from"], op["to"])
            log.append(f"Disconnected '{op['from']}' → '{op['to']}'")
        else:
            raise PatchError(f"unknown op {kind}")
    names = {n["name"] for n in wf["nodes"]}
    for src, m in list(wf.get("connections", {}).items()):
        if src not in names:
            wf["connections"].pop(src); continue
        for outs in m.get("main") or []:
            for c in outs:
                if c.get("node") not in names:
                    raise PatchError(f"connection points to missing node '{c.get('node')}'")
    return log


def ensure_executable(wf: dict) -> bool:
    """Manual-trigger workflows cannot be started by another workflow. Add an 'Execute Workflow Trigger'
    wired like the manual trigger so the FlowHub Runner can run them. Returns True if added."""
    manual = next((n for n in wf["nodes"] if short_type(n.get("type", "")) == "manualTrigger"), None)
    has_exec = any(short_type(n.get("type", "")) == "executeWorkflowTrigger" for n in wf["nodes"])
    if not manual or has_exec:
        return False
    name = "Run from FlowHub"
    pos = manual.get("position", [0, 0])
    wf["nodes"].append({"parameters": {}, "name": name, "type": "n8n-nodes-base.executeWorkflowTrigger",
                        "typeVersion": 1, "position": [pos[0], pos[1] + 200]})
    wf.setdefault("connections", {})[name] = json.loads(json.dumps(wf["connections"].get(manual["name"], {"main": [[]]})))
    return True


# ---------- applying customizations ----------

def _set_path(obj: Any, path: str, value: Any) -> None:
    """Set value at a flattened path like 'a.b[2].c' inside a dict."""
    import re
    tokens = [t for t in re.split(r"\.|(\[\d+\])", path) if t]
    cur = obj
    for i, tok in enumerate(tokens):
        last = i == len(tokens) - 1
        key: Any = int(tok[1:-1]) if tok.startswith("[") else tok
        if last:
            cur[key] = value
        else:
            nxt_is_idx = tokens[i + 1].startswith("[")
            if isinstance(cur, list):
                while len(cur) <= key: cur.append({})
                if cur[key] is None: cur[key] = [] if nxt_is_idx else {}
            else:
                cur.setdefault(key, [] if nxt_is_idx else {})
            cur = cur[key]


def _get_path(obj: Any, path: str) -> Any:
    import re
    cur = obj
    for tok in [t for t in re.split(r"\.|(\[\d+\])", path) if t]:
        key: Any = int(tok[1:-1]) if tok.startswith("[") else tok
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def apply_customizations(raw: str | dict, values: dict[str, Any], customizable: list[dict],
                         new_name: str | None = None) -> dict:
    """values: {customizable.key: user value}. Credential entries expect {"id":..,"name":..} or a plain name."""
    wf = json.loads(raw) if isinstance(raw, str) else json.loads(json.dumps(raw))
    by_name = {n.get("name"): n for n in wf["nodes"]}
    spec = {c["key"]: c for c in customizable}

    for key, val in values.items():
        c = spec.get(key)
        if not c or val in (None, ""):
            continue
        node = by_name.get(c.get("node"))
        if node is None:
            continue
        if c.get("kind") == "credential":
            node.setdefault("credentials", {})
            if isinstance(val, dict):
                node["credentials"][c["path"]] = {"id": val.get("id", ""), "name": val.get("name", "")}
            else:
                node["credentials"][c["path"]] = {"name": str(val)}
        else:
            node.setdefault("parameters", {})
            path = c["path"]
            # n8n "resource locator" params are objects {__rl, value, mode}; never overwrite the object
            cur = _get_path(node["parameters"], path)
            if isinstance(cur, dict) and cur.get("__rl"):
                path = f"{path}.value"
            _set_path(node["parameters"], path, val)

    # credentials never filled by the user are stripped so n8n prompts for them instead of
    # pointing at someone else's credential ids
    filled = {(spec[k]["node"], spec[k]["path"]) for k in values if k in spec and spec[k].get("kind") == "credential" and values[k]}
    for n in wf["nodes"]:
        for ct in list((n.get("credentials") or {}).keys()):
            if (n.get("name"), ct) not in filled:
                n["credentials"].pop(ct)

    if new_name:
        wf["name"] = new_name
    for k in ("id", "versionId", "pinData", "staticData"):
        wf.pop(k, None)
    wf.setdefault("settings", {})
    return wf
