# Vera — magicpin AI Challenge Submission

## Approach

Vera is a stateful AI merchant growth assistant built as a FastAPI server. It composes high-quality WhatsApp messages for merchants using a **4-context composition framework** (Category, Merchant, Trigger, Customer) and evaluates each message against 5 quality dimensions.

### Architecture

```
Context Store (versioned, in-memory)
        |
Trigger Router (26 trigger-specific prompt variants)
        |
Composer Engine (LLM + structured output + post-validation)
        |
Conversation Manager (multi-turn FSM)
        |
5 FastAPI Endpoints
```

### Key Design Decisions

1. **Trigger-Routed Prompts**: Instead of a single monolithic prompt, each `trigger.kind` gets its own prompt variant that injects trigger-specific framing rules. A `perf_dip` prompt focuses on loss aversion and numbers comparison, while a `recall_due` prompt focuses on customer relationship states and slot offerings.

2. **Category-Aware Voice**: The system prompt is built dynamically per category using voice rules (tone, vocab, taboos) from `CategoryContext`. A dentist gets peer-clinical tone; a salon gets warm-practical.

3. **Parallelized Tick Processing**: LLM calls within a tick are parallelized via `asyncio.gather` to fit within the 10s latency budget, with a 9s hard timeout.

4. **Post-Validation**: Every LLM output is validated for anti-patterns (URLs, taboo words, fabricated data, wrong `send_as`), with automatic correction and one re-prompt on failure.

5. **Conversation FSM**: Multi-turn conversations follow a state machine (INITIATED -> ENGAGED -> ACTION_MODE -> ENDED) with auto-reply detection (keyword + verbatim repetition), intent transition, and graceful exits for hostile/opt-out messages.

6. **Hindi-English Code-Mix**: When merchant languages include "hi", the system prompt instructs natural Hinglish code-mixing with Hindi for warmth and English for business terms.

### LLM Strategy

- **Primary**: GPT-4o (OpenAI) — best instruction-following and structured output
- **Fallback chain**: Gemini 2.0 Flash -> Groq Llama 3.3 70B -> DeepSeek
- **Output**: JSON mode with structured schema enforcement
- **Temperature**: 0.1 for deterministic composition

### What Additional Context Would Help

1. **Real merchant engagement data** — actual response rates per trigger type to weight urgency scoring
2. **A/B test results** — which compulsion levers (loss aversion vs. curiosity vs. social proof) actually drive higher reply rates per category
3. **Language model** — a fine-tuned model on actual Vera conversation logs would dramatically improve voice match
4. **Seasonal calendars** — real-time festival/event calendars per city for time-sensitive triggers

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key (at least one required)
export OPENAI_API_KEY="sk-..."
# OR
export GEMINI_API_KEY="..."

# Expand dataset
cd dataset && python generate_dataset.py --out ./expanded && cd ..

# Start the bot
python bot.py
# OR
uvicorn bot:app --host 0.0.0.0 --port 8080

# Run judge simulator (in another terminal)
python judge_simulator.py

# Generate submission.jsonl
python generate_submission.py
```

## Files

| File | Purpose |
|---|---|
| `bot.py` | FastAPI server with 5 endpoints |
| `composer.py` | LLM-based message composition engine |
| `context_store.py` | Versioned in-memory context storage |
| `conversation_manager.py` | Multi-turn FSM with reply classification |
| `conversation_handlers.py` | High-level conversation handler (submission artifact) |
| `llm_client.py` | Multi-provider LLM client with fallback |
| `prompts/system_prompt.py` | Category-aware system prompt builder |
| `prompts/trigger_prompts.py` | 26 trigger-specific prompt variants |
| `generate_submission.py` | Generates submission.jsonl from test pairs |
| `submission.jsonl` | 30 canonical test pair compositions |

## Tradeoffs

- **In-memory state**: Chose simplicity over durability. Fine for the challenge window; production would use Redis/PostgreSQL.
- **Sequential fallback**: LLM providers are tried in order, not raced. Saves cost but adds latency on primary failure.
- **Keyword-based classification**: Reply classification uses keyword matching, not LLM. Faster and more predictable, but misses nuanced intent.
- **5-trigger batch limit**: Limits parallelized tick to 5 triggers to stay within rate limits and latency budget.
