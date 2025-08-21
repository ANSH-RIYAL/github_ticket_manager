from __future__ import annotations

import os
from typing import Dict, Any
import json
import os
import urllib.request
import urllib.error


def _slim_diff(diff_bundle: Dict[str, Any], max_hunk_chars: int = 2000, files_only: bool = False) -> Dict[str, Any]:
    files = []
    total = 0
    for f in diff_bundle.get("files", []):
        entry = {"path": f.get("path"), "status": f.get("status"), "old_path": f.get("old_path")}
        if not files_only:
            hunks = []
            for h in f.get("hunks", []):
                text = h.get("text", "")
                take = max_hunk_chars - total
                if take <= 0:
                    break
                trimmed = text[:take]
                total += len(trimmed)
                hunks.append({
                    "meta": h.get("meta"),
                    "old_start": h.get("old_start"),
                    "old_lines": h.get("old_lines"),
                    "new_start": h.get("new_start"),
                    "new_lines": h.get("new_lines"),
                    "text": trimmed,
                })
            entry["hunks"] = hunks
        files.append(entry)
        if total >= max_hunk_chars:
            break
    return {"schema_version": diff_bundle.get("schema_version", "1.0"), "files": files}


def _log_prompt(name: str, system: str, user_obj: Dict[str, Any], response_obj: Dict[str, Any] | None, error: str | None = None) -> None:
    try:
        from pathlib import Path
        import json as _json
        d = Path("prompt_performance")
        d.mkdir(parents=True, exist_ok=True)
        payload = {"system": system, "input": user_obj, "output": response_obj, "error": error}
        (d / f"last_{name}.json").write_text(_json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def evaluate_ticket_alignment(ticket: Dict[str, Any], diff_bundle: Dict[str, Any], feature_summary: Dict[str, Any] | None = None, dry_run: Dict[str, Any] | None = None) -> Dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return _heuristic_alignment(ticket, diff_bundle)

    # Model call with strict IO, per-criterion evidence requirement
    system = (
        "ONLY_OUTPUT valid JSON with {\"schema_version\":\"1.0\", \"ticket_alignment\":{\"matched\":[],\"unmet\":[],\"evidence\":[]}}. "
        "For each acceptance criterion, decide matched/unmet using diff hunks plus structural evidence. "
        "Require mapping each matched AC to either (a) semantic deltas (likely_replacements or calls_added) or (b) AST deltas (exports/signature), or (c) explicit caller paths from dry_run.callers. "
        "If no structural evidence exists, mark AC unmet. Be conservative."
    )
    slim = _slim_diff(diff_bundle, max_hunk_chars=3000)
    user_payload = {"schema_version": "1.0", "ticket": ticket.get("ticket", {}), "diff": slim, "feature_summary": feature_summary or {}, "dry_run": dry_run or {}}
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        _log_prompt("ticket_alignment", system, user_payload, parsed)
        # normalize to expected fields
        if "ticket_alignment" not in parsed:
            return _heuristic_alignment(ticket, diff_bundle)
        return parsed
    except Exception as e:
        _log_prompt("ticket_alignment", system, user_payload, None, error=str(e))
        return _heuristic_alignment(ticket, diff_bundle)


def _heuristic_alignment(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    ac = ticket.get("ticket", {}).get("acceptance_criteria", [])
    matched = []
    evidence = []
    scope = ticket.get("ticket", {}).get("expected_change_scope", {})
    allowed = scope.get("files_glob", [])
    changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]
    in_scope = []
    if allowed:
        for p in changed_files:
            for g in allowed:
                from fnmatch import fnmatch
                if fnmatch(p, g):
                    in_scope.append(p)
                    break
    matched_ids = [c.get("id") for c in ac[:1]] if in_scope else []
    if matched_ids:
        matched = matched_ids
        evidence.append({"ac_id": matched_ids[0], "files": sorted(set(in_scope)), "hunks": []})
    return {
        "schema_version": "1.0",
        "ticket_alignment": {
            "matched": matched,
            "unmet": [c.get("id") for c in ac if c.get("id") not in matched],
            "evidence": evidence,
        },
        "notes": "heuristic alignment",
    }


def _openai_chat(system: str, user_obj: Dict[str, Any]) -> Dict[str, Any] | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }
    try:
        req = urllib.request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None


