## Changelog

### 2025-08-20 (later)
- feat: AST analyzer (Node @babel/parser) and Python `ast_service.py`; extract exports/functions; compute AST deltas
- feat: semantic operation deltas from diff hunks; added to `dry_run`
- feat: bold rank bands (1→15, 2→35, 3→55, 4→75, 5→95) with small evidence-based adjustments
- fix: scope guard uses deterministic result intersected with LLM to avoid false out-of-scope
- docs: refine details/plan/structure to include AST, semantic deltas, banded scoring
- templates: add `feature_summary.json` and `dry_run.json`; extend `pr_report.json` to include both
- benchmark: repo A (addMonths UTC) ranks separated 1–5; repo B (MyEdMasters-MML) ranks separated with large gaps after scope fix

### 2025-08-20
- chore: cleanup legacy/temp dirs (`tmp/`, `tmp_scenarios/`, `prompt_performance/`, `results/` regenerated)
- docs: expand design with Dry-Run Analyzer (static impact + diff features)
- docs: update roles, tools, final report schema to include `feature_summary` and `dry_run`
- plan: add milestones for Dry-Run and feature vectors; clarify storage to `results/{repoId}/analysis/`

### 2025-08-19
- feat: LLM-first guards with deterministic fallbacks; prompt logging
- feat: diff context excerpts; diff size cap; scoring section_scores
- docs: JSON-only templates for knowledge and reports

