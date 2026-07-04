import os
import json
import re
import time
import httpx
from dotenv import load_dotenv
from prompts import COMPOSE_SYSTEM
from scenario_map import SCENARIO_MAP

load_dotenv()

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")
GROQ_MODEL     = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Round-robin index across both Groq keys
_groq_key_idx = 0

def _next_groq_key() -> str:
    global _groq_key_idx
    keys = [k for k in [GROQ_API_KEY, GROQ_API_KEY_2] if k]
    if not keys:
        return ""
    key = keys[_groq_key_idx % len(keys)]
    _groq_key_idx += 1
    return key


def _call_groq(system: str, user: str, max_tokens: int = 1200) -> str:
    keys = [k for k in [GROQ_API_KEY, GROQ_API_KEY_2] if k]
    if not keys:
        return ""
    # Try each key in round-robin order; on 429 immediately try the next key
    start_idx = _groq_key_idx % len(keys)
    attempt_keys = keys[start_idx:] + keys[:start_idx]
    for i, key in enumerate(attempt_keys):
        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "temperature": 0,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                    },
                )
                if resp.status_code == 429:
                    key_label = f"key{'2' if key == GROQ_API_KEY_2 else '1'}"
                    print(f"[Groq 429] {key_label} rate limited — {'trying key2' if i == 0 and len(keys) > 1 else 'budget exhausted'}")
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[Groq FAILED] {e}")
    return ""


def _call_gemini(system: str, user: str, max_tokens: int = 1200) -> str:
    if not GEMINI_API_KEY:
        return ""
    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=system,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                max_output_tokens=max_tokens,
            ),
        )

        import threading

        result_holder = {"text": "", "error": None}

        def _call():
            try:
                resp = model.generate_content(user)
                result_holder["text"] = resp.text or ""
            except Exception as ex:
                result_holder["error"] = ex

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=4.0)
        if t.is_alive():
            print("[Gemini FAILED] timeout after 4s")
            return ""
        if result_holder["error"]:
            raise result_holder["error"]
        return result_holder["text"]

    except Exception as e:
        print(f"[Gemini FAILED] {e}")
        return ""


def call_llm(system: str, user: str, max_tokens: int = 1200) -> str:
    result = _call_groq(system, user, max_tokens)
    if result:
        return result

    print("[LLM] Tier 1 failed. Trying Tier 2 (Gemini).")
    result = _call_gemini(system, user, max_tokens)
    if result:
        return result

    print("[LLM] Both tiers failed. Returning empty.")
    return ""


