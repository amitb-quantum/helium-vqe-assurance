"""
run_kingston_twin.py
====================
Run the helium VQE on a DEVICE-ACCURATE IBM Kingston twin built from a
calibration snapshot, then score it against the pre-registered contract.

This is the bridge between the noiseless reference and real hardware: same
circuit, same contract, but the noise is Kingston's measured T1/T2/readout/CZ
error on a preflight-selected physical qubit chain.

    python run_kingston_twin.py --calib ../ibm_kingston_hardware_20260408_170917.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os

from helium_hamiltonian import build_helium_hamiltonian
from contract import helium_contract, score, Measurement
from provenance import sha256_of
import vqe_kingston as vqe
import kingston_device as kd


def measurements_from_result(r):
    p = r.measurements_payload()
    return {k: Measurement(k, v[0], v[1]) for k, v in p.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", default=None,
                    help="path to ibm_kingston_hardware_*.json")
    ap.add_argument("--shots", type=int, default=8000)
    ap.add_argument("--out", default="provenance_trail_kingston_twin.json")
    args = ap.parse_args()

    calib = args.calib
    if calib is None:
        cands = glob.glob("ibm_kingston_hardware_*.json") + \
                glob.glob("../ibm_kingston_hardware_*.json")
        if not cands:
            raise SystemExit("no calibration file found; pass --calib PATH")
        calib = sorted(cands)[-1]
    print("Using calibration:", calib)

    # PREFLIGHT
    bundle = build_helium_hamiltonian()
    exact_e = bundle.exact_qubit_ground_energy
    contract = helium_contract(exact_e, bundle.n_electrons)
    frozen_contract = contract.freeze()
    print("exact ground energy = %.8f Ha | contract %s..."
          % (exact_e, frozen_contract["sha256"][:16]))

    # Noiseless reference -> optimal parameters (trustworthy)
    r_ideal = vqe.run_vqe_statevector(bundle)
    print("noiseless VQE energy = %.8f Ha" % r_ideal.energy)

    # EXECUTE on the Kingston twin
    r_twin, placement, frozen_cal = kd.estimate_on_twin(
        bundle, r_ideal.optimal_params, calib, shots=args.shots)
    print("\nPreflight placement (lowest-cost chain):")
    print("  physical qubits :", placement["chain"])
    print("  readout errors  :", ["%.4f" % x for x in placement["readout_errors"]])
    print("  CZ edge errors  :", ["%.2e" % x for x in placement["edge_errors"]])
    print("  T1 (us)         :", ["%.0f" % (x * 1e6) for x in placement["T1"]])
    print("\nKingston-twin result:")
    print("  energy = %.6f +/- %.6f Ha" % (r_twin.energy, r_twin.energy_sigma))
    print("  <N>    = %.4f +/- %.4f" % (r_twin.n_value, r_twin.n_sigma))
    print("  <Sz>   = %.4f +/- %.4f" % (r_twin.sz_value, r_twin.sz_sigma))

    # POSTFLIGHT
    v = score(contract, measurements_from_result(r_twin))
    print("\nVERDICT:", v.overall)
    for ir in v.invariant_results:
        print("  - %-22s %-8s (meas=%.6f, resid=%+.2e)"
              % (ir.name, ir.verdict, ir.measured, ir.residual))

    trail = {
        "pipeline": "helium-vqe-assurance / kingston-twin",
        "preflight": {"contract": frozen_contract,
                      "device_calibration": frozen_cal,
                      "placement": placement},
        "execute": {"kingston_twin": {"measurements": r_twin.measurements_payload(),
                                      "extra": r_twin.extra}},
        "postflight": {"kingston_twin": v.to_payload()},
    }
    trail["trail_sha256"] = sha256_of(trail)
    with open(args.out, "w") as f:
        json.dump(trail, f, indent=2)
    print("\nProvenance trail -> %s  (sha %s...)"
          % (args.out, trail["trail_sha256"][:16]))


if __name__ == "__main__":
    main()
