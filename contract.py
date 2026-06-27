"""
contract.py
===========
Open reference implementation of a *pre-registered invariant contract* -- the
postflight discipline that QuantaCore / Eigenspectrum sells as a product.

Before any quantum result is seen, we declare the physical invariants the
result MUST satisfy, the thresholds, and the decision rule; we freeze and hash
that contract; only then do we look at the data. Because the acceptance rule
was fixed and hashed in advance, it cannot be quietly moved to fit the outcome.

Verdict semantics:
    ACCEPT  -- every hard invariant satisfied within tolerance.
    FLAG    -- at least one hard invariant violated (result not trustworthy).
    ABSTAIN -- measurement uncertainty too large to decide either way.

Helium VQE invariants:
    1. Variational lower bound: <H> >= exact ground energy. A measured energy
       below it is unphysical -- a hallmark of uncorrected device noise.
    2. Particle-number conservation: <N> == electron count.
    3. Spin projection: <S_z> == target (0 for the singlet).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from provenance import freeze, sha256_of


@dataclass
class Invariant:
    name: str
    kind: str            # "lower_bound" | "equality"
    target: float
    tol: float
    hard: bool = True
    units: str = ""


@dataclass
class Contract:
    name: str
    invariants: list
    abstain_sigma_factor: float = 1.0

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "abstain_sigma_factor": self.abstain_sigma_factor,
            "invariants": [
                {
                    "name": i.name, "kind": i.kind, "target": i.target,
                    "tol": i.tol, "hard": i.hard, "units": i.units,
                }
                for i in self.invariants
            ],
        }

    def freeze(self) -> dict:
        return freeze("contract", self.to_payload())


def helium_contract(exact_ground_energy: float,
                    n_electrons: int,
                    target_sz: float = 0.0,
                    energy_tol: float = 1.6e-3) -> Contract:
    """Standard helium-VQE contract. energy_tol ~ chemical accuracy (1 kcal/mol)."""
    return Contract(
        name="helium_vqe_v1",
        invariants=[
            # Round the target to 1e-9 Ha so the contract hash is portable
            # across BLAS/Python builds (the raw eigenvalue's last bits vary by
            # platform). 1e-9 is far below the 1.6e-3 tolerance, so scoring is
            # unaffected; only the hash becomes machine-independent.
            Invariant("energy", "lower_bound",
                      target=round(float(exact_ground_energy), 9), tol=energy_tol,
                      hard=True, units="hartree"),
            Invariant("particle_number", "equality",
                      target=float(n_electrons), tol=0.05,
                      hard=True, units="electrons"),
            Invariant("spin_projection_sz", "equality",
                      target=target_sz, tol=0.05,
                      hard=True, units="hbar"),
        ],
    )


@dataclass
class Measurement:
    name: str
    value: float
    sigma: float = 0.0


@dataclass
class InvariantResult:
    name: str
    verdict: str
    detail: str
    measured: float
    target: float
    residual: float


@dataclass
class ContractVerdict:
    overall: str
    invariant_results: list = field(default_factory=list)
    contract_sha256: str = ""

    def to_payload(self) -> dict:
        return {
            "overall": self.overall,
            "contract_sha256": self.contract_sha256,
            "invariant_results": [
                {
                    "name": r.name, "verdict": r.verdict, "detail": r.detail,
                    "measured": r.measured, "target": r.target,
                    "residual": r.residual,
                }
                for r in self.invariant_results
            ],
        }


def _score_one(inv, m, abstain_factor):
    residual = m.value - inv.target

    if m.sigma > abstain_factor * inv.tol:
        return InvariantResult(
            inv.name, "ABSTAIN",
            "sigma=%.2e exceeds %s*tol=%.2e" % (m.sigma, abstain_factor, abstain_factor * inv.tol),
            m.value, inv.target, residual,
        )

    if inv.kind == "lower_bound":
        if residual < -inv.tol:
            return InvariantResult(
                inv.name, "FLAG",
                "energy %.2e Ha below exact ground state (violates variational principle)" % residual,
                m.value, inv.target, residual,
            )
        return InvariantResult(inv.name, "ACCEPT",
                               "at or above exact ground state within tol",
                               m.value, inv.target, residual)

    if inv.kind == "equality":
        if abs(residual) > inv.tol:
            return InvariantResult(inv.name, "FLAG",
                                   "|residual|=%.2e exceeds tol=%.2e" % (abs(residual), inv.tol),
                                   m.value, inv.target, residual)
        return InvariantResult(inv.name, "ACCEPT",
                               "within tolerance", m.value, inv.target, residual)

    raise ValueError("unknown invariant kind: %s" % inv.kind)


def score(contract, measurements):
    """Apply a frozen contract. any hard FLAG -> FLAG; else hard ABSTAIN -> ABSTAIN; else ACCEPT."""
    results = []
    for inv in contract.invariants:
        if inv.name not in measurements:
            results.append(InvariantResult(inv.name, "ABSTAIN",
                                           "no measurement supplied",
                                           float("nan"), inv.target, float("nan")))
            continue
        results.append(_score_one(inv, measurements[inv.name],
                                  contract.abstain_sigma_factor))

    hard = {inv.name: inv.hard for inv in contract.invariants}
    if any(r.verdict == "FLAG" and hard.get(r.name, False) for r in results):
        overall = "FLAG"
    elif any(r.verdict == "ABSTAIN" and hard.get(r.name, False) for r in results):
        overall = "ABSTAIN"
    else:
        overall = "ACCEPT"

    return ContractVerdict(
        overall=overall,
        invariant_results=results,
        contract_sha256=sha256_of(contract.to_payload()),
    )
