"""
Code sandbox.
Safely execute generated simulation code in an isolated environment.
"""

from __future__ import annotations
import os
import sys
import json
import tempfile
import subprocess
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from utils.event_bus import get_event_bus


_NOTEBOOK_SKIP_ROLES = {"plotting", "results_display", "result_display", "display_only"}


def _build_notebook_code_package(notebook: dict) -> dict[str, str]:
    """Convert notebook code cells into a sandbox-executable code package."""
    code_blocks: list[dict[str, str]] = []
    for index, cell in enumerate(notebook.get("cells") or [], start=1):
        if cell.get("cell_type") != "code":
            continue
        role = (cell.get("metadata") or {}).get("autowisp_role", f"code_{index}")
        if role in _NOTEBOOK_SKIP_ROLES:
            continue
        source = "".join(cell.get("source") or [])
        if source.strip():
            code_blocks.append({"role": role, "source": source})

    runtime_source = (
        "import json\n\n"
        f"NOTEBOOK_BLOCKS = {json.dumps(code_blocks, ensure_ascii=False, indent=2)}\n\n"
        "def _json_safe(value):\n"
        "    if value is None or isinstance(value, (str, int, float, bool)):\n"
        "        return value\n"
        "    if isinstance(value, dict):\n"
        "        return {str(k): _json_safe(v) for k, v in value.items()}\n"
        "    if isinstance(value, (list, tuple, set)):\n"
        "        return [_json_safe(v) for v in value]\n"
        "    if hasattr(value, 'tolist'):\n"
        "        return _json_safe(value.tolist())\n"
        "    if hasattr(value, 'item'):\n"
        "        try:\n"
        "            return value.item()\n"
        "        except Exception:\n"
        "            pass\n"
        "    return str(value)\n\n"
        "def run_notebook(eval_config=None):\n"
        "    eval_config = dict(eval_config or {})\n"
        "    namespace = {'__name__': '__autowispa_notebook__', 'EVAL_CONFIG': eval_config}\n"
        "    for block in NOTEBOOK_BLOCKS:\n"
        "        exec(compile(block['source'], f\"notebook::{block['role']}\", 'exec'), namespace, namespace)\n"
        "    results = namespace.get('RESULTS')\n"
        "    if not isinstance(results, dict):\n"
        "        if callable(namespace.get('run_experiment')):\n"
        "            results = namespace['run_experiment'](namespace.get('EVAL_CONFIG', eval_config))\n"
        "        elif callable(namespace.get('run_evaluation')):\n"
        "            results = namespace['run_evaluation'](namespace.get('EVAL_CONFIG', eval_config))\n"
        "        else:\n"
        "            raise RuntimeError('Notebook execution did not produce RESULTS and no run_experiment/run_evaluation function was found')\n"
        "    return _json_safe(results)\n"
    )
    evaluation_source = (
        "from notebook_runtime import run_notebook\n\n"
        "def run_evaluation(eval_config):\n"
        "    return run_notebook(eval_config)\n"
    )
    return {
        "notebook_runtime.py": runtime_source,
        "evaluation/evaluate.py": evaluation_source,
    }


