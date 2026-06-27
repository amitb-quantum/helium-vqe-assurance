# A Pre-Registered Invariant-Contract Workflow for Auditable VQE Results: A Helium Testbed on IBM Kingston

**Draft methods/tooling preprint — prepared for Zenodo deposit**

---

## Abstract

We present a pre-registered, hash-bound *result-assurance* workflow for
variational quantum eigensolver (VQE) computations and validate it on the
helium atom as an exactly solvable few-body testbed. Before any quantum result
is observed, a contract of physical invariants — a variational lower bound on
the energy, particle-number conservation, and spin-projection conservation —
is declared together with its tolerances and decision rule, then serialized to
canonical JSON and fixed by a SHA-256 digest. Quantum results, whether from a
noisy simulator or from IBM hardware, are subsequently scored against this
frozen contract to yield an auditable ACCEPT / FLAG / ABSTAIN verdict whose
value is recomputable from the provider's returned data without re-executing
the device. On a four-qubit helium Hamiltonian (6-31G basis, Jordan–Wigner
encoding) the noiseless VQE energy reproduces the exact full-configuration-
interaction (FCI) value to 10⁻¹⁵ Hartree and is ACCEPTed; a depolarizing-noise
run is FLAGged because it leaks the particle number out of the two-electron
sector; an under-sampled run is correctly ABSTAINed, and a device-calibrated Kingston twin (built from a real calibration snapshot) ABSTAINs on energy while ACCEPTing the symmetry invariants. We argue that the
contribution of value for near-term quantum computing is not a physics result
but a *discipline*: a tamper-evident audit trail that makes "we obtained the
correct answer" a falsifiable, pre-committed claim rather than a post-hoc one.

**Scope statement.** In a finite basis under the clamped-nucleus (Born–
Oppenheimer) approximation, helium is the two-electron electronic-structure
problem. The full three-body problem (finite nuclear mass, explicit nuclear
kinetic energy) is a strict superset and is *not* addressed here. No claim of
quantum advantage or of "solving the three-body problem" is made.

---

## 1. Introduction

Near-term quantum processors return results that can be untrustworthy for two
distinct reasons: the computation may have executed on an unreliable device, or
the returned numbers may violate physical constraints the true answer is known
to satisfy. The conventional response — run the job, then decide post hoc
whether the output "looks right" — is methodologically fragile, because the
acceptance criterion can drift to accommodate the observed data. This is the
quantum-computing instance of a problem that pre-registration solved in the
empirical sciences: fixing the analysis and the acceptance rule *before* seeing
the outcome.

This paper formalizes and demonstrates a pre-registration workflow for VQE. The
key object is an **invariant contract**: a declared set of physical invariants
with tolerances and an aggregation rule, frozen and hashed prior to execution.
We deliberately choose a testbed — the helium atom in a small basis — whose
exact answer is independently computable classically, so that the assurance
layer can be validated against ground truth rather than trusted on faith.

The historical irony motivating this work is worth stating. The scalar and
vector *potentials* were introduced (Lagrange, 1770s; later Kelvin for
magnetism) as calculational conveniences for intractable mechanics, the
three-body problem foremost among them; quantum mechanics later revealed those
"bookkeeping" objects to be physically fundamental (the Aharonov–Bohm effect).
The lesson generalizes: methodological scaffolding, taken seriously, can carry
more weight than the problem that prompted it. Here the scaffolding is the
assurance contract.

## 2. Methods

### 2.1 Helium Hamiltonian and classical ground truth

We construct the electronic-structure Hamiltonian of helium in the 6-31G basis
(two spatial orbitals; STO-3G is rejected because its single spatial orbital
removes electron correlation and renders VQE trivial). The fermionic operator
is mapped to qubits with the Jordan–Wigner transformation, giving a four-qubit
Hamiltonian with 27 Pauli terms. Two independent classical references are
computed with PySCF: the restricted Hartree–Fock energy and the
full-configuration-interaction (FCI) energy. Direct diagonalization of the
qubit Hamiltonian reproduces the FCI energy to 3×10⁻¹⁵ Hartree, confirming the
mapping.

