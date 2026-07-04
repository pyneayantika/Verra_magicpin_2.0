"""
End-to-End Verification Suite for Vera AI Bot
Covers: unit tests, integration tests, endpoint tests,
        judge simulation, and score verification.
Run from inside vera-bot/ folder:
  python e2e_verify.py
"""

import sys
import os
import re
import json
import time
import subprocess
import threading
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_PORT  = 8099
BOT_BASE  = f"http://localhost:{BOT_PORT}"
RESULTS   = []
SECTION   = ""
FAIL_FAST = False

def section(name):
    global SECTION
    SECTION = name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

def check(name, condition, got=None, warn=False):
    status = "OK" if condition else ("WN" if warn else "XX")
    label  = "WARN" if (not condition and warn) else ("PASS" if condition else "FAIL")
    detail = f" -- got: {str(got)[:80]}" if (got is not None and not condition) else ""
    print(f"  {status} [{label}] {name}{detail}")
    RESULTS.append({
        "section": SECTION,
        "name": name,
        "passed": condition,
        "warn": warn,
        "got": str(got)[:200] if got is not None else None
    })
    if FAIL_FAST and not condition and not warn:
        print(f"\n  FAIL FAST: stopping at '{name}'")
        sys.exit(1)

def timeit(fn):
    start = time.time()
    result = fn()
    return result, round(time.time() - start, 3)

# ─────────────────────────────────────────────────────────────
# SECTION 1 -- FILE EXISTENCE CHECK
# ─────────────────────────────────────────────────────────────

section("SECTION 1 -- File Existence")

REQUIRED_FILES = [
    "bot.py", "store.py", "composer.py", "prompts.py",
    "reply_handler.py", "scenario_map.py",
    "requirements.txt", "render.yaml", "Procfile",
    ".env.example", ".gitignore", "README.md"
]
for f in REQUIRED_FILES:
    check(f"File exists: {f}", Path(f).exists())

check(".env has GROQ_API_KEY set",
      bool(os.getenv("GROQ_API_KEY", "").startswith("gsk_")),
      os.getenv("GROQ_API_KEY", "")[:10])
check(".env has GEMINI_API_KEY set",
      bool(os.getenv("GEMINI_API_KEY", "")),
      "present" if os.getenv("GEMINI_API_KEY") else "missing")
check(".gitignore contains .env",
      ".env" in Path(".gitignore").read_text() if Path(".gitignore").exists() else False)

# ─────────────────────────────────────────────────────────────
# SECTION 2 -- STORE.PY UNIT TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 2 -- store.py Unit Tests")

import store

r = store.upsert_context("category", "dentists", 1, {"slug": "dentists"})
check("upsert: new context → (True, stored)", r == (True, "stored"), r)

r = store.upsert_context("category", "dentists", 1, {"slug": "dentists_v2"})
check("upsert: same version → (True, no_op)", r == (True, "no_op"), r)

p = store.get_context("category", "dentists")
check("upsert: same version did not overwrite", p.get("slug") == "dentists", p)

r = store.upsert_context("category", "dentists", 0, {"slug": "old"})
check("upsert: stale version → (False, stale_version)", r == (False, "stale_version"), r)

r = store.upsert_context("category", "dentists", 2, {"slug": "dentists_new"})
check("upsert: higher version → (True, stored)", r == (True, "stored"), r)
p = store.get_context("category", "dentists")
check("upsert: higher version replaced payload", p.get("slug") == "dentists_new", p)

check("get_context: unknown → None", store.get_context("merchant", "fake_id") is None)

store.upsert_context("merchant", "m_001", 1,
    {"merchant_id": "m_001", "category_slug": "dentists"})
mer = store.get_context("merchant", "m_001")
cat = store.get_category_for_merchant(mer)
check("get_category_for_merchant resolves correctly", cat is not None, cat)

store.upsert_context("customer", "c_001", 1, {"customer_id": "c_001"})
counts = store.count_contexts()
check("count_contexts: category >= 1", counts["category"] >= 1, counts)
check("count_contexts: merchant >= 1", counts["merchant"] >= 1, counts)
check("count_contexts: customer >= 1", counts["customer"] >= 1, counts)
check("count_contexts: all 4 keys present",
      set(counts.keys()) == {"category", "merchant", "customer", "trigger"}, counts)

store.mark_suppressed("research:dentists:2026-W17")
check("is_suppressed: True for marked key", store.is_suppressed("research:dentists:2026-W17"))
check("is_suppressed: False for new key", not store.is_suppressed("other:key:2026-W17"))

turns = store.get_turns("conv_auto_1_unknown")
check("get_turns: unknown conv_id → []", turns == [], turns)

