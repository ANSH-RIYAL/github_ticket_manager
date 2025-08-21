from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Set


MAX_NO_CHANGE_LIST = 500
MAX_HUNK_TEXT_PER_FILE = 4000


def _list_dir(local_root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    files: List[Dict[str, Any]] = []
    children: List[str] = []
    for entry in sorted(local_root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".git"):
            continue
        if entry.is_dir():
            children.append(entry.name)
        else:
            files.append({
                "name": entry.name,
                "size": entry.stat().st_size,
                "ext": entry.suffix,
            })
    return files, children


def _rel_to_repo(repo_dir: str, path: Path) -> str:
    return path.resolve().relative_to(Path(repo_dir).resolve()).as_posix()


def _gather_tree_dirs(repo_dir: str) -> List[str]:
    root = Path(repo_dir)
    dirs: List[str] = [""]
    for p in root.rglob("*"):
        if p.name.startswith(".git"):
            continue
        if p.is_dir():
            rel = _rel_to_repo(repo_dir, p)
            dirs.append(rel)
    return sorted(set(dirs))


def _prune_api_for_subtree(api_surface: Dict[str, Any], subtree: str) -> Dict[str, Any]:
    prefix = (subtree.rstrip("/") + "/") if subtree else ""
    exports = []
    for e in api_surface.get("exports", []):
        frm = e.get("from") or ""
        if not prefix or frm.startswith(prefix):
            exports.append(e)
    return {"schema_version": api_surface.get("schema_version", "1.0"), "exports": exports}


def _prune_deps_for_subtree(deps: Dict[str, Any], subtree: str) -> Dict[str, Any]:
    prefix = (subtree.rstrip("/") + "/") if subtree else ""
    nodes = []
    node_ids: Set[str] = set()
    for n in deps.get("nodes", []):
        nid = n.get("id")
        if not prefix or (nid and nid.startswith(prefix)):
            nodes.append(n)
            node_ids.add(nid)
    edges = []
    for e in deps.get("edges", []):
        frm = e.get("from")
        to = e.get("to")
        if (not prefix) or (frm and to and (frm.startswith(prefix) or to.startswith(prefix))):
            edges.append(e)
            if frm and frm not in node_ids:
                node_ids.add(frm)
                nodes.append({"id": frm, "layer": "library"})
            if to and to not in node_ids:
                node_ids.add(to)
                nodes.append({"id": to, "layer": "library"})
    return {"schema_version": deps.get("schema_version", "1.0"), "nodes": nodes, "edges": edges}


def build_shadow_knowledge(repo_dir: str, out_dir: str) -> Dict[str, Any]:
    """Construct a shadow knowledge tree with per-directory meta and pruned knowledge.
    Writes files to out_dir mirroring the directory layout.
    """
    # Load base knowledge artifacts if present (optional)
    from server.services.knowledge_service import generate_repo_knowledge, load_knowledge_bundle

    repo_id = Path(repo_dir).name
    # Ensure we have a knowledge bundle to prune from
    kb_dir = Path("results") / repo_id / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    if not (kb_dir / "api_surface.json").exists():
        generate_repo_knowledge(repo_dir=repo_dir, out_dir=str(kb_dir))
    bundle = load_knowledge_bundle(str(kb_dir))
    api_surface = bundle.get("api_surface", {"schema_version": "1.0", "exports": []})
    deps = bundle.get("deps", {"schema_version": "1.0", "nodes": [], "edges": []})

    root_out = Path(out_dir)
    root_out.mkdir(parents=True, exist_ok=True)
    root = Path(repo_dir)

    total_dirs = 0
    total_files = 0

    for rel in _gather_tree_dirs(repo_dir):
        total_dirs += 1
        real_dir = root if rel == "" else (root / rel)
        shadow_dir = root_out if rel == "" else (root_out / rel)
        shadow_dir.mkdir(parents=True, exist_ok=True)
        files, children = _list_dir(real_dir)
        total_files += len([f for f in files])

        # classify kinds for files
        for f in files:
            name = f.get("name", "").lower()
            kinds: List[str] = []
            if name.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".rs")):
                kinds.append("code")
            if name.endswith((".md", ".rst")) or name.startswith("readme"):
                kinds.append("docs")
            if name.endswith((".sh", ".bash")) or name.startswith("scripts/"):
                kinds.append("scripts")
            if name in {"package.json", "pnpm-lock.yaml", "yarn.lock", "requirements.txt", "pyproject.toml", ".env", ".env.example", "Dockerfile"}:
                kinds.append("config")
            f["kinds"] = kinds

        parent_meta = (".." + "/_dir.meta.json") if rel != "" else None
        children_meta = [
            {"name": c, "rel_path": (rel + "/" + c if rel else c), "meta": f"{c}/_dir.meta.json"}
            for c in children
        ]

        # write pruned knowledge for subtree
        subtree = rel
        api_pruned = _prune_api_for_subtree(api_surface, subtree)
        deps_pruned = _prune_deps_for_subtree(deps, subtree)
        (shadow_dir / "api_exports.json").write_text(json.dumps(api_pruned, indent=2), encoding="utf-8")
        (shadow_dir / "deps_subgraph.json").write_text(json.dumps(deps_pruned, indent=2), encoding="utf-8")

        meta = {
            "schema_version": "1.0",
            "dir_name": (real_dir.name if rel != "" else "root"),
            "rel_path": rel,
            "parent_meta": parent_meta,
            "children": children_meta,
            "files": files,
            "links": {
                "api_exports": "api_exports.json",
                "deps_subgraph": "deps_subgraph.json",
            },
        }
        (shadow_dir / "_dir.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    index = {
        "schema_version": "1.0",
        "repo_id": repo_id,
        "root_meta": "_dir.meta.json",
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "counts": {"dirs": total_dirs, "files": total_files},
    }
    (root_out / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def _partition_changes_by_dir(diff_bundle: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    by_dir: Dict[str, List[Dict[str, Any]]] = {}
    for f in diff_bundle.get("files", []):
        path = f.get("path") or ""
        if not path:
            continue
        rel_dir = str(Path(path).parent).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # Cap per-file hunk text length
        clipped_file = dict(f)
        hunks = []
        total = 0
        for h in f.get("hunks", []):
            text = h.get("text", "")
            take = MAX_HUNK_TEXT_PER_FILE - total
            if take <= 0:
                break
            trimmed = text[:take]
            total += len(trimmed)
            hh = dict(h)
            hh["text"] = trimmed
            hunks.append(hh)
        clipped_file["hunks"] = hunks
        by_dir.setdefault(rel_dir, []).append(clipped_file)
    return by_dir


def build_shadow_diff(base_dir: str, head_dir: str, diff_bundle: Dict[str, Any], shadow_root: str) -> Dict[str, Any]:
    """Create per-directory diff shards under shadow_root, mirroring directory structure.
    """
    root_out = Path(shadow_root)
    root_out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(head_dir)

    by_dir = _partition_changes_by_dir(diff_bundle)
    all_dirs: Set[str] = set(by_dir.keys())
    # ensure parent directories exist in output to link children
    for d in list(all_dirs):
        p = Path(d)
        while str(p) not in all_dirs and str(p) != ".":
            all_dirs.add(str(p))
            p = p.parent
    all_dirs.add("")

    total_dirs = 0
    total_files = 0

    # enumerate directory listing for no_change entries
    def list_names(p: Path) -> List[str]:
        names: List[str] = []
        if p.exists() and p.is_dir():
            for e in sorted(p.iterdir(), key=lambda x: x.name):
                if e.name.startswith(".git"):
                    continue
                if e.is_file():
                    names.append(e.name)
        return names

    for rel in sorted(all_dirs):
        total_dirs += 1
        real_dir = repo_root if rel == "" else (repo_root / rel)
        shadow_dir = root_out if rel == "" else (root_out / rel)
        shadow_dir.mkdir(parents=True, exist_ok=True)

        changed_here = by_dir.get(rel, [])
        changed_names = {Path(f.get("path") or "").name for f in changed_here}
        local_all_names = list_names(real_dir)
        no_change_names = [n for n in local_all_names if n not in changed_names]
        # cap list
        no_change_omitted = False
        if len(no_change_names) > MAX_NO_CHANGE_LIST:
            no_change_omitted = True
            no_change_names = no_change_names[:MAX_NO_CHANGE_LIST]

        files: List[Dict[str, Any]] = []
        # include changed files with hunks
        for f in changed_here:
            files.append({
                "name": Path(f.get("path") or "").name,
                "status": f.get("status", "modified"),
                "hunks": f.get("hunks", []),
            })
        total_files += len(files)
        # include no_change entries
        for n in no_change_names:
            files.append({"name": n, "status": "no_change"})

        # link children directories
        children: List[Dict[str, Any]] = []
        if real_dir.exists():
            for e in sorted(real_dir.iterdir(), key=lambda x: x.name):
                if e.is_dir() and not e.name.startswith(".git"):
                    child_rel = (rel + "/" + e.name) if rel else e.name
                    children.append({"name": e.name, "rel_path": child_rel, "diff": f"{e.name}/_dir.diff.json"})

        summary = {
            "files_changed_here": len(changed_here),
            "insertions": diff_bundle.get("summary", {}).get("insertions", 0),
            "deletions": diff_bundle.get("summary", {}).get("deletions", 0),
            "no_change_omitted": no_change_omitted,
        }
        doc = {
            "schema_version": "1.0",
            "rel_path": rel,
            "summary": summary,
            "files": files,
            "children": children,
        }
        (shadow_dir / "_dir.diff.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

    index = {
        "schema_version": "1.0",
        "root_diff": "_dir.diff.json",
        "counts": {"dirs": total_dirs, "files_listed": total_files},
    }
    (root_out / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def get_dir_context(shadow_root: str, rel_path: str, include_diff: bool, budget: int = 3000) -> Dict[str, Any]:
    root = Path(shadow_root)
    d = root if rel_path == "" else (root / rel_path)
    meta = {}
    diff = {}
    parents: List[Dict[str, Any]] = []
    try:
        if (d / "_dir.meta.json").exists():
            meta = json.loads((d / "_dir.meta.json").read_text(encoding="utf-8"))
        if include_diff and (d / "_dir.diff.json").exists():
            diff = json.loads((d / "_dir.diff.json").read_text(encoding="utf-8"))
        # include pruned knowledge
        api_exports = {}
        deps_subgraph = {}
        if (d / "api_exports.json").exists():
            api_exports = json.loads((d / "api_exports.json").read_text(encoding="utf-8"))
        if (d / "deps_subgraph.json").exists():
            deps_subgraph = json.loads((d / "deps_subgraph.json").read_text(encoding="utf-8"))

        # build parents headers up to root
        p = d.parent
        levels = 0
        while p and (root == p or root in p.parents):
            levels += 1
            if levels > 5:
                break
            hdr = {"rel_path": str(p.relative_to(root)) if p != root else "", "name": p.name or "root"}
            if (p / "_dir.meta.json").exists():
                try:
                    m = json.loads((p / "_dir.meta.json").read_text(encoding="utf-8"))
                    hdr["children_count"] = len(m.get("children", []))
                    hdr["files_count"] = len(m.get("files", []))
                except Exception:
                    pass
            parents.append(hdr)
            if p == root:
                break
            p = p.parent

        ctx = {
            "schema_version": "1.0",
            "rel_path": rel_path,
            "meta": meta,
            "diff": diff if include_diff else {},
            "api_exports": api_exports,
            "deps_subgraph": deps_subgraph,
            "parents": parents,
            "budget": budget,
        }
        return ctx
    except Exception:
        return {"schema_version": "1.0", "rel_path": rel_path, "error": "context_build_failed"}


