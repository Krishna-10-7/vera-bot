"""
Vera Conversation Manager — Multi-turn finite state machine.
Handles auto-reply detection, intent transitions, hostile exits, and anti-repetition.
"""

from __future__ import annotations
from typing import Optional
from datetime import datetime


class ConversationManager:
    """Manages stateful multi-turn conversations per conversation_id."""

    def __init__(self):
        # {conversation_id: ConversationState}
        self._conversations: dict[str, dict] = {}
        # {merchant_id: suppressed_until_ts} for merchants who opted out
        self._suppressed_merchants: set[str] = set()

    def get_or_create(self, conversation_id: str, merchant_id: str = None,
                      trigger_id: str = None) -> dict:
        """Get existing conversation or create new one."""
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = {
                "id": conversation_id,
                "merchant_id": merchant_id,
                "trigger_id": trigger_id,
                "state": "INITIATED",
                "turns": [],
                "auto_reply_count": 0,
                "last_sent_body": "",
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
        return self._conversations[conversation_id]

    def add_turn(self, conversation_id: str, from_role: str, message: str):
        """Record a conversation turn."""
        conv = self.get_or_create(conversation_id)
        conv["turns"].append({
            "from": from_role,
            "msg": message,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

    def classify_reply(self, message: str, conversation: dict) -> str:
        """
        Classify incoming merchant/customer message into response categories.
        Returns: AUTO_REPLY, HARD_NO, HOSTILE, INTENT_COMMIT, ENGAGED
        """
        msg_lower = message.lower().strip()

        # ── AUTO-REPLY detection ──
        auto_reply_signals = [
            "thank you for contacting",
            "our team will respond",
            "we will get back",
            "automated message",
            "auto reply",
            "our team will get back",
            "hamari team",
            "ham jaldi se",
            "thank you for reaching out",
            "we appreciate your message",
            "is currently unavailable",
            "automated assistant",
        ]
        if any(sig in msg_lower for sig in auto_reply_signals):
            return "AUTO_REPLY"

        # Check for verbatim repetition (same message sent before by this role)
        prev_merchant_msgs = [
            t["msg"] for t in conversation.get("turns", [])
            if t["from"] in ("merchant", "customer") and t["msg"] != message
        ]
        # If this exact message appeared before from the same role
        merchant_msgs = [t["msg"] for t in conversation.get("turns", [])
                        if t["from"] in ("merchant", "customer")]
        if merchant_msgs.count(message) >= 1:  # Already seen once before this
            return "AUTO_REPLY"

        # ── HARD NO / OPT-OUT ──
        hard_no_signals = [
            "stop", "not interested", "unsubscribe", "don't message",
            "dont message", "stop messaging", "remove me", "opt out",
            "band karo", "nahi chahiye", "mat bhejo", "nahi", "no thanks",
        ]
        if any(sig in msg_lower for sig in hard_no_signals):
            return "HARD_NO"

        # ── HOSTILE ──
        hostile_signals = [
            "useless", "spam", "bothering", "stupid", "idiot", "nonsense",
            "bakwas", "time waste", "waste of time", "stop this",
            "why are you", "leave me alone",
        ]
        if any(sig in msg_lower for sig in hostile_signals):
            return "HOSTILE"

        # ── EXPLICIT INTENT (ready to act) ──
        intent_signals = [
            "let's do it", "lets do it", "go ahead", "proceed",
            "yes please", "yes do it", "ok do it", "confirm",
            "haan", "haan karo", "kar do", "shuru karo", "chalao",
            "ok let's do it", "ok lets do it", "yes go ahead",
            "do it", "start it", "yes send",
        ]
        # Also match simple "yes" / "ok" only if it's short
        if msg_lower.strip() in ("yes", "ok", "haan", "sure", "done", "go"):
            return "INTENT_COMMIT"
        if any(sig in msg_lower for sig in intent_signals):
            return "INTENT_COMMIT"

        # ── DEFAULT: ENGAGED ──
        return "ENGAGED"

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        """Check if a merchant has been suppressed (opted out)."""
        return merchant_id in self._suppressed_merchants

    def suppress_merchant(self, merchant_id: str):
        """Suppress all future triggers for this merchant."""
        self._suppressed_merchants.add(merchant_id)

    def mark_ended(self, conversation_id: str):
        """Mark conversation as ended."""
        if conversation_id in self._conversations:
            self._conversations[conversation_id]["state"] = "ENDED"

    def is_ended(self, conversation_id: str) -> bool:
        conv = self._conversations.get(conversation_id, {})
        return conv.get("state") == "ENDED"

    def set_last_sent(self, conversation_id: str, body: str):
        """Track last sent body for anti-repetition."""
        if conversation_id in self._conversations:
            self._conversations[conversation_id]["last_sent_body"] = body

    def get_last_sent(self, conversation_id: str) -> str:
        return self._conversations.get(conversation_id, {}).get("last_sent_body", "")
