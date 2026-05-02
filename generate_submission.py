"""
Generate submission.jsonl — compose messages for all 30 test pairs.

Usage:
    python generate_submission.py

Requires:
    - expanded dataset at ./dataset/expanded/
    - LLM API key configured via environment variable
"""

from __future__ import annotations
import asyncio
import json
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from llm_client import LLMClient
from composer import EngagementComposer


async def main():
    # Load expanded dataset
    expanded_dir = Path("dataset/expanded")

    if not expanded_dir.exists():
        print("ERROR: Run 'python dataset/generate_dataset.py --seed-dir ./dataset --out ./dataset/expanded' first")
        sys.exit(1)

    # Load test pairs
    with open(expanded_dir / "test_pairs.json") as f:
        test_pairs = json.load(f)["pairs"]

    print(f"Loaded {len(test_pairs)} test pairs")

    # Load all contexts
    categories = {}
    for f_path in (expanded_dir / "categories").glob("*.json"):
        with open(f_path) as f:
            data = json.load(f)
            categories[data["slug"]] = data

    merchants = {}
    for f_path in (expanded_dir / "merchants").glob("*.json"):
        with open(f_path) as f:
            data = json.load(f)
            merchants[data["merchant_id"]] = data

    customers = {}
    for f_path in (expanded_dir / "customers").glob("*.json"):
        with open(f_path) as f:
            data = json.load(f)
            customers[data["customer_id"]] = data

    triggers = {}
    for f_path in (expanded_dir / "triggers").glob("*.json"):
        with open(f_path) as f:
            data = json.load(f)
            triggers[data["id"]] = data

    print(f"Loaded: {len(categories)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers")

    # Initialize LLM and composer
    llm = LLMClient()
    composer = EngagementComposer(llm)
    print(f"LLM provider: {llm.primary_provider}")

    # Compose messages for all test pairs
    results = []
    for i, pair in enumerate(test_pairs):
        test_id = pair["test_id"]
        trigger_id = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        trigger = triggers.get(trigger_id, {})
        merchant = merchants.get(merchant_id, {})
        category_slug = merchant.get("category_slug", "")
        category = categories.get(category_slug, {})
        customer = customers.get(customer_id) if customer_id else None

        print(f"\n[{i+1}/{len(test_pairs)}] {test_id}: {trigger.get('kind', '?')} → {merchant.get('identity', {}).get('name', '?')}")

        try:
            result = await composer.compose(category, merchant, trigger, customer)
            if result:
                entry = {
                    "test_id": test_id,
                    "trigger_id": trigger_id,
                    "merchant_id": merchant_id,
                    "customer_id": customer_id,
                    "body": result.get("body", ""),
                    "cta": result.get("cta", "open_ended"),
                    "send_as": result.get("send_as", "vera"),
                    "suppression_key": result.get("suppression_key", ""),
                    "rationale": result.get("rationale", ""),
                }
                results.append(entry)
                print(f"  ✓ {result.get('body', '')[:80]}...")
            else:
                print(f"  ✗ Composition returned None")
                results.append({
                    "test_id": test_id, "trigger_id": trigger_id,
                    "merchant_id": merchant_id, "customer_id": customer_id,
                    "body": "Unable to compose — context insufficient.",
                    "cta": "none", "send_as": "vera",
                    "suppression_key": "", "rationale": "Fallback entry",
                })
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append({
                "test_id": test_id, "trigger_id": trigger_id,
                "merchant_id": merchant_id, "customer_id": customer_id,
                "body": "Unable to compose — error during generation.",
                "cta": "none", "send_as": "vera",
                "suppression_key": "", "rationale": f"Error: {e}",
            })

        # Small delay to respect rate limits
        await asyncio.sleep(0.5)

    # Write submission.jsonl
    output_path = Path("submission.jsonl")
    with open(output_path, "w") as f:
        for entry in results:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Written {len(results)} entries to {output_path}")
    print(f"{'='*60}")

    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
