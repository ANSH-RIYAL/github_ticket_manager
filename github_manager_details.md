## Details: Shadow Knowledge, Policy Governance, and Structured Prompts

### Roles
- **Navigator**: serves directory-scoped contexts from the Shadow Knowledge Tree (SKT) and Shadow Diff Environment (SDE).
- **Orchestrator**: coordinates deterministic guards and LLM calls; aggregates per-directory results and computes final score/rank.
- **Policy Engine**: evaluates structured policies (scope, config drift, API changes) and normalizes violations.
- **PR Agent**: evaluates ticket alignment and impact using directory-scoped prompts.
- **Exporter**: emits SARIF for CI/PR and an immutable run manifest for audit.

### Shadow Artifacts
- `_dir.meta.json` (per directory):
  - `dir_name`, `rel_path`, `parent_meta`, `children[]`, `files[]`
  - `links.api_exports`, `links.deps_subgraph`
- `api_exports.json` (per directory): exports within subtree
- `deps_subgraph.json` (per directory): nodes/edges within or touching subtree
- `_dir.diff.json` (per directory during analysis): changed files with hunks, local `no_change` listings, children links
- `_index.json` at roots (knowledge and diff trees)

### Run Artifacts (per analysis)
- `manifest.json`: immutable run manifest (runId, repoId, base/head paths, model, budgets, prompt hashes)
- `report.json`: final structured report (now includes `per_directory[]`, `policy_violations[]`, `manifest_ref`)
- `report.sarif.json`: SARIF v2.1.0 conversion for CI surfaces

### Canonical Diff
- `git diff --unified=3 --no-color --find-renames --find-copies --output-indicator-new=+ --output-indicator-old=-`
- Parsed once → partitioned into per-directory `_dir.diff.json` with capped hunk text

### Structured Prompting (LLM)
All prompts are instruction-locked and JSON-only. No subjective free text; optional `notes`/`comments` keys are allowed but not required.

1) Ticket alignment (per directory)
System:
```
ONLY_OUTPUT {"schema_version":"1.0","ticket_alignment":{"matched":[],"unmet":[],"evidence":[]}}. Use dir_context.meta/files, dir_context.diff hunks, api_exports, deps_subgraph. If evidence is absent in this subtree, leave unmet unless proven by global_summary.
```
User input:
```json
{ "schema_version": "1.0", "ticket": { ... }, "dir_context": { ... }, "global_summary": { ... } }
```

2) Impact (per directory)
System:
```
ONLY_OUTPUT {"changed_exports":[],"signature_changes":[],"possibly_impacted":[]}. Use dir_context.diff + api_exports + deps_subgraph. Limit to this subtree.
```
User input:
```json
{ "schema_version": "1.0", "dir_context": { ... }, "feature_summary": { ... }, "dry_run": { ... } }
```

3) Global alignment (root; existing)
System and schema unchanged, but can be fed with root dir_context for consistency.

All prompts must output claims with minimal, verifiable evidence:
- Evidence references: { rel_path, file, hunk_meta } or { api_symbol, ast_delta_id }
- Claims without evidence are treated as suggestions and do not affect policy/score.

### Logging and Budgets
- All prompts logged to `prompt_performance/`.
- Navigator caps hunks and lists per directory by `budget` and internal limits; reproducible and small.
- On-demand file contents are capped and logged; only changed files are fetchable by default.

### Final Report (enriched shape)
```json
{
  "schema_version": "1.0",
  "ticket_alignment": { "matched": [], "unmet": [], "evidence": [] },
  "scope": { "out_of_scope_files": [] },
  "rules": { "violations": [] },
  "impact": { "changed_exports": [], "signature_changes": [], "possibly_impacted": [] },
  "feature_summary": { "out_of_scope_count": 0, "config_drift": [], "export_changes": 0, "signature_changes": 0 },
  "dry_run": { "symbols_touched": [], "callers": [], "callers_2hop_truncated": false, "semantic_deltas": {"calls_added":[],"calls_removed":[],"likely_replacements":[]}, "ast_deltas": {"signature_breaking":[],"exports_added":[],"exports_removed":[]}, "config_drift": [], "notes": "" },
  "per_directory": [ { "rel_path": "src/utils", "matched": ["AC-1"], "impact": {"changed_exports":[],"signature_changes":[],"possibly_impacted":[]} } ],
  "policy_violations": [ { "id": "CONFIG_DRIFT_PORT", "level": "warn", "path": "compose.yml", "evidence_ref": {"rel_path":"","file":"compose.yml"} } ],
  "manifest_ref": "manifest.json",
  "score": 0,
  "risk_level": "low|medium|high",
  "rank": 3,
  "recommendations": []
}
```