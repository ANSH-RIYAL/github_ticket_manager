from __future__ import annotations

import re
from typing import Dict, Any, List, Tuple


CODE_GLOBS = (
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".jsx",
    ".py",
    ".go",
    ".rs",
)


def _is_code_file(path: str) -> bool:
    return any(path.endswith(ext) for ext in CODE_GLOBS)


def _is_docs(path: str) -> bool:
    return path.startswith("docs/") or "/docs/" in path


def _is_tests(path: str) -> bool:
    lowered = path.lower()
    return (
        "/__tests__/" in lowered
        or lowered.endswith(".test.ts")
        or lowered.endswith(".spec.ts")
        or lowered.endswith(".test.js")
        or lowered.endswith(".spec.js")
    )


def _is_scripts(path: str) -> bool:
    return path.startswith("scripts/") or path.endswith(".sh")


def _is_config_file(path: str) -> bool:
    base = path.split("/")[-1]
    return base in {
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        ".env",
        ".env.example",
        "docker-compose.yml",
        "compose.yml",
        "Dockerfile",
    }


def _count_hunk_lines(hunks: List[Dict[str, Any]]) -> Tuple[int, int]:
    added = 0
    removed = 0
    for h in hunks or []:
        for line in (h.get("text") or "").splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    return added, removed


def _detect_port_changes(hunks: List[Dict[str, Any]]) -> bool:
    pat = re.compile(r"(PORT\s*=\s*\d+|port\s*[:=]\s*\d+)")
    for h in hunks or []:
        for line in (h.get("text") or "").splitlines():
            if line.startswith("+") or line.startswith("-"):
                if pat.search(line):
                    return True
    return False


def build_feature_summary(ticket: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    files = diff_bundle.get("files", [])
    code_changed = 0
    noncode_changed = 0
    docs_changed = 0
    tests_changed = 0
    scripts_changed = 0
    config_drift: List[str] = []
    total_added = 0
    total_removed = 0

    for f in files:
        path = f.get("path") or ""
        hunks = f.get("hunks", [])
        a, r = _count_hunk_lines(hunks)
        total_added += a
        total_removed += r

        if _is_docs(path):
            docs_changed += 1
        if _is_tests(path):
            tests_changed += 1
        if _is_scripts(path):
            scripts_changed += 1
        if _is_config_file(path) or _detect_port_changes(hunks):
            config_drift.append(path or "<unknown>")

        if _is_code_file(path):
            code_changed += 1
        else:
            noncode_changed += 1

    churn = total_added + total_removed
    ratio = float(code_changed) / float(max(1, (code_changed + noncode_changed)))

    return {
        "schema_version": "1.0",
        "files_changed": len(files),
        "code_files_changed": code_changed,
        "noncode_files_changed": noncode_changed,
        "code_to_noncode_ratio": round(ratio, 3),
        "docs_changed": docs_changed,
        "tests_changed": tests_changed,
        "scripts_changed": scripts_changed,
        "config_drift": sorted(set(config_drift)),
        "added_lines": total_added,
        "removed_lines": total_removed,
        "churn": churn,
    }


_EXPORT_RE = re.compile(r"\bexport\s+(?:function|const|class|interface|type)\s+([A-Za-z0-9_]+)")


def static_dry_run(api_surface: Dict[str, Any], deps: Dict[str, Any], diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    changed_files = [f.get("path") for f in diff_bundle.get("files", []) if f.get("path")]
    symbols_added: List[str] = []
    symbols_removed: List[str] = []
    signature_changes: List[str] = []

    for f in diff_bundle.get("files", []):
        path = f.get("path") or ""
        for h in f.get("hunks", []) or []:
            text = h.get("text") or ""
            for line in text.splitlines():
                if line.startswith("+"):
                    m = _EXPORT_RE.search(line)
                    if m:
                        symbols_added.append(f"{path}#${m.group(1)}")
                    if ("export function" in line or "export interface" in line or line.strip().startswith("type ")):
                        signature_changes.append(path)
                elif line.startswith("-"):
                    m = _EXPORT_RE.search(line)
                    if m:
                        symbols_removed.append(f"{path}#${m.group(1)}")

    # reverse deps: who depends on changed files
    rev: Dict[str, List[str]] = {}
    for e in deps.get("edges", []):
        rev.setdefault(e.get("to"), []).append(e.get("from"))
    callers = sorted(set([c for p in changed_files for c in rev.get(p, [])]))

    return {
        "schema_version": "1.0",
        "symbols_touched": {
            "added": sorted(set(symbols_added)),
            "removed": sorted(set(symbols_removed)),
        },
        "signature_deltas": sorted(set(signature_changes)),
        "callers": callers,
        "config_drift": [],
        "notes": "static only; no execution",
    }


