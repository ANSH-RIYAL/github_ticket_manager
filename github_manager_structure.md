## Architecture: Shadow Knowledge + Diff Tree (AI-native)

### High-level
- **Shadow Knowledge Tree (SKT)**: Per-directory `_dir.meta.json` with parent/children links and pruned `api_exports.json` and `deps_subgraph.json` for that subtree.
- **Shadow Diff Environment (SDE)**: Per-directory `_dir.diff.json` listing changed files in that directory, marking others as `no_change`, and linking to children’s diffs.
- **Navigator**: Server-side context assembler exposing directory-scoped JSON contexts for LLM prompts with strict budgets.

### Repository Layout
```
server/
  app.py
  routes/
    __init__.py
    knowledge_routes.py
    pr_routes.py
    ticket_routes.py
    shadow_routes.py
  services/
    __init__.py
    knowledge_service.py
    diff_service.py
    guards.py
    llm_service.py
    orchestrator.py
    dry_run_service.py
    ast_service.py
    shadow_fs_service.py
templates/
  shadow_dir.meta.json
  shadow_dir.diff.json
  shadow_index.json
  repo.json
  structure.json
  api_surface.json
  deps.json
  rules.json
  profile.json
  ticket.json
  diff_bundle.json
  pr_report.json
```

### Flask Routes
- GET `/health`
- POST `/generate_knowledge` { repo_dir } → writes repo-level knowledge bundle
- POST `/shadow/init` { repo_dir } → builds Shadow Knowledge Tree under `results/{repoId}/shadow/`
- POST `/shadow/diff` { base_dir, head_dir } → builds Shadow Diff Environment under `results/{repoId}/shadow_diff/{runId}/`
- GET `/shadow/context` { repo_id, [run_id], rel_path, budget } → returns merged directory context JSON
- POST `/local/pr/analyze` { base_dir, head_dir, ticket } → root/global analysis (kept for now)

### Modules
- `shadow_fs_service`: builds SKT/SDE and provides `get_dir_context`.
- `llm_service`: adds `ticket_alignment_shadow` and `impact_guard_shadow` for per-directory structured prompting.
- Existing deterministic guards continue to run globally; orchestration can iterate per changed directory using shadow contexts.

### Configuration
- `.env` with `OPENAI_API_KEY`, `OPENAI_MODEL`. Loaded via `python-dotenv`.

### Guarantees
- All artifacts are strict JSON; linkable, stable, and referencable programmatically.
- Prompt inputs are bounded and reproducible via navigator budgets.
