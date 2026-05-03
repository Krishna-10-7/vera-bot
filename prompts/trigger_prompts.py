"""
Trigger-specific prompt variants — one framing template per trigger.kind.
Each function returns the user-prompt portion that gets sent alongside the system prompt.
"""

from __future__ import annotations
import json


def _safe_pct(val) -> str:
    """Safely format a value as percentage."""
    if isinstance(val, (int, float)):
        return f"{val:+.0%}"
    return str(val)


def _fmt_merchant(m: dict) -> str:
    """Format merchant context for prompt injection."""
    identity = m.get("identity", {})
    perf = m.get("performance", {})
    delta = perf.get("delta_7d", {})
    offers = [o["title"] for o in m.get("offers", []) if o.get("status") == "active"]
    signals = m.get("signals", [])
    cust_agg = m.get("customer_aggregate", {})
    conv_hist = m.get("conversation_history", [])
    reviews = m.get("review_themes", [])

    hist_str = ""
    if conv_hist:
        recent = conv_hist[-3:]
        hist_str = "\n".join([f"  [{t['from']}] {t['body'][:120]}" for t in recent])

    review_str = ""
    if reviews:
        review_str = ", ".join([f"{r['theme']}({r['sentiment']}, {r.get('occurrences_30d', '?')}x)" for r in reviews])

    return f"""MERCHANT:
- Name: {identity.get('name', '?')}
- Owner: {identity.get('owner_first_name', '?')}
- City/Locality: {identity.get('city', '?')}, {identity.get('locality', '?')}
- Languages: {identity.get('languages', ['en'])}
- Verified: {identity.get('verified', False)}
- Subscription: {m.get('subscription', {}).get('status', '?')} ({m.get('subscription', {}).get('plan', '?')}), {m.get('subscription', {}).get('days_remaining', '?')} days left
- Performance (30d): views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, CTR={perf.get('ctr', '?')}, directions={perf.get('directions', '?')}
- 7d delta: views {_safe_pct(delta.get('views_pct', '?'))}, calls {_safe_pct(delta.get('calls_pct', '?'))}
- Active offers: {offers if offers else 'NONE'}
- Customer aggregate: {json.dumps(cust_agg) if cust_agg else 'N/A'}
- Signals: {signals}
- Review themes: {review_str if review_str else 'none'}
- Recent conversation:
{hist_str if hist_str else '  (no prior conversation)'}

CRITICAL RULES FOR JUDGE EVALUATION (MUST FOLLOW):
1. DO NOT FABRICATE DATA: Never invent numbers, percentages, or active members. Only cite exact metrics provided above or in the trigger payload.
2. EXPLICIT CTA: End the message with a very clear, low-friction binary call-to-action (e.g., "Reply YES to activate", "Reply 1 to draft").
3. PERSONALIZATION: You MUST use the Owner Name, Merchant Name, and Locality in the first sentence."""


def _fmt_customer(c: dict) -> str:
    """Format customer context for prompt injection."""
    if not c:
        return "CUSTOMER: None (merchant-facing message)"
    identity = c.get("identity", {})
    rel = c.get("relationship", {})
    prefs = c.get("preferences", {})
    consent = c.get("consent", {})
    return f"""CUSTOMER:
- Name: {identity.get('name', '?')}
- Language: {identity.get('language_pref', 'en')}
- Age band: {identity.get('age_band', '?')}
- Relationship: {rel.get('visits_total', 0)} visits, first={rel.get('first_visit', '?')}, last={rel.get('last_visit', '?')}
- Services: {rel.get('services_received', [])}
- State: {c.get('state', '?')}
- Preferences: {json.dumps(prefs)}
- Consent scope: {consent.get('scope', [])}"""


