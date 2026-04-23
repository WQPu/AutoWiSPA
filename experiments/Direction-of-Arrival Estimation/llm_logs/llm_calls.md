
---
## [2026-04-21T15:53:51] poe / gpt-5.3-codex

### [system]

```

    # ROLE
    You are a senior wireless signal processing systems engineer.
    You convert algorithm design requests into precise, structured task specifications.

    # DOMAIN MENTAL MODEL — A Coordinate System, Not a Category Box

    Every wireless signal processing task can be located in a continuous
    problem space spanned by three orthogonal dimensions.
    Use these dimensions as a THI…(truncated)
```

### [user]

```
Please analyze the following requirements and output the task specification:

Two uncorrelated narrowband far-field sources separated by approximately 15° impinge on an 8-element half-wavelength-spaced ULA; $L = 200$ snapshots are available, nominal SNR is around 20 dB, and the number of sources $D = 2$ is assumed known. Design a DoA estimation algorithm, plot the spatial spectrum or pseudo-spectrum, provide DoA RMSE vs. SNR (0–30 dB) with the CRB as a reference lower bound, and characterize the resolution limit — the minimum SNR at which the two sources can still be separated.

Reference Schema:
{
  "problem_understanding": {
    "task_category": "Primary category (one or more):\n  detection | estimation | recovery | beamforming | tracking | localization | others \nUse '|' to indicate multi-category problems.",
    "problem_statement": "In 2-4 sentences, describe:\n  (1) What is observed (input signal/measurement)?\n  (2) What needs to be estimated/detected/designed (output)?\n  (3) What is the core mathematical relationship between them?",
    "exploitable_structure": "Mathematical structure that an algorithm can exploit:\n  e.g., channel sparsity, low-rank covariance, Toeplitz/H…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed){
  "status": "complete",
  "task_spec": {
    "problem_understanding": {
      "task_category": "estimation|localization",
      "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive noise. The objective is to estimate the two DoAs (D=2 known), generate the spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR=0 to 30 dB. The core model is x(t)=A(theta)s(t)+n(t), where A(theta) is the array manifold; subspace separation from the sample covariance enables high-resolution DoA estimation. Performance must be benchmarked against the CRB and include a resolution-threshold characterization (minimum SNR where two sources remain resolvable).",
      "exploitable_structure": "Vandermonde array manifold for ULA, rank-D signal subspace (D=2) in the covariance matrix, orthogonality between noise subspace and steering vectors (MUSIC principle), and approximately Toeplitz spatial covariance under uncorrelated far-field sources."
    },
    "system_model": {
      "waveform": "custom",
      "antenna_config": {
        "num_tx": null,
        "num_rx": 8,
        "array_type": "ULA",
        "additional_elements": {}
      },
      "channel_model": {
        "model_name": "free_space",
        "channel_properties": [
          "narrowband",
          "far_field",
          "plane_wave",
          "spatially_uncorrelated_sources",
          "quasi_static_over_snapshots",
          "awgn"
        ]
      },
      "operating_conditions": {
        "carrier_freq_ghz": null,
        "bandwidth_mhz": null,
        "mobility_kmh": null
      },
      "additional_params": {
        "num_sources": 2,
        "num_snapshots": 200,
        "inter_element_spacing_lambda": 0.5,
        "source_separation_deg": 15,
        "snr_nominal_db": 20,
        "snr_sweep_db": [0, 30],
        "num_sources_known": true,
        "recommended_algorithm": "MUSIC",
        "pseudospectrum_scan_range_deg": [-90, 90],
        "pseudospectrum_grid_step_deg": 0.1,
        "rmse_monte_carlo_trials": 1000,
        "resolution_success_rule": "two distinct peaks within +/-2 deg of true DoAs"
      }
    },
    "performance_targets": {
      "primary_metric": "RMSE_deg",
      "secondary_metrics": [
        "resolution_threshold_snr_db",
        "probability_of_resolution",
        "pseudospectrum_peak_separation_deg",
        "runtime_per_trial_ms"
      ],
      "theoretical_bound": "CRB for deterministic/stochastic two-source DoA estimation on ULA",
      "baseline_algorithms": "auto",
      "target_value": null
    },
    "constraints": {
      "complexity": null,
      "data_availability": "no_training_data"
    },
    "design_preferenc…(truncated)
```


---
## [2026-04-21T15:54:06] poe / gpt-5.3-codex

### [user]

