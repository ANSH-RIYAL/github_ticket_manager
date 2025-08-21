# GitHub Ticket Manager (AI-native, Shadow Filesystem)

This service validates local PRs using a shadow knowledge tree (per-directory metadata) and a shadow diff environment (per-directory diffs). It combines deterministic guards with strict JSON-only LLM prompting for scoped, evidence-based analysis.

## Features
- Shadow Knowledge Tree (SKT): `_dir.meta.json`, `api_exports.json`, `deps_subgraph.json` per directory.
- Shadow Diff Environment (SDE): `_dir.diff.json` per directory, with `no_change` entries and child links.
- Navigator: GET `/shadow/context` provides bounded, linkable JSON contexts.
- Analysis: deterministic guards + shadow-scoped LLM prompts; per-run outputs with rank and score.

## API
- GET `/health`
- POST `/generate_knowledge` { repo_dir }
- POST `/shadow/init` { repo_dir }
- POST `/shadow/diff` { base_dir, head_dir }
- GET `/shadow/context` { repo_id, [run_id], rel_path, budget }
- POST `/local/pr/analyze` { base_dir, head_dir, ticket }

## Environment
Create a `.env`:
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

## Run
```
python3 -m pip install -r requirements.txt
python3 -c 'from server.app import create_app; app=create_app(); app.run(host="0.0.0.0", port=5057, debug=False)'
```

## Shadow Initialization
```
curl -X POST localhost:5057/shadow/init -H 'Content-Type: application/json' \
  -d '{"repo_dir":"/abs/path/to/repo"}'
```

## Shadow Diff Build
```
curl -X POST localhost:5057/shadow/diff -H 'Content-Type: application/json' \
  -d '{"base_dir":"/abs/base","head_dir":"/abs/head"}'
```

## Analyze a PR
```
curl -X POST localhost:5057/local/pr/analyze -H 'Content-Type: application/json' -d @ticket_payload.json
```
Where `ticket_payload.json` contains:
```
{
  "base_dir": "/abs/base",
  "head_dir": "/abs/head",
  "ticket": { ... ticket schema ... }
}
```

## Outputs
- `results/{repoId}/shadow/` — SKT
- `results/{repoId}/shadow_diff/{runId}/` — SDE
- `results/{repoId}/analysis/{runId}/` — report, diff_bundle, feature_summary, dry_run
- `prompt_performance/last_*.json` — prompt traces

## Notes
- All artifacts are strict JSON; prompts are instruction-locked and conservative.
- Large directories cap `no_change` lists; hunk texts are trimmed per budget.
