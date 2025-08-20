from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from server.services.llm_service import refine_ticket_llm
from server.services.knowledge_service import load_knowledge_bundle


ticket_bp = Blueprint("ticket", __name__)


@ticket_bp.post("/ticket/propose")
def propose_ticket_route():
    payload: Dict[str, Any] = request.get_json(force=True, silent=False)
    repo_dir = payload.get("repo_dir")
    freeform = payload.get("freeform_text", "").strip()
    if not freeform:
        return jsonify({"ok": False, "error": "freeform_text required"}), 400

    repo_id = Path(repo_dir).name if repo_dir else None
    structure = None
    api_surface = None
    if repo_id:
        knowledge_dir = Path("results") / repo_id / "knowledge"
        bundle = load_knowledge_bundle(str(knowledge_dir))
        structure = bundle.get("structure")
        api_surface = bundle.get("api_surface")

    ticket = refine_ticket_llm(freeform, structure=structure, api_surface=api_surface)
    return jsonify({"ok": True, "ticket": ticket}), 200


