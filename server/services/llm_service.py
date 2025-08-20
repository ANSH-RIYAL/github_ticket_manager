from __future__ import annotations

import os
from typing import Dict, Any
import json
import os
import urllib.request
import urllib.error


def evaluate_ticket_alignment(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return _heuristic_alignment(ticket, diff_bundle)

    # Model call with strict IO
    system = "ONLY_OUTPUT valid JSON per schema. Validate PR diff against ticket acceptance criteria. Be evidence-based; if unsure, mark unmet."
    user_payload = {"schema_version": "1.0", "ticket": ticket.get("ticket", {}), "diff_bundle": diff_bundle}
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
        # normalize to expected fields
        if "ticket_alignment" not in parsed:
            return _heuristic_alignment(ticket, diff_bundle)
        return parsed
    except Exception:
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


def scope_guard_llm(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON. Determine out_of_scope_files by comparing ticket.expected_change_scope.files_glob and out_of_scope_glob to diff files."
    )
    inp = {"schema_version": "1.0", "ticket": ticket.get("ticket", {}), "diff_bundle": diff_bundle}
    out = _openai_chat(system, inp)
    if out and "out_of_scope_files" in out:
        return {"out_of_scope_files": sorted(set(out.get("out_of_scope_files", []))) }
    # fallback heuristic
    from .guards import ScopeGuard as _SG  # type: ignore
    return _SG.run(ticket, diff_bundle)


def rule_guard_llm(rules: Dict[str, Any], diff_bundle: Dict[str, Any], deps: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON with {\"violations\": [{\"rule_id\",\"file\",\"evidence\",\"severity\"}]}. "
        "Evaluate rules against changed files and deps graph; be conservative and include evidence."
    )
    inp = {"schema_version": "1.0", "rules": rules, "diff_bundle": diff_bundle, "deps": deps}
    out = _openai_chat(system, inp)
    if out and "violations" in out:
        return {"violations": out.get("violations", [])}
    from .guards import RuleGuard as _RG  # type: ignore
    return _RG.run(rules, diff_bundle, deps)


def impact_guard_llm(api: Dict[str, Any], deps: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "ONLY_OUTPUT valid JSON with keys changed_exports, signature_changes, possibly_impacted. "
        "Use api.exports, deps graph, and diff hunks to infer changes to exported symbols and affected dependents."
    )
    inp = {"schema_version": "1.0", "api_surface": api, "deps": deps, "diff_bundle": diff_bundle}
    out = _openai_chat(system, inp)
    if out and all(k in out for k in ("changed_exports", "signature_changes", "possibly_impacted")):
        return {
            "changed_exports": sorted(set(out.get("changed_exports", []))),
            "signature_changes": sorted(set(out.get("signature_changes", []))),
            "possibly_impacted": sorted(set(out.get("possibly_impacted", []))),
        }
    from .guards import ImpactGuard as _IG  # type: ignore
    return _IG.run(api, deps, diff_bundle)


def build_repo_doc_llm(structure_doc: Dict[str, Any]) -> Dict[str, Any] | None:
    system = (
        "ONLY_OUTPUT valid JSON for repo.json with keys {schema_version, repo{name,default_branch,language_primary,package_manager}, "
        "entry_points, build.commands, test.commands, layers, scope_policy}. Infer conservatively from provided structure."
    )
    inp = {"schema_version": "1.0", "structure": structure_doc}
    out = _openai_chat(system, inp)
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