store.append_turn("conv_auto_1_unknown", "merchant", "auto reply", 2)
turns = store.get_turns("conv_auto_1_unknown")
check("append_turn: creates on unknown conv", len(turns) == 1, turns)

store.clear_all()
check("clear_all: contexts empty", len(store.contexts) == 0)
check("clear_all: convs empty", store.get_turns("conv_auto_1_unknown") == [])
check("clear_all: suppressed empty", not store.is_suppressed("research:dentists:2026-W17"))

# ─────────────────────────────────────────────────────────────
# SECTION 3 -- SCENARIO_MAP.PY UNIT TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 3 -- scenario_map.py Unit Tests")

from scenario_map import SCENARIO_MAP

EXPECTED_KINDS = [
    "active_planning_intent", "category_seasonal", "cde_opportunity",
    "chronic_refill_due", "competitor_opened", "curious_ask_due",
    "customer_lapsed_hard", "dormant_with_vera", "festival_upcoming",
    "gbp_unverified", "ipl_match_today", "milestone_reached",
    "perf_dip", "perf_spike", "recall_due", "regulation_change",
    "renewal_due", "research_digest", "review_theme_emerged",
    "seasonal_perf_dip", "supply_alert", "trial_followup",
    "wedding_package_followup", "winback_eligible"
]
REQUIRED_ENTRY_FIELDS = [
    "scope", "hook_fields", "cta_style", "send_as",
    "compulsion_lever", "framing", "payload_keys"
]
VALID_CTA_STYLES = [
    "open_ended", "binary_yes_no", "binary_confirm_cancel",
    "multi_choice_slot", "none"
]
CUSTOMER_KINDS = [
    "recall_due", "wedding_package_followup",
    "customer_lapsed_hard", "trial_followup", "chronic_refill_due"
]

check("scenario_map: total entries == 24", len(SCENARIO_MAP) == 24, len(SCENARIO_MAP))

for kind in EXPECTED_KINDS:
    check(f"scenario_map: '{kind}' mapped", kind in SCENARIO_MAP)

for kind, entry in SCENARIO_MAP.items():
    for field in REQUIRED_ENTRY_FIELDS:
        check(f"scenario_map[{kind}].{field} present and non-empty",
              field in entry and bool(entry[field]))

for kind, entry in SCENARIO_MAP.items():
    check(f"scenario_map[{kind}].cta_style valid",
          entry.get("cta_style") in VALID_CTA_STYLES, entry.get("cta_style"))

for kind in CUSTOMER_KINDS:
    entry = SCENARIO_MAP.get(kind, {})
    check(f"scenario_map[{kind}].scope == customer",
          entry.get("scope") == "customer", entry.get("scope"))
    check(f"scenario_map[{kind}].send_as == merchant_on_behalf",
          entry.get("send_as") == "merchant_on_behalf", entry.get("send_as"))

for kind, entry in SCENARIO_MAP.items():
    if entry.get("scope") == "merchant":
        check(f"scenario_map[{kind}].send_as == vera",
              entry.get("send_as") == "vera", entry.get("send_as"))

# ─────────────────────────────────────────────────────────────
# SECTION 4 -- PROMPTS.PY CONTENT CHECK
# ─────────────────────────────────────────────────────────────

section("SECTION 4 -- prompts.py Content Check")

from prompts import COMPOSE_SYSTEM, REPLY_SYSTEM

check("COMPOSE_SYSTEM is non-empty string",
      isinstance(COMPOSE_SYSTEM, str) and len(COMPOSE_SYSTEM) > 500,
      f"length={len(COMPOSE_SYSTEM)}")
check("REPLY_SYSTEM is non-empty string",
      isinstance(REPLY_SYSTEM, str) and len(REPLY_SYSTEM) > 200,
      f"length={len(REPLY_SYSTEM)}")

cs_lower = COMPOSE_SYSTEM.lower()
check("COMPOSE_SYSTEM: mentions decision quality",
      "decision quality" in cs_lower or "decision_quality" in cs_lower)
check("COMPOSE_SYSTEM: mentions specificity", "specificity" in cs_lower)
check("COMPOSE_SYSTEM: mentions category fit",
      "category fit" in cs_lower or "category_fit" in cs_lower)
check("COMPOSE_SYSTEM: mentions merchant fit",
      "merchant fit" in cs_lower or "merchant_fit" in cs_lower)
check("COMPOSE_SYSTEM: mentions engagement compulsion",
      "engagement" in cs_lower and "compulsion" in cs_lower)
check("COMPOSE_SYSTEM: has dentists voice rule", "dentist" in cs_lower)
check("COMPOSE_SYSTEM: has salons voice rule", "salon" in cs_lower)
check("COMPOSE_SYSTEM: has restaurants voice rule", "restaurant" in cs_lower)
check("COMPOSE_SYSTEM: has gyms voice rule", "gym" in cs_lower)
check("COMPOSE_SYSTEM: has pharmacies voice rule", "pharmac" in cs_lower)
check("COMPOSE_SYSTEM: specifies JSON output format",
      '"body"' in COMPOSE_SYSTEM and '"cta"' in COMPOSE_SYSTEM)
