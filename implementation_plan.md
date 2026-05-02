# Vera — Execution Plan (v2)

> Integrates the deep technical analysis with challenge documentation findings. Ready for approval → execution.

---

## Critical Corrections from Source Documents

Before diving in, three important corrections based on cross-referencing your analysis against the actual challenge docs:

> [!WARNING]
> **No 320-character body limit.** The challenge brief §5.2 explicitly states: *"Body length — no hard cap; keep it concise and context-appropriate for readability."* The case study examples range from 150-450 chars. Design for **concise but not truncated** — 200-400 chars is the sweet spot.

> [!WARNING]
> **Latency budgets differ across docs.** The testing brief §5 says 30s per-call timeout, but the api-call-examples summary table says 10s for `/v1/tick` and `/v1/reply`. **Design for 10s** to be safe — this means each LLM call must complete in ~3-5s, and parallelization within a tick is mandatory.

> [!IMPORTANT]
> **URLs are PENALIZED.** The api-call-examples §F.4 states: *"Meta would reject. Penalty: -3 per URL."* Your analysis mentions URLs are "allowed when they add clear value" (from challenge brief §5.4), but the testing examples show a hard penalty. **Do NOT include URLs in any message body.**

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Vera Bot Server (FastAPI)                 │
├─────────────┬──────────────┬───────────────┬─────────────────────┤
│ Context     │ Trigger      │ Composer      │ Conversation        │
│ Store       │ Router       │ Engine        │ Manager             │
│             │              │               │                     │
│ • Versioned │ • 20+ prompt │ • LLM call    │ • FSM per conv_id   │
│ • Idempotent│   variants   │ • Structured  │ • Auto-reply detect │
│ • Cross-ref │ • Urgency    │   JSON output │ • Intent transition │
│   helpers   │   priority   │ • Post-valid  │ • Graceful exits    │
│ • Atomic    │ • Suppression│ • Anti-halluc │ • Anti-repetition   │
│   replace   │   check      │ • Voice match │ • Turn tracking     │
└──────┬──────┴──────┬───────┴──────┬────────┴────────┬────────────┘
       │             │              │                  │
    /v1/context   /v1/tick      /v1/reply         /v1/healthz
                                                  /v1/metadata
```

---

## LLM Strategy — Three-Tier Approach

Based on your research, here's the recommended LLM stack:

| Tier | Provider | Model | Cost | Best For |
|---|---|---|---|---|
| **Primary** | Google AI Studio | Gemini 2.0 Flash | Free (1,500 RPD, 1M TPM) | Highest free volume; fast |
| **Secondary** | Groq Cloud | Llama 3.3 70B | Free (30 RPM) | Blazing-fast inference; good Hinglish |
| **Premium** | Azure OpenAI | GPT-4o mini | Credits required | Best structured output; enterprise-grade |

### Recommended Default: **Gemini 2.0 Flash**
- **1,500 requests/day free** — more than enough for development + the 60-min test window
- Fast inference (<3s typical) — fits within the 10s tick budget
- Strong multilingual/Hinglish support
- Structured JSON output via `response_mime_type: "application/json"`

### Fallback chain:
```
Gemini 2.0 Flash → Groq Llama 3.3 70B → GPT-4o mini (if Azure credits available)
```

> [!IMPORTANT]
> **Which provider do you have API keys for?** I can configure any of these. If you have none, Google AI Studio gives free keys at https://aistudio.google.com/apikey — quickest path to start.

---

## Phase 0 — Setup & Dataset Expansion (~30 min)

- [ ] Set up Python environment
- [ ] Run `generate_dataset.py` → expand to 50 merchants, 200 customers, 100 triggers, 30 test pairs
- [ ] Configure LLM API key
- [ ] Verify `judge_simulator.py` runs against stub

### Dependencies
```
fastapi
uvicorn
pydantic
httpx          # for async LLM calls
```

---

## Phase 1 — Context Store & Skeleton Endpoints (~1 hour)

### 1.1 Context Store (`context_store.py`)

```python
class ContextStore:
    """In-memory versioned context store with cross-reference helpers."""
    
    # Storage: {(scope, context_id): {"version": int, "payload": dict}}
    
    def push(scope, context_id, version, payload) -> (bool, str)
        # Idempotent: reject if existing version >= incoming version (409)
        # Atomic: replace entire payload on version bump
    
    def get(scope, context_id) -> dict | None
    def get_category_for_merchant(merchant_id) -> dict | None
        # Cross-ref: merchant.category_slug → category payload
    def get_customer(customer_id) -> dict | None
    def get_trigger(trigger_id) -> dict | None
    def counts() -> dict  # {"category": 5, "merchant": 50, ...}
