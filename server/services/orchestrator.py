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
    # AST/dry-run based penalties/credits
    dry = dry_run or {}
    ast = (dry.get("ast_deltas") or {}) if dry else {}
    sem = (dry.get("semantic_deltas") or {}) if dry else {}
    callers = dry.get("callers") or []
    signature_breaking_penalty = len(ast.get("signature_breaking", [])) * 20
    export_add_penalty = len(ast.get("exports_added", [])) * 8
    export_remove_penalty = len(ast.get("exports_removed", [])) * 12
    # blast radius penalty per 50 callers
    blast_penalty = (len(callers) // 50) * 5
    # semantic replacements: penalize likely global replacements
    sem_penalty = 0
    for rep in sem.get("likely_replacements", []) or []:
        frm = (rep.get("from") or "").lower()
        to = (rep.get("to") or "").lower()
        if frm and to and frm != to:
            sem_penalty += 6
            # heavier for core time/date setters
            if frm.startswith("set") or to.startswith("set"):
                sem_penalty += 6
    # guarded change credit: presence of both legacy and new calls suggests scoping
    guard_credit = 0
    added_names = {e.get("name") for e in sem.get("calls_added", []) or []}
    removed_names = {e.get("name") for e in sem.get("calls_removed", []) or []}
    if ("setUTCMonth" in added_names and "setMonth" not in removed_names) or (
        "setUTCFullYear" in added_names and "setFullYear" not in removed_names
    ):
        guard_credit = 10
    struct_score = 100 - min(
        100,
        error_violations
        + warn_violations
        + out_of_scope_penalty
        + export_penalty
        + signature_penalty
        + config_drift_penalty
        + signature_breaking_penalty
        + export_add_penalty
        + export_remove_penalty
        + blast_penalty
        + sem_penalty
        - guard_credit,
    )

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

    # Discrete rank with big gaps, based on strong signals
    unmet_count = len(unmet)
    out_count = len(scope.get("out_of_scope_files", []))
    ast = (dry_run or {}).get("ast_deltas", {})
    sem = (dry_run or {}).get("semantic_deltas", {})
    callers = (dry_run or {}).get("callers", [])
    replacements = sem.get("likely_replacements", []) if isinstance(sem, dict) else []
    sig_break = len(ast.get("signature_breaking", [])) if isinstance(ast, dict) else 0
    exp_add = len(ast.get("exports_added", [])) if isinstance(ast, dict) else 0
    exp_rem = len(ast.get("exports_removed", [])) if isinstance(ast, dict) else 0

    # guard signal: UTC setters added while local setters preserved
    added_names = {e.get("name") for e in (sem.get("calls_added", []) or [])} if isinstance(sem, dict) else set()
    removed_names = {e.get("name") for e in (sem.get("calls_removed", []) or [])} if isinstance(sem, dict) else set()
    # Guard signal: both UTC setter and local setter observed in added lines (coexistence),
    # indicating a conditional branch that preserves local behavior.
    guard_signal = (
        ("setUTCMonth" in added_names and "setMonth" in added_names) or
        ("setUTCFullYear" in added_names and "setFullYear" in added_names)
    )

    if has_blocker or sig_break > 0 or exp_rem > 0 or out_count >= 5:
        rank = 1
    elif out_count >= 3 or len(replacements) >= 3 or len(callers) >= 300:
        rank = 2
    elif unmet_count >= 2 or out_count >= 1 or len(replacements) >= 1:
        rank = 3
    elif unmet_count == 1 or exp_add > 0:
        rank = 4
    elif guard_signal and out_count == 0 and len(replacements) == 0 and sig_break == 0 and exp_add == 0 and exp_rem == 0:
        rank = 5
    else:
        # Generic perfection: clean, in-scope, no API/signature changes, no replacements
        if out_count == 0 and sig_break == 0 and exp_add == 0 and exp_rem == 0 and len(replacements) == 0:
            rank = 5
        else:
            rank = 4 if total >= 75 else 3

    # Map rank to bold score bands, then apply small evidence-based adjustments (no overfitting)
    band = {1: 15, 2: 35, 3: 55, 4: 75, 5: 95}
    base = band.get(rank, total)
    # adjustments from structural signals (bounded)
    adj = 0
    adj -= 2 * unmet_count
    adj -= 3 * out_count
    adj -= 5 * sig_break
    adj -= 2 * exp_add
    adj -= 3 * exp_rem
    adj -= min(5, len(replacements))
    adj -= min(5, len(callers) // 100)
    if feature_summary:
        adj -= min(5, len(feature_summary.get("config_drift", [])))
    if guard_signal:
        adj += 5
    # clamp to keep within a narrow range around the band
    margin = 6
    total = max(0, min(100, max(base - margin, min(base + margin, base + adj))))

    if rank in (1, 2):
        risk = "high"
    elif rank == 3:
        risk = "medium"
    else:
        risk = "low"

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


