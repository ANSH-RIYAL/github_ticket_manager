from __future__ import annotations

import json
from typing import Dict, Any, List


def _sarif_result(rule_id: str, level: str, message: str, file_path: str | None) -> Dict[str, Any]:
    loc = {}
    if file_path:
        loc = {
            "physicalLocation": {
                "artifactLocation": {"uri": file_path}
            }
        }
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [loc] if loc else []
    }


def build_sarif(report: Dict[str, Any], policy_violations: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    # Scope violations
    for v in policy_violations or []:
        rid = v.get("id", "POLICY")
        lvl = v.get("level", "warning")
        path = v.get("path")
        msg = f"{rid} at {path}"
        results.append(_sarif_result(rid, lvl, msg, path))

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Shadow PR Governance", "informationUri": "https://example.local"}},
                "results": results,
            }
        ]
    }
    return sarif


