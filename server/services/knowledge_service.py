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
    # Parse src/index.ts re-exports and discover symbol names from each module file
    exports: List[Dict[str, Any]] = []
    src_root = Path(repo_dir) / "src"
    index_path = src_root / "index.ts"
    reexport_targets: List[str] = []
    if index_path.exists():
        try:
            text = index_path.read_text(encoding="utf-8", errors="ignore")
            for raw in text.splitlines():
                line = raw.strip()
                # export * from "./addDays/index.ts";
                if line.startswith("export * from \"") and line.endswith("\";"):
                    inner = line[len("export * from \"") : -2]
                    reexport_targets.append(inner)
                # export type * from "./types.ts";
                if line.startswith("export type * from \"") and line.endswith("\";"):
                    inner = line[len("export type * from \"") : -2]
                    reexport_targets.append(inner)
        except Exception:
            pass

    def classify_and_symbols(module_path: Path) -> List[Dict[str, Any]]:
        try:
            text = module_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        found: List[Dict[str, Any]] = []
        for raw in text.splitlines():
            line = raw.strip()
            # function exports
            if line.startswith("export function "):
                name = line.split()[2].split("(")[0]
                found.append({"symbol": name, "kind": "function"})
            # const exports
            elif line.startswith("export const "):
                name = line.split()[2].split("=")[0]
                found.append({"symbol": name, "kind": "const"})
            # type/interface exports
            elif line.startswith("export interface "):
                name = line.split()[2].split("{")[0]
                found.append({"symbol": name, "kind": "type"})
            elif line.startswith("export type "):
                # export type Foo = ...
                parts = line[len("export type "):].split("=")[0].strip()
                if parts:
                    name = parts.split()[0]
                    found.append({"symbol": name, "kind": "type"})
        return found

    for inner in reexport_targets:
        mod_rel = inner if inner.endswith(".ts") else f"{inner}.ts"
        module_path = (src_root / Path(mod_rel))
        if module_path.exists():
            symbols = classify_and_symbols(module_path)
            for s in symbols:
                exports.append({"symbol": s["symbol"], "from": inner, "kind": s["kind"]})
        else:
            # try index.ts resolution if path points to directory
            alt = src_root / inner / "index.ts"
            if alt.exists():
                symbols = classify_and_symbols(alt)
                for s in symbols:
                    exports.append({"symbol": s["symbol"], "from": f"{inner}/index.ts", "kind": s["kind"]})

    return {"schema_version": "1.0", "exports": exports}


def _infer_deps(repo_dir: str) -> Dict[str, Any]:
    # Robust-ish file-level import scan in src/** for TypeScript
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    src_root = Path(repo_dir) / "src"
    if not src_root.exists():
        return {"schema_version": "1.0", "nodes": nodes, "edges": edges}

    all_files = list(src_root.rglob("*.ts"))
    for path in all_files:
        rel = path.relative_to(Path(repo_dir)).as_posix()
        nodes.append({"id": rel, "layer": "library"})
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for raw in text.splitlines():
            line_s = raw.strip()
            if not line_s.startswith("import "):
                continue
            # Handle: import ... from "..." | '...'
            mod = None
            if " from \"" in line_s:
                mod = line_s.split(" from \"")[-1]
                if mod.endswith("\""):
                    mod = mod[:-1]
            elif " from '\"" in line_s:
                # defensive; unlikely
                pass
            elif " from '" in line_s:
                mod = line_s.split(" from '")[-1]
                if mod.endswith("'"):
                    mod = mod[:-1]
            else:
                # bare import like: import "./polyfill";
                if line_s.endswith(";") and ("\"" in line_s or "'" in line_s):
                    q = "\"" if "\"" in line_s else "'"
                    try:
                        mod = line_s.split(q)[1]
                    except Exception:
                        mod = None
            if not mod:
                continue
            if not (mod.startswith("./") or mod.startswith("../")):
                continue
            # Resolve to candidate targets
            candidates = []
            base = path.parent / mod
            candidates.append(base)
            candidates.append(Path(str(base) + ".ts"))
            candidates.append(base / "index.ts")
            for t in candidates:
                if t.exists():
                    try:
                        target_rel = t.resolve().relative_to(Path(repo_dir)).as_posix()
                        edges.append({"from": rel, "to": target_rel})
                        break
                    except Exception:
                        continue

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
            "ticket_alignment": 0.6,
            "structure_compliance": 0.4,
            "conventions": 0.0,
        },
        "blockers": ["NO_IMPORT_FROM_TESTS_001"],
        "risk_thresholds": {
            "high": "score < 40 or any blocker present",
            "medium": "40 <= score < 70 and no blockers",
            "low": "score >= 70 and no blockers",
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


