## Details: Agents, Prompts, Schemas (JSON-only, local-first)

### Roles (minimal)
- Orchestrator: coordinates guards, LLM calls, scoring.
- PR Agent: validates a PR using guards and structured prompts.

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

### Canonical diff
- Command: `git diff --unified=3 --no-color --find-renames --find-copies --output-indicator-new=+ --output-indicator-old=-`
- Store unified hunks verbatim in `diff_bundle.json`. No difftastic overlay.

### Guards (pure Python)
- ScopeGuard(ticket, diff): returns `{ out_of_scope_files: [] }` by glob match.
- RuleGuard(rules, diff, deps): returns `{ violations: [{ rule_id, file, evidence, severity }] }`.
- ImpactGuard(api, deps, diff): returns `{ changed_exports: [], signature_changes: [], possibly_impacted: [] }`.

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

2) Final scoring
- Done deterministically in Python; no LLM required. Use `profile.json` weights and blockers.

### API (local-only for MVP)
- POST `/local/pr/analyze`: { base_dir, head_dir, ticket } → { analysis, rank }.
- POST `/generate_knowledge`: { repo_dir } → writes JSON bundle.

### Tools (internal)
- diff_service: compute_local_diff(base_dir, head_dir) → `diff_bundle.json`.
- knowledge_service: repo scan → `repo.json`, `structure.json`, `api_surface.json`, `deps.json`.
- guards: ScopeGuard, RuleGuard, ImpactGuard.
- llm_service: evaluate_ticket_alignment(ticket, diff_bundle).

### Final report (JSON)
```json
{
  "schema_version": "1.0",
  "ticket_alignment": { "matched": [], "unmet": [], "evidence": [] },
  "scope": { "out_of_scope_files": [] },
  "rules": { "violations": [] },
  "impact": { "changed_exports": [], "signature_changes": [], "possibly_impacted": [] },
  "score": 0,
  "risk_level": "low|medium|high",
  "rank": 3,
  "recommendations": []
}
```