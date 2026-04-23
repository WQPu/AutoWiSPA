# Wireless Signal Processing Algorithm Design — Problem Set

---

## P1 · Spectrum Sensing for Cognitive Radio

A cognitive radio secondary user equipped with a single antenna collects $N = 256$ complex baseband samples per sensing interval and must decide whether a licensed band is occupied by a primary user under AWGN conditions (flat fading assumed compensated). The false-alarm probability must satisfy $P_{fa} \leq 0.01$, and reliable detection is expected at SNR as low as $-10$ dB. Design the detection algorithm, explain how the decision threshold is set, provide the theoretical $P_d$ vs. SNR curve from $-20$ dB to $0$ dB, and validate with Monte Carlo simulation.

---

## P2 · Pilot-Based Channel Estimation for OFDM

A SISO-OFDM system operates with 64 subcarriers (SCS = 15 kHz, CP length 16, carrier frequency 3.5 GHz), where 16 equally spaced pilot subcarriers are available and the channel frequency response at the remaining 48 data subcarriers must be recovered; the channel follows a 3GPP TDL-A model with 30 ns rms delay spread. Design at least two estimation approaches with different performance–complexity trade-offs, explain the interpolation strategy used to obtain non-pilot subcarrier estimates, and provide NMSE vs. SNR curves from 0 dB to 30 dB for each approach.

---

## P3 · Direction-of-Arrival Estimation with a Uniform Linear Array

Two uncorrelated narrowband far-field sources separated by approximately 15° impinge on an 8-element half-wavelength-spaced ULA; $L = 200$ snapshots are available, nominal SNR is around 20 dB, and the number of sources $D = 2$ is assumed known. Design a DoA estimation algorithm, plot the spatial spectrum or pseudo-spectrum, provide DoA RMSE vs. SNR (0–30 dB) with the CRB as a reference lower bound, and characterize the resolution limit — the minimum SNR at which the two sources can still be separated.

---