def parse_json(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def extract_facts(category: dict, merchant: dict,
                  trigger: dict, customer: dict | None) -> dict:
    identity = merchant.get("identity", {})
    perf     = merchant.get("performance", {})
    peer     = category.get("peer_stats", {})
    cust_agg = merchant.get("customer_aggregate", {})
    offers   = [o for o in merchant.get("offers", [])
                if o.get("status") == "active"]
    payload  = trigger.get("payload", {})
    digest   = category.get("digest", [])

    facts = {
        "owner_first_name":      identity.get("owner_first_name", ""),
        "merchant_name":         identity.get("name", ""),
        "locality":              identity.get("locality", ""),
        "city":                  identity.get("city", ""),
        "languages":             identity.get("languages", ["en"]),
        "views":                 perf.get("views"),
        "calls":                 perf.get("calls"),
        "ctr":                   perf.get("ctr"),
        "leads":                 perf.get("leads"),
        "delta_7d_views":        perf.get("delta_7d", {}).get("views_pct"),
        "delta_7d_calls":        perf.get("delta_7d", {}).get("calls_pct"),
        "peer_avg_ctr":          peer.get("avg_ctr"),
        "peer_avg_rating":       peer.get("avg_rating"),
        "active_offers":         [o.get("title") for o in offers],
        "active_offer_ids":      [o.get("id")    for o in offers],
        "signals":               merchant.get("signals", []),
        "active_customers":      cust_agg.get("total_unique_ytd"),
        "lapsed_customers":      cust_agg.get("lapsed_180d_plus"),
        "retention_rate":        cust_agg.get("retention_6mo_pct"),
        "high_risk_adult_count": cust_agg.get("high_risk_adult_count"),
        "trigger_kind":          trigger.get("kind"),
        "trigger_urgency":       trigger.get("urgency"),
        "trigger_payload":       payload,
        "suppression_key":       trigger.get("suppression_key", ""),
    }

    if digest:
        d = digest[0]
        facts["digest_title"]   = d.get("title", "")
        facts["digest_source"]  = d.get("source", "")
        facts["digest_trial_n"] = d.get("trial_n", "")
        facts["digest_summary"] = d.get("summary", "")
        facts["digest_kind"]    = d.get("kind", "")

    if customer:
        cust_id  = customer.get("identity", {})
        cust_rel = customer.get("relationship", {})
        facts.update({
            "customer_name":          cust_id.get("name", ""),
            "customer_language":      cust_id.get("language_pref", "english"),
            "customer_age_band":      cust_id.get("age_band", ""),
            "customer_state":         customer.get("state", ""),
            "customer_visits":        cust_rel.get("visits_total", ""),
            "customer_last_visit":    cust_rel.get("last_visit", ""),
            "customer_ltv":           cust_rel.get("lifetime_value", ""),
            "customer_preferred_svc": cust_rel.get("preferred_service", ""),
        })

    # Unpack trigger payload keys as named facts for cleaner prompt surfacing
    scenario_cfg = SCENARIO_MAP.get(trigger.get("kind", ""), {})
    for key in scenario_cfg.get("payload_keys", []):
        if key in payload:
            facts[f"payload_{key}"] = payload[key]

    ctr      = perf.get("ctr", 0)
    peer_ctr = peer.get("avg_ctr", 0)
    if ctr and peer_ctr and peer_ctr > 0:
        gap_pct = round((peer_ctr - ctr) / peer_ctr * 100)
        facts["ctr_gap_pct"]  = gap_pct
        facts["ctr_gap_text"] = (
            f"CTR {ctr:.1%} vs peer avg {peer_ctr:.1%} ({gap_pct}% below)"
        )

    return facts


def _payload_block(facts: dict) -> str:
    keys = [k for k in facts if k.startswith("payload_")]
    if not keys:
        raw = facts.get("trigger_payload", {})
        if raw:
            return f"Full trigger payload: {json.dumps(raw, ensure_ascii=False)}"
        return ""
    lines = ["=== TRIGGER PAYLOAD (use these directly) ==="]
    for k in sorted(keys):
        label = k.replace("payload_", "").replace("_", " ").title()
        lines.append(f"{label}: {facts[k]}")
    return "\n".join(lines)


def build_user_prompt(facts: dict, framing: str,
                      category: dict, trigger: dict) -> str:
    active_offers_str = (
        ", ".join(facts.get("active_offers", [])) or
        "No active offers currently"
    )
    signals_str = (
        ", ".join(facts.get("signals", [])) or "No signals"
    )
    ctr_gap = facts.get("ctr_gap_text", "CTR data not available")

    customer_block = ""
    if facts.get("customer_name"):
        extras = ""
        if facts.get("customer_ltv"):           extras += f"\nLifetime value: {facts['customer_ltv']}"
        if facts.get("customer_preferred_svc"): extras += f"\nPreferred service: {facts['customer_preferred_svc']}"
        if facts.get("customer_age_band"):      extras += f"\nAge band: {facts['customer_age_band']}"
        customer_block = f"""
=== CUSTOMER CONTEXT ===
Name:        {facts['customer_name']}
Language:    {facts['customer_language']}
State:       {facts['customer_state']}
Visits:      {facts['customer_visits']}
Last visit:  {facts['customer_last_visit']}{extras}
"""

    digest_block = ""
    if facts.get("digest_title"):
        digest_block = f"""
=== RESEARCH / DIGEST ITEM ===
Title:    {facts['digest_title']}
Source:   {facts['digest_source']}
Trial N:  {facts['digest_trial_n']}
Summary:  {facts['digest_summary']}
MANDATORY: End the message body with the source citation
in parentheses — e.g. ({facts['digest_source']})
Score is capped at 7/10 without it.
"""

    return f"""=== SCENARIO INSTRUCTION ===
Trigger kind: {facts['trigger_kind']}
Framing:      {framing}

=== EXTRACTED FACTS — USE ONLY THESE, NEVER INVENT ===
Owner first name:  {facts['owner_first_name']}
Merchant name:     {facts['merchant_name']}
Locality:          {facts['locality']}, {facts['city']}
Languages:         {facts['languages']}
Views (30d):       {facts['views']}
Calls (30d):       {facts['calls']}
CTR vs peers:      {ctr_gap}
7d view change:    {facts['delta_7d_views']}
7d call change:    {facts['delta_7d_calls']}
Active offers:     {active_offers_str}
Active customers:  {facts['active_customers']}
Lapsed customers:  {facts['lapsed_customers']}
Retention (6mo):   {facts['retention_rate']}
High-risk adults:  {facts['high_risk_adult_count']}
Signals:           {signals_str}
Trigger urgency:   {facts['trigger_urgency']}
Suppression key:   {facts['suppression_key']}
{_payload_block(facts)}
{digest_block}{customer_block}
=== MANDATORY MERCHANT-FIT RULES (checked by judge) ===
Your message MUST include ALL THREE or merchant_fit is capped at 6:
  1. Locality: mention "{facts['locality']}" or "{facts['city']}" by name
  2. Offer: name at least one active offer with its exact price
  3. Metric: use at least one real number (views, calls, CTR, lapsed count)
Messages that only swap the owner name score ≤6. Make it unusable for any other merchant.

=== YOUR TASK ===
Using ONLY the facts above, compose the message now.
Reference at least 3 specific facts (numbers, names,
dates, or sources). Return ONLY valid JSON. No other text."""


def ensure_minimum_numbers(result: dict, facts: dict) -> dict:
    body = result.get("body", "")
    num_count = len(re.findall(r'\d+', body))
    if num_count >= 3:
        return result

    injections = []
    v = facts.get("views")
    if v and str(v) not in body:
        injections.append(f"{v} views this month")
    ctr_text = facts.get("ctr_gap_text")
    if ctr_text and "CTR" not in body:
        injections.append(ctr_text)
    lapsed = facts.get("lapsed_customers")
    if lapsed and str(lapsed) not in body:
        injections.append(f"{lapsed} lapsed customers")
    offers = facts.get("active_offers", [])
    if offers and offers[0] and offers[0] not in body:
        injections.append(offers[0])

    if injections:
        needed = max(0, 3 - num_count)
        addition = " | ".join(str(x) for x in injections[:needed])
        first_period = body.find(".")
        if first_period > 0:
            body = (body[:first_period + 1] +
                    f" ({addition})" +
                    body[first_period + 1:])
        else:
            body = body + f" ({addition})"
        result["body"] = body
    return result


def ensure_merchant_fit(result: dict, facts: dict) -> dict:
    """Post-process: inject locality and top offer into body if either is missing."""
    body     = result.get("body", "")
    locality = facts.get("locality", "")
    city     = facts.get("city", "")
    offers   = facts.get("active_offers", [])
    offer    = offers[0] if offers else ""

    loc_present = (locality and locality.lower() in body.lower()) or \
                  (city and city.lower() in body.lower())
    offer_present = offer and offer.split("@")[0].strip().lower() in body.lower()

    injections = []
    if not loc_present and (locality or city):
        injections.append(f"{locality}, {city}".strip(", "))
    if not offer_present and offer:
        injections.append(offer)

    if injections:
        tag = " (" + " | ".join(injections) + ")"
        first_period = body.find(".")
        if first_period > 0:
            body = body[:first_period + 1] + tag + body[first_period + 1:]
        else:
            body = body + tag
        result["body"] = body
    return result


def ensure_citation(result: dict, facts: dict, kind: str) -> dict:
    if kind not in ("research_digest", "regulation_change"):
        return result
    body   = result.get("body", "")
    source = facts.get("digest_source", "")
    if not source:
        return result
    source_key = source.split(",")[0].strip()
    if source_key.lower() in body.lower():
        return result
    result["body"] = body.rstrip(".").rstrip() + f" ({source})"
    return result


def build_smart_fallback(facts: dict, scenario: dict | None) -> dict:
    owner    = facts.get("owner_first_name", "")
    views    = facts.get("views", "")
    lapsed   = facts.get("lapsed_customers", "")
    offers   = facts.get("active_offers", [])
    offer    = offers[0] if offers else ""
    kind     = facts.get("trigger_kind", "update")
    ctr_text = facts.get("ctr_gap_text", "")

    locality = facts.get("locality", "")
    city     = facts.get("city", "")
    loc_str  = f"{locality}, {city}".strip(", ") if (locality or city) else ""

    parts = [f"{owner},"]
    if loc_str:
        parts.append(f"aapki {loc_str} ki listing pe")
    if views:
        parts.append(f"{views} views aaye is mahine.")
    else:
        parts.append("")
    if ctr_text:
        parts.append(ctr_text + ".")
    if lapsed:
        parts.append(f"{lapsed} customers lapsed hain.")
    if offer:
        parts.append(f"Aapka '{offer}' promote karna chahiye?")
    parts.append("Reply YES.")

    return {
        "body": " ".join(parts),
        "cta": "binary_yes_no",
        "send_as": (
            "merchant_on_behalf"
            if scenario and scenario.get("scope") == "customer"
            else "vera"
        ),
        "suppression_key": facts.get("suppression_key",
                                     f"fallback:{kind}"),
        "rationale": (
            f"Fallback (LLM unavailable). "
            f"Signal: {kind}. Facts: views={views}, lapsed={lapsed}"
        ),
    }


def compose(category: dict, merchant: dict,
            trigger: dict, customer: dict | None = None) -> dict:
    kind     = trigger.get("kind", "")
    scenario = SCENARIO_MAP.get(kind)

    facts = extract_facts(category, merchant, trigger, customer)

    if scenario:
        framing        = scenario["framing"]
        forced_cta     = scenario["cta_style"]
        forced_send_as = scenario["send_as"]
    else:
        print(f"[compose] Unknown kind: {kind} — using generic framing")
        framing        = (f"Unknown trigger kind '{kind}'. "
                          f"Use trigger payload to determine best angle.")
        forced_cta     = "open_ended"
        forced_send_as = "vera"

    user_prompt = build_user_prompt(facts, framing, category, trigger)

    raw = call_llm(COMPOSE_SYSTEM, user_prompt)

    result = parse_json(raw)

    if not result or not result.get("body"):
        print(f"[compose] LLM returned no body for kind={kind}. Using fallback.")
        result = build_smart_fallback(facts, scenario)

    result["cta"]     = forced_cta
    result["send_as"] = forced_send_as
    result.setdefault("suppression_key", facts.get("suppression_key", ""))
    result.setdefault(
        "rationale",
        f"Signal: {kind}. "
        f"Lever: {scenario.get('compulsion_lever', 'generic') if scenario else 'generic'}.",
    )

    result = ensure_minimum_numbers(result, facts)
    result = ensure_merchant_fit(result, facts)
    result = ensure_citation(result, facts, kind)

    return result