| Quantity | Value (Hartree) |
|----------|-----------------|
| Hartree–Fock | −2.85516043 |
| FCI / exact qubit ground | −2.87016214 |
| Correlation energy | −0.01500 |

### 2.2 Ansatz and execution

The trial state is a UCCSD ansatz on a Hartree–Fock reference. UCCSD conserves
particle number and total spin by construction, so a *correct* run satisfies
the symmetry invariants automatically; a violation therefore indicates genuine
device error rather than an ill-posed ansatz. Three observables are estimated
per run: the energy ⟨H⟩, the particle number ⟨N⟩ = Σᵢ(I−Zᵢ)/2, and the spin
projection ⟨S_z⟩. The noiseless reference uses an exact statevector estimator;
the hardware-like path uses a depolarizing noise model with finite-shot
sampling, exposing the statistical uncertainty consumed by the contract. The
identical circuit and observables transpile to IBM Kingston (156-qubit Heron
r2) for hardware submission.

### 2.3 The pre-registered contract

A contract is a list of invariants, each with a kind (`lower_bound` or
`equality`), a target, a tolerance, and a hardness flag, plus an
`abstain_sigma_factor`. For helium:

1. **Variational lower bound.** By the variational principle, ⟨H⟩ ≥ E₀ for any
   normalized state, where E₀ is the exact ground-state energy. A measured
   energy a full tolerance band *below* E₀ is unphysical and is FLAGged; values
   at or above E₀ are admissible (an imperfect ansatz only raises the energy).
2. **Particle-number conservation.** ⟨N⟩ must equal the electron count within
   tolerance.
3. **Spin-projection conservation.** ⟨S_z⟩ must equal its target (0 for the
   singlet).

The contract payload is serialized to canonical JSON (sorted keys, complex
coefficients encoded as [re, im]) and fixed by a SHA-256 digest *before* any
result is seen. Scoring then applies a three-way rule per invariant:

- **ABSTAIN** if the reported uncertainty exceeds `abstain_sigma_factor × tol`
  (the data cannot resolve the tolerance band);
- **FLAG** if the invariant is violated beyond tolerance;
- **ACCEPT** otherwise.

The overall verdict is FLAG if any hard invariant FLAGs, else ABSTAIN if any
hard invariant ABSTAINs, else ACCEPT. The verdict record carries the contract
hash, binding it to the pre-registered rule.

### 2.4 Provenance

Each stage emits a frozen record `{label, frozen_at_utc, sha256, payload}`; the
full trail (Hamiltonian metadata, contract, per-run measurements, verdicts) is
itself hashed. Re-hashing any payload must reproduce its digest — the audit
check. For hardware runs the IBM job ID is stored so that the observables and
verdict regenerate from the provider's returned counts with no QPU re-run.

## 3. Results

### 3.1 Detector validation on synthetic ground truth

Following the practice of validating a detector against labeled cases, the
contract was scored on four synthetic inputs with known correct verdicts: a
valid at-ground result (ACCEPT), an energy below the variational bound (FLAG), a
particle-number leak (FLAG), and a high-uncertainty input (ABSTAIN). All four
verdicts matched expectation.

### 3.2 End-to-end runs

| Run | Energy (Ha) | ⟨N⟩ | ⟨S_z⟩ | Verdict | Cause |
|-----|-------------|------|--------|---------|-------|
| Noiseless statevector | −2.87016214 | 2.0000 | 0.0000 | **ACCEPT** | energy = FCI to 1e-15; symmetries exact |
| Noisy, 4000 shots | −2.1937 ± 0.016 | 2.056 | 0.049 | **FLAG** | ⟨N⟩ leaves the 2-electron sector (resolved at σ≈0.016) |
| Noisy, 80 shots | −2.170 ± 0.112 | 2.026 | −0.119 | **ABSTAIN** | all observables unresolved at tolerance |