def _fmt_digest(category: dict, item_id: str = None) -> str:
    """Extract relevant digest item from category."""
    digests = category.get("digest", [])
    if item_id:
        for d in digests:
            if d.get("id") == item_id:
                return f"""DIGEST ITEM:
- Title: {d.get('title', '?')}
- Source: {d.get('source', '?')}
- Summary: {d.get('summary', '?')}
- Trial N: {d.get('trial_n', 'N/A')}
- Patient segment: {d.get('patient_segment', 'N/A')}
- Actionable: {d.get('actionable', 'N/A')}"""
    if digests:
        d = digests[0]
        return f"DIGEST (latest): {d.get('title', '?')} — {d.get('source', '?')}"
    return "DIGEST: none available"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRIGGER-SPECIFIC PROMPT BUILDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def prompt_research_digest(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    digest_id = payload.get("top_item_id")
    return f"""TRIGGER: Research digest release — a new research/clinical finding relevant to this merchant's category just dropped.

{_fmt_digest(category, digest_id)}
{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Leads with the research finding — cite the source, trial size, and key number
2. Connects it to THIS merchant's patient/customer base (use their customer_aggregate data)
3. Offers to do something useful with it (draft a patient-ed WhatsApp, pull the abstract)
4. Peer/clinical tone — no hype, source citation at the end"""


def prompt_regulation_change(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    digest_id = payload.get("top_item_id")
    deadline = payload.get("deadline_iso", "upcoming")
    return f"""TRIGGER: Regulation/compliance change — a new rule affects this merchant's category. Deadline: {deadline}.

{_fmt_digest(category, digest_id)}
{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Leads with the regulation change and deadline
2. States exactly what the merchant needs to do
3. Offers to help audit/prepare
4. Urgency appropriate — this is compliance, not marketing"""


def prompt_recall_due(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    slots = payload.get("available_slots", [])
    slot1 = slots[0].get("label", "Slot 1") if len(slots) > 0 else "Slot 1"
    slot2 = slots[1].get("label", "Slot 2") if len(slots) > 1 else "Slot 2"
    service = payload.get("service_due", "checkup")
    last_date = payload.get("last_service_date", "?")
    due_date = payload.get("due_date", "?")
    days_until_expiry = payload.get("days_until_expiry", "?")

    # Get merchant offer for this service
    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]

    return f"""TRIGGER: Recall reminder — a customer's {service} is due. This is a CUSTOMER-FACING message sent from the merchant's WhatsApp number.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

TRIGGER DATA:
- Service due: {service}
- Last service: {last_date}
- Due date: {due_date}
- Days until expiry: {days_until_expiry}
- Available slots: {slot1} and {slot2}
- Active merchant offers: {active_offers}

ENGAGEMENT STRATEGY — MANDATORY:
1. URGENCY: Use specific deadline language ("expires {due_date}", "only {days_until_expiry} days left")
2. BINARY CTA: End with EXACTLY TWO options: "Reply 1 for {slot1} or Reply 2 for {slot2}"
3. SOCIAL PROOF: If available, mention "Preferred by X% of your peer customers"
4. NO MULTI-CHOICE: Never offer 3+ options — exactly 2 slot choices maximum
5. EFFORT EXTERNAL: Frame as "Quick 2-min booking" not "Schedule appointment"

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. Addresses the customer by name
2. References the specific due date and urgency (days remaining)
3. Mentions slots as binary choice with urgency cues ("only 1 spot left at {slot1}")
4. Includes actual price from merchant's active offers if available
5. Match the customer's language_pref
6. Warm but clinical — no overclaims, no medical guarantees
7. Character count: 200-350 chars max"""


def prompt_perf_dip(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", 0)
    window = payload.get("window", "7d")
    vs_baseline = payload.get("vs_baseline", "?")
    peer_median = payload.get("peer_median_ctr", "?")
    suggested_action = payload.get("suggested_action", "Try a fresh promo offer")

    return f"""TRIGGER: Performance dip alert — merchant's key metric has declined. This is a MERCHANT-FACING message.

{_fmt_merchant(merchant)}

TRIGGER DATA:
- Metric: {metric}
- Delta: {delta} in {window}
- vs baseline: {vs_baseline}
- Peer median {metric}: {peer_median}
- Suggested action: {suggested_action}

ENGAGEMENT STRATEGY — MANDATORY:
1. SPECIFICITY: Lead with exact numbers ("views down {delta}% to {vs_baseline}", NOT "significantly down")
2. CONTEXT: Explain WHY now ("post-holiday dip is normal", "weekend pattern")
3. LOSS AVERSION: Highlight revenue impact ("missing X views = approx Y lost bookings")
4. EFFORT EXTERNAL: "I'll draft 3 posts for you (takes 5 min), you choose to post or skip"
5. BINARY CTA: "Reply YES and I'll send drafts in 3 minutes" OR "Reply 1 to activate, 2 to skip"
6. NO VAGUE SOLUTIONS: Never say "try a fresh promo" — say "Post a specific offer like 'Service @ ₹Price'"

COMPOSE a merchant-facing message (send_as=vera) that:
1. Starts with: Owner Name, Merchant Name, Locality
2. States exact delta with context (not alarming, matter-of-fact)
3. Compares to peer median to normalize (e.g., "you're at 3.2% CTR, peer avg is 3.5%")
4. Proposes ONE specific action (not generic advice)
5. Ends with binary YES/NO CTA with time estimate ("Reply YES, 5-min fix")
6. Character count: 250-350 chars max
7. No URLs, no generic language"""


def prompt_perf_spike(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", 0)
    driver = payload.get("likely_driver", "")

    return f"""TRIGGER: Performance spike — merchant's {metric} up {_safe_pct(delta)} over 7d. Likely driver: {driver}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Celebrate the spike with exact numbers
2. Attribute it if driver is known
3. Suggest how to capitalize on the momentum
4. Keep it brief and encouraging"""


def prompt_milestone(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "reviews")
    value = payload.get("value_now", 0)
    milestone = payload.get("milestone_value", 0)

    return f"""TRIGGER: Milestone approaching — merchant is at {value} {metric}, close to {milestone}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Highlight how close they are to the milestone
2. Social proof — what reaching this milestone means vs peers
3. Offer to help push past it (e.g., ask recent happy customers for a review)
4. Celebratory but practical tone"""


def prompt_ipl_match(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    match = payload.get("match", "?")
    venue = payload.get("venue", "?")
    is_weeknight = payload.get("is_weeknight", True)
    match_time = payload.get("match_time_iso", "?")

    # Get relevant digest about IPL impact
    ipl_digest = ""
    for d in category.get("digest", []):
        if "ipl" in d.get("title", "").lower() or "match" in d.get("title", "").lower():
            ipl_digest = f"DATA INSIGHT: {d['title']} — {d.get('summary', '')}"
            break

    return f"""TRIGGER: IPL match today — {match} at {venue}, {match_time}. Weekend match: {not is_weeknight}.

{_fmt_merchant(merchant)}
{ipl_digest}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Reference the specific match and venue
2. Use DATA from digest to give contrarian advice (Saturday matches = fewer dine-in covers; weeknight = more)
3. Leverage the merchant's EXISTING active offers — don't invent new ones
4. Suggest a specific deliverable (banner, story, post) with time estimate
5. Operator-to-operator voice"""


def prompt_review_theme(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    theme = payload.get("theme", "?")
    count = payload.get("occurrences_30d", 0)
    quote = payload.get("common_quote", "")
    trend = payload.get("trend", "stable")

    return f"""TRIGGER: Review theme emerged — "{theme}" mentioned {count}x in last 30 days ({trend} trend). Quote: "{quote}"

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Present the pattern factually — quote an actual review
2. Context: is this above/below peer average for this theme?
3. Suggest ONE concrete fix
4. Reciprocity frame: "I flagged this so you can address it before it affects your rating"
"""


def prompt_curious_ask(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    ask_template = payload.get("ask_template", "what_service_in_demand")

    return f"""TRIGGER: Curious ask — weekly engagement cadence. Goal: get the merchant talking.

{_fmt_merchant(merchant)}

ASK TEMPLATE: {ask_template}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Ask ONE low-stakes question about their business this week
2. Offer something in return ("I'll turn the answer into a Google post + WhatsApp reply")
3. Keep it under 200 characters
4. The asking-the-merchant lever is the core driver here"""


def prompt_customer_lapsed(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_visit", 0)
    focus = payload.get("previous_focus", "")
    membership_months = payload.get("previous_membership_months", 0)

    return f"""TRIGGER: Customer lapsed — {days} days since last visit. Previous focus: {focus}. Was a {membership_months}-month member.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. Address by name — warm, no-shame tone
2. "Happens to most members" — normalize the lapse
3. Reference a NEW offering that matches their previous focus
4. Single binary CTA with explicit "no commitment, no auto-charge" reassurance
5. Specific date/time for the re-engagement offer"""


def prompt_chronic_refill(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    molecules = payload.get("molecule_list", [])
    runs_out = payload.get("stock_runs_out_iso", "soon")
    delivery_saved = payload.get("delivery_address_saved", False)

    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]

    return f"""TRIGGER: Chronic prescription refill due — patient's medicines running out.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

REFILL DATA:
- Molecules: {', '.join(molecules)}
- Stock runs out: {runs_out}
- Delivery address saved: {delivery_saved}
- Active merchant offers: {active_offers}

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. List all molecule names (precision builds trust)
2. State exact run-out date
3. Apply any relevant merchant offers (senior discount, free delivery)
4. Calculate total with savings shown
5. Provide two response options (reply CONFIRM or call for dosage changes)
6. Respectful tone — if senior, use appropriate salutation
7. If customer.preferences.channel includes "via_son", address accordingly"""


def prompt_supply_alert(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    molecule = payload.get("molecule", "?")
    batches = payload.get("affected_batches", [])
    manufacturer = payload.get("manufacturer", "?")

    cust_agg = merchant.get("customer_aggregate", {})
    chronic_count = cust_agg.get("chronic_rx_count", "?")

    return f"""TRIGGER: Supply alert — voluntary recall on {molecule} batches {batches} by {manufacturer}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Lead with urgency — batch numbers are specific
2. State risk level accurately (sub-potency, no safety risk)
3. Derive affected customer count from merchant's chronic_rx_count ({chronic_count})
4. Offer to draft customer WhatsApp note + replacement workflow
5. Trustworthy-precise tone — no alarm beyond what's warranted"""


def prompt_active_planning(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    topic = payload.get("intent_topic", "?")
    last_msg = payload.get("merchant_last_message", "")

    return f"""TRIGGER: Active planning intent — merchant expressed interest in: "{topic}". Their last message: "{last_msg}"

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Provide a COMPLETE draft artifact — a ready-to-use plan, not more questions
2. Include tiered pricing if appropriate (e.g., 10/25/50 unit tiers)
3. Reference locality-specific opportunities
4. End with a follow-on action offer
5. This is ACTION MODE — the merchant already committed. Don't ask qualifying questions."""


def prompt_renewal_due(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    days = payload.get("days_remaining", 0)
    plan = payload.get("plan", "Pro")
    amount = payload.get("renewal_amount", "?")

    perf = merchant.get("performance", {})

    return f"""TRIGGER: Subscription renewal due in {days} days. Plan: {plan}, amount: ₹{amount}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Recap value delivered during current period (use their actual performance numbers)
2. Frame renewal urgency without being pushy
3. Single binary CTA
4. If performance is poor, acknowledge it and offer to fix it as part of renewal"""


def prompt_competitor_opened(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    comp_name = payload.get("competitor_name", "?")
    distance = payload.get("distance_km", "?")
    their_offer = payload.get("their_offer", "?")
    opened = payload.get("opened_date", "?")

    return f"""TRIGGER: New competitor opened — {comp_name}, {distance}km away, opened {opened}. Their offer: "{their_offer}"

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Name the competitor and distance (it's in the context — NOT fabricated)
2. Compare their offer to merchant's current offer
3. Suggest differentiation strategy (not price war)
4. Curiosity lever — "want to see their full GBP listing?"
5. Voyeur-curiosity framing, not alarm"""


def prompt_festival(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    festival = payload.get("festival", "?")
    date = payload.get("date", "?")
    days_until = payload.get("days_until", "?")

    seasonal = category.get("seasonal_beats", [])
    relevant_beat = ""
    for s in seasonal:
        if any(month in s.get("month_range", "").lower() for month in ["oct", "nov", "dec", "diwali"]):
            relevant_beat = s.get("note", "")
            break

    return f"""TRIGGER: Festival upcoming — {festival} on {date}, {days_until} days away.

{_fmt_merchant(merchant)}
SEASONAL INSIGHT: {relevant_beat}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Reference the festival and timeline
2. Connect to category-specific seasonal opportunity
3. Suggest a specific campaign or offer (using their existing catalog if possible)
4. Time-bound CTA"""


def prompt_dormant(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_merchant_message", 0)
    last_topic = payload.get("last_topic", "unknown")

    return f"""TRIGGER: Dormant merchant — no message from them in {days} days. Last topic was: "{last_topic}".

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Light touch — don't guilt-trip about absence
2. Lead with a NEW piece of value (latest digest item, a performance insight, a peer comparison)
3. Keep it very short (<200 chars)
4. Curiosity lever — give them a reason to reply"""


def prompt_winback_merchant(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    days_expired = payload.get("days_since_expiry", 0)
    perf_dip = payload.get("perf_dip_pct", 0)
    lapsed_added = payload.get("lapsed_customers_added_since_expiry", 0)

    return f"""TRIGGER: Winback eligible — subscription expired {days_expired} days ago. Performance dipped {_safe_pct(perf_dip)} since expiry. {lapsed_added} customers lapsed since.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Frame the impact of expiry with their real numbers
2. Show what they're missing (lapsed customers, performance dip)
3. Offer a specific winback action (not just "renew")
4. Loss aversion is the primary lever"""


def prompt_gbp_unverified(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    uplift = payload.get("estimated_uplift_pct", 0.3)
    path = payload.get("verification_path", "postcard_or_phone_call")

    return f"""TRIGGER: GBP unverified — merchant's Google Business Profile is not verified. Estimated uplift: +{_safe_pct(uplift)}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. State the uplift potential with specific numbers (their current views × uplift)
2. Explain the verification process briefly ({path})
3. Offer to guide them through it
4. Effort externalization — "takes 5 minutes, I'll walk you through it" """


def prompt_cde_opportunity(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    digest_id = payload.get("digest_item_id", "")
    credits = payload.get("credits", 0)
    fee = payload.get("fee", "?")

    digest_str = _fmt_digest(category, digest_id)

    return f"""TRIGGER: CDE/training opportunity — continuing education event relevant to this merchant.

{digest_str}
{_fmt_merchant(merchant)}

EVENT DATA: {credits} CDE credits, Fee: {fee}

COMPOSE a merchant-facing message (send_as=vera) that:
1. Reference the specific event title, date, and speaker if available
2. Mention CDE credits and fee
3. Peer-to-peer recommendation tone
4. Simple CTA — register link or "shall I register you?" """


def prompt_trial_followup(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    trial_date = payload.get("trial_date", "?")
    next_options = payload.get("next_session_options", [])
    slot_str = " ya ".join([s.get("label", "?") for s in next_options[:2]])

    return f"""TRIGGER: Trial followup — customer did a trial on {trial_date}. Next session options: {slot_str}.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. Reference the trial experience
2. Offer specific next slots
3. If child (age_band includes "child"), address the parent
4. Low-friction commitment"""


def prompt_seasonal_category(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    season = payload.get("season", "?")
    trends = payload.get("trends", [])
    shelf_action = payload.get("shelf_action_recommended", False)

    return f"""TRIGGER: Category seasonal shift — {season}. Demand trends: {trends}. Shelf action recommended: {shelf_action}.

{_fmt_merchant(merchant)}

COMPOSE a merchant-facing message (send_as=vera) that:
1. List the top 2-3 demand shifts with numbers
2. Recommend specific shelf/inventory action
3. Practical, data-driven tone
4. Offer to help with the transition"""


def prompt_wedding_followup(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    payload = trigger.get("payload", {})
    wedding_date = payload.get("wedding_date", "?")
    trial_date = payload.get("trial_completed", "?")
    days_to = payload.get("days_to_wedding", "?")
    next_step = payload.get("next_step_window_open", "?")

    return f"""TRIGGER: Bridal/wedding package followup — {days_to} days to wedding ({wedding_date}). Trial completed {trial_date}. Current window: {next_step}.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. Wedding countdown creates urgency
2. Reference the specific prep window that's open now
3. Include package price from merchant's catalog if available
4. Offer to block their preferred slot
5. Warm, exciting tone — this is a happy occasion"""


def prompt_appointment_reminder(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    return f"""TRIGGER: Appointment tomorrow — standard reminder.

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a customer-facing message (send_as=merchant_on_behalf) that:
1. Confirm the appointment details (time, service)
2. Any prep instructions relevant to the category
3. Friendly, brief
4. Reply option to reschedule"""


def prompt_generic(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> str:
    """Fallback for trigger kinds not explicitly mapped."""
    payload = trigger.get("payload", {})
    return f"""TRIGGER: {trigger.get('kind', 'unknown')} (source: {trigger.get('source', '?')}, urgency: {trigger.get('urgency', '?')})

TRIGGER PAYLOAD: {json.dumps(payload, indent=2)}

{_fmt_merchant(merchant)}
{_fmt_customer(customer)}

COMPOSE a {'customer-facing (send_as=merchant_on_behalf)' if trigger.get('scope') == 'customer' else 'merchant-facing (send_as=vera)'} message that:
1. Clearly communicates WHY NOW (the trigger event)
2. Anchors on a specific fact from the context
3. Single clear CTA
4. Match the category voice and merchant's language preference"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ROUTER — maps trigger.kind → prompt builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRIGGER_PROMPT_MAP = {
    "research_digest": prompt_research_digest,
    "regulation_change": prompt_regulation_change,
    "recall_due": prompt_recall_due,
    "perf_dip": prompt_perf_dip,
    "seasonal_perf_dip": prompt_perf_dip,
    "perf_spike": prompt_perf_spike,
    "milestone_reached": prompt_milestone,
    "ipl_match_today": prompt_ipl_match,
    "review_theme_emerged": prompt_review_theme,
    "curious_ask_due": prompt_curious_ask,
    "customer_lapsed_hard": prompt_customer_lapsed,
    "customer_lapsed_soft": prompt_customer_lapsed,
    "chronic_refill_due": prompt_chronic_refill,
    "supply_alert": prompt_supply_alert,
    "active_planning_intent": prompt_active_planning,
    "renewal_due": prompt_renewal_due,
    "competitor_opened": prompt_competitor_opened,
    "festival_upcoming": prompt_festival,
    "dormant_with_vera": prompt_dormant,
    "winback_eligible": prompt_winback_merchant,
    "gbp_unverified": prompt_gbp_unverified,
    "cde_opportunity": prompt_cde_opportunity,
    "trial_followup": prompt_trial_followup,
    "category_seasonal": prompt_seasonal_category,
    "wedding_package_followup": prompt_wedding_followup,
    "appointment_tomorrow": prompt_appointment_reminder,
}


def get_trigger_prompt(kind: str):
    """Get the prompt builder function for a trigger kind."""
    return TRIGGER_PROMPT_MAP.get(kind, prompt_generic)