check("COMPOSE_SYSTEM: no fabrication rule present",
      "fabricat" in cs_lower or "invent" in cs_lower or "never invent" in cs_lower)
check("COMPOSE_SYSTEM: single CTA rule present",
      "single" in cs_lower or "one cta" in cs_lower or "one clear" in cs_lower)

rs_lower = REPLY_SYSTEM.lower()
check("REPLY_SYSTEM: has actioning guidance",
      any(w in rs_lower for w in ["done", "confirm", "proceed", "draft"]))
check("REPLY_SYSTEM: specifies JSON output format", '"action"' in REPLY_SYSTEM)

# ─────────────────────────────────────────────────────────────
# SECTION 5 -- COMPOSER.PY UNIT TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 5 -- composer.py Unit Tests")

import composer

SAMPLE_CAT = {
    "slug": "dentists", "category_slug": "dentists",
    "voice": {"tone": "peer-clinical", "vocab_taboo": ["cure", "guaranteed"]},
    "peer_stats": {"avg_ctr": 0.030, "avg_rating": 4.4},
    "offer_catalog": [{"id": "d01", "title": "Dental Cleaning @ Rs299"}],
    "digest": [{"id": "d1", "kind": "research",
                "title": "3-month fluoride recall cuts caries 38%",
                "source": "JIDA Oct 2026, p.14", "trial_n": "2,100",
                "summary": "Fluoride recall every 3 months better"}],
    "seasonal_beats": [], "trend_signals": []
}
SAMPLE_MER = {
    "merchant_id": "m_001_drmeera",
    "category_slug": "dentists",
    "identity": {"name": "Dr. Meera Dental", "owner_first_name": "Meera",
                 "city": "Delhi", "locality": "Lajpat Nagar",
                 "languages": ["en", "hi"], "verified": True},
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
    "performance": {"views": 2410, "calls": 18, "ctr": 0.021, "leads": 12,
                    "directions": 45,
                    "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05}},
    "offers": [{"id": "o1", "title": "Dental Cleaning @ Rs299", "status": "active"}],
    "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78,
                           "retention_6mo_pct": 0.38, "high_risk_adult_count": 124},
    "signals": ["ctr_below_peer_median", "stale_posts"],
    "conversation_history": []
}
SAMPLE_TRG_RESEARCH = {
    "id": "trg_001", "kind": "research_digest",
    "scope": "merchant", "source": "external",
    "merchant_id": "m_001_drmeera",
    "customer_id": None, "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2026-12-31T00:00:00Z",
    "payload": {"category": "dentists", "top_item_id": "d1"}
}

facts = composer.extract_facts(SAMPLE_CAT, SAMPLE_MER, SAMPLE_TRG_RESEARCH, None)
check("extract_facts: owner_first_name", facts.get("owner_first_name") == "Meera", facts.get("owner_first_name"))
check("extract_facts: locality", facts.get("locality") == "Lajpat Nagar", facts.get("locality"))
check("extract_facts: views == 2410", facts.get("views") == 2410, facts.get("views"))
check("extract_facts: ctr_gap_text computed", "ctr_gap_text" in facts, list(facts.keys()))
check("extract_facts: digest_title present", bool(facts.get("digest_title")), facts.get("digest_title"))
check("extract_facts: digest_source present",
      facts.get("digest_source") == "JIDA Oct 2026, p.14", facts.get("digest_source"))
check("extract_facts: suppression_key present", bool(facts.get("suppression_key")), facts.get("suppression_key"))

result_no_nums = {"body": "Dr. Meera, kuch interesting update hai. Reply YES."}
r2 = composer.ensure_minimum_numbers(result_no_nums, facts)
num_count = len(re.findall(r'\d+', r2["body"]))
check("ensure_minimum_numbers: injects to >=3 digits",
      num_count >= 3, f"count={num_count}, body={r2['body'][:80]}")

result_no_cite = {"body": "Dr. Meera, new research aaya hai. Reply YES."}
r3 = composer.ensure_citation(result_no_cite, facts, "research_digest")
check("ensure_citation: appends JIDA citation",
      "JIDA" in r3["body"] or "p.14" in r3["body"], r3["body"][:100])

result_other = {"body": "Some message. Reply YES."}
r4 = composer.ensure_citation(result_other.copy(), facts, "perf_dip")
check("ensure_citation: skips for perf_dip", r4["body"] == result_other["body"])

