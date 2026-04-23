"""
Problem Analyzer Agent
Converts user natural-language descriptions into a structured TaskSpec.
"""

from __future__ import annotations
import json
import re
from typing import Optional
from utils.llm_client import LLMClient


LEGACY_SYSTEM_PARAM_MAP = {
    "carrier_frequency": "carrier_freq_ghz",
    "bandwidth": "bandwidth_mhz",
    "waveform": "waveform",
    "channel_model": "channel_model",
    "snr_range_dB": "snr_range_db",
    "modulation": "modulation",
}


TASK_SPEC_SCHEMA = {
    # ═══════════════════════════════════════════════
    #  Layer 1: Problem Understanding
    # ═══════════════════════════════════════════════
    "problem_understanding": {
        "task_category": (
            "Primary category (one or more):\n"
            "  detection | estimation | recovery | "
            "beamforming | tracking | localization | others \n"
            "Use '|' to indicate multi-category problems."
        ),
        "problem_statement": (
            "In 2-4 sentences, describe:\n"
            "  (1) What is observed (input signal/measurement)?\n"
            "  (2) What needs to be estimated/detected/designed (output)?\n"
            "  (3) What is the core mathematical relationship between them?"
        ),
        "exploitable_structure": (
            "Mathematical structure that an algorithm can exploit:\n"
            "  e.g., channel sparsity, low-rank covariance, Toeplitz/Hankel matrix structure, "
            "group sparsity, temporal correlation, manifold structure, shift-invariance.\n"
            "  Be specific: name the structure and how it constrains the problem.\n"
            "  Write 'none_identified' if genuinely unclear."
        ),
    },

    # ═══════════════════════════════════════════════
    #  Layer 2: System Model
    # ═══════════════════════════════════════════════
    "system_model": {
        "waveform": (
            "Signal/waveform type. Examples: single-carrier, OFDM, FMCW, SC-FDMA, OTFS.\n"
            "Use 'custom' for non-standard waveforms and describe in "
            "additional_params."
        ),
        "antenna_config": {
            "num_tx": "Number of Tx antennas (int or null)",
            "num_rx": "Number of Rx antennas (int or null)",
            "array_type": "ULA / UPA / distributed / other (optional)",
            "additional_elements": (
                "Dict for scenario-specific elements, e.g.:\n"
                "  {num_ris_elements: 64} or {num_virtual: 128}\n"
                "  Empty {} if not applicable."
            ),
        },
        "channel_model": {
            "model_name": (
                "Channel/propagation model name. "
                "Examples: Rayleigh, Rician, 3GPP_CDL-C, free_space.\n"
                "Use 'custom' and describe in 'channel_properties' "
                "for non-standard models."
            ),
            "channel_properties": (
                "Key statistical/structural properties (list of tags):\n"
                "  e.g., [sparse, time_varying, frequency_selective, "
                "spatially_correlated, LoS_dominant, near_field]\n"
                "  This field is critical for algorithm design — "
                "fill even when model_name is standard."
            ),
        },
        "operating_conditions": {
            "carrier_freq_ghz": "Carrier frequency (GHz) or null",
            "bandwidth_mhz": "Bandwidth (MHz) or null",
            "mobility_kmh": "Mobility (km/h) or null",
        },
        "additional_params": (
            "Dict of scenario-specific parameters not covered above.\n"
            "  Examples: {num_subcarriers: 1024, cp_length: 72, "
            "prf_hz: 1000, num_targets: 3}\n"
            "  Keep only parameters that directly affect algorithm design."
        ),
    },

    # ═══════════════════════════════════════════════
    #  Layer 3: Evaluation Specification (runtime key: performance_targets)
    # ═══════════════════════════════════════════════
    "performance_targets": {
        "primary_metric": (
            "Primary performance metric with unit.\n"
            "  Examples: NMSE_dB, BER, RMSE_deg, sum_rate_bps_Hz, P_d_at_P_fa_1e-3.\n"
            "  Choose the single most important metric."
        ),
        "secondary_metrics": (
            "List of secondary metrics in priority order.\n"
            "  e.g., [complexity_flops, convergence_iterations, latency_ms]\n"
            "  Empty [] if only primary metric matters."
        ),
        "theoretical_bound": (
            "Known theoretical lower/upper bound, if applicable:\n"
            "  e.g., 'CRB for DoA estimation', 'channel capacity', "
            "'matched filter bound'.\n"
            "  Write 'unknown' if not applicable or not known."
        ),
        "baseline_algorithms": (
            "Methods to compare against (user-specified or auto-selected).\n"
            "  If user specifies: list them directly.\n"
            "  If not specified: write 'auto' and the downstream planner "
            "will select appropriate baselines.\n"
            "  Examples: [LS, MMSE, OMP] or [ZF, MMSE_SIC] or 'auto'."
        ),
        "target_value": (
            "Quantitative target, if any. Format: {metric: value, at_snr_db: X}\n"
            "  e.g., {NMSE_dB: -20, at_snr_db: 10}, {Pd: 0.9, at_p_fa: 1e-3}\n"
            "  Null if no specific target; relative goals go in "
            "problem_understanding.problem_statement."
        ),
    },

    # ═══════════════════════════════════════════════
    #  Layer 4: Design Constraints
    # ═══════════════════════════════════════════════
    "constraints": {
        "complexity": (
            "Computational constraint in natural language.\n"
            "  e.g., 'O(N log N) per iteration', 'parameters < 500k', "
            "'no matrix inversion larger than 64x64'.\n"
            "  Null if unconstrained."
        ),
        "data_availability": (
            "Training data assumption:\n"
            "  'synthetic_only' — only simulated data available\n"
            "  'offline_dataset' — labeled dataset exists\n"
            "  'few_shot_online' — small amount of online adaptation data\n"
            "  'no_training_data' — purely model-based, no data-driven component\n"
            "  'not_applicable' — problem does not involve learning"
        ),
    },

    # ═══════════════════════════════════════════════
    #  Layer 5: Design Preferences
    # ═══════════════════════════════════════════════
    "design_preferences": {
        "approach": (
            "User's preferred approach direction (SOFT hint, not mandate):\n"
            "  'auto' — let the system decide (RECOMMENDED default)\n"
            "  'classical_signal_processing' / 'optimization_based' / "
            "'deep_learning' / 'deep_unfolding' / 'hybrid'\n"
            "  The planner SHOULD override this if analysis suggests "
            "a different approach is fundamentally more suitable."
        ),
        "interpretability": "high / medium / low — preference, not constraint",
        "online_adaptation": "bool — whether online adaptation is desired",
    },
}

