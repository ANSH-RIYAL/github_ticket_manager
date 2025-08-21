## GitHub Manager MVP Plan (local PR analyzer)

### Goal
Build a minimal, reliable local PR validation service using Flask + OpenAI. JSON-only artifacts; no GitHub integration in v0.

### MVP Scope (v0)
- Generate JSON knowledge bundle from a base repository folder.
- Accept a ticket JSON, a base folder, and a modified folder; compute git diff; analyze PR.
- Produce a structured JSON report with rank and recommendations.
- Include Dry-Run Analyzer (no execution): syntactic + static dependency impact + diff features.

### Non-Goals (v0)
- No GitHub API usage; local-only.
- No automated unit tests; manual + CLI debugging only.
- No auto-merge.

### Dependencies
- OpenAI Chat Completions (ticket alignment only).
- `git` CLI present on system.

### Core Flows
1) Generate Knowledge
   - Input: { repo_dir }
   - Output: `repo.json`, `structure.json`, `api_surface.json`, `deps.json`, `rules.json`, `profile.json` under `storage/{repoId}/knowledge_min/`.

2) Ticket Propose (LLM)
   - Input: { repo_dir, freeform_text }
   - Steps: LLM converts freeform to strict ticket.json using structure/api_surface as hints
   - Output: ticket.json

3) Local PR Analyze
   - Input: { base_dir, head_dir, ticket }
   - Steps:
     a) compute `diff_bundle.json` via git diff
     b) build `feature_summary.json` (export/signature changes, out_of_scope_count, config drift, churn, code/noncode ratio)
     c) Dry-Run Analyzer: `dry_run.json` with symbol touches, callers (2-hop with caps), config drift, signature deltas, semantic operation deltas, AST deltas
     d) Guards: Scope, Rule, Impact consume diff + features + dry_run
     e) LLM ticket_alignment + dry_run_impact_llm (LLM-first with deterministic fallbacks)
     f) compute score/rank deterministically (profile weights)
   - Output: final report JSON with banded ranks and small evidence-based score adjustments.

### Storage Layout
- `storage/{repoId}/knowledge_min/` → persistent JSON knowledge bundle.
- `results/{repoId}/analysis/` → inputs/outputs for each run (overwritten by repoId/ticket run to avoid clutter).

### Milestones
- M0: Flask skeleton + health.
- M1: knowledge generation CLI + endpoints.
- M2: diff service (local dirs) + guards.
- M3: Dry-Run Analyzer + feature_summary + guard integration.
- M4: LLM ticket alignment + dry_run impact + scoring + report.

### Risks
- Knowledge fidelity: keep schemas minimal and conservative.
- Diff parsing: stick to unified format with fixed flags.
- Token use: keep inputs compact; avoid full file dumps.
- Overfitting: use generic diff features and static dependency reasoning, not case-specific heuristics.