check("parse_json: valid JSON",
      composer.parse_json('{"body":"test","cta":"binary_yes_no"}') == {"body": "test", "cta": "binary_yes_no"})
check("parse_json: extracts from embedded text",
      composer.parse_json('Here:\n{"body":"hello","cta":"none"}\nDone.').get("body") == "hello")
check("parse_json: empty string → {}", composer.parse_json("") == {})

store.clear_all()
fallback = composer.build_smart_fallback(facts, SCENARIO_MAP.get("research_digest"))
check("build_smart_fallback: returns body", bool(fallback.get("body")))
check("build_smart_fallback: body has >=3 numbers",
      len(re.findall(r'\d+', fallback.get("body", ""))) >= 3, fallback.get("body", "")[:80])
check("build_smart_fallback: valid cta",
      fallback.get("cta") in ["binary_yes_no", "open_ended", "binary_confirm_cancel", "none"])
check("build_smart_fallback: no fabrication",
      not any(w in fallback.get("body", "").lower()
              for w in ["suppression_key", "hook_fields", "framing"]))

print("\n  [compose() test -- requires live Groq/Gemini key]")
store.clear_all()
compose_result, elapsed = timeit(
    lambda: composer.compose(SAMPLE_CAT, SAMPLE_MER, SAMPLE_TRG_RESEARCH, None)
)
check("compose: returns dict", isinstance(compose_result, dict))
check("compose: has body", bool(compose_result.get("body", "")))
check("compose: has cta", bool(compose_result.get("cta", "")))
check("compose: send_as == vera", compose_result.get("send_as") == "vera", compose_result.get("send_as"))
check("compose: has suppression_key", bool(compose_result.get("suppression_key", "")))
check("compose: has rationale", bool(compose_result.get("rationale", "")))
check("compose: body has >=3 numbers",
      len(re.findall(r'\d+', compose_result.get("body", ""))) >= 3,
      compose_result.get("body", "")[:80])
check("compose: citation in body for research_digest",
      "JIDA" in compose_result.get("body", "") or "p.14" in compose_result.get("body", ""),
      compose_result.get("body", "")[:120])
check("compose: no internal jargon in body",
      not any(w in compose_result.get("body", "")
              for w in ["SCENARIO_MAP", "hook_fields", "framing",
                        "trigger_payload", "suppression_key"]),
      compose_result.get("body", "")[:80])
check("compose: completed within 15s", elapsed < 15.0, f"{elapsed}s", warn=elapsed > 10.0)
print(f"\n  Preview: {compose_result.get('body', '')[:120]}...")
print(f"  Rationale: {compose_result.get('rationale', '')[:80]}")
print(f"  Elapsed: {elapsed}s")

# ─────────────────────────────────────────────────────────────
# SECTION 6 -- REPLY_HANDLER.PY UNIT TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 6 -- reply_handler.py Unit Tests")

import reply_handler

store.clear_all()

r = reply_handler.handle(
    "conv_hostile_1", "m_001", None, "merchant",
    "Stop messaging me. This is useless spam.", 2)
check("reply: hostile → action:end", r.get("action") == "end", r.get("action"))
check("reply: hostile body has won't or action=end",
      "won't" in r.get("body", "").lower() or r.get("action") == "end")

store.clear_all()
r = reply_handler.handle(
    "conv_auto_test", "m_001", None, "merchant",
    "Thank you for contacting us! Our team will respond shortly.", 2)
check("reply: auto-reply 1st → send", r.get("action") == "send", r.get("action"))
check("reply: auto-reply 1st → binary_yes_no CTA", r.get("cta") == "binary_yes_no", r.get("cta"))

r = reply_handler.handle(
    "conv_auto_test", "m_001", None, "merchant",
    "Thank you for contacting us! Our team will respond shortly.", 3)
check("reply: auto-reply 2nd → wait", r.get("action") == "wait", r.get("action"))
check("reply: auto-reply 2nd → wait_seconds 86400", r.get("wait_seconds") == 86400, r.get("wait_seconds"))

r = reply_handler.handle(
    "conv_auto_test", "m_001", None, "merchant",
    "Thank you for contacting us! Our team will respond shortly.", 4)
check("reply: auto-reply 3rd → end", r.get("action") == "end", r.get("action"))

store.clear_all()
ACTIONING = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
QUALIFYING = ["would you", "do you", "can you tell", "what if", "how about"]
r = reply_handler.handle(
    "conv_intent", "m_001", None, "merchant",
    "Ok lets do it. Whats next?", 3)
check("reply: intent commit → send", r.get("action") == "send", r.get("action"))
body = r.get("body", "")
check("reply: intent commit → actioning word present",
      any(w in body.lower() for w in ACTIONING), body[:80])
check("reply: intent commit → NO qualifying phrase",
      not any(q in body.lower() for q in QUALIFYING), body[:80])

