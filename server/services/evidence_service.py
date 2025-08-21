from __future__ import annotations

from typing import Dict, Any, List


def merge_alignment_evidence(root_alignment: Dict[str, Any], per_dir_alignments: List[Dict[str, Any]]) -> Dict[str, Any]:
    ac_list = []
    try:
        ac_list = [c.get("id") for c in root_alignment.get("ticket", {}).get("acceptance_criteria", [])]
    except Exception:
        pass
    matched_union: List[str] = list(root_alignment.get("ticket_alignment", {}).get("matched", []))
    evidence: List[Dict[str, Any]] = list(root_alignment.get("ticket_alignment", {}).get("evidence", []))
    for a in per_dir_alignments:
        ta = a.get("ticket_alignment", {})
        for m in ta.get("matched", []) or []:
            if m not in matched_union:
                matched_union.append(m)
        for ev in ta.get("evidence", []) or []:
            evidence.append(ev)
    unmet = [x for x in ac_list if x not in matched_union]
    return {
        "schema_version": "1.0",
        "ticket_alignment": {"matched": matched_union, "unmet": unmet, "evidence": evidence},
        "notes": "shadow_alignment"
    }


