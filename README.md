# Vera AI Bot — magicpin AI Challenge

## Overview

Vera is an AI growth assistant for Indian local business merchants. It receives merchant context, customer data, and trigger signals from the magicpin harness, then composes hyper-personalised WhatsApp messages via a stateful FastAPI server backed by a 2-tier LLM pipeline.

---

## Final Score Results

Evaluated across 5 categories × multiple triggers using the same judge rubric as the real harness:

| Category | Decision Quality | Specificity | Category Fit | Merchant Fit | Engagement Compulsion | Total |
|---|---|---|---|---|---|---|
| Dentists | 9.0 | 9.0 | 9.0 | 8.4 | 8.2 | **43.6 / 50** |
| Salons | 9.0 | 9.0 | 9.0 | 8.2 | 7.2 | **42.5 / 50** |
| Restaurants | 9.0 | 9.0 | 8.5 | 8.5 | 7.0 | **41.5 / 50** |
| Gyms | 9.0 | 9.0 | 8.5 | 8.2 | 7.8 | **42.5 / 50** |
| Pharmacies | 8.8 | 9.0 | 9.0 | 8.2 | 7.0 | **42.0 / 50** |
| **OVERALL** | **9.0** | **9.0** | **8.8** | **8.3** | **7.5** | **42.6 / 50 (85%)** |

> Grade: **GOOD — Ready to deploy**

---

## Architecture

### LLM Pipeline (2-Tier with Round-Robin)

```
Incoming trigger
      │
      ▼
extract_facts()          ← deterministic, no hallucination risk
      │
      ▼
build_user_prompt()      ← scenario framing + mandatory merchant-fit rules
      │
      ▼
 ┌────┴────┐
 │  Groq   │  llama-3.3-70b-versatile  (key1 → key2 round-robin on 429)
 └────┬────┘
      │ fail/429
      ▼
 ┌────┴────┐
 │ Gemini  │  gemini-2.5-flash  (uncorrelated vendor fallback)
 └────┬────┘
      │ fail
      ▼
build_smart_fallback()   ← locality-aware deterministic fallback
      │
      ▼
Post-LLM validators:
  ensure_minimum_numbers()   ← guarantees ≥3 numeric facts
  ensure_merchant_fit()      ← injects locality + offer if missing
  ensure_citation()          ← appends source for research/regulation triggers
      │
      ▼
Final composed message
```

### Scenario Coverage

`scenario_map.py` defines explicit strategies for all **24 trigger kinds** — zero generic fallbacks:

| Trigger Kind | Scope | CTA Style | Compulsion Lever |
|---|---|---|---|
| `research_digest` | merchant | open_ended | authority_social_proof |
| `recall_due` | customer | binary_yes_no | loss_aversion |
| `perf_dip` | merchant | binary_yes_no | loss_aversion |
| `regulation_change` | merchant | open_ended | authority_deadline |
| `competitor_opened` | merchant | binary_yes_no | fear_of_loss |
| `festival_upcoming` | merchant | binary_yes_no | urgency_scarcity |
| `wedding_package_followup` | customer | binary_yes_no | urgency_days_countdown |
| `winback_eligible` | merchant | binary_yes_no | loss_aversion |
| `ipl_match_today` | merchant | binary_yes_no | urgency_scarcity |
| `customer_lapsed_hard` | customer | binary_yes_no | loss_aversion |
| `dormant_with_vera` | merchant | binary_yes_no | curiosity_gap |
| … and 13 more | — | — | — |

---

## Key Changes & Improvements

### 1. Enhanced Fact Extraction (`composer.py` — `extract_facts`)

**Problem:** Customer relationship data was shallow; trigger payload keys were buried in a raw JSON blob making it hard for the LLM to use them.

**Fix:**
- Unpacked trigger payload keys into named `payload_*` facts (e.g. `payload_days_to_wedding`, `payload_wedding_date`) using each scenario's `payload_keys` config
- Added `customer_ltv`, `customer_preferred_svc`, `customer_age_band` to customer context
- Added `_payload_block()` helper to surface these as labelled lines in the prompt instead of a raw JSON dump

```python
# Before
"trigger_payload": payload  # raw JSON blob

# After — each key surfaced individually
"payload_days_to_wedding": 21
"payload_wedding_date": "2026-11-15"
"payload_trial_completed": True
```

---

### 2. Mandatory Merchant-Fit Rules in Prompt (`composer.py` — `build_user_prompt`)

**Problem:** The LLM would sometimes produce generic messages that only swapped the owner name, scoring ≤6 on Merchant Fit.

**Fix:** Added an explicit enforcement block in every user prompt:

```
=== MANDATORY MERCHANT-FIT RULES (checked by judge) ===
Your message MUST include ALL THREE or merchant_fit is capped at 6:
  1. Locality: mention "{locality}" or "{city}" by name
  2. Offer: name at least one active offer with its exact price
  3. Metric: use at least one real number (views, calls, CTR, lapsed count)
Messages that only swap the owner name score ≤6.
```

**Impact:** Merchant Fit improved from **7.8 → 8.3** average across all categories.

---

### 3. `ensure_merchant_fit()` Post-Processor (`composer.py`)

**Problem:** Even with prompt instructions, rare LLM outputs still omitted locality or offer — no safety net existed.

