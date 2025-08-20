from __future__ import annotations

from typing import Dict, Any, List, Tuple


def compute_score_and_rank(
    profile: Dict[str, Any],
    alignment: Dict[str, Any],
    scope: Dict[str, Any],
    rules: Dict[str, Any],
    impact: Dict[str, Any],
) -> Tuple[int, str, int, List[str]]:
    weights = profile.get("weights", {})
    w_ticket = float(weights.get("ticket_alignment", 0.5))
    w_struct = float(weights.get("structure_compliance", 0.35))
    w_conv = float(weights.get("conventions", 0.15))

    unmet = alignment.get("ticket_alignment", {}).get("unmet", [])
    matched = alignment.get("ticket_alignment", {}).get("matched", [])
    ticket_score = 100 if matched and not unmet else (50 if matched else 0)

    violations = rules.get("violations", [])
    struct_score = 100 - min(100, len([v for v in violations if v.get("severity") == "error"]) * 40 + len(violations) * 10)

    # conventions not implemented separately; keep neutral
    conv_score = 100

    total = int(round(w_ticket * ticket_score + w_struct * struct_score + w_conv * conv_score))

    blockers = set(profile.get("blockers", []))
    has_blocker = False
    # rule blockers
    rule_ids = {v.get("rule_id") for v in violations}
    if blockers.intersection(rule_ids):
        has_blocker = True
    # unmet AC blocker
    if "unmet_acceptance_criteria" in blockers and unmet:
        has_blocker = True

    thresholds = profile.get("risk_thresholds", {})
    if has_blocker or total < 60:
        risk = "high"
    elif 60 <= total < 80:
        risk = "medium"
    else:
        risk = "low"

    if not has_blocker and total >= 90:
        rank = 1
    elif not has_blocker and 80 <= total < 90:
        rank = 2
    elif not has_blocker and 70 <= total < 80:
        rank = 3
    elif has_blocker:
        rank = 5
    else:
        rank = 4

    recs: List[str] = []
    if unmet:
        recs.append("Address unmet acceptance criteria.")
    if violations:
        recs.append("Resolve architectural rule violations.")
    if impact.get("changed_exports"):
        recs.append("Review breaking changes to public API.")
    if scope.get("out_of_scope_files"):
        recs.append("Remove or explain out-of-scope file changes.")

    return total, risk, rank, recs