class SubprocessSandbox:
    """
    Subprocess-based code sandbox (lightweight, suitable for development).

    Executes code in an independent Python subprocess, passing results via JSON files.
    For production scenarios, use DockerSandbox for stronger isolation.
    """

    RUNNER_TEMPLATE = """
import os, logging
os.environ.setdefault("NUMEXPR_MAX_THREADS", "12")
logging.getLogger("numexpr").setLevel(logging.WARNING)
logging.getLogger("numexpr.utils").setLevel(logging.WARNING)

import sys, json, traceback
sys.path.insert(0, "{code_dir}")

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("evaluate", "{eval_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    eval_config = {eval_config_json}

    import inspect as _inspect
    _sig = _inspect.signature(module.run_evaluation)

    try:
        results = module.run_evaluation(eval_config)
    except TypeError as _te:
        _te_msg = str(_te)
        if "str" in _te_msg or "PathLike" in _te_msg or "bytes" in _te_msg:
            import yaml as _yaml, tempfile as _tmp, os as _os
            _tf = _tmp.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
            _yaml.dump(eval_config, _tf)
            _tf.close()
            try:
                results = module.run_evaluation(_tf.name)
            finally:
                _os.unlink(_tf.name)
        else:
            raise

    with open("{result_file}", "w") as f:
        json.dump({{"status": "success", "results": results}}, f)

except Exception as e:
    with open("{result_file}", "w") as f:
        json.dump({{"status": "error", "error": traceback.format_exc()}}, f)
"""

    def __init__(self, timeout: int = 300, python_executable: str = None):
        self.timeout = timeout
        self.python = python_executable or sys.executable
        # Preserve code to this directory on timeout for debugging (None=use project default path)
        self.debug_dump_dir: Optional[str] = None

    def run(
        self,
        code_package: dict[str, str],
        eval_config: dict,
    ) -> dict:
        """
        Run a code package in a subprocess and return evaluation results.

        Args:
            code_package: {file_path: file_content}
            eval_config: {snr_points, num_samples, metrics, ...}

        Returns:
            Performance data dict
        """
        with tempfile.TemporaryDirectory(prefix="autowispa_") as tmpdir:
            bus = get_event_bus()
            # 1. Write code files
            self._write_code(code_package, tmpdir)

            # 2. Ensure evaluate.py exists or create a default version
            eval_script = self._ensure_eval_script(tmpdir)

            # 3. Write configuration
            config_file = os.path.join(tmpdir, "eval_config.json")
            with open(config_file, "w") as f:
                json.dump(eval_config, f)

            # 4. Write result placeholder file
            result_file = os.path.join(tmpdir, "results.json")

            # 5. Generate runner script
            # Use repr() to serialize eval_config as a valid Python literal
            # Avoids JSON null → Python NameError: 'null' not defined
            eval_config_python = repr(eval_config)
            runner_code = self.RUNNER_TEMPLATE.format(
                code_dir=tmpdir,
                eval_script=eval_script,
                eval_config_json=eval_config_python,
                result_file=result_file,
            )
            runner_path = os.path.join(tmpdir, "_runner.py")
            with open(runner_path, "w") as f:
                f.write(runner_code)

            # 6. Execute
            stdout_file = os.path.join(tmpdir, "_stdout.txt")
            stderr_file = os.path.join(tmpdir, "_stderr.txt")
            proc = None
            try:
                import logging as _logging
                _logger = _logging.getLogger(__name__)
                _logger.info("[Sandbox] Starting subprocess (timeout %ds): %s", self.timeout, runner_path)
                bus.emit_sandbox_start("simulation", {"timeout": self.timeout, "runner": runner_path})

                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []

                def _pump(stream, sink: list[str], emitter) -> None:
                    try:
                        for line in iter(stream.readline, ""):
                            if not line:
                                break
                            sink.append(line)
                            emitter("simulation", line)
                    finally:
                        try:
                            stream.close()
                        except Exception:
                            pass

                started_at = time.time()

                proc = subprocess.Popen(
                    [self.python, runner_path],
                    cwd=tmpdir,
                    env={
                        **os.environ,
                        "NUMEXPR_MAX_THREADS": os.environ.get("NUMEXPR_MAX_THREADS", "12"),
                    },
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                stdout_thread = threading.Thread(target=_pump, args=(proc.stdout, stdout_chunks, bus.emit_sandbox_stdout), daemon=True)
                stderr_thread = threading.Thread(target=_pump, args=(proc.stderr, stderr_chunks, bus.emit_sandbox_stderr), daemon=True)
                stdout_thread.start()
                stderr_thread.start()

                try:
                    proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    _logger.warning("[Sandbox] Subprocess timed out (%ds), force killed", self.timeout)
                    _stderr_snippet = "".join(stderr_chunks)[-3000:]
                    if _stderr_snippet:
                        _logger.warning("[Sandbox stderr at timeout]\\n%s", _stderr_snippet)
                    _debug_dir = self._dump_debug_dir(tmpdir)
                    if _debug_dir:
                        _logger.warning("[Sandbox] Timed-out code saved to: %s", _debug_dir)
                    with open(stdout_file, "w", encoding="utf-8") as _fout:
                        _fout.write("".join(stdout_chunks))
                    with open(stderr_file, "w", encoding="utf-8") as _ferr:
                        _ferr.write("".join(stderr_chunks))
                    bus.emit_sandbox_end("simulation", {"status": "timeout", "elapsed": f"{self.timeout:.2f}s"})
                    return {
                        "status": "error",
                        "error": f"Execution timed out after {self.timeout}s",
                        "stderr_snippet": _stderr_snippet,
                        "debug_dir": _debug_dir or "",
                    }

                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                with open(stdout_file, "w", encoding="utf-8") as _fout:
                    _fout.write("".join(stdout_chunks))
                with open(stderr_file, "w", encoding="utf-8") as _ferr:
                    _ferr.write("".join(stderr_chunks))

                returncode = proc.returncode

                # Read output
                try:
                    with open(stdout_file) as _f:
                        stdout_text = _f.read()
                except Exception:
                    stdout_text = ""
                try:
                    with open(stderr_file) as _f:
                        stderr_text = _f.read()
                except Exception:
                    stderr_text = ""

                if stdout_text:
                    _logger.debug("[Sandbox stdout]\\n%s", stdout_text[-2000:])
                if stderr_text and returncode != 0:
                    _logger.warning("[Sandbox stderr]\\n%s", stderr_text[-2000:])

                elapsed = time.time() - started_at
                bus.emit_sandbox_end("simulation", {"status": "success" if returncode == 0 else f"rc={returncode}", "elapsed": f"{elapsed:.2f}s"})

                if os.path.exists(result_file):
                    with open(result_file) as f:
                        payload = json.load(f)
                    if isinstance(payload, dict):
                        if payload.get("status") == "success":
                            return {
                                "status": "success",
                                "results": payload.get("results", {}),
                            }
                        if payload.get("status") == "error":
                            err_tb = payload.get("error", "Unknown sandbox error")
                            # ── Auto-install missing dependencies and retry once ───────────────
                            missing = self._extract_missing_modules(err_tb)
                            if missing:
                                installed = self._try_auto_install(missing)
                                if installed:
                                    _logger.info("[Sandbox] Installed %s, re-executing...", installed)
                                    proc2 = subprocess.run(
                                        [self.python, runner_path],
                                        cwd=tmpdir,
                                        env={
                                            **os.environ,
                                            "NUMEXPR_MAX_THREADS": os.environ.get("NUMEXPR_MAX_THREADS", "12"),
                                        },
                                        stdin=subprocess.DEVNULL,
                                        capture_output=True,
                                        text=True,
                                        timeout=self.timeout,
                                    )
                                    if os.path.exists(result_file):
                                        try:
                                            payload = json.load(open(result_file))
                                        except Exception:
                                            pass
                                    if isinstance(payload, dict) and payload.get("status") == "success":
                                        return {
                                            "status": "success",
                                            "results": payload.get("results", {}),
                                        }
                                    err_tb = payload.get("error", err_tb) if isinstance(payload, dict) else err_tb
                            return {
                                "status": "error",
                                "error": err_tb,
                            }
                    return {"status": "error", "error": "Invalid sandbox result payload"}
                else:
                    return {
                        "status": "error",
                        "error": stderr_text[-2000:] if stderr_text else "Unknown error (no result file)",
                        "stdout": stdout_text[-1000:] if stdout_text else "",
                    }

            except Exception as e:
                if proc is not None:
                    try:
                        proc.kill()
                        proc.wait()
                    except Exception:
                        pass
                get_event_bus().emit_sandbox_end("simulation", {"status": "error", "elapsed": "failed"})
                return {"status": "error", "error": str(e)}

    def run_notebook(self, notebook: dict, eval_config: dict) -> dict:
        return self.run(_build_notebook_code_package(notebook), eval_config)

    def _write_code(self, code_package: dict[str, str], tmpdir: str):
        """Write code package to temporary directory."""
        for filepath, content in code_package.items():
            full_path = Path(tmpdir) / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _extract_missing_modules(traceback_text: str) -> list[str]:
        """Extract missing module names from ImportError / ModuleNotFoundError traceback."""
        import re
        # ModuleNotFoundError: No module named 'foo.bar'  → foo
        # ImportError: cannot import name 'X' from 'foo'  → foo
        patterns = [
            re.compile(r"No module named ['\"]([a-zA-Z0-9_]+)"),
            re.compile(r"cannot import name .+ from ['\"]([a-zA-Z0-9_]+)"),
            re.compile(r"ImportError: ['\"]([a-zA-Z0-9_]+)['\"] is not installed"),
        ]
        found: list[str] = []
        for pat in patterns:
            for m in pat.finditer(traceback_text):
                mod = m.group(1)
                if mod not in found:
                    found.append(mod)
        # Filter out builtin/local modules (take top-level for dotted subpackages, ignore project modules)
        local_tops = {"algorithms", "evaluation", "system_model", "training", "utils", "simulation", "graph", "agents"}
        return [mod for mod in found if mod not in local_tops]

    # Module name → pip package name mapping (common discrepancies)
    _MODULE_TO_PACKAGE: dict[str, str] = {
        "sklearn": "scikit-learn",
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "yaml": "pyyaml",
        "sionna": "sionna",
        "deepmimo": "deepmimo",
        "torchsig": "torchsig",
        "commpy": "commpy",
        "cvxpy": "cvxpy",
        "h5py": "h5py",
        "tqdm": "tqdm",
    }

    def _try_auto_install(self, missing_modules: list[str]) -> list[str]:
        """Attempt pip install for missing modules, return list of successfully installed package names."""
        import logging as _ll
        _logger = _ll.getLogger(__name__)
        installed: list[str] = []
        for mod in missing_modules:
            pkg = self._MODULE_TO_PACKAGE.get(mod, mod)
            _logger.info("[Sandbox] Attempting auto-install of missing dependency: %s (import %s)", pkg, mod)
            try:
                result = subprocess.run(
                    [self.python, "-m", "pip", "install", pkg, "--quiet"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    _logger.info("[Sandbox] Successfully installed: %s", pkg)
                    installed.append(pkg)
                else:
                    _logger.warning("[Sandbox] Installation failed: %s\n%s", pkg, result.stderr[-500:])
            except Exception as exc:
                _logger.warning("[Sandbox] Installation exception: %s → %s", pkg, exc)
        return installed

    def _ensure_eval_script(self, tmpdir: str) -> str:
        """Ensure the evaluation script exists."""
        for root, _, files in os.walk(tmpdir):
            for f in files:
                if f == "evaluate.py":
                    return os.path.join(root, f)

        default_eval = os.path.join(tmpdir, "evaluate.py")
        with open(default_eval, "w") as f:
            f.write(DEFAULT_EVALUATE_SCRIPT)
        return default_eval

    def _dump_debug_dir(self, tmpdir: str) -> str:
        """Copy code files from tmpdir to a persistent debug directory, return target path (empty string on failure)."""
        import time as _time
        try:
            base = Path(self.debug_dump_dir) if self.debug_dump_dir else (
                Path(__file__).resolve().parents[1] / "experiments" / "sandbox_debug"
            )
            dest = base / f"timeout_{int(_time.time())}"
            dest.mkdir(parents=True, exist_ok=True)
            for src_path in Path(tmpdir).rglob("*"):
                if src_path.is_file() and (
                    src_path.suffix == ".py"
                    or src_path.name in ("_stderr.txt", "_stdout.txt", "eval_config.json")
                ):
                    rel = src_path.relative_to(tmpdir)
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, target)
            return str(dest)
        except Exception:
            return ""


DEFAULT_EVALUATE_SCRIPT = """
import json
import numpy as np


def run_evaluation(config: dict) -> dict:
    variable_points = config.get("variable_points", config.get("snr_points", list(range(-10, 31, 5))))
    num_samples = config.get("num_samples", 1000)

    results = {}
    from algorithms.proposed.model import ProposedModel
    model = ProposedModel()
    results["metric_vs_operating_point"] = {
        "x": variable_points,
        "proposed": _simulate_metric(model, variable_points, num_samples),
    }
    return results


def _simulate_metric(model, variable_points, num_samples):
    rng = numpy.random.default_rng(42)
    return [-5.0 - pt * 0.8 + rng.normal(0, 0.5) for pt in variable_points]
"""


class DockerSandbox:
    """Docker container-based code sandbox (production-grade isolation)."""

    DEFAULT_IMAGE = "autowispa-sandbox:latest"

    def __init__(
        self,
        image: str = None,
        timeout: int = 3600,
        memory_limit: str = "16g",
        cpu_limit: float = 4.0,
    ):
        self.image = image or self.DEFAULT_IMAGE
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit

    def run(self, code_package: dict[str, str], eval_config: dict) -> dict:
        try:
            import docker
            client = docker.from_env()
        except ImportError:
            return {"status": "error", "error": "docker package not installed; pip install docker"}
        except Exception as e:
            return {"status": "error", "error": f"Docker unavailable: {e}"}

        with tempfile.TemporaryDirectory(prefix="autowispa_docker_") as tmpdir:
            for filepath, content in code_package.items():
                full_path = Path(tmpdir) / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")

            result_file = os.path.join(tmpdir, "results.json")
            try:
                client.containers.run(
                    image=self.image,
                    command=["python", "/workspace/evaluate.py"],
                    volumes={tmpdir: {"bind": "/workspace", "mode": "rw"}},
                    mem_limit=self.memory_limit,
                    nano_cpus=int(self.cpu_limit * 1e9),
                    remove=True,
                    detach=False,
                    timeout=self.timeout,
                )
                if os.path.exists(result_file):
                    with open(result_file) as f:
                        return json.load(f)
            except Exception as e:
                return {"status": "error", "error": str(e)}

        return {"status": "error", "error": "Docker run completed but no result file"}

    def run_notebook(self, notebook: dict, eval_config: dict) -> dict:
        return self.run(_build_notebook_code_package(notebook), eval_config)
