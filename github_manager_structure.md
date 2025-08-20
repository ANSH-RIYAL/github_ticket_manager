## GitHub Manager Structure (local PR analyzer)

### Repository Layout
```
server/
  app.py
  routes/
    __init__.py
    knowledge_routes.py
    pr_routes.py
  services/
    __init__.py
    knowledge_service.py
    diff_service.py
    guards.py
    llm_service.py
    orchestrator.py
    dry_run_service.py
  storage/
    README.md
templates/
  repo.json
  structure.json
  api_surface.json
  deps.json
  rules.json
  profile.json
  ticket.json
  diff_bundle.json
  feature_summary.json
  dry_run.json
README.md
```

### Flask Routes (v0 local)
- GET `/health`
- POST `/generate_knowledge` { repo_dir } → writes knowledge_min bundle and returns artifact names
- POST `/local/pr/analyze` { base_dir, head_dir, ticket } → returns final report JSON

### Python Modules (high-level)
- `knowledge_service`: scan repo and emit JSON artifacts
- `diff_service`: compute local git diff between two folders; parse unified diff → diff_bundle.json
- `dry_run_service`: extract diff features; perform static dependency impact reasoning (no execution)
- `guards`: ScopeGuard, RuleGuard, ImpactGuard consume diff + features + dry_run
- `llm_service`: ticket alignment + dry_run impact (LLM-first JSON)
- `orchestrator`: runs dry-run, guards, ticket alignment, scoring, and assembles final report

### Configuration
- Environment: `OPENAI_API_KEY`, `MODEL` (e.g., `gpt-4o-mini`), `TIMEOUT_MS`
- Feature flags: `RUN_JS_TESTS=0` (reserved), `ENABLE_DRY_RUN=1`