```
You are an expert in wireless signal processing research. Extract exactly 3-5 focused keyword groups for searching academic papers.

Each keyword group should be a short phrase (3-6 words) targeting a DIFFERENT aspect:
- One for the core algorithm/technique (e.g., 'MUSIC algorithm DOA estimation')
- One for the system model (e.g., 'uniform linear array mutual coupling')
- One for the specific challenge (e.g., 'DOA estimation correlated noise low SNR')
- Optionally one for alternative approaches (e.g., 'sparse signal recovery direction finding')
- Optionally one for performance benchmark (e.g., 'Cramer-Rao bound angle estimation')

Requirements:
- Each group must be specific enough to find relevant IEEE/arXiv papers
- Do NOT include generic terms like 'wireless communication' alone
- Focus on terms that appear in paper titles and abstracts in this domain
- Output ONLY the keyword groups, one per line, nothing else

Task category: estimation|localization
Description: An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive noise. The objective is to estimate the two DoAs (D=2 known), generate the spatial pseudo-sp…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)MUSIC subspace DoA estimation
half-wavelength 8-element ULA model
two-source resolution threshold low SNR
Root-MUSIC versus ESPRIT comparison
DoA Cramer-Rao bound RMSE
```


---
## [2026-04-21T15:54:16] poe / gpt-5.3-codex

### [user]

```
Task: estimation|localization — An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive noise. The objective is to estimate the two DoAs (D=2 known), generate the spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR=0 to 30 dB. The core model is x(t)=A(theta)s(t)+n(t), where A(theta) is the array manifold; subspace separation from the sample covariance enables high-resolution DoA estimation. Performance must be benchmarked against the CRB and include a resolution-threshold characterization (minimum SNR where two sources remain resolvable).

Below are 15 candidate papers. Select the 5 MOST RELEVANT papers for this specific wireless signal processing task.

Relevance criteria:
- Paper must be about wireless/signal processing/communications (NOT astronomy, physics, biology, etc.)
- Paper should relate to the specific technique, algorithm, or system model in the task
- Prefer papers with concrete algorithmic contributions over surveys

[0] Performance Comparison of Music, Root-Music, And Esprit Algorithms for DOA Estimation Under Rayleigh Fading Channels
    Abstract: Accurate estimation of…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)0,7,8,3,1
```


---
## [2026-04-21T15:55:05] poe / gpt-5.3-codex

### [user]

```
Task category: estimation|localization
System model: custom, antenna config={'num_tx': None, 'num_rx': 8, 'array_type': 'ULA', 'additional_elements': {}}

== Retrieved relevant papers (total 4, showing first 4) ==
[P1] Weiss-Weinstein bound and SNR threshold analysis for DOA estimation with a cold array (2011, CrossRef(2011 IEEE Statistical Signal P), Citations:6)
     Abstract: (No abstract)

[P2] Stochastic Cramer-Rao bound of DOA estimates for non-circular Gaussian signals (, CrossRef(2004 IEEE International Confer), Citations:4)
     Abstract: (No abstract)

[P3] Cramer-Rao Lower Bound for DoA Estimation with RF Lens-Embedded Antenna Array (2016, arXiv)
     Abstract: In this paper, we consider the Cramer-Rao lower bound (CRLB) for estimation of a lens-embedded antenna array with deterministic parameters. Unlike CRLB of uniform linear array (ULA), it is noted that CRLB for direction of arrival (DoA) of lens-embedded antenna array is dominated by not only angle but characteristics of lens. Derivation is based on the approximation that amplitude of received signal with lens is approximated to Gaussian function. We confirmed that parameters needed to design a lens can be derived b…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed)## 1. **Core Technical Roadmap**

Given your retrieved set, the dominant technical line is **classical statistical signal processing for DoA estimation**, centered on:

1. **Estimator design (subspace / ML family)**  
   - Typical practical estimators in this space: MUSIC / Root-MUSIC / ML.
   - These estimators are then assessed against fundamental limits.

2. **Performance bounds and threshold behavior analysis**  
   - **CRLB**: local (high-SNR/asymptotic) lower bound for unbiased estimators.  
   - **WWB**: tighter/nonlocal bound that better captures **threshold effects** (sudden breakdown at low SNR or limited snapshots), especially highlighted in [P1].

3. **Model-aware extensions of the base DoA problem**  
   - **Signal impropriety / non-circularity** modifies covariance structure and Fisher information [P2].  
   - **Array front-end physics** (e.g., RF lens shaping amplitude profile) changes array manifold and therefore CRLB [P3].  
   - **Hardware non-idealities** (low-resolution ADC) modeled by AQNM to propagate quantization impact into estimator behavior and CRLB [P4].

So this paper set is not “deep unfolding / end-to-end DL / sparse CS-first”; it is mainly:
- **Physics + statistical modeling**
- **Classical estimators**
- **Theoretical bounds as evaluation backbone**

---

## 2. **Key Innovation Extraction**

### [P1] Weiss-Weinstein bound and SNR threshold analysis for DOA estimation with a cold array
*(No abstract provided; interpretation based on title and standard WWB usage.)*
- **Innovation A:** Uses **WWB** rather than only CRLB to characterize DoA performance in regimes where CRLB is optimistic (finite snapshots, low/moderate SNR).  
- **Innovation B:** Explicit focus on **SNR threshold behavior**—critical for practical design because many DoA algorithms exhibit abrupt degradation not predicted by CRLB.

### [P2] Stochastic Cramer-Rao bound of DOA estimates for non-circular Gaussian signals
*(No abstract provided; interpretation based on title and standard non-circular CRB literature.)*
- **Innovation A:** Derives stochastic CRLB under **non-circular (improper) Gaussian signal models**, where pseudo-covariance contains exploitable information.  
- **Innovation B:** Shows how model-aware processing can tighten theoretical bounds versus circular-only assumptions.

### [P3] CRLB for DoA Estimation with RF Lens-Embedded Antenna Array
- **Innovation A:** Incorporates **lens-induced amplitude shaping** (approximated Gaussian profile across elements) into FIM/CRLB derivation [P3].  
- **Innovation B:** Demonstrates that DoA accuracy depends not only on angle and SNR but also on **lens design parameters** (e.g., effective spread parameter), creatin…(truncated)
```


