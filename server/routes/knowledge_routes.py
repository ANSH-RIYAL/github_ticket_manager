from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from server.services.knowledge_service import generate_repo_knowledge
from server.services.llm_service import build_repo_doc_llm


knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.post("/generate_knowledge")
def generate_knowledge_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    repo_dir = payload.get("repo_dir")
    if not repo_dir or not os.path.isdir(repo_dir):
        return jsonify({"ok": False, "error": "Invalid repo_dir"}), 400

    # repo_id: use folder name
    repo_id = Path(repo_dir).name
    out_dir = Path("results") / repo_id / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = generate_repo_knowledge(repo_dir=repo_dir, out_dir=str(out_dir))
    # LLM post-process repo.json
    try:
        structure_doc = json.loads((out_dir / "structure.json").read_text(encoding="utf-8"))
        repo_doc = build_repo_doc_llm(structure_doc)
        if repo_doc and isinstance(repo_doc, dict):
            (out_dir / "repo.json").write_text(json.dumps(repo_doc, indent=2), encoding="utf-8")
    except Exception:
        pass
    return jsonify({"ok": True, "artifacts": artifacts, "out_dir": str(out_dir)}), 200