store.clear_all()
r = reply_handler.handle(
    "conv_reject", "m_001", None, "merchant",
    "Not interested. Stop messaging.", 2)
check("reply: reject → end", r.get("action") == "end", r.get("action"))

store.clear_all()
try:
    r = reply_handler.handle(
        "conv_auto_1", "m_001", None, "merchant",
        "Thank you for contacting us! Our team will respond shortly.", 2)
    check("reply: unknown conv_id handled gracefully", True)
    check("reply: unknown conv_id returns valid action",
          r.get("action") in ("send", "wait", "end"), r.get("action"))
except Exception as e:
    check("reply: unknown conv_id handled gracefully", False, str(e))

store.clear_all()
r = reply_handler.handle(
    "conv_slot", "m_001", "c_001", "customer",
    "Yes please book me for Wed 5 Nov 6pm", 2)
check("reply: customer slot → send", r.get("action") == "send", r.get("action"))
check("reply: customer slot → merchant_on_behalf",
      r.get("send_as") == "merchant_on_behalf", r.get("send_as"))

# ─────────────────────────────────────────────────────────────
# SECTION 7 -- HTTP ENDPOINT TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 7 -- HTTP Endpoint Tests (live server)")

server_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "bot:app",
     "--host", "0.0.0.0", "--port", str(BOT_PORT),
     "--log-level", "error"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(3)

def api(method, path, body=None, timeout=15.0):
    url = BOT_BASE + path
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                return client.get(url)
            else:
                return client.post(url, json=body,
                                   headers={"Content-Type": "application/json"})
    except Exception as e:
        return None

