## Details: Agents, Prompts, Schemas (JSON-only, local-first)

### Roles (minimal)
- Orchestrator: coordinates guards, LLM calls, scoring.
- PR Agent: validates a PR using guards and structured prompts.
- Dry-Run Analyzer: builds diff features and performs static dependency impact checks (no actual execution).

### Knowledge Artifacts (persistent JSON)
- `repo.json`: repo basics, entrypoints, build/test, layer globs, scope policy.
- `structure.json`: hierarchical directory summary with counts and samples.
- `api_surface.json`: export symbols → source files.
- `deps.json`: file-level dependency edges.
- `rules.json`: architectural invariants.
- `profile.json`: scoring weights, blockers, thresholds.

Per-analysis JSON:
- `ticket.json`: refined ticket spec.
- `diff_bundle.json`: unified git diff parsed into hunks; per-file status/rename.
- `feature_summary.json`: compact diff feature vector for robust scoring and prompts.
- `dry_run.json`: static impact analysis: symbol touches, signature deltas, callers, out-of-scope drift, config drift.

### Canonical diff
- Command: `git diff --unified=3 --no-color --find-renames --find-copies --output-indicator-new=+ --output-indicator-old=-`
- Store unified hunks verbatim in `diff_bundle.json`. No difftastic overlay.

### LLM-first Guards and Logging
- Scope/Rule/Impact guards call OpenAI with slimmed inputs; deterministic fallbacks retained
- Ticket alignment requires per-criterion evidence
- repo.json is post-processed via LLM after programmatic scan
- Dry-Run results and feature vectors are included in prompts to ground LLM reasoning
- All prompts and I/O logged under `prompt_performance/last_*.json`

### LLM usage (instruction-locked, JSON-only)
1) Ticket alignment
System:
```
ONLY_OUTPUT valid JSON per schema. Validate PR diff against ticket acceptance criteria. Be evidence-based; if unsure, mark unmet.
```
User input (contract):
```json
{ "schema_version": "1.0", "ticket": { ... }, "diff_bundle": { ... } }
```
Expected output:
```json
{ "schema_version": "1.0", "ticket_alignment": { "matched": [], "unmet": [], "evidence": [ { "ac_id": "AC-1", "files": ["path"], "hunks": ["@@..."] } ] }, "notes": "" }
```

2) Dry-Run impact reasoning
System:
```
ONLY_OUTPUT valid JSON. Given ticket + diff features + dry_run, identify risky areas: signature changes, export changes, likely impacted callers, config drift. Be conservative and reference symbols.
```
User input (contract):
```json
{ "schema_version": "1.0", "ticket": { ... }, "feature_summary": { ... }, "dry_run": { ... } }
```
Expected output:
```json
{ "schema_version": "1.0", "impact": { "changed_exports": [], "signature_changes": [], "possibly_impacted": [] }, "notes": "" }
```

3) Final scoring
- Done deterministically in Python; no LLM required. Use `profile.json` weights and blockers.

### API (local-only for MVP)
- POST `/local/pr/analyze`: { base_dir, head_dir, ticket } → { analysis, rank }.
- POST `/generate_knowledge`: { repo_dir } → writes JSON bundle.

### Tools (internal)
- diff_service: compute_local_diff(base_dir, head_dir) → `diff_bundle.json`.
- knowledge_service: repo scan → `repo.json`, `structure.json`, `api_surface.json`, `deps.json`.
- dry_run_service: feature extraction (churn, code/noncode, docs/tests/scripts, config drift), semantic deltas, 2-hop dependency callers.
- ast_service: Node-based AST extractor to summarize exports/functions and compute AST deltas.
- guards: ScopeGuard, RuleGuard, ImpactGuard, DryRunGuard (feature extraction + static impact).
- llm_service: evaluate_ticket_alignment(ticket, diff_bundle, feature_summary, dry_run); dry_run_impact_llm(ticket, feature_summary, dry_run).

### Final report (JSON)
```json
{
  "schema_version": "1.0",
  "ticket_alignment": { "matched": [], "unmet": [], "evidence": [] },
  "scope": { "out_of_scope_files": [] },
  "rules": { "violations": [] },
  "impact": { "changed_exports": [], "signature_changes": [], "possibly_impacted": [] },
  "feature_summary": { "out_of_scope_count": 0, "config_drift": [], "export_changes": 0, "signature_changes": 0 },
  "dry_run": { "symbols_touched": [], "callers": [], "callers_2hop_truncated": false, "semantic_deltas": {"calls_added":[],"calls_removed":[],"likely_replacements":[]}, "ast_deltas": {"signature_breaking":[],"exports_added":[],"exports_removed":[]}, "config_drift": [], "notes": "" },
  "score": 0,
  "risk_level": "low|medium|high",
  "rank": 3,
  "recommendations": []
}
```