---
## [2026-04-21T15:55:10] poe / gpt-5.3-codex

### [user]

```
Task: estimation|localization — An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive noise. The objective is to estimate the two DoAs (D=2 known), generate the spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR=0 to 30 dB. The core model is x(t)=A(theta)s(t)+n(t), where A(theta) is the array manifold; subspace separation from the sample covariance enables high-resolution DoA estimation. Performance must be benchmarked against the CRB and include a resolution-threshold characterization (minimum SNR where two sources remain resolvable).

Papers:
- Weiss-Weinstein bound and SNR threshold analysis for DOA estimation with a cold array: 
- Stochastic Cramer-Rao bound of DOA estimates for non-circular Gaussian signals: 
- Cramer-Rao Lower Bound for DoA Estimation with RF Lens-Embedded Antenna Array: In this paper, we consider the Cramer-Rao lower bound (CRLB) for estimation of a lens-embedded antenna array with determ
- Impact of Low-Resolution ADC on DOA Estimation Performance for Massive MIMO Receive Array: In this paper, we present a new scenario of direction of arrival (DOA) estimatio…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)MUSIC
Root-MUSIC
ESPRIT
Stochastic Maximum Likelihood
Deterministic Maximum Likelihood
Cramér–Rao Bound
Weiss–Weinstein Bound
```


---
## [2026-04-21T15:55:37] poe / gpt-5.3-codex

### [system]

```

    # ROLE
    You are a senior wireless signal processing systems engineer.
    You convert algorithm design requests into precise, structured task specifications.

    # DOMAIN MENTAL MODEL — A Coordinate System, Not a Category Box

    Every wireless signal processing task can be located in a continuous
    problem space spanned by three orthogonal dimensions.
    Use these dimensions as a THI…(truncated)
```

### [user]

```
## Existing Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive noise. The objective is to estimate the two DoAs (D=2 known), generate the spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR=0 to 30 dB. The core model is x(t)=A(theta)s(t)+n(t), where A(theta) is the array manifold; subspace separation from the sample covariance enables high-resolution DoA estimation. Performance must be benchmarked against the CRB and include a resolution-threshold characterization (minimum SNR where two sources remain resolvable).",
    "exploitable_structure": "Vandermonde array manifold for ULA, rank-D signal subspace (D=2) in the covariance matrix, orthogonality between noise subspace and steering vectors (MUSIC principle), and approximately Toeplitz spatial covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additional…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed){
  "status": "complete",
  "task_spec": {
    "problem_understanding": {
      "task_category": "estimation|localization|subspace_spectral_estimation",
      "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
      "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
    },
    "system_model": {
      "waveform": "custom_narrowband",
      "antenna_config": {
        "num_tx": null,
        "num_rx": 8,
        "array_type": "ULA",
        "additional_elements": {}
      },
      "channel_model": "free_space_los",
      "operating_conditions": {
        "carrier_freq_ghz": null,
        "bandwidth_mhz": null,
        "mobility_kmh": 0
      },
      "additional_params": {
        "num_sources": 2,
        "num_snapshots": 200,
        "inter_element_spacing_lambda": 0.5,
        "source_separation_deg": 15,
        "source_angles_deg_default": [
          -7.5,
          7.5
        ],
        "snr_nominal_db": 20,
        "snr_sweep_db": [
          0,
          30
        ],
        "snr_step_db": 2,
        "snr_definition": "per_sensor_input_snr",
        "num_sources_known": true,
        "recommended_algorithm": "MUSIC",
        "baseline_algorithms_ordered": [
          "Root-MUSIC",
          "ESPRIT",
          "Deterministic Maximum Likelihood",
          "Stochastic Maximum Likelihood"
        ],
        "pseudospectrum_scan_range_deg": [
          -90,
          90
        ],
        "pseudospectrum_grid_step_deg": 0.1,
        "rmse_monte_carlo_trials": 1000,
        "resolution_success_rule": "exactly two dominant peaks, each within +/-2 deg of its nearest true DoA",
        "resolution_probability_target": 0.9,
        "threshold_gap_rule": "threshold region flagged when RMSE exceeds 3x stochastic CRB"
      },
      "channel_properties": [
        "narrowband",
        "far_field",
        "plane_wave",
        "spatially_uncorrelated_sources",
        "quasi_static_over_snapshots",
        "awgn"
      ]
    },
    "performance_targets": {
      "primary_metric": "RMSE_deg",
      "secondary_metrics": [
        "resolution…(truncated)
```


