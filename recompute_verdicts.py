"""
recompute_verdicts.py
=====================
Re-derive every ACCEPT / FLAG / ABSTAIN verdict from the PUBLISHED measurement
data, using the same frozen contract — no quantum hardware, no QPU re-run.

For each provenance_trail*.json, this reads the recorded measured observables
(energy, particle_number, spin_projection_sz) from the 'execute' section,
re-scores them against helium_contract(...), and checks the recomputed verdict
matches the 'postflight' verdict stored in the trail. This is what makes the
claim "every verdict re-computes from the published data" literally true.

Run:
    python recompute_verdicts.py                  # all provenance_trail*.json here
    python recompute_verdicts.py path/to/trail.json
"""
import glob
import json
import sys

from helium_hamiltonian import build_helium_hamiltonian
from contract import helium_contract, score, Measurement


def main():
    files = sys.argv[1:] or sorted(glob.glob("provenance_trail*.json"))
    if not files:
        print("No provenance_trail*.json found.")
        return 1

    b = build_helium_hamiltonian()
    contract = helium_contract(b.exact_qubit_ground_energy, b.n_electrons)
    chash = contract.freeze()["sha256"]
    print("Frozen contract SHA-256: %s\n" % chash)

    total, matched = 0, 0
    for fp in files:
        d = json.load(open(fp))
        execute = d.get("execute", {})
        postflight = d.get("postflight", {})
        print("== %s ==" % fp)
        for run_name, run in execute.items():
            meas_raw = run.get("measurements")
            if not meas_raw:
                continue
            meas = {k: Measurement(k, float(v[0]), float(v[1]))
                    for k, v in meas_raw.items()}
            v = score(contract, meas)
            recorded = postflight.get(run_name, {}).get("overall")
            total += 1
            if recorded is None:
                status = "(no recorded verdict to compare)"
            elif v.overall == recorded:
                status = "MATCH"
                matched += 1
            else:
                status = "MISMATCH (recorded %s)" % recorded
            print("  %-22s recomputed -> %-8s %s" % (run_name, v.overall, status))
        print()

    print("Recomputed %d verdict(s); %d matched the published record."
          % (total, matched))
    ok = (matched == total) or all(False for _ in ())  # matched==total when records present
    return 0 if matched == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
