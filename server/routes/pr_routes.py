from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from server.services.diff_service import compute_local_diff
from server.services.knowledge_service import load_knowledge_bundle
from server.services.guards import ScopeGuard, RuleGuard, ImpactGuard
from server.services.llm_service import evaluate_ticket_alignment
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

    diff_bundle = compute_local_diff(base_dir=base_dir, head_dir=head_dir)

    scope_out = ScopeGuard.run(ticket=ticket, diff_bundle=diff_bundle)
    rule_out = RuleGuard.run(rules=bundle["rules"], diff_bundle=diff_bundle, deps=bundle["deps"])
    impact_out = ImpactGuard.run(api=bundle["api_surface"], deps=bundle["deps"], diff_bundle=diff_bundle)

    alignment = evaluate_ticket_alignment(ticket=ticket, diff_bundle=diff_bundle)

    score, risk_level, rank, recommendations = compute_score_and_rank(
        profile=bundle["profile"],
        alignment=alignment,
        scope=scope_out,
        rules=rule_out,
        impact=impact_out,
    )

    report = {
        "schema_version": "1.0",
        "ticket_alignment": alignment.get("ticket_alignment", {}),
        "scope": scope_out,
        "rules": rule_out,
        "impact": impact_out,
        "score": score,
        "risk_level": risk_level,
        "rank": rank,
        "recommendations": recommendations,
    }

    # Persist stable outputs under results/{repoId}/analysis
    out_dir = Path("results") / repo_id / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff_bundle.json").write_text(json.dumps(diff_bundle, indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "report": report, "output_dir": str(out_dir)}), 200


