"""
run_kingston_live.py
====================
Submit the helium VQE to REAL IBM Kingston and score the returned result against
the pre-registered, frozen contract -- writing a job-ID-stamped provenance trail.

  preflight: build He Hamiltonian, exact ground truth, FREEZE + hash contract
  optimize : noiseless VQE fixes the trial parameters (trustworthy reference)
  execute  : submit those parameters to ibm_kingston (single job mode)
  postflight: score energy / <N> / <Sz> vs the frozen contract -> verdict
  provenance: record the public IBM job id so anyone can recompute the verdict

WARNING: this consumes real QPU time and will queue. Open-plan QPU minutes are
limited, so keep shots modest and avoid repeated runs.

Usage (inside the activated env, from the project folder):
    python run_kingston_live.py                 # asks for confirmation
    python run_kingston_live.py --yes           # no prompt
    python run_kingston_live.py --shots 4096
"""

from __future__ import annotations

import argparse
import json

from helium_hamiltonian import build_helium_hamiltonian
from contract import helium_contract, score, Measurement
from provenance import sha256_of
import vqe_kingston as vqe


def measurements_from_result(r):
    p = r.measurements_payload()
    return {k: Measurement(k, v[0], v[1]) for k, v in p.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="ibm_kingston")
    ap.add_argument("--shots", type=int, default=4096)
    ap.add_argument("--out", default="provenance_trail_kingston_live.json")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    args = ap.parse_args()

    # PREFLIGHT
    bundle = build_helium_hamiltonian()
    exact_e = bundle.exact_qubit_ground_energy
    contract = helium_contract(exact_e, bundle.n_electrons)
    frozen_contract = contract.freeze()
    print("PREFLIGHT: exact ground = %.8f Ha | contract %s..."
          % (exact_e, frozen_contract["sha256"][:16]))

    print("Optimizing VQE (noiseless) to fix the trial parameters ...")
    r_ideal = vqe.run_vqe_statevector(bundle)
    print("  noiseless energy = %.8f Ha (nfev=%d)" % (r_ideal.energy, r_ideal.nfev))

    # Pre-submit cost summary so you know what you are spending.
    from helium_hamiltonian import bundle_to_sparse_pauli_op
    n_bases = len(bundle_to_sparse_pauli_op(bundle).group_commuting(qubit_wise=True))
    total_shots = n_bases * args.shots
    print("\nCost summary for this submission:")
    print("  jobs submitted      : 1 (no hardware optimization loop)")
    print("  measurement circuits: %d (qubit-wise-commuting bases)" % n_bases)
    print("  shots per circuit   : %d" % args.shots)
    print("  total shot-executions: %d" % total_shots)
    print("  open-plan budget    : 600 quantum-seconds / 28-day window")
    print("  (actual quantum_seconds is reported after the run)")

    if not args.yes:
        resp = input("\nSubmit to %s with %d shots? Uses real QPU time. [y/N] "
                     % (args.backend, args.shots))
        if resp.strip().lower() != "y":
            print("aborted.")
            return

    # EXECUTE on hardware
    print("Submitting to %s ... (this will queue; leave it running)" % args.backend)
    r_hw = vqe.run_on_kingston(bundle, r_ideal.optimal_params,
                               backend_name=args.backend, shots=args.shots)
    job_id = r_hw.extra.get("provider_job_id")
    print("\nHardware result (job id %s):" % job_id)
    print("  energy = %.6f +/- %.6f Ha" % (r_hw.energy, r_hw.energy_sigma))
    print("  <N>    = %.4f +/- %.4f" % (r_hw.n_value, r_hw.n_sigma))
    print("  <Sz>   = %.4f +/- %.4f" % (r_hw.sz_value, r_hw.sz_sigma))

    qs = r_hw.extra.get("quantum_seconds")
    if qs is not None:
        print("  QPU time billed    : %.3f quantum-seconds (%.2f%% of the 600s window)"
              % (qs, 100.0 * qs / 600.0))
    else:
        print("  QPU time billed    : see dashboard (job.usage() unavailable)")

    # POSTFLIGHT
    v = score(contract, measurements_from_result(r_hw))
    print("\nVERDICT:", v.overall)
    for ir in v.invariant_results:
        print("  - %-22s %-8s (meas=%.6f, resid=%+.2e)"
              % (ir.name, ir.verdict, ir.measured, ir.residual))

    trail = {
        "pipeline": "helium-vqe-assurance / kingston-LIVE",
        "preflight": {"contract": frozen_contract},
        "execute": {"kingston_live": {"measurements": r_hw.measurements_payload(),
                                      "extra": r_hw.extra}},
        "postflight": {"kingston_live": v.to_payload()},
    }
    trail["trail_sha256"] = sha256_of(trail)
    with open(args.out, "w") as f:
        json.dump(trail, f, indent=2)
    print("\nProvenance trail -> %s" % args.out)
    print("  job_id = %s" % job_id)
    print("  trail sha = %s..." % trail["trail_sha256"][:16])
    print("\nAnyone can recompute this verdict from IBM's returned data for job "
          + str(job_id) + " -- no QPU re-run needed.")


if __name__ == "__main__":
    main()