```

### 1.2 Five Endpoints (`bot.py`)

| Endpoint | Logic |
|---|---|
| `GET /v1/healthz` | Return `{status, uptime_seconds, contexts_loaded}` from store counts |
| `GET /v1/metadata` | Static team info + model selection |
| `POST /v1/context` | Validate → `store.push()` → 200/409 response |
| `POST /v1/tick` | *Stub: return `{"actions": []}`* — fill in Phase 2 |
| `POST /v1/reply` | *Stub: return `{"action": "send", "body": "..."}`* — fill in Phase 3 |

### Verification
```bash
python judge_simulator.py  # warmup scenario — all context pushes pass
```

---

## Phase 2 — Composer Engine (CORE — ~2.5 hours)

### 2.1 Trigger Router (`trigger_router.py`)

Maps `trigger.kind` → specialized prompt variant + composition strategy:

| Trigger Kind | Prompt Focus | Key Compulsion Levers |
|---|---|---|
| `research_digest` | Source citation, clinical relevance | Curiosity, reciprocity, specificity |
| `regulation_change` | Deadline, specific changes, audit steps | Loss aversion, urgency |
| `recall_due` | Slot offering, language match | Effort externalization, binary CTA |
| `perf_dip` / `perf_spike` | Numbers comparison, peer context | Social proof, loss aversion |
| `milestone_reached` | Celebration, momentum | Social proof, next milestone |
| `ipl_match_today` | Contrarian insight, existing offer leverage | Loss aversion, specificity |
| `review_theme_emerged` | Actual review quote, corrective action | Reciprocity, specificity |
| `curious_ask_due` | Low-stakes question, reciprocity offer | Asking-the-merchant |
| `customer_lapsed_hard/soft` | No-shame, new offering | Effort externalization, binary CTA |
| `chronic_refill_due` | Molecule names, savings, delivery | Specificity, effort externalization |
| `supply_alert` | Batch numbers, affected count | Urgency, specificity |
| `active_planning_intent` | Complete drafted artifact | Effort externalization |
| `renewal_due` | Value recap, deadline urgency | Loss aversion |
| `competitor_opened` | Voyeur curiosity, differentiation | Curiosity, social proof |
| `festival_upcoming` | Category-relevant seasonal tie-in | Timeliness |
| `dormant_with_vera` | Light touch, value-first | Curiosity, reciprocity |
| `winback_eligible` | Perf dip post-expiry | Loss aversion |
| `gbp_unverified` | Uplift data, step-by-step | Specificity |
| `cde_opportunity` | Credits, fee, date | Specificity, timeliness |
| `trial_followup` | Next session slot | Effort externalization |
| `category_seasonal` | Demand shift data | Specificity, loss aversion |
| `wedding_package_followup` | Days-to-wedding countdown | Urgency, effort externalization |

### 2.2 Master Composer (`composer.py`)

```python
class EngagementComposer:
    async def compose(category, merchant, trigger, customer=None) -> dict:
        """
        1. Build system prompt:
           - Voice rules from category.voice (tone, taboos, vocab)
           - Anti-patterns list (§11 of challenge brief)
           - Compulsion levers guidance
           - "Available data" enumeration (anti-hallucination)
           - Language preference rules
        
        2. Build user prompt via trigger_router:
           - Trigger-specific framing template
           - All 4 contexts as structured data
           - Output schema requirement (JSON)
        
        3. Call LLM with structured output enforcement:
           - Gemini: response_mime_type="application/json" + response_schema
           - Azure: response_format={"type":"json_schema", "strict":true}
           - Groq: response_format={"type":"json_object"}
        
        4. Parse JSON: {body, cta, send_as, suppression_key, rationale}
        
        5. Post-validation:
           - Body contains no URLs
           - Body doesn't contain taboo vocabulary
           - CTA is single and at the end
           - No fabricated data (cross-check numbers against contexts)
           - Language matches merchant.identity.languages
           - Not identical to any previous message in this conversation
        
        6. Re-prompt once if validation fails
        
        Returns: validated ComposedMessage dict
        """