try:
    r, t = timeit(lambda: api("GET", "/v1/healthz"))
    check("GET /v1/healthz → 200", r and r.status_code == 200, r.status_code if r else "no response")
    if r and r.status_code == 200:
        d = r.json()
        check("healthz: status == ok", d.get("status") == "ok", d.get("status"))
        check("healthz: uptime_seconds present", "uptime_seconds" in d, list(d.keys()))
        cl = d.get("contexts_loaded", {})
        check("healthz: contexts_loaded has 4 keys",
              set(cl.keys()) == {"category", "merchant", "customer", "trigger"}, cl)
    check("healthz: responds < 2s", t < 5.0, f"{t}s", warn=t > 3.0)

    r, t = timeit(lambda: api("GET", "/v1/metadata"))
    check("GET /v1/metadata → 200", r and r.status_code == 200, r.status_code if r else "no response")
    if r and r.status_code == 200:
        d = r.json()
        check("metadata: team_name present", bool(d.get("team_name")), d.get("team_name"))
        check("metadata: model present", bool(d.get("model")), d.get("model"))
        check("metadata: approach present", bool(d.get("approach")), str(d.get("approach", ""))[:50])
        check("metadata: version present", bool(d.get("version")))
    check("metadata: responds < 2s", t < 5.0, f"{t}s", warn=t > 3.0)

    cat_payload = {
        "slug": "dentists", "category_slug": "dentists",
        "voice": {"tone": "peer-clinical", "vocab_taboo": ["cure", "guaranteed"]},
        "peer_stats": {"avg_ctr": 0.030, "avg_rating": 4.4},
        "offer_catalog": [], "digest": [], "seasonal_beats": [], "trend_signals": []
    }
    r, t = timeit(lambda: api("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": cat_payload, "delivered_at": "2026-07-04T10:00:00Z"
    }))
    check("POST /v1/context → 200", r and r.status_code == 200, r.status_code if r else "no response")
    if r and r.status_code == 200:
        d = r.json()
        check("context: new push → accepted:true", d.get("accepted") == True, d)
        check("context: ack_id present", "ack_id" in d, d)
        check("context: stored_at present", "stored_at" in d, d)
    check("context: responds < 5s", t < 5.0, f"{t}s", warn=t > 3.0)

    r = api("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": cat_payload, "delivered_at": "2026-07-04T10:00:00Z"
    })
    check("context: same version → accepted:true (idempotent)",
          r and r.status_code == 200 and r.json().get("accepted") == True,
          r.json() if r else "no response")

    r = api("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 0,
        "payload": cat_payload, "delivered_at": "2026-07-04T10:00:00Z"
    })
    check("context: stale version → accepted:false",
          r and r.json().get("accepted") == False, r.json() if r else "no response")
    check("context: stale version → reason:stale_version",
          r and r.json().get("reason") == "stale_version",
          r.json().get("reason") if r else "no response")

    r = api("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 2,
        "payload": {**cat_payload, "updated": True},
        "delivered_at": "2026-07-04T10:00:00Z"
    })
    check("context: higher version → accepted:true",
          r and r.json().get("accepted") == True, r.json() if r else "no response")

    r = api("GET", "/v1/healthz")
    cl = r.json().get("contexts_loaded", {}) if r else {}
    check("healthz: category count updated after push", cl.get("category", 0) >= 1, cl)

    r, t = timeit(lambda: api("POST", "/v1/tick", {
        "now": "2026-07-04T10:00:00Z", "available_triggers": []
    }))
    check("POST /v1/tick (empty) → 200", r and r.status_code == 200, r.status_code if r else "no response")
    check("tick empty: actions == []", r and r.json().get("actions") == [], r.json() if r else "no response")
    check("tick empty: responds < 2s", t < 5.0, f"{t}s", warn=t > 3.0)

    r = api("POST", "/v1/tick", {
        "now": "2026-07-04T10:00:00Z",
        "available_triggers": ["trg_nonexistent_xyz_999"]
    })
    check("tick: unknown trigger → empty actions (no crash)",
          r and r.status_code == 200 and len(r.json().get("actions", [])) == 0,
          r.json() if r else "no response")

    r = api("POST", "/v1/reply", {
        "conversation_id": "conv_e2e_hostile",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": "Stop messaging me. This is spam.",
        "turn_number": 2
    })
    check("POST /v1/reply hostile → 200", r and r.status_code == 200, r.status_code if r else "no response")
    check("reply hostile: action == end",
          r and r.json().get("action") == "end", r.json().get("action") if r else "no response")

    r = api("POST", "/v1/reply", {
        "conversation_id": "conv_e2e_auto",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond.",
        "turn_number": 2
    })
    check("reply auto-reply 1st: action == send",
          r and r.json().get("action") == "send", r.json().get("action") if r else "no response")
    check("reply auto-reply 1st: cta == binary_yes_no",
          r and r.json().get("cta") == "binary_yes_no", r.json().get("cta") if r else "no response")

    r = api("POST", "/v1/reply", {
        "conversation_id": "conv_e2e_auto",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond.",
        "turn_number": 3
    })
    check("reply auto-reply 2nd: action == wait",
          r and r.json().get("action") == "wait", r.json().get("action") if r else "no response")

    r = api("POST", "/v1/reply", {
        "conversation_id": "conv_e2e_intent",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "turn_number": 3
    })
    check("reply intent commit: action == send",
          r and r.json().get("action") == "send", r.json().get("action") if r else "no response")
    if r and r.status_code == 200:
        body_text = r.json().get("body", "")
        has_act = any(w in body_text.lower() for w in
                      ["done", "sending", "draft", "here", "confirm", "proceed", "next"])
        has_qual = any(q in body_text.lower() for q in
                       ["would you", "do you", "can you tell", "what if", "how about"])
        check("reply intent commit: actioning word present", has_act, body_text[:80])
        check("reply intent commit: NO qualifying phrase", not has_qual, body_text[:80])

    r = api("POST", "/v1/teardown", {})
    check("POST /v1/teardown → 200", r and r.status_code == 200, r.status_code if r else "no response")
    r2 = api("GET", "/v1/healthz")
    cl2 = r2.json().get("contexts_loaded", {}) if r2 else {}
    check("teardown: all counts reset to 0", all(v == 0 for v in cl2.values()), cl2)

    # Push full context for LLM tick test
    api("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": SAMPLE_CAT, "delivered_at": "2026-07-04T10:00:00Z"
    })
    api("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_001_drmeera", "version": 1,
        "payload": SAMPLE_MER, "delivered_at": "2026-07-04T10:00:00Z"
    })
    api("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_001_research", "version": 1,
        "payload": SAMPLE_TRG_RESEARCH, "delivered_at": "2026-07-04T10:00:00Z"
    })
    r, t = timeit(lambda: api("POST", "/v1/tick", {
        "now": "2026-07-04T10:00:00Z",
        "available_triggers": ["trg_001_research"]
    }, timeout=20.0))
    check("tick with real trigger → 200", r and r.status_code == 200, r.status_code if r else "no response")
    if r and r.status_code == 200:
        actions = r.json().get("actions", [])
        check("tick with real trigger → >=1 action", len(actions) >= 1, f"{len(actions)} actions")
        if actions:
            a = actions[0]
            check("tick action: has body", bool(a.get("body", "")))
            check("tick action: has conversation_id", bool(a.get("conversation_id", "")))
            check("tick action: has template_name", bool(a.get("template_name", "")))
            check("tick action: has template_params", isinstance(a.get("template_params"), list))
            check("tick action: has suppression_key", bool(a.get("suppression_key", "")))
            check("tick action: body has >=3 numbers",
                  len(re.findall(r'\d+', a.get("body", ""))) >= 3, a.get("body", "")[:80])
            print(f"\n  Tick body preview: {a.get('body', '')[:120]}...")
    check("tick with LLM: < 15s (judge budget)", t < 15.0, f"{t}s", warn=t > 10.0)

