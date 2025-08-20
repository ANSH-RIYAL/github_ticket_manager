from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, List


def _infer_structure(repo_dir: str) -> Dict[str, Any]:
    root = Path(repo_dir)
    entries = []

    def describe_dir(p: Path, max_children: int = 10) -> Dict[str, Any]:
        children = list(p.iterdir()) if p.exists() else []
        item = {
            "name": p.name,
            "type": "dir",
            "children_count": len(children),
        }
        sample = []
        for c in children[:max_children]:
            if c.is_dir():
                sample.append({"name": c.name, "type": "dir"})
            else:
                sample.append({"name": c.name, "type": "file", "ext": c.suffix})
        if sample:
            item["sample"] = sample
        return item

    for name in ["src", "test", "scripts", "docs", "examples"]:
        p = root / name
        if p.exists():
            entries.append(describe_dir(p))

    return {"schema_version": "1.0", "root": "/", "tree": entries}


def _infer_repo(repo_dir: str) -> Dict[str, Any]:
    # Conservative defaults tailored for date-fns-like repo
    return {
        "schema_version": "1.0",
        "repo": {
            "name": Path(repo_dir).name,
            "default_branch": "main",
            "language_primary": "TypeScript",
            "package_manager": "pnpm",
        },
        "entry_points": [{"type": "library", "path": "src/index.ts"}],
        "build": {"commands": ["pnpm -w run types"]},
        "test": {"commands": []},
        "layers": [
            {"name": "library", "globs": ["src/**"]},
            {"name": "tests", "globs": ["test/**"]},
            {"name": "scripts", "globs": ["scripts/**"]},
            {"name": "docs", "globs": ["docs/**"]},
            {"name": "examples", "globs": ["examples/**"]},
        ],
        "scope_policy": {
            "allowed_change_globs": [],
            "disallowed_change_globs": ["docs/**", "examples/**", "scripts/**"],
        },
    }


def _infer_api_surface(repo_dir: str) -> Dict[str, Any]:
    # Heuristic: parse src/index.ts re-exports lines like: export * from "./addDays/index.ts";
    exports: List[Dict[str, Any]] = []
    index_path = Path(repo_dir) / "src" / "index.ts"
    if index_path.exists():
        try:
            text = index_path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("export * from \"") and line.endswith("\";"):
                    inner = line[len("export * from \"") : -2]
                    # compute a rough symbol from folder name
                    parts = inner.split("/")
                    if len(parts) >= 2:
                        folder = parts[-2]
                        symbol = folder
                        exports.append({"symbol": symbol, "from": f"{inner}", "kind": "function"})
        except Exception:
            pass

    return {"schema_version": "1.0", "exports": exports}


def _infer_deps(repo_dir: str) -> Dict[str, Any]:
    # Minimal file-level import scan in src/** for TypeScript
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    src_root = Path(repo_dir) / "src"
    if not src_root.exists():
        return {"schema_version": "1.0", "nodes": nodes, "edges": edges}

    for path in src_root.rglob("*.ts"):
        rel = path.relative_to(Path(repo_dir)).as_posix()
        nodes.append({"id": rel, "layer": "library"})
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("import ") and " from \"" in line_s and line_s.endswith("\""):
                try:
                    mod = line_s.split(" from \"")[-1][:-1]
                except Exception:
                    continue
                if mod.startswith("./") or mod.startswith("../"):
                    target = (path.parent / (mod + (".ts" if not mod.endswith(".ts") else ""))).resolve()
                    if target.exists():
                        try:
                            target_rel = target.relative_to(Path(repo_dir)).as_posix()
                            edges.append({"from": rel, "to": target_rel})
                        except Exception:
                            pass

    return {"schema_version": "1.0", "nodes": nodes, "edges": edges}


def _rules() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "rules": [
            {
                "id": "NO_IMPORT_FROM_TESTS_001",
                "level": "error",
                "type": "forbid_import",
                "from_globs": ["src/**"],
                "to_globs": ["test/**"],
            },
            {
                "id": "NO_SUBMODULE_OR_TMP_002",
                "level": "error",
                "type": "forbid_import",
                "from_globs": ["**"],
                "to_globs": ["submodules/**", "tmp/**"],
            },
            {
                "id": "ENTRYPOINT_DECLARATION_003",
                "level": "warn",
                "type": "presence",
                "required_entrypoint": "src/index.ts",
            },
        ],
    }


def _profile() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "weights": {
            "ticket_alignment": 0.5,
            "structure_compliance": 0.35,
            "conventions": 0.15,
        },
        "blockers": ["NO_IMPORT_FROM_TESTS_001", "unmet_acceptance_criteria"],
        "risk_thresholds": {
            "high": "score < 60 or any blocker present",
            "medium": "60 <= score < 80 and no blockers",
            "low": "score >= 80 and no blockers",
        },
    }


def generate_repo_knowledge(repo_dir: str, out_dir: str) -> List[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    repo = _infer_repo(repo_dir)
    structure = _infer_structure(repo_dir)
    api_surface = _infer_api_surface(repo_dir)
    deps = _infer_deps(repo_dir)
    rules = _rules()
    profile = _profile()

    artifacts = {
        "repo.json": repo,
        "structure.json": structure,
        "api_surface.json": api_surface,
        "deps.json": deps,
        "rules.json": rules,
        "profile.json": profile,
    }
    for name, data in artifacts.items():
        (out / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return list(artifacts.keys())


def load_knowledge_bundle(knowledge_dir: str) -> Dict[str, Any]:
    base = Path(knowledge_dir)
    files = [
        "repo.json",
        "structure.json",
        "api_surface.json",
        "deps.json",
        "rules.json",
        "profile.json",
    ]
    bundle: Dict[str, Any] = {}
    for f in files:
        p = base / f
        if p.exists():
            bundle[f.split(".")[0]] = json.loads(p.read_text(encoding="utf-8"))
        else:
            bundle[f.split(".")[0]] = {}
    return bundle