Two findings deserve emphasis. First, the FLAG is a *real* detection: under
depolarizing noise the measured particle number drifts to 2.056, outside the
0.05 tolerance, and the pipeline rejects the result on a physical invariant
rather than on a fit to the known energy. Second, the energy invariant ABSTAINs
even at 4000 shots, because chemical-accuracy tolerance (1.6 mHartree) lies far
below attainable shot-noise precision; the workflow reports this honestly
instead of over-claiming resolution it does not have.

### 3.3 Device-calibrated Kingston twin

To bridge the gap between an idealized noise model and hardware, we build a
*digital twin* of IBM Kingston directly from a calibration snapshot
(`ibm_kingston_hardware_*.json`): per-qubit T1/T2 and readout error, and
measured CZ gate error per coupling edge (native basis rz, sx, x, cz). A
preflight placement step selects the lowest-cost connected four-qubit chain by
calibration cost (readout + single-qubit + CZ error), excluding disabled
qubits and edges. For the snapshot used here the selected chain was physical
qubits [68, 67, 57, 47] (readout errors 0.29-0.76%, CZ edge errors
1.15-1.71x10^-3, T1 175-409 us).

Running the optimized circuit on this twin at 8000 shots gives:

| Observable | Value | Verdict |
|------------|-------|---------|
| energy | -2.7297 +/- 0.0112 Ha | ABSTAIN |
| particle number | 2.034 +/- 0.011 | ACCEPT |
| spin projection | 0.010 +/- 0.011 | ACCEPT |

Overall verdict: **ABSTAIN**. With realistic Kingston-level errors the symmetry
invariants are satisfied within tolerance -- the measured particle number stays
close to two, because the device CZ error (~0.16%) is far below the 1% used in
the synthetic stress test of Section 3.2 -- but the energy cannot be resolved to
chemical accuracy at this shot count, so the pipeline abstains on energy and
therefore overall. This quantifies a practically important boundary: on
current-generation hardware, symmetry-based verification of this workload is
attainable while direct energy verification to chemical accuracy is
shot-limited.

## 4. Discussion

The workflow converts an informal judgement ("the result looks right") into a
pre-committed, hash-bound, recomputable verdict. Its value is independent of any
quantum-advantage question: like build-provenance tooling for software, it
provides an audit trail that stands on its own. The ABSTAIN verdict is as
important as the other two — a verifier that never declines is not measuring its
own resolution.

The approach is also conservative by design. It attributes a FLAG to a *result*,
not to *hardware*: a violated invariant establishes that the returned numbers
are untrustworthy, not that the device is at fault, since stale references,
transpilation errors, or mis-specified contracts are mundane alternative
explanations that must be excluded first.

## 5. Limitations

- The testbed is a four-qubit, two-electron system; scaling the contract to
  larger Hamiltonians and to error-mitigated estimators (e.g. zero-noise
  extrapolation, which can itself overshoot below the variational bound — a
  failure mode this contract is well placed to catch) remains future work.
- Energy resolution to chemical accuracy is shot-limited; the present contract
  consequently ABSTAINs on energy at realistic shot counts and relies on
  symmetry invariants for FLAGs.
- The invariants used are necessary but not sufficient conditions for
  correctness; passing the contract bounds, but does not prove, result quality.

## 6. Reproducibility

All code, the requirements file, and an example frozen provenance trail are
provided. `python run_pipeline.py` regenerates the trail; `--selftest` runs the
detector validation. Every reported figure recomputes from the canonical-JSON
artifacts via their SHA-256 digests.

## References (to be completed for deposit)

1. A. Peruzzo et al., "A variational eigenvalue solver on a photonic quantum
   processor," *Nat. Commun.* **5**, 4213 (2014).
2. J. Tilly et al., "The Variational Quantum Eigensolver: A review of methods
   and best practices," *Phys. Rep.* **986**, 1 (2022).
3. Y. Aharonov and D. Bohm, "Significance of Electromagnetic Potentials in the
   Quantum Theory," *Phys. Rev.* **115**, 485 (1959).
4. T. T. Wu and C. N. Yang, "Concept of nonintegrable phase factors and global
   formulation of gauge fields," *Phys. Rev. D* **12**, 3845 (1975).
5. Qiskit Nature and Qiskit (IBM Quantum) software documentation.