```

### 2.3 System Prompt Design

The system prompt is **per-category** (voice rules change by vertical) with **per-trigger injection** (framing changes by event type):

```
SYSTEM = f"""
You are Vera, a merchant growth assistant on WhatsApp for {category.display_name}.

VOICE RULES for {category.slug}:
- Tone: {category.voice.tone}
- Register: {category.voice.register}
- Allowed vocabulary: {category.voice.vocab_allowed}
- NEVER use: {category.voice.vocab_taboo}
- Salutation: {category.voice.salutation_examples}

HARD RULES:
1. Single primary CTA — at the END of the message. Binary (YES/STOP) for actions.
2. NO URLs in the message body.
3. NO fabrication — only cite data from the contexts below.
4. NO generic offers — use "Service @ ₹Price" not "X% off".
5. NO long preambles — jump straight to the value.
6. NO re-introduction after the first message.
7. If merchant languages include "hi", use natural Hindi-English code-mix.
8. Anchor on a verifiable fact (number, date, headline, source citation).
9. Keep body concise: 200-400 characters, context-appropriate.

COMPULSION LEVERS (use 2-3 per message):
- Specificity: concrete numbers, dates, sources
- Loss aversion: "you're missing X" / "before window closes"
- Social proof: "3 peers in your locality did Y"  
- Effort externalization: "I've drafted X — just say go"
- Curiosity: "want to see who?"
- Reciprocity: "I noticed Y, thought you'd want to know"
- Asking-the-merchant: "what's your most-asked service?"
- Single binary commitment: Reply YES / STOP

OUTPUT FORMAT (strict JSON):
{{
  "body": "...",
  "cta": "binary_yes_no" | "open_ended" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "...",
  "rationale": "1-2 sentence explanation of why this message, what it achieves"
}}
"""
```

### 2.4 Hinglish Code-Mix Strategy

Per your research, the approach for Hindi-English code-mixing:

1. **Detection**: Check `merchant.identity.languages` — if includes `"hi"`, enable Hinglish
2. **Prompt instruction**: *"Use natural Hindi-English code-mix. Hindi for conversational warmth (aapka, chalega, shukriya), English for technical/business terms (CTR, views, profile). Don't force Hindi — let it flow naturally."*
3. **Examples in prompt**: Include 2-3 examples from the case studies showing ideal code-mix level
4. **Model selection**: Gemini 2.0 Flash and GPT-4o both handle Hinglish well; Groq's Llama 3.3 70B is also strong here

### 2.5 `/v1/tick` Implementation

```python
async def tick(body: TickBody):
    actions = []
    
    # 1. Resolve all trigger contexts
    trigger_tasks = []
    for tid in body.available_triggers:
        trigger = store.get("trigger", tid)
        if not trigger: continue
        merchant = store.get("merchant", trigger["merchant_id"])
        if not merchant: continue
        category = store.get("category", merchant["category_slug"])
        customer = store.get("customer", trigger.get("customer_id")) if trigger.get("customer_id") else None
        
        # 2. Suppression check
        if trigger.get("suppression_key") in sent_suppressions:
            continue
        
        trigger_tasks.append((tid, category, merchant, trigger, customer))
    
    # 3. Parallelize LLM calls (critical for 10s budget)
    #    Limit to 5 concurrent to avoid rate limits
    results = await asyncio.gather(*[
        composer.compose(cat, merch, trig, cust)
        for tid, cat, merch, trig, cust in trigger_tasks[:5]
    ])
    
    # 4. Build action objects
    for (tid, cat, merch, trig, cust), result in zip(trigger_tasks, results):
        if result:
            actions.append({
                "conversation_id": f"conv_{merch['merchant_id']}_{tid}",
                "merchant_id": merch["merchant_id"],
                "customer_id": cust["customer_id"] if cust else None,
                "send_as": result["send_as"],
                "trigger_id": tid,
                "template_name": f"vera_{trig['kind']}_v1",
                "template_params": [merch["identity"]["name"], "...", "..."],
                "body": result["body"],
                "cta": result["cta"],
                "suppression_key": result["suppression_key"],
                "rationale": result["rationale"]
            })
            sent_suppressions.add(result["suppression_key"])
    
    return {"actions": actions}
```

> [!IMPORTANT]
> **Parallelization is mandatory.** With a 10s budget and 3-5s per LLM call, sequential processing of 5 triggers would take 15-25s. `asyncio.gather` with async HTTP calls solves this.

---

## Phase 3 — Conversation Handler (~1.5 hours)

### 3.1 Conversation State Machine (`conversation_manager.py`)

```
                        ┌──────────────────┐
                        │    INITIATED     │
                        │ (bot sent first  │
                        │  proactive msg)  │
                        └────────┬─────────┘
                                 │ merchant replies
                    ┌────────────┼────────────────┐
                    │            │                 │
              ┌─────▼──────┐ ┌──▼──────────┐ ┌───▼──────────┐
              │ AUTO_REPLY  │ │  ENGAGED    │ │ HARD_NO /    │
              │ DETECTED    │ │             │ │ HOSTILE      │
              └──────┬──────┘ └──────┬──────┘ └──────┬───────┘
                     │               │                │
              count: 1→wait    intent detected   ┌───▼───┐
              count: 2→wait    │                 │ ENDED │
              count: 3→end     ▼                 └───────┘
                          ┌────────────┐
                          │ ACTION_MODE│
                          │ (execute,  │
                          │  confirm)  │
                          └─────┬──────┘
                                │ goal achieved / merchant done
                                ▼
                          ┌────────────┐
                          │   ENDED    │
                          └────────────┘
