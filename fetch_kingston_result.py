"""
fetch_kingston_result.py
========================
Retrieve a previously submitted IBM Kingston job by its ID, score the returned
data against the (deterministically re-derived) frozen contract, and write the
provenance trail. NO new QPU time is used -- this only reads existing results.

This decouples submission from retrieval: submit once, close the laptop, and
come back hours later to pull the result when the queue clears.

Usage (inside the activated env, from the project folder):
    python fetch_kingston_result.py d9018e06c68s73ahgqqg
    python fetch_kingston_result.py <JOB_ID> --out my_trail.json

Checking status does not consume QPU, so run it as often as you like.
"""

from __future__ import annotations

import argparse
import json

from helium_hamiltonian import build_helium_hamiltonian
from contract import helium_contract, score, Measurement
from provenance import sha256_of
from qiskit_ibm_runtime import QiskitRuntimeService


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    svc = QiskitRuntimeService()
    job = svc.job(args.job_id)
    status = str(job.status())
    print("job %s status: %s" % (args.job_id, status))

    if status.upper() != "DONE" and "DONE" not in status.upper():
        for probe in ("queue_position", "queue_info"):
            try:
                print("  %s: %s" % (probe, getattr(job, probe)()))
            except Exception:
                pass
        print("Not finished yet. Re-run this command later. (Checking uses no QPU.)")
        if status.upper() in ("ERROR", "CANCELLED"):
            try:
                print("  error message:", job.error_message())
            except Exception:
                pass
        return

    res = job.result()

    # Re-derive the SAME contract deterministically (same machine -> same hash).
    bundle = build_helium_hamiltonian()
    nuc = bundle.nuclear_repulsion
    contract = helium_contract(bundle.exact_qubit_ground_energy, bundle.n_electrons)
    frozen_contract = contract.freeze()

    # PUB order matches submission: [energy, particle_number, spin_projection_sz]
    meas = {
        "energy": Measurement("energy",
                              float(res[0].data.evs) + nuc, float(res[0].data.stds)),
        "particle_number": Measurement("particle_number",
                                       float(res[1].data.evs), float(res[1].data.stds)),
        "spin_projection_sz": Measurement("spin_projection_sz",
                                          float(res[2].data.evs), float(res[2].data.stds)),
    }

    qs = None
    try:
        qs = float(job.usage())
    except Exception:
        pass

    print("\nKingston result:")
    print("  energy = %.6f +/- %.6f Ha" % (meas["energy"].value, meas["energy"].sigma))
    print("  <N>    = %.4f +/- %.4f"
          % (meas["particle_number"].value, meas["particle_number"].sigma))
    print("  <Sz>   = %.4f +/- %.4f"
          % (meas["spin_projection_sz"].value, meas["spin_projection_sz"].sigma))
    if qs is not None:
        print("  QPU billed: %.3f quantum-seconds (%.2f%% of 600s window)"
              % (qs, 100.0 * qs / 600.0))

    v = score(contract, meas)
    print("\nVERDICT:", v.overall)
    for ir in v.invariant_results:
        print("  - %-22s %-8s (meas=%.6f, resid=%+.2e)"
              % (ir.name, ir.verdict, ir.measured, ir.residual))

    out = args.out or ("provenance_trail_kingston_%s.json" % args.job_id)
    trail = {
        "pipeline": "helium-vqe-assurance / kingston-LIVE (retrieved)",
        "preflight": {"contract": frozen_contract},
        "execute": {"kingston_live": {
            "measurements": {k: [m.value, m.sigma] for k, m in meas.items()},
            "extra": {"provider_job_id": args.job_id, "quantum_seconds": qs}}},
        "postflight": {"kingston_live": v.to_payload()},
    }
    trail["trail_sha256"] = sha256_of(trail)
    with open(out, "w") as f:
        json.dump(trail, f, indent=2)
    print("\nProvenance trail -> %s  (job_id=%s)" % (out, args.job_id))


if __name__ == "__main__":
    main()