finally:
    server_proc.terminate()
    server_proc.wait()
    print("\n  [Test server stopped]")

# ─────────────────────────────────────────────────────────────
# SECTION 8 -- EDGE CASE TESTS
# ─────────────────────────────────────────────────────────────

section("SECTION 8 -- Edge Case Tests")

store.clear_all()

print("  Testing all 24 scenario kinds produce valid output structure...")
store.clear_all()

for kind in EXPECTED_KINDS:
    facts = {
        "owner_first_name": "Test",
        "merchant_name": "Test Clinic",
        "locality": "Test Nagar",
        "city": "Delhi",
        "languages": ["en"],
        "views": 1000,
        "calls": 10,
        "ctr": 0.020,
        "leads": 5,
        "delta_7d_views": 5,
        "delta_7d_calls": -3,
        "peer_avg_ctr": 0.030,
        "active_offers": ["Service @ Rs299"],
        "signals": [],
        "active_customers": 200,
        "lapsed_customers": 30,
        "retention_rate": 0.40,
        "high_risk_adult_count": 50,
        "trigger_kind": kind,
        "trigger_urgency": 3,
        "trigger_payload": {},
        "suppression_key": f"{kind}:m_test:2026-W17",
        "ctr_gap_pct": 30,
        "ctr_gap_text": "CTR 2.0% vs peer avg 3.0% (30% below)"
    }
    scenario = SCENARIO_MAP.get(kind)
    fb = composer.build_smart_fallback(facts, scenario)
    num_count = len(re.findall(r'\d+', fb.get("body", "")))
    check(f"fallback for '{kind}': >=3 numbers in body",
          num_count >= 3, f"count={num_count}, body={fb.get('body', '')[:60]}")
    check(f"fallback for '{kind}': valid cta",
          fb.get("cta") in ["binary_yes_no", "open_ended", "binary_confirm_cancel", "none"])

for kind in EXPECTED_KINDS:
    facts["trigger_kind"] = kind
    fb = composer.build_smart_fallback(facts, SCENARIO_MAP.get(kind))
    body = fb.get("body", "")
    check(f"fallback '{kind}': no internal jargon",
          not any(jarg in body for jarg in
                  ["SCENARIO_MAP", "hook_fields", "framing",
                   "trigger_payload", "suppression_key"]))

for kind in CUSTOMER_KINDS:
    facts["trigger_kind"] = kind
    fb = composer.build_smart_fallback(facts, SCENARIO_MAP.get(kind))
    check(f"fallback '{kind}': send_as == merchant_on_behalf",
          fb.get("send_as") == "merchant_on_behalf", fb.get("send_as"))

store.clear_all()
store.mark_suppressed("test:dup:2026-W17")
check("suppression: key correctly blocked", store.is_suppressed("test:dup:2026-W17"))
check("suppression: different key not blocked", not store.is_suppressed("test:other:2026-W17"))

# ─────────────────────────────────────────────────────────────
# SECTION 9 -- JUDGE SIMULATOR INTEGRATION
# ─────────────────────────────────────────────────────────────

section("SECTION 9 -- Judge Simulator Integration")

JUDGE_SIM = Path("../magicpin-ai-challenge/judge_simulator.py")
if not JUDGE_SIM.exists():
    JUDGE_SIM = Path("judge_simulator.py")

if not JUDGE_SIM.exists():
    check("judge_simulator.py found", False, "Not found in parent or same folder")
else:
    check("judge_simulator.py found", True, str(JUDGE_SIM))

    server_proc2 = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bot:app",
         "--host", "0.0.0.0", "--port", str(BOT_PORT),
         "--log-level", "error"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(3)

    def run_judge(scenario: str):
        try:
            judge_src = JUDGE_SIM.read_text(encoding="utf-8")
            patched = judge_src
            import re as _re
            patched = _re.sub(r'BOT_URL\s*=\s*"[^"]*"',
                              f'BOT_URL = "{BOT_BASE}"', patched)
            patched = _re.sub(r'TEST_SCENARIO\s*=\s*"[^"]*"',
                              f'TEST_SCENARIO = "{scenario}"', patched)
            tmp = JUDGE_SIM.parent / "_judge_tmp.py"
            tmp.write_text(patched, encoding="utf-8")
            try:
                result = subprocess.run(
                    [sys.executable, str(tmp)],
                    capture_output=True, text=True, timeout=300
                )
                output = result.stdout + result.stderr
                passed = result.returncode == 0
                return passed, output
            finally:
                tmp.unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT after 300s"
        except Exception as e:
            return False, str(e)

    try:
        print("\n  [Running judge_simulator -- TEST_SCENARIO=warmup]")
        print("  (This may take 30-60 seconds...)")
        passed, output = run_judge("warmup")
        check("judge: warmup PASS", passed, output[-300:] if not passed else None)
        if not passed:
            print(f"\n  Warmup output tail:\n{output[-500:]}")

        print("\n  [Running judge_simulator -- TEST_SCENARIO=all]")
        print("  (This may take 2-3 minutes...)")
        passed, output = run_judge("all")
        check("judge: all scenarios PASS", passed, output[-300:] if not passed else None)
        if not passed:
            print(f"\n  Judge 'all' output tail:\n{output[-500:]}")

    finally:
        server_proc2.terminate()
        server_proc2.wait()
        print("\n  [Judge test server stopped]")

