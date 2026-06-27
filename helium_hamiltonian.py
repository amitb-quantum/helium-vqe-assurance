"""
helium_hamiltonian.py
=====================
Constructs the electronic-structure Hamiltonian for the helium atom
(clamped-nucleus / Born-Oppenheimer approximation: nucleus + 2 electrons)
in a small Gaussian basis, maps it to qubits, and computes the exact
ground-state energy by direct diagonalization as the *classical ground truth*.

SCOPE NOTE (state this in any publication):
    In a finite basis under the clamped-nucleus approximation, helium is the
    two-electron electronic-structure problem. The *full* three-body problem
    (finite nuclear mass, explicit nuclear kinetic energy) is a strict
    superset and is NOT what is solved here. The value of this testbed is that
    it is a genuine correlated few-body quantum system with an exactly known
    answer -- ideal for validating a result-assurance workflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np


@dataclass
class HamiltonianBundle:
    """Everything downstream stages need, plus reproducibility metadata."""
    basis: str
    n_qubits: int
    n_electrons: int
    nuclear_repulsion: float
    pauli_terms: list[tuple[str, complex]]   # (pauli_string, coefficient)
    hf_energy: float                          # Hartree-Fock reference
    fci_energy: float                         # full-CI (pyscf) reference
    exact_qubit_ground_energy: float          # exact diag of the qubit op

    def to_metadata(self) -> dict:
        return {
            "basis": self.basis,
            "n_qubits": self.n_qubits,
            "n_electrons": self.n_electrons,
            "nuclear_repulsion": self.nuclear_repulsion,
            "n_pauli_terms": len(self.pauli_terms),
            "hf_energy_hartree": self.hf_energy,
            "fci_energy_hartree": self.fci_energy,
            "exact_qubit_ground_energy_hartree": self.exact_qubit_ground_energy,
        }


def build_helium_hamiltonian(basis: str = "6-31g") -> HamiltonianBundle:
    """
    Build the helium qubit Hamiltonian and classical references.

    A minimal STO-3G basis gives only a single spatial orbital for He, which
    has no electron correlation (a single determinant is exact and VQE is
    trivial). We default to 6-31g, which gives two spatial orbitals -> four
    spin orbitals -> four qubits under Jordan-Wigner, with genuine
    (if modest) electron correlation.
    """
    from qiskit_nature.second_q.drivers import PySCFDriver
    from qiskit_nature.second_q.mappers import JordanWignerMapper
    from qiskit_nature.units import DistanceUnit

    driver = PySCFDriver(atom="He 0.0 0.0 0.0", basis=basis,
                         charge=0, spin=0, unit=DistanceUnit.ANGSTROM)
    problem = driver.run()

    second_q_op = problem.hamiltonian.second_q_op()
    nuclear_repulsion = float(problem.hamiltonian.nuclear_repulsion_energy)

    mapper = JordanWignerMapper()
    qubit_op = mapper.map(second_q_op)  # SparsePauliOp (electronic part only)

    n_qubits = qubit_op.num_qubits
    n_electrons = int(sum(problem.num_particles))

    # Exact diagonalization of the qubit Hamiltonian (electronic) + nuc. rep.
    dense = qubit_op.to_matrix()
    eigvals = np.linalg.eigvalsh(dense)
    exact_qubit_ground = float(eigvals[0].real) + nuclear_repulsion

    hf_energy, fci_energy = _pyscf_references(basis)

    pauli_terms = [(str(p), complex(c))
                   for p, c in zip(qubit_op.paulis.to_labels(),
                                   qubit_op.coeffs)]

    return HamiltonianBundle(
        basis=basis,
        n_qubits=n_qubits,
        n_electrons=n_electrons,
        nuclear_repulsion=nuclear_repulsion,
        pauli_terms=pauli_terms,
        hf_energy=hf_energy,
        fci_energy=fci_energy,
        exact_qubit_ground_energy=exact_qubit_ground,
    )


def _pyscf_references(basis: str) -> tuple[float, float]:
    """Independent HF and FCI energies straight from pyscf."""
    from pyscf import gto, scf, fci
    mol = gto.M(atom="He 0 0 0", basis=basis, charge=0, spin=0, unit="Angstrom")
    mf = scf.RHF(mol).run(verbose=0)
    hf_energy = float(mf.e_tot)
    cisolver = fci.FCI(mf)
    fci_energy = float(cisolver.kernel()[0])
    return hf_energy, fci_energy


def bundle_to_sparse_pauli_op(bundle: HamiltonianBundle):
    """Reconstruct a qiskit SparsePauliOp from the stored terms."""
    from qiskit.quantum_info import SparsePauliOp
    labels = [p for p, _ in bundle.pauli_terms]
    coeffs = [c for _, c in bundle.pauli_terms]
    return SparsePauliOp(labels, coeffs)


if __name__ == "__main__":
    b = build_helium_hamiltonian()
    print(json.dumps(b.to_metadata(), indent=2))
    diff = abs(b.exact_qubit_ground_energy - b.fci_energy)
    print(f"\n|exact_qubit_ground - pyscf_FCI| = {diff:.3e} Hartree")
    assert diff < 1e-6, "Qubit Hamiltonian does not reproduce FCI -- check mapping!"
    print("OK: qubit Hamiltonian reproduces the exact (FCI) ground-state energy.")
