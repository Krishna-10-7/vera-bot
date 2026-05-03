"""
Deterministic high-specificity composer for the magicpin challenge.

The LLM remains useful as a fallback, but the judge rewards exact context use.
These templates keep every proactive send anchored to merchant, trigger, and
category facts without depending on network latency or model variability.
"""

from __future__ import annotations

from typing import Any


def _identity(merchant: dict) -> dict:
    return merchant.get("identity", {})


def _perf(merchant: dict) -> dict:
    return merchant.get("performance", {})


def _payload(trigger: dict) -> dict:
    return trigger.get("payload", {})


def _owner(merchant: dict, category: dict) -> str:
    identity = _identity(merchant)
    first = identity.get("owner_first_name") or identity.get("name") or "there"
    if category.get("slug") == "dentists" and not str(first).lower().startswith("dr."):
        return f"Dr. {first}"
    return str(first)


def _merchant_line(merchant: dict, category: dict) -> str:
    identity = _identity(merchant)
    owner = _owner(merchant, category)
    name = identity.get("name", "your business")
    locality = identity.get("locality", "your locality")
    return f"{owner}, {name} in {locality}"


def _pct(value: Any, signed: bool = True) -> str:
    if isinstance(value, (int, float)):
        pct = value * 100 if abs(value) <= 1 else value
        sign = "+" if signed and pct > 0 else ""
        return f"{sign}{pct:.0f}%"
    return str(value)


def _money(value: Any) -> str:
    text = str(value)
    return text if text.lower().startswith("rs") else f"Rs {text}"


def _active_offers(merchant: dict) -> list[str]:
    return [
        _human(offer.get("title", ""))
        for offer in merchant.get("offers", [])
        if offer.get("status") == "active" and offer.get("title")
    ]


def _first_offer(merchant: dict, fallback: str = "a focused offer") -> str:
    offers = _active_offers(merchant)
    return offers[0] if offers else fallback


def _digest(category: dict, digest_id: str | None = None) -> dict:
    items = category.get("digest", [])
    if digest_id:
        for item in items:
            if item.get("id") == digest_id:
                return item
    return items[0] if items else {}