---
## [2026-04-21T15:57:25] poe / gpt-5.3-codex

### [system]

```
You are a senior wireless signal processing theorist and simulation designer.

Your task is to transform a structured task specification into one unified formalization package that is directly useful for simulation, algorithm design, and reporting.

Return one strict JSON object with this structure:
{
  "scenario_spec": {
    "signal_type": "...",
    "core_parameters": {"...": "..."},
    "snr_ra…(truncated)
```

### [user]

```
## Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization|subspace_spectral_estimation",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
    "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom_narrowband",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additiona…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed)Thinking... (13s elapsed)Thinking... (14s elapsed)Thinking... (15s elapsed)Thinking... (16s elapsed)Thinking... (17s elapsed)Thinking... (18s elapsed){
  "scenario_spec": {
    "signal_type": "narrowband far-field two-source ULA DoA estimation with subspace pseudo-spectrum localization",
    "core_parameters": {
      "array_type": "ULA",
      "num_rx": 8,
      "inter_element_spacing_lambda": 0.5,
      "num_sources": 2,
      "num_sources_known": true,
      "num_snapshots": 200,
      "source_angles_deg_default": [
        -7.5,
        7.5
      ],
      "source_separation_deg": 15,
      "noise_model": "spatially white circular complex Gaussian",
      "source_model": "uncorrelated narrowband complex Gaussian",
      "pseudospectrum_scan_range_deg": [
        -90,
        90
      ],
      "pseudospectrum_grid_step_deg": 0.1,
      "snr_definition": "per_sensor_input_snr",
      "snr_step_db": 2,
      "rmse_monte_carlo_trials": 1000,
      "resolution_success_rule": "exactly two dominant peaks, each within +/-2 deg of its nearest true DoA",
      "resolution_probability_target": 0.9,
      "threshold_gap_rule": "threshold region flagged when RMSE exceeds 3x stochastic CRB"
    },
    "snr_range_db": [
      0,
      30
    ],
    "test_scenarios": [
      {
        "name": "nominal_snr_sweep",
        "description": "Evaluate RMSE, pseudo-spectrum behavior, and CRB ratio over SNR 0:2:30 dB with fixed M=8, L=200, and true angles [-7.5, 7.5] deg.",
        "overrides": {}
      },
      {
        "name": "resolution_probability_curve",
        "description": "Estimate probability of resolution versus SNR using the provided two-peak +/-2 deg success rule and extract minimum SNR achieving probability >= 0.9.",
        "overrides": {}
      },
      {
        "name": "single_snr_pseudospectrum_diagnostics",
        "description": "At nominal SNR 20 dB, generate trial-level pseudo-spectrum and peak separation statistics for localization sanity checks.",
        "overrides": {
          "snr_db": 20
        }
      }
    ],
    "data_contract": {
      "inputs": [
        "M=8, d_over_lambda=0.5, D=2, L=200",
        "theta_true_deg (default [-7.5, 7.5])",
        "snr_db_grid = [0,2,...,30]",
        "num_trials=1000",
        "scan_grid_deg = [-90,-89.9,...,90]",
        "random_seed (optional reproducibility control)"
      ],
      "expected_outputs": [
        "theta_hat_deg[snr_index, trial, D] for each estimator",
        "music_pseudospectrum[snr_index, trial_or_avg, grid_index]",
        "rmse_deg_per_snr for MUSIC and baselines",
        "stochastic_crb_deg_per_snr",
        "rmse_to_crb_ratio_per_snr",
        "resolution_probability_per_snr",
      …(truncated)
```


