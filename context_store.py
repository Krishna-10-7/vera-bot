"""
Vera Context Store — Versioned in-memory storage for all 4 context scopes.
Idempotent by (context_id, version). Atomic version replacement.
"""

from __future__ import annotations
from typing import Any, Optional
from datetime import datetime


class ContextStore:
    """Thread-safe, versioned, in-memory context store."""

    def __init__(self):
        # Storage: {(scope, context_id): {"version": int, "payload": dict, "stored_at": str}}
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def push(self, scope: str, context_id: str, version: int, payload: dict) -> tuple[bool, str, int | None]:
        """
        Push a context payload. Returns (accepted, reason, current_version).
        - Accepted if version > current version (or no prior version).
        - Rejected with 'stale_version' if version <= current.
        """
        valid_scopes = {"category", "merchant", "customer", "trigger"}
        if scope not in valid_scopes:
            return False, "invalid_scope", None

        key = (scope, context_id)
        existing = self._store.get(key)

        if existing and existing["version"] >= version:
            return False, "stale_version", existing["version"]

        self._store[key] = {
            "version": version,
            "payload": payload,
            "stored_at": datetime.utcnow().isoformat() + "Z"
        }
        return True, "ok", version

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        """Get the payload for a (scope, context_id) pair."""
        entry = self._store.get((scope, context_id))
        return entry["payload"] if entry else None

    def get_category(self, slug: str) -> Optional[dict]:
        return self.get("category", slug)

    def get_merchant(self, merchant_id: str) -> Optional[dict]:
        return self.get("merchant", merchant_id)

    def get_customer(self, customer_id: str) -> Optional[dict]:
        return self.get("customer", customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[dict]:
        return self.get("trigger", trigger_id)

    def get_category_for_merchant(self, merchant_id: str) -> Optional[dict]:
        """Cross-reference: merchant → category via category_slug."""
        merchant = self.get_merchant(merchant_id)
        if merchant and "category_slug" in merchant:
            return self.get_category(merchant["category_slug"])
        return None

    def counts(self) -> dict[str, int]:
        """Count contexts by scope for healthz."""
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _) in self._store:
            if scope in counts:
                counts[scope] += 1
        return counts

    def all_by_scope(self, scope: str) -> list[dict]:
        """Get all payloads for a given scope."""
        return [
            entry["payload"]
            for (s, _), entry in self._store.items()
            if s == scope
        ]
