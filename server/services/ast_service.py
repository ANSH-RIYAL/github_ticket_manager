from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple


def _run_node_ast(file_path: str) -> Dict[str, Any] | None:
    script = Path(__file__).parent / "js_ast_extract.js"
    if not script.exists():
        return None
    try:
        out = subprocess.check_output([
            "node", str(script), "--file", file_path
        ], stderr=subprocess.STDOUT, timeout=20)
        return json.loads(out.decode("utf-8"))
    except Exception:
        return None


def summarize_files_ast(root_dir: str, rel_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    summaries: Dict[str, Dict[str, Any]] = {}
    for rel in rel_paths:
        fp = str(Path(root_dir) / rel)
        ast = _run_node_ast(fp)
        if ast is None:
            ast = {"exports": [], "functions": []}
        summaries[rel] = ast
    return summaries


def compute_ast_deltas(base_dir: str, head_dir: str, changed_files: List[str]) -> Dict[str, Any]:
    code_files = [p for p in changed_files if p.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs"))]
    if not code_files:
        return {"signature_breaking": [], "exports_added": [], "exports_removed": []}

    base = summarize_files_ast(base_dir, code_files)
    head = summarize_files_ast(head_dir, code_files)

    signature_breaking: List[str] = []
    exports_added: List[str] = []
    exports_removed: List[str] = []

    for rel in code_files:
        b = base.get(rel, {"exports": [], "functions": []})
        h = head.get(rel, {"exports": [], "functions": []})

        bex = {e.get("name"): e.get("kind") for e in b.get("exports", [])}
        hex = {e.get("name"): e.get("kind") for e in h.get("exports", [])}
        for name in (hex.keys() - bex.keys()):
            exports_added.append(f"{rel}#${name}")
        for name in (bex.keys() - hex.keys()):
            exports_removed.append(f"{rel}#${name}")

        bf = {f.get("name"): (f.get("params", []), bool(f.get("isExported"))) for f in b.get("functions", []) if f.get("name")}
        hf = {f.get("name"): (f.get("params", []), bool(f.get("isExported"))) for f in h.get("functions", []) if f.get("name")}
        # breaking if param length changes or export status toggles
        for name in (set(bf.keys()) & set(hf.keys())):
            bsig, bexp = bf[name]
            hsig, hexp = hf[name]
            if len(bsig) != len(hsig) or bexp != hexp:
                signature_breaking.append(f"{rel}#${name}")

    return {
        "signature_breaking": sorted(set(signature_breaking)),
        "exports_added": sorted(set(exports_added)),
        "exports_removed": sorted(set(exports_removed)),
    }