---
## [2026-04-21T15:59:02] poe / gpt-5.3-codex

### [system]

```
You are a senior wireless algorithm designer and notebook-oriented implementation planner.

Given the task specification, formalized system/mathematical model, and retrieved knowledge, design one coherent solution package that is immediately ready for notebook generation.

CRITICAL — You MUST reference the mathematical formulas from the formalization (especially math_formulation and algorithm_desi…(truncated)
```

### [user]

```
## Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization|subspace_spectral_estimation",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
    "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom_narrowband",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additiona…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed){
  "architecture": {
    "name": "Grid-MUSIC-CRB Threshold Benchmark Suite",
    "strategy_label": "Subspace pseudo-spectrum estimation with multi-baseline Monte Carlo SNR sweep",
    "summary": "Implement the formalized 11-step Grid-MUSIC pipeline for two-source ULA DoA estimation, compute stochastic CRB per SNR, and benchmark MUSIC against Root-MUSIC, ESPRIT, DML, and SML in a unified Monte Carlo loop over SNR=0:2:30 dB with resolution-threshold extraction.",
    "rationale": "The formal model provides a rank-D covariance structure and noise-subspace orthogonality, making MUSIC the primary interpretable estimator with required pseudo-spectrum output. ULA structure enables Root-MUSIC and ESPRIT as efficient baselines, while DML/SML provide likelihood references. CRB is mandatory for bound-comparison and threshold-gap masking.",
    "algorithm_structure": "Single notebook workflow: parameter setup -> shared data generation -> per-trial covariance and eigenspace -> estimator block (MUSIC/Root-MUSIC/ESPRIT/DML/SML) -> error/resolution bookkeeping -> CRB computation -> aggregate metrics and threshold extraction -> plots and sensitivity sweeps.",
    "pseudocode": "1. Build grid/manifold using $\\Theta_g=\\{\\theta_g^{(k)}\\},\\ \\theta_g^{(k)}=(\\theta_{\\min}+(k-1)\\Delta\\theta)\\pi/180$, $a_m(\\theta)=e^{-j\\pi m\\sin\\theta}$, and $\\mathbf{A}_0=[\\mathbf{a}(\\theta_{0,1}),\\mathbf{a}(\\theta_{0,2})]$.\n2. For each SNR index $q$ and trial $t$, compute $\\gamma_q=10^{\\mathrm{SNR}_{\\mathrm{dB}}[q]/10}$, set $\\sigma_s^2=1$, and $\\sigma_n^2=D\\sigma_s^2/\\gamma_q$.\n3. Generate random snapshots $\\mathbf{S}\\sim\\mathcal{CN}(0,\\sigma_s^2)$ and $\\mathbf{N}\\sim\\mathcal{CN}(0,\\sigma_n^2)$ via $S_{d,\\ell}\\sim\\mathcal{CN}(0,\\sigma_s^2)$ and $N_{m,\\ell}\\sim\\mathcal{CN}(0,\\sigma_n^2)$.\n4. Form received data $\\mathbf{X}=\\mathbf{A}_0\\mathbf{S}+\\mathbf{N}$.\n5. Estimate covariance $\\hat{\\mathbf{R}}_x=\\frac{1}{L}\\mathbf{X}\\mathbf{X}^H$.\n6. Eigendecompose and sort: $\\hat{\\mathbf{R}}_x\\mathbf{u}_i=\\lambda_i\\mathbf{u}_i$, $\\lambda_1\\ge\\cdots\\ge\\lambda_M$, $\\mathbf{U}_n=[\\mathbf{u}_{D+1},\\dots,\\mathbf{u}_M]$.\n7. MUSIC scan: for each grid point, compute $d_k=\\mathbf{a}_k^H\\mathbf{U}_n\\mathbf{U}_n^H\\mathbf{a}_k$ and $P_k=1/\\Re\\{d_k\\}$.\n8. Peak localization using $\\mathcal{K}_{\\mathrm{pk}}=\\{k: P_k>P_{k-1}\\land P_k\\ge P_{k+1}\\}$, choose $\\hat{k}_{1:2}=\\operatorname*{arg\\,top2}_{k\\in\\mathcal{K}_{\\mathrm{pk}}}P_k$, return $\\hat{\\theta}_{1:2}=\\operatorname{sort}(\\theta_g^{(\\hat{k}_{1:2})})$.\n9. Per-trial metrics: $\\mathbf{e}_t=\\hat{\\boldsymbol{\\theta}}_t-\\boldsymbol{\\theta}_0$ and $\\mathcal{R}_t=\\mathbf{1}\\…(truncated)
```


