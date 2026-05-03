"""
Vera Engagement Composer — LLM-based message composition engine.
Takes 4 contexts → produces validated ComposedMessage.
"""

from __future__ import annotations
import json
import asyncio
from typing import Optional

from llm_client import LLMClient
from prompts.system_prompt import build_system_prompt
from prompts.trigger_prompts import get_trigger_prompt
from deterministic_composer import compose_deterministic


class EngagementComposer:
    """Composes WhatsApp messages using LLM with trigger-specific routing."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def compose(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: dict = None
    ) -> Optional[dict]:
        """
        Compose a message for a (category, merchant, trigger, customer?) tuple.
        Returns dict with {body, cta, send_as, suppression_key, rationale} or None on failure.
        """
        deterministic = compose_deterministic(category, merchant, trigger, customer)
        if deterministic.get("body"):
            polished = await self._llm_polish(deterministic, category, merchant, trigger, customer)
            if polished:
                return self._validate(polished, category, merchant, trigger, customer)
            return self._validate(deterministic, category, merchant, trigger, customer)

        try:
            # 1. Build system prompt from category voice
            system = build_system_prompt(category)

            # 2. Get trigger-specific user prompt
            kind = trigger.get("kind", "unknown")
            prompt_builder = get_trigger_prompt(kind)
            user_prompt = prompt_builder(category, merchant, trigger, customer)

            # 3. Call LLM
            response = await self.llm.complete(system, user_prompt, temperature=0.1, json_mode=True)
            result = response.parse_json()

            # 4. Post-validate
            result = self._validate(result, category, merchant, trigger, customer)

            # 5. Ensure suppression_key
            if not result.get("suppression_key"):
                result["suppression_key"] = trigger.get("suppression_key", f"{kind}:{merchant.get('merchant_id', '?')}")

            return result

        except Exception as e:
            # Fallback: try once more with simplified prompt
            try:
                return await self._fallback_compose(category, merchant, trigger, customer)
            except Exception:
                return None

    async def _llm_polish(
        self,
        draft: dict,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: dict = None,
    ) -> Optional[dict]:
        """Use the configured LLM to improve wording while preserving exact facts."""
        if not getattr(self.llm, "is_configured", False):
            return None
        if trigger.get("kind") in {
            "active_planning_intent",
            "chronic_refill_due",
            "supply_alert",
            "regulation_change",
        }:
            return None

        identity = merchant.get("identity", {})
        perf = merchant.get("performance", {})
        active_offers = [
            o.get("title", "")
            for o in merchant.get("offers", [])
            if o.get("status") == "active"
        ]
        customer_block = customer or {}

        system = """You are Vera's final message editor for the magicpin AI Challenge.
Improve the draft, but preserve factual safety.

Rules:
- Use ONLY facts present in the provided JSON context or already present in the draft.
- Do not invent numbers, peer counts, percentages, prices, dates, offers, sources, or customer details.
- Keep owner name, merchant name, and locality in the first sentence for merchant-facing messages.
- For customer-facing messages, address the customer by name and keep send_as=merchant_on_behalf.
- Translate internal tokens into merchant/customer-friendly language.
- Optimize for merchant reply likelihood: make the payoff concrete, immediate, and low-effort.
- Use one of these engagement levers when true from context: loss avoided, time window, exact ready-to-use artifact, curiosity, or convenience.
- Avoid generic phrases like "growth plan", "campaign", "checklist", or "draft" unless the body says exactly what artifact Vera will send.
- Make the CTA more compelling and low-friction, but keep a single CTA at the end.
- Keep body between 180 and 420 characters.
- Output JSON only."""

        user = f"""CATEGORY:
{json.dumps({"slug": category.get("slug"), "voice": category.get("voice", {}), "peer_stats": category.get("peer_stats", {})}, ensure_ascii=False)}

MERCHANT:
{json.dumps({"merchant_id": merchant.get("merchant_id"), "identity": identity, "performance": perf, "signals": merchant.get("signals", []), "active_offers": active_offers, "review_themes": merchant.get("review_themes", [])}, ensure_ascii=False)}

TRIGGER:
{json.dumps({"id": trigger.get("id"), "kind": trigger.get("kind"), "scope": trigger.get("scope"), "payload": trigger.get("payload", {}), "urgency": trigger.get("urgency"), "suppression_key": trigger.get("suppression_key")}, ensure_ascii=False)}

CUSTOMER:
{json.dumps(customer_block, ensure_ascii=False)}

CURRENT DRAFT:
{json.dumps(draft, ensure_ascii=False)}

Return exactly:
{{
  "body": "<improved WhatsApp message>",
  "cta": "{draft.get('cta', 'binary_yes_no')}",
  "send_as": "{draft.get('send_as', 'vera')}",
  "suppression_key": "{draft.get('suppression_key', trigger.get('suppression_key', ''))}",
  "rationale": "<why this is more specific/engaging>"
}}"""

        try:
            response = await asyncio.wait_for(
                self.llm.complete(system, user, temperature=0.05, json_mode=True),
                timeout=7.0,
            )
            result = response.parse_json()
        except Exception:
            return None

        body = str(result.get("body", "")).strip()
        if not body or len(body) < 80 or "reply" not in body.lower():
            return None
        if draft.get("send_as") == "merchant_on_behalf":
            result["send_as"] = "merchant_on_behalf"
        else:
            result["send_as"] = "vera"
        result["cta"] = result.get("cta") or draft.get("cta", "binary_yes_no")
        result["suppression_key"] = draft.get("suppression_key", trigger.get("suppression_key", ""))
        result["rationale"] = result.get("rationale", draft.get("rationale", "LLM-polished deterministic draft."))
        return result

    async def compose_reply(
        self,
        conversation: dict,
        mode: str,
        category: dict = None,
        merchant: dict = None,
        trigger: dict = None
    ) -> dict:
        """
        Compose a reply in an active conversation.
        mode: 'action_mode', 'continuation', 'continuation_alt'
        """
        turns = conversation.get("turns", [])
        turn_str = "\n".join([f"[{t['from'].upper()}] {t['msg']}" for t in turns[-6:]])

        # Build category-appropriate system prompt if available
        system = build_system_prompt(category) if category else self._default_reply_system()

        merchant_name = "the merchant"
        merchant_info = ""
        if merchant:
            identity = merchant.get("identity", {})
            merchant_name = identity.get("owner_first_name", identity.get("name", "the merchant"))
            merchant_info = f"""
