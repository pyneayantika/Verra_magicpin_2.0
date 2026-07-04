"""
score_tester.py — Vera Bot 5-Dimension Score Tester

Loads real category JSONs from dataset/, pairs them with realistic
merchant/trigger/customer data, calls compose(), then scores each
message with Groq as the AI judge on all 5 dimensions.

Run from inside vera-bot/:
    python score_tester.py

Takes ~8-12 minutes (22 compose+score pairs, 5s pause each).
"""

import os
import json
import re
import time
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
import store
import composer
from scenario_map import SCENARIO_MAP

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")
GROQ_JUDGE_KEYS = [k for k in [GROQ_API_KEY, GROQ_API_KEY_2] if k]
_judge_key_idx  = 0
MODEL          = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# Path to real category JSONs (relative to this file)
DATASET_DIR = Path(__file__).resolve().parent.parent / "magicpin-ai-challenge" / "dataset"

# ─────────────────────────────────────────────────────────────────────
# JUDGE SYSTEM PROMPT
# Exact same rubric as the real judge (extracted from judge_simulator.py)
# ─────────────────────────────────────────────────────────────────────

JUDGE_SYSTEM = """
You are the official AI judge for the magicpin Vera AI Challenge.
Score a WhatsApp message on exactly 5 dimensions.

SCORING SCALE: 0-10 per dimension. Be strict.
  5 = average/acceptable
  7 = good, clearly above average
  9 = excellent, near-perfect for this dimension
  10 = perfect, could not be improved

=== DIMENSION 1 -- DECISION QUALITY (0-10) ===
Did the bot combine trigger + merchant state + category fit
before deciding what to write?
  9-10: Perfect signal selection -- ONE best fact chosen, all 3
        inputs (trigger + merchant state + category) clearly combined
  7-8:  Two of three inputs used well
  5-6:  Only trigger used, merchant context mostly ignored
  3-4:  Generic message, no visible signal reasoning
  0-2:  Completely irrelevant to the trigger

=== DIMENSION 2 -- SPECIFICITY (0-10) ===
Does the message use real numbers, dates, offers, or local facts
from the given context?
  9-10: 3+ concrete verifiable facts (numbers, price, source
        citation, date, locality name) -- all traceable to context
  7-8:  2 specific facts used correctly
  5-6:  1 specific fact, rest is vague
  3-4:  Pure generic ("increase your sales", "customers are searching")
  0-2:  Fabricated data not in context -- PENALTY

=== DIMENSION 3 -- CATEGORY FIT (0-10) ===
Does the tone, vocabulary, and framing match the business type?
  DENTISTS expected: peer-clinical, technical terms (fluoride,
    caries, recall), source citations (JIDA, DCI, IDA)
  SALONS expected: warm-practical, visual, trend-aware, aspirational
  RESTAURANTS expected: operator-to-operator, fast, event-driven,
    covers/AOV focused
  GYMS expected: coach energy, retention-focused, data-backed,
    no guilt-shaming
  PHARMACIES expected: trustworthy-precise, molecule names OK,
    compliance-safe, utility-first

  9-10: Unmistakably right category voice -- no ambiguity
  7-8:  Mostly right tone, minor mismatch
  5-6:  Neutral tone, could be any business
  3-4:  Wrong tone for this category
  0-2:  Taboo word used (cure/guaranteed for dentist, etc.)

=== DIMENSION 4 -- MERCHANT FIT (0-10) ===
Is this message personalized to THIS specific merchant?
Could this same message (with only the name changed) be sent to
a different merchant in the same category?
  9-10: References owner name + locality + specific metric +
        active offer -- unusable for any other merchant
  7-8:  Name + one specific data point
  5-6:  Name only, otherwise generic
  3-4:  No personalization at all
  0-2:  Wrong data used (fabricated or from wrong merchant)

=== DIMENSION 5 -- ENGAGEMENT COMPULSION (0-10) ===
Does the message give one strong reason to reply NOW, with a
low-effort next action?
  9-10: Clear compulsion lever (loss aversion, social proof,
        effort externalization, curiosity, urgency) + binary CTA
        as the LAST sentence + replies in under 10 seconds of effort
  7-8:  Good compulsion, CTA present but not perfectly placed
  5-6:  Weak compulsion, CTA buried or unclear
  3-4:  No compulsion lever, vague ask
  0-2:  Multiple CTAs or no CTA at all

=== PENALTIES (deduct from total AFTER summing) ===
  Fabricated data not in context:       -2 per instance
  Internal jargon in body (hook_fields, SCENARIO_MAP, etc.): -1
  Multiple CTAs in one message:          -2

=== OUTPUT FORMAT ===
Return ONLY valid JSON. No markdown. No explanation.
{
  "decision_quality": <0-10>,
  "specificity": <0-10>,
  "category_fit": <0-10>,
  "merchant_fit": <0-10>,
  "engagement_compulsion": <0-10>,
  "total": <sum of 5 dimensions, before penalties>,
  "penalties": <0 or negative integer>,
  "adjusted_total": <total + penalties>,
  "feedback": {
    "strongest": "one sentence: best thing this message did",
    "weakest": "one sentence: single biggest problem",
    "fix": "one sentence: exact change that would raise lowest score"
  }
}
"""

