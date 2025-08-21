from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from server.services.diff_service import compute_local_diff
from server.services.knowledge_service import load_knowledge_bundle
from server.services.guards import ScopeGuard, RuleGuard, ImpactGuard
from server.services.dry_run_service import build_feature_summary, static_dry_run
from server.services.ast_service import compute_ast_deltas
from server.services.llm_service import (
    evaluate_ticket_alignment,
    scope_guard_llm,
    rule_guard_llm,
    impact_guard_llm,
)
from server.services.orchestrator import compute_score_and_rank


pr_bp = Blueprint("pr", __name__)


@pr_bp.post("/local/pr/analyze")
def analyze_local_pr_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    base_dir = payload.get("base_dir")
    head_dir = payload.get("head_dir")
    ticket = payload.get("ticket")
    if not base_dir or not os.path.isdir(base_dir):
        return jsonify({"ok": False, "error": "Invalid base_dir"}), 400
    if not head_dir or not os.path.isdir(head_dir):
        return jsonify({"ok": False, "error": "Invalid head_dir"}), 400
    if not isinstance(ticket, dict):
        return jsonify({"ok": False, "error": "Invalid ticket"}), 400

    # repo_id derived from base folder name
    repo_id = Path(base_dir).name
    knowledge_dir = Path("results") / repo_id / "knowledge"
    bundle = load_knowledge_bundle(str(knowledge_dir))

    diff_bundle = compute_local_diff(base_dir=base_dir, head_dir=head_dir, include_context=True)
    feature_summary = build_feature_summary(ticket=ticket, diff_bundle=diff_bundle)
    dry_run = static_dry_run(api_surface=bundle["api_surface"], deps=bundle["deps"], diff_bundle=diff_bundle)

    # AST-level deltas on changed code files
    changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]
    ast_deltas = compute_ast_deltas(base_dir=base_dir, head_dir=head_dir, changed_files=changed_files)

    # Prefer LLM guards with deterministic fallbacks
    scope_out = scope_guard_llm(ticket=ticket, diff_bundle=diff_bundle)
    rule_out = rule_guard_llm(rules=bundle["rules"], diff_bundle=diff_bundle, deps=bundle["deps"])
    impact_out = impact_guard_llm(api=bundle["api_surface"], deps=bundle["deps"], diff_bundle=diff_bundle, feature_summary=feature_summary, dry_run=dry_run)

    alignment = evaluate_ticket_alignment(ticket=ticket, diff_bundle=diff_bundle, feature_summary=feature_summary, dry_run=dry_run)

    score, risk_level, rank, recommendations = compute_score_and_rank(
        profile=bundle["profile"],
        alignment=alignment,
        scope=scope_out,
        rules=rule_out,
        impact=impact_out,
        feature_summary=feature_summary,
        dry_run={**dry_run, "ast_deltas": ast_deltas},
    )

    report = {
        "schema_version": "1.0",
        "ticket_alignment": alignment.get("ticket_alignment", {}),
        "scope": scope_out,
        "rules": rule_out,
        "impact": impact_out,
        "feature_summary": feature_summary,
        "dry_run": {**dry_run, "ast_deltas": ast_deltas},
        "score": score,
        "risk_level": risk_level,
        "rank": rank,
        "recommendations": recommendations,
        "section_scores": {
            "ticket_alignment": alignment.get("ticket_alignment", {}).get("matched", []),
            "out_of_scope_count": len(scope_out.get("out_of_scope_files", [])),
            "rule_violations": len(rule_out.get("violations", [])),
            "api_changes": len(impact_out.get("changed_exports", [])) + len(impact_out.get("signature_changes", []))
        },
    }

    # Persist stable outputs under results/{repoId}/analysis
    out_dir = Path("results") / repo_id / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff_bundle.json").write_text(json.dumps(diff_bundle, indent=2), encoding="utf-8")
    (out_dir / "feature_summary.json").write_text(json.dumps(feature_summary, indent=2), encoding="utf-8")
    (out_dir / "dry_run.json").write_text(json.dumps(report["dry_run"], indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "report": report, "output_dir": str(out_dir)}), 200


