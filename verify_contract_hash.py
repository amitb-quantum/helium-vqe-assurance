"""
verify_contract_hash.py
=======================
Independently confirm the pre-registered contract receipt.

The published hash (44d34db0…) is NOT `sha256sum contract.py`. It is the
SHA-256 of the contract's canonical-JSON payload — the object the pipeline
actually freezes and that the postflight scorer recomputes. This script
recomputes it two ways and checks they agree with the published value:

  (1) from the live code  : helium_contract(...).freeze()
  (2) from the receipt    : frozen_contract.json on disk

Run:
    python verify_contract_hash.py
No quantum hardware, credentials, or network needed.
"""
import json
from helium_hamiltonian import build_helium_hamiltonian
from contract import helium_contract
from provenance import sha256_of, verify_frozen, canonical_json

PUBLISHED = "44d34db05a53f148672dc1e2108604977243f0e9fd1574e1b6a61db8d2ed35c3"

b = build_helium_hamiltonian()
c = helium_contract(b.exact_qubit_ground_energy, b.n_electrons)
from_code = c.freeze()["sha256"]

with open("frozen_contract.json") as f:
    receipt = json.load(f)
from_receipt = receipt["sha256"]
receipt_payload_hash = sha256_of(receipt["payload"])

print("published hash      :", PUBLISHED)
print("recomputed (code)   :", from_code)
print("recorded (receipt)  :", from_receipt)
print("receipt payload hash:", receipt_payload_hash)
print()
ok = (from_code == PUBLISHED == from_receipt == receipt_payload_hash
      and verify_frozen(receipt))
print("canonical payload:")
print(" ", canonical_json(receipt["payload"]))
print()
print("ALL CHECKS PASS" if ok else "MISMATCH — DO NOT TRUST")
raise SystemExit(0 if ok else 1)
