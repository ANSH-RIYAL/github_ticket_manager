from __future__ import annotations

from fnmatch import fnmatch
from typing import Dict, Any, List


class ScopeGuard:
    @staticmethod
    def run(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
        out_of_scope: List[str] = []
        scope = (ticket or {}).get("ticket", {}).get("expected_change_scope", {})
        allowed = scope.get("files_glob", [])
        out_globs = (ticket or {}).get("ticket", {}).get("out_of_scope_glob", [])

        changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]

        def is_allowed(p: str) -> bool:
            if not allowed:
                return True
            return any(fnmatch(p, g) for g in allowed)

        for p in changed_files:
            if any(fnmatch(p, g) for g in out_globs):
                out_of_scope.append(p)
            elif not is_allowed(p):
                out_of_scope.append(p)

        return {"out_of_scope_files": sorted(set(out_of_scope))}


class RuleGuard:
    @staticmethod
    def run(rules: Dict[str, Any], diff_bundle: Dict[str, Any], deps: Dict[str, Any]) -> Dict[str, Any]:
        violations: List[Dict[str, Any]] = []
        rule_list = (rules or {}).get("rules", [])
        files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]

        for rule in rule_list:
            rtype = rule.get("type")
            rid = rule.get("id")
            level = rule.get("level", "warn")
            if rtype == "presence" and rule.get("required_entrypoint"):
                # Presence is repo-level; only warn if missing in repo.json (not available here). Skip in PR.
                continue
            if rtype == "forbid_import":
                # Simple path-based guard: flag any changes in forbidden targets to keep PR scope safe.
                to_globs = rule.get("to_globs", [])
                for p in files:
                    if any(fnmatch(p, g) for g in to_globs):
                        violations.append({
                            "rule_id": rid,
                            "file": p,
                            "evidence": f"changed forbidden path pattern {to_globs}",
                            "severity": level,
                        })
        return {"violations": violations}


class ImpactGuard:
    @staticmethod
    def run(api: Dict[str, Any], deps: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
        api_exports = {(e.get("from"), e.get("symbol")) for e in (api or {}).get("exports", [])}
        changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]

        changed_exports: List[str] = []
        for (path, symbol) in api_exports:
            if path in changed_files:
                changed_exports.append(symbol)

        # naive signature change detection: check for lines starting with '+' that change function signature keywords
        signature_changes: List[str] = []
        for f in diff_bundle.get("files", []):
            path = f.get("path")
            for h in f.get("hunks", []):
                text = h.get("text", "")
                for line in text.splitlines():
                    if line.startswith("+") and ("export function" in line or "export interface" in line or "type " in line):
                        signature_changes.append(path)
                        break

        # impacted via reverse deps
        rev: Dict[str, List[str]] = {}
        for e in deps.get("edges", []):
            rev.setdefault(e["to"], []).append(e["from"])
        possibly_impacted = sorted(set([d for c in changed_files for d in rev.get(c, [])]))

        return {
            "changed_exports": sorted(set(changed_exports)),
            "signature_changes": sorted(set(signature_changes)),
            "possibly_impacted": possibly_impacted,
        }