# ─────────────────────────────────────────────────────────────────────
# CATEGORY -> TRIGGER TEST MATRIX
# ─────────────────────────────────────────────────────────────────────

CATEGORY_TEST_MATRIX = {
    "dentists": [
        "research_digest",
        "recall_due",
        "perf_dip",
        "regulation_change",
        "competitor_opened",
    ],
    "salons": [
        "festival_upcoming",
        "wedding_package_followup",
        "curious_ask_due",
        "winback_eligible",
    ],
    "restaurants": [
        "ipl_match_today",
        "active_planning_intent",
        "review_theme_emerged",
        "milestone_reached",
    ],
    "gyms": [
        "seasonal_perf_dip",
        "customer_lapsed_hard",
        "perf_spike",
        "dormant_with_vera",
        "trial_followup",
    ],
    "pharmacies": [
        "supply_alert",
        "chronic_refill_due",
        "category_seasonal",
        "gbp_unverified",
    ],
}

# ─────────────────────────────────────────────────────────────────────
# LOAD CATEGORY JSONS FROM DATASET (falls back to inline if missing)
# ─────────────────────────────────────────────────────────────────────

def _load_category_json(slug: str) -> dict:
    """Load category JSON from dataset/categories/, merge with voice keys."""
    cat_path = DATASET_DIR / "categories" / f"{slug}.json"
    if cat_path.exists():
        with open(cat_path, encoding="utf-8") as f:
            data = json.load(f)
        # Normalise: ensure category_slug key present
        data.setdefault("category_slug", data.get("slug", slug))
        # Normalise voice sub-keys used by composer
        voice = data.get("voice", {})
        voice.setdefault("vocab_taboo", [])
        voice.setdefault("vocab_allowed", [])
        return data
    print(f"  [warn] dataset not found for {slug}, using inline sample")
    return _INLINE_CATEGORIES.get(slug, {})


# Inline fallback categories (used only if dataset folder unreachable)
_INLINE_CATEGORIES = {
    "dentists": {
        "slug": "dentists", "category_slug": "dentists",
        "voice": {
            "tone": "peer-clinical",
            "vocab_taboo": ["cure", "guaranteed", "100% safe"],
            "vocab_allowed": ["fluoride", "caries", "recall", "bruxism"],
        },
        "peer_stats": {"avg_ctr": 0.030, "avg_rating": 4.4, "avg_review_count": 62},
        "offer_catalog": [{"id": "d01", "title": "Dental Cleaning @ Rs299"}],
        "digest": [{
            "id": "dig1", "kind": "research",
            "title": "3-month fluoride recall cuts caries recurrence 38%",
            "source": "JIDA Oct 2026, p.14", "trial_n": 2100,
            "summary": "High-risk adults benefit from 3-month vs 6-month recall",
        }],
        "seasonal_beats": [], "trend_signals": [],
    },
    "salons": {
        "slug": "salons", "category_slug": "salons",
        "voice": {
            "tone": "warm-practical",
            "vocab_taboo": ["clinical", "treatment procedure"],
            "vocab_allowed": ["glow", "bridal", "festive", "trend"],
        },
        "peer_stats": {"avg_ctr": 0.028, "avg_rating": 4.3, "avg_review_count": 48},
        "offer_catalog": [{"id": "s01", "title": "Bridal Package @ Rs2,499"}],
        "digest": [], "seasonal_beats": [], "trend_signals": [],
    },
    "restaurants": {
        "slug": "restaurants", "category_slug": "restaurants",
        "voice": {
            "tone": "operator-fast",
            "vocab_taboo": ["delicious", "yummy"],
            "vocab_allowed": ["covers", "AOV", "delivery mix"],
        },
        "peer_stats": {"avg_ctr": 0.031, "avg_rating": 4.1, "avg_review_count": 89},
        "offer_catalog": [{"id": "r01", "title": "Lunch Thali @ Rs149"}],
        "digest": [], "seasonal_beats": [], "trend_signals": [],
    },
    "gyms": {
        "slug": "gyms", "category_slug": "gyms",
        "voice": {
            "tone": "coach-motivational",
            "vocab_taboo": ["lazy", "fat", "overweight"],
            "vocab_allowed": ["retention", "comeback", "streak"],
        },
        "peer_stats": {"avg_ctr": 0.027, "avg_rating": 4.2, "avg_review_count": 71},
        "offer_catalog": [{"id": "g01", "title": "30-Day Trial @ Rs999"}],
        "digest": [], "seasonal_beats": [], "trend_signals": [],
    },
    "pharmacies": {
        "slug": "pharmacies", "category_slug": "pharmacies",
        "voice": {
            "tone": "trustworthy-precise",
            "vocab_taboo": ["cure", "miracle"],
            "vocab_allowed": ["Metformin", "refill", "compliance"],
        },
        "peer_stats": {"avg_ctr": 0.038, "avg_rating": 4.6, "avg_review_count": 44},
        "offer_catalog": [{"id": "p01", "title": "Monthly BP Monitoring @ Rs199"}],
        "digest": [], "seasonal_beats": [], "trend_signals": [],
    },
}