**Fix:** New post-processing function that runs after every LLM response:

```python
def ensure_merchant_fit(result, facts):
    # Checks if locality/city appears in body
    # Checks if at least one active offer name appears in body
    # If either missing — injects them after the first sentence
```

This is a **zero-miss guarantee** — every message that leaves the composer contains the merchant's locality and at least one offer name, regardless of LLM behaviour.

---

### 4. Locality-Aware Smart Fallback (`composer.py` — `build_smart_fallback`)

**Problem:** When both LLM tiers fail, the fallback body was generic: `"Meera, aapki listing pe 2410 views..."` — no locality, scored low on Merchant Fit.

**Fix:** Fallback now always includes locality:

```python
# Before
"Meera, aapki listing pe 2410 views aaye is mahine."

# After
"Meera, aapki Lajpat Nagar, Delhi ki listing pe 2410 views aaye is mahine."
```

---

### 5. Dual Groq Key Round-Robin (`composer.py` — `_call_groq`)

**Problem:** Single Groq API key limited to 12,000 tokens/minute — bulk test runs hit 429 rate limits mid-suite.

**Fix:** Added `GROQ_API_KEY_2` support with automatic failover:

```python
# On 429 from key1 → instantly retries with key2 (no wait)
# Doubles effective token budget: 12k → 24k tokens/minute
```

The judge in `score_tester.py` also uses the same round-robin across both keys.

---

### 6. Judge Rate-Limit Cap (`score_tester.py`)

**Problem:** Groq's `retry-after` header sometimes returned 1800+ seconds — the score tester would block for 30 minutes mid-run.

**Fix:** Capped the wait at 65 seconds maximum per attempt; skips scoring that message and moves on if still rate-limited after 2 attempts.

---

## File Structure

```
vera-bot/
├── bot.py              # FastAPI server — 6 endpoints
├── composer.py         # Full composition pipeline + LLM calls + post-processors
├── prompts.py          # COMPOSE_SYSTEM prompt with 5-dimension scoring rubric
├── reply_handler.py    # Replay-compliant reply routing (intent-commit, hostile, auto)
├── scenario_map.py     # 24 trigger kind → framing/CTA/compulsion strategy map
├── store.py            # In-memory context/conversation/suppression store
├── score_tester.py     # Local 5-dimension evaluation harness
├── requirements.txt
├── Dockerfile          # For Fly.io deployment
├── fly.toml            # Fly.io app config (region: bom — Mumbai)
├── Procfile            # For Render deployment
├── render.yaml         # Render service config
└── .env.example        # Environment variable template
```

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/healthz` | Liveness probe |
| GET | `/v1/metadata` | Bot identity |
| POST | `/v1/context` | Receive merchant/customer/category context |
| POST | `/v1/tick` | Periodic wake-up — proactive message composition |
| POST | `/v1/reply` | Handle merchant/customer replies |
| POST | `/v1/teardown` | Reset all in-memory state |

---

## Local Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your keys in .env (never edit .env.example with real keys)
uvicorn bot:app --host 0.0.0.0 --port 8080
```

Run the local score evaluation:
```bash
python score_tester.py
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ | Groq API key — primary LLM (get from console.groq.com) |
| `GROQ_API_KEY_2` | Optional | Second Groq key from different account — doubles token budget |
| `LLM_MODEL` | Optional | Groq model name (default: `llama-3.3-70b-versatile`) |
| `GEMINI_API_KEY` | Optional | Gemini fallback key (get from aistudio.google.com) |
| `GEMINI_MODEL` | Optional | Gemini model name (default: `gemini-2.5-flash`) |

> **Security:** Never put real API keys in `.env.example`. Always use the `.env` file which is gitignored.

---

## Deploy to Fly.io

```bash
# 1. Install flyctl
powershell -ExecutionPolicy ByPass -c "irm https://fly.io/install.ps1 | iex"

# 2. Login
fly auth login

# 3. Launch (one time)
fly launch --name vera-magicpin-bot --region bom --no-deploy

# 4. Set secrets
fly secrets set \
  GROQ_API_KEY="your_key" \
  GROQ_API_KEY_2="your_key2" \
  LLM_MODEL="llama-3.3-70b-versatile" \
  GEMINI_API_KEY="your_gemini_key" \
  GEMINI_MODEL="gemini-2.5-flash"

# 5. Deploy
fly deploy

# 6. Verify
curl https://vera-magicpin-bot.fly.dev/v1/healthz
```

---

## Scoring Dimensions

| Dimension | What it measures | How Vera addresses it |
|---|---|---|
| **Decision Quality** | Strongest signal chosen per trigger | Explicit `framing` per trigger kind in `SCENARIO_MAP`; payload keys unpacked as named facts |
| **Specificity** | ≥3 real numbers/dates/sources | `ensure_minimum_numbers()` post-processor guarantees this |
| **Category Fit** | Correct voice per business type | `prompts.py` category voice rules; taboo word enforcement |
| **Merchant Fit** | Locality, offers, performance metrics in message | Mandatory prompt rules + `ensure_merchant_fit()` post-processor |
| **Engagement Compulsion** | Single binary CTA as last sentence | `forced_cta` from scenario config; reply handler enforces binary paths |