```

### 3.2 Reply Classification (`classify_reply()`)

```python
def classify_reply(message: str, conversation_state: dict) -> str:
    """
    Classify incoming merchant message into response categories.
    Uses keyword detection + LLM fallback for ambiguous cases.
    """
    msg_lower = message.lower().strip()
    
    # 1. AUTO-REPLY detection (keyword + repetition)
    auto_reply_signals = [
        "thank you for contacting", "our team will respond",
        "automated", "auto reply", "we'll get back",
        "ham jaldi se", "hamari team"
    ]
    if any(sig in msg_lower for sig in auto_reply_signals):
        return "AUTO_REPLY"
    
    # Check if same message sent before (verbatim repetition)
    if message in [t["msg"] for t in conversation_state.get("turns", [])]:
        return "AUTO_REPLY"
    
    # 2. HARD NO / OPT-OUT
    hard_no_signals = ["stop", "not interested", "unsubscribe", 
                       "don't message", "band karo", "nahi chahiye"]
    if any(sig in msg_lower for sig in hard_no_signals):
        return "HARD_NO"
    
    # 3. HOSTILE
    hostile_signals = ["useless", "spam", "bothering", "stupid",
                       "bakwas", "time waste"]
    if any(sig in msg_lower for sig in hostile_signals):
        return "HOSTILE"
    
    # 4. EXPLICIT INTENT (ready to act)
    intent_signals = ["let's do it", "go ahead", "yes", "haan",
                      "ok do it", "proceed", "confirm", "chalao",
                      "kar do", "shuru karo"]
    if any(sig in msg_lower for sig in intent_signals):
        return "INTENT_COMMIT"
    
    # 5. Default: ENGAGED (question, info, or continuation)
    return "ENGAGED"
```

### 3.3 `/v1/reply` Implementation

```python
async def reply(body: ReplyBody):
    # 1. Load/create conversation state
    conv = conversations.setdefault(body.conversation_id, {
        "turns": [], "state": "INITIATED", 
        "auto_reply_count": 0, "last_sent_body": ""
    })
    conv["turns"].append({"from": body.from_role, "msg": body.message})
    
    # 2. Classify merchant message
    classification = classify_reply(body.message, conv)
    
    # 3. Route by classification
    match classification:
        case "AUTO_REPLY":
            conv["auto_reply_count"] += 1
            if conv["auto_reply_count"] == 1:
                return {"action": "send",
                        "body": "Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes'.",
                        "cta": "binary_yes_no",
                        "rationale": "Detected auto-reply; one explicit prompt for the owner."}
            elif conv["auto_reply_count"] == 2:
                return {"action": "wait", "wait_seconds": 86400,
                        "rationale": "Same auto-reply twice → owner not at phone. Wait 24h."}
            else:
                return {"action": "end",
                        "rationale": "Auto-reply 3x+, no real reply. Closing conversation."}
        
        case "HARD_NO":
            return {"action": "end",
                    "rationale": "Merchant explicitly opted out. Suppressing future triggers."}
        
        case "HOSTILE":
            return {"action": "send",
                    "body": "Apologies — I won't message again. If anything changes, restart with 'Hi Vera'. 🙏",
                    "cta": "none",
                    "rationale": "One-line acknowledgment + opt-out path; closing after this."}
        
        case "INTENT_COMMIT":
            conv["state"] = "ACTION_MODE"
            # LLM call with action-mode prompt:
            # "Merchant committed. Provide concrete next steps, not more questions."
            response = await composer.compose_reply(conv, "action_mode")
            return {"action": "send", "body": response["body"],
                    "cta": response["cta"], "rationale": response["rationale"]}
        
        case "ENGAGED":
            conv["state"] = "ENGAGED"
            # LLM call with full conversation context
            response = await composer.compose_reply(conv, "continuation")
            # Anti-repetition check
            if response["body"] == conv["last_sent_body"]:
                response = await composer.compose_reply(conv, "continuation_alt")
            conv["last_sent_body"] = response["body"]
            return {"action": "send", "body": response["body"],
                    "cta": response["cta"], "rationale": response["rationale"]}
