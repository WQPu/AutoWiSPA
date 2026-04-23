# AGENTS.md — AutoWiSPA Developer & Coding-Agent Guidelines

> This document is for **all contributors** to this codebase — human developers, GitHub Copilot, Claude Code, and other AI coding agents.
> Read it before making any change to the pipeline.

---

## Project Snapshot

AutoWiSPA is a **LangGraph-based multi-agent system** that automates wireless-signal-processing research.
A natural-language query enters at `problem_analysis` and exits at `report_generation` as a runnable
Jupyter notebook + Markdown report.

### Key Paths

| Category | Path |
|----------|------|
| Main entry | `main.py` — `AutoWiSPA` class + CLI |
| Web UI | `visualization/app.py` |
| Global config | `config.yaml` + `.env` |
| Agent implementations | `agents/` — 8 files, one per pipeline stage |
| Workflow graph | `graph/` — `state.py` / `nodes.py` / `edges.py` / `builder.py` |
| Simulation sandbox | `simulation/sandbox.py` (subprocess-isolated execution) |
| Knowledge base | `knowledge_base/` — algorithms / papers / benchmarks |
| Code templates | `templates/` |
| Utilities | `utils/` — llm_client / event_bus / checkpoint / paper_search |
| Experiment output | `experiments/<run_id>/` — report / notebook / checkpoints / llm_logs |

---

## 8-Node Pipeline

| # | Node | File | Key Inputs (State) | Key Outputs (State) |
|---|------|------|-------------------|---------------------|
| S1 | `problem_analysis` | `agents/problem_analyzer.py` | `user_query` | `task_spec`, `task_spec_complete` |
| S2 | `knowledge_retrieval` | `agents/knowledge_retriever.py` | `task_spec` | `retrieved_knowledge` |
| S3 | `model_formulation` | `agents/model_formalizer.py` | `task_spec`, `retrieved_knowledge` | `problem_formalization` |
| S4 | `solution_planning` | `agents/solution_designer.py` | `problem_formalization`, `retrieved_knowledge` | `solution_plan` |
| S5 | `notebook_generation` | `agents/notebook_generator.py` | `solution_plan`, `problem_formalization` | `notebook`, `notebook_validated` |
| S6 | `verification` | `agents/verifier.py` | `notebook` | `verification_results`, `verification_retry_count` |
| S7 | `simulation` | `agents/simulator.py` | `notebook` | `simulation_results`, `simulation_retry_count` |
| S8 | `report_generation` | `agents/reporter.py` | full state | `final_report` |

### Routing Logic (`graph/edges.py`)

| Function | Trigger | Decision |
|----------|---------|----------|
| `route_after_problem_analysis` | after S1 | `task_spec_complete` → S2 or `__end__` |
| `route_after_verification` | after S6 | `verification_results.status == "passed"` → S7; else retry S5 or fall through to S8 |
| `route_after_simulation` | after S7 | `simulation_results.status == "error"` → retry S5 or fall through to S8; else → S8 |

**Retry limits** (both checked before each loop-back):

```python
# S6 repair loop
retry_count = state["verification_retry_count"]
max_retries = state["max_verification_retries"]  # default 3, set by nodes.py

# S7 repair loop
retry_count = state["simulation_retry_count"]
max_retries = state["max_simulation_retries"]    # default 5, from config.yaml
```

---

## Shared State (`graph/state.py`)

`AutoWiSPAState` is the TypedDict shared across all nodes:

```python
# User input
user_query: str
conversation_history: Annotated[List[dict], operator.add]

# Pipeline stages
task_spec: Optional[dict]          # S1 output — structured task specification
task_spec_complete: bool           # S1 routing flag
clarification_questions: Optional[List[str]]
retrieved_knowledge: Optional[dict]   # S2 output
problem_formalization: Optional[dict] # S3 output — math model, variables, algorithm design
solution_plan: Optional[dict]         # S4 output — notebook structure, eval strategy

# Notebook
notebook: Optional[dict]           # S5 output — parsed notebook dict
notebook_validated: bool

# Results
verification_results: Optional[dict]  # S6 output
simulation_results: Optional[dict]    # S7 output
review_feedback: Optional[dict]

# Retry counters
verification_retry_count: int
simulation_retry_count: int
max_verification_retries: int
max_simulation_retries: int

# Execution trace
execution_trace: Annotated[List[dict], operator.add]

# Final outputs
final_report: Optional[str]
final_notebook: Optional[dict]

# Control
current_phase: str
should_terminate: bool
termination_reason: Optional[str]
error_state: Optional[str]
config: Optional[dict]
```

**Rules:**
- Never rename existing state fields — doing so breaks all downstream nodes silently
- New fields must be `Optional` with a sensible default to avoid breaking checkpoint resume
- `conversation_history` and `execution_trace` use `operator.add` — append only, never replace

---

## Agent Implementation Conventions

### Prompt constants
Each agent defines its prompts as **module-level string constants** at the top of the file:

```python
# agents/problem_analyzer.py — example
SYSTEM_PROMPT = "..."
TASK_SPEC_SCHEMA = {...}   # JSON schema used inside the prompt
```

Prompts can be overridden via YAML files in `prompts/`, managed by `utils/prompt_manager.py`.
After changing any prompt, verify that `utils/md_parser.py` can still parse the expected output format.

### LLM calls
All LLM calls go through `utils/llm_client.py` (`call_llm` / `call_llm_json`):
- Handles model fallback chain (`primary_model` → `fallback_models`)
- Logs every call to `llm_logs/llm_calls.jsonl`
- Respects `node_max_tokens` from `config.yaml`

```python
from utils.llm_client import call_llm, call_llm_json

response = call_llm(
    system=SYSTEM_PROMPT,
    user=user_msg,
    stage="problem_analysis",   # maps to node_max_tokens key
    config=state.get("config"),
)
```

