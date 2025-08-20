from __future__ import annotations

from typing import Dict, Any, List, Tuple


def compute_score_and_rank(
    profile: Dict[str, Any],
    alignment: Dict[str, Any],
    scope: Dict[str, Any],
    rules: Dict[str, Any],
    impact: Dict[str, Any],
    feature_summary: Dict[str, Any] | None = None,
    dry_run: Dict[str, Any] | None = None,
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
    config_drift_penalty = 0
    if feature_summary:
        config_drift_penalty = len(feature_summary.get("config_drift", [])) * 8
    struct_score = 100 - min(100, error_violations + warn_violations + out_of_scope_penalty + export_penalty + signature_penalty + config_drift_penalty)

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
    if has_blocker or total < 40:
        risk = "high"
    elif 40 <= total < 70:
        risk = "medium"
    else:
        risk = "low"

    # Rank scale inverted to your desired mapping: 1 worst, 5 best
    if has_blocker:
        rank = 1
    elif total >= 90:
        rank = 5
    elif 70 <= total < 90:
        rank = 4
    elif 50 <= total < 70:
        rank = 3
    else:
        rank = 2

    recs: List[str] = []
    if unmet:
        recs.append("Address unmet acceptance criteria.")
    if violations:
        recs.append("Resolve architectural rule violations.")
    if impact.get("changed_exports"):
        recs.append("Review breaking changes to public API.")
    if scope.get("out_of_scope_files"):
        recs.append("Remove or explain out-of-scope file changes.")
    if feature_summary and feature_summary.get("config_drift"):
        recs.append("Revert unintended config/port/dependency changes unless in scope.")

    return total, risk, rank, recs


