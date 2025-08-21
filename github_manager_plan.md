## Plan: Build Shadow Filesystem and Agentic Analysis

### Goal
Implement an AI-native shadow filesystem with per-directory knowledge and diff shards, plus strict JSON LLM prompting for scoped analysis.

### Scope
- Initialization: Build SKT under `results/{repoId}/shadow/`.
- Analysis: Build SDE under `results/{repoId}/shadow_diff/{runId}/`.
- Navigator: Retrieve bounded directory contexts.
- LLM prompts: shadow-aware ticket alignment and impact.
- Keep deterministic guards and current report schema.

### Dependencies
- `git` CLI
- OpenAI Chat Completions via `.env` (`OPENAI_API_KEY`, `OPENAI_MODEL`)
- `python-dotenv` for environment loading

### Flows
1) Shadow Init
   - Input: { repo_dir }
   - Steps: walk repo; write `_dir.meta.json`, `api_exports.json`, `deps_subgraph.json`; write `_index.json`.
   - Output: shadow tree under `results/{repoId}/shadow/`.

2) Shadow Diff
   - Input: { base_dir, head_dir }
   - Steps: compute diff; partition changes per directory; write `_dir.diff.json` per directory; write `_index.json`.
   - Output: `results/{repoId}/shadow_diff/{runId}/` with shards.

3) Analysis (phase 2)
   - Iterate over changed dirs; build dir contexts; run `ticket_alignment_shadow` and `impact_guard_shadow` per dir; aggregate with deterministic guards.

### Storage Layout
- `results/{repoId}/knowledge/` → repo/global knowledge
- `results/{repoId}/shadow/` → SKT
- `results/{repoId}/shadow_diff/{runId}/` → SDE
- `prompt_performance/` → prompt I/O logs

### Milestones
- M0: dotenv + routes + shadow services + templates (this change)
- M1: orchestrator shadow-aware loop + per-dir prompts
- M2: evaluation on target repos; refine budgets and schemas

### Risks & Mitigations
- Large directories → cap `no_change` lists; navigator budgets
- Model drift → strict schemas + deterministic fallbacks
- Path normalization → use repo-root-relative POSIX paths everywhere