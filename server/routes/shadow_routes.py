from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from server.services.diff_service import compute_local_diff
from server.services.shadow_fs_service import (
    build_shadow_knowledge,
    build_shadow_diff,
    get_dir_context,
)
from server.services.policy_service import evaluate_policies, load_policies
from server.services.sarif_service import build_sarif


shadow_bp = Blueprint("shadow", __name__)


@shadow_bp.post("/shadow/init")
def shadow_init_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    repo_dir = payload.get("repo_dir")
    if not repo_dir or not os.path.isdir(repo_dir):
        return jsonify({"ok": False, "error": "Invalid repo_dir"}), 400

    repo_id = Path(repo_dir).name
    out_dir = Path("results") / repo_id / "shadow"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = build_shadow_knowledge(repo_dir=repo_dir, out_dir=str(out_dir))
    return jsonify({"ok": True, "repo_id": repo_id, "shadow_root": str(out_dir), "summary": summary}), 200


@shadow_bp.post("/shadow/diff")
def shadow_diff_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    base_dir = payload.get("base_dir")
    head_dir = payload.get("head_dir")
    if not base_dir or not os.path.isdir(base_dir):
        return jsonify({"ok": False, "error": "Invalid base_dir"}), 400
    if not head_dir or not os.path.isdir(head_dir):
        return jsonify({"ok": False, "error": "Invalid head_dir"}), 400

    repo_id = Path(base_dir).name
    diff_bundle = compute_local_diff(base_dir=base_dir, head_dir=head_dir, include_context=False)
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("results") / repo_id / "shadow_diff" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "diff_bundle.json").write_text(json.dumps(diff_bundle, indent=2), encoding="utf-8")
    index = build_shadow_diff(base_dir=base_dir, head_dir=head_dir, diff_bundle=diff_bundle, shadow_root=str(out_dir))

    return jsonify({
        "ok": True,
        "repo_id": repo_id,
        "run_id": run_id,
        "shadow_diff_root": str(out_dir),
        "index": index,
    }), 200


@shadow_bp.get("/shadow/context")
def shadow_context_route():
    repo_id = request.args.get("repo_id", type=str)
    run_id = request.args.get("run_id", type=str)
    rel_path = request.args.get("rel_path", default="", type=str)
    budget = request.args.get("budget", default=3000, type=int)
    include_diff = request.args.get("include_diff", default=1, type=int) == 1
    if not repo_id:
        return jsonify({"ok": False, "error": "repo_id required"}), 400
    shadow_root = Path("results") / repo_id / ("shadow_diff" if run_id else "shadow")
    if run_id:
        shadow_root = shadow_root / run_id
    if not shadow_root.exists():
        return jsonify({"ok": False, "error": "shadow root not found"}), 404

    ctx = get_dir_context(shadow_root=str(shadow_root), rel_path=rel_path, include_diff=include_diff, budget=budget)
    return jsonify({"ok": True, "context": ctx}), 200


@shadow_bp.post("/shadow/file_content")
def shadow_file_content_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    repo_id = payload.get("repo_id")
    run_id = payload.get("run_id")
    rel_path = payload.get("rel_path", "")
    where = payload.get("where", "head")
    max_bytes = int(payload.get("max_bytes", 4000))
    if not repo_id:
        return jsonify({"ok": False, "error": "repo_id required"}), 400
    base = Path("results") / repo_id / ("shadow_diff" if run_id else "shadow")
    if run_id:
        base = base / run_id
    # Fetch from shadow diff context: for simplicity, read the head file under the real head_dir is not stored; this endpoint is a placeholder to be extended with base/head paths in manifest.
    # For now, return from shadow context if context captured excerpts (future: include base/head roots in manifest and resolve here).
    try:
        d = base if rel_path == "" else (base / rel_path)
        meta = {}
        if (d / "_dir.diff.json").exists():
            meta = json.loads((d / "_dir.diff.json").read_text(encoding="utf-8"))
        # Not storing file bodies; return empty with guidance
        return jsonify({"ok": True, "content": "", "truncated": False, "note": "file bodies not stored; extend manifest to resolve base/head paths"}), 200
    except Exception:
        return jsonify({"ok": False, "error": "unavailable"}), 500


@shadow_bp.post("/policy/evaluate")
def policy_evaluate_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    report = payload.get("report", {})
    policies_path = payload.get("policies_path")
    policies = payload.get("policies") or load_policies(policies_path)
    violations = evaluate_policies(report, policies)
    sarif = build_sarif(report, violations)
    return jsonify({"ok": True, "policy_violations": violations, "sarif": sarif}), 200