REQUIRED_FIELDS = [
    # Only keep core fields that cannot be reasonably inferred
    "task_category",
    "performance_targets.primary_metric",
    # task_description / target_value / antenna_config can be inferred by the LLM or set to null
]


class ProblemAnalyzerAgent:
    """
    Problem Analyzer Agent

    Workflow:
    1. Analyze user input and extract all known information
    2. Identify missing key information and generate clarification questions
    3. Populate the complete TaskSpec JSON
    4. Infer reasonable default parameters based on task type
    """

    SYSTEM_PROMPT = """
    # ROLE
    You are a senior wireless signal processing systems engineer.
    You convert algorithm design requests into precise, structured task specifications.

    # DOMAIN MENTAL MODEL — A Coordinate System, Not a Category Box

    Every wireless signal processing task can be located in a continuous
    problem space spanned by three orthogonal dimensions.
    Use these dimensions as a THINKING FRAMEWORK to analyze any request,
    including those that do not fit neatly into textbook categories.

    ## Dimension 1 · Processing Object
    What physical quantity is being processed or estimated?

    Think in terms of the INFORMATION HIERARCHY in wireless systems:
        Physical layer:   waveform, channel, interference, noise
        Parameter level:  delay, Doppler, angle, amplitude, phase
        Spatial level:    beamspace, subspace, array manifold
        Strategy level:   precoding, power, resource allocation, codebook
        Semantic level:   position, trajectory, environment, intent

    A task may target ONE level or SPAN MULTIPLE levels.
    This dimension determines the I/O interface and natural evaluation metrics.

    ## Dimension 2 · Mathematical Essence
    What canonical mathematical problem is being solved?

    This dimension is a spectrum. Common regions include:
        - Estimation (parametric, nonparametric, signal recovery)
        - Detection & hypothesis testing
        - Filtering & sequential inference
        - Optimization & resource design
        - Decomposition & separation
        - Coding & information-theoretic

    But many real problems are HYBRIDS or lie BETWEEN these regions.
    Identify the mathematical core from the problem physics, not by
    pattern-matching to a fixed list.

    KEY INSIGHT: problems sharing the same canonical model (e.g., y = Ax + n) across different physical domains (channel estimation, DOA, MIMO detection, compressed sensing, image reconstruction …) can leverage the same algorithm families. Always flag such cross-domain connections.

    ## Dimension 3 · System Context
    What is the wireless system configuration?

    Characterize along these (non-exhaustive) facets:
        - Antenna topology (SISO / MIMO / massive-MIMO / distributed / RIS-aided …)
        - Waveform (OFDM / SC / FMCW / spread-spectrum / custom …)
        - Frequency band & propagation regime
        - Channel dynamics (static / block-fading / fast-fading / doubly-selective …)
        - Functional mode (communication / sensing / ISAC / localization / control …)
        - Hardware constraints (quantization / nonlinearity / phase noise / …)

    Not every facet is relevant for every task. Focus on what MATTERS for the
    algorithm design.

    # ANALYTICAL WORKFLOW

    1. UNDERSTAND — Read the request; identify what the user ultimately wants
        to achieve (not just what they literally asked for).

    2. DECOMPOSE — Locate the problem in the 3D space above.
        If the problem is novel or cross-cutting, say so explicitly rather than
        forcing it into a conventional category.

    3. EXTRACT & INFER — Gather all stated parameters.
        For unstated parameters, infer from PHYSICAL FIRST PRINCIPLES:
            · What does the physics of the scenario constrain?
            · What are standard/practical values in this operating regime?
            · What would a domain expert choose as a reasonable default?
        DO NOT memorize fixed lookup tables. Reason from the scenario each time.

    4. POPULATE — Fill the complete task specification JSON. If any parameter is missing, always infer a reasonable default and record it in assumptions_made.

    # INFERENCE GUIDELINES (Principles, Not Rules)

    When the user is vague, translate qualitative descriptions into
    concrete parameters by reasoning about the PHYSICAL SCENARIO:

        · "High mobility" → estimate speed from context (vehicular? HSR? UAV?),
            then derive coherence time, Doppler spread, appropriate channel model.
        · Unspecified channel → choose based on propagation environment and
            carrier frequency. Justify your choice briefly.
        · Unspecified SNR range → consider the operating regime of the algorithm
            class (e.g., detection problems need low-SNR; BER curves need wide range).
        · Missing array parameters → infer from spatial resolution requirements
            or system context.

    General principle: infer what a COMPETENT ENGINEER would assume given
    the stated context, and record your assumptions transparently.

    # OUTPUT FORMAT

    Strict JSON. No prose outside the JSON block.

    Always output:
    {
        "status": "complete",
        "task_spec": { ... }
    }

    SCHEMA FILLING RULES:
        · Values must be CONCRETE (numbers, strings, null). Never copy type descriptions.
        · task_category: free-form. Combine categories or coin new ones if needed.
        · primary_metric: free-form. Not limited to any predefined set.
        · performance_targets.target_value: null if no quantitative target; describe goals in task_description.
        · additional_params: task-specific dict; {} if nothing special.
        · system_model fields: fill null for genuinely inapplicable fields
            (e.g., num_antennas_tx = null for a pure detection problem on a single sensor).
        · assumptions_made: MANDATORY. Transparency about inferred values.
    """

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def _max_tokens(self, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(self.llm, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def analyze(
        self,
        user_query: str,
        conversation_history: list[dict],
    ) -> dict:
        """
        Analyze user input and return the task specification.

        Returns:
            dict with keys: status, task_spec (or questions + partial_spec)
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            *conversation_history,
            {
                "role": "user",
                "content": f"Please analyze the following requirements and output the task specification:\n\n{user_query}\n\n"
                           f"Reference Schema:\n{json.dumps(TASK_SPEC_SCHEMA, ensure_ascii=False, indent=2)}",
            },
        ]

        response = self.llm.chat(
            messages,
            max_tokens=self._max_tokens("problem_analysis"),
            node_name="problem_analysis",
        )

        result = self._parse_json_response(response)
        # 强制推断所有参数，始终输出 status: complete
        if isinstance(result.get("task_spec"), dict):
            result["task_spec"] = self._normalize_task_spec(result["task_spec"])
            result["status"] = "complete"
            return result
        # 若未能解析，返回空spec但status: complete
        return {"status": "complete", "task_spec": {}}

    def refine_with_knowledge(self, task_spec: dict, retrieved_knowledge: dict) -> dict:
        """Refine the existing task specification using retrieval summaries and paper evidence.

        The goal is not to change user intent, but to tighten terminology, assumptions,
        baselines, and evaluation focus using retrieved evidence.
        """
        compact_knowledge = {
            "paper_titles": [
                {
                    "title": item.get("title"),
                    "year": item.get("year"),
                    "source": item.get("source"),
                }
                for item in (retrieved_knowledge.get("relevant_papers") or [])[:6]
            ],
            "relevant_algorithms": [
                item if isinstance(item, str) else (item or {}).get("name", "")
                for item in (retrieved_knowledge.get("relevant_algorithms") or [])[:5]
                if item
            ],
            "design_insights": (retrieved_knowledge.get("design_insights") or "")[:10000],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    self.SYSTEM_PROMPT
                    + "\n\nAdditional refinement instruction: refine the existing task specification using the retrieved knowledge. "
                    "Preserve the original user intent, but strengthen technical wording, baseline selection, assumptions, "
                    "and evaluation focus when justified by the evidence. Do not remove existing fields that are absent from "
                    "the retrieved evidence, and do not replace a user-aligned primary metric with a generic metric unless the "
                    "user explicitly changed the objective. Return strict JSON in the same output format."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Existing Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"## Retrieved Knowledge Summary\n```json\n{json.dumps(compact_knowledge, ensure_ascii=False, indent=2)}\n```\n\n"
                    "Refine the task specification and return strict JSON."
                ),
            },
        ]
        response = self.llm.chat(
            messages,
            max_tokens=self._max_tokens("problem_analysis_refine"),
            node_name="problem_analysis_refine",
        )
        parsed = self._parse_json_response(response)
        if parsed.get("status") == "complete" and isinstance(parsed.get("task_spec"), dict):
            return parsed["task_spec"]
        if isinstance(parsed.get("partial_spec"), dict):
            return parsed["partial_spec"]
        return task_spec

    def check_completeness(self, task_spec: dict) -> tuple[bool, list[str]]:
        """
        Check whether the task specification contains all required fields.

        Returns:
            (is_complete, list_of_missing_fields)
        """
        missing = []
        for field_path in REQUIRED_FIELDS:
            keys = field_path.split(".")
            obj = task_spec
            for k in keys:
                if not isinstance(obj, dict) or k not in obj:
                    missing.append(field_path)
                    break
                obj = obj[k]
            else:
                if obj is None or obj == "":
                    missing.append(field_path)

        return len(missing) == 0, missing

    def build_clarification_questions(self, missing_fields: list[str]) -> list[str]:
        """Build clarification questions based on missing fields."""
        field_questions = {
            "task_category": "What type of task is this? (e.g. channel_estimation, mimo_detection, doa_estimation, isac — feel free to describe)",
            "performance_targets.primary_metric": "What is the primary performance metric to optimize? (e.g. NMSE, BER, RMSE_deg, P_d)",
        }
        questions = [
            field_questions.get(f, f"Please provide the value for {f}") for f in missing_fields[:2]
        ]
        if not questions:
            questions = [
                "Please clarify the task type and primary performance metric so the simulation can be configured correctly."
            ]
        return questions

    def generate_clarification(self, missing_fields: list[str]) -> str:
        """Generate clarification questions based on missing fields."""
        questions = self.build_clarification_questions(missing_fields)
        return "To design the algorithm precisely, please provide the following information:\n" + "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(questions)
        )

    @staticmethod
    def _extract_json_dict(text: str) -> Optional[dict]:
        stripped = (text or "").strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        fence_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
        for candidate in fence_matches:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        decoder = json.JSONDecoder()
        start = stripped.find("{")
        while start != -1:
            try:
                parsed, _ = decoder.raw_decode(stripped[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            start = stripped.find("{", start + 1)

        return None

    @classmethod
    def _normalize_task_spec(cls, task_spec: dict) -> dict:
        if not isinstance(task_spec, dict):
            return {}

        spec = dict(task_spec)

        # Bridge newer nested schema back to runtime-compatible top-level fields.
        problem_understanding = spec.get("problem_understanding")
        if isinstance(problem_understanding, dict):
            if not spec.get("task_category") and problem_understanding.get("task_category"):
                spec["task_category"] = problem_understanding.get("task_category")
            if not spec.get("task_description") and problem_understanding.get("problem_statement"):
                spec["task_description"] = problem_understanding.get("problem_statement")
            # Bridge exploitable_structure to top level so downstream agents can access it directly
            if not spec.get("exploitable_structure") and problem_understanding.get("exploitable_structure"):
                spec["exploitable_structure"] = problem_understanding.get("exploitable_structure")

        evaluation = spec.get("evaluation")
        performance_targets = spec.get("performance_targets")
        if not isinstance(performance_targets, dict):
            performance_targets = {}
            spec["performance_targets"] = performance_targets
        if isinstance(evaluation, dict):
            if performance_targets.get("primary_metric") in (None, "") and evaluation.get("primary_metric") not in (None, ""):
                performance_targets["primary_metric"] = evaluation.get("primary_metric")
            if performance_targets.get("secondary_metrics") in (None, "") and evaluation.get("secondary_metrics") not in (None, ""):
                performance_targets["secondary_metrics"] = evaluation.get("secondary_metrics")
            if performance_targets.get("baseline_algorithms") in (None, "") and evaluation.get("baseline_algorithms") not in (None, ""):
                performance_targets["baseline_algorithms"] = evaluation.get("baseline_algorithms")
            if performance_targets.get("target_value") in (None, "") and evaluation.get("target_performance") not in (None, ""):
                performance_targets["target_value"] = evaluation.get("target_performance")

        design_preferences = spec.get("design_preferences")
        if isinstance(design_preferences, dict):
            if design_preferences.get("approach") in (None, "") and design_preferences.get("approach_hint") not in (None, ""):
                design_preferences["approach"] = design_preferences.get("approach_hint")

        legacy_system_params = spec.get("system_params")
        system_model = spec.get("system_model")
        if not isinstance(system_model, dict):
            system_model = {}
            spec["system_model"] = system_model

        channel_model = system_model.get("channel_model")
        if isinstance(channel_model, dict):
            model_name = channel_model.get("model_name")
            if model_name not in (None, ""):
                system_model["channel_model"] = model_name
            props = channel_model.get("channel_properties")
            if props not in (None, "") and system_model.get("channel_properties") in (None, ""):
                system_model["channel_properties"] = props

        operating_conditions = system_model.get("operating_conditions")
        if isinstance(operating_conditions, dict):
            for key in ("carrier_freq_ghz", "bandwidth_mhz", "mobility_kmh"):
                if system_model.get(key) in (None, "") and operating_conditions.get(key) not in (None, ""):
                    system_model[key] = operating_conditions.get(key)

        if isinstance(legacy_system_params, dict):
            for legacy_key, target_key in LEGACY_SYSTEM_PARAM_MAP.items():
                value = legacy_system_params.get(legacy_key)
                if value is not None and system_model.get(target_key) in (None, ""):
                    system_model[target_key] = value

            antenna_config = system_model.get("antenna_config")
            if not isinstance(antenna_config, dict):
                antenna_config = {}
                system_model["antenna_config"] = antenna_config

            if legacy_system_params.get("num_antennas_tx") is not None and antenna_config.get("num_tx") is None:
                antenna_config["num_tx"] = legacy_system_params.get("num_antennas_tx")
            if legacy_system_params.get("num_antennas_rx") is not None and antenna_config.get("num_rx") is None:
                antenna_config["num_rx"] = legacy_system_params.get("num_antennas_rx")

            additional_params = system_model.get("additional_params")
            if not isinstance(additional_params, dict):
                additional_params = {}
                system_model["additional_params"] = additional_params
            if isinstance(legacy_system_params.get("additional_params"), dict):
                for key, value in legacy_system_params["additional_params"].items():
                    additional_params.setdefault(key, value)

        if not spec.get("task_category"):
            spec["task_category"] = cls._infer_task_category(spec)

        return spec

    @staticmethod
    def _infer_task_category(task_spec: dict) -> str:
        # Try to infer from legacy three_dimensions field
        three_dim = task_spec.get("three_dimensions")
        if isinstance(three_dim, dict):
            essence = str(three_dim.get("mathematical_essence") or "").lower()
            obj = str(three_dim.get("processing_object") or "").lower()
            combined = f"{essence} {obj}"
            if any(k in combined for k in ("angle", "doa", "direction of arrival", "bearing")):
                return "doa_estimation"
            if any(k in combined for k in ("channel", "csi", "propagation")):
                return "channel_estimation"
            if any(k in combined for k in ("detect", "hypothesis", "mimo")):
                return "mimo_detection"
            if any(k in combined for k in ("beam", "precod", "weight")):
                return "beamforming"
            if any(k in combined for k in ("track", "kalman", "locali")):
                return "tracking_localization"
            if any(k in combined for k in ("isac", "sensing", "radar")):
                return "isac"
        # Try task_description heuristic
        desc = str(task_spec.get("task_description") or "").lower()
        if any(k in desc for k in ("doa", "direction of arrival", "angle of arrival")):
            return "doa_estimation"
        if any(k in desc for k in ("channel estimation", "channel recovery")):
            return "channel_estimation"
        # Generic fallback
        return "wireless_signal_processing"

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        parsed = ProblemAnalyzerAgent._extract_json_dict(response)
        if isinstance(parsed, dict):
            return parsed
        # 若无法解析，返回空spec但status: complete
        return {"status": "complete", "task_spec": {}, "raw": response}