# ─────────────────────────────────────────────────────────────────────
# SAMPLE MERCHANTS (one per category)
# ─────────────────────────────────────────────────────────────────────

SAMPLE_MERCHANTS = {
    "dentists": {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": {
            "name": "Dr. Meera's Dental Clinic",
            "owner_first_name": "Meera",
            "city": "Delhi",
            "locality": "Lajpat Nagar",
            "languages": ["en", "hi"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
        "performance": {
            "views": 2410, "calls": 18, "ctr": 0.021,
            "leads": 12, "directions": 45,
            "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05},
        },
        "offers": [
            {"id": "den01", "title": "Dental Cleaning @ Rs299", "status": "active"},
            {"id": "den02", "title": "X-Ray @ Rs150",            "status": "active"},
        ],
        "customer_aggregate": {
            "total_unique_ytd": 540,
            "lapsed_180d_plus": 78,
            "retention_6mo_pct": 0.38,
            "high_risk_adult_count": 124,
        },
        "signals": ["ctr_below_peer_median", "stale_posts:22d", "high_risk_adult_cohort"],
        "conversation_history": [],
    },
    "salons": {
        "merchant_id": "m_002_studio11_salon_mumbai",
        "category_slug": "salons",
        "identity": {
            "name": "Studio 11 Salon",
            "owner_first_name": "Anita",
            "city": "Mumbai",
            "locality": "Karol Bagh",
            "languages": ["en", "hi"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Basic", "days_remaining": 45},
        "performance": {
            "views": 1820, "calls": 24, "ctr": 0.033,
            "leads": 19, "directions": 31,
            "delta_7d": {"views_pct": 0.28, "calls_pct": 0.12},
        },
        "offers": [
            {"id": "sal01", "title": "Bridal Glow Package @ Rs2,499", "status": "active"},
            {"id": "sal02", "title": "Festive Hair Spa @ Rs799",       "status": "active"},
        ],
        "customer_aggregate": {
            "total_unique_ytd": 312, "lapsed_180d_plus": 44,
            "retention_6mo_pct": 0.52, "high_risk_adult_count": 0,
        },
        "signals": ["views_spike_28pct", "festival_season_active"],
        "conversation_history": [],
    },
    "restaurants": {
        "merchant_id": "m_003_pizzajunction_restaurant_delhi",
        "category_slug": "restaurants",
        "identity": {
            "name": "Pizza Junction",
            "owner_first_name": "Rahul",
            "city": "Delhi",
            "locality": "Sector 14 Gurgaon",
            "languages": ["en"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 120},
        "performance": {
            "views": 3140, "calls": 41, "ctr": 0.029,
            "leads": 28, "directions": 67,
            "delta_7d": {"views_pct": -0.08, "calls_pct": -0.12},
        },
        "offers": [
            {"id": "res01", "title": "Lunch Thali @ Rs149",    "status": "active"},
            {"id": "res02", "title": "Family Combo @ Rs599",   "status": "active"},
        ],
        "customer_aggregate": {
            "total_unique_ytd": 890, "lapsed_180d_plus": 134,
            "retention_6mo_pct": 0.44, "high_risk_adult_count": 0,
        },
        "signals": ["calls_dropped_12pct", "delivery_mix_high"],
        "conversation_history": [],
    },
    "gyms": {
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "category_slug": "gyms",
        "identity": {
            "name": "FitZone Gym",
            "owner_first_name": "Priya",
            "city": "Bangalore",
            "locality": "Koramangala",
            "languages": ["en", "kn"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 67},
        "performance": {
            "views": 2890, "calls": 33, "ctr": 0.025,
            "leads": 21, "directions": 58,
            "delta_7d": {"views_pct": -0.22, "calls_pct": -0.31},
        },
        "offers": [
            {"id": "gym01", "title": "30-Day Trial @ Rs999",    "status": "active"},
            {"id": "gym02", "title": "Annual Plan @ Rs8,499",   "status": "active"},
        ],
        "customer_aggregate": {
            "total_unique_ytd": 445, "lapsed_180d_plus": 92,
            "retention_6mo_pct": 0.31, "high_risk_adult_count": 0,
        },
        "signals": ["seasonal_dip_expected", "lapse_rate_high"],
        "conversation_history": [],
    },
    "pharmacies": {
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "category_slug": "pharmacies",
        "identity": {
            "name": "Wellness Pharmacy",
            "owner_first_name": "Suresh",
            "city": "Pune",
            "locality": "Aundh",
            "languages": ["en", "mr"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Basic", "days_remaining": 30},
        "performance": {
            "views": 1240, "calls": 29, "ctr": 0.041,
            "leads": 24, "directions": 18,
            "delta_7d": {"views_pct": 0.05, "calls_pct": 0.08},
        },
        "offers": [
            {"id": "pha01", "title": "Monthly BP Monitoring @ Rs199",  "status": "active"},
            {"id": "pha02", "title": "Senior Citizen 10% Discount",    "status": "active"},
        ],
        "customer_aggregate": {
            "total_unique_ytd": 680, "lapsed_180d_plus": 56,
            "retention_6mo_pct": 0.61, "high_risk_adult_count": 210,
        },
        "signals": ["refill_due_cluster", "high_chronic_patient_base"],
        "conversation_history": [],
    },
}

# ─────────────────────────────────────────────────────────────────────
# SAMPLE TRIGGERS (one per kind)
# ─────────────────────────────────────────────────────────────────────

SAMPLE_TRIGGERS = {
    "research_digest": {
        "id": "trg_research", "kind": "research_digest",
        "scope": "merchant", "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None, "urgency": 2,
        "suppression_key": "research:dentists:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
    },
    "recall_due": {
        "id": "trg_recall", "kind": "recall_due",
        "scope": "customer", "source": "internal",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": "c_priya_001", "urgency": 3,
        "suppression_key": "recall:m_001:c_priya_001",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "service_due": "dental_cleaning",
            "last_service_date": "2026-01-15",
            "due_date": "2026-07-15",
            "available_slots": ["Wed 6 Nov 6pm", "Thu 7 Nov 5pm"],
        },
    },
    "perf_dip": {
        "id": "trg_perf_dip", "kind": "perf_dip",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None, "urgency": 4,
        "suppression_key": "perf_dip:m_001:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {"metric": "calls", "delta_pct": -40, "window": "7d", "vs_baseline": "peer_avg"},
    },
    "regulation_change": {
        "id": "trg_reg", "kind": "regulation_change",
        "scope": "merchant", "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None, "urgency": 5,
        "suppression_key": "reg:m_001:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "category": "dentists",
            "top_item_id": "d_2026W17_dci_radiograph",
            "deadline_iso": "2026-12-15",
        },
    },
    "competitor_opened": {
        "id": "trg_comp", "kind": "competitor_opened",
        "scope": "merchant", "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None, "urgency": 2,
        "suppression_key": "comp:m_001:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "competitor_name": "SmileCare Dental",
            "distance_km": 1.3,
            "their_offer": "Free Consultation",
            "opened_date": "2026-06-28",
        },
    },
    "festival_upcoming": {
        "id": "trg_fest", "kind": "festival_upcoming",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_002_studio11_salon_mumbai",
        "customer_id": None, "urgency": 3,
        "suppression_key": "fest:m_002:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "festival": "Navratri", "date": "2026-10-02",
            "days_until": 14, "category_relevance": "high",
        },
    },
    "wedding_package_followup": {
        "id": "trg_wed", "kind": "wedding_package_followup",
        "scope": "customer", "source": "internal",
        "merchant_id": "m_002_studio11_salon_mumbai",
        "customer_id": "c_bride_001", "urgency": 4,
        "suppression_key": "wed:m_002:c_bride_001",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "wedding_date": "2026-11-15", "days_to_wedding": 21,
            "trial_completed": True, "next_step_window_open": True,
        },
    },
    "curious_ask_due": {
        "id": "trg_ask", "kind": "curious_ask_due",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_002_studio11_salon_mumbai",
        "customer_id": None, "urgency": 1,
        "suppression_key": "ask:m_002:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {"ask_template": "most_requested_service", "last_ask_at": "2026-06-01"},
    },
    "winback_eligible": {
        "id": "trg_win", "kind": "winback_eligible",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_002_studio11_salon_mumbai",
        "customer_id": None, "urgency": 3,
        "suppression_key": "win:m_002:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "days_since_expiry": 45, "perf_dip_pct": 28,
            "lapsed_customers_added_since_expiry": 44,
        },
    },
    "ipl_match_today": {
        "id": "trg_ipl", "kind": "ipl_match_today",
        "scope": "merchant", "source": "external",
        "merchant_id": "m_003_pizzajunction_restaurant_delhi",
        "customer_id": None, "urgency": 5,
        "suppression_key": "ipl:m_003:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "match": "MI vs CSK", "venue": "Wankhede",
            "city": "Mumbai", "match_time_iso": "2026-07-04T19:30:00Z",
            "is_weeknight": False,
        },
    },
    "active_planning_intent": {
        "id": "trg_plan", "kind": "active_planning_intent",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_003_pizzajunction_restaurant_delhi",
        "customer_id": None, "urgency": 4,
        "suppression_key": "plan:m_003:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "intent_topic": "corporate_lunch_package",
            "merchant_last_message": "Haan, corporate lunch ke liye package banana chahta hoon",
        },
    },
    "review_theme_emerged": {
        "id": "trg_rev", "kind": "review_theme_emerged",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_003_pizzajunction_restaurant_delhi",
        "customer_id": None, "urgency": 3,
        "suppression_key": "rev:m_003:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "theme": "slow_delivery", "occurrences_30d": 18,
            "trend": "rising", "common_quote": "delivery took 45 mins",
        },
    },
    "milestone_reached": {
        "id": "trg_mile", "kind": "milestone_reached",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_003_pizzajunction_restaurant_delhi",
        "customer_id": None, "urgency": 2,
        "suppression_key": "mile:m_003:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {"metric": "reviews", "value_now": 98, "milestone_value": 100, "is_imminent": True},
    },
    "seasonal_perf_dip": {
        "id": "trg_seas", "kind": "seasonal_perf_dip",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "customer_id": None, "urgency": 3,
        "suppression_key": "seas:m_004:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "metric": "footfall", "delta_pct": -31, "window": "30d",
            "is_expected_seasonal": True,
            "season_note": "Summer dip -- all Bangalore gyms -25 to -35%",
        },
    },
    "customer_lapsed_hard": {
        "id": "trg_lapse", "kind": "customer_lapsed_hard",
        "scope": "customer", "source": "internal",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "customer_id": "c_raj_001", "urgency": 4,
        "suppression_key": "lapse:m_004:c_raj_001",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "days_since_last_visit": 62,
            "previous_focus": "evening_yoga",
            "previous_membership_months": 8,
        },
    },
    "perf_spike": {
        "id": "trg_spike", "kind": "perf_spike",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "customer_id": None, "urgency": 3,
        "suppression_key": "spike:m_004:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "metric": "views", "delta_pct": 34, "window": "7d",
            "vs_baseline": "own_30d_avg",
            "likely_driver": "new_year_resolution_season",
        },
    },
    "dormant_with_vera": {
        "id": "trg_dorm", "kind": "dormant_with_vera",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "customer_id": None, "urgency": 1,
        "suppression_key": "dorm:m_004:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "days_since_last_merchant_message": 21,
            "last_topic": "summer_offer_campaign",
        },
    },
    "trial_followup": {
        "id": "trg_trial", "kind": "trial_followup",
        "scope": "customer", "source": "internal",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "customer_id": "c_neha_001", "urgency": 4,
        "suppression_key": "trial:m_004:c_neha_001",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "trial_date": "2026-06-28",
            "next_session_options": ["Mon 7 Jul 7am", "Wed 9 Jul 6pm"],
        },
    },
    "supply_alert": {
        "id": "trg_supply", "kind": "supply_alert",
        "scope": "merchant", "source": "external",
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "customer_id": None, "urgency": 5,
        "suppression_key": "supply:m_005:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "alert_id": "CDSCO-2026-07-042",
            "molecule": "Metformin 500mg",
            "affected_batches": ["MF2024B12", "MF2024B13"],
            "manufacturer": "Sun Pharma",
        },
    },
    "chronic_refill_due": {
        "id": "trg_refill", "kind": "chronic_refill_due",
        "scope": "customer", "source": "internal",
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "customer_id": "c_sharma_001", "urgency": 4,
        "suppression_key": "refill:m_005:c_sharma_001",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "molecule_list": ["Metformin 500mg", "Amlodipine 5mg"],
            "last_refill": "2026-06-04",
            "stock_runs_out_iso": "2026-07-10",
            "delivery_address_saved": True,
        },
    },
    "category_seasonal": {
        "id": "trg_catseason", "kind": "category_seasonal",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "customer_id": None, "urgency": 2,
        "suppression_key": "catseason:m_005:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "season": "monsoon",
            "trends": ["ORS", "antifungal", "mosquito repellent"],
            "shelf_action_recommended": "Move ORS + antifungal to front shelf display",
        },
    },
    "gbp_unverified": {
        "id": "trg_gbp", "kind": "gbp_unverified",
        "scope": "merchant", "source": "internal",
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "customer_id": None, "urgency": 2,
        "suppression_key": "gbp:m_005:2026-W17",
        "expires_at": "2026-12-31T00:00:00Z",
        "payload": {
            "verified": False,
            "verification_path": "3 steps via Google app",
            "estimated_uplift_pct": 34,
        },
    },
}

