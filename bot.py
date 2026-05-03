"""
Vera Bot — magicpin AI Challenge
Stateful FastAPI server exposing 5 endpoints for the Engagement Composer.

Usage:
    uvicorn bot:app --host 0.0.0.0 --port 8080

Environment variables:
    OPENAI_API_KEY   — GPT-4o (primary)
    GEMINI_API_KEY   — Gemini 2.0 Flash (fallback)
    GROQ_API_KEY     — Groq Llama 3.3 70B (fallback)
"""

from __future__ import annotations
import asyncio
import json
import time
from typing import Any, Optional
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from context_store import ContextStore
from llm_client import LLMClient
from composer import EngagementComposer
from conversation_manager import ConversationManager

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APP INITIALIZATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = FastAPI(title="Vera Bot", version="1.0.0")
store = ContextStore()
llm = LLMClient()
composer = EngagementComposer(llm)
conv_mgr = ConversationManager()

START_TIME = time.time()
sent_suppressions: set[str] = set()

# Semaphore to limit concurrent LLM calls (prevent burst rate-limit hits)
# Azure OpenAI 105k TPM limit: 5 concurrent calls = ~14k TPM per call, safe
compose_semaphore = asyncio.Semaphore(5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PYDANTIC MODELS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict


class TickBody(BaseModel):
    now: Optional[str] = None
    available_triggers: list[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    from_role: Optional[str] = "merchant"  # "merchant" or "customer"
    message: str
    timestamp: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 1: GET /v1/healthz
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/v1/healthz")
async def healthz():
    """Liveness check with context store counts."""
    counts = store.counts()
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "contexts_loaded": counts,
        "total_contexts": sum(counts.values()),
        "llm_provider": llm.primary_provider,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 2: GET /v1/metadata
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/v1/metadata")
async def metadata():
    """Team and model information."""
    return {
        "team_name": "Vera AI",
        "bot_name": "Vera",
        "model": llm.primary_provider,
        "approach": (
            "4-context composition framework with trigger-routed LLM prompting. "
            "26 trigger-specific prompt variants. Post-validation for anti-patterns. "
            "Multi-turn FSM with auto-reply detection, intent transitions, and graceful exits."
        ),
        "version": "1.0.0",
        "features": [
            "trigger_routing",
            "category_voice_matching",
            "hinglish_code_mix",
            "auto_reply_detection",
            "intent_transition",
            "hostile_exit",
            "suppression_tracking",
            "parallelized_tick",
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 3: POST /v1/context
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/v1/context")
async def push_context(body: ContextBody):
    """Ingest a context payload (category, merchant, customer, or trigger)."""
    accepted, reason, current_version = store.push(
        body.scope, body.context_id, body.version, body.payload
    )

    if accepted:
        return {
            "accepted": True,
            "ack_id": f"ack_{body.scope}_{body.context_id}_v{body.version}",
            "stored_at": datetime.utcnow().isoformat() + "Z",
            "scope": body.scope,
            "context_id": body.context_id,
            "version": body.version,
        }
    else:
        return JSONResponse(
            status_code=409 if reason == "stale_version" else 400,
            content={
                "accepted": False,
                "reason": reason,
                "current_version": current_version,
                "scope": body.scope,
                "context_id": body.context_id,
            }
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 4: POST /v1/tick
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/v1/tick")
async def tick(body: TickBody):
    """
    Process available triggers → compose proactive messages.
    Parallelizes LLM calls for latency budget compliance.
    """
    global sent_suppressions

    if not body.available_triggers:
        return {"actions": []}

    # 1. Resolve contexts for each trigger
    tasks = []
    for tid in body.available_triggers:
        trigger = store.get_trigger(tid)
        if not trigger:
            continue

        # Check suppression
        sup_key = trigger.get("suppression_key", "")
        if sup_key and sup_key in sent_suppressions:
            continue

        merchant_id = trigger.get("merchant_id", "")
        merchant = store.get_merchant(merchant_id)
        if not merchant:
            continue

        # Check if merchant is suppressed (opted out)
        if conv_mgr.is_merchant_suppressed(merchant_id):
            continue

        category_slug = merchant.get("category_slug", "")
        category = store.get_category(category_slug)
        if not category:
            continue

        customer_id = trigger.get("customer_id")
        customer = store.get_customer(customer_id) if customer_id else None

        tasks.append({
            "tid": tid,
            "trigger": trigger,
            "merchant": merchant,
            "merchant_id": merchant_id,
            "category": category,
            "customer": customer,
            "customer_id": customer_id,
        })

    if not tasks:
        return {"actions": []}

    # 2. Parallelize LLM calls with semaphore (max 5 to respect rate limits & latency)
    async def compose_with_semaphore(t):
        async with compose_semaphore:
            return await composer.compose(
                t["category"], t["merchant"], t["trigger"], t["customer"]
            )
    
    batch = tasks[:5]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[
                compose_with_semaphore(t)
                for t in batch
            ], return_exceptions=True),
            timeout=9.0  # 9s hard timeout — leave 1s margin
        )
    except asyncio.TimeoutError:
        return {"actions": []}

    # 3. Build action objects
    actions = []
    for task, result in zip(batch, results):
        if isinstance(result, Exception) or result is None:
            continue

        tid = task["tid"]
        trigger = task["trigger"]
        merchant = task["merchant"]
        merchant_id = task["merchant_id"]
        customer_id = task["customer_id"]
        identity = merchant.get("identity", {})

        # Determine template params
        owner = identity.get("owner_first_name", identity.get("name", ""))
        params = [owner]

        conv_id = f"conv_{merchant_id}_{tid}"

        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "trigger_id": tid,
            "send_as": result.get("send_as", "vera"),
            "template_name": f"vera_{trigger.get('kind', 'general')}_v1",
            "template_params": params,
            "body": result.get("body", ""),
            "cta": result.get("cta", "open_ended"),
            "suppression_key": result.get("suppression_key", trigger.get("suppression_key", "")),
            "rationale": result.get("rationale", ""),
        }

        if customer_id:
            action["customer_id"] = customer_id

        actions.append(action)

        # Track suppression
        sup_key = result.get("suppression_key", trigger.get("suppression_key", ""))
        if sup_key:
            sent_suppressions.add(sup_key)

        # Initialize conversation state
        conv = conv_mgr.get_or_create(conv_id, merchant_id, tid)
        conv_mgr.add_turn(conv_id, "vera", result.get("body", ""))
        conv_mgr.set_last_sent(conv_id, result.get("body", ""))

    return {"actions": actions}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 5: POST /v1/reply
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    """
    Process an incoming merchant/customer message in an active conversation.
    Classifies the message and routes to appropriate response logic.
    """
    conv_id = body.conversation_id
    merchant_id = body.merchant_id or ""
    trigger_id = body.trigger_id or ""

    # Get/create conversation state
    conv = conv_mgr.get_or_create(conv_id, merchant_id, trigger_id)

    # If conversation already ended, don't re-engage
    if conv_mgr.is_ended(conv_id):
        return {
            "action": "none",
            "rationale": "Conversation already ended."
        }

    # Classify BEFORE recording (to avoid false repetition detection)
    classification = conv_mgr.classify_reply(body.message, conv)

    # Record the incoming turn AFTER classification
    conv_mgr.add_turn(conv_id, body.from_role or "merchant", body.message)

    # ── AUTO-REPLY handling ──
    if classification == "AUTO_REPLY":
        conv["auto_reply_count"] = conv.get("auto_reply_count", 0) + 1
        count = conv["auto_reply_count"]

        if count == 1:
            reply_body = "Looks like an auto-reply! 😊 When you see this, just reply 'Yes' or 'Not now' — I'll take it from there."
            conv_mgr.add_turn(conv_id, "vera", reply_body)
            conv_mgr.set_last_sent(conv_id, reply_body)
            return {
                "action": "send",
                "body": reply_body,
                "cta": "binary_yes_no",
                "rationale": "Auto-reply detected (1st). One nudge for the owner.",
            }
        elif count == 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Auto-reply detected twice. Owner likely unavailable. Waiting 24h.",
            }
        else:
            conv_mgr.mark_ended(conv_id)
            return {
                "action": "end",
                "rationale": "Auto-reply detected 3+ times. Closing conversation to avoid spam.",
            }

    # ── HARD NO handling ──
    if classification == "HARD_NO":
        conv_mgr.mark_ended(conv_id)
        if merchant_id:
            conv_mgr.suppress_merchant(merchant_id)
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out. Conversation closed, merchant suppressed.",
        }

    # ── HOSTILE handling ──
    if classification == "HOSTILE":
        reply_body = "Apologies for the bother — won't message again. If anything changes, just text 'Hi Vera'. 🙏"
        conv_mgr.add_turn(conv_id, "vera", reply_body)
        conv_mgr.mark_ended(conv_id)
        if merchant_id:
            conv_mgr.suppress_merchant(merchant_id)
        return {
            "action": "send",
            "body": reply_body,
            "cta": "none",
            "rationale": "Hostile message detected. One-line apology + exit.",
        }

    # ── INTENT COMMIT ──
    if classification == "INTENT_COMMIT":
        conv["state"] = "ACTION_MODE"

        # Resolve contexts for LLM call
        merchant = store.get_merchant(merchant_id) if merchant_id else None
        trigger = store.get_trigger(trigger_id) if trigger_id else None
        category = store.get_category_for_merchant(merchant_id) if merchant_id else None

        try:
            result = await asyncio.wait_for(
                composer.compose_reply(conv, "action_mode", category, merchant, trigger),
                timeout=8.0
            )
            reply_body = result.get("body", "On it! Setting things up now. ✅")
        except Exception:
            reply_body = "On it! Setting things up — will share the details shortly. ✅"
            result = {"cta": "none", "rationale": "Intent commit — fallback confirmation."}

        conv_mgr.add_turn(conv_id, "vera", reply_body)
        conv_mgr.set_last_sent(conv_id, reply_body)
        return {
            "action": "send",
            "body": reply_body,
            "cta": result.get("cta", "none"),
            "rationale": result.get("rationale", "Merchant committed. Providing next steps."),
        }

    # ── ENGAGED (default: continue conversation) ──
    conv["state"] = "ENGAGED"
    merchant = store.get_merchant(merchant_id) if merchant_id else None
    trigger = store.get_trigger(trigger_id) if trigger_id else None
    category = store.get_category_for_merchant(merchant_id) if merchant_id else None

    try:
        result = await asyncio.wait_for(
            composer.compose_reply(conv, "continuation", category, merchant, trigger),
            timeout=8.0
        )
        reply_body = result.get("body", "")

        # Anti-repetition check
        if reply_body == conv_mgr.get_last_sent(conv_id):
            result = await asyncio.wait_for(
                composer.compose_reply(conv, "continuation_alt", category, merchant, trigger),
                timeout=4.0
            )
            reply_body = result.get("body", "Let me pull some fresh data on this — give me a moment.")

    except Exception:
        reply_body = "Good question — let me look into this and get back to you shortly."
        result = {"cta": "open_ended", "rationale": "Engagement reply — fallback."}

    conv_mgr.add_turn(conv_id, "vera", reply_body)
    conv_mgr.set_last_sent(conv_id, reply_body)
    return {
        "action": "send",
        "body": reply_body,
        "cta": result.get("cta", "open_ended"),
        "rationale": result.get("rationale", "Continued engaged conversation."),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STARTUP / SHUTDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.on_event("startup")
async def startup():
    print(f"[VERA] Bot starting - LLM: {llm.primary_provider}")
    print(f"   Endpoints: /v1/healthz, /v1/metadata, /v1/context, /v1/tick, /v1/reply")


@app.on_event("shutdown")
async def shutdown():
    await llm.close()
    print("[VERA] Bot shut down")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DIRECT RUN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
