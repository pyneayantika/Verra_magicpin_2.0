"""
score_server.py — Vera Dev Console Scoring Server
Lightweight FastAPI server on port 8090.
Uses the EXACT LLMScorer judge prompt from judge_simulator.py.

Run from inside vera-bot/:
    python score_server.py
"""

import os
import re
import json
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL        = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

app = FastAPI(title="Vera Score Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# EXACT LLMScorer.SYSTEM prompt from judge_simulator.py — verbatim copy
# ---------------------------------------------------------------------------
JUDGE_SYSTEM = """You are a STRICT judge for the magicpin AI Challenge. You score merchant engagement messages.

SCORING DIMENSIONS (0-10 each, be strict - 5 is average, 7+ is good, 9+ is excellent):

1. SPECIFICITY: Does the message have VERIFIABLE facts?
   - Numbers (percentages, counts, prices)
   - Dates/times
   - Source citations
   - Concrete claims vs vague statements

2. CATEGORY FIT: Does the voice match the business type?
   - Dentists: clinical, peer-to-peer, technical OK, use "Dr." prefix
   - Salons: warm, friendly, practical
   - Restaurants: operator-to-operator
   - Gyms: coaching, motivational
   - Pharmacies: trustworthy, precise

3. MERCHANT FIT: Is it personalized to THIS merchant?
   - Uses their name/owner name correctly
   - References their actual data (not fabricated)
   - Honors language preference

4. TRIGGER RELEVANCE: Does it connect to WHY NOW?
   - Clear reason for this specific message
   - Uses data from the trigger payload
   - Not a generic nudge

5. ENGAGEMENT COMPULSION: Would they reply?
   - Loss aversion, curiosity, social proof
   - Clear CTA
   - Low friction ask

PENALTIES:
- Fabricating data not in context: -2
- Exposing internal jargon to merchant: -1

RESPOND ONLY WITH THIS EXACT JSON FORMAT:
{
  "specificity": <0-10>,
  "specificity_reason": "<why this score, 1-2 sentences>",
  "category_fit": <0-10>,
  "category_fit_reason": "<why this score>",
  "merchant_fit": <0-10>,
  "merchant_fit_reason": "<why this score>",
  "decision_quality": <0-10>,
  "decision_quality_reason": "<why this score>",
  "engagement_compulsion": <0-10>,
  "engagement_reason": "<why this score>",
  "hint": "<one sentence guidance for improvement, cryptic not direct>"
}"""


class ScoreRequest(BaseModel):
    body: str
    category: dict[str, Any] = {}
    merchant: dict[str, Any] = {}
    trigger:  dict[str, Any] = {}
    customer: dict[str, Any] | None = None
    cta:      str = ""
    send_as:  str = "vera"


class ScoreResponse(BaseModel):
    specificity:           float
    category_fit:          float
    merchant_fit:          float
    decision_quality:      float
    engagement_compulsion: float
    total:                 float
    penalties:             float
    adjusted_total:        float
    feedback: dict[str, str]
    reasons:  dict[str, str]
    hint:     str


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "model": MODEL}


@app.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest):
    body     = req.body
    category = req.category
    merchant = req.merchant
    trigger  = req.trigger
    customer = req.customer

    ident   = merchant.get("identity", {})
    perf    = merchant.get("performance", {})
    offers  = [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"]
    signals = merchant.get("signals", [])

    user_prompt = f"""SCORE THIS MESSAGE:

=== CONTEXT PROVIDED TO BOT ===
Category: {category.get('slug', category.get('category_slug', 'unknown'))}
Voice: {category.get('voice', {}).get('tone', 'unknown')}
Taboos: {category.get('voice', {}).get('vocab_taboo', [])[:5]}

Merchant: {ident.get('name', 'unknown')}
Owner: {ident.get('owner_first_name', 'unknown')}
Locality: {ident.get('locality', 'unknown')}
Languages: {ident.get('languages', [])}
Performance: views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, ctr={perf.get('ctr', '?')}
Signals: {signals}
Active Offers: {offers}

Trigger Kind: {trigger.get('kind', 'unknown')}
Trigger Payload: {json.dumps(trigger.get('payload', {}), ensure_ascii=False)}
Trigger Urgency: {trigger.get('urgency', '?')}

Customer: {json.dumps(customer.get('identity', {}) if customer else None, ensure_ascii=False)}

=== BOT'S MESSAGE ===
Body ({len(body)} chars): "{body}"
CTA: {req.cta or 'none'}
Send As: {req.send_as}

Score each dimension 0-10 with clear reasoning. Be STRICT."""

    wait_times = [10, 20]
    raw: dict = {}

    for attempt, wait in enumerate(wait_times):
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":       MODEL,
                        "temperature": 0,
                        "max_tokens":  700,
                        "messages": [
                            {"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user",   "content": user_prompt},
                        ],
                    },
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", wait))
                    import asyncio; await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                text  = resp.json()["choices"][0]["message"]["content"]
                match = re.search(r"\{[\s\S]*\}", text)
                if match:
                    raw = json.loads(match.group())
                    break
        except Exception as e:
            print(f"[score_server] attempt {attempt+1} error: {e}")
            if attempt < len(wait_times) - 1:
                import asyncio; await asyncio.sleep(wait)

    def g(key: str, default: float = 5.0) -> float:
        v = raw.get(key, default)
        try:
            return float(min(10, max(0, v)))
        except Exception:
            return default

    sp  = g("specificity")
    cf  = g("category_fit")
    mf  = g("merchant_fit")
    dq  = g("decision_quality")
    ec  = g("engagement_compulsion")
    tot = sp + cf + mf + dq + ec
    pen = 0.0
    adj = tot + pen

    return ScoreResponse(
        specificity=sp,
        category_fit=cf,
        merchant_fit=mf,
        decision_quality=dq,
        engagement_compulsion=ec,
        total=tot,
        penalties=pen,
        adjusted_total=adj,
        feedback={
            "strongest": raw.get("hint", ""),
            "weakest":   "",
            "fix":       raw.get("hint", ""),
        },
        reasons={
            "specificity":           raw.get("specificity_reason", ""),
            "category_fit":          raw.get("category_fit_reason", ""),
            "merchant_fit":          raw.get("merchant_fit_reason", ""),
            "decision_quality":      raw.get("decision_quality_reason", ""),
            "engagement_compulsion": raw.get("engagement_reason", ""),
        },
        hint=raw.get("hint", ""),
    )


if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set in .env")
        sys.exit(1)
    print(f"[score_server] Starting on http://localhost:8090")
    print(f"[score_server] Model: {MODEL}")
    uvicorn.run("score_server:app", host="0.0.0.0", port=8090, reload=False)