# ─────────────────────────────────────────────────────────────────────
# SAMPLE CUSTOMERS
# ─────────────────────────────────────────────────────────────────────

SAMPLE_CUSTOMERS = {
    "c_priya_001": {
        "customer_id": "c_priya_001",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "identity": {"name": "Priya Sharma", "language_pref": "hindi", "age_group": "30-40"},
        "state": "recall_due",
        "relationship": {"visits_total": 4, "last_visit": "2026-01-15", "avg_spend": 850},
    },
    "c_bride_001": {
        "customer_id": "c_bride_001",
        "merchant_id": "m_002_studio11_salon_mumbai",
        "identity": {"name": "Kavya Mehta", "language_pref": "english", "age_group": "25-30"},
        "state": "pre_wedding",
        "relationship": {"visits_total": 3, "last_visit": "2026-06-20", "avg_spend": 2100},
    },
    "c_raj_001": {
        "customer_id": "c_raj_001",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "identity": {"name": "Raj Kumar", "language_pref": "english", "age_group": "25-35"},
        "state": "lapsed_hard",
        "relationship": {"visits_total": 48, "last_visit": "2026-05-03", "avg_spend": 0},
    },
    "c_neha_001": {
        "customer_id": "c_neha_001",
        "merchant_id": "m_004_fitzone_gym_bangalore",
        "identity": {"name": "Neha Joshi", "language_pref": "english", "age_group": "20-30"},
        "state": "trial_completed",
        "relationship": {"visits_total": 1, "last_visit": "2026-06-28", "avg_spend": 999},
    },
    "c_sharma_001": {
        "customer_id": "c_sharma_001",
        "merchant_id": "m_005_wellness_pharmacy_pune",
        "identity": {"name": "Shyam Sharma", "language_pref": "hindi", "age_group": "60-70"},
        "state": "chronic_active",
        "relationship": {"visits_total": 14, "last_visit": "2026-06-04", "avg_spend": 1200},
    },
}