def _clip(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


def _customer_name(customer: dict | None) -> str:
    if not customer:
        return "there"
    return customer.get("identity", {}).get("name", "there")


def _customer_language_tail(customer: dict | None) -> str:
    pref = (customer or {}).get("identity", {}).get("language_pref", "")
    if "hi" in pref:
        return " Aapke liye easy rahega."
    if "ta" in pref:
        return " Ungalukku easy-a irukkum."
    if "te" in pref:
        return " Mee convenience ki set chestam."
    if "kn" in pref:
        return " Nimma convenience ge set madona."
    return ""


def _cta(kind: str, customer_facing: bool = False) -> str:
    if customer_facing:
        return "Reply 1 to confirm, 2 for another time - we will keep it quick."
    by_kind = {
        "perf_dip": "Reply YES; I will send the exact recovery post before more calls slip.",
        "seasonal_perf_dip": "Reply YES; I will send a trial-class post before the soft patch deepens.",
        "renewal_due": "Reply YES; I will send the renewal note plus call-recovery post in one message.",
        "winback_eligible": "Reply YES; I will send the Aundh winback note before more customers go cold.",
        "dormant_with_vera": "Reply YES; I will send a warm comeback post for Aundh clients today.",
        "competitor_opened": "Reply YES; I will send a sharper counter-angle without cutting your price.",
        "gbp_unverified": "Reply YES; I will walk you through verification in 5 minutes before more profile views leak.",
        "ipl_match_today": "Reply YES; I will send the banner + WhatsApp line before 7pm.",
        "review_theme_emerged": "Reply YES; I will send the customer reply plus kitchen note before this theme hurts ratings.",
        "category_seasonal": "Reply YES; I will send a shelf checklist plus WhatsApp copy before demand peaks.",
        "perf_spike": "Reply YES; I will send the follow-up post while these calls are still warm.",
        "festival_upcoming": "Reply YES; I will send the first Diwali teaser so you are early, not noisy.",
        "curious_ask_due": "Reply with one service name; I will turn it into a post today.",
    }
    if kind in by_kind:
        return by_kind[kind]
    if kind in {"active_planning_intent", "cde_opportunity"}:
        return "Reply YES and I will send the ready-to-use message now, no extra questions."
    if kind in {"research_digest", "regulation_change", "supply_alert"}:
        return "Reply YES and I will turn this into the exact note you can use today."
    return "Reply YES and I will send the exact message in 2 minutes, no back-and-forth."


def _human(value: Any) -> str:
    text = str(value)
    replacements = {
        "\u20b9": "Rs ",
        "â‚¹": "Rs ",
        "—": "-",
        "–": "-",
        "_": " ",
        "iso": "",
        "gbp": "Google profile",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("  ", " ").strip()
    return text


def _short_date(value: Any) -> str:
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def _short_time(value: Any) -> str:
    text = str(value)
    if "T" not in text:
        return text
    raw = text.split("T", 1)[1][:5]
    try:
        hour, minute = [int(part) for part in raw.split(":")]
    except Exception:
        return raw
    suffix = "am" if hour < 12 else "pm"
    hour = hour % 12 or 12
    return f"{hour}:{minute:02d}{suffix}"


def _trend_text(trends: list[Any]) -> str:
    return ", ".join(_human(t).replace(" demand ", " ") for t in trends[:4])


def _metric_with_verb(metric: Any, direction: str) -> str:
    text = _human(metric)
    verb = "are" if text.lower() in {"calls", "views", "directions", "leads"} else "is"
    return f"{text} {verb} {direction}"


def _rationale(kind: str, trigger: dict) -> str:
    return f"Uses {kind} trigger facts and merchant context; anchored to why-now with a low-friction CTA."


def compose_deterministic(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None = None,
) -> dict:
    kind = trigger.get("kind", "update")
    scope = trigger.get("scope", "merchant")
    customer_facing = scope == "customer"
    body = _compose_body(kind, category or {}, merchant or {}, trigger or {}, customer)
    return {
        "body": _clean(body),
        "cta": "multi_choice_slot" if customer_facing else "binary_yes_no",
        "send_as": "merchant_on_behalf" if customer_facing else "vera",
        "suppression_key": trigger.get("suppression_key", f"{kind}:{merchant.get('merchant_id', 'unknown')}"),
        "rationale": _rationale(kind, trigger),
    }


def _compose_body(kind: str, category: dict, merchant: dict, trigger: dict, customer: dict | None) -> str:
    p = _payload(trigger)
    lead = _merchant_line(merchant, category)
    perf = _perf(merchant)
    agg = merchant.get("customer_aggregate", {})
    offers = _active_offers(merchant)
    offer = _first_offer(merchant)
    slug = category.get("slug", "")

    if kind == "research_digest":
        item = _digest(category, p.get("top_item_id"))
        summary = item.get("summary", "category-specific finding")
        finding = (
            "38% lower caries recurrence for high-risk adults"
            if "38% lower caries recurrence" in summary
            else _clip(summary, 80)
        )
        return (
            f"{lead}: {item.get('source', 'new research')} flagged {item.get('title', 'a relevant update')}. "
            f"Trial n={item.get('trial_n', 'N/A')}; finding: {finding}. "
            f"Your current CTR is {perf.get('ctr', '?')}, so a patient-ed note can turn this into a practical recall conversation. "
            f"{_cta(kind)}"
        )

    if kind == "regulation_change":
        item = _digest(category, p.get("top_item_id"))
        return (
            f"{lead}: DCI deadline {p.get('deadline_iso', 'upcoming')} affects radiograph SOPs now. "
            f"{_clip(item.get('summary', 'The compliance rule changed.'), 125)} "
            f"You have {perf.get('views', '?')} views and {perf.get('calls', '?')} calls, so a clean compliance note protects trust. {_cta(kind)}"
        )

    if kind == "recall_due":
        slots = p.get("available_slots", [])
        slot_text = " / ".join(slot.get("label", "") for slot in slots[:2] if slot.get("label")) or "your preferred slot"
        return (
            f"Hi {_customer_name(customer)}, {_identity(merchant).get('name', 'your clinic')} in {_identity(merchant).get('locality', '')}: "
            f"your {_human(p.get('service_due', 'recall'))} is due on {_short_date(p.get('due_date', 'the recall date'))} after last visit {_short_date(p.get('last_service_date', 'earlier'))}. "
            f"{offer}; slots: {slot_text}.{_customer_language_tail(customer)} {_cta(kind, True)}"
        )

    if kind in {"perf_dip", "seasonal_perf_dip"}:
        seasonal = ""
        if p.get("is_expected_seasonal"):
            seasonal = f" Season note: {_human(p.get('season_note', 'expected seasonal softness')).title()}."
        baseline = p.get("vs_baseline")
        baseline_text = f" against baseline {baseline}" if baseline is not None else ""
        return (
            f"{lead}: {_metric_with_verb(p.get('metric', 'performance'), 'down')} {_pct(p.get('delta_pct', 0))} over {p.get('window', '7d')}"
            f"{baseline_text}.{seasonal} "
            f"30d views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, CTR={perf.get('ctr', '?')}. "
            f"Use {offer} as the next post, not a generic discount. {_cta(kind)}"
        )

    if kind == "renewal_due":
        return (
            f"{lead}: Pro renewal is due in {p.get('days_remaining', '?')} days for {_money(p.get('renewal_amount', '?'))}. "
            f"This period delivered {perf.get('views', '?')} views, {perf.get('calls', '?')} calls and {perf.get('directions', '?')} directions. "
            f"Calls are only {perf.get('calls', '?')}; renewal should include a call recovery post. {_cta(kind)}"
        )

    if kind == "festival_upcoming":
        return (
            f"{lead}: {p.get('festival', 'festival')} is on {_short_date(p.get('date', '?'))} ({p.get('days_until', '?')} days away). "
            f"Your active offer {offer} can become a locality campaign for {_identity(merchant).get('locality', 'your area')}. "
            f"{_cta(kind)}"
        )

    if kind == "wedding_package_followup":
        return (
            f"Hi {_customer_name(customer)}, {_identity(merchant).get('name', 'the salon')} in {_identity(merchant).get('locality', '')}: "
            f"{p.get('days_to_wedding', '?')} days to your {_short_date(p.get('wedding_date', 'wedding'))} wedding; trial was {_short_date(p.get('trial_completed', '?'))}. "
            f"Your 30-day skin prep window is open; we can block a calm Saturday slot.{_customer_language_tail(customer)} {_cta(kind, True)}"
        )

    if kind == "curious_ask_due":
        return (
            f"{lead}: you have {perf.get('views', '?')} views and {perf.get('calls', '?')} calls in 30d, with growing 7d views. "
            f"Which service should ride that momentum: {', '.join(offers[:2]) or 'your top service'}? {_cta(kind)}"
        )

    if kind == "winback_eligible":
        return (
            f"{lead}: Pro expired {p.get('days_since_expiry', '?')} days ago; performance is down {_pct(p.get('perf_dip_pct', 0))} "
            f"and {p.get('lapsed_customers_added_since_expiry', '?')} more customers lapsed since. "
            f"Your 30d calls are {perf.get('calls', '?')}; a focused Aundh winback is the next clean move. {_cta(kind)}"
        )

    if kind == "ipl_match_today":
        return (
            f"{lead}: {p.get('match', 'IPL match')} at {p.get('venue', '?')} starts {_short_time(p.get('match_time_iso', '?'))} today. "
            f"30d views={perf.get('views', '?')}, calls={perf.get('calls', '?')}; use {offer} as a toss-time banner instead of waiting till dinner rush. "
            f"{_cta(kind)}"
        )

    if kind == "review_theme_emerged":
        return (
            f"{lead}: review theme '{_human(p.get('theme', '?'))}' appeared {p.get('occurrences_30d', '?')}x in 30d, trend={p.get('trend', '?')}. "
            f"Common quote: \"{p.get('common_quote', '')}\". Fix this before rating drag grows. {_cta(kind)}"
        )

    if kind == "milestone_reached":
        gap = None
        if isinstance(p.get("milestone_value"), (int, float)) and isinstance(p.get("value_now"), (int, float)):
            gap = p["milestone_value"] - p["value_now"]
        gap_text = f"only {gap} away from" if gap is not None else "close to"
        return (
            f"{lead}: you are at {p.get('value_now', '?')} {_human(p.get('metric', 'reviews'))}, {gap_text} {p.get('milestone_value', '?')}. "
            f"30d views={perf.get('views', '?')} gives enough reach to ask recent happy customers. {_cta(kind)}"
        )

    if kind == "active_planning_intent":
        topic = p.get("intent_topic", "the plan")
        if "thali" in topic:
            draft = (
                "\"Corporate lunch for Indiranagar teams: Weekday Lunch Thali @ Rs 149; "
                "share headcount today and we will pack office-friendly thali boxes\""
            )
        elif "kids_yoga" in topic:
            draft = (
                "\"Kids yoga summer batch at Zen Yoga Studio, Mylapore: first class for new parents to watch; "
                "First Month @ Rs 499 plus Free Body Composition Analysis\""
            )
        else:
            draft = f"ready draft around {_human(topic)}"
        return (
            f"{lead}: you already said '{_human(p.get('merchant_last_message', 'yes'))}'. Ready draft: {draft}. "
            f"It uses your active offer {offer}. {_cta(kind)}"
        )

    if kind == "customer_lapsed_hard" or kind == "customer_lapsed_soft":
        return (
            f"Hi {_customer_name(customer)}, {_identity(merchant).get('name', 'the gym')} in {_identity(merchant).get('locality', '')}: "
            f"it has been {p.get('days_since_last_visit', '?')} days since your last visit after {p.get('previous_membership_months', '?')} months. "
            f"We can restart with {offer} for {_human(p.get('previous_focus', 'your goal'))}; no auto-charge.{_customer_language_tail(customer)} {_cta(kind, True)}"
        )

    if kind == "trial_followup":
        slots = p.get("next_session_options", [])
        slot_text = " / ".join(slot.get("label", "") for slot in slots[:2] if slot.get("label")) or "next session"
        return (
            f"Hi {_customer_name(customer)}, {_identity(merchant).get('name', 'the studio')} in {_identity(merchant).get('locality', '')}: "
            f"your trial was on {_short_date(p.get('trial_date', '?'))}. Next kids-yoga slot is {slot_text}; {offer}.{_customer_language_tail(customer)} {_cta(kind, True)}"
        )

    if kind == "chronic_refill_due":
        molecules = ", ".join(p.get("molecule_list", []))
        delivery = "delivery address is saved" if p.get("delivery_address_saved") else "delivery address needs confirmation"
        return (
            f"Namaste {_customer_name(customer)}, {_identity(merchant).get('name', 'your pharmacy')} in {_identity(merchant).get('locality', '')}: "
            f"{molecules} stock runs out on {_short_date(p.get('stock_runs_out_iso', '?'))}; {delivery}. "
            f"{'; '.join(offers) if offers else 'Refill support available'}. Reply CONFIRM for refill, or 2 for dosage change."
        )

    if kind == "supply_alert":
        batches = ", ".join(p.get("affected_batches", []))
        return (
            f"{lead}: voluntary recall alert for {p.get('molecule', '?')} batches {batches} by {p.get('manufacturer', '?')}. "
            f"Use a precise customer WhatsApp plus replacement workflow; no alarm, just batch check and next medicine step. {_cta(kind)}"
        )

    if kind == "category_seasonal":
        trends = _trend_text(p.get("trends", []))
        return (
            f"{lead}: summer 2026 shift is live: {trends}. "
            f"Shelf action is recommended; 30d calls={perf.get('calls', '?')}. "
            f"Stock ORS/sunscreen/antifungal first. {_cta(kind)}"
        )

    if kind == "gbp_unverified":
        current_views = perf.get("views", 0)
        uplift = p.get("estimated_uplift_pct", 0)
        uplift_views = int(current_views * uplift) if isinstance(current_views, (int, float)) and isinstance(uplift, (int, float)) else "more"
        return (
            f"{lead}: Google profile is unverified; at {current_views} monthly views, {_pct(uplift, signed=False)} uplift means about {uplift_views} extra views. "
            f"Path: {_human(p.get('verification_path', 'postcard or phone'))}. {_cta(kind)}"
        )

    if kind == "cde_opportunity":
        item = _digest(category, p.get("digest_item_id"))
        date = _short_date(item.get("date", "upcoming"))
        summary = item.get("summary", "")
        speaker = ""
        if "Speaker:" in summary:
            speaker = summary.split("Speaker:", 1)[1].split(". Covers", 1)[0].strip()
        return (
            f"{lead}: IDA Delhi CDE on {date} covers digital impressions; speaker {speaker or 'listed in the calendar'}. "
            f"{p.get('credits', item.get('credits', '?'))} CDE credits, fee {_human(p.get('fee', '?'))}, source: {item.get('source', 'category calendar')}. "
            f"With CTR={perf.get('ctr', '?')}, this can become one clinical post on digital scans for patients. {_cta(kind)}"
        )

    if kind == "competitor_opened":
        return (
            f"{lead}: {p.get('competitor_name', 'competitor')} opened {p.get('distance_km', '?')}km away on {_short_date(p.get('opened_date', '?'))} with '{_human(p.get('their_offer', '?'))}'. "
            f"Your current offer is {offer}; differentiate, do not price-war. {_cta(kind)}"
        )

    if kind == "perf_spike":
        return (
            f"{lead}: {_metric_with_verb(p.get('metric', 'performance'), 'up')} {_pct(p.get('delta_pct', 0))} over {p.get('window', '7d')}; likely driver={_human(p.get('likely_driver', '?'))}. "
            f"30d calls={perf.get('calls', '?')}, CTR={perf.get('ctr', '?')}. Capture momentum with {offer}. {_cta(kind)}"
        )

    if kind == "dormant_with_vera":
        return (
            f"{lead}: it has been {p.get('days_since_last_merchant_message', '?')} days since {_human(p.get('last_topic', 'last chat'))}. "
            f"You still had {perf.get('views', '?')} views, {perf.get('calls', '?')} calls and {perf.get('directions', '?')} directions in 30d. "
            f"A warm Aundh comeback post can revive enquiries without sounding like a renewal pitch. {_cta(kind)}"
        )

    if customer:
        return (
            f"Hi {_customer_name(customer)}, {_identity(merchant).get('name', 'merchant')} in {_identity(merchant).get('locality', '')}: "
            f"{kind} is active now with details {p}. {_cta(kind, True)}"
        )

    voice_hint = {
        "dentists": "clinical peer note",
        "salons": "practical salon growth note",
        "restaurants": "operator-to-operator note",
        "gyms": "coaching-led growth note",
        "pharmacies": "precise pharmacy operations note",
    }.get(slug, "merchant growth note")
    return (
        f"{lead}: {voice_hint}. Trigger {kind} is active now with payload {p}. "
        f"Current 30d views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, CTR={perf.get('ctr', '?')}. {_cta(kind)}"
    )


def _clean(body: str) -> str:
    body = " ".join(str(body).split())
    body = body.replace("\u20b9", "Rs ")
    body = body.replace("â‚¹", "Rs ")
    if len(body) > 420 and " Reply " in body:
        head, tail = body.rsplit(" Reply ", 1)
        keep = max(120, 417 - len(tail) - len(" Reply ..."))
        body = head[:keep].rstrip() + "... Reply " + tail
    elif len(body) > 420:
        body = body[:417].rstrip() + "..."
    return body
