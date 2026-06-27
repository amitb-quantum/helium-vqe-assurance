"""
run_pipeline.py
===============
End-to-end driver: PREFLIGHT (freeze Hamiltonian + contract) -> EXECUTE
(VQE on simulator; swap in Kingston) -> POSTFLIGHT (score against the frozen
contract) -> emit one hash-bound provenance trail.

This mirrors the QuantaCore -> Eigenspectrum spine, as an open reference so the
whole verdict is recomputable by anyone from the saved JSON.

Run:
    python run_pipeline.py                 # full demo (CPU)
    python run_pipeline.py --selftest      # detector logic test only (fast)
"""

from __future__ import annotations

import argparse
import json
import sys

from helium_hamiltonian import build_helium_hamiltonian
from contract import (helium_contract, score, Measurement)
from provenance import freeze, verify_frozen, sha256_of
import vqe_kingston as vqe


def measurements_from_result(r) -> dict:
    p = r.measurements_payload()
    return {k: Measurement(k, v[0], v[1]) for k, v in p.items()}


def selftest_detector(exact_e: float, n_elec: int) -> bool:
    """
    Validate the detector against synthetic ground truth (the way the real
    Eigenspectrum was validated on simulated records): feed it known-good and
    known-bad inputs and confirm the verdicts.
    """
    c = helium_contract(exact_e, n_elec)
    cases = {
        # name: (measurements, expected overall verdict)
        "valid_at_ground": (
            {"energy": Measurement("energy", exact_e + 1e-4, 1e-5),
             "particle_number": Measurement("particle_number", 2.0, 1e-4),
             "spin_projection_sz": Measurement("spin_projection_sz", 0.0, 1e-4)},
            "ACCEPT"),
        "below_ground_variational_violation": (
            {"energy": Measurement("energy", exact_e - 5e-3, 1e-4),
             "particle_number": Measurement("particle_number", 2.0, 1e-4),
             "spin_projection_sz": Measurement("spin_projection_sz", 0.0, 1e-4)},
            "FLAG"),
        "particle_number_leak": (
            {"energy": Measurement("energy", exact_e + 1e-3, 1e-4),
             "particle_number": Measurement("particle_number", 1.7, 1e-4),
             "spin_projection_sz": Measurement("spin_projection_sz", 0.0, 1e-4)},
            "FLAG"),
        "too_noisy_to_decide": (
            {"energy": Measurement("energy", exact_e + 1e-3, 5e-2),
             "particle_number": Measurement("particle_number", 2.0, 1e-4),
             "spin_projection_sz": Measurement("spin_projection_sz", 0.0, 1e-4)},
            "ABSTAIN"),
    }
    ok = True
    print("\n=== detector self-test (synthetic ground truth) ===")
    for name, (meas, expected) in cases.items():
        v = score(c, meas)
        status = "PASS" if v.overall == expected else "FAIL"
        ok = ok and (v.overall == expected)
        print(f"  [{status}] {name:38s} -> {v.overall:8s} (expected {expected})")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default="6-31g")
    ap.add_argument("--selftest", action="store_true",
                    help="run only the detector logic self-test")
    ap.add_argument("--out", default="provenance_trail.json")
    args = ap.parse_args()

    # ---------------- PREFLIGHT ----------------
    print("PREFLIGHT: building Hamiltonian + classical ground truth ...")
    bundle = build_helium_hamiltonian(args.basis)
    exact_e = bundle.exact_qubit_ground_energy
    print(f"  exact (FCI) ground-state energy = {exact_e:.8f} Ha "
          f"({bundle.n_qubits} qubits)")

    contract = helium_contract(exact_e, bundle.n_electrons)
    frozen_ham = freeze("hamiltonian", bundle.to_metadata())
    frozen_contract = contract.freeze()
    print(f"  contract SHA-256  = {frozen_contract['sha256'][:16]}...")
    print(f"  hamiltonian SHA-256 = {frozen_ham['sha256'][:16]}...")

    if not selftest_detector(exact_e, bundle.n_electrons):
        print("\nDETECTOR SELF-TEST FAILED", file=sys.stderr)
        sys.exit(1)
    print("  detector self-test: ALL PASS")

    if args.selftest:
        return

    # ---------------- EXECUTE ----------------
    print("\nEXECUTE: VQE on local statevector (trustworthy reference) ...")
    r_ideal = vqe.run_vqe_statevector(bundle)
    print(f"  noiseless VQE energy = {r_ideal.energy:.8f} Ha "
          f"(nfev={r_ideal.nfev}); <N>={r_ideal.n_value:.4f}, "
          f"<Sz>={r_ideal.sz_value:.4f}")

    print("EXECUTE: hardware-like Aer run (noisy, finite shots) ...")
    r_noisy = vqe.estimate_with_noise(bundle, r_ideal.optimal_params,
                                      shots=4000, noise_scale=1.0)
    print(f"  noisy energy = {r_noisy.energy:.6f} +/- {r_noisy.energy_sigma:.6f} Ha")

    print("EXECUTE: deliberately under-sampled Aer run (should ABSTAIN) ...")
    r_lowshot = vqe.estimate_with_noise(bundle, r_ideal.optimal_params,
                                        shots=80, noise_scale=1.0, seed=99)
    print(f"  low-shot energy = {r_lowshot.energy:.6f} "
          f"+/- {r_lowshot.energy_sigma:.6f} Ha")

    # ---------------- POSTFLIGHT ----------------
    print("\nPOSTFLIGHT: scoring each result against the FROZEN contract ...")
    runs = {"noiseless": r_ideal, "noisy_4000shots": r_noisy,
            "lowshot_80": r_lowshot}
    verdicts = {}
    for name, r in runs.items():
        v = score(contract, measurements_from_result(r))
        verdicts[name] = v
        print(f"  {name:18s} -> {v.overall}")
        for ir in v.invariant_results:
            print(f"       - {ir.name:24s} {ir.verdict:8s} "
                  f"(meas={ir.measured:.6f}, resid={ir.residual:+.2e})")

    # ---------------- PROVENANCE TRAIL ----------------
    trail = {
        "pipeline": "helium-vqe-assurance (open reference)",
        "preflight": {
            "hamiltonian": frozen_ham,
            "contract": frozen_contract,
        },
        "execute": {name: {"label": r.label,
                           "measurements": r.measurements_payload(),
                           "optimal_params": r.optimal_params,
                           "extra": r.extra}
                    for name, r in runs.items()},
        "postflight": {name: v.to_payload() for name, v in verdicts.items()},
    }
    trail["trail_sha256"] = sha256_of(trail)

    with open(args.out, "w") as f:
        json.dump(trail, f, indent=2, default=lambda o: o.real if isinstance(o, complex) else str(o))

    # audit: every frozen record must re-verify
    assert verify_frozen(frozen_ham) and verify_frozen(frozen_contract)
    print(f"\nProvenance trail written to {args.out}")
    print(f"  trail SHA-256 = {trail['trail_sha256'][:16]}...")
    print("  all frozen records re-verified: OK")


if __name__ == "__main__":
    main()