MERCHANT: {identity.get('name', '?')} ({identity.get('city', '?')}, {identity.get('locality', '?')})
Owner: {identity.get('owner_first_name', '?')}
Languages: {identity.get('languages', ['en'])}
Active offers: {[o['title'] for o in merchant.get('offers', []) if o.get('status') == 'active']}
"""

        mode_instruction = {
            "action_mode": f"""The merchant just COMMITTED to action. DO NOT ask more qualifying questions.
Provide CONCRETE next steps: what you'll do, what they'll see, timeline.
Examples: "Drafting now — 90 seconds", "Done! Here's what I set up:", "Sending the draft now"
{merchant_info}""",
            "continuation": f"""Continue the conversation naturally. Build on what was discussed.
Answer any questions the merchant asked. Add value.
Do NOT repeat what you already said.
{merchant_info}""",
            "continuation_alt": f"""Continue the conversation with a DIFFERENT angle than before.
Bring in a new piece of relevant context (a digest item, a peer stat, a seasonal insight).
{merchant_info}"""
        }.get(mode, f"Continue helpfully.\n{merchant_info}")

        user_prompt = f"""{mode_instruction}

CONVERSATION SO FAR:
{turn_str}

Compose Vera's next reply. Output ONLY this JSON:
{{
  "body": "<reply text>",
  "cta": "<binary_yes_no | open_ended | none>",
  "rationale": "<why this reply, what it achieves>"
}}"""

        response = await self.llm.complete(system, user_prompt, temperature=0.15, json_mode=True)
        result = response.parse_json()

        # Ensure required fields
        result.setdefault("cta", "open_ended")
        result.setdefault("rationale", "Continuation reply")
        return result

    def _validate(self, result: dict, category: dict, merchant: dict,
                  trigger: dict, customer: dict = None) -> dict:
        """Post-validation: check for anti-patterns."""
        body = result.get("body", "")

        # Check for URLs
        if "http://" in body or "https://" in body or "www." in body:
            # Strip URLs
            import re
            body = re.sub(r'https?://\S+', '', body)
            body = re.sub(r'www\.\S+', '', body)
            result["body"] = body.strip()

        # Check taboo words
        voice = category.get("voice", {})
        taboos = voice.get("vocab_taboo", [])
        body_lower = body.lower()
        for taboo in taboos:
            if taboo.lower() in body_lower:
                body = body.replace(taboo, "")
                body = body.replace(taboo.lower(), "")

        result["body"] = body.strip()

        # Ensure send_as is correct
        if trigger.get("scope") == "customer" and customer:
            result["send_as"] = "merchant_on_behalf"
        elif not result.get("send_as"):
            result["send_as"] = "vera"

        # Ensure cta exists
        if not result.get("cta"):
            result["cta"] = "open_ended"

        # Ensure rationale exists
        if not result.get("rationale"):
            result["rationale"] = f"Composed for trigger {trigger.get('kind', '?')}"

        if len(result["body"]) > 420:
            if " Reply " in result["body"]:
                head, tail = result["body"].rsplit(" Reply ", 1)
                keep = max(120, 417 - len(tail) - len(" Reply ..."))
                result["body"] = head[:keep].rstrip() + "... Reply " + tail
            else:
                result["body"] = result["body"][:417].rstrip() + "..."

        return result

    async def _fallback_compose(self, category: dict, merchant: dict,
                                trigger: dict, customer: dict = None) -> dict:
        """Simplified fallback composition when primary fails."""
        identity = merchant.get("identity", {})
        name = identity.get("owner_first_name", identity.get("name", "there"))
        kind = trigger.get("kind", "update")
        is_customer_facing = trigger.get("scope") == "customer" and customer

        system = "You are Vera, a merchant assistant. Return valid JSON only."
        user = f"""Compose a brief WhatsApp message for {name} about: {kind}.
Merchant: {identity.get('name', '?')} in {identity.get('locality', '?')}, {identity.get('city', '?')}
Trigger: {json.dumps(trigger.get('payload', {}))}

Return JSON: {{"body": "...", "cta": "open_ended", "send_as": "{'merchant_on_behalf' if is_customer_facing else 'vera'}", "suppression_key": "{trigger.get('suppression_key', kind)}", "rationale": "..."}}"""

        response = await self.llm.complete(system, user, temperature=0.2, json_mode=True)
        return response.parse_json()

    def _default_reply_system(self) -> str:
        return """You are Vera, magicpin's merchant growth assistant.
Reply concisely and helpfully. Match the merchant's language.
No URLs. No fabrication. Single CTA at the end.
Output JSON only: {"body": "...", "cta": "...", "rationale": "..."}"""
