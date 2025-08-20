from __future__ import annotations

import os
from typing import Dict, Any
import json
import os
import urllib.request
import urllib.error


def evaluate_ticket_alignment(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return _heuristic_alignment(ticket, diff_bundle)

    # Model call with strict IO
    system = "ONLY_OUTPUT valid JSON per schema. Validate PR diff against ticket acceptance criteria. Be evidence-based; if unsure, mark unmet."
    user_payload = {"schema_version": "1.0", "ticket": ticket.get("ticket", {}), "diff_bundle": diff_bundle}
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        # normalize to expected fields
        if "ticket_alignment" not in parsed:
            return _heuristic_alignment(ticket, diff_bundle)
        return parsed
    except Exception:
        return _heuristic_alignment(ticket, diff_bundle)


def _heuristic_alignment(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    ac = ticket.get("ticket", {}).get("acceptance_criteria", [])
    matched = []
    evidence = []
    scope = ticket.get("ticket", {}).get("expected_change_scope", {})
    allowed = scope.get("files_glob", [])
    changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]
    in_scope = []
    if allowed:
        for p in changed_files:
            for g in allowed:
                from fnmatch import fnmatch
                if fnmatch(p, g):
                    in_scope.append(p)
                    break
    matched_ids = [c.get("id") for c in ac[:1]] if in_scope else []
    if matched_ids:
        matched = matched_ids
        evidence.append({"ac_id": matched_ids[0], "files": sorted(set(in_scope)), "hunks": []})
    return {
        "schema_version": "1.0",
        "ticket_alignment": {
            "matched": matched,
            "unmet": [c.get("id") for c in ac if c.get("id") not in matched],
            "evidence": evidence,
        },
        "notes": "heuristic alignment",
    }