---
## [2026-04-21T16:03:08] poe / gpt-5.3-codex

### [system]

```
You are a senior wireless signal processing researcher building a single executable Jupyter notebook.

Return notebook content using only these section markers:

# ========== MARKDOWN: <role> ==========
<markdown body>

# ========== CODE: <role> ==========
<python code>

═══════════════════════════════════════════════
PART A — STRUCTURE AND FORMAT
═══════════════════════════════════════════════
1.…(truncated)
```

### [user]

```
## Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization|subspace_spectral_estimation",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
    "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom_narrowband",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additiona…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed)Thinking... (13s elapsed)Thinking... (14s elapsed)Thinking... (15s elapsed)Thinking... (16s elapsed)Thinking... (17s elapsed)Thinking... (18s elapsed)Thinking... (19s elapsed)Thinking... (20s elapsed)Thinking... (21s elapsed)Thinking... (22s elapsed)Thinking... (23s elapsed)Thinking... (24s elapsed)Thinking... (25s elapsed)Thinking... (26s elapsed)Thinking... (27s elapsed)Thinking... (28s elapsed)Thinking... (29s elapsed)Thinking... (30s elapsed)Thinking... (31s elapsed)Thinking... (32s elapsed)Thinking... (33s elapsed)Thinking... (34s elapsed)Thinking... (35s elapsed)Thinking... (36s elapsed)Thinking... (37s elapsed)Thinking... (38s elapsed)Thinking... (39s elapsed)Thinking... (40s elapsed)Thinking... (41s elapsed)Thinking... (42s elapsed)Thinking... (43s elapsed)Thinking... (44s elapsed)Thinking... (45s elapsed)Thinking... (46s elapsed)Thinking... (47s elapsed)Thinking... (48s elapsed)Thinking... (49s elapsed)Thinking... (50s elapsed)Thinking... (51s elapsed)Thinking... (52s elapsed)Thinking... (53s elapsed)Thinking... (54s elapsed)Thinking... (55s elapsed)Thinking... (56s elapsed)Thinking... (57s elapsed)Thinking... (58s elapsed)Thinking... (59s elapsed)Thinking... (60s elapsed)Thinking... (61s elapsed)Thinking... (62s elapsed)Thinking... (63s elapsed)Thinking... (64s elapsed)Thinking... (65s elapsed)Thinking... (66s elapsed)Thinking... (67s elapsed)Thinking... (68s elapsed)Thinking... (69s elapsed)Thinking... (70s elapsed)Thinking... (71s elapsed)Thinking... (72s elapsed)Thinking... (73s elapsed)Thinking... (74s elapsed)Thinking... (75s elapsed)Thinking... (76s elapsed)Thinking... (77s elapsed)Thinking... (78s elapsed)Thinking... (79s elapsed)Thinking... (80s elapsed)Thinking... (81s elapsed)Thinking... (82s elapsed)Thinking... (83s elapsed)Thinking... (84s elapsed)Thinking... (85s elapsed)Thinking... (86s elapsed)Thinking... (87s elapsed)Thinking... (88s elapsed)Thinking... (89s elapsed)Thinking... (90s elapsed)Thinking... (91s elapsed)Thinking... (92s elapsed)Thinking... (93s elapsed)Thinking... (94s elapsed)Thinking... (95s elapsed)Thinking... (96s elapsed)Thinking... (97s elapsed)Thinking... (98s elapsed)Thinking... (99s elapsed)Thinking... (100s elapsed)Thinking... (101s elapsed)Thinking... (102s elapsed)Thinking... (103s elapsed)Thinking... (104s elapsed)Thinking... (105s elapsed)Thinking... (106s elapsed)Thinking... (107s elapsed)Thinking... (108s elapsed)# ========== MARKDOWN: title ==========
# Two-Source ULA DoA Estimation via MUSIC with Root-MUSIC / ESPRIT / DML / SML Baselines and Stochastic CRB Benchmark

This notebook implements a complete Monte Carlo evaluation pipeline for $M=8$ half-wavelength ULA DoA estimation with $D=2$ known sources, in…(truncated)
```


---
## [2026-04-21T16:05:47] poe / gpt-5.3-codex

### [system]

```
You repair AutoWiSP notebook cells.

Return the FULL repaired notebook using the same section marker format:
# ========== MARKDOWN: <role> ==========
# ========== CODE: <role> ==========

Requirements:
1. Repair root causes, not symptoms. Preserve roles, baselines, metric names, and result keys.
2. The execution cell must still assign RESULTS with keys: algorithm, elapsed_sec, performance_data, re…(truncated)
```

### [user]

