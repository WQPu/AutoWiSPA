# AutoWiSPA Visualization

## Start

```bash
python visualization/app.py
```

Custom experiments root or port:

```bash
python visualization/app.py --experiments-root /path/to/experiments --port 8091
```

## What It Shows

- Auto-follows the newest timestamp-style run under `experiments/`
- Presents the workflow inferred from each experiment's real checkpoint and execution trace, including legacy intermediate stages when they are present
- Builds live status from `checkpoint.json`, `execution_trace.json`, `llm_logs/llm_calls.jsonl`, `verification_results.json`, `simulation_results.json`, and `report.md` when available
- Surfaces mission input, active stage, recent execution feed, runtime state, LLM activity, stage summaries, report preview, and simulation performance
- Supports `View Full Context` actions for report content, stage artifacts, and recent LLM prompt/response payloads
- Supports older run traces by normalizing legacy stage names such as `critic` or `file_generation`

## Notes

- The page is read-only and polling-based. Use the run selector in the header, or let the dashboard auto-follow the latest run.
- Add `?run=<run_name>` to the page URL if you want to pin the dashboard to a specific run instead of auto-following the latest one.
- When a run is incomplete, the dashboard degrades gracefully and shows whatever stage evidence is currently available.
