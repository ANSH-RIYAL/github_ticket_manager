from __future__ import annotations

import re
from typing import Dict, Any, List, Tuple, Set


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


def _extract_calls_from_hunks(hunks: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    call_pat = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    method_pat = re.compile(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    added: Dict[str, int] = {}
    removed: Dict[str, int] = {}
    for h in hunks or []:
        text = h.get("text") or ""
        for line in text.splitlines():
            if line.startswith("+"):
                for m in call_pat.findall(line):
                    added[m] = added.get(m, 0) + 1
                for m in method_pat.findall(line):
                    added[m] = added.get(m, 0) + 1
            elif line.startswith("-"):
                for m in call_pat.findall(line):
                    removed[m] = removed.get(m, 0) + 1
                for m in method_pat.findall(line):
                    removed[m] = removed.get(m, 0) + 1
    return added, removed


def _compute_semantic_deltas(diff_bundle: Dict[str, Any]) -> Dict[str, Any]:
    total_added: Dict[str, int] = {}
    total_removed: Dict[str, int] = {}
    for f in diff_bundle.get("files", []):
        # only analyze code files for semantics
        path = f.get("path") or ""
        if not _is_code_file(path):
            continue
        hunks = f.get("hunks", [])
        a, r = _extract_calls_from_hunks(hunks)
        for k, v in a.items():
            total_added[k] = total_added.get(k, 0) + v
        for k, v in r.items():
            total_removed[k] = total_removed.get(k, 0) + v
    # identify likely replacements: call reduced in removed and increased in added
    replacements: List[Dict[str, Any]] = []
    for rem_name, rem_cnt in total_removed.items():
        # naive: if there exists an added name with similar suffix/prefix or common roots, include pairs of interest
        for add_name, add_cnt in total_added.items():
            if rem_name != add_name and (rem_name.lower() in add_name.lower() or add_name.lower() in rem_name.lower()):
                replacements.append({"from": rem_name, "to": add_name, "removed": rem_cnt, "added": add_cnt})
    # compact output: top few entries
    def top_n(d: Dict[str, int], n: int = 10) -> List[Dict[str, Any]]:
        return [{"name": k, "count": d[k]} for k in sorted(d.keys(), key=lambda x: -d[x])[:n]]
    return {
        "calls_added": top_n(total_added),
        "calls_removed": top_n(total_removed),
        "likely_replacements": replacements[:10],
    }


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

    # reverse deps: who depends on changed files (2-hop with caps)
    rev: Dict[str, List[str]] = {}
    for e in deps.get("edges", []):
        rev.setdefault(e.get("to"), []).append(e.get("from"))
    first_hop: Set[str] = set()
    for p in changed_files:
        first_hop.update(rev.get(p, []))
    second_hop: Set[str] = set()
    for n in list(first_hop)[:200]:
        second_hop.update(rev.get(n, []))
    callers = sorted(set(list(first_hop)[:200] + list(second_hop)[:200]))
    hop_truncated = len(first_hop) > 200 or len(second_hop) > 200

    semantic = _compute_semantic_deltas(diff_bundle)
    return {
        "schema_version": "1.0",
        "symbols_touched": {
            "added": sorted(set(symbols_added)),
            "removed": sorted(set(symbols_removed)),
        },
        "signature_deltas": sorted(set(signature_changes)),
        "callers": callers,
        "callers_2hop_truncated": hop_truncated,
        "config_drift": [],
        "semantic_deltas": semantic,
        "notes": "static only; no execution",
    }