# Legacy global LLM guards removed; shadow-scoped prompts are used instead.


def build_repo_doc_llm(structure_doc: Dict[str, Any]) -> Dict[str, Any] | None:
    system = (
        "ONLY_OUTPUT valid JSON for repo.json with keys {schema_version, repo{name,default_branch,language_primary,package_manager}, "
        "entry_points, build.commands, test.commands, layers, scope_policy}. Infer conservatively from provided structure."
    )
    inp = {"schema_version": "1.0", "structure": structure_doc}
    out = _openai_chat(system, inp)
    _log_prompt("repo_postprocess", system, inp, out)
    return out


def refine_ticket_llm(freeform_text: str, structure: Dict[str, Any] | None = None, api_surface: Dict[str, Any] | None = None) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON per the ticket schema with keys {schema_version, ticket{ id, title, summary, acceptance_criteria[], expected_change_scope{files_glob,modules}, out_of_scope_glob, labels, links }}. "
        "Be concise and testable. Suggest files_glob using structure tree and api exports when present."
    )
    user = {
        "schema_version": "1.0",
        "freeform": freeform_text,
        "structure": structure or {},
        "api_surface": api_surface or {},
    }
    out = _openai_chat(system, user)
    _log_prompt("ticket_propose", system, user, out)
    if out and "ticket" in out:
        return out
    # fallback minimal ticket
    return {
        "schema_version": "1.0",
        "ticket": {
            "id": "T-DRAFT",
            "title": freeform_text.split("\n")[0][:80],
            "summary": freeform_text[:240],
            "acceptance_criteria": [{"id": "AC-1", "text": freeform_text[:120], "verification": "manual"}],
            "expected_change_scope": {"files_glob": [], "modules": []},
            "out_of_scope_glob": ["docs/**", "examples/**", "scripts/**"],
            "labels": [],
            "links": [],
        },
    }


def ticket_alignment_shadow(ticket: Dict[str, Any], dir_context: Dict[str, Any], global_summary: Dict[str, Any] | None = None) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON with {\"schema_version\":\"1.0\", \"ticket_alignment\":{\"matched\":[],\"unmet\":[],\"evidence\":[]}}. "
        "Use dir_context.meta/files, dir_context.diff.hunks, and dir_context.api_exports/deps_subgraph. "
        "If structural evidence for an AC is absent in this subtree, leave it unmet unless explicitly proven in global_summary. Be conservative."
    )
    user_payload = {
        "schema_version": "1.0",
        "ticket": ticket.get("ticket", {}),
        "dir_context": dir_context,
        "global_summary": global_summary or {},
    }
    out = _openai_chat(system, user_payload)
    _log_prompt("ticket_alignment_shadow", system, user_payload, out)
    if out and "ticket_alignment" in out:
        return out
    return {
        "schema_version": "1.0",
        "ticket_alignment": {"matched": [], "unmet": [c.get("id") for c in ticket.get("ticket", {}).get("acceptance_criteria", [])], "evidence": []},
        "notes": "shadow_fallback"
    }


def impact_guard_shadow(dir_context: Dict[str, Any], feature_summary: Dict[str, Any] | None = None, dry_run: Dict[str, Any] | None = None) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON: {\"changed_exports\":[],\"signature_changes\":[],\"possibly_impacted\":[]}. "
        "Use dir_context.diff.hunks + dir_context.api_exports + dir_context.deps_subgraph. Limit reasoning to this subtree."
    )
    user_payload = {
        "schema_version": "1.0",
        "dir_context": dir_context,
        "feature_summary": feature_summary or {},
        "dry_run": dry_run or {},
    }
    out = _openai_chat(system, user_payload)
    _log_prompt("impact_guard_shadow", system, user_payload, out)
    if out and all(k in out for k in ("changed_exports", "signature_changes", "possibly_impacted")):
        return {
            "changed_exports": out.get("changed_exports", []),
            "signature_changes": out.get("signature_changes", []),
            "possibly_impacted": out.get("possibly_impacted", []),
        }
    # fallback to empty impact for the subtree
    return {"changed_exports": [], "signature_changes": [], "possibly_impacted": []}

