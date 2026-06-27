"""
kingston_device.py
==================
Turn an IBM Kingston calibration snapshot (the ibm_kingston_hardware_*.json
produced from the live backend) into:

  1. a DEVICE-ACCURATE Aer noise model -- thermal relaxation from per-qubit
     T1/T2 and gate durations, depolarising error from measured CZ gate error,
     and per-qubit readout error;
  2. a PREFLIGHT qubit-placement choice -- the best-connected n-qubit chain by
     calibration cost (readout + 1q + 2q errors), which is exactly the kind of
     placement diagnostic the QuantaCore preflight stage performs;
  3. a hash-bound calibration summary for the provenance trail.

Native Kingston basis is rz, sx, x, cz (CZ, not CX). Dead qubits/edges
(gate_error == 1.0 or missing readout) are excluded from placement.

This makes the local simulation a faithful twin of running on those physical
Kingston qubits -- runs on CPU (fine for 4 qubits; no GPU required).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from provenance import freeze

KINGSTON_BASIS = ["rz", "sx", "x", "cz"]
_DEAD = 1.0  # gate_error sentinel for disabled qubit/edge


# ---------------------------------------------------------------------------
# Calibration parsing
# ---------------------------------------------------------------------------
@dataclass
class Calibration:
    backend_name: str
    extraction_timestamp: str
    n_qubits: int
    coupling_map: list           # list of [a, b]
    qubit: dict                  # qid -> {T1,T2,readout_error}
    gate1q: dict                 # (gate, q) -> {error, length}
    gate2q: dict                 # (a, b) -> {error, length}  (cz)

    def snapshot_payload(self) -> dict:
        """Compact, deterministic summary for hashing into provenance."""
        return {
            "backend_name": self.backend_name,
            "extraction_timestamp": self.extraction_timestamp,
            "n_qubits": self.n_qubits,
            "n_edges": len(self.coupling_map),
        }

    def freeze(self) -> dict:
        return freeze("device_calibration", self.snapshot_payload())


def load_calibration(path: str) -> Calibration:
    with open(path) as f:
        d = json.load(f)
    qprops = {q["qubit_id"]: {"T1": q["T1"], "T2": q["T2"],
                              "readout_error": q["readout_error"]}
              for q in d["qubit_properties"]}
    gate1q, gate2q = {}, {}
    for g in d["gate_properties"]:
        qs = g.get("qubits", [])
        if len(qs) == 1 and g["gate"] in ("sx", "x", "rz", "id"):
            gate1q[(g["gate"], qs[0])] = {"error": g["gate_error"],
                                          "length": g["gate_length"]}
        elif len(qs) == 2 and g["gate"] == "cz":
            gate2q[(qs[0], qs[1])] = {"error": g["gate_error"],
                                      "length": g["gate_length"]}
    return Calibration(
        backend_name=d["backend_name"],
        extraction_timestamp=d["extraction_timestamp"],
        n_qubits=d["basic_config"]["n_qubits"],
        coupling_map=[list(e) for e in d["basic_config"]["coupling_map"]],
        qubit=qprops, gate1q=gate1q, gate2q=gate2q,
    )


# ---------------------------------------------------------------------------
# Preflight placement: best connected chain of n qubits
# ---------------------------------------------------------------------------
def _edge_error(cal: Calibration, a: int, b: int):
    e = cal.gate2q.get((a, b)) or cal.gate2q.get((b, a))
    return e["error"] if e else None


def _qubit_cost(cal: Calibration, q: int):
    ro = cal.qubit[q]["readout_error"]
    sx = cal.gate1q.get(("sx", q), {}).get("error")
    if ro is None or sx is None or ro >= _DEAD or sx >= _DEAD:
        return None
    return ro + sx


def select_chain(cal: Calibration, n: int = 4) -> dict:
    """
    Find the lowest-cost connected CHAIN (path) of n physical qubits.

    Cost = sum of node costs (readout + sx error) + sum of CZ errors on the
    n-1 chain edges. Dead qubits/edges are excluded. Returns the chain (a list
    of physical qubit ids) plus the line coupling map on virtual indices.
    """
    adj = {}
    for a, b in cal.coupling_map:
        if _edge_error(cal, a, b) is None or _edge_error(cal, a, b) >= _DEAD:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    best = {"cost": float("inf"), "chain": None}

    def dfs(path, cost):
        if len(path) == n:
            if cost < best["cost"]:
                best["cost"] = cost
                best["chain"] = list(path)
            return
        last = path[-1]
        for nb in adj.get(last, ()):  # extend
            if nb in path:
                continue
            qc = _qubit_cost(cal, nb)
            ec = _edge_error(cal, last, nb)
            if qc is None or ec is None:
                continue
            path.append(nb)
            dfs(path, cost + qc + ec)
            path.pop()

    # Seed from the lowest-cost qubits to keep the search cheap and good.
    seeds = sorted((q for q in cal.qubit if _qubit_cost(cal, q) is not None),
                   key=lambda q: _qubit_cost(cal, q))[:30]
    for s in seeds:
        qc = _qubit_cost(cal, s)
        if qc is None:
            continue
        dfs([s], qc)

    chain = best["chain"]
    if chain is None:
        raise RuntimeError("no viable %d-qubit chain found" % n)
    line_coupling = [[i, i + 1] for i in range(n - 1)]
    return {
        "chain": chain,
        "cost": best["cost"],
        "line_coupling": line_coupling,
        "edge_errors": [_edge_error(cal, chain[i], chain[i + 1])
                        for i in range(n - 1)],
        "readout_errors": [cal.qubit[q]["readout_error"] for q in chain],
        "sx_errors": [cal.gate1q[("sx", q)]["error"] for q in chain],
        "T1": [cal.qubit[q]["T1"] for q in chain],
        "T2": [cal.qubit[q]["T2"] for q in chain],
    }


# ---------------------------------------------------------------------------
# Device-accurate noise model on virtual qubits 0..n-1 carrying the chain's
# physical calibration.
# ---------------------------------------------------------------------------
def build_noise_model(cal: Calibration, chain: list):
    from qiskit_aer.noise import (NoiseModel, thermal_relaxation_error,
                                  depolarizing_error, ReadoutError)

    nm = NoiseModel(basis_gates=KINGSTON_BASIS)
    n = len(chain)

    # default 1q gate time if a length is 0/missing (rz is virtual -> skip)
    def g1(gate, q):
        return cal.gate1q.get((gate, q), {"error": 0.0, "length": 3.2e-8})

    for v, phys in enumerate(chain):
        t1 = cal.qubit[phys]["T1"]
        t2 = cal.qubit[phys]["T2"]
        # single-qubit gates: thermal relaxation over the gate duration
        for gate in ("sx", "x"):
            L = g1(gate, phys)["length"] or 3.2e-8
            err = thermal_relaxation_error(t1, t2, L)
            nm.add_quantum_error(err, gate, [v])
        # readout error
        p = cal.qubit[phys]["readout_error"]
        nm.add_readout_error(ReadoutError([[1 - p, p], [p, 1 - p]]), [v])

    # two-qubit CZ on each chain edge: measured depol error + thermal relax
    for i in range(n - 1):
        a, b = chain[i], chain[i + 1]
        e = cal.gate2q.get((a, b)) or cal.gate2q.get((b, a))
        L = (e["length"] if e and e["length"] else 6.8e-8)
        depol = depolarizing_error(e["error"] if e else 0.0, 2)
        th = thermal_relaxation_error(cal.qubit[a]["T1"], cal.qubit[a]["T2"], L).tensor(
             thermal_relaxation_error(cal.qubit[b]["T1"], cal.qubit[b]["T2"], L))
        nm.add_quantum_error(depol.compose(th), "cz", [i, i + 1])

    return nm


# ---------------------------------------------------------------------------
# Twin estimator: run the helium VQE on the Kingston twin (CPU Aer)
# ---------------------------------------------------------------------------
def estimate_on_twin(bundle, params, calib_path, shots=4000, device="CPU",
                     seed=11, n_qubits_chain=None):
    """Estimate energy/N/Sz at fixed params on a device-accurate Kingston twin.

    Transpiles the UCCSD circuit to the Kingston basis (rz,sx,x,cz) on the
    selected physical chain, then samples with the calibration-derived noise
    model. Returns (VQEResult, placement_dict, frozen_calibration).
    """
    from qiskit import transpile
    from qiskit_aer.primitives import EstimatorV2 as AerEstimator

    from vqe_kingston import (build_ansatz, number_operator, sz_operator,
                              VQEResult)

    cal = load_calibration(calib_path)
    n = n_qubits_chain or bundle.n_qubits
    placement = select_chain(cal, n)
    nm = build_noise_model(cal, placement["chain"])

    ansatz, _, _, _ = build_ansatz(bundle.basis)
    bound = ansatz.assign_parameters(params)
    bound = transpile(bound, basis_gates=KINGSTON_BASIS,
                      coupling_map=placement["line_coupling"],
                      optimization_level=1)

    h_elec = __import__("helium_hamiltonian").bundle_to_sparse_pauli_op(bundle)
    n_op = number_operator(bundle.n_qubits)
    sz_op = sz_operator(bundle.n_qubits)
    nuc = bundle.nuclear_repulsion

    precision = 1.0 / (shots ** 0.5)
    est = AerEstimator(options={
        "backend_options": {"noise_model": nm, "device": device,
                            "seed_simulator": seed},
        "default_precision": precision,
    })
    res = est.run([(bound, h_elec), (bound, n_op), (bound, sz_op)]).result()

    result = VQEResult(
        label="kingston_twin_%s" % cal.backend_name,
        energy=float(res[0].data.evs) + nuc, energy_sigma=float(res[0].data.stds),
        n_value=float(res[1].data.evs), n_sigma=float(res[1].data.stds),
        sz_value=float(res[2].data.evs), sz_sigma=float(res[2].data.stds),
        optimal_params=list(params), nfev=0,
        extra={"backend": cal.backend_name, "shots": shots,
               "physical_qubits": placement["chain"],
               "placement_cost": placement["cost"]},
    )
    return result, placement, cal.freeze()
