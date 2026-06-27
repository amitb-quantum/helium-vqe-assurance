"""
run_negative_control.py
=======================
HARDWARE NEGATIVE CONTROL on a chosen backend (default ibm_fez).

Takes the optimized helium UCCSD circuit and DELIBERATELY breaks it by injecting
a single X gate, which flips one spin-orbital occupation and drives the particle
number out of the 2-electron sector. The same pre-registered, frozen contract is
then applied to the returned data -- and should FLAG it on particle_number.

Why this matters: it demonstrates, on real hardware (not simulation), that the
contract rejects a physically invalid result. Together with the valid Kingston
run (ACCEPT / ABSTAIN) it completes the ACCEPT / FLAG / ABSTAIN story on QPUs.

This is a *labeled* negative control -- an intentionally invalid input used to
prove the detector works. It is NOT a claim about helium.

Cost: identical to the main run -- 1 job, 9 measurement circuits.

Usage:
    python run_negative_control.py                 # ibm_fez, 1024 shots, asks to confirm
    python run_negative_control.py --backend ibm_fez --shots 1024 --yes
"""

from __future__ import annotations

import argparse
import json

from helium_hamiltonian import build_helium_hamiltonian, bundle_to_sparse_pauli_op
from contract import helium_contract, score, Measurement
from provenance import sha256_of
import vqe_kingston as vqe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="ibm_fez")
    ap.add_argument("--shots", type=int, default=1024)
    ap.add_argument("--fault-qubit", type=int, default=0,
                    help="qubit to flip with the injected X (breaks <N>)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    from qiskit import transpile  # noqa: F401  (kept for parity / debugging)
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime import QiskitRuntimeService, EstimatorV2 as RT

    # PREFLIGHT: contract + optimal (valid) parameters
    bundle = build_helium_hamiltonian()
    contract = helium_contract(bundle.exact_qubit_ground_energy, bundle.n_electrons)
    frozen_contract = contract.freeze()
    print("PREFLIGHT: contract %s..." % frozen_contract["sha256"][:16])
    r_ideal = vqe.run_vqe_statevector(bundle)
    print("  optimized (valid) energy = %.8f Ha" % r_ideal.energy)

    # Build the FAULTED circuit: optimal UCCSD + injected X (breaks particle number)
    ansatz, _, _, _ = vqe.build_ansatz(bundle.basis)
    faulted = ansatz.assign_parameters(r_ideal.optimal_params)
    faulted.x(args.fault_qubit)
    print("  injected fault: X on qubit %d (expected to push <N> off 2)"
          % args.fault_qubit)

    svc = QiskitRuntimeService()
    backend = svc.backend(args.backend)
    pm = generate_preset_pass_manager(optimization_level=3, backend=backend)
    isa = pm.run(faulted)

    H = bundle_to_sparse_pauli_op(bundle)
    obs = {"energy": H,
           "particle_number": vqe.number_operator(bundle.n_qubits),
           "spin_projection_sz": vqe.sz_operator(bundle.n_qubits)}
    iobs = {k: v.apply_layout(isa.layout) for k, v in obs.items()}

    n_bases = len(H.group_commuting(qubit_wise=True))
    print("\nCost summary:")
    print("  backend: %s | jobs: 1 | circuits: %d | shots: %d | total: %d"
          % (args.backend, n_bases, args.shots, n_bases * args.shots))

    if not args.yes:
        if input("Submit NEGATIVE CONTROL to %s? [y/N] " % args.backend).strip().lower() != "y":
            print("aborted.")
            return

    est = RT(mode=backend)
    est.options.default_shots = args.shots
    job = est.run([(isa, iobs["energy"]),
                   (isa, iobs["particle_number"]),
                   (isa, iobs["spin_projection_sz"])])
    job_id = job.job_id()
    print("\nSubmitted. job id: %s" % job_id)
    with open("negative_control_jobid.txt", "w") as f:
        f.write(job_id + "\n")
    print("(job id saved to negative_control_jobid.txt; you can Ctrl-C and "
          "fetch later with fetch_kingston_result.py)")

    print("Waiting for result ... (%s queue is short)" % args.backend)
    res = job.result()
    try:
        qs = float(job.usage())
    except Exception:
        qs = None

    nuc = bundle.nuclear_repulsion
    meas = {
        "energy": Measurement("energy", float(res[0].data.evs) + nuc, float(res[0].data.stds)),
        "particle_number": Measurement("particle_number", float(res[1].data.evs), float(res[1].data.stds)),
        "spin_projection_sz": Measurement("spin_projection_sz", float(res[2].data.evs), float(res[2].data.stds)),
    }
    print("\nNegative-control result (job %s):" % job_id)
    print("  energy = %.6f +/- %.6f Ha" % (meas["energy"].value, meas["energy"].sigma))
    print("  <N>    = %.4f +/- %.4f  <-- expect far from 2"
          % (meas["particle_number"].value, meas["particle_number"].sigma))
    print("  <Sz>   = %.4f +/- %.4f" % (meas["spin_projection_sz"].value, meas["spin_projection_sz"].sigma))
    if qs is not None:
        print("  QPU billed: %.3f quantum-seconds" % qs)

    v = score(contract, meas)
    print("\nVERDICT:", v.overall, "(expected FLAG on particle_number)")
    for ir in v.invariant_results:
        print("  - %-22s %-8s (meas=%.6f, resid=%+.2e)"
              % (ir.name, ir.verdict, ir.measured, ir.residual))

    out = args.out or ("provenance_trail_negative_control_%s.json" % job_id)
    trail = {
        "pipeline": "helium-vqe-assurance / hardware NEGATIVE CONTROL",
        "note": "intentional fault: X on qubit %d breaks particle-number conservation" % args.fault_qubit,
        "preflight": {"contract": frozen_contract},
        "execute": {"negative_control": {
            "backend": args.backend,
            "measurements": {k: [m.value, m.sigma] for k, m in meas.items()},
            "extra": {"provider_job_id": job_id, "quantum_seconds": qs,
                      "fault_qubit": args.fault_qubit}}},
        "postflight": {"negative_control": v.to_payload()},
    }
    trail["trail_sha256"] = sha256_of(trail)
    with open(out, "w") as f:
        json.dump(trail, f, indent=2)
    print("\nProvenance trail -> %s" % out)


if __name__ == "__main__":
    main()
