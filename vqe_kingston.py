"""
vqe_kingston.py
===============
VQE engine for the helium testbed. Runs on the local Aer simulator for
validation and submits to IBM Kingston (156-qubit Heron r2) unchanged.

Each run estimates three observables -- energy, particle number <N>, and spin
projection <S_z> -- because the pre-registered contract scores all three.

  * UCCSD ansatz on a Hartree-Fock reference conserves N and spin by
    construction, so a correct run satisfies the symmetry invariants
    automatically; violations therefore signal real hardware error.
  * Noiseless StatevectorEstimator -> trustworthy reference result.
  * Aer EstimatorV2 + depolarising noise + finite shots -> hardware-like
    result with reported statistical uncertainty (used by the ABSTAIN rule).
  * GPU: install qiskit-aer-gpu and pass device="GPU" to use the RTX 4060 /
    RTX A1000. Default device="CPU" runs anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from qiskit.quantum_info import SparsePauliOp
from qiskit.primitives import StatevectorEstimator

from helium_hamiltonian import HamiltonianBundle, bundle_to_sparse_pauli_op


# ---------------------------------------------------------------------------
# Observables (Jordan-Wigner, qiskit-nature blocked spin ordering:
# qubits [0..n_spatial-1]=alpha, [n_spatial..2n_spatial-1]=beta)
# ---------------------------------------------------------------------------
def number_operator(n_qubits):
    """N = sum_i (I - Z_i)/2 ."""
    terms = [("", [], 0.5 * n_qubits)]
    terms += [("Z", [i], -0.5) for i in range(n_qubits)]
    return SparsePauliOp.from_sparse_list(terms, num_qubits=n_qubits).simplify()


def sz_operator(n_qubits):
    """S_z = (1/2)(N_alpha - N_beta) = -1/4 (sum_alpha Z - sum_beta Z)."""
    n_spatial = n_qubits // 2
    terms = []
    for i in range(n_spatial):
        terms.append(("Z", [i], -0.25))
    for i in range(n_spatial, n_qubits):
        terms.append(("Z", [i], +0.25))
    return SparsePauliOp.from_sparse_list(terms, num_qubits=n_qubits).simplify()


def build_ansatz(basis="6-31g"):
    """Return (ansatz_circuit, mapper, num_spatial_orbitals, num_particles)."""
    from qiskit_nature.second_q.drivers import PySCFDriver
    from qiskit_nature.second_q.mappers import JordanWignerMapper
    from qiskit_nature.second_q.circuit.library import UCCSD, HartreeFock
    from qiskit_nature.units import DistanceUnit

    driver = PySCFDriver(atom="He 0.0 0.0 0.0", basis=basis,
                         charge=0, spin=0, unit=DistanceUnit.ANGSTROM)
    problem = driver.run()
    n_spatial = problem.num_spatial_orbitals
    n_particles = problem.num_particles
    mapper = JordanWignerMapper()
    hf = HartreeFock(n_spatial, n_particles, mapper)
    ansatz = UCCSD(n_spatial, n_particles, mapper, initial_state=hf)
    return ansatz, mapper, n_spatial, n_particles


@dataclass
class VQEResult:
    label: str
    energy: float
    energy_sigma: float
    n_value: float
    n_sigma: float
    sz_value: float
    sz_sigma: float
    optimal_params: list
    nfev: int
    extra: dict

    def measurements_payload(self):
        return {
            "energy": [self.energy, self.energy_sigma],
            "particle_number": [self.n_value, self.n_sigma],
            "spin_projection_sz": [self.sz_value, self.sz_sigma],
        }


def run_vqe_statevector(bundle, maxiter=300, seed=7):
    ansatz, _, _, _ = build_ansatz(bundle.basis)
    h_elec = bundle_to_sparse_pauli_op(bundle)
    n_op = number_operator(bundle.n_qubits)
    sz_op = sz_operator(bundle.n_qubits)
    nuc = bundle.nuclear_repulsion

    est = StatevectorEstimator()
    rng = np.random.default_rng(seed)
    x0 = 1e-1 * rng.standard_normal(ansatz.num_parameters)

    def energy(x):
        res = est.run([(ansatz, h_elec, x)]).result()
        return float(res[0].data.evs) + nuc

    out = minimize(energy, x0, method="COBYLA", options={"maxiter": maxiter, "tol": 1e-8})
    xopt = out.x
    e = energy(xopt)
    n_val = float(est.run([(ansatz, n_op, xopt)]).result()[0].data.evs)
    sz_val = float(est.run([(ansatz, sz_op, xopt)]).result()[0].data.evs)

    return VQEResult(
        label="noiseless_statevector",
        energy=e, energy_sigma=0.0,
        n_value=n_val, n_sigma=0.0,
        sz_value=sz_val, sz_sigma=0.0,
        optimal_params=[float(v) for v in xopt],
        nfev=int(out.nfev),
        extra={"optimizer": "COBYLA", "converged_message": str(out.message)},
    )


AER_BASIS = ["rz", "sx", "x", "cx"]  # transpile target == noisy gate set


def _simple_noise_model(p1=1e-3, p2=1e-2):
    from qiskit_aer.noise import NoiseModel, depolarizing_error
    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(depolarizing_error(p1, 1), ["sx", "x"])
    nm.add_all_qubit_quantum_error(depolarizing_error(p2, 2), ["cx"])
    return nm


def estimate_with_noise(bundle, params, shots=4000, noise_scale=1.0,
                        device="CPU", seed=11):
    """Estimate energy/N/Sz at fixed params on a noisy Aer backend.

    noise_scale multiplies base error rates (for zero-noise extrapolation
    studies). device='GPU' uses qiskit-aer-gpu if installed.
    """
    from qiskit import transpile
    from qiskit_aer.primitives import EstimatorV2 as AerEstimator

    ansatz, _, _, _ = build_ansatz(bundle.basis)
    bound = ansatz.assign_parameters(params)
    # UCCSD uses high-level evolution gates; Aer needs explicit basis gates.
    bound = transpile(bound, basis_gates=AER_BASIS, optimization_level=1)
    h_elec = bundle_to_sparse_pauli_op(bundle)
    n_op = number_operator(bundle.n_qubits)
    sz_op = sz_operator(bundle.n_qubits)
    nuc = bundle.nuclear_repulsion

    nm = _simple_noise_model(1e-3 * noise_scale, 1e-2 * noise_scale)
    # Finite-shot statistics enter via precision = 1/sqrt(shots); this makes
    # the estimator SAMPLE (non-zero reported stds) instead of returning the
    # exact noisy expectation, so the contract ABSTAIN rule is exercised.
    precision = 1.0 / (shots ** 0.5)
    est = AerEstimator(options={
        "backend_options": {"noise_model": nm, "device": device,
                            "seed_simulator": seed},
        "default_precision": precision,
    })

    res = est.run([(bound, h_elec), (bound, n_op), (bound, sz_op)]).result()
    e_val = float(res[0].data.evs) + nuc
    e_sig = float(res[0].data.stds)
    n_val = float(res[1].data.evs); n_sig = float(res[1].data.stds)
    sz_val = float(res[2].data.evs); sz_sig = float(res[2].data.stds)

    return VQEResult(
        label="aer_noisy_shots%d_scale%s" % (shots, noise_scale),
        energy=e_val, energy_sigma=e_sig,
        n_value=n_val, n_sigma=n_sig,
        sz_value=sz_val, sz_sigma=sz_sig,
        optimal_params=list(params), nfev=0,
        extra={"shots": shots, "noise_scale": noise_scale, "device": device},
    )


def transpile_for_kingston(bundle, params, backend_name="ibm_kingston",
                           optimization_level=3):
    """Produce the ISA (hardware-native) circuit + observables for Kingston.

    Requires qiskit-ibm-runtime and saved IBM Quantum credentials. The exact
    transpilation is returned so it can be part of the provenance record.
    """
    from qiskit_ibm_runtime import QiskitRuntimeService
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    service = QiskitRuntimeService()
    backend = service.backend(backend_name)

    ansatz, _, _, _ = build_ansatz(bundle.basis)
    bound = ansatz.assign_parameters(params)
    pm = generate_preset_pass_manager(optimization_level=optimization_level,
                                      backend=backend)
    isa_circuit = pm.run(bound)

    h_elec = bundle_to_sparse_pauli_op(bundle)
    observables = {
        "energy": h_elec,
        "particle_number": number_operator(bundle.n_qubits),
        "spin_projection_sz": sz_operator(bundle.n_qubits),
    }
    isa_obs = {k: v.apply_layout(isa_circuit.layout) for k, v in observables.items()}
    return isa_circuit, isa_obs, backend


def run_on_kingston(bundle, params, backend_name="ibm_kingston", shots=4000):
    """Submit energy/N/Sz estimation to IBM Kingston via Estimator V2.

    Returns a VQEResult including the provider job id (record it in provenance:
    'the claim is not trust us, it is pull the job and check').
    """
    # Open plan: use single-job mode (mode=backend). Sessions are paid-plan only.
    from qiskit_ibm_runtime import EstimatorV2 as RuntimeEstimator

    isa_circuit, isa_obs, backend = transpile_for_kingston(bundle, params, backend_name)
    nuc = bundle.nuclear_repulsion

    est = RuntimeEstimator(mode=backend)
    est.options.default_shots = shots
    job = est.run([
        (isa_circuit, isa_obs["energy"]),
        (isa_circuit, isa_obs["particle_number"]),
        (isa_circuit, isa_obs["spin_projection_sz"]),
    ])
    job_id = job.job_id()
    res = job.result()

    # Actual QPU time billed (quantum seconds), if the provider exposes it.
    quantum_seconds = None
    try:
        quantum_seconds = float(job.usage())
    except Exception:
        try:
            quantum_seconds = float(job.metrics().get("usage", {}).get("quantum_seconds"))
        except Exception:
            quantum_seconds = None

    e_val = float(res[0].data.evs) + nuc
    return VQEResult(
        label="kingston_%s" % backend_name,
        energy=e_val, energy_sigma=float(res[0].data.stds),
        n_value=float(res[1].data.evs), n_sigma=float(res[1].data.stds),
        sz_value=float(res[2].data.evs), sz_sigma=float(res[2].data.stds),
        optimal_params=list(params), nfev=0,
        extra={"provider_job_id": job_id, "backend": backend_name, "shots": shots,
               "quantum_seconds": quantum_seconds},
    )
