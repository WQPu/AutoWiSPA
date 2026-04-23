"""
Simulation engine main class.
Integrates channel models, system models, and evaluators to provide a unified simulation interface.
"""

from __future__ import annotations
from typing import Optional


class WirelessSimulationEngine:
    """
    Wireless signal processing simulation engine.

    Supported system models:
    - SISO OFDM
    - MIMO-OFDM
    - Massive MIMO
    - OTFS (partial support)

    Supported channel models:
    - 3GPP TDL-A/B/C/D/E
    - 3GPP CDL-A/B/C/D/E
    - Rayleigh / Rician (statistical models)
    """

    SUPPORTED_CHANNELS = {
        "3GPP_TDL": ["TDL-A", "TDL-B", "TDL-C", "TDL-D", "TDL-E"],
        "3GPP_CDL": ["CDL-A", "CDL-B", "CDL-C", "CDL-D", "CDL-E"],
        "Statistical": ["Rayleigh", "Rician"],
    }

    SUPPORTED_METRICS = {
        "channel_estimation": ["NMSE", "MSE", "spectral_efficiency"],
        "detection": ["BER", "SER", "block_error_rate"],
        "beamforming": ["spectral_efficiency", "SINR", "energy_efficiency"],
        "general": ["FLOPs", "params", "latency_ms", "memory_MB"],
    }

    def __init__(self, backend: str = "numpy", gpu_enabled: bool = False):
        """
        Args:
            backend: "numpy" | "sionna" | "deepmimo" | "torchsig" | "matlab"
            gpu_enabled: whether to enable GPU acceleration
        """
        self.backend = backend
        self.gpu_enabled = gpu_enabled
        self._channel_lib = None
        self._system_lib = None

    def recommend_simulation_stack(self, task_spec: dict) -> dict:
        """Return the lightweight built-in simulation stack recommendation."""
        return {
            "primary": {"name": "numpy", "available": True},
            "recommended": [{"name": "numpy", "available": True}],
            "available": [{"name": "numpy", "available": True}],
            "context": "Use the built-in NumPy-based notebook execution path.",
        }

    def create_standard_scenario(self, task_spec: dict) -> dict:
        """
        Create a standard simulation scenario configuration based on task specification.

        Returns:
            scenario_config dict (can be passed to sandbox for execution)
        """
        system_model = task_spec.get("system_model", {})
        perf_targets = task_spec.get("performance_targets", {})

        operating_range = system_model.get("snr_range_db") or system_model.get("operating_range") or [-10, 30]
        range_step = 5 if (operating_range[1] - operating_range[0]) > 30 else 2.5

        return {
            "system": {
                "waveform": system_model.get("waveform", "single-carrier"),
                "num_tx": system_model.get("antenna_config", {}).get("num_tx", 16),
                "num_rx": system_model.get("antenna_config", {}).get("num_rx", 4),
                "num_subcarriers": system_model.get("num_subcarriers", 256),
                "modulation": system_model.get("modulation", "unknown"),
            },
            "channel": {
                "model": system_model.get("channel_model", "AWGN"),
                "mobility_kmh": system_model.get("mobility_kmh", 30),
                "carrier_freq_ghz": system_model.get("carrier_freq_ghz", 3.5),
            },
            "evaluation": {
                "variable_points": list(
                    map(
                        lambda x: round(operating_range[0] + x * range_step, 1),
                        range(int((operating_range[1] - operating_range[0]) / range_step) + 1),
                    )
                ),
                "primary_metric": perf_targets.get("primary_metric", "primary_metric"),
                "baselines": perf_targets.get("baseline_algorithms", []),
            },
        }

    def compute_flops(self, code_str: str, system_config: dict) -> Optional[int]:
        """
        Estimate algorithm FLOPs (approximate computation).

        Returns:
            Estimated FLOPs count, None if estimation is not possible.
        """
        # Simple heuristic: count matrix multiplications and key operations
        # For precise computation, use torchinfo or fvcore
        try:
            from utils.complexity_analyzer import ComplexityAnalyzer
            analyzer = ComplexityAnalyzer()
            return analyzer.estimate_from_code(code_str, system_config)
        except Exception:
            return None
