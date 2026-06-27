# Helium VQE with a Pre-Registered Result-Assurance Contract

An open, reproducible reference implementation of a **preflight -> execute ->
postflight** assurance pipeline for VQE results, demonstrated on the helium atom
and targeting **IBM Kingston** (156-qubit Heron r2). The contribution is the
*method* -- a hash-bound, pre-registered invariant contract yielding an
auditable ACCEPT / FLAG / ABSTAIN verdict -- not a claim about the physics of
helium, and emphatically not a claim of "solving the three-body problem".

## Scope (read before publishing)

In a finite basis under the clamped-nucleus (Born-Oppenheimer) approximation,
helium is the **two-electron** electronic-structure problem. The full
three-body problem (finite nuclear mass, explicit nuclear kinetic energy) is a
strict superset and is **not** solved here. No quantum-advantage claim is made.

## Files

| File | Purpose |
|------|---------|
| `helium_hamiltonian.py` | He qubit Hamiltonian (6-31G, 4 qubits); exact diag + pyscf HF/FCI. |
| `provenance.py`         | Canonical-JSON + SHA-256 freeze/verify helpers. |
| `contract.py`           | Pre-registered invariant contract; ACCEPT/FLAG/ABSTAIN scoring. |
| `vqe_kingston.py`       | UCCSD VQE; noiseless + toy-noise Aer paths; IBM Kingston submission. |
| `kingston_device.py`    | Build device-accurate noise model + preflight qubit placement from a calibration snapshot. |
| `run_pipeline.py`       | End-to-end demo (noiseless / toy-noisy / low-shot). |
| `run_kingston_twin.py`  | End-to-end on a device-calibrated Kingston twin. |
| `provenance_trail*.json`| Example frozen provenance trails. |

## Quick start

```bash
pip install -r requirements.txt
python run_pipeline.py                 # noiseless / toy-noise / low-shot demo
python run_pipeline.py --selftest      # detector logic test (fast)
python run_kingston_twin.py            # device-calibrated Kingston twin
```

`run_kingston_twin.py` auto-discovers `ibm_kingston_hardware_*.json` in this
folder or its parent, or pass `--calib /path/to/snapshot.json`.

## Running on your Dell6 laptop (WSL, Intel Arc GPU, 32 GB RAM)

This package runs entirely on **CPU** and needs no GPU and no proprietary
environment:

- **Do NOT install `qiskit-aer-gpu`.** It is CUDA-only (NVIDIA). The Intel Arc
  GPU and the integrated SoC are not CUDA devices, so Aer cannot offload to
  them. The CUDA `device="GPU"` paths are only for your other (RTX) machine.
- For this 4-qubit problem, CPU Aer is effectively instantaneous; 32 GB RAM is
  far more than enough (the twin only ever simulates the 4 selected qubits, not
  all 156).
- Run inside WSL Ubuntu: `python3 -m venv .venv && source .venv/bin/activate &&
  pip install -r requirements.txt`.
- You do **not** need the QuantaCore environment to run this -- it is a
  self-contained open reference of the same pre-registration discipline. Clone
  your own repo separately if you want the commercial pipeline alongside.

## Running on real IBM Kingston (updated 2026 access)

The legacy `ibm_quantum` channel has been **retired**. Current access:

1. Create an **IBM Cloud API key** and note your **instance CRN** from the IBM
   Quantum Platform.
2. Save credentials once (channel defaults to `ibm_quantum_platform`):

   ```python
   from qiskit_ibm_runtime import QiskitRuntimeService
   QiskitRuntimeService.save_account(
       token="YOUR_IBM_CLOUD_API_KEY",
       instance="YOUR_CRN",
       set_as_default=True,
   )
   ```
3. Submit the real job (after the noiseless optimization):

   ```python
   r_hw = vqe.run_on_kingston(bundle, r_ideal.optimal_params)  # backend ibm_kingston
   print(r_hw.extra["provider_job_id"])  # public IBM job id -> store in provenance
   ```

Record the `provider_job_id`: the verdict then recomputes from IBM's own
returned data with no QPU re-run.

## Device twin from a calibration snapshot

`kingston_device.py` turns `ibm_kingston_hardware_*.json` into a faithful local
twin: thermal relaxation from per-qubit T1/T2 and gate durations, depolarising
error from measured CZ errors, per-qubit readout error, plus a preflight
placement that picks the lowest-error connected qubit chain. This is the recommended way to dry-run and validate the contract before spending QPU time.

## Reproduced results (local)

| Run | Verdict | Why |
|-----|---------|-----|
| noiseless statevector | ACCEPT | energy = FCI to 1e-15 Ha; <N>=2, <Sz>=0 |
| toy noise, 4000 shots | FLAG   | 1% depol leaks <N> out of the 2-electron sector |
| toy noise, 80 shots   | ABSTAIN| observables unresolved at tolerance |
| Kingston twin, 8000 shots | ABSTAIN | symmetries ACCEPT; energy shot-limited below chemical accuracy |
