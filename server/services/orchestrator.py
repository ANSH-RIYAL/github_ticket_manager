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

    tb = alignment.get("ticket_alignment", {})
    unmet = tb.get("unmet", [])
    matched = tb.get("matched", [])
    # proportional ticket score
    total_acs = len(unmet) + len(matched)
    if total_acs > 0:
        ticket_score = int(round(100 * (len(matched) / total_acs)))
    else:
        ticket_score = 0

    violations = rules.get("violations", [])
    # base struct score and penalties
    error_violations = len([v for v in violations if v.get("severity") == "error"]) * 40
    warn_violations = (len(violations) - len([v for v in violations if v.get("severity") == "error"])) * 10
    out_of_scope_penalty = len(scope.get("out_of_scope_files", [])) * 12
    export_penalty = len(impact.get("changed_exports", [])) * 15
    signature_penalty = len(impact.get("signature_changes", [])) * 10
    struct_score = 100 - min(100, error_violations + warn_violations + out_of_scope_penalty + export_penalty + signature_penalty)

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