# ─────────────────────────────────────────────────────────────────────
# GROQ JUDGE SCORING
# ─────────────────────────────────────────────────────────────────────

def score_message(
    body: str,
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None,
) -> dict:
    """Call Groq as judge to score a composed message on all 5 dimensions."""

    identity  = merchant.get("identity", {})
    perf      = merchant.get("performance", {})
    peer      = category.get("peer_stats", {})
    offers    = [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"]
    digest_0  = category.get("digest", [None])[0]

    user_prompt = f"""Score this WhatsApp message:

MESSAGE TO SCORE:
"{body}"

CONTEXT AVAILABLE TO THE BOT WHEN COMPOSING:
  Category:        {category.get("slug")}
  Voice tone:      {category.get("voice", {}).get("tone")}
  Taboo words:     {category.get("voice", {}).get("vocab_taboo")}
  Merchant name:   {identity.get("name")}
  Owner:           {identity.get("owner_first_name")}
  Locality:        {identity.get("locality")}, {identity.get("city")}
  Languages:       {identity.get("languages")}
  Views (30d):     {perf.get("views")}
  Calls (30d):     {perf.get("calls")}
  CTR:             {perf.get("ctr")} (peer avg: {peer.get("avg_ctr")})
  7d view change:  {perf.get("delta_7d", {}).get("views_pct")}
  Active offers:   {offers}
  Lapsed:          {merchant.get("customer_aggregate", {}).get("lapsed_180d_plus")}
  Signals:         {merchant.get("signals", [])}
  Trigger kind:    {trigger.get("kind")}
  Trigger urgency: {trigger.get("urgency")}
  Trigger payload: {json.dumps(trigger.get("payload", {}), ensure_ascii=False)}
  Customer:        {json.dumps({"name": customer.get("identity", {}).get("name"), "language": customer.get("identity", {}).get("language_pref"), "state": customer.get("state")} if customer else None, ensure_ascii=False)}
  Digest item:     {json.dumps({"title": digest_0.get("title"), "source": digest_0.get("source"), "trial_n": digest_0.get("trial_n")} if digest_0 else None, ensure_ascii=False)}

Score all 5 dimensions now. Return ONLY valid JSON."""

    global _judge_key_idx
    MAX_JUDGE_WAIT = 65   # never block longer than this per attempt
    wait_times = [15, 30]
    for attempt, wait in enumerate(wait_times):
        key = GROQ_JUDGE_KEYS[_judge_key_idx % len(GROQ_JUDGE_KEYS)] if GROQ_JUDGE_KEYS else ""
        if not key:
            break
        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "temperature": 0,
                        "max_tokens": 600,
                        "messages": [
                            {"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user",   "content": user_prompt},
                        ],
                    },
                )
                if resp.status_code == 429:
                    ra = min(int(resp.headers.get("retry-after", wait)), MAX_JUDGE_WAIT)
                    _judge_key_idx += 1
                    next_key = GROQ_JUDGE_KEYS[_judge_key_idx % len(GROQ_JUDGE_KEYS)] if GROQ_JUDGE_KEYS else ""
                    if next_key != key:
                        print(f"    [Judge 429] key rate limited — switching to other key")
                        time.sleep(2)
                    else:
                        print(f"    [Judge 429] rate-limited -- waiting {ra}s (capped at {MAX_JUDGE_WAIT}s)...")
                        time.sleep(ra)
                    continue
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                match = re.search(r"\{[\s\S]*\}", text)
                if match:
                    return json.loads(match.group())
                print(f"    [Judge] no JSON found in response: {text[:80]}")
        except Exception as e:
            print(f"    [Judge error attempt {attempt + 1}] {e}")
            if attempt < len(wait_times) - 1:
                time.sleep(wait)
    print(f"    [Judge] giving up after {len(wait_times)} attempts — skipping score")
    return {}