```
## Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization|subspace_spectral_estimation",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
    "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom_narrowband",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additiona…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed)Thinking... (13s elapsed)Thinking... (14s elapsed)Thinking... (15s elapsed)Thinking... (16s elapsed)Thinking... (17s elapsed)Thinking... (18s elapsed)Thinking... (19s elapsed)Thinking... (20s elapsed)Thinking... (21s elapsed)Thinking... (22s elapsed)Thinking... (23s elapsed)Thinking... (24s elapsed)Thinking... (25s elapsed)Thinking... (26s elapsed)# ========== MARKDOWN: problem_setup ==========
We simulate the narrowband far-field array model
$$
\mathbf{x}[\ell]=\mathbf{A}(\boldsymbol{\theta})\mathbf{s}[\ell]+\mathbf{n}[\ell],\quad \ell=1,\dots,L
$$
with:
- $M=8$ sensors (ULA, $d/\lambda=0.5$),
- $D=2$ uncorrelated Gaussian sources,
- $L=200$ snapshots (primary study),
- true angles $\boldsymbol{\theta}_0=[-7.5^\circ,\ 7.5^\circ]$,
- SNR sweep $0:2:30$ dB (per-sensor input SNR).

Primary method: **Grid-MUSIC**.  
Baselines: **Root-MUSIC, ESPRIT, Deterministic ML (DML), Stochastic ML (SML)**.  
Benchmark: **Stochastic CRB**.

Main outputs:
1. RMSE vs SNR for all methods + CRB.
2. Resolution probability vs SNR and threshold SNR where $P_{\mathrm{res}}\ge 0.9$.
3. MUSIC pseudo-spectrum diagnostic at $20$ dB.
4. Snapshot sensitivity (RMSE vs SNR for $L\in\{50,100,200,400\}$).

# ========== MARKDOWN: modeling_summary ==========
Key formulas used in implementation:

- Steering vector (half-wavelength ULA):
$
\mathbf{a}(\theta)=\left[e^{-j2\pi d m\sin\theta}\right]_{m=0}^{M-1},\ d=0.5
$.

- Angle grid and true manifold:
$
\Theta_g=\{\theta_g^{(k)}\},\ \mathbf{A}_0=[\mathbf{a}(\theta_{0,1}),\mathbf{a}(\theta_{0,2})]
$.

- Sample covariance:
$
\hat{\mathbf{R}}_x=\frac{1}{L}\mathbf{X}\mathbf{X}^H
$.

- MUSIC pseudo-spectrum:
$
P_{\mathrm{MU}}(\theta)=\frac{1}{\mathbf{a}^H(\theta)\mathbf{U}_n\mathbf{U}_n^H\mathbf{a}(\theta)}
$,
with $\mathbf{U}_n$ from the smallest $M-D$ eigenvectors of $\hat{\mathbf{R}}_x$.

- Root-MUSIC polynomial:
$
Q(z)=\sum_{p=-(M-1)}^{M-1}c_p z^{-p},\ c_p=\sum_{m-n=p}[\mathbf{U}_n\mathbf{U}_n^H]_{m,n}
$.

- ESPRIT shift invariance:
$
\mathbf{\Psi}=(\mathbf{J}_1\mathbf{U}_s)^\dagger(\mathbf{J}_2\mathbf{U}_s),\ 
\hat{\theta}_i=\arcsin\!\left(-\frac{\arg(\lambda_i(\mathbf{\Psi}))}{2\pi d}\right)
$.

- DML objective:
$
\hat{\boldsymbol{\theta}}_{\mathrm{DML}}=\arg\min_{\boldsymbol{\theta}}
\operatorname{tr}\!\left(\mathbf{P}_{\mathbf{A}(\boldsymbol{\theta})}^{\perp}\hat{\mathbf{R}}_x\right)
$.

- SML objective:
$
\hat{\boldsymbol{\theta}}_{\mathrm{SML}}=\arg\min_{\boldsymbol{\theta},\mathbf{R}_s,\sigma_n^2}
\left[\log\det\mathbf{R}_x+\operatorname{tr}(\mathbf{R}_x^{-1}\hat{\mathbf{R}}_x)\right]
$,
with iterative local refinement and convergence check.

- Stochastic CRB:
$
[\mathbf{J}]_{ij}=2L\Re\!\left\{\operatorname{tr}\!\left(
\mathbf{R}_x^{-1}\frac{\…(truncated)
```


---
## [2026-04-21T16:12:43] poe / gpt-5.3-codex

### [system]

