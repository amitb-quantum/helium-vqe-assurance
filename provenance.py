"""
provenance.py
=============
Tamper-evident provenance helpers. Every artifact in the pipeline is reduced
to a canonical JSON form and hashed with SHA-256, so a verdict can be
recomputed and audited later from the same inputs (the discipline the
QuantaCore / Eigenspectrum pipeline is built around).

Nothing here is proprietary -- it is a minimal, open reference implementation
of "freeze it, hash it, bind the verdict to the hash".
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def canonical_json(obj) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace.

    Complex numbers are encoded as [re, im] so Pauli coefficients hash stably.
    """
    def default(o):
        if isinstance(o, complex):
            return {"__complex__": [o.real, o.imag]}
        raise TypeError(f"not JSON serialisable: {type(o)}")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=default)


def sha256_of(obj) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of obj."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def freeze(label: str, payload: dict) -> dict:
    """Wrap a payload into a frozen, hash-bound record.

    The returned dict embeds its own content hash. Re-hashing the 'payload'
    field must reproduce 'sha256' -- that is the audit check.
    """
    return {
        "label": label,
        "frozen_at_utc": utc_now_iso(),
        "sha256": sha256_of(payload),
        "payload": payload,
    }


def verify_frozen(record: dict) -> bool:
    """Recompute the hash of a frozen record's payload and compare."""
    return sha256_of(record["payload"]) == record["sha256"]
