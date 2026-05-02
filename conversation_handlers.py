"""
Vera Conversation Handlers — High-level orchestration for multi-turn merchant interactions.
This module is a required submission artifact for the magicpin AI Challenge.

Handles:
- Auto-reply detection and graceful exit after 3 strikes
- Intent transition to action mode
- Hostile message detection and brand-safe exit
- Off-topic redirection
- Anti-repetition across conversation turns
"""

from __future__ import annotations
from typing import Optional
from conversation_manager import ConversationManager
from composer import EngagementComposer


class ConversationHandler:
    """
    High-level handler for processing merchant replies within active conversations.
    Wraps the ConversationManager FSM and EngagementComposer to produce
    appropriate responses based on message classification.
    """

    def __init__(self, conv_mgr: ConversationManager, composer: EngagementComposer):
        self.conv_mgr = conv_mgr
        self.composer = composer

    async def handle_reply(
        self,
        conversation_id: str,
        merchant_id: str,
        trigger_id: str,
        from_role: str,
        message: str,
        context_resolver=None
    ) -> dict:
        """
        Process an incoming reply and return the bot's action.

        Args:
            conversation_id: Unique conversation identifier
            merchant_id: The merchant involved
            trigger_id: The trigger that initiated this conversation
            from_role: "merchant" or "customer"
            message: The incoming message text
            context_resolver: Optional callable(merchant_id) → (category, merchant, trigger)

        Returns:
            dict with keys: action, body?, cta?, rationale
        """
        # Get or create conversation state
        conv = self.conv_mgr.get_or_create(conversation_id, merchant_id, trigger_id)

        # Record the incoming turn
        self.conv_mgr.add_turn(conversation_id, from_role, message)

        # Don't re-engage ended conversations
        if self.conv_mgr.is_ended(conversation_id):
            return {"action": "none", "rationale": "Conversation already ended."}

        # Classify the message
        classification = self.conv_mgr.classify_reply(message, conv)

        # Route to appropriate handler
        handler_map = {
            "AUTO_REPLY": self._handle_auto_reply,
            "HARD_NO": self._handle_hard_no,
            "HOSTILE": self._handle_hostile,
            "INTENT_COMMIT": self._handle_intent_commit,
            "ENGAGED": self._handle_engaged,
        }

        handler = handler_map.get(classification, self._handle_engaged)
        return await handler(conversation_id, merchant_id, trigger_id, conv, context_resolver)

    async def _handle_auto_reply(self, conv_id, merchant_id, trigger_id, conv, resolver) -> dict:
        """Handle detected auto-replies with progressive patience."""
        conv["auto_reply_count"] = conv.get("auto_reply_count", 0) + 1
        count = conv["auto_reply_count"]

        if count == 1:
            body = "Looks like an auto-reply! 😊 When you see this, just reply 'Yes' or 'Not now' — I'll take it from there."
            self.conv_mgr.add_turn(conv_id, "vera", body)
            self.conv_mgr.set_last_sent(conv_id, body)
            return {"action": "send", "body": body, "cta": "binary_yes_no",
                    "rationale": "Auto-reply detected (1st). One nudge for the owner."}
        elif count == 2:
            return {"action": "wait", "wait_seconds": 86400,
                    "rationale": "Auto-reply detected twice. Owner likely unavailable. Waiting 24h."}
        else:
            self.conv_mgr.mark_ended(conv_id)
            return {"action": "end",
                    "rationale": "Auto-reply detected 3+ times. Closing conversation."}

    async def _handle_hard_no(self, conv_id, merchant_id, trigger_id, conv, resolver) -> dict:
        """Handle explicit opt-out."""
        self.conv_mgr.mark_ended(conv_id)
        if merchant_id:
            self.conv_mgr.suppress_merchant(merchant_id)
        return {"action": "end",
                "rationale": "Merchant explicitly opted out. Conversation closed."}

    async def _handle_hostile(self, conv_id, merchant_id, trigger_id, conv, resolver) -> dict:
        """Handle hostile messages with brand-safe exit."""
        body = "Apologies for the bother — won't message again. If anything changes, just text 'Hi Vera'. 🙏"
        self.conv_mgr.add_turn(conv_id, "vera", body)
        self.conv_mgr.mark_ended(conv_id)
        if merchant_id:
            self.conv_mgr.suppress_merchant(merchant_id)
        return {"action": "send", "body": body, "cta": "none",
                "rationale": "Hostile message detected. One-line apology + exit."}

    async def _handle_intent_commit(self, conv_id, merchant_id, trigger_id, conv, resolver) -> dict:
        """Handle merchant committing to action."""
        conv["state"] = "ACTION_MODE"

        category, merchant, trigger = None, None, None
        if resolver:
            category, merchant, trigger = resolver(merchant_id)

        try:
            result = await self.composer.compose_reply(
                conv, "action_mode", category, merchant, trigger
            )
            body = result.get("body", "On it! Setting things up now. ✅")
        except Exception:
            body = "On it! Setting things up — will share the details shortly. ✅"
            result = {"cta": "none", "rationale": "Intent commit — fallback confirmation."}

        self.conv_mgr.add_turn(conv_id, "vera", body)
        self.conv_mgr.set_last_sent(conv_id, body)
        return {"action": "send", "body": body,
                "cta": result.get("cta", "none"),
                "rationale": result.get("rationale", "Merchant committed. Providing next steps.")}

    async def _handle_engaged(self, conv_id, merchant_id, trigger_id, conv, resolver) -> dict:
        """Handle engaged merchant — continue the conversation."""
        conv["state"] = "ENGAGED"

        category, merchant, trigger = None, None, None
        if resolver:
            category, merchant, trigger = resolver(merchant_id)

        try:
            result = await self.composer.compose_reply(
                conv, "continuation", category, merchant, trigger
            )
            body = result.get("body", "")

            # Anti-repetition
            if body == self.conv_mgr.get_last_sent(conv_id):
                result = await self.composer.compose_reply(
                    conv, "continuation_alt", category, merchant, trigger
                )
                body = result.get("body", "Let me pull some fresh data on this — one moment.")
        except Exception:
            body = "Good question — let me look into this and get back to you."
            result = {"cta": "open_ended", "rationale": "Engagement reply — fallback."}

        self.conv_mgr.add_turn(conv_id, "vera", body)
        self.conv_mgr.set_last_sent(conv_id, body)
        return {"action": "send", "body": body,
                "cta": result.get("cta", "open_ended"),
                "rationale": result.get("rationale", "Continued engaged conversation.")}
