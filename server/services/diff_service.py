from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List


DIFF_CMD = [
    "git",
    "diff",
    "--unified=3",
    "--no-color",
    "--find-renames",
    "--find-copies",
    "--output-indicator-new=+",
    "--output-indicator-old=-",
]

MAX_DIFF_BYTES = 2_000_000  # 2 MB cap to avoid huge payloads


def _init_git_repo_with_tree(repo_dir: str, commit_message: str) -> str:
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "-c", "user.email=dev@example.com", "-c", "user.name=Dev", "commit", "--allow-empty", "--no-verify", "-m", commit_message], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir).decode().strip()
    return sha


def _parse_unified_diff(patch_text: str) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            if current:
                files.append(current)
            current = {"path": "", "status": "modified", "old_path": None, "hunks": []}
        elif line.startswith("rename from ") and current is not None:
            current["status"] = "renamed"
            current["old_path"] = line[len("rename from "):].strip()
        elif line.startswith("rename to ") and current is not None:
            current["path"] = line[len("rename to "):].strip()
        elif line.startswith("+++ b/") and current is not None:
            # new path
            path = line[len("+++ b/"):].strip()
            if path == "/dev/null":
                current["status"] = "removed"
            else:
                current["path"] = path
        elif line.startswith("--- a/") and current is not None:
            old_path = line[len("--- a/"):].strip()
            if old_path == "/dev/null":
                current["status"] = "added"
            else:
                if current["status"] != "renamed":
                    current["old_path"] = old_path
        elif line.startswith("@@ ") and current is not None:
            # hunk header
            meta = line.strip()
            # attempt to extract ranges
            try:
                # @@ -old_start,old_lines +new_start,new_lines @@
                header = meta.split("@@")[1].strip()
                left, right = header.split(" ")[0:2]
                old_start, old_lines = left[1:].split(",")
                new_start, new_lines = right[1:].split(",")
                hunk = {
                    "meta": meta,
                    "old_start": int(old_start),
                    "old_lines": int(old_lines),
                    "new_start": int(new_start),
                    "new_lines": int(new_lines),
                    "text": "",
                }
            except Exception:
                hunk = {"meta": meta, "old_start": 0, "old_lines": 0, "new_start": 0, "new_lines": 0, "text": ""}
            current["hunks"].append(hunk)
        else:
            if current and current.get("hunks"):
                # append diff lines to last hunk text
                current["hunks"][-1]["text"] += line + "\n"

    if current:
        files.append(current)
    # compute summary
    insertions = sum(h["text"].count("\n+") for f in files for h in f["hunks"])
    deletions = sum(h["text"].count("\n-") for f in files for h in f["hunks"])
    summary = {"files_changed": len(files), "insertions": insertions, "deletions": deletions}
    return {"schema_version": "1.0", "base": "local", "head": "local", "summary": summary, "files": files}


def compute_local_diff(base_dir: str, head_dir: str, include_context: bool = True, context_bytes: int = 8000) -> Dict[str, Any]:
    # create temp repo; commit base, then replace with head, commit; run git diff between commits
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        # copy base
        shutil.copytree(base_dir, repo, dirs_exist_ok=True)
        base_sha = _init_git_repo_with_tree(str(repo), "base")

        # replace with head snapshot (preserve .git)
        for child in repo.iterdir():
            if child.name == ".git":
                continue
            if child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
        # copy head snapshot excluding .git
        def _ignore_git(dirpath, names):
            ignored = []
            if ".git" in names:
                ignored.append(".git")
            return ignored

        shutil.copytree(head_dir, repo, dirs_exist_ok=True, ignore=_ignore_git)
        subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "head"], cwd=str(repo), check=True)
        head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo)).decode().strip()

        cmd = DIFF_CMD + [base_sha, head_sha]
        raw = subprocess.check_output(cmd, cwd=str(repo))
        if len(raw) > MAX_DIFF_BYTES:
            # too big; return summary only with file list, no hunks
            parsed = _parse_unified_diff(raw[:0].decode("utf-8", errors="ignore"))
            # Construct minimal file list by git name-status
            name_status = subprocess.check_output(["git", "diff", "--name-status", base_sha, head_sha], cwd=str(repo)).decode("utf-8", errors="ignore")
            files = []
            for line in name_status.splitlines():
                if not line:
                    continue
                parts = line.split("\t")
                status = parts[0]
                if status.startswith("R") and len(parts) >= 3:
                    files.append({"path": parts[2], "status": "renamed", "old_path": parts[1], "hunks": []})
                elif status == "A" and len(parts) >= 2:
                    files.append({"path": parts[1], "status": "added", "old_path": None, "hunks": []})
                elif status == "D" and len(parts) >= 2:
                    files.append({"path": parts[1], "status": "removed", "old_path": parts[1], "hunks": []})
                elif len(parts) >= 2:
                    files.append({"path": parts[1], "status": "modified", "old_path": parts[1], "hunks": []})
            parsed["files"] = files
            parsed["summary"]["files_changed"] = len(files)
            return parsed
        patch = raw.decode(errors="ignore")
        parsed = _parse_unified_diff(patch)
        if include_context:
            # attach head file excerpts for changed files
            for f in parsed.get("files", []):
                p = Path(head_dir) / f.get("path", "")
                try:
                    if p.exists() and p.is_file():
                        data = p.read_bytes()[:context_bytes]
                        try:
                            text = data.decode("utf-8", errors="ignore")
                        except Exception:
                            text = ""
                        f["context"] = text
                except Exception:
                    f["context"] = ""
        return parsed


