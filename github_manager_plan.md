## GitHub Manager MVP Plan (local PR analyzer)

### Goal
Build a minimal, reliable local PR validation service using Flask + OpenAI. JSON-only artifacts; no GitHub integration in v0.

### MVP Scope (v0)
- Generate JSON knowledge bundle from a base repository folder.
- Accept a ticket JSON, a base folder, and a modified folder; compute git diff; analyze PR.
- Produce a structured JSON report with rank and recommendations.

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

2) Local PR Analyze
   - Input: { base_dir, head_dir, ticket }
   - Steps: compute `diff_bundle.json` via git diff; run ScopeGuard, RuleGuard, ImpactGuard; call LLM for ticket alignment; compute score/rank.
   - Output: final report JSON.

### Storage Layout
- `storage/{repoId}/knowledge_min/` → persistent JSON knowledge bundle.
- `storage/{repoId}/tickets/{ticketId}/pr_{n}/` → inputs/outputs for each run.

### Milestones
- M0: Flask skeleton + health.
- M1: knowledge generation CLI + endpoints.
- M2: diff service (local dirs) + guards.
- M3: LLM ticket alignment + scoring + report.

### Risks
- Knowledge fidelity: keep schemas minimal and conservative.
- Diff parsing: stick to unified format with fixed flags.
- Token use: keep inputs compact; avoid full file dumps.