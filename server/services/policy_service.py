from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List


def load_policies(policies_path: str | None) -> Dict[str, Any]:
    if not policies_path:
        return {}
    p = Path(policies_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def evaluate_policies(report: Dict[str, Any], policies: Dict[str, Any]) -> List[Dict[str, Any]]:
    violations: List[Dict[str, Any]] = []
    # scope: max out-of-scope files
    scope_cfg = (policies or {}).get("scope", {})
    max_out = int(scope_cfg.get("max_out_of_scope", 0))
    out_list = (report.get("scope", {}) or {}).get("out_of_scope_files", [])
    if max_out == 0 and out_list:
        for p in out_list:
            violations.append({
                "id": "OUT_OF_SCOPE",
                "level": "error",
                "path": p,
                "evidence_ref": {"rel_path": str(Path(p).parent) if "/" in p else "", "file": Path(p).name},
            })

    # api changes: signature breaks / exports add/remove
    api_cfg = (policies or {}).get("api_change", {})
    impact = report.get("impact", {}) or {}
    for path in impact.get("signature_changes", []) or []:
        violations.append({
            "id": "SIGNATURE_BREAK",
            "level": api_cfg.get("signature_break", {}).get("level", "error"),
            "path": path,
            "evidence_ref": {"rel_path": str(Path(path).parent) if "/" in path else "", "file": Path(path).name},
        })

    # config drift from feature_summary and dry_run
    cfg_cfg = (policies or {}).get("config_drift", {})
    for p in (report.get("feature_summary", {}) or {}).get("config_drift", []) or []:
        violations.append({
            "id": "CONFIG_DRIFT",
            "level": cfg_cfg.get("env", {}).get("level", "warn"),
            "path": p,
            "evidence_ref": {"rel_path": str(Path(p).parent) if "/" in p else "", "file": Path(p).name if p != "<unknown>" else p},
        })
    return violations


