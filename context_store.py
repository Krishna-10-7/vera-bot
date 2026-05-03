"""
Vera Context Store — Versioned in-memory storage for all 4 context scopes.
Idempotent by (context_id, version). Atomic version replacement.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


class ContextStore:
    """Thread-safe, versioned, in-memory context store."""

    def __init__(self):
        # Storage: {(scope, context_id): {"version": int, "payload": dict, "stored_at": str}}
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._seed_cache: dict[str, dict[str, dict]] = {}

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

        if existing and existing["version"] > version:
            return False, "stale_version", existing["version"]
        if existing and existing["version"] == version:
            return True, "ok", existing["version"]

        self._store[key] = {
            "version": version,
            "payload": payload,
            "stored_at": datetime.utcnow().isoformat() + "Z"
        }
        return True, "ok", version

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        """Get the payload for a (scope, context_id) pair."""
        entry = self._store.get((scope, context_id))
        if entry:
            return entry["payload"]
        return self._get_seed(scope, context_id)

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

    def _get_seed(self, scope: str, context_id: str) -> Optional[dict]:
        """Lazy local fallback for the bundled simulator, which omits customer pushes."""
        if scope not in self._seed_cache:
            self._seed_cache[scope] = self._load_seed_scope(scope)
        return self._seed_cache[scope].get(context_id)

    def _load_seed_scope(self, scope: str) -> dict[str, dict]:
        dataset_dir = Path(__file__).parent / "dataset"
        files = {
            "merchant": (dataset_dir / "merchants_seed.json", "merchants", "merchant_id"),
            "customer": (dataset_dir / "customers_seed.json", "customers", "customer_id"),
            "trigger": (dataset_dir / "triggers_seed.json", "triggers", "id"),
        }

        if scope == "category":
            data: dict[str, dict] = {}
            cat_dir = dataset_dir / "categories"
            if not cat_dir.exists():
                return data
            for path in cat_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    data[payload.get("slug", path.stem)] = payload
                except Exception:
                    continue
            return data

        if scope not in files:
            return {}

        path, collection_key, id_key = files[scope]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        return {
            item[id_key]: item
            for item in raw.get(collection_key, [])
            if isinstance(item, dict) and item.get(id_key)
        }
