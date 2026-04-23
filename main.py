"""
AutoWiSPA Main Entry — CLI & Python API

Usage:
  CLI:
    python main.py --query "Design a DOA estimation for 8x1 ULA ..."
    python main.py --demo                       # Run built-in demo task
    python main.py --demo --output-dir ./out    # Custom output directory

    Python API:
        from main import AutoWiSPA
        app = AutoWiSPA()
    result = app.run("Design a DOA estimation for 8x1 ULA ...")
    print(result.report_path)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import uuid

import yaml


@dataclass
class AutoWiSPAResult:
    """AutoWiSPA single run result."""

    final_score: float
    iterations: int
    report_path: str
    notebook_path: str
    output_dir: str
    termination_reason: str


class AutoWiSPA:
    """AutoWiSPA main public class."""

    def __init__(self, config_path: Optional[str] = None):
        self.project_root = Path(__file__).resolve().parent
        self.config_path = Path(config_path) if config_path else self.project_root / "config.yaml"
        self.config = self._load_config()

        from graph.builder import build_autowisp_graph
        self.graph = build_autowisp_graph(config=self.config)

    def run(self, query: str, output_dir: Optional[str] = None) -> AutoWiSPAResult:
        """Execute one end-to-end pipeline run and save outputs to disk."""
        run_dir = Path(output_dir) if output_dir else self._make_output_dir()
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_dir.name or str(uuid.uuid4())

        # Write all raw LLM call logs to llm_logs/llm_calls.jsonl
        from utils.llm_client import set_llm_log_dir
        set_llm_log_dir(str(run_dir / "llm_logs"))

        from utils.event_bus import activate_event_bus, get_event_bus, NoOpBus
        bus = get_event_bus()
        if isinstance(bus, NoOpBus):
            bus = activate_event_bus()
        bus.configure_run(run_id=run_id, log_dir=str(run_dir / "events"))

        # Activate checkpoint system
        from graph.nodes import set_checkpoint_dir
        set_checkpoint_dir(run_dir)

        initial_state = self._build_initial_state(query)
        final_state = self.graph.invoke(initial_state)

        report_text = final_state.get("final_report") or "# AutoWiSPA Report\n\nPipeline terminated early: task specification is incomplete, user input needed.\n"
        report_path = run_dir / "report.md"
        report_path.write_text(report_text, encoding="utf-8")

        notebook = final_state.get("final_notebook") or final_state.get("notebook") or {}
        notebook_path = run_dir / "simulation.ipynb"
        notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding="utf-8")

        task_spec = final_state.get("task_spec") or {}
        (run_dir / "task_spec.json").write_text(
            json.dumps(task_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        retrieved_knowledge = final_state.get("retrieved_knowledge") or {}
        (run_dir / "retrieved_knowledge.json").write_text(
            json.dumps(retrieved_knowledge, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        problem_formalization = final_state.get("problem_formalization") or {}
        (run_dir / "problem_formalization.json").write_text(
            json.dumps(problem_formalization, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        solution_plan = final_state.get("solution_plan") or {}
        (run_dir / "solution_plan.json").write_text(
            json.dumps(solution_plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        notebook_plan = (solution_plan or {}).get("notebook_plan") or []
        (run_dir / "notebook_plan.json").write_text(
            json.dumps(notebook_plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        verification_results = final_state.get("verification_results") or {}
        (run_dir / "verification_results.json").write_text(
            json.dumps(verification_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        sim_results = final_state.get("simulation_results") or {}
        (run_dir / "simulation_results.json").write_text(
            json.dumps(sim_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        review_feedback = final_state.get("review_feedback") or {}
        (run_dir / "review_feedback.json").write_text(
            json.dumps(review_feedback, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        execution_trace = final_state.get("execution_trace") or []
        (run_dir / "execution_trace.json").write_text(
            json.dumps(execution_trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        final_score = self._extract_final_score(final_state)
        iterations = (
            int(final_state.get("verification_retry_count", 0))
            + int(final_state.get("simulation_retry_count", 0))
            + int(final_state.get("review_retry_count", 0))
            + 1
        )
        termination_reason = final_state.get("termination_reason") or "Termination condition not triggered (may have ended early)"

        return AutoWiSPAResult(
            final_score=final_score,
            iterations=iterations,
            report_path=str(report_path),
            notebook_path=str(notebook_path),
            output_dir=str(run_dir),
            termination_reason=termination_reason,
        )

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _build_initial_state(self, query: str) -> dict[str, Any]:
        max_simulation_retries = int((self.config.get("agents") or {}).get("max_simulation_retries", 2))
        max_verification_retries = int((self.config.get("agents") or {}).get("max_verification_retries", 3))
        max_review_retries = int((self.config.get("agents") or {}).get("max_review_retries", 2))
        return {
            "user_query": query,
            "conversation_history": [],
            "task_spec": None,
            "task_spec_complete": False,
            "clarification_questions": [],
            "retrieved_knowledge": None,
            "problem_formalization": None,
            "solution_plan": None,
            "notebook": None,
            "notebook_validated": False,
            "verification_results": None,
            "simulation_results": None,
            "review_feedback": None,
            "max_simulation_retries": max_simulation_retries,
            "max_verification_retries": max_verification_retries,
            "max_review_retries": max_review_retries,
            "simulation_retry_count": 0,
            "verification_retry_count": 0,
            "review_retry_count": 0,
            "execution_trace": [],
            "final_report": None,
            "final_notebook": None,
            "current_phase": "start",
            "should_terminate": False,
            "termination_reason": None,
            "error_state": None,
            "config": self.config,
        }

    def _make_output_dir(self) -> Path:
        output_cfg = self.config.get("output") or {}
        experiments_dir = output_cfg.get("experiments_dir", "./experiments")
        base = (self.project_root / experiments_dir).resolve() if experiments_dir.startswith("./") else Path(experiments_dir)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return base / ts

    @staticmethod
    def _extract_final_score(final_state: dict[str, Any]) -> float:
        feedback = final_state.get("review_feedback") or {}
        score = feedback.get("overall_score")
        if isinstance(score, (int, float)):
            return float(score)

        return 0.0

# DoA
# DEMO_QUERY = (
#     "Two uncorrelated narrowband far-field sources separated by approximately 15° impinge on an 8-element half-wavelength-spaced ULA; $L = 200$ snapshots are available, nominal SNR is around 20 dB, and the number of sources $D = 2$ is assumed known. Design a DoA estimation algorithm, plot the spatial spectrum or pseudo-spectrum, provide DoA RMSE vs. SNR (0–30 dB) with the CRB as a reference lower bound, and characterize the resolution limit — the minimum SNR at which the two sources can still be separated."
# )

# Spectrum Sensing
# DEMO_QUERY = (
#     " A cognitive radio secondary user equipped with a single antenna collects $N = 256$ complex baseband samples per sensing interval and must decide whether a licensed band is occupied by a primary user under AWGN conditions (flat fading assumed compensated). The false-alarm probability must satisfy $P_{fa} \leq 0.01$, and reliable detection is expected at SNR as low as $-10$ dB. Design the detection algorithm, explain how the decision threshold is set, provide the theoretical $P_d$ vs. SNR curve from $-20$ dB to $0$ dB, and validate with Monte Carlo simulation. "
# )                                                                                                                                
# Pilot Design
# DEMO_QUERY = (
#     "A SISO-OFDM system operates with 64 subcarriers (SCS = 15 kHz, CP length 16, carrier frequency 3.5 GHz), where 16 equally spaced pilot subcarriers are available and the channel frequency response at the remaining 48 data subcarriers must be recovered; the channel follows a 3GPP TDL-A model with 30 ns rms delay spread. Design at least two estimation approaches with different performance–complexity trade-offs, explain the interpolation strategy used to obtain non-pilot subcarrier estimates, and provide NMSE vs. SNR curves from 0 dB to 30 dB for each approach."
# )

DEMO_QUERY = (
    " Implement a **2D least-squares positioning** algorithm using ToA range measurements from 3 base stations. BS positions: $BS_1 = (0, 0)$, $BS_2 = (200, 0)$, $BS_3 = (100, 173)$ m (approximately equilateral triangle with 200 m side length). The true target position is $(80, 60)$ m. Each BS provides a noisy range measurement $\hat{d}_i = d_i + n_i$, where $n_i \sim \mathcal{N}(0, \sigma^2)$ with $\sigma = 3$ m. The solution must: linearize the nonlinear range equations via a reference-station differencing approach, solve the resulting linear system using least squares, and run a Monte Carlo simulation ($\geq 1000$ trials) to obtain the positioning RMSE. Optionally compute the Geometric Dilution of Precision (GDOP) and compare it with the observed RMSE. "
)
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AutoWiSPA — Automated Wireless Signal Processing Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python main.py --query "Design a DOA estimator for 8x1 ULA, SNR -5~25 dB"\n'
            "  python main.py --demo\n"
            "  python main.py --demo --output-dir ./my_results\n"
            "  python main.py --demo --config custom_config.yaml\n"
        ),
    )
    parser.add_argument("--query", type=str, default="", help="Natural language task description")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo task")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: experiments/<timestamp>)")
    parser.add_argument("--config", type=str, default="", help="Config file path (default: ./config.yaml)")
    return parser


def _setup_logging() -> None:
    import logging
    import os
    os.environ.setdefault("NUMEXPR_MAX_THREADS", "12")
    try:
        from rich.logging import RichHandler
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, markup=True)],
        )
    except ImportError:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    for name in ("numexpr", "numexpr.utils", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _load_env() -> None:
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.demo or (not args.query.strip()):
        query = DEMO_QUERY
        if not args.query.strip():
            print("[INFO] No --query provided, running built-in demo task.\n")
    else:
        query = args.query.strip()

    _setup_logging()
    _load_env()

    from utils.event_bus import activate_event_bus, get_event_bus, NoOpBus
    bus = get_event_bus()
    if isinstance(bus, NoOpBus):
        bus = activate_event_bus()
    from utils.cli_progress import attach_cli_progress
    attach_cli_progress(bus)

    import time
    config_path = args.config or None
    app = AutoWiSPA(config_path=config_path)

    print(f"\n╔{'═'*60}╗")
    print(f"║  {'AutoWiSPA — Starting Pipeline':<58}║")
    print(f"╠{'═'*60}╣")
    q_display = query[:56] + '…' if len(query) > 56 else query
    print(f"║  Query: {q_display:<50}║")
    print(f"╚{'═'*60}╝\n")

    t0 = time.time()
    result = app.run(query=query, output_dir=args.output_dir or None)
    elapsed = time.time() - t0

    print(f"\n╔{'═'*60}╗")
    print(f"║  {'AutoWiSPA — Run Complete':<58}║")
    print(f"╚{'═'*60}╝")
    print(f"  Score      {result.final_score:.2f} / 10")
    print(f"  Iterations {result.iterations}")
    print(f"  Time       {elapsed:.1f}s")
    print(f"  {'─'*40}")
    print(f"  Report     {result.report_path}")
    print(f"  Notebook   {result.notebook_path}")
    print(f"  Output     {result.output_dir}")


if __name__ == "__main__":
    main()