```

---

## Phase 4 — Submission Generation (~45 min)

1. **Expand dataset**: `python generate_dataset.py --seed-dir ./dataset --out ./dataset/expanded`
2. **Load 30 test pairs** from `expanded/test_pairs.json`
3. **Compose each** using the full pipeline (composer + trigger router)
4. **Write** `submission.jsonl` — one JSON line per test pair
5. **Quality audit**: Manual review against the [10 case studies](file:///c:/Users/hp/Downloads/magicpin-ai-challenge/examples/case-studies.md) scoring criteria

---

## Phase 5 — Testing & Polish (~1 hour)

### 5.1 Judge Simulator Runs

```bash
# Terminal 1: Start bot
uvicorn bot:app --host 0.0.0.0 --port 8080

# Terminal 2: Run judge
python judge_simulator.py
```

Scenarios to pass:
| Scenario | Target | Key Metric |
|---|---|---|
| `warmup` | All 255 contexts accepted | 100% pass |
| `phase2_short` | Composition quality | 40+/50 per message |
| `auto_reply_hell` | Exit by turn 3-4 | `action: end` |
| `intent_transition` | Switch to action mode | No qualifying questions |
| `hostile` | Graceful exit | `action: end` or apology |
| `full_evaluation` | All triggers scored | Avg 40+/50 |

### 5.2 Iteration Targets
- **Specificity**: Every message has ≥2 verifiable facts from contexts
- **Category fit**: Voice audit across all 5 categories
- **Merchant fit**: Owner first name used, language preference honored
- **Trigger relevance**: "Why now" is explicit in every message
- **Engagement**: CTA always last sentence, 2-3 compulsion levers per message

### 5.3 Deliverables
- [ ] `bot.py` — main FastAPI server
- [ ] `composer.py` — LLM composition engine
- [ ] `trigger_router.py` — prompt variant dispatch
- [ ] `context_store.py` — versioned context storage
- [ ] `conversation_manager.py` — multi-turn FSM
- [ ] `conversation_handlers.py` — multi-turn reply handler (submission artifact)
- [ ] `prompts/system_prompt.py` — master system prompt builder
- [ ] `prompts/trigger_prompts.py` — per-trigger prompt variants
- [ ] `submission.jsonl` — 30 test pair outputs
- [ ] `README.md` — approach documentation
- [ ] `requirements.txt` — dependencies

---

## Structured Output Enforcement Strategy

Per your research on constrained decoding, here's the provider-specific approach:

```python
# Gemini (primary)
response = model.generate_content(
    prompt,
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": ComposedMessageSchema,
        "temperature": 0.1
    }
)

# Azure OpenAI (premium)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "composed_message", "strict": True, "schema": schema}
    }
)

# Groq (secondary)
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    response_format={"type": "json_object"},
    temperature=0.1
)
```

---

## Open Questions (Need Your Input)

> [!IMPORTANT]
> **1. API Key** — Which LLM provider API key do you have ready? If none, Google AI Studio (Gemini) is the fastest free option. Do you have Azure credits from a startup program?

> [!IMPORTANT]
> **2. Team Name** — Needed for `/v1/metadata` endpoint and `README.md`

> [!NOTE]
> **3. Deployment** — For now I'll build for `localhost:8080`. When ready to submit, we can use ngrok or deploy to Render/Railway. Any preference?

---

## Estimated Timeline

| Phase | Time | Description |
|---|---|---|
| Phase 0 | 30 min | Setup, dataset expansion, LLM config |
| Phase 1 | 1 hour | Context store + skeleton endpoints |
| Phase 2 | 2.5 hours | **Composer engine (core differentiator)** |
| Phase 3 | 1.5 hours | Conversation handler + multi-turn FSM |
| Phase 4 | 45 min | Submission generation + quality audit |
| Phase 5 | 1 hour | Testing with judge_simulator + polish |
| **Total** | **~7 hours** | |

---

## Verification Plan

### Automated
1. `judge_simulator.py` — all 6 scenarios pass, avg score 40+/50
2. Context warmup — all 255 contexts loaded and acknowledged
3. Latency check — every `/v1/tick` and `/v1/reply` completes within 10s

### Manual
1. Review all 30 `submission.jsonl` entries against case study quality bar
2. Spot-check Hinglish code-mix quality for `hi`-speaking merchants
3. Verify zero fabricated data across all compositions
4. Confirm voice consistency per category (dentist ≠ salon ≠ pharmacy)