### JSON output parsing
Use `utils/md_parser.py` to extract JSON from LLM responses — never `json.loads` directly on raw LLM output:

```python
from utils.md_parser import extract_json_block

data = extract_json_block(response_text)  # handles ```json fences, trailing commas, etc.
```

---

## Critical Data Dependencies

### `task_spec` (S1 → all downstream)
Produced by `problem_analyzer.py`. Key fields consumed downstream:

```
task_spec
├── task_category         # e.g. "channel_estimation", "doa_estimation"
├── three_dimensions
│   ├── processing_object  # e.g. "received signal", "angle of arrival"
│   ├── processing_target  # e.g. "estimate channel matrix"
│   └── performance_metric # e.g. "NMSE", "RMSE"
├── exploitable_structure  # e.g. "sparse channel, pilot grid"  ← must reach S3
├── theoretical_bound      # e.g. "CRLB"                        ← must reach S3 and S4
└── constraints            # e.g. "pilot overhead < 10%"
```

### `problem_formalization` (S3 → S4/S5/S8)
Produced by `model_formalizer.py`. Key fields consumed downstream:

```
problem_formalization
├── system_model           # variables, dimensions, LaTeX equations
├── algorithm_design
│   ├── algorithm_steps    # [{name, description, formula_latex}]
│   └── key_equations      # LaTeX strings
├── exploitable_structure  # bridged from task_spec — must be preserved
└── theoretical_bound      # bridged from task_spec — must be preserved
```

`_compact_formalization` in `solution_designer.py` must NOT truncate `exploitable_structure`,
`theoretical_bound`, `algorithm_design`, or `formulation_markdown`.

### `solution_plan` (S4 → S5)
`notebook_generator.py` reads `solution_plan.execution_contract.algorithm_steps`.
Each step must carry `formula_latex` for the repair prompt to include mathematical context.

---

## Simulation Sandbox (`simulation/sandbox.py`)

`SubprocessSandbox` executes notebooks in an isolated Python subprocess:

- Default timeout: 300 s (`config.yaml → simulation.sandbox_timeout`)
- Process leak protection: `proc.wait(timeout)` + `proc.kill()`
- `stdin=DEVNULL` — prevents generated code from blocking on `input()`
- Results returned via a temporary JSON file in the run directory
- On timeout or exception: notebook and error traceback are preserved to `iterations/iter_NNN/`

**Generated notebook code must not:**
- Call `os.system()`, `eval()`, or `exec()`
- Block on `input()` or interactive prompts
- Read files from absolute paths outside the sandbox temp directory
- Import modules not in `requirements.txt`

`agents/verifier.py` (S6) performs static checks for the above before execution.

---

## Modification Guidelines

### Minimal-change principle
Only modify code directly required by the task. Do **not**:
- Add docstrings, type hints, or comments to code you did not change
- Refactor unrelated functions to "improve" them
- Remove error-handling or retry logic on production paths

### Adding / modifying an agent
1. Keep all prompt constants at module top level
2. Return a `dict` with only the state fields this node writes — LangGraph merges by key
3. Always guard `.get()` calls — state fields can be `None` on first run or after checkpoint resume
4. Use `isinstance(x, str)` guards when downstream data can be either a plain string or a dict
   (the `relevant_algorithms` list is a known case — items may be either strings or dicts)

### Modifying `TASK_SPEC_SCHEMA` or `problem_formalization` structure
`TASK_SPEC_SCHEMA` is the data contract for all downstream agents.
After changes, verify:
- `_normalize_task_spec` in `problem_analyzer.py` bridges old/new field names
- `_compact_formalization` in `solution_designer.py` includes the new fields
- `_build_repair_prompt` in `notebook_generator.py` still injects `algorithm_design`
- `_build_knowledge_summary` in `model_formalizer.py` still handles `relevant_algorithms`

### Modifying routing logic
Routing functions in `graph/edges.py` must return string keys that exactly match the
`add_conditional_edges` mapping in `graph/builder.py`. A key mismatch causes a silent
LangGraph routing error.

---

## Environment & Common Commands

```bash
# Activate environment
conda activate LLMPy                # Python 3.11

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest -q

# Run full test suite with verbose output
pytest -v tests/

# Import health check (fast)
python -c "
from agents import *
from graph.builder import build_autowisp_graph
g = build_autowisp_graph()
print(f'OK — {len(g.nodes) - 1} nodes')
"

# Run CLI demo
python main.py --demo

# Run single query
python main.py --query "Design a LS channel estimator for a 64-subcarrier OFDM system"

# Launch web dashboard
python visualization/app.py
```

---

## Security Rules

- **Never commit real API keys** — `.env` is in `.gitignore`; use placeholder `sk-...` only as documentation
- Generated code in the sandbox must not call `os.system()` / `eval()` / `exec()`
- `verifier.py` (S6) automatically checks for banned calls — do not weaken these checks
- Do not bypass `SubprocessSandbox` by calling notebooks directly in the main process

---

## Prohibited Operations

- Do not delete or rename existing `AutoWiSPAState` fields without updating every agent that reads them
- Do not delete entries from `knowledge_base/` — they are maintained by external tooling
- Do not modify files under `experiments/` unless the task explicitly requires it
- Do not bypass the subprocess isolation in `simulation/sandbox.py`
- Do not modify the increment logic of `simulation_retry_count` / `verification_retry_count`
- Do not introduce synchronous blocking I/O inside `graph/nodes.py` node functions
- Do not introduce heavyweight new dependencies without justification in the PR description
- Do not use destructive git commands (`reset --hard`, `push --force`, `branch -D`) without explicit user confirmation