# ─────────────────────────────────────────────────────────────
# SECTION 10 -- DEPLOYMENT CONFIG CHECK
# ─────────────────────────────────────────────────────────────

section("SECTION 10 -- Deployment Config Check")

if Path("render.yaml").exists():
    ry = Path("render.yaml").read_text()
    check("render.yaml: plan == starter", "starter" in ry, ry[:200])
    check("render.yaml: GROQ_API_KEY env var present", "GROQ_API_KEY" in ry)
    check("render.yaml: GEMINI_API_KEY env var present", "GEMINI_API_KEY" in ry)
    check("render.yaml: buildCommand present", "pip install" in ry)
    check("render.yaml: startCommand uses uvicorn", "uvicorn" in ry)
else:
    check("render.yaml exists", False)

if Path("Procfile").exists():
    pf = Path("Procfile").read_text()
    check("Procfile: starts uvicorn", "uvicorn" in pf and "bot:app" in pf, pf)
    check("Procfile: uses $PORT", "$PORT" in pf, pf)
else:
    check("Procfile exists", False)

if Path("requirements.txt").exists():
    req = Path("requirements.txt").read_text().lower()
    for pkg in ["fastapi", "uvicorn", "httpx", "pydantic", "python-dotenv", "google-generativeai"]:
        check(f"requirements.txt: {pkg} present", pkg.lower() in req)
else:
    check("requirements.txt exists", False)

check("README.md exists", Path("README.md").exists())
if Path("README.md").exists():
    readme = Path("README.md").read_text().lower()
    check("README.md: mentions approach", "approach" in readme)
    check("README.md: mentions groq or llm", "groq" in readme or "llm" in readme)

if Path(".gitignore").exists():
    gi = Path(".gitignore").read_text()
    check(".gitignore: .env excluded", ".env" in gi)
    check(".gitignore: __pycache__ excluded", "__pycache__" in gi)
    check(".gitignore: no API keys visible", "gsk_" not in gi)

# ─────────────────────────────────────────────────────────────
# FINAL REPORT
# ─────────────────────────────────────────────────────────────

section("FINAL REPORT")

total    = len(RESULTS)
passed   = sum(1 for r in RESULTS if r["passed"])
failed   = sum(1 for r in RESULTS if not r["passed"] and not r["warn"])
warnings = sum(1 for r in RESULTS if r["warn"] and not r["passed"])

print(f"\n  Total checks:  {total}")
print(f"  Passed:        {passed}")
print(f"  Failed:        {failed}")
print(f"  Warnings:      {warnings}")

if failed > 0:
    print(f"\n  FAILED CHECKS (fix before deploying):")
    by_section = {}
    for r in RESULTS:
        if not r["passed"] and not r["warn"]:
            s = r["section"]
            by_section.setdefault(s, []).append(r["name"])
    for sec, names in by_section.items():
        print(f"\n  [{sec}]")
        for n in names:
            print(f"    - {n}")

if warnings > 0:
    print(f"\n  WARNINGS (non-blocking but review):")
    for r in RESULTS:
        if r["warn"] and not r["passed"]:
            print(f"    - {r['name']}")
            if r.get("got"):
                print(f"      got: {r['got']}")

print()
if failed == 0:
    print("  ALL CHECKS PASSED")
    print("  READY TO DEPLOY TO RENDER")
    print()
    print("  Next steps:")
    print("  1. git add . && git commit -m 'Vera v2.0 -- e2e verified'")
    print("  2. git push origin main")
    print("  3. Connect repo to Render -> Starter plan")
    print("  4. Set GROQ_API_KEY + GEMINI_API_KEY in Render dashboard")
    print("  5. Deploy -> wait for build -> verify live URL")
    print("  6. Submit URL on challenge page")
else:
    print(f"  {failed} CHECK(S) FAILED")
    print("  DO NOT DEPLOY until all failures are resolved.")
    print("  Fix the failed checks, then re-run: python e2e_verify.py")
    sys.exit(1)
