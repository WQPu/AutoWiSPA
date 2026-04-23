# AutoWiSPA — Experiment Output Directory

Each call to `app.run()` or `python main.py` creates a subdirectory here named after the **problem description** (or a timestamp fallback), containing a complete record of that run.

## Directory Layout

```
experiments/
└── <run_id>/                        # query text  or  YYYYMMDD_HHMMSS timestamp
    ├── report.md                    # Final technical report (equations, tables, figure refs)
    ├── simulation.ipynb             # Final simulation notebook (last successful iteration)
    ├── simulation_results.json      # Final simulation outcome (status, performance_data, elapsed_sec, …)
    ├── verification_results.json    # Final static verification result
    ├── checkpoint.json              # Full pipeline state snapshot (stage, timestamp, state)
    ├── task_spec.json               # S1 output: problem understanding, system model, targets, constraints
    ├── problem_formalization.json   # S3 output: mathematical model (JSON + LaTeX)
    ├── solution_plan.json           # S4 output: notebook plan + evaluation strategy
    ├── notebook_plan.json           # S5 output: notebook structure plan
    ├── retrieved_knowledge.json     # S2 output: retrieved papers and algorithm entries
    ├── review_feedback.json         # Review feedback (only when review node is enabled)
    ├── execution_trace.json         # Node execution trace (order, timing, status per node)
    ├── figures/                     # Plots auto-exported during notebook execution
    │   ├── asset_curve_*.png        # System / algorithm illustration figures
    │   └── perf_curve_*.png         # Performance curves
    ├── iterations/                  # Notebook snapshots per repair iteration
    │   └── iter_NNN/
    │       ├── simulation.ipynb     # Notebook at this iteration
    │       └── simulation_results.json   # Execution result (present only for attempted iterations)
    ├── events/
    │   └── events.jsonl             # Real-time node progress events (Web Dashboard feed)
    └── llm_logs/
        └── llm_calls.jsonl          # Full LLM call log (role, content, model, token counts)
```

## File Reference

| File | Pipeline Node | Contents |
|:---|:---:|:---|
| `task_spec.json` | S1 | Structured problem understanding: system model, performance targets, constraints |
| `retrieved_knowledge.json` | S2 | Retrieved algorithm and paper knowledge entries |
| `problem_formalization.json` | S3 | Mathematical formulation and variable definitions (JSON + LaTeX) |
| `solution_plan.json` | S4 | Algorithm design plan and simulation evaluation strategy |
| `simulation.ipynb` | S5 / S7 | Final runnable simulation notebook |
| `simulation_results.json` | S7 | Simulation execution result (success status, performance data, elapsed time) |
| `report.md` | S8 | Full technical report in short-paper style |
| `checkpoint.json` | Global | Complete pipeline state snapshot for debugging and reproducibility |
| `execution_trace.json` | Global | Node execution order and per-node timing statistics |

## Notes

- This directory is listed in `.gitignore` — experiment files are **not** committed to the repository.
- The run ID defaults to the natural-language query text. If the query is too long or contains special characters, it falls back to the `YYYYMMDD_HHMMSS` timestamp format.
- `events/events.jsonl` is written when the event bus is activated during a run.
- `review_feedback.json` is only present when the optional review node is enabled; it does not exist in the default pipeline.
