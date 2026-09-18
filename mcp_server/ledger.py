"""Decision ledger — the agent's accountability trail.

Every decision the agent makes is appended here with a one-line reason:
what it surfaced (alert), what it held back and why (suppress / hold),
what it refused to do (refuse), what the human overruled (challenge).
Cancelled or withheld items are ALWAYS recorded — silence is also a decision.

The ledger is the observability surface of the product: "why did you bother
me — and why did you NOT bother me" must be answerable line by line.

Tamper-evidence (2026-09-18): entries are hash-chained. Each entry records
the hash of its predecessor and its own SHA256 over the canonical payload,
so any edit to a recorded decision breaks verification from that point on.
The chain anchors at the earliest surviving entry (the ledger is capped at
MAX_ENTRIES, so verification proves "nothing in the retained window was
altered", which is exactly the promise an audit trail can make honestly).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import store

MAX_ENTRIES = 500
GENESIS_HASH = "0" * 64


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry_hash(prev_hash: str, body: dict) -> str:
    material = {"prev_hash": prev_hash, **body}
    return hashlib.sha256(_canonical(material)).hexdigest()


def record(kind: str, subject: str, reason: str, evidence: list[str] | None = None,
           path: Path | None = None) -> dict:
    """Append one decision entry. `kind` in alert|suppress|hold|propose|refuse|challenge|budget."""
    state = store.load_state(path)
    chain = state["ledger"]
    prev_hash = chain[-1]["hash"] if chain and "hash" in chain[-1] else GENESIS_HASH
    body = {
        "seq": len(chain) + 1,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "subject": subject,
        "reason": reason,
        "evidence": evidence or [],
    }
    entry = {**body, "prev_hash": prev_hash, "hash": _entry_hash(prev_hash, body)}
    chain.append(entry)
    state["ledger"] = chain[-MAX_ENTRIES:]
    store.save_state(state, path)
    return entry


def verify_chain(path: Path | None = None) -> dict:
    """Re-derive every hash in the retained window.

    Returns {"ok", "entries", "legacy", "broken_at"}. `legacy` counts
    pre-chain entries without a hash field; `broken_at` is the seq of the
    first entry whose stored hash no longer matches its content or whose
    prev_hash pointer was rewired.
    """
    chain = store.load_state(path)["ledger"]
    legacy = 0
    expected_prev: str | None = None
    for entry in chain:
        if "hash" not in entry:
            legacy += 1
            expected_prev = None  # restart the chain after a legacy block
            continue
        body = {k: v for k, v in entry.items() if k not in ("hash",)}
        if expected_prev is not None and entry["prev_hash"] != expected_prev:
            return {"ok": False, "entries": len(chain), "legacy": legacy,
                    "broken_at": entry["seq"], "reason": "prev_hash pointer mismatch"}
        if _entry_hash(entry["prev_hash"], body) != entry["hash"]:
            return {"ok": False, "entries": len(chain), "legacy": legacy,
                    "broken_at": entry["seq"], "reason": "content hash mismatch"}
        expected_prev = entry["hash"]
    return {"ok": True, "entries": len(chain), "legacy": legacy, "broken_at": None}


def entries(path: Path | None = None, kinds: set[str] | None = None) -> list[dict]:
    ledger = store.load_state(path)["ledger"]
    if kinds:
        ledger = [e for e in ledger if e["kind"] in kinds]
    return ledger


def has_fired(anomaly_id: str, month: str, path: Path | None = None) -> bool:
    """True if this anomaly was already surfaced for this month (suppression)."""
    fired = store.load_state(path)["alerts_fired"]
    return fired.get(anomaly_id) == month


def mark_fired(anomaly_id: str, month: str, path: Path | None = None) -> None:
    state = store.load_state(path)
    state["alerts_fired"][anomaly_id] = month
    store.save_state(state, path)


def challenge(entry_seq: int, note: str, path: Path | None = None) -> dict:
    """The human overrules a decision. Challenges flow back as context —
    the challenged subject will not be suppressed the same way again."""
    state = store.load_state(path)
    target = next((e for e in state["ledger"] if e["seq"] == entry_seq), None)
    if target is None:
        raise KeyError(f"no ledger entry with seq={entry_seq}")
    challenge_record = {"seq": entry_seq, "subject": target["subject"], "note": note,
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    state["challenges"].append(challenge_record)
    store.save_state(state, path)
    record("challenge", target["subject"], f"Human overruled: {note}", path=path)
    return challenge_record


def challenged_subjects(path: Path | None = None) -> set[str]:
    return {c["subject"] for c in store.load_state(path)["challenges"]}