```
You are an expert technical writer producing a rigorous, detailed research-style report for a notebook-based wireless signal processing study.

Write thorough, evidence-grounded Markdown with these sections (in order):
1. Abstract
2. System Model and Mathematical Formulation
3. Algorithm Design
4. Experimental Setup
5. Results and Discussion
6. Performance Analysis and Assessment
7. Reliability an…(truncated)
```

### [user]

```
## Task Specification
```json
{
  "problem_understanding": {
    "task_category": "estimation|localization|subspace_spectral_estimation",
    "problem_statement": "An 8-element half-wavelength ULA receives L=200 temporal snapshots of two uncorrelated narrowband far-field sources in additive spatially white complex Gaussian noise. Estimate the two DoAs (D=2 known), form a spatial pseudo-spectrum for peak localization, and evaluate DoA RMSE over SNR from 0 dB to 30 dB. Use the array model x(t)=A(theta)s(t)+n(t) with sample-covariance subspace decomposition. Benchmark estimator performance against stochastic CRB across SNR and characterize resolution threshold as the minimum SNR where two sources remain resolvable with high probability.",
    "exploitable_structure": "ULA Vandermonde steering matrix, rank-2 signal subspace in Rx covariance, noise-subspace orthogonality exploited by MUSIC/Root-MUSIC, shift-invariance enabling ESPRIT baseline, and approximately Toeplitz covariance under uncorrelated far-field sources."
  },
  "system_model": {
    "waveform": "custom_narrowband",
    "antenna_config": {
      "num_tx": null,
      "num_rx": 8,
      "array_type": "ULA",
      "additiona…(truncated)
```

### [response]

```
Thinking... (1s elapsed)Thinking... (2s elapsed)Thinking... (3s elapsed)Thinking... (4s elapsed)Thinking... (5s elapsed)Thinking... (6s elapsed)Thinking... (7s elapsed)Thinking... (8s elapsed)Thinking... (9s elapsed)Thinking... (10s elapsed)Thinking... (11s elapsed)Thinking... (12s elapsed)Thinking... (13s elapsed)Thinking... (14s elapsed)Thinking... (15s elapsed)Thinking... (16s elapsed)Thinking... (17s elapsed)Thinking... (18s elapsed)Thinking... (19s elapsed)Thinking... (20s elapsed)Thinking... (21s elapsed)## 1. Abstract

This study investigates two-source direction-of-arrival (DoA) estimation for a narrowband far-field scenario using an $M=8$ half-wavelength uniform linear array (ULA) with $L=200$ snapshots under spatially white complex Gaussian noise, with the source count fixed and known ($D=2$). The primary method is **MUSIC**, selected to satisfy pseudo-spectrum-based peak localization requirements, and it is benchmarked against **Root-MUSIC**, **ESPRIT**, **Deterministic Maximum Likelihood (DML)**, and **Stochastic Maximum Likelihood (SML)** across an SNR sweep from $0$ to $30$ dB in $2$ dB steps using $1000$ Monte Carlo trials per point. The pipeline uses sample-covariance eigendecomposition to separate signal and noise subspaces, computes the MUSIC pseudo-spectrum over $[-90^\circ,90^\circ]$ with $0.1^\circ$ grid resolution, and applies a two-peak rule for localization and resolution statistics. Performance is evaluated with **RMSE (deg)**, **resolution probability**, **RMSE-to-CRB ratio**, **runtime per trial**, and a threshold mask based on $\mathrm{RMSE}>3\times \mathrm{CRB}_{\mathrm{RMSE}}$. Quantitatively, **MUSIC** RMSE decreases from $0.2616^\circ$ at $0$ dB to $0.01884^\circ$ at $20$ dB, while **Root-MUSIC** and **ESPRIT** reach $0.02353^\circ$ and $0.02876^\circ$ at $20$ dB, respectively; however, the reported near-zero high-SNR RMSE for MUSIC/DML/SML ($\approx5.13\times10^{-12}$ deg) and flat $P_{\mathrm{res}}=1$ across all SNR indicate likely optimistic behavior tied to implementation effects (e.g., grid locking and identical estimator paths), which constrains strict physical interpretability despite successful notebook execution and verification status.

---

## 2. System Model and Mathematical Formulation

The physical scenario is a classical passive array processing setup: two uncorrelated narrowband far-field emitters impinge on an 8-element ULA with inter-element spacing $d=\lambda/2$. Because the wavefronts are assumed planar (far-field), each source is represented by a phase progression across array elements. Temporal snapshots are collected under quasi-static geometry, so the array manifold remains fixed during each trial. This permits covariance-based subspace decomposition, where DoA information is encoded in a low-rank signal subspace.

The received complex snapshot at time index $\ell$ is modeled as a linear superposition of source components and additive white Gaussian noise. The source signals are mutually unc…(truncated)
```

