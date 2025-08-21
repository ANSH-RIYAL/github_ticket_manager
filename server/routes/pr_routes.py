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
    ticket_alignment_shadow,
    impact_guard_shadow,
)
from server.services.orchestrator import compute_score_and_rank
from server.services.shadow_fs_service import build_shadow_knowledge, build_shadow_diff, get_dir_context
from server.services.policy_service import evaluate_policies, load_policies
from server.services.sarif_service import build_sarif


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

    # Ensure shadow knowledge exists (used by navigator contexts)
    shadow_root = Path("results") / repo_id / "shadow"
    if not shadow_root.exists():
        shadow_root.mkdir(parents=True, exist_ok=True)
        try:
            build_shadow_knowledge(repo_dir=base_dir, out_dir=str(shadow_root))
        except Exception:
            pass

    diff_bundle = compute_local_diff(base_dir=base_dir, head_dir=head_dir, include_context=True)
    feature_summary = build_feature_summary(ticket=ticket, diff_bundle=diff_bundle)
    dry_run = static_dry_run(api_surface=bundle["api_surface"], deps=bundle["deps"], diff_bundle=diff_bundle)

    # AST-level deltas on changed code files
    changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]
    ast_deltas = compute_ast_deltas(base_dir=base_dir, head_dir=head_dir, changed_files=changed_files)

    # Deterministic guards (global). Shadow-scoped LLM prompts are used for alignment/impact per directory
    scope_out = ScopeGuard.run(ticket=ticket, diff_bundle=diff_bundle)
    rule_out = RuleGuard.run(rules=bundle["rules"], diff_bundle=diff_bundle, deps=bundle["deps"])
    impact_out = ImpactGuard.run(api=bundle["api_surface"], deps=bundle["deps"], diff_bundle=diff_bundle)

    # Build shadow diff environment for this analysis and perform root + per-directory shadow prompts
    run_id = __import__("datetime").datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    shadow_diff_root = Path("results") / repo_id / "shadow_diff" / run_id
    shadow_diff_root.mkdir(parents=True, exist_ok=True)
    build_shadow_diff(base_dir=base_dir, head_dir=head_dir, diff_bundle=diff_bundle, shadow_root=str(shadow_diff_root))

    # Root context alignment
    root_ctx = get_dir_context(shadow_root=str(shadow_diff_root), rel_path="", include_diff=True, budget=4000)
    global_summary = {"feature_summary": feature_summary, "dry_run": dry_run}
    alignment = ticket_alignment_shadow(ticket=ticket, dir_context=root_ctx, global_summary=global_summary)

    # Per-directory shadow prompts
    changed_dirs = sorted({str(Path(f.get("path") or "").parent) if str(Path(f.get("path") or "").parent) != "." else "" for f in diff_bundle.get("files", []) if f.get("path")})
    per_dir_alignment: List[Dict[str, Any]] = []
    per_dir_impact: List[Dict[str, Any]] = []
    per_directory: List[Dict[str, Any]] = []
    for rel in changed_dirs:
        ctx = get_dir_context(shadow_root=str(shadow_diff_root), rel_path=rel, include_diff=True, budget=3000)
        try:
            a = ticket_alignment_shadow(ticket=ticket, dir_context=ctx, global_summary=global_summary)
            per_dir_alignment.append({"rel_path": rel, "alignment": a})
        except Exception:
            per_dir_alignment.append({"rel_path": rel, "alignment": {"ticket_alignment": {"matched": [], "unmet": [], "evidence": []}}})
        try:
            ig = impact_guard_shadow(dir_context=ctx, feature_summary=feature_summary, dry_run=dry_run)
            per_dir_impact.append({"rel_path": rel, "impact": ig})
        except Exception:
            per_dir_impact.append({"rel_path": rel, "impact": {"changed_exports": [], "signature_changes": [], "possibly_impacted": []}})

    # Merge per-dir results conservatively into global
    ac_list = [c.get("id") for c in ticket.get("ticket", {}).get("acceptance_criteria", [])]
    matched_union: List[str] = [m for m in (alignment.get("ticket_alignment", {}).get("matched", []) or []) if m in ac_list]
    evidence: List[Dict[str, Any]] = list(alignment.get("ticket_alignment", {}).get("evidence", []))
    for a in per_dir_alignment:
        ta = (a.get("alignment") or {}).get("ticket_alignment", {})
        rel = a.get("rel_path", "")
        for m in ta.get("matched", []) or []:
            if m in ac_list and m not in matched_union:
                matched_union.append(m)
        for ev in ta.get("evidence", []) or []:
            # attach rel_path if missing
            if isinstance(ev, dict) and "rel_path" not in ev:
                ev["rel_path"] = rel
            evidence.append(ev)
    unmet = [x for x in ac_list if x not in matched_union]
    alignment = {
        "schema_version": "1.0",
        "ticket_alignment": {"matched": matched_union, "unmet": unmet, "evidence": evidence},
        "notes": "shadow_alignment"
    }

    # Impact: union and de-dup (override deterministic if shadow has signals)
    ch: List[str] = []
    sig: List[str] = []
    imp: List[str] = []
    for ig in per_dir_impact:
        impact_obj = ig.get("impact") or {}
        for v in impact_obj.get("changed_exports", []) or []:
            if v not in ch:
                ch.append(v)
        for v in impact_obj.get("signature_changes", []) or []:
            if v not in sig:
                sig.append(v)
        for v in impact_obj.get("possibly_impacted", []) or []:
            if v not in imp:
                imp.append(v)
    if ch or sig or imp:
        impact_out = {"changed_exports": ch, "signature_changes": sig, "possibly_impacted": imp}

    # Build per_directory array
    for i in range(len(per_dir_alignment)):
        rel = per_dir_alignment[i].get("rel_path", "")
        align = (per_dir_alignment[i].get("alignment") or {}).get("ticket_alignment", {})
        imp_dir = (per_dir_impact[i].get("impact") if i < len(per_dir_impact) else {}) or {}
        per_directory.append({
            "rel_path": rel,
            "matched": [m for m in (align.get("matched", []) or []) if m in ac_list],
            "impact": {
                "changed_exports": imp_dir.get("changed_exports", []),
                "signature_changes": imp_dir.get("signature_changes", []),
                "possibly_impacted": imp_dir.get("possibly_impacted", []),
            }
        })

    score, risk_level, rank, recommendations = compute_score_and_rank(
        profile=bundle["profile"],
        alignment=alignment,
        scope=scope_out,
        rules=rule_out,
        impact=impact_out,
        feature_summary=feature_summary,
        dry_run={**dry_run, "ast_deltas": ast_deltas},
    )

    # Policy evaluation and SARIF
    policies_path = str(Path("templates") / "policies.sample.json")
    policies = load_policies(policies_path)
    policy_violations = evaluate_policies(report={
        "impact": impact_out,
        "scope": scope_out,
        "feature_summary": feature_summary,
    }, policies=policies)
    sarif = build_sarif(report={}, policy_violations=policy_violations)

    report = {
        "schema_version": "1.0",
        "ticket_alignment": alignment.get("ticket_alignment", {}),
        "scope": scope_out,
        "rules": rule_out,
        "impact": impact_out,
        "feature_summary": feature_summary,
        "dry_run": {**dry_run, "ast_deltas": ast_deltas},
        "per_directory": per_directory,
        "policy_violations": policy_violations,
        "manifest_ref": "manifest.json",
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

    # Persist stable outputs under results/{repoId}/analysis/{run_id}
    out_dir = Path("results") / repo_id / "analysis" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff_bundle.json").write_text(json.dumps(diff_bundle, indent=2), encoding="utf-8")
    (out_dir / "feature_summary.json").write_text(json.dumps(feature_summary, indent=2), encoding="utf-8")
    (out_dir / "dry_run.json").write_text(json.dumps(report["dry_run"], indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.sarif.json").write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    # minimal manifest
    manifest = {
        "schema_version": "1.0",
        "repo_id": repo_id,
        "run_id": run_id,
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "budgets": {"root": 4000, "dir": 3000},
        "base_dir": base_dir,
        "head_dir": head_dir,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    extra = {"shadow_diff_root": str(shadow_diff_root)} if 'shadow_diff_root' in locals() else {}
    return jsonify({"ok": True, "report": report, "output_dir": str(out_dir), **extra}), 200