# ─────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────

def bar(score: float, width: int = 20) -> str:
    filled = round(score / 10 * width)
    return "#" * filled + "." * (width - filled)

def grade_label(score: float) -> str:
    if score >= 9:   return "EXCELLENT"
    if score >= 7:   return "GOOD     "
    if score >= 5:   return "AVERAGE  "
    return                   "WEAK     "

# ─────────────────────────────────────────────────────────────────────
# MAIN TEST RUNNER
# ─────────────────────────────────────────────────────────────────────

def run_score_tests() -> dict:
    all_results   = []
    category_avgs = {}

    print("\n" + "=" * 65)
    print("  VERA BOT -- 5-DIMENSION SCORE TESTER")
    print("  Testing all 5 categories across their trigger kinds")
    print("  Scoring: Decision Quality | Specificity | Category Fit")
    print("           Merchant Fit | Engagement Compulsion")
    print("=" * 65)

    for cat_slug, trigger_kinds in CATEGORY_TEST_MATRIX.items():
        print(f"\n{'-' * 65}")
        print(f"  CATEGORY: {cat_slug.upper()}")
        print(f"{'-' * 65}")

        category = _load_category_json(cat_slug)
        merchant = SAMPLE_MERCHANTS[cat_slug]
        cat_scores = []

        for kind in trigger_kinds:
            trigger = SAMPLE_TRIGGERS.get(kind)
            if not trigger:
                print(f"  [warn] No sample trigger for kind: {kind} -- skipping")
                continue

            customer_id = trigger.get("customer_id")
            customer    = SAMPLE_CUSTOMERS.get(customer_id) if customer_id else None

            print(f"\n  [{kind}]")

            # Load context into store for this run
            store.clear_all()
            store.upsert_context("category", cat_slug, 1, category)
            store.upsert_context("merchant", merchant["merchant_id"], 1, merchant)
            store.upsert_context("trigger", trigger["id"], 1, trigger)
            if customer:
                store.upsert_context("customer", customer_id, 1, customer)

            # Compose
            try:
                compose_start = time.time()
                composed = composer.compose(category, merchant, trigger, customer)
                compose_elapsed = round(time.time() - compose_start, 2)
                body = composed.get("body", "")
            except Exception as e:
                print(f"    [FAIL] compose() raised: {e}")
                continue

            if not body:
                print("    [FAIL] compose() returned empty body -- skipping")
                continue

            num_count = len(re.findall(r"\d+", body))
            print(f"    Body ({len(body)} chars, {num_count} numbers, {compose_elapsed}s):")
            preview = body[:130] + ("..." if len(body) > 130 else "")
            print(f"    \"{preview}\"")

            # Rate-limit buffer between compose (Groq) and judge (also Groq)
            time.sleep(6)

            # Judge score
            scores = score_message(body, category, merchant, trigger, customer)
            if not scores:
                print("    [FAIL] Judge scoring failed -- skipping")
                continue

            dq  = float(scores.get("decision_quality",      0))
            sp  = float(scores.get("specificity",           0))
            cf  = float(scores.get("category_fit",          0))
            mf  = float(scores.get("merchant_fit",          0))
            ec  = float(scores.get("engagement_compulsion", 0))
            tot = float(scores.get("total",   dq + sp + cf + mf + ec))
            pen = float(scores.get("penalties", 0))
            adj = float(scores.get("adjusted_total", tot + pen))
            fb  = scores.get("feedback", {})

            print(f"\n    SCORES:")
            print(f"    Decision Quality      [{bar(dq)}] {dq:4.1f}/10  {grade_label(dq)}")
            print(f"    Specificity           [{bar(sp)}] {sp:4.1f}/10  {grade_label(sp)}")
            print(f"    Category Fit          [{bar(cf)}] {cf:4.1f}/10  {grade_label(cf)}")
            print(f"    Merchant Fit          [{bar(mf)}] {mf:4.1f}/10  {grade_label(mf)}")
            print(f"    Engagement Compulsion [{bar(ec)}] {ec:4.1f}/10  {grade_label(ec)}")
            print(f"    {'-' * 50}")
            pen_str = f"  (penalties: {pen:+.0f})" if pen else ""
            print(f"    TOTAL: {tot:.0f}/50{pen_str}  |  ADJUSTED: {adj:.0f}/50")

            if fb:
                print(f"\n    [+] Best:  {fb.get('strongest', '')}")
                print(f"    [-] Issue: {fb.get('weakest', '')}")
                print(f"    [>] Fix:   {fb.get('fix', '')}")

            result = {
                "category": cat_slug, "kind": kind,
                "body": body, "body_len": len(body), "num_count": num_count,
                "decision_quality": dq, "specificity": sp,
                "category_fit": cf, "merchant_fit": mf,
                "engagement_compulsion": ec,
                "total": tot, "penalties": pen,
                "adjusted_total": adj, "feedback": fb,
            }
            all_results.append(result)
            cat_scores.append(result)

            # Pause between pairs to respect Groq rate limits
            time.sleep(7)

        # Per-category averages
        if cat_scores:
            n = len(cat_scores)
            def avg(key): return sum(r[key] for r in cat_scores) / n
            category_avgs[cat_slug] = {
                "decision_quality":      round(avg("decision_quality"),      1),
                "specificity":           round(avg("specificity"),           1),
                "category_fit":          round(avg("category_fit"),          1),
                "merchant_fit":          round(avg("merchant_fit"),          1),
                "engagement_compulsion": round(avg("engagement_compulsion"), 1),
                "total":                 round(avg("adjusted_total"),        1),
                "n": n,
            }

    # ─────────────────────────────────────────────────────────────────
    # FINAL REPORT
    # ─────────────────────────────────────────────────────────────────

    DIMS = [
        ("Decision Quality",      "decision_quality"),
        ("Specificity",           "specificity"),
        ("Category Fit",          "category_fit"),
        ("Merchant Fit",          "merchant_fit"),
        ("Engagement Compulsion", "engagement_compulsion"),
    ]

    print("\n" + "=" * 65)
    print("  FINAL SCORE REPORT -- ALL CATEGORIES")
    print("=" * 65)

    # Header
    dim_short = ["DecQ", "Spec", "CatF", "MerF", "EngC"]
    print(f"\n  {'Category':<15}  " + "  ".join(f"{s:>5}" for s in dim_short) + "  {'Total':>6}  n")
    print(f"  {'-'*15}  " + "  ".join(["-----"] * 5) + "  ------  -")

    for cat_slug, avgs in category_avgs.items():
        vals = [avgs[k] for _, k in DIMS]
        flags = ["^" if v >= 9 else ("~" if v >= 7 else "v") for v in vals]
        row = "  ".join(f"{f}{v:4.1f}" for f, v in zip(flags, vals))
        print(f"  {cat_slug:<15}  {row}  {avgs['total']:6.1f}  {avgs['n']}")

    # Grand total row
    grand_total   = 0.0
    weakest_dim   = None
    weakest_avg   = 10.0

    if all_results:
        n = len(all_results)
        print(f"\n  {'OVERALL AVG':<15}  ", end="")
        for _, key in DIMS:
            avg = sum(r[key] for r in all_results) / n
            grand_total += avg
            flag = "^" if avg >= 9 else ("~" if avg >= 7 else "v")
            print(f"{flag}{avg:4.1f}  ", end="")
            if avg < weakest_avg:
                weakest_avg  = avg
                weakest_dim  = key
        print(f"  {grand_total:5.1f}  {n}")

    # Grade
    pct = grand_total / 50 * 100 if all_results else 0
    if   pct >= 90: grade = "EXCELLENT *** -- Deploy now"
    elif pct >= 80: grade = "GOOD ** -- Ready to deploy"
    elif pct >= 70: grade = "AVERAGE * -- Fix weakest dim first"
    else:           grade = "WEAK -- Significant prompt tuning needed"

    print(f"\n  GRADE:   {grade}")
    print(f"  Overall: {grand_total:.1f}/50 ({pct:.0f}%)")

    # Bottom 3 messages
    if all_results:
        sorted_r = sorted(all_results, key=lambda x: x["adjusted_total"])
        print(f"\n{'-' * 65}")
        print("  BOTTOM 3 MESSAGES (fix these first)")
        print(f"{'-' * 65}")
        for r in sorted_r[:3]:
            print(f"\n  [{r['category']} / {r['kind']}] -- {r['adjusted_total']:.0f}/50")
            print(f"  Body: \"{r['body'][:80]}...\"")
            fb = r.get("feedback", {})
            if fb.get("weakest"):
                print(f"  Issue: {fb['weakest']}")
            if fb.get("fix"):
                print(f"  Fix:   {fb['fix']}")

    # Weakest dimension guidance
    if weakest_dim and all_results:
        FIX_GUIDE = {
            "decision_quality": (
                "Strengthen scenario_map.py framing field for weak trigger kinds. "
                "Each framing must name ONE specific signal to lead with."
            ),
            "specificity": (
                "Verify ensure_minimum_numbers() is injecting correctly. "
                "Check extract_facts() pulls all numeric fields without None values."
            ),
            "category_fit": (
                "Add more category-specific vocabulary to COMPOSE_SYSTEM. "
                "Consider adding a 'do NOT write like this' anti-example per category."
            ),
            "merchant_fit": (
                "Verify owner_first_name + locality + active_offers + signals are "
                "all surfaced in build_user_prompt(). Check for None key paths."
            ),
            "engagement_compulsion": (
                "Ensure CTA is always the LAST sentence. "
                "Add binary CTA enforcement to post-LLM validation in compose()."
            ),
        }
        print(f"\n{'-' * 65}")
        print(f"  WEAKEST DIMENSION: {weakest_dim} (avg {weakest_avg:.1f}/10)")
        print(f"  Fix: {FIX_GUIDE.get(weakest_dim, 'Review prompts.py for this dimension.')}")
        print(f"{'-' * 65}")

    # Save full JSON report
    report = {
        "summary": {
            "total_messages": len(all_results),
            "overall_avg_50": round(grand_total, 2),
            "overall_pct": round(pct, 1),
            "grade": grade,
            "weakest_dimension": weakest_dim,
            "weakest_dimension_avg": round(weakest_avg, 1) if weakest_dim else None,
            "category_averages": category_avgs,
        },
        "messages": all_results,
    }

    out = Path("score_test_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n  Full report saved to: {out.resolve()}")
    print("=" * 65 + "\n")

    return report


if __name__ == "__main__":
    if not GROQ_JUDGE_KEYS:
        print("ERROR: GROQ_API_KEY not set in .env")
        sys.exit(1)
    print(f"  Model (compose): {MODEL}")
    print(f"  Model (judge):   {MODEL}")
    print(f"  Dataset dir:     {DATASET_DIR}")
    print(f"  Categories found: {', '.join(p.stem for p in sorted((DATASET_DIR / 'categories').glob('*.json'))) if (DATASET_DIR / 'categories').exists() else 'using inline fallbacks'}")
    run_score_tests()
